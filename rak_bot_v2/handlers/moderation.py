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
from rak_bot_v2.utils.formatters import styled_card, unmute_keyboard
from rak_bot_v2.utils.helpers import is_admin, safe_delete, safe_handler

LOGGER = logging.getLogger(__name__)


@safe_handler
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Moderate incoming group messages."""
    if not update:
        return

    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat or chat.type == "private":
        return

    user = msg.from_user
    is_anonymous_admin = bool(msg.sender_chat and msg.sender_chat.id == chat.id and not user)

    # Skip bot's own messages
    if user and user.id == context.bot.id:
        return
    # Skip unknown sender types
    if not user and not is_anonymous_admin:
        LOGGER.debug("no_from_user – unsupported sender type")
        return

    store = context.application.bot_data.get("store")
    if not store:
        LOGGER.error("store_not_initialized")
        return

    await store.track_chat(chat.id, chat.type)

    # ── BUG FIX: Skip moderation for admins & owner ────────────────────────
    role = await _resolve_user_role(update, context, is_anonymous_admin)
    if role in {"owner", "admin"}:
        return

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
        await _send_warning_message(context, msg, result.reason)
        return

    if result.action == "delete":
        await safe_delete(context, chat.id, msg.message_id)
        await _send_warning_message(context, msg, result.reason)

        if user:
            warnings = await store.increment_warning(chat.id, user.id)
            if warnings >= MAX_WARNINGS:
                await _mute_user(update, context, user.id)
                await store.reset_warning(chat.id, user.id)


@safe_handler
async def handle_edited(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Moderate edited messages – ONLY schedule deletion if the new content
    is also flagged as a violation (not ALL edits indiscriminately).
    """
    msg = update.edited_message
    if not msg or not update.effective_chat:
        return

    # Skip admins & owner
    role = await _resolve_user_role(update, context, is_anonymous_admin=False)
    if role in {"owner", "admin"}:
        return

    result = await _moderate_content(update, context)
    if result.action == "allow":
        return  # Clean edit – no action needed

    # Flagged edit → schedule deletion
    if context.job_queue:
        context.job_queue.run_once(
            _delete_job,
            EDIT_DELETE_DELAY_SECONDS,
            data={
                "chat_id": update.effective_chat.id,
                "message_id": msg.message_id,
            },
        )
    await _send_warning_message(context, msg, result.reason)


@safe_handler
async def handle_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Flag suspicious display-names on join and restrict the user."""
    msg = update.effective_message
    if not msg or not msg.new_chat_members:
        return

    settings = context.application.bot_data.get("settings") or get_settings()

    for member in msg.new_chat_members:
        text = f"{member.full_name} {member.username or ''}".lower()
        if any(word in text for word in SUSPICIOUS_WORDS):
            # Delete join notification
            await safe_delete(context, msg.chat_id, msg.message_id)

            # BUG FIX: actually restrict the suspicious user, not just delete the join msg
            try:
                await context.bot.restrict_chat_member(
                    msg.chat_id,
                    member.id,
                    permissions=ChatPermissions(can_send_messages=False),
                )
            except (Forbidden, BadRequest, RetryAfter) as exc:
                LOGGER.warning("restrict_suspicious_user_failed user=%s err=%s", member.id, exc)

            # Log to log group
            try:
                await context.bot.send_message(
                    settings.log_group_id,
                    (
                        f"🚫 <b>Suspicious join restricted</b>\n"
                        f"user_id={member.id}\n"
                        f"name={member.full_name}\n"
                        f"chat_id={msg.chat_id}"
                    ),
                    parse_mode="HTML",
                )
            except (Forbidden, BadRequest, RetryAfter) as exc:
                LOGGER.warning("log_failed: %s", exc)


# ── Role Resolution ────────────────────────────────────────────────────────

async def _resolve_user_role(
    update: Update, context: ContextTypes.DEFAULT_TYPE, is_anonymous_admin: bool
) -> str:
    """Return sender's role string: owner | admin | member."""
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


# ── Logging ────────────────────────────────────────────────────────────────

async def _log_violation(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    user_id: int | None,
    username: str | None,
    reason: str,
    role: str,
) -> None:
    """Log moderation violation to the configured log group."""
    settings = context.application.bot_data.get("settings")
    if not settings:
        return
    actor = str(user_id) if user_id is not None else "anonymous_admin"
    handle = f"@{username}" if username else "-"
    try:
        await context.bot.send_message(
            settings.log_group_id,
            (
                "🚨 <b>moderation_violation</b>\n"
                f"chat_id={chat_id}\n"
                f"message_id={message_id}\n"
                f"user_id={actor}\n"
                f"username={handle}\n"
                f"role={role}\n"
                f"reason={reason}"
            ),
            parse_mode="HTML",
        )
    except (Forbidden, BadRequest, RetryAfter) as exc:
        LOGGER.warning("log_failed: %s", exc)


# ── Warning Message ────────────────────────────────────────────────────────

