import asyncio
import logging
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from ai_services import ai_moderation_service, moderation_service
from settings import get_settings

logger = logging.getLogger(__name__)

SET_DELAY_VALUE = 1
DEFAULT_EDIT_DELETE_DELAY = 300
DEFAULT_AUTO_DELETE_DELAY = 3600
MIN_DELAY = 1
MAX_DELAY = 86400


class ModerationBot:
    def __init__(self) -> None:
        self.config = get_settings()
        self.application = Application.builder().token(self.config.BOT_TOKEN).build()
        self._delete_tasks: dict[tuple[int, int], asyncio.Task] = {}

    async def _is_admin(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
        try:
            member = await context.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            return member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}
        except TelegramError as exc:
            logger.error("Admin check failed chat=%s user=%s error=%s", chat_id, user_id, exc)
            return False

    def _status_text(self) -> str:
        return (
            "Moderation Status\n\n"
            "Text moderation: ON\n"
            "Image moderation: ON\n"
            f"Edit message delete: ON ({DEFAULT_EDIT_DELETE_DELAY}s)\n"
            f"Auto delete: ON ({DEFAULT_AUTO_DELETE_DELAY}s)\n\n"
            "To change delay use:\n"
            "/setdelay"
        )

    async def _safe_delete_message(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> None:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except RetryAfter as exc:
            logger.warning("Delete rate-limited chat=%s message=%s retry_after=%s", chat_id, message_id, exc.retry_after)
        except (BadRequest, Forbidden, TelegramError) as exc:
            logger.debug("Delete skipped chat=%s message=%s error=%s", chat_id, message_id, exc)
        except Exception as exc:
            logger.error("Unexpected delete error chat=%s message=%s error=%s", chat_id, message_id, exc)

    async def _delete_after_delay(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        message_id: int,
        delay_seconds: int,
    ) -> None:
        task_key = (chat_id, message_id)
        try:
            await asyncio.sleep(max(1, delay_seconds))
            await self._safe_delete_message(context=context, chat_id=chat_id, message_id=message_id)
        except Exception as exc:
            logger.error("Delayed delete task failed chat=%s message=%s error=%s", chat_id, message_id, exc)
        finally:
            self._delete_tasks.pop(task_key, None)

    def _schedule_delete(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        message_id: int,
        delay_seconds: int,
    ) -> None:
        task_key = (chat_id, message_id)
        existing_task = self._delete_tasks.get(task_key)
        if existing_task and not existing_task.done():
            return
        task = asyncio.create_task(self._delete_after_delay(context, chat_id, message_id, delay_seconds))
        self._delete_tasks[task_key] = task

    async def _auto_delete_if_needed(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat = update.effective_chat
        if not message or not chat or chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
            return
        delay = int(context.chat_data.get("auto_delete_delay", DEFAULT_AUTO_DELETE_DELAY))
        self._schedule_delete(context=context, chat_id=chat.id, message_id=message.message_id, delay_seconds=delay)

    async def _delete_unsafe_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat = update.effective_chat
        if not message or not chat:
            return
        await self._safe_delete_message(context=context, chat_id=chat.id, message_id=message.message_id)

    async def _should_skip_for_conversation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        chat = update.effective_chat
        user = update.effective_user
        if not chat or not user or chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
            return True
        awaiting_user = context.chat_data.get("awaiting_delay_user")
        return awaiting_user == user.id

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            chat = update.effective_chat
            user = update.effective_user
            if not chat or not user:
                return

            if chat.type == ChatType.PRIVATE:
                me = await context.bot.get_me()
                keyboard = InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("Add to Group", url=f"https://t.me/{me.username}?startgroup=true")],
                        [InlineKeyboardButton("Support", url=self.config.SUPPORT_CHANNEL_LINK)],
                        [InlineKeyboardButton("Commands & Controls", callback_data="panel")],
                    ]
                )
                text = "Moderation Bot\n\nAI powered protection for Telegram groups.\n\nUse the buttons below."
                await update.effective_message.reply_text(text=text, reply_markup=keyboard)
                return

            if chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}:
                if not await self._is_admin(context=context, chat_id=chat.id, user_id=user.id):
                    await update.effective_message.reply_text("You must be an admin to use this command.")
                    return
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]])
                await update.effective_message.reply_text(self._status_text(), reply_markup=keyboard)
        except Exception as exc:
            logger.error("start_command failed: %s", exc)

    async def panel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            chat = update.effective_chat
            user = update.effective_user
            message = update.effective_message
            if not chat or not user or not message:
                return
            if chat.type in {ChatType.GROUP, ChatType.SUPERGROUP} and not await self._is_admin(context, chat.id, user.id):
                await message.reply_text("You must be an admin to use this command.")
                return
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]])
            await message.reply_text(self._status_text(), reply_markup=keyboard)
        except Exception as exc:
            logger.error("panel_command failed: %s", exc)

    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            query = update.callback_query
            if not query:
                return
            await query.answer()

            chat = query.message.chat if query.message else None
            user = query.from_user
            if not chat or not user:
                return

            data = query.data or ""
            if data not in {"panel", "back"}:
                return

            if chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}:
                if not await self._is_admin(context=context, chat_id=chat.id, user_id=user.id):
                    return

            if data == "panel":
                text = self._status_text()
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]])
            elif chat.type == ChatType.PRIVATE:
                me = await context.bot.get_me()
                text = "Moderation Bot\n\nAI powered protection for Telegram groups.\n\nUse the buttons below."
                keyboard = InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("Add to Group", url=f"https://t.me/{me.username}?startgroup=true")],
                        [InlineKeyboardButton("Support", url=self.config.SUPPORT_CHANNEL_LINK)],
                        [InlineKeyboardButton("Commands & Controls", callback_data="panel")],
                    ]
                )
            else:
                text = self._status_text()
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]])

            try:
                await query.edit_message_text(text=text, reply_markup=keyboard)
            except BadRequest as exc:
                if "Message is not modified" in str(exc):
                    return
                if "message to edit not found" in str(exc).lower():
                    return
                logger.error("Callback edit failed: %s", exc)
            except TelegramError as exc:
                logger.error("Callback edit telegram error: %s", exc)
        except Exception as exc:
            logger.error("on_callback failed: %s", exc)

    async def setdelay_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        try:
            chat = update.effective_chat
            user = update.effective_user
            message = update.effective_message
            if not chat or not user or not message:
                return ConversationHandler.END
            if chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
                await message.reply_text("You must be an admin to use this command.")
                return ConversationHandler.END
            if not await self._is_admin(context=context, chat_id=chat.id, user_id=user.id):
                await message.reply_text("You must be an admin to use this command.")
                return ConversationHandler.END
            context.chat_data["awaiting_delay_user"] = user.id
            await message.reply_text("Send new delay in seconds.\nRange: 1 - 86400")
            return SET_DELAY_VALUE
        except Exception as exc:
            logger.error("setdelay_start failed: %s", exc)
            return ConversationHandler.END

    async def setdelay_receive(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        try:
            chat = update.effective_chat
            user = update.effective_user
            message = update.effective_message
            if not chat or not user or not message:
                context.chat_data.pop("awaiting_delay_user", None)
                return ConversationHandler.END

            awaiting_user = context.chat_data.get("awaiting_delay_user")
            if awaiting_user != user.id:
                return SET_DELAY_VALUE

            raw = (message.text or "").strip()
            if not raw.isdigit():
                await message.reply_text("Invalid value. Send number between 1 and 86400.")
                return SET_DELAY_VALUE

            value = int(raw)
            if value < MIN_DELAY or value > MAX_DELAY:
                await message.reply_text("Invalid value. Send number between 1 and 86400.")
                return SET_DELAY_VALUE

            context.chat_data["auto_delete_delay"] = value
            context.chat_data.pop("awaiting_delay_user", None)
            await message.reply_text(f"Delay updated to {value} seconds.")
            return ConversationHandler.END
        except Exception as exc:
            logger.error("setdelay_receive failed: %s", exc)
            context.chat_data.pop("awaiting_delay_user", None)
            return ConversationHandler.END

    async def setdelay_timeout(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        try:
            context.chat_data.pop("awaiting_delay_user", None)
            if update.effective_message:
                await update.effective_message.reply_text("Delay update timed out. Run /setdelay again.")
        except Exception as exc:
            logger.error("setdelay_timeout failed: %s", exc)
        return ConversationHandler.END

    async def moderate_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            if await self._should_skip_for_conversation(update, context):
                return
            message = update.effective_message
            if not message or not message.text:
                return
            result = await ai_moderation_service.analyze_message(message.text)
            if not result.get("is_safe", True):
                await self._delete_unsafe_message(update, context)
                return
            await self._auto_delete_if_needed(update, context)
        except Exception as exc:
            logger.error("moderate_text failed: %s", exc)

    async def moderate_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            if await self._should_skip_for_conversation(update, context):
                return
            message = update.effective_message
            if not message or not message.photo:
                return
            photo = message.photo[-1]
            file = await photo.get_file()
            image_bytes = await file.download_as_bytearray()
            result = await moderation_service.analyze_image(bytes(image_bytes))
            if not result.get("is_safe", True):
                await self._delete_unsafe_message(update, context)
                return
            await self._auto_delete_if_needed(update, context)
        except Exception as exc:
            logger.error("moderate_photo failed: %s", exc)

    async def moderate_sticker(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            if await self._should_skip_for_conversation(update, context):
                return
            message = update.effective_message
            sticker = message.sticker if message else None
            if not message or not sticker:
                return
            file = await sticker.get_file()
            sticker_bytes = await file.download_as_bytearray()
            result = await moderation_service.analyze_sticker(
                bytes(sticker_bytes),
                is_animated=bool(sticker.is_animated or sticker.is_video),
                set_name=sticker.set_name,
            )
            if not result.get("is_safe", True):
                await self._delete_unsafe_message(update, context)
                return
            await self._auto_delete_if_needed(update, context)
        except Exception as exc:
            logger.error("moderate_sticker failed: %s", exc)

    async def moderate_animation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            if await self._should_skip_for_conversation(update, context):
                return
            message = update.effective_message
            animation = message.animation if message else None
            if not message or not animation:
                return
            file = await animation.get_file()
            anim_bytes = await file.download_as_bytearray()
            result = await moderation_service.analyze_animation(
                bytes(anim_bytes),
                mime_type=animation.mime_type or "image/gif",
                file_name=animation.file_name,
            )
            if not result.get("is_safe", True):
                await self._delete_unsafe_message(update, context)
                return
            await self._auto_delete_if_needed(update, context)
        except Exception as exc:
            logger.error("moderate_animation failed: %s", exc)

    async def handle_edited_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            message = update.edited_message
            chat = update.effective_chat
            if not message or not chat or chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
                return
            self._schedule_delete(
                context=context,
                chat_id=chat.id,
                message_id=message.message_id,
                delay_seconds=DEFAULT_EDIT_DELETE_DELAY,
            )
        except Exception as exc:
            logger.error("handle_edited_message failed: %s", exc)

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            logger.error("Unhandled error: %s", context.error)
        except Exception:
            logger.error("Unhandled error logging failure")

    def register_handlers(self) -> None:
        setdelay_handler = ConversationHandler(
            entry_points=[CommandHandler("setdelay", self.setdelay_start)],
            states={
                SET_DELAY_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.setdelay_receive)],
                ConversationHandler.TIMEOUT: [MessageHandler(filters.ALL, self.setdelay_timeout)],
            },
            fallbacks=[],
            conversation_timeout=120,
            per_chat=True,
            per_user=True,
            per_message=False,
        )

        self.application.add_handler(CommandHandler("start", self.start_command), group=0)
        self.application.add_handler(CommandHandler("panel", self.panel_command), group=0)
        self.application.add_handler(setdelay_handler, group=0)
        self.application.add_handler(CallbackQueryHandler(self.on_callback), group=0)

        group_filter = filters.ChatType.GROUPS
        self.application.add_handler(
            MessageHandler(group_filter & filters.TEXT & ~filters.COMMAND, self.moderate_text),
            group=1,
        )
        self.application.add_handler(MessageHandler(group_filter & filters.PHOTO, self.moderate_photo), group=1)
        self.application.add_handler(MessageHandler(group_filter & filters.Sticker.ALL, self.moderate_sticker), group=1)
        self.application.add_handler(MessageHandler(group_filter & filters.ANIMATION, self.moderate_animation), group=1)
        self.application.add_handler(
            MessageHandler(group_filter & filters.UpdateType.EDITED_MESSAGE, self.handle_edited_message),
            group=1,
        )

        self.application.add_error_handler(self.error_handler)

    def run(self) -> None:
        self.register_handlers()
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)


def run_bot() -> None:
    bot = ModerationBot()
    bot.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    run_bot()
