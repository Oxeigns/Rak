"""Message handlers for the 4 core moderation features."""

import asyncio
import io
import logging
from typing import TYPE_CHECKING

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from ai_services import moderation_service

if TYPE_CHECKING:
    from bot import AIGovernorBot

logger = logging.getLogger(__name__)


class MessageHandlers:
    async def handle_message(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_message or not update.effective_chat or not update.effective_user:
            return

        message = update.effective_message
        chat = update.effective_chat
        user = update.effective_user

        if chat.type == ChatType.PRIVATE or user.is_bot:
            return

        await self._create_group(chat)

        # Text moderation
        if message.text or message.caption:
            text_result = await moderation_service.analyze_text(message.text or "", message.caption)
            if not text_result.get("is_safe", True):
                try:
                    await message.delete()
                    warn = await context.bot.send_message(
                        chat_id=chat.id,
                        text=f"◆ ᴍsɢ ᴅᴇʟᴇᴛᴇᴅ 🚫\n\nʀᴇᴀsᴏɴ: {text_result.get('reason', 'Unsafe text detected')}",
                    )
                    delay = context.chat_data.get("auto_delete_delay", self.settings.AUTO_DELETE_BOT_MSG)
                    asyncio.create_task(warn.delete() if delay <= 0 else self._delete_after(warn, delay))
                except Exception as exc:
                    logger.error("Failed to delete unsafe text message: %s", exc)
                return

        # Image moderation
        if message.photo:
            try:
                largest_photo = message.photo[-1]
                telegram_file = await largest_photo.get_file()
                buffer = io.BytesIO()
                await telegram_file.download_to_memory(out=buffer)
                image_result = await moderation_service.analyze_image(buffer.getvalue())
                if not image_result.get("is_safe", True):
                    await message.delete()
                    return
            except Exception as exc:
                logger.error("Image moderation failed: %s", exc)

            delay = context.chat_data.get("auto_delete_delay", self.settings.AUTO_DELETE_BOT_MSG)
            asyncio.create_task(self._delete_after(message, delay))

    async def handle_edited_message(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.edited_message or not update.effective_chat:
            return

        if update.effective_chat.type == ChatType.PRIVATE:
            return

        delay = context.chat_data.get("edit_delete_delay", self.settings.AUTO_DELETE_EDITED)
        asyncio.create_task(self._delete_after(update.edited_message, delay))

    async def _delete_after(self, message, delay: int):
        await asyncio.sleep(max(1, delay))
        try:
            await message.delete()
        except Exception as exc:
            logger.error("Auto-delete error: %s", exc)

    async def handle_error(self: "AIGovernorBot", update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.error("Exception while handling update: %s", context.error)
