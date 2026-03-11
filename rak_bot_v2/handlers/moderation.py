"""Message moderation handlers."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from telegram import ChatPermissions, Update
from telegram.error import BadRequest, Forbidden, RetryAfter
from telegram.ext import ContextTypes

from rak_bot_v2.config.constants import (
    EDIT_DELETE_DELAY_SECONDS,
    MAX_WARNINGS,
    MUTE_SECONDS,
    SUSPICIOUS_WORDS,
    WARNING_DELETE_DELAY_SECONDS,
)
from rak_bot_v2.config.settings import get_settings
from rak_bot_v2.services.ai_moderation import ModerationResult
from rak_bot_v2.utils.formatters import styled_card
from rak_bot_v2.utils.helpers import is_admin, safe_delete, safe_handler

LOGGER = logging.getLogger(__name__)


@safe_handler
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Moderate incoming group messages for every sender role."""
    if not update:
        LOGGER.error("update_is_none")
        return

    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return
    if chat.type == "private":
        return

    user = msg.from_user
    is_anonymous_admin = bool(msg.sender_chat and msg.sender_chat.id == chat.id and not user)
    if user and user.id == context.bot.id:
        return
    if not user and not is_anonymous_admin:
        LOGGER.debug("no_from_user - unsupported sender type")
        return

    store = context.application.bot_data.get("store")
    if not store:
        LOGGER.error("store_not_initialized")
        return

    await store.track_chat(chat.id, chat.type)

    role = await _resolve_user_role(update, context, is_anonymous_admin)
    result = await _moderate_content(update, context)

    if result.action == "allow":
        return

    await _log_violation(
        context=context,
        chat_id=chat.id,
        message_id=msg.message_id,
        user_id=user.id if user else None,
        username=user.username if user else None,
        reason=result.reason,
        role=role,
    )

    if result.action == "warn":
        await _send_warning_message(msg, result.reason)
        return

    if result.action == "delete":
        await safe_delete(context, chat.id, msg.message_id)
        await _send_warning_message(msg, result.reason)

        if user:
            warnings = await store.increment_warning(chat.id, user.id)
            if warnings >= MAX_WARNINGS:
                await _mute_user(update, context, user.id)
                await store.reset_warning(chat.id, user.id)


