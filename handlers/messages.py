"""Message handlers for moderation actions with Times New Roman styling."""

from __future__ import annotations

import asyncio
import io
import logging
from typing import TYPE_CHECKING

from telegram import Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ai_services import moderation_service
from helpers import auto_delete_message, get_group_settings
from styled_helpers import styled_violation_card

if TYPE_CHECKING:
    from bot import AIGovernorBot

logger = logging.getLogger(__name__)


class MessageHandlers:
    async def handle_message(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message or not update.effective_chat or not update.effective_user:
            return

        message = update.effective_message
        chat = update.effective_chat
        user = update.effective_user

        if chat.type == ChatType.PRIVATE:
            return

        await self._create_group(chat)
        settings = await get_group_settings(chat.id)

        try:
            member = await context.bot.get_chat_member(chat.id, user.id)
            if member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}:
                return
        except TelegramError:
            logger.debug("Admin check failed", exc_info=True)


        if message.text or message.caption:
            text_result = await moderation_service.analyze_text(message.text or "", message.caption)
            if not text_result.get("is_safe", True):
                try:
                    await message.delete()
                    warn = await context.bot.send_message(
                        chat_id=chat.id,
                        text=styled_violation_card(
                            user_mention=user.mention_html(),
                            reason=text_result.get("reason", "Unsafe text detected"),
                            warning_count=1,
                            max_warnings=int(settings.get("max_warnings", 3)),
                            action_taken="Message deleted",
                            is_bot_user=bool(user.is_bot),
                        ),
                        parse_mode="HTML",
                    )
                    asyncio.create_task(
                        auto_delete_message(warn, int(settings.get("auto_delete_violation", self.settings.AUTO_DELETE_VIOLATION)))
                    )
                except TelegramError as exc:
                    logger.error("Failed to delete unsafe text message: %s", exc)
                return

        if message.photo:
            try:
                largest_photo = message.photo[-1]
                telegram_file = await largest_photo.get_file()
                buffer = io.BytesIO()
                await telegram_file.download_to_memory(out=buffer)
                image_result = await moderation_service.analyze_image(buffer.getvalue())
                if not image_result.get("is_safe", True):
                    await message.delete()
            except Exception as exc:
                logger.error("Image moderation failed: %s", exc)

    async def handle_edited_message(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.edited_message or not update.effective_chat:
            return
        if update.effective_chat.type == ChatType.PRIVATE:
            return
        delay = context.chat_data.get("edit_delete_delay", self.settings.AUTO_DELETE_EDITED)
        asyncio.create_task(auto_delete_message(update.edited_message, int(delay)))

    async def handle_error(self: "AIGovernorBot", update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error("Exception while handling update: %s", context.error)
