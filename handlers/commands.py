"""
Command Handlers for AI Governor Bot.
Contains /start, /panel, /guide, /set_edit commands.
"""

import logging
import asyncio
from typing import TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from helpers import auto_delete_message, ensure_user_joined, is_user_joined, update_group_setting
from control_panel import control_panel
from i18n import get_text

if TYPE_CHECKING:
    from bot import AIGovernorBot

logger = logging.getLogger(__name__)


class CommandHandlers:
    """Mixin for command handlers."""

    def _support_buttons(self: "AIGovernorBot") -> list[list[InlineKeyboardButton]]:
        """Build support buttons with a single official support URL."""
        return [[InlineKeyboardButton("📢 sᴜᴘᴘᴏʀᴛ", url="https://t.me/aghoris")]]

    async def cmd_start(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command with premium minimal UI."""
        if not update.effective_chat or not update.effective_user:
            return

        chat = update.effective_chat

        # In groups, keep /start behavior same as /panel to avoid inconsistent flows.
        if chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}:
            await self.cmd_panel(update, context)
            return

        if chat.type == ChatType.PRIVATE and not await ensure_user_joined(update, context):
            return

        total_groups = await self._get_total_groups()
        total_violations = await self._get_total_violations()

        welcome_text = f"""◆ ʜᴇʏ ɪ ᴀᴍ 🤖 ʀᴀᴋsʜᴀᴋ ᴀɪ 💗

━━━━━━━━━━━━━━━━━━━━━━━━━━

ᴀɪ ᴍᴏᴅᴇʀᴀᴛɪᴏɴ ʙᴏᴛ ғᴏʀ ᴛᴇʟᴇɢʀᴀᴍ ɢʀᴏᴜᴘs

━━━━━━━━━━━━━━━━━━━━━━━━━━

⚘ ɴᴇᴡ ғᴇᴀᴛᴜʀᴇs :-

● ᴀɪ ᴛᴇxᴛ ᴍᴏᴅᴇʀᴀᴛɪᴏɴ
● ɪᴍᴀɢᴇ ᴄᴏɴᴛᴇɴᴛ ᴀɴᴀʟʏsɪs
● sᴛɪᴄᴋᴇʀ & ɢɪғ ᴅᴇᴛᴇᴄᴛɪᴏɴ
● ʟɪɴᴋ ғɪʟᴛᴇʀɪɴɢ
● ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ sʏsᴛᴇᴍ

━━━━━━━━━━━━━━━━━━━━━━━━━━

◉ ᴛᴏᴛᴀʟ ɢʀᴏᴜᴘs : {total_groups} | ᴠɪᴏʟᴀᴛɪᴏɴs : {total_violations}

• ᴀᴅᴅ ᴍᴇ ʙᴀʙʏ •"""

        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("• ᴀᴅᴅ ᴍᴇ ʙᴀʙʏ •", url=f"https://t.me/{context.bot.username}?startgroup=true")],
                *self._support_buttons(),
            ]
        )
        msg = await context.bot.send_message(chat_id=chat.id, text=welcome_text, reply_markup=keyboard)
        asyncio.create_task(auto_delete_message(msg, self.settings.AUTO_DELETE_WELCOME))

    @is_user_joined
    async def cmd_panel(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /panel command - open control panel."""
        if not update.effective_chat or not update.effective_user or not update.message:
            return

        chat = update.effective_chat
        user = update.effective_user

        if chat.type == ChatType.PRIVATE:
            msg = await update.message.reply_text(
                "◆ ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ 🚫\n\n"
                "ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ᴄᴀɴ ᴏɴʟʏ ʙᴇ ᴜsᴇᴅ ɪɴ ɢʀᴏᴜᴘs.\n\n"
                "ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ ᴀɴᴅ ᴜsᴇ /ᴘᴀɴᴇʟ ᴛʜᴇʀᴇ.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("• ᴀᴅᴅ ᴍᴇ ᴛᴏ ɢʀᴏᴜᴘ •", url=f"https://t.me/{context.bot.username}?startgroup=true")]]
                ),
            )
            asyncio.create_task(auto_delete_message(msg, 60))
            return

        if not await self._is_admin(chat.id, user.id, context):
            msg = await update.message.reply_text(
                "◆ ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ 🚫\n\n"
                "ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀɴ ᴀᴅᴍɪɴ ɪɴ ᴛʜɪs ɢʀᴏᴜᴘ.\n\n"
                "ᴏɴʟʏ ɢʀᴏᴜᴘ ᴀᴅᴍɪɴs ᴄᴀɴ ᴀᴄᴄᴇss ᴛʜᴇ ᴄᴏɴᴛʀᴏʟ ᴘᴀɴᴇʟ."
            )
            asyncio.create_task(auto_delete_message(msg, 30))
            return

        if not await ensure_user_joined(update, context):
            return

        group = await self._get_group(chat.id)
        language = group.language if group else "en"
        await control_panel.show_menu(update, context, "main", chat.id, language)

    async def cmd_guide(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show helper guide for admins."""
        if not update.effective_chat or not update.effective_user or not update.message:
            return

        chat = update.effective_chat
        user = update.effective_user

        if chat.type != ChatType.PRIVATE and not await self._is_admin(chat.id, user.id, context):
            msg = await update.message.reply_text(
                "◆ ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ 🚫\n\n"
                "ᴏɴʟʏ ᴀᴅᴍɪɴs ᴄᴀɴ ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ!"
            )
            asyncio.create_task(auto_delete_message(msg, 30))
            return

        guide_text = """◆ ʀᴀᴋsʜᴀᴋ ᴀɪ - ᴀᴅᴍɪɴ ɢᴜɪᴅᴇ 📖

━━━━━━━━━━━━━━━━━━━━━━━━━━

⚘ ǫᴜɪᴄᴋ sᴛᴀʀᴛ :-

1️⃣ ᴀᴅᴅ ʙᴏᴛ ᴛᴏ ɢʀᴏᴜᴘ
2️⃣ ᴍᴀᴋᴇ ʙᴏᴛ ᴀᴅᴍɪɴ
3️⃣ ᴜsᴇ /ᴘᴀɴᴇʟ ᴛᴏ ᴏᴘᴇɴ sᴇᴛᴛɪɴɢs

━━━━━━━━━━━━━━━━━━━━━━━━━━

⚘ ᴄᴏᴍᴍᴀɴᴅs :-

• /panel - ᴏᴘᴇɴ ᴄᴏɴᴛʀᴏʟ ᴘᴀɴᴇʟ
• /set_edit <s> - ᴇᴅɪᴛᴇᴅ ᴍsɢ ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ
• /guide - sʜᴏᴡ ᴛʜɪs ʜᴇʟᴘ

━━━━━━━━━━━━━━━━━━━━━━━━━━

⚘ sᴇᴛᴛɪɴɢs ᴇxᴘʟᴀɪɴᴇᴅ :-

🛡️ ғɪʟᴛᴇʀs
• ᴛᴇxᴛ - ᴀɪ ᴄᴏɴᴛᴇɴᴛ ᴍᴏᴅᴇʀᴀᴛɪᴏɴ
• ɪᴍᴀɢᴇ - ɴsғᴡ/ᴠɪᴏʟᴇɴᴄᴇ ᴅᴇᴛᴇᴄᴛɪᴏɴ
• sᴛɪᴄᴋᴇʀ - sᴛɪᴄᴋᴇʀ ᴀɴᴀʟʏsɪs
• ɢɪғ - ɢɪғ ᴍᴏᴅᴇʀᴀᴛɪᴏɴ
• ʟɪɴᴋ - sᴜsᴘɪᴄɪᴏᴜs ʟɪɴᴋs

⚙️ sᴇᴛᴛɪɴɢs
• ᴀᴜᴛᴏ-ᴅᴇʟ - ʙᴏᴛ ᴍsɢ ᴅᴇʟᴇᴛᴇ ᴛɪᴍᴇ
• ᴇᴅɪᴛᴇᴅ ᴀᴜᴛᴏ-ᴅᴇʟ - ᴇᴅɪᴛᴇᴅ ᴍsɢ ᴅᴇʟᴇᴛᴇ ᴛɪᴍᴇ
• ᴛʜʀᴇsʜᴏʟᴅ - ᴀɪ sᴇɴsɪᴛɪᴠɪᴛʏ
• ᴍᴜᴛᴇ - ᴍᴜᴛᴇ ᴅᴜʀᴀᴛɪᴏɴ
• ᴡᴀʀɴɪɴɢs - ᴍᴀx ᴡᴀʀɴɪɴɢs ʙᴇғᴏʀᴇ ᴍᴜᴛᴇ

━━━━━━━━━━━━━━━━━━━━━━━━━━

⚘ ʜᴏᴡ ᴛᴏ ᴄᴏɴғɪɢᴜʀᴇ :-

1. ᴄʟɪᴄᴋ ᴀɴʏ sᴇᴛᴛɪɴɢ ʙᴜᴛᴛᴏɴ
2. ᴇɴᴛᴇʀ ʏᴏᴜʀ ᴠᴀʟᴜᴇ
3. ᴅᴏɴᴇ!

━━━━━━━━━━━━━━━━━━━━━━━━━━

• ғᴏʀ sᴜᴘᴘᴏʀᴛ, ᴄʟɪᴄᴋ ʙᴇʟᴏᴡ •"""

        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("• ᴏᴘᴇɴ ᴄᴏɴᴛʀᴏʟ ᴘᴀɴᴇʟ •", callback_data=f"cp:main:{chat.id}")],
                *self._support_buttons(),
            ]
        )

        msg = await context.bot.send_message(
            chat_id=chat.id,
            text=guide_text,
            reply_markup=keyboard,
        )
        asyncio.create_task(auto_delete_message(msg, 600))

    async def cmd_set_edit_autodelete(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set edited message auto-delete time via command."""
        if not update.effective_chat or not update.effective_user or not update.message:
            return

        chat = update.effective_chat
        user = update.effective_user

        # Admin check
        if not await self._is_admin(chat.id, user.id, context):
            await update.message.reply_text("❌ Only admins can use this command!")
            return

        # Check args
        if not context.args or len(context.args) != 1:
            await update.message.reply_text(
                "Usage: /set_edit <seconds>\nExample: /set_edit 300\nRange: 0-10000 seconds (0 = disable)"
            )
            return

        try:
            seconds = int(context.args[0])
            if seconds < 0 or seconds > 10000:
                await update.message.reply_text("❌ Value must be between 0 and 10000 seconds!")
                return

            # Update setting
            success = await update_group_setting(chat.id, "auto_delete_edited", seconds)

            if success:
                await update.message.reply_text(f"✅ Edited messages will be auto-deleted after {seconds} seconds!")
            else:
                await update.message.reply_text("❌ Failed to update setting. Try again.")
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number!")
