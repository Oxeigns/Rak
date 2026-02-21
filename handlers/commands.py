"""Simplified command handlers for the 4 core moderation features."""

import asyncio
import logging
from typing import TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from helpers import auto_delete_message, ensure_user_joined, is_user_joined, update_group_setting

if TYPE_CHECKING:
    from bot import AIGovernorBot

logger = logging.getLogger(__name__)


class CommandHandlers:
    """Mixin for /start, /panel and /setdelay."""

    def _support_buttons(self: "AIGovernorBot") -> list[list[InlineKeyboardButton]]:
        """Build support URL button defensively."""
        try:
            return [[InlineKeyboardButton("📢 sᴜᴘᴘᴏʀᴛ", url=self.settings.SUPPORT_CHANNEL_LINK)]]
        except Exception:
            return []

    def _main_panel_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📝 ᴛᴇxᴛ ᴍᴏᴅᴇʀᴀᴛɪᴏɴ", callback_data="btn_text")],
                [InlineKeyboardButton("🖼️ ɪᴍᴀɢᴇ ᴍᴏᴅᴇʀᴀᴛɪᴏɴ", callback_data="btn_image")],
                [InlineKeyboardButton("✏️ ᴇᴅɪᴛ ᴅᴇʟᴇᴛᴇ", callback_data="btn_edit")],
                [InlineKeyboardButton("⏱️ ᴀᴜᴛᴏ ᴅᴇʟᴇᴛᴇ", callback_data="btn_auto")],
                [InlineKeyboardButton("❌ ᴄʟᴏsᴇ", callback_data="btn_close")],
            ]
        )

    async def cmd_start(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_chat:
            return

        chat = update.effective_chat
        if chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}:
            await self.cmd_panel(update, context)
            return

        if chat.type == ChatType.PRIVATE and not await ensure_user_joined(update, context):
            return

        text = """◆ ʜᴇʏ ᴛʜᴇʀᴇ! 👋 💗

━━━━━━━━━━━━━━━━━━━━━━━━━━

ɪ'ᴍ ᴀɴ ᴀᴜᴛᴏ ᴅᴇʟᴇᴛᴇʀ ʙᴏᴛ.
ɪ ᴘʀᴏᴄᴇss & ᴍᴏᴅᴇʀᴀᴛᴇ ᴇᴠᴇʀʏ ᴍᴇssᴀɢᴇ,
ɪɴᴄʟᴜᴅɪɴɢ ᴍᴇssᴀɢᴇs ғʀᴏᴍ ᴏᴛʜᴇʀ ʙᴏᴛs.
ᴍᴏᴅᴇʀᴀᴛɪᴏɴ ᴀᴘᴘʟɪᴇs ᴛᴏ ᴛᴇxᴛ & ɪᴍᴀɢᴇs.

━━━━━━━━━━━━━━━━━━━━━━━━━━

• ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ •"""

        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("• ᴀᴅᴅ ᴍᴇ ᴛᴏ ɢʀᴏᴜᴘ •", url=f"https://t.me/{context.bot.username}?startgroup=true")],
                *self._support_buttons(),
            ]
        )
        msg = await context.bot.send_message(chat.id, text, reply_markup=keyboard)
        asyncio.create_task(auto_delete_message(msg, self.settings.AUTO_DELETE_WELCOME))

    @is_user_joined
    async def cmd_panel(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_chat or not update.effective_user:
            return

        chat = update.effective_chat
        user = update.effective_user

        if chat.type == ChatType.PRIVATE:
            await context.bot.send_message(chat.id, "◆ ᴇʀʀᴏʀ 🚫\n\nᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ᴡᴏʀᴋs ᴏɴʟʏ ɪɴ ɢʀᴏᴜᴘs.")
            return

        if not await self._is_admin(chat.id, user.id, context):
            await context.bot.send_message(chat.id, "◆ ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ 🚫\n\nᴏɴʟʏ ᴀᴅᴍɪɴs ᴄᴀɴ ᴜsᴇ /panel.")
            return

        text = """◆ ᴄᴏɴᴛʀᴏʟ ᴘᴀɴᴇʟ 💗

━━━━━━━━━━━━━━━━━━━━━━━━━━

sᴇʟᴇᴄᴛ ᴀ ғᴇᴀᴛᴜʀᴇ ᴛᴏ ᴠɪᴇᴡ:

━━━━━━━━━━━━━━━━━━━━━━━━━━

• ᴛᴀᴘ ʙᴜᴛᴛᴏɴs ʙᴇʟᴏᴡ •"""
        await context.bot.send_message(chat.id, text, reply_markup=self._main_panel_keyboard())

    async def cmd_setdelay(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_chat or not update.effective_user:
            return

        chat = update.effective_chat
        user = update.effective_user

        if chat.type == ChatType.PRIVATE:
            await context.bot.send_message(chat.id, "◆ ᴇʀʀᴏʀ 🚫\n\n/setdelay ᴏɴʟʏ ᴡᴏʀᴋs ɪɴ ɢʀᴏᴜᴘs.")
            return

        if not await self._is_admin(chat.id, user.id, context):
            await context.bot.send_message(chat.id, "◆ ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ 🚫\n\nᴏɴʟʏ ᴀᴅᴍɪɴs!")
            return

        if not context.args or len(context.args) != 1:
            await context.bot.send_message(chat.id, "◆ ᴜsᴀɢᴇ 📖\n\n/setdelay <seconds>\nʀᴀɴɢᴇ: 1-86400")
            return

        try:
            delay = int(context.args[0])
            if not 1 <= delay <= 86400:
                raise ValueError

            context.chat_data["auto_delete_delay"] = delay
            await update_group_setting(chat.id, "auto_delete_time", delay)
            await context.bot.send_message(chat.id, f"◆ ᴅᴇʟᴀʏ ᴜᴘᴅᴀᴛᴇᴅ ✓\n\nᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ: {delay}s")
        except ValueError:
            await context.bot.send_message(chat.id, "❌ ɪɴᴠᴀʟɪᴅ! ᴜsᴇ 1-86400 sᴇᴄᴏɴᴅs")