@safe_handler
async def handle_edited(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete edited messages after delay."""
    msg = update.edited_message
    if not msg or not update.effective_chat:
        return
    if context.job_queue:
        context.job_queue.run_once(
            _delete_warning_job,
            EDIT_DELETE_DELAY_SECONDS,
            data={"chat_id": update.effective_chat.id, "message_id": msg.message_id},
        )


@safe_handler
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


async def _resolve_user_role(update: Update, context: ContextTypes.DEFAULT_TYPE, is_anonymous_admin: bool) -> str:
    """Resolve sender role for moderation logs."""
    if is_anonymous_admin:
        return "admin"
    user = update.effective_user
    if not user:
        return "member"

    settings = get_settings()
    if user.id == settings.owner_id:
        return "owner"

    try:
        if await is_admin(update, context):
            return "admin"
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("role_resolution_failed user=%s err=%s", user.id, exc)
    return "member"


async def _log_violation(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    user_id: int | None,
    username: str | None,
    reason: str,
    role: str,
) -> None:
    """Log moderation violations to configured log group."""
    settings = context.application.bot_data.get("settings")
    if not settings:
        return

    actor = str(user_id) if user_id is not None else "anonymous_admin"
    handle = f"@{username}" if username else "-"
    try:
        await context.bot.send_message(
            settings.log_group_id,
            (
                "🚨 moderation_violation\n"
                f"chat_id={chat_id}\n"
                f"message_id={message_id}\n"
                f"user_id={actor}\n"
                f"username={handle}\n"
                f"role={role}\n"
                f"reason={reason}"
            ),
        )
    except (Forbidden, BadRequest, RetryAfter) as exc:
        LOGGER.warning("log_failed: %s", exc)


async def _send_warning_message(msg, reason: str) -> None:
    """Send warning and auto-delete after configured delay without blocking."""
    warn_text = styled_card("⚠️ ᴡᴀʀɴɪɴɢ", f"ʀᴇᴀsᴏɴ: {reason}")
    warn_msg = await msg.reply_text(warn_text, parse_mode="HTML")
    asyncio.create_task(_auto_delete_warning(warn_msg, WARNING_DELETE_DELAY_SECONDS))


async def _auto_delete_warning(msg, delay_seconds: int) -> None:
    """Best-effort warning auto-deletion."""
    await asyncio.sleep(delay_seconds)
    try:
        await msg.delete()
    except Exception as exc:  # noqa: BLE001
        LOGGER.debug("warning_delete_failed chat=%s msg=%s err=%s", msg.chat_id, msg.message_id, exc)


async def _delete_warning_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete warning/edit message safely from job queue."""
    try:
        job_data = context.job.data if context.job else None
        if not job_data:
            return
        if not isinstance(job_data, dict):
            LOGGER.error("invalid_job_data: %s", job_data)
            return
        await safe_delete(context, int(job_data["chat_id"]), int(job_data["message_id"]))
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("delete_job_failed: %s", exc)


async def _moderate_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> ModerationResult:
    """Run rule-based checks first, then AI moderation for text/media/captions."""
    msg = update.effective_message
    ai = context.application.bot_data.get("ai")
    cache = context.application.bot_data.get("cache")
    if not msg:
        return ModerationResult(action="allow", reason="No message")

    text_payload = (msg.text or msg.caption or "").strip()
    if text_payload:
        if cache and await cache.is_text_cached_illegal(text_payload):
            return ModerationResult(action="delete", reason="Cached illegal content")
        if cache and await cache.contains_blacklist_word(text_payload):
            await cache.save_illegal_text(text_payload)
            return ModerationResult(action="delete", reason="Blacklisted word detected")
        if cache and await cache.contains_whitelist_word(text_payload):
            return ModerationResult(action="allow", reason="Whitelisted content")

    if not ai:
        return ModerationResult(action="allow", reason="AI unavailable")

    try:
        if msg.photo:
            return await _moderate_photo(update, context)
        if msg.sticker:
            return await _moderate_downloaded_media(context, ai, msg.sticker.file_id, "image/webp", text_payload)
        if msg.animation:
            mime_type = msg.animation.mime_type or "video/mp4"
            return await _moderate_downloaded_media(context, ai, msg.animation.file_id, mime_type, text_payload)
        if msg.document:
            mime_type = msg.document.mime_type or "application/octet-stream"
            return await _moderate_downloaded_media(context, ai, msg.document.file_id, mime_type, text_payload)
        if text_payload:
            result = await ai.moderate_text(text_payload)
            if cache and result.action == "delete":
                await cache.save_illegal_text(text_payload)
            return result
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("moderation_pipeline_failed chat=%s msg=%s err=%s", update.effective_chat.id if update.effective_chat else None, msg.message_id, exc)

    return ModerationResult(action="allow", reason="Unsupported content")


async def _moderate_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> ModerationResult:
    """Moderate Telegram photo with perceptual cache then AI."""
    msg = update.effective_message
    ai = context.application.bot_data.get("ai")
    cache = context.application.bot_data.get("cache")
    if not msg or not msg.photo or not ai:
        return ModerationResult(action="allow", reason="Unsupported photo")
    try:
        file = await context.bot.get_file(msg.photo[-1].file_id)
        blob = bytes(await file.download_as_bytearray())
        if cache and await cache.is_image_cached_illegal(blob):
            return ModerationResult(action="delete", reason="Cached illegal image")
        result = await ai.moderate_media(blob, "image/jpeg", msg.caption or "")
        if cache and result.action == "delete":
            await cache.save_illegal_image(blob)
        return result
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("image_moderation_failed: %s", exc)
        return ModerationResult(action="allow", reason="Processing failed")


async def _moderate_downloaded_media(
    context: ContextTypes.DEFAULT_TYPE,
    ai,
    file_id: str,
    mime_type: str,
    caption: str = "",
) -> ModerationResult:
    """Moderate downloadable media via AI backend."""
    try:
        file = await context.bot.get_file(file_id)
        blob = await file.download_as_bytearray()
        return await ai.moderate_media(bytes(blob), mime_type, caption)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("download_failed: %s", exc)
        return ModerationResult(action="allow", reason="Download failed")


async def _mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Apply temporary mute to user reaching warning threshold."""
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
