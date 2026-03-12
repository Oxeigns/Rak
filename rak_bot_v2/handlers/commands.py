"""Command handlers."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from telegram import ChatPermissions, Update
from telegram.error import BadRequest, Forbidden, RetryAfter
from telegram.ext import ContextTypes

from rak_bot_v2.config.constants import (
    BAN_SECONDS,
    BROADCAST_DELAY_SECONDS,
    MAX_DELETE_DELAY_SECONDS,
    MAX_WARNINGS,
    MIN_DELETE_DELAY_SECONDS,
    MUTE_SECONDS,
)
from rak_bot_v2.config.settings import get_settings
from rak_bot_v2.utils.formatters import (
    add_to_group_keyboard,
    verify_keyboard,
    help_text,
    panel_keyboard,
    styled_card,
    unmute_keyboard,
    warn_keyboard,
)
from rak_bot_v2.utils.helpers import (
    enforce_force_join,
    get_reply_target,
    is_admin,
    is_target_admin,
    safe_handler,
)

LOGGER = logging.getLogger(__name__)


# ── Start / Help ───────────────────────────────────────────────────────────

@safe_handler
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /start with specialized logic for DM vs Group.
    Includes Force-Join security and Dynamic UI.
    """
    if not update.effective_message or not update.effective_chat or not update.effective_user:
        return

    settings = get_settings()
    user = update.effective_user
    chat = update.effective_chat

    # 1. Security Check: Force Join
    is_joined = await enforce_force_join(update, context, settings.force_channel_id)
    if not is_joined:
        await update.effective_message.reply_text(
            styled_card(
                "ACCESS DENIED",
                "Join the official channel first, then tap VERIFY to continue.",
            ),
            reply_markup=verify_keyboard(),
            parse_mode="HTML",
        )
        return

    # 2. Handle Private DM
    if chat.type == "private":
        me = await context.bot.get_me()
        welcome_text = (
            f"Hello <b>{user.first_name}</b>!\n\n"
            "I am AI Governor, the most advanced group moderation bot.\n\n"
            "<b>Features:</b>\n"
            "• AI-Powered Spam Protection\n"
            "• Image & Sticker Moderation\n"
            "• Zero-Bypass Security\n"
            "• Performance Statistics\n\n"
            "Click below to add me to your group!"
        )
        await update.effective_message.reply_text(
            styled_card("WELCOME", welcome_text),
            parse_mode="HTML",
            reply_markup=add_to_group_keyboard(me.username),
        )
        return

    # 3. Handle Group/Supergroup
    if not await is_admin(update, context):
        await update.effective_message.reply_text(
            f"Hello {user.first_name}! Bot active.",
            parse_mode="HTML",
        )
        return

    # Show colored admin panel immediately if sender is admin
    await update.effective_message.reply_text(
        styled_card(
            "ADMIN CONTROL PANEL",
            "Select an option below to configure moderation for this group."
        ),
        reply_markup=panel_keyboard(),
        parse_mode="HTML",
    )


@safe_handler
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show full command list."""
    if not update.effective_message:
        return
    await update.effective_message.reply_text(help_text(), parse_mode="HTML")


# ── Admin Panel ────────────────────────────────────────────────────────────

@safe_handler
async def panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show admin control panel."""
    if not update.effective_message or not update.effective_chat:
        return
    if not await is_admin(update, context):
        await update.effective_message.reply_text(
            styled_card("FORBIDDEN", "This panel is restricted to chat administrators."),
            parse_mode="HTML",
        )
        return
    await update.effective_message.reply_text(
        styled_card(
            "ADMIN PANEL",
            "Use the buttons below to manage system settings and view group data."
        ),
        reply_markup=panel_keyboard(),
        parse_mode="HTML",
    )


# ── Set Delay ──────────────────────────────────────────────────────────────

