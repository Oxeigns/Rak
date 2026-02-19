import asyncio
import logging
import re
import time
from typing import Any

from telegram import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from ai_services import ai_moderation_service, moderation_service
from helpers import VERIFY_CALLBACK_DATA, ensure_user_joined, verify_join_callback
from runtime_store import RuntimeStore
from settings import get_settings

logger = logging.getLogger(__name__)

SET_DELAY_VALUE = 1
DEFAULT_EDIT_DELETE_DELAY = 300
DEFAULT_AUTO_DELETE_DELAY = 3600
MIN_DELAY = 1
MAX_DELAY = 86400
WARNING_LIMIT = 3
AUTO_MUTE_SECONDS = 600
SUPPORT_URL = "https://t.me/aghoris"


class ModerationBot:
    def __init__(self) -> None:
        self.config = get_settings()
        self.application = (
            Application.builder()
            .token(self.config.BOT_TOKEN)
            .post_init(self.post_init)
            .post_shutdown(self.post_shutdown)
            .build()
        )
        self._delete_tasks: dict[tuple[int, int], asyncio.Task] = {}
        self._promotion_task: asyncio.Task | None = None
        self.store = RuntimeStore()

    async def post_init(self, application: Application) -> None:
        await self.store.init()
        if not self._promotion_task or self._promotion_task.done():
            self._promotion_task = asyncio.create_task(self._promotion_loop(application))

    async def post_shutdown(self, application: Application) -> None:
        if self._promotion_task and not self._promotion_task.done():
            self._promotion_task.cancel()
            try:
                await self._promotion_task
            except asyncio.CancelledError:
                pass

    async def _is_admin(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
        try:
            member = await context.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            return member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}
        except TelegramError as exc:
            await self._log_event(context, log_type="admin_check_failed", user_id=user_id, chat_id=chat_id, details=str(exc))
            return False

    async def _log_event(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        log_type: str,
        details: str,
        user_id: int | None = None,
        chat_id: int | None = None,
    ) -> None:
        try:
            ts = int(time.time())
            text = (
                "⚠️ LOG\n"
                f"Type: {log_type}\n"
                f"User ID: {user_id if user_id is not None else '-'}\n"
                f"Chat ID: {chat_id if chat_id is not None else '-'}\n"
                f"Details: {details}\n"
                f"Timestamp: {ts}"
            )
            await context.bot.send_message(chat_id=self.config.LOG_GROUP_ID, text=text)
        except Exception as exc:
            logger.error("log send failed: %s", exc)

    async def _log_error(self, context: ContextTypes.DEFAULT_TYPE, error: Exception | BaseException, location: str) -> None:
        try:
            ts = int(time.time())
            text = (
                "⚠️ ERROR LOG\n"
                f"Type: {type(error).__name__}\n"
                f"Error: {error}\n"
                f"Location: {location}\n"
                f"Timestamp: {ts}"
            )
            await context.bot.send_message(chat_id=self.config.LOG_GROUP_ID, text=text)
        except Exception as exc:
            logger.error("error log send failed: %s", exc)

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
        await self.store.upsert_chat(chat.id, chat.type)
        awaiting_user = context.chat_data.get("awaiting_delay_user")
        return awaiting_user == user.id

    def _warning_text(self, count: int, user_id: int, muted: bool = False) -> str:
        text = f"⚠️ Warning ({min(count, WARNING_LIMIT)}/{WARNING_LIMIT})\nReason: Image Violation\n\nUser ID: {user_id}"
        if muted:
            text += "\n\n🔇 User muted for 10 minutes."
        return text

    async def _send_or_edit_warning(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        user_id: int,
        count: int,
        muted: bool = False,
    ) -> int | None:
        message_id = await self.store.get_warning_message_id(chat_id, user_id)
        text = self._warning_text(count=count, user_id=user_id, muted=muted)
        markup = None
        if muted:
            markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔓 Unmute", callback_data=f"unmute:{chat_id}:{user_id}"), InlineKeyboardButton("📢 Support", url=SUPPORT_URL)]]
            )
        try:
            if message_id:
                await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup)
                return message_id
            sent = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)
            await self.store.set_warning_message_id(chat_id, user_id, sent.message_id)
            return sent.message_id
        except TelegramError as exc:
            await self._log_event(context, log_type="warning_message_failed", user_id=user_id, chat_id=chat_id, details=str(exc))
            return None

    async def _apply_image_violation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        user = update.effective_user
        if not chat or not user:
            return
        count = await self.store.increment_warning(chat.id, user.id)
        await self._send_or_edit_warning(context, chat.id, user.id, count, muted=False)
        if count > WARNING_LIMIT:
            try:
                await context.bot.restrict_chat_member(
                    chat_id=chat.id,
                    user_id=user.id,
                    permissions=ChatPermissions(can_send_messages=False, can_send_other_messages=False, can_add_web_page_previews=False),
                    until_date=int(time.time()) + AUTO_MUTE_SECONDS,
                )
                await self._send_or_edit_warning(context, chat.id, user.id, count, muted=True)
                await self._log_event(
                    context,
                    log_type="auto_mute",
                    user_id=user.id,
                    chat_id=chat.id,
                    details="Image violations exceeded threshold; muted for 10 minutes",
                )
            except TelegramError as exc:
                await self._log_event(
                    context,
                    log_type="auto_mute_failed",
                    user_id=user.id,
                    chat_id=chat.id,
                    details=str(exc),
                )

    async def _promotion_loop(self, application: Application) -> None:
        while True:
            try:
                now_ts = int(time.time())
                due_chats = await self.store.get_due_chats(
                    now_ts,
                    group_interval_h=self.config.GROUP_PROMOTION_INTERVAL,
                    dm_interval_h=self.config.DM_PROMOTION_INTERVAL,
                )
                for chat_id, chat_type in due_chats:
                    text = "📢 Support: https://t.me/aghoris"
                    if chat_type == ChatType.PRIVATE:
                        text = "📢 Need help or updates? Join support: https://t.me/aghoris"
                    try:
                        await application.bot.send_message(chat_id=chat_id, text=text)
                        await self.store.set_last_sent(chat_id, now_ts)
                    except TelegramError:
                        continue
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("promotion loop failed: %s", exc)
                await asyncio.sleep(120)

    def _is_suspicious_name(self, first_name: str | None, username: str | None) -> bool:
        combined = f"{first_name or ''} {username or ''}".lower()
        patterns = [r"(?:drug|fake|sex|porn|casino|bet|hack|crack|terror|kill)", r"(?:t\.me/|http://|https://)"]
        return any(re.search(pat, combined) for pat in patterns)

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            chat = update.effective_chat
            user = update.effective_user
            if not chat or not user:
                return
            await self.store.upsert_chat(chat.id, chat.type)
            if chat.type == ChatType.PRIVATE:
                await self._log_event(context, log_type="dm_start", user_id=user.id, chat_id=chat.id, details="User started bot in DM")
                if not await ensure_user_joined(update, context):
                    return
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
            await self._log_error(context, exc, "start_command")

    async def info_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        user = update.effective_user
        message = update.effective_message
        if not chat or not user or not message:
            return
        if await self.store.is_illegal_user(chat.id, user.id):
            reply = await message.reply_text("Info unavailable.")
            await self._safe_delete_message(context, chat.id, reply.message_id)
            await self._log_event(context, log_type="illegal_info_attempt", user_id=user.id, chat_id=chat.id, details="Blocked /info output")
            return
        await message.reply_text(f"User ID: {user.id}")

    async def panel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            chat = update.effective_chat
            user = update.effective_user
            message = update.effective_message
            if not chat or not user or not message:
                return
            if chat.type == ChatType.PRIVATE and not await ensure_user_joined(update, context):
                return
            if chat.type in {ChatType.GROUP, ChatType.SUPERGROUP} and not await self._is_admin(context, chat.id, user.id):
                await message.reply_text("You must be an admin to use this command.")
                return
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back")]])
            await message.reply_text(self._status_text(), reply_markup=keyboard)
        except Exception as exc:
            logger.error("panel_command failed: %s", exc)
            await self._log_error(context, exc, "panel_command")

    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            query = update.callback_query
            if not query:
                return
            chat = query.message.chat if query.message else None
            user = query.from_user
            if not chat or not user:
                return

            data = query.data or ""
            if data == VERIFY_CALLBACK_DATA:
                await verify_join_callback(update, context)
                return

            if data.startswith("unmute:"):
                parts = data.split(":")
                if len(parts) != 3:
                    await query.answer("Invalid action", show_alert=True)
                    return
                cb_chat_id = int(parts[1])
                cb_user_id = int(parts[2])
                if chat.id != cb_chat_id:
                    await query.answer("Invalid action", show_alert=True)
                    return
                if not await self._is_admin(context, chat.id, user.id):
                    await query.answer("Only admins can use this.", show_alert=True)
                    return
                await context.bot.restrict_chat_member(chat_id=chat.id, user_id=cb_user_id, permissions=ChatPermissions(can_send_messages=True, can_send_photos=True, can_send_videos=True, can_send_documents=True, can_send_voice_notes=True, can_send_video_notes=True, can_send_polls=True, can_send_other_messages=True, can_add_web_page_previews=True, can_change_info=False, can_invite_users=True, can_pin_messages=False, can_manage_topics=False))
                await self.store.reset_warning(chat.id, cb_user_id)
                await query.edit_message_text(
                    text=f"✅ User manually unmuted by Admin\n⚠️ Warning counter reset (0/{WARNING_LIMIT})",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📢 Support", url=SUPPORT_URL)]]),
                )
                await query.answer("Done")
                await self._log_event(context, log_type="manual_unmute", user_id=cb_user_id, chat_id=chat.id, details=f"Unmuted by admin {user.id}")
                return

            await query.answer()
            if data not in {"panel", "back"}:
                return

            if chat.type == ChatType.PRIVATE and not await ensure_user_joined(update, context):
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
            await self._log_error(context, exc, "on_callback")

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
            await self._log_error(context, exc, "setdelay_start")
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
            await self._log_error(context, exc, "setdelay_receive")
            return ConversationHandler.END

    async def setdelay_timeout(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        try:
            context.chat_data.pop("awaiting_delay_user", None)
            if update.effective_message:
                await update.effective_message.reply_text("Delay update timed out. Run /setdelay again.")
        except Exception as exc:
            logger.error("setdelay_timeout failed: %s", exc)
            await self._log_error(context, exc, "setdelay_timeout")
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
            await self._log_error(context, exc, "moderate_text")

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
                await self._apply_image_violation(update, context)
                return
            await self._auto_delete_if_needed(update, context)
        except Exception as exc:
            logger.error("moderate_photo failed: %s", exc)
            await self._log_error(context, exc, "moderate_photo")

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
                await self._apply_image_violation(update, context)
                return
            await self._auto_delete_if_needed(update, context)
        except Exception as exc:
            logger.error("moderate_sticker failed: %s", exc)
            await self._log_error(context, exc, "moderate_sticker")

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
                await self._apply_image_violation(update, context)
                return
            await self._auto_delete_if_needed(update, context)
        except Exception as exc:
            logger.error("moderate_animation failed: %s", exc)
            await self._log_error(context, exc, "moderate_animation")

    async def on_new_members(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat = update.effective_chat
        if not message or not chat or not message.new_chat_members:
            return
        await self.store.upsert_chat(chat.id, chat.type)
        for member in message.new_chat_members:
            if member.id == self.config.OWNER_ID:
                await message.reply_text("👑 Bot Owner Joined")
                try:
                    await context.bot.promote_chat_member(chat.id, member.id, can_manage_chat=True, can_delete_messages=True, can_restrict_members=True)
                    await self._log_event(context, log_type="owner_join", user_id=member.id, chat_id=chat.id, details="Owner welcomed and promoted")
                except TelegramError as exc:
                    await self._log_event(context, log_type="owner_promote_failed", user_id=member.id, chat_id=chat.id, details=str(exc))
                continue

            if self._is_suspicious_name(member.first_name, member.username):
                await self.store.flag_illegal_user(chat.id, member.id, "Suspicious name pattern")
                self._schedule_delete(context, chat.id, message.message_id, 5)
                await self._log_event(
                    context,
                    log_type="illegal_name_detection",
                    user_id=member.id,
                    chat_id=chat.id,
                    details=f"Username: {member.username or '-'} | Flag: Suspicious name pattern",
                )

    async def handle_chat_member_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            if not update.my_chat_member:
                return
            chat = update.effective_chat
            if not chat:
                return
            old_status = update.my_chat_member.old_chat_member.status
            new_status = update.my_chat_member.new_chat_member.status
            if new_status in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR} and old_status in {
                ChatMemberStatus.LEFT,
                ChatMemberStatus.KICKED,
            }:
                await self._log_event(context, log_type="bot_added", chat_id=chat.id, details="Bot added to group")
                await self.store.upsert_chat(chat.id, chat.type)
            if new_status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}:
                await self._log_event(context, log_type="bot_removed", chat_id=chat.id, details="Bot removed from group")
        except Exception as exc:
            await self._log_error(context, exc, "handle_chat_member_update")

    async def handle_edited_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            message = update.edited_message
            chat = update.effective_chat
            if not message or not chat or chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
                return
            self._schedule_delete(context=context, chat_id=chat.id, message_id=message.message_id, delay_seconds=DEFAULT_EDIT_DELETE_DELAY)
        except Exception as exc:
            logger.error("handle_edited_message failed: %s", exc)
            await self._log_error(context, exc, "handle_edited_message")

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            logger.error("Unhandled error: %s", context.error)
            if context.error:
                await self._log_error(context, context.error, "global_error_handler")
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
        self.application.add_handler(CommandHandler("info", self.info_command), group=0)
        self.application.add_handler(setdelay_handler, group=0)
        self.application.add_handler(CallbackQueryHandler(self.on_callback), group=0)
        self.application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, self.on_new_members), group=0)
        self.application.add_handler(ChatMemberHandler(self.handle_chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER), group=0)

        group_filter = filters.ChatType.GROUPS
        self.application.add_handler(MessageHandler(group_filter & filters.TEXT & ~filters.COMMAND, self.moderate_text), group=1)
        self.application.add_handler(MessageHandler(group_filter & filters.PHOTO, self.moderate_photo), group=1)
        self.application.add_handler(MessageHandler(group_filter & filters.Sticker.ALL, self.moderate_sticker), group=1)
        self.application.add_handler(MessageHandler(group_filter & filters.ANIMATION, self.moderate_animation), group=1)
        self.application.add_handler(MessageHandler(group_filter & filters.UpdateType.EDITED_MESSAGE, self.handle_edited_message), group=1)

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
