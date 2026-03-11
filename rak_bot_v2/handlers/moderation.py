"""Message moderation handlers."""

from __future__ import annotations

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
    """Moderate incoming group messages."""
    if not update:
        LOGGER.error("update_is_none")
        return

    msg = update.effective_message
    chat = update.effective_chat
    if not msg:
        LOGGER.debug("no_effective_message")
        return
    if not chat:
        LOGGER.debug("no_effective_chat")
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
    ai = context.application.bot_data.get("ai")
    if not ai or not store:
        LOGGER.error("services_not_initialized")
        return
    await store.track_chat(chat.id, chat.type)
    settings = get_settings()

    admin_user = await is_admin(update, context) if user else False
    is_owner = bool(user and user.id == settings.owner_id)
    privileged_user = admin_user or is_owner or is_anonymous_admin

    result = await _moderate_content(update, context)
    if result.action == "allow":
        return

    LOGGER.info(
        "content_flagged chat=%s user=%s action=%s privileged=%s reason=%s",
        chat.id,
        user.id if user else None,
        result.action,
        privileged_user,
        result.reason,
    )

    if result.action in {"warn", "delete"} and privileged_user:
        await _send_warning_message(msg, context, result.reason, admin_notice=True)
        await _log_violation(context, chat.id, user.id if user else None, result.reason, privileged_user=True)
        LOGGER.info("privileged_violation chat=%s user=%s", chat.id, user.id if user else None)
        return

    if result.action == "warn":
        await _send_warning_message(msg, context, result.reason)
        return

    if result.action != "delete":
        return

    await safe_delete(context, chat.id, msg.message_id)
    await _log_violation(context, chat.id, user.id if user else None, result.reason, privileged_user=False)

    if not user:
        await _send_warning_message(msg, context, result.reason)
        return

    warnings = await store.increment_warning(chat.id, user.id)
    warning_count = min(warnings, MAX_WARNINGS)
    warn_text = styled_card("⚠️ ᴡᴀʀɴɪɴɢ", f"ʀᴇᴀsᴏɴ: {result.reason}\nᴄᴏᴜɴᴛ: {warning_count}/{MAX_WARNINGS}")
    warn_msg = await msg.reply_text(warn_text, parse_mode="HTML")
    if context.job_queue:
        context.job_queue.run_once(
            _delete_warning_job,
            WARNING_DELETE_DELAY_SECONDS,
            data={"chat_id": warn_msg.chat_id, "message_id": warn_msg.message_id},
        )

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


async def _log_violation(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int | None,
    reason: str,
    privileged_user: bool,
) -> None:
    """Log moderation violations to configured log group."""
    settings = context.application.bot_data.get("settings")
    if not settings:
        return

    actor = str(user_id) if user_id is not None else "anonymous_admin"
    role = "admin_or_owner" if privileged_user else "member"
    try:
        await context.bot.send_message(
            settings.log_group_id,
            f"🚨 moderation_violation\nchat={chat_id}\nuser={actor}\nrole={role}\nreason={reason}",
        )
    except (Forbidden, BadRequest, RetryAfter) as exc:
        LOGGER.warning("log_failed: %s", exc)


async def _send_warning_message(
    msg,
    context: ContextTypes.DEFAULT_TYPE,
    reason: str,
    admin_notice: bool = False,
) -> None:
    """Send and auto-delete warning cards for flagged messages."""
    if admin_notice:
        warn_text = styled_card("⚠️ ʜᴇᴀᴅs ᴜᴘ ᴀᴅᴍɪɴ", f"ғʀɪᴇɴᴅʟʏ ɴᴏᴛᴇ: {reason}\nᴍsɢ ɢʀᴏᴜᴘ ʀᴇᴠɪᴇᴡ ᴋᴇ ʟɪʏᴇ ғʟᴀɢ ᴋɪʏᴀ ɢʏᴀ ʜᴀɪ.")
    else:
        warn_text = styled_card("⚠️ ᴡᴀʀɴɪɴɢ", f"ʀᴇᴀsᴏɴ: {reason}")

    warn_msg = await msg.reply_text(warn_text, parse_mode="HTML")
    if context.job_queue:
        context.job_queue.run_once(
            _delete_warning_job,
            WARNING_DELETE_DELAY_SECONDS,
            data={"chat_id": warn_msg.chat_id, "message_id": warn_msg.message_id},
        )


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
    """Run cache checks and AI moderation for message payload."""
    msg = update.effective_message
    ai = context.application.bot_data.get("ai")
    cache = context.application.bot_data.get("cache")
    if not ai:
        return ModerationResult(action="allow", reason="AI unavailable")
    if msg and msg.text:
        if cache and await cache.is_text_cached_illegal(msg.text):
            return ModerationResult(action="delete", reason="Cached illegal content")
        if cache and await cache.contains_blacklist_word(msg.text):
            await cache.save_illegal_text(msg.text)
            return ModerationResult(action="delete", reason="Blacklisted word detected")
        if cache and await cache.contains_whitelist_word(msg.text):
            return ModerationResult(action="allow", reason="Whitelisted content")
        result = await ai.moderate_text(msg.text)
        if cache and result.action == "delete":
            await cache.save_illegal_text(msg.text)
        return result
    if msg and msg.photo:
        return await _moderate_photo(update, context)
    if msg and msg.sticker:
        return await _moderate_downloaded_media(context, ai, msg.sticker.file_id, "image/webp")
    if msg and msg.animation:
        mime_type = msg.animation.mime_type or "video/mp4"
        return await _moderate_downloaded_media(context, ai, msg.animation.file_id, mime_type, msg.caption or "")
    if msg and msg.caption:
        return await ai.moderate_text(msg.caption)
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