@safe_handler
async def set_delay_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Update auto-delete delay for this group."""
    if not update.effective_chat or not update.effective_message:
        return
    if not await is_admin(update, context):
        await update.effective_message.reply_text(
            styled_card("FORBIDDEN", "Only admins can change the deletion delay."),
            parse_mode="HTML",
        )
        return
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text(
            styled_card("INVALID", "Usage: <code>/setdelay [seconds]</code>\nRange: 1 to 86400"),
            parse_mode="HTML",
        )
        return

    seconds = int(context.args[0])
    if seconds < MIN_DELETE_DELAY_SECONDS or seconds > MAX_DELETE_DELAY_SECONDS:
        await update.effective_message.reply_text(
            styled_card("INVALID", "Delay must be between 1 and 86400 seconds."),
            parse_mode="HTML",
        )
        return

    store = context.application.bot_data.get("store")
    if store:
        await store.set_delete_delay(update.effective_chat.id, seconds)
    await update.effective_message.reply_text(
        styled_card("SUCCESS", f"Auto-delete delay updated to {seconds} seconds."),
        parse_mode="HTML",
    )


# ── Owner Commands ─────────────────────────────────────────────────────────

@safe_handler
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show bot statistics for owner."""
    settings = get_settings()
    if not update.effective_message or not update.effective_user:
        return
    if update.effective_user.id != settings.owner_id:
        await update.effective_message.reply_text(
            styled_card("FORBIDDEN", "This command is restricted to the bot owner."),
            parse_mode="HTML",
        )
        return
    store = context.application.bot_data.get("store")
    cache = context.application.bot_data.get("cache")
    total_chats = len(await store.get_all_chats()) if store else 0
    total_warn = await store.get_total_warnings() if store else 0
    cached_texts = cache.cached_text_count if cache else 0
    cached_imgs = cache.cached_image_count if cache else 0
    text = styled_card(
        "STATISTICS",
        (
            f"Total Chats: {total_chats}\n"
            f"Cached Texts: {cached_texts}\n"
            f"Cached Images: {cached_imgs}\n"
            f"Global Warnings: {total_warn}"
        ),
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")


@safe_handler
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Broadcast owner-provided message to all tracked chats."""
    settings = get_settings()
    if not update.effective_message or not update.effective_user:
        return
    if update.effective_user.id != settings.owner_id:
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: <code>/broadcast [message]</code>", parse_mode="HTML")
        return

    store = context.application.bot_data.get("store")
    chats = await store.get_all_chats() if store else []
    sent = 0
    failed = 0
    broadcast_text = " ".join(context.args)
    for chat_id, _chat_type in chats:
        try:
            await context.bot.send_message(chat_id, broadcast_text, parse_mode="HTML")
            sent += 1
            await asyncio.sleep(BROADCAST_DELAY_SECONDS)
        except Exception:  # noqa: BLE001
            failed += 1

    await update.effective_message.reply_text(
        styled_card("BROADCAST COMPLETE", f"Sent: {sent}\nFailed: {failed}"),
        parse_mode="HTML",
    )


@safe_handler
async def reload_words_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reload cache word lists without restart for owner."""
    settings = get_settings()
    if not update.effective_message or not update.effective_user:
        return
    if update.effective_user.id != settings.owner_id:
        return
    cache = context.application.bot_data.get("cache")
    if not cache:
        return
    await cache.reload_word_lists()
    await update.effective_message.reply_text(styled_card("SUCCESS", "Word lists reloaded."), parse_mode="HTML")


# ── Warn / Unwarn ──────────────────────────────────────────────────────────

@safe_handler
async def warn_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Warn a user (reply to their message)."""
    if not update.effective_chat or not update.effective_message:
        return
    if not await is_admin(update, context):
        await update.effective_message.reply_text(
            styled_card("FORBIDDEN", "Only admins can issue warnings."), parse_mode="HTML"
        )
        return

    target = get_reply_target(update)
    if not target:
        await update.effective_message.reply_text(
            styled_card("INVALID", "Reply to a message to warn that user."), parse_mode="HTML"
        )
        return

    if await is_target_admin(update.effective_chat.id, target.id, context):
        await update.effective_message.reply_text(
            styled_card("FORBIDDEN", "You cannot warn another administrator."), parse_mode="HTML"
        )
        return

    store = context.application.bot_data.get("store")
    warnings = await store.increment_warning(update.effective_chat.id, target.id) if store else 1
    action = ""
    if warnings >= MAX_WARNINGS:
        until = datetime.now(timezone.utc) + timedelta(seconds=MUTE_SECONDS)
        try:
            await context.bot.restrict_chat_member(
                update.effective_chat.id,
                target.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
            if store:
                await store.reset_warning(update.effective_chat.id, target.id)
            warnings = 0
            action = "\n\n<b>Warning limit reached. User has been muted.</b>"
        except (Forbidden, BadRequest, RetryAfter) as exc:
            LOGGER.warning("warn_auto_mute_failed user=%s err=%s", target.id, exc)
            action = "\n\n<b>Warning limit reached, but auto-mute failed. Warning counter kept.</b>"
            await update.effective_message.reply_text(
                styled_card(
                    "MUTE FAILED",
                    f"Could not mute user <code>{target.id}</code>. Check bot permissions.",
                ),
                parse_mode="HTML",
            )

    await update.effective_message.reply_text(
        styled_card(
            "WARNING ISSUED",
            f"{target.mention_html()} has been warned.\nStatus: {warnings}/{MAX_WARNINGS}{action}",
        ),
        parse_mode="HTML",
        reply_markup=warn_keyboard(target.id),
    )


@safe_handler
async def unwarn_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove one warning from a user (reply to their message)."""
    if not update.effective_chat or not update.effective_message:
        return
    if not await is_admin(update, context):
        await update.effective_message.reply_text(
            styled_card("FORBIDDEN", "Only admins can remove warnings."), parse_mode="HTML"
        )
        return

    target = get_reply_target(update)
    if not target:
        await update.effective_message.reply_text(
            styled_card("INVALID", "Reply to a message to remove warnings."), parse_mode="HTML"
        )
        return

    store = context.application.bot_data.get("store")
    if store:
        await store.reset_warning(update.effective_chat.id, target.id)

    await update.effective_message.reply_text(
        styled_card("SUCCESS", f"All warnings removed for {target.mention_html()}."),
        parse_mode="HTML",
    )


# ── Mute / Unmute ──────────────────────────────────────────────────────────

@safe_handler
async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mute a user temporarily (reply to their message)."""
    if not update.effective_chat or not update.effective_message:
        return
    if not await is_admin(update, context):
        await update.effective_message.reply_text(
            styled_card("FORBIDDEN", "Only admins can mute users."), parse_mode="HTML"
        )
        return

    target = get_reply_target(update)
    if not target:
        await update.effective_message.reply_text(
            styled_card("INVALID", "Reply to a message to mute that user."), parse_mode="HTML"
        )
        return

    if await is_target_admin(update.effective_chat.id, target.id, context):
        await update.effective_message.reply_text(
            styled_card("FORBIDDEN", "You cannot mute another administrator."), parse_mode="HTML"
        )
        return

    until = datetime.now(timezone.utc) + timedelta(seconds=MUTE_SECONDS)
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
        await update.effective_message.reply_text(
            styled_card(
                "USER MUTED",
                f"{target.mention_html()} has been muted for {MUTE_SECONDS // 60} minutes.",
            ),
            parse_mode="HTML",
            reply_markup=unmute_keyboard(target.id),
        )
    except (Forbidden, BadRequest, RetryAfter) as exc:
        LOGGER.warning("mute_cmd_failed user=%s err=%s", target.id, exc)
        await update.effective_message.reply_text(
            styled_card("ERROR", "Failed to mute user. Ensure bot has permissions."), parse_mode="HTML"
        )


@safe_handler
async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unmute a user (reply to their message)."""
    if not update.effective_chat or not update.effective_message:
        return
    if not await is_admin(update, context):
        await update.effective_message.reply_text(
            styled_card("FORBIDDEN", "Only admins can unmute users."), parse_mode="HTML"
        )
        return

    target = get_reply_target(update)
    if not target:
        await update.effective_message.reply_text(
            styled_card("INVALID", "Reply to a message to unmute that user."), parse_mode="HTML"
        )
        return

    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            target.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_audios=True,
                can_send_documents=True,
            ),
        )
        await update.effective_message.reply_text(
            styled_card("USER UNMUTED", f"{target.mention_html()} can now speak."),
            parse_mode="HTML",
        )
    except (Forbidden, BadRequest, RetryAfter) as exc:
        LOGGER.warning("unmute_cmd_failed user=%s err=%s", target.id, exc)
        await update.effective_message.reply_text(
            styled_card("ERROR", "Failed to unmute user."), parse_mode="HTML"
        )


