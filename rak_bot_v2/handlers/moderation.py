"""Message moderation handlers."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from telegram import ChatPermissions, Update
from telegram.error import BadRequest, Forbidden, RetryAfter
from telegram.ext import ContextTypes

from rak_bot_v2.config.constants import EDIT_DELETE_DELAY_SECONDS, MAX_WARNINGS, MUTE_SECONDS, SUSPICIOUS_WORDS, WARNING_DELETE_DELAY_SECONDS
from rak_bot_v2.services.ai_moderation import ModerationResult
from rak_bot_v2.utils.formatters import styled_card
from rak_bot_v2.utils.helpers import is_admin, safe_delete

LOGGER = logging.getLogger(__name__)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Moderate incoming group messages."""
    msg = update.effective_message
    if not msg or not update.effective_chat or update.effective_chat.type == "private":
        return
    if msg.from_user and msg.from_user.id == context.bot.id:
        return
    store = context.application.bot_data.get("store")
    ai = context.application.bot_data.get("ai")
    if not ai or not store:
        LOGGER.error("services_not_initialized")
        return
    result = await _moderate_content(update, context)
    if result.action == "allow":
        return
    await safe_delete(context, update.effective_chat.id, msg.message_id)
    warnings = await store.increment_warning(update.effective_chat.id, msg.from_user.id) if msg.from_user else 0
    warn_msg = await msg.reply_text(
        styled_card("⚠️ ᴡᴀʀɴɪɴɢ", f"ʀᴇᴀsᴏɴ: {result.reason}\nᴄᴏᴜɴᴛ: {warnings}/{MAX_WARNINGS}"),
        parse_mode="HTML",
    )
    if context.job_queue:
        context.job_queue.run_once(
            lambda c: c.application.create_task(safe_delete(c, warn_msg.chat_id, warn_msg.message_id)),
            WARNING_DELETE_DELAY_SECONDS,
        )
    if msg.from_user and await is_admin(update, context):
        LOGGER.info("admin_violation chat=%s user=%s", update.effective_chat.id, msg.from_user.id)
    if warnings >= MAX_WARNINGS and msg.from_user:
        await _mute_user(update, context, msg.from_user.id)
        await store.reset_warning(update.effective_chat.id, msg.from_user.id)


async def handle_edited(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete edited messages after delay."""
    msg = update.edited_message
    if not msg or not update.effective_chat:
        return
    if context.job_queue:
        context.job_queue.run_once(
            lambda c: c.application.create_task(safe_delete(c, update.effective_chat.id, msg.message_id)),
            EDIT_DELETE_DELAY_SECONDS,
        )


async def handle_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Flag suspicious names on join."""
    msg = update.effective_message
    if not msg or not msg.new_chat_members:
        return
    for member in msg.new_chat_members:
        text = f"{member.full_name} {member.username or ''}".lower()
        if any(word in text for word in SUSPICIOUS_WORDS):
            await safe_delete(context, msg.chat_id, msg.message_id)
            try:
                await context.bot.send_message(context.application.bot_data["settings"].log_group_id, f"🚫 suspicious join: {member.id}")
            except (Forbidden, BadRequest, RetryAfter) as exc:
                LOGGER.warning("log_failed: %s", exc)


async def _moderate_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    ai = context.application.bot_data.get("ai")
    if not ai:
        return ModerationResult(action="allow", reason="AI unavailable")
    if msg and msg.text:
        return await ai.moderate_text(msg.text)
    if msg and msg.photo:
        return await _moderate_downloaded_media(context, ai, msg.photo[-1].file_id, "image/jpeg", msg.caption or "")
    if msg and msg.sticker:
        return await _moderate_downloaded_media(context, ai, msg.sticker.file_id, "image/webp")
    if msg and msg.animation:
        mime_type = msg.animation.mime_type or "video/mp4"
        return await _moderate_downloaded_media(context, ai, msg.animation.file_id, mime_type, msg.caption or "")
    if msg and msg.caption:
        return await ai.moderate_text(msg.caption)
    return ModerationResult(action="allow", reason="Unsupported content")


async def _moderate_downloaded_media(
    context: ContextTypes.DEFAULT_TYPE,
    ai,
    file_id: str,
    mime_type: str,
    caption: str = "",
) -> ModerationResult:
    try:
        file = await context.bot.get_file(file_id)
        blob = await file.download_as_bytearray()
        return await ai.moderate_media(bytes(blob), mime_type, caption)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("download_failed: %s", exc)
        return ModerationResult(action="allow", reason="Download failed")


async def _mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    try:
        until = datetime.now(timezone.utc) + timedelta(seconds=MUTE_SECONDS)
        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
    except (Forbidden, BadRequest, RetryAfter) as exc:
        LOGGER.warning("mute_failed chat=%s user=%s err=%s", update.effective_chat.id, user_id, exc)
