"""Command handlers."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from rak_bot_v2.config.constants import MAX_DELETE_DELAY_SECONDS, MIN_DELETE_DELAY_SECONDS
from rak_bot_v2.config.settings import get_settings

settings = get_settings()
from rak_bot_v2.utils.formatters import add_to_group_keyboard, force_join_keyboard, panel_keyboard, styled_card
from rak_bot_v2.utils.helpers import enforce_force_join, is_admin, safe_handler


@safe_handler
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start in DM and groups."""
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
        text = styled_card("ᴡᴇʟᴄᴏᴍᴇ", "ᴍᴇɪɴ ᴀɪ ɢᴏᴠᴇʀɴᴏʀ ʙᴏᴛ ʜᴜɴ. ɢʀᴏᴜᴘ ᴍᴇɪɴ ᴀᴅᴅ ᴋᴀʀᴏ ✓")
        me = await context.bot.get_me()
        await update.effective_message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=add_to_group_keyboard(me.username),
        )
        return
    await panel_command(update, context)


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
        styled_card("ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ", "• /setdelay &lt;sec&gt;\n• ᴠᴇʀɪғʏ ᴊᴏɪɴ\n• ᴍᴏᴅᴇʀᴀᴛɪᴏɴ ᴏɴ"),
        reply_markup=panel_keyboard(),
        parse_mode="HTML",
    )


@safe_handler
async def set_delay_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Update auto-delete delay for group."""
    if not update.effective_chat or not update.effective_message:
        return
    if not await is_admin(update, context):
        await update.effective_message.reply_text(
            styled_card("🚫 ɴᴏ ᴀᴄᴄᴇss", "ꜱɪʀꜰ ᴀᴅᴍɪɴ ᴅᴇʟᴀʏ ʙᴀᴅᴀʟ ꜱᴀᴋᴛᴀ ʜᴀɪ."),
            parse_mode="HTML",
        )
        return
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text(styled_card("ɪɴᴠᴀʟɪᴅ", "ᴜsᴇ: /setdelay 1-86400"), parse_mode="HTML")
        return
    seconds = int(context.args[0])
    if seconds < MIN_DELETE_DELAY_SECONDS or seconds > MAX_DELETE_DELAY_SECONDS:
        await update.effective_message.reply_text(
            styled_card("ɪɴᴠᴀʟɪᴅ", "ʀᴀɴɢᴇ 1 sᴇ 86400 sᴇᴄ ᴛᴀᴋ ʀᴀᴋʜᴏ."),
            parse_mode="HTML",
        )
        return
    await context.application.bot_data["store"].set_delete_delay(update.effective_chat.id, seconds)
    await update.effective_message.reply_text(
        styled_card("✓ sᴀᴠᴇᴅ", f"ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ ᴀʙ {seconds}s ʜᴏ ɢᴀʏᴀ."),
        parse_mode="HTML",
    )


@safe_handler
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show bot statistics for owner."""
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
    cached = len(cache._memory_cache) if cache else 0
    text = (
        "◆ <b>ʙᴏᴛ sᴛᴀᴛɪsᴛɪᴄs</b> 📊\n\n━━━━━━━━━━━━\n\n"
        f"ᴛᴏᴛᴀʟ ᴄʜᴀᴛs: {total_chats}\n"
        f"ɪʟʟᴇɢᴀʟ ᴛᴇxᴛs ᴄᴀᴄʜᴇᴅ: {cached}\n"
        f"ᴡᴀʀɴɪɴɢs: {total_warn}\n\n"
        f"◆ <b>ᴏᴡɴᴇʀ:</b> @{update.effective_user.username or 'N/A'}"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")


@safe_handler
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Broadcast owner-provided message to all tracked chats."""
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
        except Exception:  # noqa: BLE001
            failed += 1
    await update.effective_message.reply_text(
        styled_card("✓ ʙʀᴏᴀᴅᴄᴀsᴛ ᴄᴏᴍᴘʟᴇᴛᴇ", f"sᴇɴᴛ: {sent}\nғᴀɪʟᴇᴅ: {failed}"),
        parse_mode="HTML",
    )


@safe_handler
async def reload_words_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reload cache word lists without restart for owner."""
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
