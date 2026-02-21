"""Comprehensive moderation module with bot-message support and styled notices."""

from __future__ import annotations

import asyncio
import io
import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from telegram import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ContextTypes

from ai_services import moderation_service
from database import GroupUser, db_manager
from helpers import auto_delete_message, ensure_user_joined, get_group_settings
from styled_helpers import styled_mute_card, styled_violation_card

logger = logging.getLogger(__name__)

TOXIC_THRESHOLD = 0.7
ILLEGAL_THRESHOLD = 0.6
SPAM_THRESHOLD = 0.85
MUTE_HOURS = 24
URL_PATTERN = re.compile(r"http[s]?://")
SUSPICIOUS_URL_PATTERN = re.compile(r"(?:bit\.ly|tinyurl|phish|free.*money|verify.*account)", re.IGNORECASE)


async def moderate_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message or update.edited_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user or not (message.text or message.caption):
        return

    if chat.type == ChatType.PRIVATE:
        if not await ensure_user_joined(update, context):
            return
        return

    if await _is_user_admin(update, context):
        return

    settings = await get_group_settings(chat.id)

    text = message.text or message.caption or ""
    if settings.get("link_filter", True):
        for url in await detect_links(text):
            url_check = await check_link_safety(url)
            if not url_check.get("is_safe", True):
                await _delete_and_warn(context, message, chat.id, user, url_check.get("reason", "Suspicious URL"), "link")
                return

    result = await moderation_service.analyze_text(text, caption=message.caption)
    toxic_score = float(result.get("toxic_score", result.get("toxicity_score", 0.0)))
    illegal_score = float(result.get("illegal_score", 0.0))
    spam_score = float(result.get("spam_score", 0.0))
    if (
        result.get("is_safe", True)
        and toxic_score <= float(settings.get("toxic_threshold", TOXIC_THRESHOLD))
        and illegal_score <= ILLEGAL_THRESHOLD
        and spam_score <= SPAM_THRESHOLD
    ):
        return

    await _delete_and_warn(context, message, chat.id, user, result.get("reason", "Policy violation"), "text")


async def moderate_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message or update.edited_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user or not message.photo:
        return

    if chat.type == ChatType.PRIVATE:
        if not await ensure_user_joined(update, context):
            return
        return

    if await _is_user_admin(update, context):
        return

    try:
        file_obj = await message.photo[-1].get_file()
        buffer = io.BytesIO()
        await file_obj.download_to_memory(out=buffer)
        image_result = await moderation_service.analyze_image(buffer.getvalue())
    except Exception:
        logger.exception("Photo moderation failed")
        return

    caption_result = await moderation_service.analyze_text(message.caption or "", caption=message.caption or "")
    image_unsafe = image_result.get("is_safe") is False
    caption_unsafe = caption_result.get("is_safe") is False
    if image_unsafe or caption_unsafe:
        reason = image_result.get("reason", "Unsafe image") if image_unsafe else caption_result.get("reason", "Unsafe caption")
        await _delete_and_warn(context, message, chat.id, user, reason, "photo")


async def moderate_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message or update.edited_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user or not message.sticker:
        return

    settings = await get_group_settings(chat.id)
    if not settings.get("sticker_filter", True) or await _is_user_admin(update, context):
        return

    try:
        sticker_file = await message.sticker.get_file()
        buffer = io.BytesIO()
        await sticker_file.download_to_memory(out=buffer)
        result = await moderation_service.analyze_sticker(
            buffer.getvalue(),
            message.sticker.is_animated,
            message.sticker.set_name,
        )
        if message.sticker.is_animated and not result.get("is_safe", True):
            await _delete_and_warn(context, message, chat.id, user, result.get("reason", "Animated sticker blocked"), "sticker")
    except Exception:
        logger.exception("Sticker moderation failed")


async def moderate_animation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message or update.edited_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not chat or not user or not message.animation:
        return

    settings = await get_group_settings(chat.id)
    if not settings.get("gif_filter", True) or await _is_user_admin(update, context):
        return

    try:
        anim_file = await message.animation.get_file()
        buffer = io.BytesIO()
        await anim_file.download_to_memory(out=buffer)
        result = await moderation_service.analyze_animation(
            buffer.getvalue(), message.animation.mime_type or "application/octet-stream", message.animation.file_name
        )
        if not result.get("is_safe", True):
            await _delete_and_warn(context, message, chat.id, user, result.get("reason", "GIF blocked"), "animation")
    except Exception:
        logger.exception("Animation moderation failed")


async def moderate_edited_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.edited_message
    if not message:
        return
    await moderate_text(update, context)


async def detect_links(text: str) -> list[str]:
    if not text or not URL_PATTERN.search(text):
        return []
    return re.findall(r"http[s]?://\S+", text)


async def check_link_safety(url: str) -> dict:
    if SUSPICIOUS_URL_PATTERN.search(url):
        return {"is_safe": False, "reason": "Suspicious short/phishing URL"}
    return {"is_safe": True}


async def _delete_and_warn(
    context: ContextTypes.DEFAULT_TYPE,
    message,
    chat_id: int,
    user,
    reason: str,
    content_type: str,
) -> None:
    settings = await get_group_settings(chat_id)
    max_warnings = int(settings.get("max_warnings", 3))
    mute_duration = int(settings.get("mute_duration", MUTE_HOURS))

    try:
        await message.delete()
    except (BadRequest, Forbidden, TelegramError):
        logger.exception("Failed to delete violating message")
        return

    warn_count = await _increment_warning(chat_id, user.id)
    action = f"Deleted {content_type}"
    if warn_count >= max_warnings:
        action = f"Muted {mute_duration}h"
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=datetime.now(timezone.utc) + timedelta(hours=mute_duration),
            )
        except TelegramError:
            logger.exception("Failed to mute user %s in chat %s", user.id, chat_id)

    text = styled_violation_card(
        user_mention=user.mention_html(),
        reason=reason,
        warning_count=warn_count,
        max_warnings=max_warnings,
        action_taken=action,
        is_bot_user=bool(user.is_bot),
    )
    if warn_count >= max_warnings:
        text = styled_mute_card(user.mention_html(), reason, mute_duration, warn_count)

    notice = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔓 Unmute", callback_data=f"unmute_{user.id}")]]
        )
        if warn_count >= max_warnings
        else None,
    )
    asyncio.create_task(auto_delete_message(notice, int(settings.get("auto_delete_violation", 30))))

    if user.is_bot:
        logger.info("[BOT-VIOLATION] chat=%s user=%s warnings=%s", chat_id, user.id, warn_count)


async def _is_user_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user or chat.type == ChatType.PRIVATE:
        return False
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except TelegramError:
        logger.debug("Admin check failed for %s in %s", user.id, chat.id, exc_info=True)
        return False


async def _increment_warning(chat_id: int, user_id: int) -> int:
    async with db_manager.get_session() as session:
        stmt = select(GroupUser).where(GroupUser.group_id == chat_id, GroupUser.user_id == user_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            row = GroupUser(group_id=chat_id, user_id=user_id, violation_count=1)
            session.add(row)
        else:
            row.violation_count += 1
        await session.commit()
        return int(row.violation_count)
