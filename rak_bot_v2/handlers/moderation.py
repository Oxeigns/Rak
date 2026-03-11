"""Message moderation handlers — zero-bypass, full security for all senders."""

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
from rak_bot_v2.utils.helpers import safe_delete, safe_handler

LOGGER = logging.getLogger(__name__)

# ── Sender type constants (for logs & action routing) ─────────────────────
_ROLE_OWNER         = "owner"
_ROLE_ADMIN         = "admin"
_ROLE_BOT           = "bot"
_ROLE_ANON_ADMIN    = "anonymous_admin"   # group posting as itself
_ROLE_LINKED_CH     = "linked_channel"    # linked channel auto-post
_ROLE_MEMBER        = "member"


# ══════════════════════════════════════════════════════════════════════════
#  PUBLIC HANDLERS
# ══════════════════════════════════════════════════════════════════════════

@safe_handler
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Moderate ALL incoming group messages.
    ─────────────────────────────────────────────────────────────────
    WHO gets moderated:
      • Regular members          – full pipeline (warn / delete / mute)
      • Admins & Owner           – full pipeline (no bypass)
      • Other bots               – full pipeline (delete only, no mute)
      • Anonymous admins         – full pipeline (delete only)
      • Linked-channel posts     – full pipeline (delete only)
    WHO is always skipped:
      • THIS bot's own messages  – to prevent infinite reply loops
    ─────────────────────────────────────────────────────────────────
    """
    if not update:
        return

    msg  = update.effective_message
    chat = update.effective_chat
    if not msg or not chat or chat.type == "private":
        return

    user = msg.from_user

    # ── Skip only THIS bot's own replies (loop guard) ──────────────────────
    if user and user.id == context.bot.id:
        return

    # ── Classify the sender ────────────────────────────────────────────────
    sender_type = await _classify_sender(update, context)
    if sender_type is None:
        # Truly unresolvable sender (should not happen in practice)
        LOGGER.debug("unresolvable_sender_type chat=%s", chat.id)
        return

    store = context.application.bot_data.get("store")
    if not store:
        LOGGER.error("store_not_initialized")
        return
    await store.track_chat(chat.id, chat.type)

    # ── Run moderation pipeline (no role bypass) ──────────────────────────
    result = await _moderate_content(update, context)
    if result.action == "allow":
        return

    # Determine actor id/name for logging
    actor_id   = user.id if user else (msg.sender_chat.id if msg.sender_chat else None)
    actor_name = (
        user.username if user
        else (msg.sender_chat.username or msg.sender_chat.title if msg.sender_chat else None)
    )

    await _log_violation(
        context=context,
        chat_id=chat.id,
        message_id=msg.message_id,
        actor_id=actor_id,
        actor_name=actor_name,
        sender_type=sender_type,
        reason=result.reason,
    )

    # ── Apply action ───────────────────────────────────────────────────────
    if result.action == "warn":
        # Warn action: send warning, DO NOT delete the message
        await _send_warning_message(context, msg, result.reason, sender_type)
        return

    if result.action == "delete":
        await safe_delete(context, chat.id, msg.message_id)
        await _send_warning_message(context, msg, result.reason, sender_type)

        # Warning counter + mute only for human users (regular, admin, owner)
        # Bots, anonymous admins, linked channels cannot be muted via restrict_chat_member
        if user and not user.is_bot:
            warnings = await store.increment_warning(chat.id, user.id)
            if warnings >= MAX_WARNINGS:
                muted = await _mute_user(context, chat.id, user.id, sender_type)
                if muted:
                    await store.reset_warning(chat.id, user.id)


@safe_handler
async def handle_edited(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Moderate edited messages.
    NO role bypass — admins, owners, bots all have edits checked.
    Deletion is only scheduled when the edited content is actually flagged.
    """
    msg = update.edited_message
    if not msg or not update.effective_chat:
        return

    user = msg.from_user
    # Skip only this bot's own edits
    if user and user.id == context.bot.id:
        return

    result = await _moderate_content(update, context)
    if result.action == "allow":
        return  # Clean edit – no action needed

    # Schedule deletion for flagged edits
    if context.job_queue:
        context.job_queue.run_once(
            _delete_job,
            EDIT_DELETE_DELAY_SECONDS,
            data={
                "chat_id": update.effective_chat.id,
                "message_id": msg.message_id,
            },
        )
    await _send_warning_message(context, msg, result.reason, _ROLE_MEMBER)


