"""Command handlers."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from rak_bot_v2.config.constants import MAX_DELETE_DELAY_SECONDS, MIN_DELETE_DELAY_SECONDS
from rak_bot_v2.config.settings import settings
from rak_bot_v2.utils.formatters import force_join_keyboard, panel_keyboard, styled_card
from rak_bot_v2.utils.helpers import enforce_force_join, is_admin


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
        await update.effective_message.reply_text(text, parse_mode="HTML")
        return
    await panel_command(update, context)


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
        styled_card("ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ", "• /setdelay <sec>\n• ᴠᴇʀɪғʏ ᴊᴏɪɴ\n• ᴍᴏᴅᴇʀᴀᴛɪᴏɴ ᴏɴ"),
        reply_markup=panel_keyboard(),
        parse_mode="HTML",
    )


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