async def _send_warning_message(
    context: ContextTypes.DEFAULT_TYPE, msg, reason: str
) -> None:
    """Send a warning reply and auto-delete it after the configured delay."""
    warn_text = styled_card("⚠️ ᴡᴀʀɴɪɴɢ", f"ʀᴇᴀsᴏɴ: {reason}")
    try:
        warn_msg = await msg.reply_text(warn_text, parse_mode="HTML")
        # Use application.create_task so the task is tracked and cancelled on shutdown
        context.application.create_task(
            _auto_delete_after(warn_msg, WARNING_DELETE_DELAY_SECONDS)
        )
    except (Forbidden, BadRequest, RetryAfter) as exc:
        LOGGER.warning("warning_send_failed: %s", exc)


async def _auto_delete_after(msg, delay_seconds: int) -> None:
    """Best-effort auto-deletion after delay."""
    await asyncio.sleep(delay_seconds)
    try:
        await msg.delete()
    except Exception as exc:  # noqa: BLE001
        LOGGER.debug(
            "auto_delete_failed chat=%s msg=%s err=%s",
            msg.chat_id,
            msg.message_id,
            exc,
        )


# ── Job Queue Deletion ─────────────────────────────────────────────────────

async def _delete_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job-queue callback to delete a message."""
    try:
        job_data = context.job.data if context.job else None
        if not isinstance(job_data, dict):
            LOGGER.error("invalid_job_data: %s", job_data)
            return
        await safe_delete(context, int(job_data["chat_id"]), int(job_data["message_id"]))
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("delete_job_failed: %s", exc)


# ── Content Moderation Pipeline ────────────────────────────────────────────

async def _moderate_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> ModerationResult:
    """
    Run moderation pipeline:
      1. Cache lookup (fast)
      2. Blacklist / whitelist check
      3. AI moderation (text / image / media)
    Covers: text, captions, photos, stickers, animations, documents,
            videos, voice messages, audio files.
    """
    msg = update.effective_message
    ai = context.application.bot_data.get("ai")
    cache = context.application.bot_data.get("cache")

    if not msg:
        return ModerationResult(action="allow", reason="No message")

    text_payload = (msg.text or msg.caption or "").strip()

    # ── Text pipeline ──────────────────────────────────────────────────────
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
        # ── Photo ──────────────────────────────────────────────────────────
        if msg.photo:
            return await _moderate_photo(update, context)

        # ── Sticker / Animation / Document ────────────────────────────────
        if msg.sticker:
            return await _moderate_downloaded_media(
                context, ai, msg.sticker.file_id, "image/webp", text_payload
            )
        if msg.animation:
            mime_type = msg.animation.mime_type or "video/mp4"
            return await _moderate_downloaded_media(
                context, ai, msg.animation.file_id, mime_type, text_payload
            )
        if msg.document:
            mime_type = msg.document.mime_type or "application/octet-stream"
            return await _moderate_downloaded_media(
                context, ai, msg.document.file_id, mime_type, text_payload
            )

        # ── BUG FIX: Video, Voice, Audio were previously ignored ──────────
        if msg.video:
            # Only caption is moderated (video download would be too large)
            if text_payload:
                result = await ai.moderate_text(text_payload)
                if cache and result.action == "delete":
                    await cache.save_illegal_text(text_payload)
                return result

        if msg.voice or msg.audio:
            # Moderate caption/text only
            if text_payload:
                result = await ai.moderate_text(text_payload)
                if cache and result.action == "delete":
                    await cache.save_illegal_text(text_payload)
                return result

        # ── Plain text ─────────────────────────────────────────────────────
        if text_payload:
            result = await ai.moderate_text(text_payload)
            if cache and result.action == "delete":
                await cache.save_illegal_text(text_payload)
            return result

    except Exception as exc:  # noqa: BLE001
        LOGGER.exception(
            "moderation_pipeline_failed chat=%s msg=%s err=%s",
            update.effective_chat.id if update.effective_chat else None,
            msg.message_id,
            exc,
        )

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
    """Download media and moderate via AI."""
    try:
        file = await context.bot.get_file(file_id)
        blob = bytes(await file.download_as_bytearray())
        return await ai.moderate_media(blob, mime_type, caption)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("download_failed: %s", exc)
        return ModerationResult(action="allow", reason="Download failed")


# ── Mute / Unmute ──────────────────────────────────────────────────────────

async def _mute_user(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> None:
    """
    Apply temporary mute to a user and send an unmute button to the chat.
    BUG FIX: Previously the unmute keyboard was never sent.
    """
    chat = update.effective_chat
    if not chat:
        return
    try:
        until = datetime.now(timezone.utc) + timedelta(seconds=MUTE_SECONDS)
        await context.bot.restrict_chat_member(
            chat.id,
            user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
        # Inform chat and give admins an inline unmute button
        mute_text = styled_card(
            "🔇 ᴜsᴇʀ ᴍᴜᴛᴇᴅ",
            f"ᴜsᴇʀ <code>{user_id}</code> ᴋᴏ {MUTE_SECONDS // 60} ᴍɪɴ ᴋᴇ ʟɪʏᴇ ᴍᴜᴛᴇ ᴋɪʏᴀ ɢᴀʏᴀ.",
        )
        await context.bot.send_message(
            chat.id,
            mute_text,
            parse_mode="HTML",
            reply_markup=unmute_keyboard(user_id),
        )
    except (Forbidden, BadRequest, RetryAfter) as exc:
        LOGGER.warning("mute_failed chat=%s user=%s err=%s", chat.id, user_id, exc)