@safe_handler
async def handle_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Scan every joining member's display name and username for suspicious
    patterns. Includes bots added to the group.
    """
    msg = update.effective_message
    if not msg or not msg.new_chat_members:
        return

    settings = context.application.bot_data.get("settings") or get_settings()

    for member in msg.new_chat_members:
        # Skip our own bot joining
        if member.id == context.bot.id:
            continue

        display = f"{member.full_name} {member.username or ''}".lower()
        is_suspicious = any(word in display for word in SUSPICIOUS_WORDS)

        if is_suspicious:
            await safe_delete(context, msg.chat_id, msg.message_id)

            # Restrict the suspicious new member (works for bots too)
            try:
                await context.bot.restrict_chat_member(
                    msg.chat_id,
                    member.id,
                    permissions=ChatPermissions(can_send_messages=False),
                )
                LOGGER.info("suspicious_join_restricted user=%s chat=%s", member.id, msg.chat_id)
            except (Forbidden, BadRequest, RetryAfter) as exc:
                LOGGER.warning(
                    "restrict_suspicious_user_failed user=%s err=%s", member.id, exc
                )

            # Log to configured log group
            try:
                label = "🤖 Bot" if member.is_bot else "👤 User"
                await context.bot.send_message(
                    settings.log_group_id,
                    (
                        f"🚫 <b>Suspicious join restricted</b>\n"
                        f"type={label}\n"
                        f"user_id={member.id}\n"
                        f"name={member.full_name}\n"
                        f"chat_id={msg.chat_id}"
                    ),
                    parse_mode="HTML",
                )
            except (Forbidden, BadRequest, RetryAfter) as exc:
                LOGGER.warning("log_failed: %s", exc)


# ══════════════════════════════════════════════════════════════════════════
#  SENDER CLASSIFICATION
# ══════════════════════════════════════════════════════════════════════════

async def _classify_sender(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> str | None:
    """
    Return a string label for who sent the message.
    Returns None only for genuinely unclassifiable senders.

    sender_chat logic:
      • sender_chat.id == chat.id  → anonymous admin (group posting as itself)
      • sender_chat.id != chat.id  → linked channel auto-post (different chat)
    """
    msg  = update.effective_message
    chat = update.effective_chat
    user = msg.from_user if msg else None

    if not msg or not chat:
        return None

    # ── sender_chat (no from_user) ─────────────────────────────────────────
    if msg.sender_chat and not user:
        if msg.sender_chat.id == chat.id:
            return _ROLE_ANON_ADMIN
        return _ROLE_LINKED_CH

    if not user:
        return None

    # ── Bot (other than us) ────────────────────────────────────────────────
    if user.is_bot:
        return _ROLE_BOT

    # ── Human users ───────────────────────────────────────────────────────
    settings = get_settings()
    if user.id == settings.owner_id:
        return _ROLE_OWNER

    try:
        from telegram import ChatMemberAdministrator, ChatMemberOwner
        member = await context.bot.get_chat_member(chat.id, user.id)
        if isinstance(member, (ChatMemberAdministrator, ChatMemberOwner)):
            return _ROLE_ADMIN
    except (Forbidden, BadRequest):
        pass

    return _ROLE_MEMBER


# ══════════════════════════════════════════════════════════════════════════
#  VIOLATION LOGGING
# ══════════════════════════════════════════════════════════════════════════

async def _log_violation(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    actor_id: int | None,
    actor_name: str | None,
    sender_type: str,
    reason: str,
) -> None:
    """Send a structured violation log to the admin log group."""
    settings = context.application.bot_data.get("settings")
    if not settings:
        return

    actor  = str(actor_id) if actor_id is not None else "unknown"
    handle = f"@{actor_name}" if actor_name else "-"
    role_emoji = {
        _ROLE_OWNER:      "👑",
        _ROLE_ADMIN:      "🛡",
        _ROLE_BOT:        "🤖",
        _ROLE_ANON_ADMIN: "👥",
        _ROLE_LINKED_CH:  "📢",
        _ROLE_MEMBER:     "👤",
    }.get(sender_type, "❓")

    try:
        await context.bot.send_message(
            settings.log_group_id,
            (
                f"🚨 <b>moderation_violation</b>\n"
                f"chat_id=<code>{chat_id}</code>\n"
                f"message_id=<code>{message_id}</code>\n"
                f"actor_id=<code>{actor}</code>\n"
                f"actor=<code>{handle}</code>\n"
                f"role={role_emoji} {sender_type}\n"
                f"reason={reason}"
            ),
            parse_mode="HTML",
        )
    except (Forbidden, BadRequest, RetryAfter) as exc:
        LOGGER.warning("log_violation_failed: %s", exc)


# ══════════════════════════════════════════════════════════════════════════
#  WARNING MESSAGES
# ══════════════════════════════════════════════════════════════════════════

async def _send_warning_message(
    context: ContextTypes.DEFAULT_TYPE,
    msg,
    reason: str,
    sender_type: str,
) -> None:
    """
    Send a warning reply and auto-delete it after WARNING_DELETE_DELAY_SECONDS.
    For bots and channel posts a simpler card is shown (no mention tag).
    """
    warn_text = styled_card("⚠️ ᴡᴀʀɴɪɴɢ", f"ʀᴇᴀsᴏɴ: {reason}")
    try:
        warn_msg = await msg.reply_text(warn_text, parse_mode="HTML")
        # Tracked task — cancelled cleanly on shutdown
        context.application.create_task(
            _auto_delete_after(warn_msg, WARNING_DELETE_DELAY_SECONDS)
        )
    except (Forbidden, BadRequest, RetryAfter) as exc:
        LOGGER.warning("warning_send_failed: %s", exc)


async def _auto_delete_after(msg, delay_seconds: int) -> None:
    """Best-effort auto-deletion after a delay."""
    await asyncio.sleep(delay_seconds)
    try:
        await msg.delete()
    except Exception as exc:  # noqa: BLE001
        LOGGER.debug(
            "auto_delete_failed chat=%s msg=%s err=%s",
            msg.chat_id, msg.message_id, exc,
        )


# ══════════════════════════════════════════════════════════════════════════
#  JOB QUEUE CALLBACK
# ══════════════════════════════════════════════════════════════════════════

async def _delete_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job-queue callback for scheduled message deletion (used by handle_edited)."""
    try:
        job_data = context.job.data if context.job else None
        if not isinstance(job_data, dict):
            LOGGER.error("invalid_job_data: %s", job_data)
            return
        await safe_delete(context, int(job_data["chat_id"]), int(job_data["message_id"]))
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("delete_job_failed: %s", exc)


