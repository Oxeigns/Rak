"""
AI Governor Bot - Main Bot Handler
Core message processing and event handling
"""

import logging
import asyncio
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Optional

from telegram import ChatMemberAdministrator, ChatMemberOwner, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from settings import get_settings
from database import Group, GroupSettings, GroupType, GroupUser, Message, PersonalityMode, RiskLevel, User, db_manager
from ai_moderation import ai_moderation_service
from anti_raid import anti_raid_system
from control_panel import control_panel
from risk_engine import risk_engine
from trust_engine import trust_engine
from helpers import (
    auto_delete_message,
    get_all_groups,
    get_all_users,
    is_user_joined,
    ensure_user_joined,
    verify_join_callback,
)
from i18n import get_text

logger = logging.getLogger(__name__)


class AIGovernorBot:
    """AI Governor Bot - Telegram event orchestration."""

    def __init__(self):
        self.settings = get_settings()
        self.application: Optional[Application] = None
        self._handlers_registered = False
        self._promotion_tasks = []
        self._button_clicks: dict[int, deque[float]] = defaultdict(deque)

    async def initialize(self):
        """Initialize telegram application and register all handlers before start."""
        if self.application is not None:
            return

        self.application = Application.builder().token(self.settings.BOT_TOKEN).build()
        self._register_handlers()
        self._promotion_tasks.append(asyncio.create_task(self._group_promotion_loop()))
        self._promotion_tasks.append(asyncio.create_task(self._dm_promotion_loop()))

    def _register_handlers(self):
        """Register all bot handlers exactly once."""
        if self._handlers_registered:
            return

        app = self.application
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("panel", self.cmd_panel))
        app.add_handler(CommandHandler("guide", self.cmd_guide))
        app.add_handler(CommandHandler("set_edit", self.cmd_set_edit_autodelete))

        # Most-specific callbacks first
        app.add_handler(CallbackQueryHandler(self.handle_set_autodelete, pattern=r"^cp_action:set_autodelete:"))
        app.add_handler(CallbackQueryHandler(self.handle_set_edited_autodelete, pattern=r"^cp_action:set_edited_autodelete:"))
        app.add_handler(CallbackQueryHandler(self.handle_set_threshold, pattern=r"^cp_action:set_threshold:"))
        app.add_handler(CallbackQueryHandler(self.handle_set_mute_duration, pattern=r"^cp_action:set_mute_duration:"))
        app.add_handler(CallbackQueryHandler(self.handle_set_max_warnings, pattern=r"^cp_action:set_max_warnings:"))

        # Pattern callbacks
        app.add_handler(CallbackQueryHandler(self.handle_toggle, pattern=r"^cp_toggle:"))
        app.add_handler(CallbackQueryHandler(self.handle_action, pattern=r"^cp_action:"))
        app.add_handler(CallbackQueryHandler(self.handle_language, pattern=r"^cp_language:"))
        app.add_handler(CallbackQueryHandler(self.handle_personality, pattern=r"^cp_personality:"))

        # Generic callback last
        app.add_handler(CallbackQueryHandler(self.handle_callback, pattern=r"^cp:"))
        app.add_handler(CallbackQueryHandler(verify_join_callback, pattern=r"^verify_join$"))

        app.add_handler(ChatMemberHandler(self.handle_chat_member, ChatMemberHandler.ANY_CHAT_MEMBER))
        app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, self.handle_new_members))
        # Admin text input handler
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
            self.handle_text_input,
            block=False
        ))
        app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, self.handle_message))

        app.add_error_handler(self.handle_error)
        self._handlers_registered = True

    @is_user_joined
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command with premium minimal UI."""
        if not update.effective_chat or not update.effective_user:
            return

        chat = update.effective_chat
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
                [InlineKeyboardButton("📢 sᴜᴘᴘᴏʀᴛ", url=self.settings.SUPPORT_CHANNEL_LINK)],
            ]
        )
        msg = await context.bot.send_message(chat_id=chat.id, text=welcome_text, reply_markup=keyboard)
        asyncio.create_task(auto_delete_message(msg, self.settings.AUTO_DELETE_WELCOME))

    @is_user_joined
    async def cmd_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    async def cmd_guide(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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

⚘ ǫᴜɪᴄᴋ sᴛᴀʀᴛ :-\n\n1️⃣ ᴀᴅᴅ ʙᴏᴛ ᴛᴏ ɢʀᴏᴜᴘ\n2️⃣ ᴍᴀᴋᴇ ʙᴏᴛ ᴀᴅᴍɪɴ\n3️⃣ ᴜsᴇ /ᴘᴀɴᴇʟ ᴛᴏ ᴏᴘᴇɴ sᴇᴛᴛɪɴɢs\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━

⚘ ᴄᴏᴍᴍᴀɴᴅs :-\n\n• /panel - ᴏᴘᴇɴ ᴄᴏɴᴛʀᴏʟ ᴘᴀɴᴇʟ\n• /set_edit <s> - ᴇᴅɪᴛᴇᴅ ᴍsɢ ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ\n• /guide - sʜᴏᴡ ᴛʜɪs ʜᴇʟᴘ\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━

⚘ sᴇᴛᴛɪɴɢs ᴇxᴘʟᴀɪɴᴇᴅ :-\n\n🛡️ ғɪʟᴛᴇʀs
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

⚘ ʜᴏᴡ ᴛᴏ ᴄᴏɴғɪɢᴜʀᴇ :-\n\n1. ᴄʟɪᴄᴋ ᴀɴʏ sᴇᴛᴛɪɴɢ ʙᴜᴛᴛᴏɴ\n2. ᴇɴᴛᴇʀ ʏᴏᴜʀ ᴠᴀʟᴜᴇ\n3. ᴅᴏɴᴇ!\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━

• ғᴏʀ sᴜᴘᴘᴏʀᴛ, ᴄʟɪᴄᴋ ʙᴇʟᴏᴡ •"""

        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("• ᴏᴘᴇɴ ᴄᴏɴᴛʀᴏʟ ᴘᴀɴᴇʟ •", callback_data=f"cp:main:{chat.id}")],
                [InlineKeyboardButton("📢 sᴜᴘᴘᴏʀᴛ ᴄʜᴀɴɴᴇʟ", url=self.settings.SUPPORT_CHANNEL_LINK)],
            ]
        )

        msg = await context.bot.send_message(
            chat_id=chat.id,
            text=guide_text,
            reply_markup=keyboard,
        )
        asyncio.create_task(auto_delete_message(msg, 600))

    async def cmd_set_edit_autodelete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            from helpers import update_group_setting
            success = await update_group_setting(chat.id, "auto_delete_edited", seconds)

            if success:
                await update.message.reply_text(f"✅ Edited messages will be auto-deleted after {seconds} seconds!")
            else:
                await update.message.reply_text("❌ Failed to update setting. Try again.")
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number!")

    async def handle_set_autodelete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle auto-delete time setting."""
        query = update.callback_query
        await query.answer()

        group_id = int(query.data.split(":")[-1])
        user_id = update.effective_user.id

        # Verify admin
        if not await self._is_admin(group_id, user_id, context):
            await query.answer("❌ Admin only!", show_alert=True)
            return

        # Store state
        context.user_data["awaiting_input"] = {"type": "auto_delete_time", "group_id": group_id}

        await query.edit_message_text(
            "⏱️ <b>Set Auto-Delete Time</b>\n\n"
            "Enter time in seconds (0-10000):\n"
            "<code>0</code> = Disable auto-delete\n"
            "Example: <code>60</code> for 1 minute",
            parse_mode="HTML"
        )

    async def handle_set_edited_autodelete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle edited message auto-delete time setting."""
        query = update.callback_query
        await query.answer()

        group_id = int(query.data.split(":")[-1])
        user_id = update.effective_user.id

        if not await self._is_admin(group_id, user_id, context):
            await query.answer("❌ Admin only!", show_alert=True)
            return

        context.user_data["awaiting_input"] = {"type": "auto_delete_edited", "group_id": group_id}

        await query.edit_message_text(
            "✏️ <b>Set Edited Msg Auto-Delete</b>\n\n"
            "Enter time in seconds (0-10000):\n"
            "<code>0</code> = Disable auto-delete\n"
            "Example: <code>300</code> for 5 minutes",
            parse_mode="HTML"
        )

    async def handle_set_threshold(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle toxic threshold setting."""
        query = update.callback_query
        await query.answer()

        group_id = int(query.data.split(":")[-1])
        user_id = update.effective_user.id

        if not await self._is_admin(group_id, user_id, context):
            await query.answer("❌ Admin only!", show_alert=True)
            return

        context.user_data["awaiting_input"] = {"type": "toxic_threshold", "group_id": group_id}

        await query.edit_message_text(
            "⚡ <b>Set Toxic Threshold</b>\n\n"
            "Enter percentage (1-100):\n"
            "Example: <code>70</code> for 70%",
            parse_mode="HTML"
        )

    async def handle_set_mute_duration(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle mute duration setting."""
        query = update.callback_query
        await query.answer()

        group_id = int(query.data.split(":")[-1])
        user_id = update.effective_user.id

        if not await self._is_admin(group_id, user_id, context):
            await query.answer("❌ Admin only!", show_alert=True)
            return

        context.user_data["awaiting_input"] = {"type": "mute_duration", "group_id": group_id}

        await query.edit_message_text(
            "⏳ <b>Set Mute Duration</b>\n\n"
            "Enter hours (1-168):\n"
            "Example: <code>24</code> for 24 hours",
            parse_mode="HTML"
        )

    async def handle_set_max_warnings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle max warnings setting."""
        query = update.callback_query
        await query.answer()

        group_id = int(query.data.split(":")[-1])
        user_id = update.effective_user.id

        if not await self._is_admin(group_id, user_id, context):
            await query.answer("❌ Admin only!", show_alert=True)
            return

        context.user_data["awaiting_input"] = {"type": "max_warnings", "group_id": group_id}

        await query.edit_message_text(
            "📝 <b>Set Max Warnings</b>\n\n"
            "Enter number (1-10):\n"
            "Example: <code>3</code> for 3 warnings",
            parse_mode="HTML"
        )

    async def handle_text_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle admin text input for settings."""
        if not update.effective_user or not update.effective_chat or not update.message or not update.message.text:
            return

        user_data = context.user_data.get("awaiting_input")
        if not user_data:
            return

        group_id = user_data.get("group_id")
        setting_type = user_data.get("type")

        # Verify admin
        if not await self._is_admin(group_id, update.effective_user.id, context):
            await update.message.reply_text("❌ Only admins can change settings!")
            context.user_data.pop("awaiting_input", None)
            return

        text = update.message.text.strip()

        try:
            from helpers import update_group_setting

            if setting_type == "auto_delete_time":
                value = int(text)
                if value < 0 or value > 10000:
                    await update.message.reply_text("❌ Must be between 0-10000 seconds!")
                    return
                await update_group_setting(group_id, "auto_delete_time", value)
                await update.message.reply_text(f"✅ Auto-delete set to {value}s")

            elif setting_type == "auto_delete_edited":
                value = int(text)
                if value < 0 or value > 10000:
                    await update.message.reply_text("❌ Must be between 0-10000 seconds!")
                    return
                await update_group_setting(group_id, "auto_delete_edited", value)
                await update.message.reply_text(f"✅ Edited msg auto-delete set to {value}s")

            elif setting_type == "toxic_threshold":
                value = int(text)
                if value < 1 or value > 100:
                    await update.message.reply_text("❌ Must be between 1-100!")
                    return
                await update_group_setting(group_id, "toxic_threshold", value / 100)
                await update.message.reply_text(f"✅ Toxic threshold set to {value}%")

            elif setting_type == "mute_duration":
                value = int(text)
                if value < 1 or value > 168:
                    await update.message.reply_text("❌ Must be between 1-168 hours!")
                    return
                await update_group_setting(group_id, "mute_duration", value)
                await update.message.reply_text(f"✅ Mute duration set to {value}h")

            elif setting_type == "max_warnings":
                value = int(text)
                if value < 1 or value > 10:
                    await update.message.reply_text("❌ Must be between 1-10!")
                    return
                await update_group_setting(group_id, "max_warnings", value)
                await update.message.reply_text(f"✅ Max warnings set to {value}")

        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number!")
        finally:
            context.user_data.pop("awaiting_input", None)


    def _parse_callback_payload(self, data: str, expected_prefix: str) -> tuple[str, int] | None:
        parts = data.split(":")
        if len(parts) != 3 or parts[0] != expected_prefix:
            return None

        action = parts[1].strip()
        raw_group_id = parts[2].strip()
        if not action or not raw_group_id.lstrip("-").isdigit():
            return None

        group_id = int(raw_group_id)
        if group_id == 0:
            return None

        return action, group_id

    async def _rate_limited(self, user_id: int) -> bool:
        now = time.monotonic()
        window = self.settings.BUTTON_CLICK_RATE_LIMIT_WINDOW_SECONDS
        limit = self.settings.BUTTON_CLICK_RATE_LIMIT_MAX

        bucket = self._button_clicks[user_id]
        while bucket and now - bucket[0] > window:
            bucket.popleft()

        if len(bucket) >= limit:
            return True

        bucket.append(now)
        return False

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback queries."""
        query = update.callback_query
        if not query or not query.data or not update.effective_user:
            return

        user_id = update.effective_user.id

        # Rate limiting
        now = time.time()
        user_clicks = self._button_clicks[user_id]
        while user_clicks and user_clicks[0] < now - self.settings.BUTTON_CLICK_RATE_LIMIT_WINDOW_SECONDS:
            user_clicks.popleft()
        if len(user_clicks) >= self.settings.BUTTON_CLICK_RATE_LIMIT_MAX:
            await query.answer("⏳ Please slow down!", show_alert=True)
            return
        user_clicks.append(now)

        data = query.data

        # Parse callback data
        if data.startswith("cp:"):
            parts = data.split(":")
            if len(parts) >= 3:
                menu = parts[1]
                group_id = int(parts[2])

                # Verify admin
                if not await self._is_admin(group_id, user_id, context):
                    await query.answer("❌ Admin only!", show_alert=True)
                    return

                if menu == "close":
                    await query.message.delete()
                else:
                    group = await self._get_group(group_id)
                    language = group.language if group else "en"
                    await control_panel.show_menu(update, context, menu, group_id, language)

        await query.answer()

    async def handle_toggle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle toggle callbacks with better error messages."""
        query = update.callback_query
        if not query or not query.data:
            return

        payload = self._parse_callback_payload(query.data, "cp_toggle")
        if not payload:
            await query.answer("Invalid payload", show_alert=True)
            return

        setting_name, group_id = payload
        if await self._rate_limited(query.from_user.id):
            await query.answer("⏳ Please slow down!", show_alert=True)
            return

        if not await self._is_admin(group_id, query.from_user.id, context):
            await query.answer(
                "◆ ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ 🚫\n\nʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀɴ ᴀᴅᴍɪɴ ɪɴ ᴛʜɪs ɢʀᴏᴜᴘ.",
                show_alert=True,
            )
            return

        setting_columns = {
            "strict_mode": (Group, Group.strict_mode),
            "crypto_shield": (Group, Group.crypto_shield),
            "deep_media": (Group, Group.deep_media_analysis),
            "ai_abuse": (GroupSettings, GroupSettings.ai_moderation_enabled),
            "daily_q": (Group, Group.engagement_enabled),
            "analytics": (Group, Group.analytics_enabled),
        }

        setting_target = setting_columns.get(setting_name)
        if setting_target is None:
            await query.answer(f"Setting '{setting_name}' is not supported yet.", show_alert=True)
            return

        model_cls, column = setting_target

        async with db_manager.get_session() as session:
            if model_cls is Group:
                result = await session.execute(select(Group).where(Group.id == group_id))
                record = result.scalar_one_or_none()
                if record is None:
                    await query.answer("Group not found", show_alert=True)
                    return
            else:
                result = await session.execute(select(GroupSettings).where(GroupSettings.group_id == group_id))
                record = result.scalar_one_or_none()
                if record is None:
                    record = GroupSettings(group_id=group_id)
                    session.add(record)

            current_value = bool(getattr(record, column.key))
            setattr(record, column.key, not current_value)
            await session.commit()

        await query.answer(f"{setting_name} {'enabled' if not current_value else 'disabled'}")
        await self.handle_callback(update, context)

    async def handle_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle action button callbacks."""
        query = update.callback_query
        if not query or not query.data:
            return

        payload = self._parse_callback_payload(query.data, "cp_action")
        if not payload:
            await query.answer("Invalid payload", show_alert=True)
            return

        action_name, group_id = payload
        critical_actions = {"trust_reset", "raid_lockdown", "set_owner", "system_reset"}
        if action_name in critical_actions and query.from_user.id != self.settings.OWNER_ID:
            await query.answer("Only owner can perform this action.", show_alert=True)
            return
        if not await self._is_admin(group_id, query.from_user.id, context):
            await query.answer(get_text("not_admin", "en"), show_alert=True)
            return

        await query.answer("Processing...")
        if action_name == "status_refresh":
            try:
                await query.edit_message_text("Status refreshed ✓")
            except BadRequest as exc:
                if "Message is not modified" not in str(exc):
                    raise

    async def handle_language(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle language selection."""
        query = update.callback_query
        if not query or not query.data:
            return

        payload = self._parse_callback_payload(query.data, "cp_language")
        if not payload:
            await query.answer("Invalid payload", show_alert=True)
            return

        lang_code, group_id = payload
        if not await self._is_admin(group_id, query.from_user.id, context):
            await query.answer(get_text("not_admin", "en"), show_alert=True)
            return

        from sqlalchemy import update as sql_update

        async with db_manager.get_session() as session:
            await session.execute(sql_update(Group).where(Group.id == group_id).values(language=lang_code))
            await session.commit()

        await query.answer("Language updated")
        await self.handle_callback(update, context)

    async def handle_personality(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle personality mode selection."""
        query = update.callback_query
        if not query or not query.data:
            return

        payload = self._parse_callback_payload(query.data, "cp_personality")
        if not payload:
            await query.answer("Invalid payload", show_alert=True)
            return

        personality, group_id = payload
        if not await self._is_admin(group_id, query.from_user.id, context):
            await query.answer(get_text("not_admin", "en"), show_alert=True)
            return

        from sqlalchemy import update as sql_update

        async with db_manager.get_session() as session:
            await session.execute(
                sql_update(Group)
                .where(Group.id == group_id)
                .values(personality_mode=PersonalityMode(personality))
            )
            await session.commit()

        await query.answer("Personality updated")
        await self.handle_callback(update, context)

    async def handle_new_members(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle new chat members."""
        if not update.message:
            return

        for member in update.message.new_chat_members:
            if member.id == context.bot.id:
                await self._on_bot_added(update, context)
            else:
                await self._on_user_join(update, context, member)

    async def handle_chat_member(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle chat member updates (promotions, etc)."""
        if not update.chat_member:
            return

        old_status = update.chat_member.old_chat_member.status
        new_status = update.chat_member.new_chat_member.status

        if (
            update.chat_member.new_chat_member.user.id == context.bot.id
            and old_status != "administrator"
            and new_status == "administrator"
        ):
            await self._on_bot_promoted(update, context)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process incoming messages through moderation pipeline."""
        if not update.message or not update.message.text:
            return

        chat = update.effective_chat
        user = update.effective_user
        message = update.message
        if not chat or not user:
            return

        group = await self._get_group(chat.id)
        if not group:
            return

        user_history = await self._get_user_history(user.id, chat.id)

        ai_result = await ai_moderation_service.analyze_message(
            message.text,
            context={"user_violations_24h": user_history.get("violations_24h", 0), "group_type": group.group_type.value},
        )

        ai_payload = ai_result if isinstance(ai_result, dict) else ai_result.to_dict()
        if "spam_score" in ai_payload:
            ai_payload = {
                "spam": ai_payload.get("spam_score", 0.0),
                "toxicity": ai_payload.get("toxicity_score", 0.0),
                "illegal": ai_payload.get("illegal_score", 0.0),
                "scam": 0.0,
                "phishing": 0.0,
                "nsfw": 0.0,
                "suspicious_links": 0.0,
            }

        risk_assessment = await risk_engine.calculate_risk(
            message_text=message.text,
            user_id=user.id,
            group_id=chat.id,
            ai_analysis=ai_payload,
            user_history=user_history,
            context={"recent_user_messages": user_history.get("recent_messages", 0), "time_window_seconds": 60},
        )

        await self._execute_action(update, context, risk_assessment, user, chat, message)
        await self._log_message(message, risk_assessment, chat.id, user)

    async def handle_error(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """Global error handler for uncaught telegram exceptions."""
        logger.exception("Unhandled bot error for update %s: %s", update, context.error)

        if isinstance(update, Update) and update.effective_chat:
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="⚠️ An internal error occurred while processing your request.",
                )
            except TelegramError:
                logger.exception("Failed to send error notification to chat %s", update.effective_chat.id)

    async def _on_bot_added(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        if not chat or not update.message:
            return

        bot_member = await chat.get_member(context.bot.id)
        if bot_member.status not in {"administrator", "creator"}:
            await update.message.reply_text(get_text("activate_admin", "en"), parse_mode="Markdown")
            return

        await self._create_group(chat)
        await self._send_welcome_message(update, context)

    async def _on_bot_promoted(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        if not chat:
            return

        await self._create_group(chat)
        await context.bot.send_message(
            chat_id=chat.id,
            text=get_text("select_language_prompt", "en"),
            reply_markup=self._language_selection_keyboard(chat.id),
        )

    async def _on_user_join(self, update: Update, context: ContextTypes.DEFAULT_TYPE, member):
        chat = update.effective_chat
        if not chat:
            return

        raid_result = await anti_raid_system.record_join(chat.id, member.id, member.username or "", None)
        if raid_result.is_raid:
            await self._handle_raid_detection(update, context, raid_result)

    async def _execute_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE, risk_assessment, user, chat, message):
        if risk_assessment.decision == "allow":
            return

        action = risk_assessment.action
        language = await self._get_group_language(chat.id)

        if action == "delete_mute_notify":
            await message.delete()
            await context.bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=user.id,
                permissions={"can_send_messages": False},
                until_date=datetime.utcnow() + timedelta(hours=1),
            )
            await self._notify_admins(
                context,
                chat.id,
                f"Critical risk message deleted. User muted.\nRisk: {risk_assessment.final_score:.1f}",
            )
        elif action == "delete_warn":
            await message.delete()
            warning_text = get_text("action_warned", language)
            await context.bot.send_message(
                chat_id=chat.id,
                text=f"{warning_text}\nRisk: {risk_assessment.final_score:.1f}",
                reply_to_message_id=message.message_id,
            )

        db_risk_level = RiskLevel.coerce(risk_assessment.risk_level)

        trust_update = await trust_engine.calculate_trust_update(
            user.id,
            chat.id,
            "violation",
            severity=db_risk_level.normalized,
        )

        async with db_manager.get_session() as session:
            await trust_engine.update_user_trust(user.id, chat.id, trust_update.new_score, session)

    async def _send_welcome_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        if not chat:
            return

        text = (
            f"{self.settings.BOT_NAME} Activated\n\n"
            "Protection System Activated:\n"
            "✓ Spam Shield\n"
            "✓ AI Abuse Detection\n"
            "✓ Link Intelligence\n"
            "✓ Anti-Raid System\n"
            "✓ Trust Score Engine\n"
            "✓ Media Scanner\n\n"
            "Use /panel to customize settings."
        )

        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Open Control Panel", callback_data=f"cp:main:{chat.id}")]]
        )

        await context.bot.send_message(chat_id=chat.id, text=text, reply_markup=keyboard)

    def _language_selection_keyboard(self, group_id: int):
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("English", callback_data=f"cp_language:en:{group_id}")],
                [InlineKeyboardButton("Hindi", callback_data=f"cp_language:hi:{group_id}")],
                [InlineKeyboardButton("Hinglish", callback_data=f"cp_language:hinglish:{group_id}")],
            ]
        )

    async def _is_admin(self, chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            return member.status in {"administrator", "creator"}
        except TelegramError:
            return False

    async def _get_group(self, group_id: int) -> Optional[Group]:
        from sqlalchemy import select

        async with db_manager.get_session() as session:
            result = await session.execute(select(Group).where(Group.id == group_id))
            return result.scalar_one_or_none()

    async def _get_group_language(self, group_id: int) -> str:
        group = await self._get_group(group_id)
        return group.language if group else "en"

    async def _create_group(self, chat):
        from sqlalchemy import select

        async with db_manager.get_session() as session:
            existing = (await session.execute(select(Group).where(Group.id == chat.id))).scalar_one_or_none()
            if existing:
                return

            group_type = GroupType.SUPERGROUP if chat.type == "supergroup" else GroupType.PUBLIC
            session.add(
                Group(
                    id=chat.id,
                    title=chat.title or "Unknown",
                    username=chat.username,
                    group_type=group_type,
                )
            )
            await session.commit()

    async def _get_user_history(self, user_id: int, group_id: int) -> dict:
        return {
            "violations_24h": 0,
            "violations_7d": 0,
            "total_violations": 0,
            "trust_score": 50,
            "recent_messages": 0,
        }

    async def _ensure_user_exists(self, session, telegram_user) -> None:
        """Create user row if missing. Safe under concurrent inserts."""
        await session.execute(
            insert(User)
            .values(
                id=telegram_user.id,
                username=telegram_user.username,
                first_name=telegram_user.first_name,
                last_name=telegram_user.last_name,
                language_code=telegram_user.language_code or "en",
                is_bot=telegram_user.is_bot,
            )
            .on_conflict_do_nothing(index_elements=[User.id])
        )

    async def _log_message(self, message, risk_assessment, group_id, telegram_user):
        async with db_manager.get_session() as session:
            async with session.begin():
                await self._ensure_user_exists(session, telegram_user)
                session.add(
                    Message(
                        message_id=message.message_id,
                        group_id=group_id,
                        user_id=telegram_user.id,
                        text=message.text,
                        risk_score=risk_assessment.final_score,
                        risk_level=RiskLevel.coerce(risk_assessment.risk_level),
                        action_taken=risk_assessment.action,
                    )
                )

    async def _notify_admins(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, message: str):
        try:
            admins = await context.bot.get_chat_administrators(chat_id)
            for admin in admins:
                try:
                    await context.bot.send_message(chat_id=admin.user.id, text=f"Alert from group {chat_id}:\n{message}")
                except TelegramError:
                    continue
        except TelegramError:
            logger.exception("Unable to notify admins for chat %s", chat_id)

    async def _handle_raid_detection(self, update, context, raid_result):
        chat = update.effective_chat
        if not chat:
            return

        await context.bot.send_message(
            chat_id=chat.id,
            text=(
                "🚨 RAID DETECTED 🚨\n\n"
                f"Type: {raid_result.raid_type}\n"
                f"Confidence: {raid_result.confidence:.0%}\n\n"
                "Protection activated."
            ),
        )

    async def _group_promotion_loop(self):
        while True:
            await asyncio.sleep(max(1, self.settings.GROUP_PROMOTION_INTERVAL) * 3600)
            await self._send_group_promotion()

    async def _dm_promotion_loop(self):
        while True:
            await asyncio.sleep(max(1, self.settings.DM_PROMOTION_INTERVAL) * 3600)
            await self._send_dm_promotion()

    async def _send_group_promotion(self):
        if not self.application:
            return
        try:
            groups = await get_all_groups()
            promo_text = """◆ 🤖 ʀᴀᴋsʜᴀᴋ ᴀɪ ɢᴜᴀʀᴅɪᴀɴ 💗

━━━━━━━━━━━━━━━━━━━━━━━━━━

ᴋᴇᴇᴘɪɴɢ ʏᴏᴜʀ ɢʀᴏᴜᴘ sᴀғᴇ ᴀɴᴅ ᴄʟᴇᴀɴ

⚘ ғᴇᴀᴛᴜʀᴇs :-

● ᴀɪ ᴄᴏɴᴛᴇɴᴛ ᴍᴏᴅᴇʀᴀᴛɪᴏɴ
● sᴛɪᴄᴋᴇʀ & ɢɪғ ᴀɴᴀʟʏsɪs
● ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ sʏsᴛᴇᴍ

━━━━━━━━━━━━━━━━━━━━━━━━━━

• ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ •"""
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("• ᴀᴅᴅ ᴍᴇ ʙᴀʙʏ •", url=f"https://t.me/{self.application.bot.username}?startgroup=true")]]
            )
            for group_id in groups:
                try:
                    msg = await self.application.bot.send_message(chat_id=group_id, text=promo_text, reply_markup=keyboard)
                    asyncio.create_task(auto_delete_message(msg, 3600))
                except Exception:
                    continue
        except Exception as exc:
            logger.error("Group promotion error: %s", exc)

    async def _send_dm_promotion(self):
        if not self.application:
            return
        try:
            users = await get_all_users()
            promo_text = """◆ ʜᴇʏ ᴛʜᴇʀᴇ 👋 💗

━━━━━━━━━━━━━━━━━━━━━━━━━━

ᴍɪss ᴍᴇ ? ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ
ᴀɴᴅ ᴋᴇᴇᴘ ɪᴛ sᴀғᴇ ғʀᴏᴍ sᴘᴀᴍ & ᴛᴏxɪᴄɪᴛʏ

━━━━━━━━━━━━━━━━━━━━━━━━━━

• ᴀᴅᴅ ᴍᴇ ɴᴏᴡ •"""
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("• ᴀᴅᴅ ᴍᴇ ʙᴀʙʏ •", url=f"https://t.me/{self.application.bot.username}?startgroup=true")]]
            )
            for user_id in users:
                try:
                    await self.application.bot.send_message(chat_id=user_id, text=promo_text, reply_markup=keyboard)
                except Exception:
                    continue
        except Exception as exc:
            logger.error("DM promotion error: %s", exc)

    async def _get_total_groups(self) -> int:
        return len(await get_all_groups())

    async def _get_total_violations(self) -> int:
        async with db_manager.get_session() as session:
            rows = await session.execute(select(GroupUser.violation_count))
            return int(sum(row[0] or 0 for row in rows.all()))


governor_bot = AIGovernorBot()


async def run_bot() -> None:
    """Run the bot with database initialization and graceful shutdown."""
    await db_manager.initialize()
    await db_manager.create_tables()

    await governor_bot.initialize()
    app = governor_bot.application
    if app is None:
        raise RuntimeError("Telegram application failed to initialize")

    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(run_bot())
