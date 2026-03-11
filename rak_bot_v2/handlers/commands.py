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
    force_join_keyboard,
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
    """Handle /start in DM and groups."""
    settings = get_settings()
    if not update.effective_message or not update.effective_chat:
        return

    is_joined = await enforce_force_join(update, context, settings.force_channel_id)
    if not is_joined:
        await update.effective_message.reply_text(
            styled_card("🚫 ɴᴏ ᴀᴄᴄᴇss", "ᴘᴇʜʟᴇ ᴄʜᴀɴɴᴇʟ ᴊᴏɪɴ ᴋᴀʀᴏ, ᴘʜɪʀ ᴠᴇʀɪғʏ ᴅᴀʙᴀᴏ."),
            reply_markup=force_join_keyboard(str(settings.force_channel_link)),
            parse_mode="HTML",
        )
        return

    if update.effective_chat.type == "private":
        me = await context.bot.get_me()
        await update.effective_message.reply_text(
            styled_card("ᴡᴇʟᴄᴏᴍᴇ", "ᴍᴇɪɴ ᴀɪ ɢᴏᴠᴇʀɴᴏʀ ʙᴏᴛ ʜᴜɴ. ɢʀᴏᴜᴘ ᴍᴇɪɴ ᴀᴅᴅ ᴋᴀʀᴏ ✓"),
            parse_mode="HTML",
            reply_markup=add_to_group_keyboard(me.username),
        )
        return

    await panel_command(update, context)


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
    if not update.effective_message:
        return
    if not await is_admin(update, context):
        await update.effective_message.reply_text(
            styled_card("🚫 ɴᴏ ᴀᴄᴄᴇss", "ʏᴇʜ ᴘᴀɴᴇʟ ꜱɪʀꜰ ᴀᴅᴍɪɴ ᴋᴇ ʟɪʏᴇ ʜᴀɪ."),
            parse_mode="HTML",
        )
        return
    await update.effective_message.reply_text(
        styled_card(
            "ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ",
            "• /setdelay &lt;sec&gt;\n• /ban /kick /mute\n• ᴠᴇʀɪғʏ ᴊᴏɪɴ\n• ᴍᴏᴅᴇʀᴀᴛɪᴏɴ ᴏɴ",
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
            styled_card("🚫 ɴᴏ ᴀᴄᴄᴇss", "ꜱɪʀꜰ ᴀᴅᴍɪɴ ᴅᴇʟᴀʏ ʙᴀᴅᴀʟ ꜱᴀᴋᴛᴀ ʜᴀɪ."),
            parse_mode="HTML",
        )
        return
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text(
            styled_card("ɪɴᴠᴀʟɪᴅ", "ᴜsᴇ: /setdelay 1-86400"),
            parse_mode="HTML",
        )
        return

    seconds = int(context.args[0])
    if seconds < MIN_DELETE_DELAY_SECONDS or seconds > MAX_DELETE_DELAY_SECONDS:
        await update.effective_message.reply_text(
            styled_card("ɪɴᴠᴀʟɪᴅ", "ʀᴀɴɢᴇ 1 sᴇ 86400 sᴇᴄ ᴛᴀᴋ ʀᴀᴋʜᴏ."),
            parse_mode="HTML",
        )
        return

    store = context.application.bot_data.get("store")
    if store:
        await store.set_delete_delay(update.effective_chat.id, seconds)
    await update.effective_message.reply_text(
        styled_card("✓ sᴀᴠᴇᴅ", f"ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ ᴀʙ {seconds}s ʜᴏ ɢᴀʏᴀ."),
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
            styled_card("🚫 ꜰᴏʀʙɪᴅᴅᴇɴ", "ʏᴇʜ ᴄᴏᴍᴍᴀɴᴅ ꜱɪʀꜰ ᴏᴡɴᴇʀ ᴋᴇ ʟɪʏᴇ ʜᴀɪ."),
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
        "📊 ꜱᴛᴀᴛꜱ",
        (
            f"ᴛᴏᴛᴀʟ ᴄʜᴀᴛs: {total_chats}\n"
            f"ᴄᴀᴄʜᴇᴅ ᴛᴇxᴛs: {cached_texts}\n"
            f"ᴄᴀᴄʜᴇᴅ ɪᴍᴀɢᴇs: {cached_imgs}\n"
            f"ᴡᴀʀɴɪɴɢs: {total_warn}"
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
        await update.effective_message.reply_text("ᴜsᴀɢᴇ: /broadcast <ᴍᴇssᴀɢᴇ>")
        return

    store = context.application.bot_data.get("store")
    chats = await store.get_all_chats() if store else []
    sent = 0
    failed = 0
    for chat_id, _chat_type in chats:
        try:
            await context.bot.send_message(chat_id, " ".join(context.args), parse_mode="HTML")
            sent += 1
            await asyncio.sleep(BROADCAST_DELAY_SECONDS)
        except Exception:  # noqa: BLE001
            failed += 1

    await update.effective_message.reply_text(
        styled_card("✓ ʙʀᴏᴀᴅᴄᴀsᴛ ᴄᴏᴍᴘʟᴇᴛᴇ", f"sᴇɴᴛ: {sent}\nғᴀɪʟᴇᴅ: {failed}"),
        parse_mode="HTML",
    )


@safe_handler
async def reload_words_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reload cache word lists without restart for owner."""
    settings = get_settings()
    if not update.effective_message or not update.effective_user:
        return
    if update.effective_user.id != settings.owner_id:
        await update.effective_message.reply_text(
            styled_card("🚫 ꜰᴏʀʙɪᴅᴅᴇɴ", "ʏᴇʜ ᴄᴏᴍᴍᴀɴᴅ ꜱɪʀꜰ ᴏᴡɴᴇʀ ᴋᴇ ʟɪʏᴇ ʜᴀɪ."),
            parse_mode="HTML",
        )
        return
    cache = context.application.bot_data.get("cache")
    if not cache:
        await update.effective_message.reply_text(styled_card("⚠️", "Cache unavailable."), parse_mode="HTML")
        return
    await cache.reload_word_lists()
    await update.effective_message.reply_text(styled_card("✓", "Word lists reloaded."), parse_mode="HTML")


# ── Warn / Unwarn ──────────────────────────────────────────────────────────

@safe_handler
async def warn_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Warn a user (reply to their message)."""
    if not update.effective_chat or not update.effective_message:
        return
    if not await is_admin(update, context):
        await update.effective_message.reply_text(
            styled_card("🚫", "ꜱɪʀꜰ ᴀᴅᴍɪɴ ᴡᴀʀɴ ᴋᴀʀ ꜱᴀᴋᴛᴇ ʜᴀɪɴ."), parse_mode="HTML"
        )
        return

    target = get_reply_target(update)
    if not target:
        await update.effective_message.reply_text(
            styled_card("ɪɴᴠᴀʟɪᴅ", "ᴜsᴇʀ ᴋᴇ ᴍᴇssᴀɢᴇ ᴘᴀʀ ʀᴇᴘʟʏ ᴋᴀʀᴏ."), parse_mode="HTML"
        )
        return

    if await is_target_admin(update.effective_chat.id, target.id, context):
        await update.effective_message.reply_text(
            styled_card("🚫", "ᴀᴅᴍɪɴ ᴋᴏ ᴡᴀʀɴ ɴᴀʜɪ ᴋᴀʀ ꜱᴀᴋᴛᴇ."), parse_mode="HTML"
        )
        return

    store = context.application.bot_data.get("store")
    warnings = await store.increment_warning(update.effective_chat.id, target.id) if store else 1
    action = ""
    if warnings >= MAX_WARNINGS:
        warnings = 0
        if store:
            await store.reset_warning(update.effective_chat.id, target.id)
        action = "\n\n⚠️ ʟɪᴍɪᴛ ᴄʀᴏss! ᴜsᴇʀ ᴍᴜᴛᴇ ᴋɪʏᴀ ɢᴀʏᴀ."
        until = datetime.now(timezone.utc) + timedelta(seconds=MUTE_SECONDS)
        try:
            await context.bot.restrict_chat_member(
                update.effective_chat.id,
                target.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
        except (Forbidden, BadRequest, RetryAfter) as exc:
            LOGGER.warning("warn_auto_mute_failed user=%s err=%s", target.id, exc)
            action = "\n\n⚠️ ᴀᴜᴛᴏ-ᴍᴜᴛᴇ ꜰᴀɪʟᴇᴅ."

    await update.effective_message.reply_text(
        styled_card(
            "⚠️ ᴡᴀʀɴ",
            f"{target.mention_html()} ᴋᴏ ᴡᴀʀɴ ᴍɪʟᴀ.\nᴄᴏᴜɴᴛ: {warnings}/{MAX_WARNINGS}{action}",
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
            styled_card("🚫", "ꜱɪʀꜰ ᴀᴅᴍɪɴ ᴜɴᴡᴀʀɴ ᴋᴀʀ ꜱᴀᴋᴛᴇ ʜᴀɪɴ."), parse_mode="HTML"
        )
        return

    target = get_reply_target(update)
    if not target:
        await update.effective_message.reply_text(
            styled_card("ɪɴᴠᴀʟɪᴅ", "ᴜsᴇʀ ᴋᴇ ᴍᴇssᴀɢᴇ ᴘᴀʀ ʀᴇᴘʟʏ ᴋᴀʀᴏ."), parse_mode="HTML"
        )
        return

    store = context.application.bot_data.get("store")
    if store:
        await store.reset_warning(update.effective_chat.id, target.id)

    await update.effective_message.reply_text(
        styled_card("✓ ᴜɴᴡᴀʀɴ", f"{target.mention_html()} ᴋɪ ᴡᴀʀɴɪɴɢs ʜᴀᴛᴀ ᴅɪ."),
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
            styled_card("🚫", "ꜱɪʀꜰ ᴀᴅᴍɪɴ ᴍᴜᴛᴇ ᴋᴀʀ ꜱᴀᴋᴛᴇ ʜᴀɪɴ."), parse_mode="HTML"
        )
        return

    target = get_reply_target(update)
    if not target:
        await update.effective_message.reply_text(
            styled_card("ɪɴᴠᴀʟɪᴅ", "ᴜsᴇʀ ᴋᴇ ᴍᴇssᴀɢᴇ ᴘᴀʀ ʀᴇᴘʟʏ ᴋᴀʀᴏ."), parse_mode="HTML"
        )
        return

    if await is_target_admin(update.effective_chat.id, target.id, context):
        await update.effective_message.reply_text(
            styled_card("🚫", "ᴀᴅᴍɪɴ ᴋᴏ ᴍᴜᴛᴇ ɴᴀʜɪ ᴋᴀʀ ꜱᴀᴋᴛᴇ."), parse_mode="HTML"
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
                "🔇 ᴍᴜᴛᴇᴅ",
                f"{target.mention_html()} ᴋᴏ {MUTE_SECONDS // 60} ᴍɪɴ ᴋᴇ ʟɪʏᴇ ᴍᴜᴛᴇ ᴋɪʏᴀ.",
            ),
            parse_mode="HTML",
            reply_markup=unmute_keyboard(target.id),
        )
    except (Forbidden, BadRequest, RetryAfter) as exc:
        LOGGER.warning("mute_cmd_failed user=%s err=%s", target.id, exc)
        await update.effective_message.reply_text(
            styled_card("⚠️", "Mute failed. Bot ko admin banaon."), parse_mode="HTML"
        )


@safe_handler
async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unmute a user (reply to their message)."""
    if not update.effective_chat or not update.effective_message:
        return
    if not await is_admin(update, context):
        await update.effective_message.reply_text(
            styled_card("🚫", "ꜱɪʀꜰ ᴀᴅᴍɪɴ ᴜɴᴍᴜᴛᴇ ᴋᴀʀ ꜱᴀᴋᴛᴇ ʜᴀɪɴ."), parse_mode="HTML"
        )
        return

    target = get_reply_target(update)
    if not target:
        await update.effective_message.reply_text(
            styled_card("ɪɴᴠᴀʟɪᴅ", "ᴜsᴇʀ ᴋᴇ ᴍᴇssᴀɢᴇ ᴘᴀʀ ʀᴇᴘʟʏ ᴋᴀʀᴏ."), parse_mode="HTML"
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
            styled_card("🔊 ᴜɴᴍᴜᴛᴇᴅ", f"{target.mention_html()} ᴀʙ ʙᴏʟ ꜱᴀᴋᴛᴀ ʜᴀɪ."),
            parse_mode="HTML",
        )
    except (Forbidden, BadRequest, RetryAfter) as exc:
        LOGGER.warning("unmute_cmd_failed user=%s err=%s", target.id, exc)
        await update.effective_message.reply_text(
            styled_card("⚠️", "Unmute failed."), parse_mode="HTML"
        )


# ── Kick ───────────────────────────────────────────────────────────────────

@safe_handler
async def kick_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Kick (ban then immediately unban) a user (reply to their message)."""
    if not update.effective_chat or not update.effective_message:
        return
    if not await is_admin(update, context):
        await update.effective_message.reply_text(
            styled_card("🚫", "ꜱɪʀꜰ ᴀᴅᴍɪɴ ᴋɪᴄᴋ ᴋᴀʀ ꜱᴀᴋᴛᴇ ʜᴀɪɴ."), parse_mode="HTML"
        )
        return

    target = get_reply_target(update)
    if not target:
        await update.effective_message.reply_text(
            styled_card("ɪɴᴠᴀʟɪᴅ", "ᴜsᴇʀ ᴋᴇ ᴍᴇssᴀɢᴇ ᴘᴀʀ ʀᴇᴘʟʏ ᴋᴀʀᴏ."), parse_mode="HTML"
        )
        return

    if await is_target_admin(update.effective_chat.id, target.id, context):
        await update.effective_message.reply_text(
            styled_card("🚫", "ᴀᴅᴍɪɴ ᴋᴏ ᴋɪᴄᴋ ɴᴀʜɪ ᴋᴀʀ ꜱᴀᴋᴛᴇ."), parse_mode="HTML"
        )
        return

    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await asyncio.sleep(1)
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.effective_message.reply_text(
            styled_card("👢 ᴋɪᴄᴋᴇᴅ", f"{target.mention_html()} ᴋᴏ ᴋɪᴄᴋ ᴋɪʏᴀ ɢᴀʏᴀ."),
            parse_mode="HTML",
        )
    except (Forbidden, BadRequest, RetryAfter) as exc:
        LOGGER.warning("kick_cmd_failed user=%s err=%s", target.id, exc)
        await update.effective_message.reply_text(
            styled_card("⚠️", "Kick failed. Bot ko admin banaon."), parse_mode="HTML"
        )


# ── Ban / Unban ────────────────────────────────────────────────────────────

@safe_handler
async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Permanently ban a user (reply to their message)."""
    if not update.effective_chat or not update.effective_message:
        return
    if not await is_admin(update, context):
        await update.effective_message.reply_text(
            styled_card("🚫", "ꜱɪʀꜰ ᴀᴅᴍɪɴ ʙᴀɴ ᴋᴀʀ ꜱᴀᴋᴛᴇ ʜᴀɪɴ."), parse_mode="HTML"
        )
        return

    target = get_reply_target(update)
    if not target:
        await update.effective_message.reply_text(
            styled_card("ɪɴᴠᴀʟɪᴅ", "ᴜsᴇʀ ᴋᴇ ᴍᴇssᴀɢᴇ ᴘᴀʀ ʀᴇᴘʟʏ ᴋᴀʀᴏ."), parse_mode="HTML"
        )
        return

    if await is_target_admin(update.effective_chat.id, target.id, context):
        await update.effective_message.reply_text(
            styled_card("🚫", "ᴀᴅᴍɪɴ ᴋᴏ ʙᴀɴ ɴᴀʜɪ ᴋᴀʀ ꜱᴀᴋᴛᴇ."), parse_mode="HTML"
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
                "🔨 ʙᴀɴɴᴇᴅ",
                f"{target.mention_html()} ᴋᴏ ʙᴀɴ ᴋɪʏᴀ ɢᴀʏᴀ.\nʀᴇᴀsᴏɴ: {reason}",
            ),
            parse_mode="HTML",
        )
    except (Forbidden, BadRequest, RetryAfter) as exc:
        LOGGER.warning("ban_cmd_failed user=%s err=%s", target.id, exc)
        await update.effective_message.reply_text(
            styled_card("⚠️", "Ban failed. Bot ko admin banaon."), parse_mode="HTML"
        )


@safe_handler
async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unban a previously banned user (reply to a forwarded message)."""
    if not update.effective_chat or not update.effective_message:
        return
    if not await is_admin(update, context):
        await update.effective_message.reply_text(
            styled_card("🚫", "ꜱɪʀꜰ ᴀᴅᴍɪɴ ᴜɴʙᴀɴ ᴋᴀʀ ꜱᴀᴋᴛᴇ ʜᴀɪɴ."), parse_mode="HTML"
        )
        return

    target = get_reply_target(update)
    if not target:
        await update.effective_message.reply_text(
            styled_card("ɪɴᴠᴀʟɪᴅ", "ᴜsᴇʀ ᴋᴇ ᴍᴇssᴀɢᴇ ᴘᴀʀ ʀᴇᴘʟʏ ᴋᴀʀᴏ."), parse_mode="HTML"
        )
        return

    try:
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.effective_message.reply_text(
            styled_card("✓ ᴜɴʙᴀɴɴᴇᴅ", f"{target.mention_html()} ᴀʙ ᴠᴀᴘᴀs ᴀᴀ ꜱᴀᴋᴛᴀ ʜᴀɪ."),
            parse_mode="HTML",
        )
    except (Forbidden, BadRequest, RetryAfter) as exc:
        LOGGER.warning("unban_cmd_failed user=%s err=%s", target.id, exc)
        await update.effective_message.reply_text(
            styled_card("⚠️", "Unban failed."), parse_mode="HTML"
        )