# ══════════════════════════════════════════════════════════════════════════
#  CONTENT MODERATION PIPELINE
# ══════════════════════════════════════════════════════════════════════════

async def _moderate_content(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> ModerationResult:
    """
    Four-stage pipeline — runs on ALL sender types:

    Stage 1  →  Cache hit (known-illegal text hash)          [instant]
    Stage 2  →  Blacklist / Whitelist word match             [instant]
    Stage 3  →  Deep regex scan inside AI service            [instant]
    Stage 4  →  AI model call (Groq / Gemini)               [async]

    Supported content:
      • Plain text            • Photos
      • Stickers              • Animations / GIFs
      • Documents             • Videos (caption only)
      • Voice messages        • Audio files
      • Linked channel posts  • Bot-generated messages
    """
    msg   = update.effective_message
    ai    = context.application.bot_data.get("ai")
    cache = context.application.bot_data.get("cache")

    if not msg:
        return ModerationResult(action="allow", reason="No message")

    text_payload = (msg.text or msg.caption or "").strip()

    # ── Stage 1 & 2: Local cache + word lists ─────────────────────────────
    if text_payload:
        if cache and await cache.is_text_cached_illegal(text_payload):
            return ModerationResult(action="delete", reason="Cached illegal content")

        if cache and await cache.contains_blacklist_word(text_payload):
            await cache.save_illegal_text(text_payload)
            return ModerationResult(action="delete", reason="Blacklisted word detected")

        if cache and await cache.contains_whitelist_word(text_payload):
            return ModerationResult(action="allow", reason="Whitelisted content")

    # ── Stage 3 & 4: AI pipeline ──────────────────────────────────────────
    if not ai:
        return ModerationResult(action="allow", reason="AI unavailable")

    try:
        # Photo
        if msg.photo:
            return await _moderate_photo(update, context)

        # Sticker
        if msg.sticker:
            return await _moderate_downloaded_media(
                context, ai, msg.sticker.file_id, "image/webp", text_payload
            )

        # Animation / GIF
        if msg.animation:
            return await _moderate_downloaded_media(
                context, ai, msg.animation.file_id,
                msg.animation.mime_type or "video/mp4", text_payload,
            )

        # Document (any file)
        if msg.document:
            return await _moderate_downloaded_media(
                context, ai, msg.document.file_id,
                msg.document.mime_type or "application/octet-stream", text_payload,
            )

        # Video — too large to download; caption/text is checked
        if msg.video:
            return await _moderate_text_only(ai, cache, text_payload)

        # Voice message — caption/text checked
        if msg.voice:
            return await _moderate_text_only(ai, cache, text_payload)

        # Audio — caption/text checked
        if msg.audio:
            return await _moderate_text_only(ai, cache, text_payload)

        # Video note (round video)
        if msg.video_note:
            # No caption possible; allow unless there is text
            if text_payload:
                return await _moderate_text_only(ai, cache, text_payload)
            return ModerationResult(action="allow", reason="Video note – no text")

        # Plain text (no media)
        if text_payload:
            return await _moderate_text_only(ai, cache, text_payload)

    except Exception as exc:  # noqa: BLE001
        LOGGER.exception(
            "moderation_pipeline_failed chat=%s msg=%s err=%s",
            update.effective_chat.id if update.effective_chat else None,
            msg.message_id, exc,
        )

    return ModerationResult(action="allow", reason="Unsupported content type")


async def _moderate_text_only(ai, cache, text_payload: str) -> ModerationResult:
    """Helper: run AI text moderation and cache illegal results."""
    if not text_payload:
        return ModerationResult(action="allow", reason="No text payload")
    result = await ai.moderate_text(text_payload)
    if cache and result.action == "delete":
        await cache.save_illegal_text(text_payload)
    return result


async def _moderate_photo(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> ModerationResult:
    """Perceptual-hash cache check → AI image analysis → caption check."""
    msg   = update.effective_message
    ai    = context.application.bot_data.get("ai")
    cache = context.application.bot_data.get("cache")

    if not msg or not msg.photo or not ai:
        return ModerationResult(action="allow", reason="No photo data")

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
        LOGGER.warning("photo_moderation_failed: %s", exc)
        return ModerationResult(action="allow", reason="Photo processing failed")


async def _moderate_downloaded_media(
    context: ContextTypes.DEFAULT_TYPE,
    ai,
    file_id: str,
    mime_type: str,
    caption: str = "",
) -> ModerationResult:
    """Download a Telegram file and run AI moderation on the bytes."""
    try:
        file = await context.bot.get_file(file_id)
        blob = bytes(await file.download_as_bytearray())
        return await ai.moderate_media(blob, mime_type, caption)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("media_download_moderation_failed: %s", exc)
        return ModerationResult(action="allow", reason="Media download failed")


# ══════════════════════════════════════════════════════════════════════════
#  MUTE HELPER
# ══════════════════════════════════════════════════════════════════════════

async def _mute_user(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sender_type: str,
) -> bool:
    """
    Apply a temporary mute and send an inline unmute button.

    Returns True  → mute was applied successfully.
    Returns False → Telegram rejected it (e.g. user is admin with
                    'restrict members' permission locked).

    NOTE: Telegram allows restricting admins IF the bot was promoted with
    the 'restrict_members' right AND the admin's rights were not set by the
    bot itself. If it fails, we log and move on — the warning counter is
    NOT reset so future violations still accumulate.
    """
    until = datetime.now(timezone.utc) + timedelta(seconds=MUTE_SECONDS)
    try:
        await context.bot.restrict_chat_member(
            chat_id,
            user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
        role_label = {
            _ROLE_OWNER:  "👑 ᴏᴡɴᴇʀ",
            _ROLE_ADMIN:  "🛡 ᴀᴅᴍɪɴ",
            _ROLE_MEMBER: "👤 ᴜsᴇʀ",
        }.get(sender_type, "👤 ᴜsᴇʀ")

        mute_text = styled_card(
            "🔇 ᴍᴜᴛᴇᴅ",
            f"{role_label} <code>{user_id}</code> ᴋᴏ "
            f"{MUTE_SECONDS // 60} ᴍɪɴ ᴋᴇ ʟɪʏᴇ ᴍᴜᴛᴇ ᴋɪʏᴀ ɢᴀʏᴀ.\n"
            f"({MAX_WARNINGS} ᴡᴀʀɴɪɴɢs ᴘᴀᴀʀ ʜᴏ ɢɪ)",
        )
        await context.bot.send_message(
            chat_id,
            mute_text,
            parse_mode="HTML",
            reply_markup=unmute_keyboard(user_id),
        )
        LOGGER.info("muted user=%s chat=%s role=%s duration=%ss",
                    user_id, chat_id, sender_type, MUTE_SECONDS)
        return True

    except (Forbidden, BadRequest, RetryAfter) as exc:
        LOGGER.warning(
            "mute_failed chat=%s user=%s role=%s err=%s",
            chat_id, user_id, sender_type, exc,
        )
        # Inform chat that mute could not be applied (helpful for admins)
        try:
            await context.bot.send_message(
                chat_id,
                styled_card(
                    "⚠️ ᴍᴜᴛᴇ ꜰᴀɪʟᴇᴅ",
                    f"ᴜsᴇʀ <code>{user_id}</code> ᴋᴏ ᴍᴜᴛᴇ ɴᴀʜɪ ᴋɪʏᴀ — "
                    f"ʙᴏᴛ ᴋᴏ ᴘᴜʀᴀ ᴀᴅᴍɪɴ ᴘᴇʀᴍɪssɪᴏɴ ᴅᴏ ʏᴀ ᴜsᴇʀ ᴋᴏ ᴍᴀɴᴜᴀʟʟʏ ʀᴇsᴛʀɪᴄᴛ ᴋᴀʀᴏ.",
                ),
                parse_mode="HTML",
            )
        except Exception:  # noqa: BLE001
            pass
        return False
