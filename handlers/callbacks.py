"""Simple ELIF-based callback handlers for the 4 feature control panel."""

from typing import TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

if TYPE_CHECKING:
    from bot import AIGovernorBot


class CallbackHandlers:
    def _main_menu_text(self) -> str:
        return """◆ ᴄᴏɴᴛʀᴏʟ ᴘᴀɴᴇʟ 💗

━━━━━━━━━━━━━━━━━━━━━━━━━━

sᴇʟᴇᴄᴛ ᴀ ғᴇᴀᴛᴜʀᴇ ᴛᴏ ᴠɪᴇᴡ:

━━━━━━━━━━━━━━━━━━━━━━━━━━

• ᴛᴀᴘ ʙᴜᴛᴛᴏɴs ʙᴇʟᴏᴡ •"""

    def _main_menu_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📝 ᴛᴇxᴛ ᴍᴏᴅᴇʀᴀᴛɪᴏɴ", callback_data="btn_text")],
                [InlineKeyboardButton("🖼️ ɪᴍᴀɢᴇ ᴍᴏᴅᴇʀᴀᴛɪᴏɴ", callback_data="btn_image")],
                [InlineKeyboardButton("✏️ ᴇᴅɪᴛ ᴅᴇʟᴇᴛᴇ", callback_data="btn_edit")],
                [InlineKeyboardButton("⏱️ ᴀᴜᴛᴏ ᴅᴇʟᴇᴛᴇ", callback_data="btn_auto")],
                [InlineKeyboardButton("❌ ᴄʟᴏsᴇ", callback_data="btn_close")],
            ]
        )

    def _card(self, title: str, description: str) -> str:
        return (
            f"◆ {title} 💗\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{description}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "• ᴛᴀᴘ ʙᴜᴛᴛᴏɴs ʙᴇʟᴏᴡ •"
        )

    async def handle_callback(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query or not query.data:
            return

        data = query.data

        if data == "btn_text":
            await query.edit_message_text(
                self._card(
                    "ᴛᴇxᴛ ᴍᴏᴅᴇʀᴀᴛɪᴏɴ 📝",
                    "Deletes toxic, illegal, spammy or unsafe text content using AI moderation.",
                ),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 ʙᴀᴄᴋ", callback_data="btn_back")],
                    [InlineKeyboardButton("❌ ᴄʟᴏsᴇ", callback_data="btn_close")],
                ]),
            )

        elif data == "btn_image":
            await query.edit_message_text(
                self._card(
                    "ɪᴍᴀɢᴇ ᴍᴏᴅᴇʀᴀᴛɪᴏɴ 🖼️",
                    "Scans image uploads and removes NSFW/unsafe media with optional delay clean-up.",
                ),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 ʙᴀᴄᴋ", callback_data="btn_back")],
                    [InlineKeyboardButton("❌ ᴄʟᴏsᴇ", callback_data="btn_close")],
                ]),
            )

        elif data == "btn_edit":
            await query.edit_message_text(
                self._card(
                    "ᴇᴅɪᴛ ᴍsɢ ᴅᴇʟᴇᴛᴇ ✏️",
                    "When a user edits a message, bot auto-deletes it after configured edited-message delay.",
                ),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 ʙᴀᴄᴋ", callback_data="btn_back")],
                    [InlineKeyboardButton("❌ ᴄʟᴏsᴇ", callback_data="btn_close")],
                ]),
            )

        elif data == "btn_auto":
            await query.edit_message_text(
                self._card(
                    "ᴀᴜᴛᴏ ᴅᴇʟᴇᴛᴇ ⏱️",
                    "Bot messages are auto-cleaned after delay. Use /setdelay <seconds> to configure.",
                ),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("30s", callback_data="set_delay_30"), InlineKeyboardButton("60s", callback_data="set_delay_60")],
                    [InlineKeyboardButton("5m", callback_data="set_delay_300"), InlineKeyboardButton("15m", callback_data="set_delay_900")],
                    [InlineKeyboardButton("🔙 ʙᴀᴄᴋ", callback_data="btn_back")],
                    [InlineKeyboardButton("❌ ᴄʟᴏsᴇ", callback_data="btn_close")],
                ]),
            )

        elif data.startswith("set_delay_"):
            delay = int(data.rsplit("_", maxsplit=1)[-1])
            context.chat_data["auto_delete_delay"] = delay
            if query.message and query.message.chat:
                from helpers import update_group_setting

                await update_group_setting(query.message.chat.id, "auto_delete_time", delay)
            await query.answer(f"Delay set to {delay}s")
            return

        elif data == "btn_back":
            await query.edit_message_text(self._main_menu_text(), reply_markup=self._main_menu_keyboard())

        elif data == "btn_close":
            await query.message.delete()

        await query.answer()