# ── Kick ───────────────────────────────────────────────────────────────────

@safe_handler
async def kick_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Kick a user (reply to their message)."""
    if not update.effective_chat or not update.effective_message:
        return
    if not await is_admin(update, context):
        await update.effective_message.reply_text(
            styled_card("FORBIDDEN", "Only admins can kick users."), parse_mode="HTML"
        )
        return

    target = get_reply_target(update)
    if not target:
        await update.effective_message.reply_text(
            styled_card("INVALID", "Reply to a message to kick that user."), parse_mode="HTML"
        )
        return

    if await is_target_admin(update.effective_chat.id, target.id, context):
        await update.effective_message.reply_text(
            styled_card("FORBIDDEN", "You cannot kick another administrator."), parse_mode="HTML"
        )
        return

    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await asyncio.sleep(1)
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.effective_message.reply_text(
            styled_card("USER KICKED", f"{target.mention_html()} has been removed."),
            parse_mode="HTML",
        )
    except (Forbidden, BadRequest, RetryAfter) as exc:
        LOGGER.warning("kick_cmd_failed user=%s err=%s", target.id, exc)
        await update.effective_message.reply_text(
            styled_card("ERROR", "Failed to kick user."), parse_mode="HTML"
        )


# ── Ban / Unban ────────────────────────────────────────────────────────────

@safe_handler
async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Permanently ban a user (reply to their message)."""
    if not update.effective_chat or not update.effective_message:
        return
    if not await is_admin(update, context):
        await update.effective_message.reply_text(
            styled_card("FORBIDDEN", "Only admins can ban users."), parse_mode="HTML"
        )
        return

    target = get_reply_target(update)
    if not target:
        await update.effective_message.reply_text(
            styled_card("INVALID", "Reply to a message to ban that user."), parse_mode="HTML"
        )
        return

    if await is_target_admin(update.effective_chat.id, target.id, context):
        await update.effective_message.reply_text(
            styled_card("FORBIDDEN", "You cannot ban another administrator."), parse_mode="HTML"
        )
        return

    reason = " ".join(context.args) if context.args else "No reason provided"
    try:
        until_date = (
            datetime.now(timezone.utc) + timedelta(seconds=BAN_SECONDS)
            if BAN_SECONDS > 0
            else None
        )
        await context.bot.ban_chat_member(
            update.effective_chat.id, target.id, until_date=until_date
        )
        await update.effective_message.reply_text(
            styled_card(
                "USER BANNED",
                f"{target.mention_html()} banned permanently.\nReason: {reason}",
            ),
            parse_mode="HTML",
        )
    except (Forbidden, BadRequest, RetryAfter) as exc:
        LOGGER.warning("ban_cmd_failed user=%s err=%s", target.id, exc)
        await update.effective_message.reply_text(
            styled_card("ERROR", "Failed to ban user."), parse_mode="HTML"
        )


@safe_handler
async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unban a previously banned user."""
    if not update.effective_chat or not update.effective_message:
        return
    if not await is_admin(update, context):
        await update.effective_message.reply_text(
            styled_card("FORBIDDEN", "Only admins can unban users."), parse_mode="HTML"
        )
        return

    target = get_reply_target(update)
    if not target:
        await update.effective_message.reply_text(
            styled_card("INVALID", "Reply to their message/forward to unban."), parse_mode="HTML"
        )
        return

    try:
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.effective_message.reply_text(
            styled_card("USER UNBANNED", f"{target.mention_html()} is now unbanned."),
            parse_mode="HTML",
        )
    except (Forbidden, BadRequest, RetryAfter) as exc:
        LOGGER.warning("unban_cmd_failed user=%s err=%s", target.id, exc)
        await update.effective_message.reply_text(
            styled_card("ERROR", "Failed to unban user."), parse_mode="HTML"
        )
