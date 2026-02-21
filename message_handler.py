"""Primary AI moderation message handler with bot-message coverage."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ContextTypes

from ai_services import ai_moderation_service
from helpers import auto_delete_message, get_group_settings
from styled_helpers import styled_violation_card

logger = logging.getLogger(__name__)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Analyze message text/caption, delete violations, and post styled notices."""
    if not update.effective_chat or not update.effective_user:
        return

    message = update.message or update.edited_message
    if not message:
        return

    content_to_analyze = message.text or message.caption
    if not content_to_analyze:
        return

    chat = update.effective_chat
    user = update.effective_user

    group_settings = await get_group_settings(chat.id)
    if chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}:
        try:
            member = await chat.get_member(user.id)
            if member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}:
                return
        except TelegramError as exc:
            logger.debug("Admin status verification failed for %s: %s", user.id, exc)

    if user.is_bot and not group_settings.get("bot_moderation", True):
        return

    try:
        ai_result = await asyncio.wait_for(
            ai_moderation_service.analyze_message(
                content_to_analyze,
                context={"chat_id": chat.id, "user_id": user.id, "is_bot_user": user.is_bot},
            ),
            timeout=8,
        )
    except asyncio.TimeoutError:
        logger.warning("AI moderation timed out for chat=%s msg=%s", chat.id, message.message_id)
        return
    except Exception:
        logger.exception("AI moderation failure for chat=%s user=%s", chat.id, user.id)
        return

    illegal_score = float(ai_result.get("illegal_score", 0.0))
    toxic_score = float(ai_result.get("toxicity_score", ai_result.get("toxic_score", 0.0)))
    spam_score = float(ai_result.get("spam_score", 0.0))
    should_delete = (
        ai_result.get("is_safe", True) is False
        or illegal_score > 0.6
        or toxic_score > 0.7
        or spam_score > 0.85
    )

    if not should_delete:
        return

    try:
        bot_member = await chat.get_member(context.bot.id)
        if not getattr(bot_member, "can_delete_messages", False):
            logger.warning("Bot cannot delete messages in chat %s", chat.id)
            return
    except TelegramError as exc:
        logger.error("Permission verification failed in chat %s: %s", chat.id, exc)
        return

    try:
        await message.delete()
        user_mention = user.mention_html()
        reason = ai_result.get("reason", "Unsafe content detected by AI")
        notice = await context.bot.send_message(
            chat_id=chat.id,
            text=styled_violation_card(
                user_mention=user_mention,
                reason=reason,
                warning_count=1,
                max_warnings=int(group_settings.get("max_warnings", 3)),
                action_taken="Message deleted",
                is_bot_user=user.is_bot,
            ),
            parse_mode="HTML",
        )
        asyncio.create_task(auto_delete_message(notice, int(group_settings.get("auto_delete_violation", 30))))
        if user.is_bot:
            logger.info("[BOT-VIOLATION] chat=%s user=%s msg=%s", chat.id, user.id, message.message_id)
    except BadRequest as exc:
        logger.warning("BadRequest while deleting message %s: %s", message.message_id, exc)
    except Forbidden:
        logger.error("Forbidden while moderating in chat %s", chat.id)
    except TelegramError:
        logger.exception("Telegram API error during moderation flow")
