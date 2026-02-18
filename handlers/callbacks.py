"""
Callback Handlers for AI Governor Bot.
Contains all callback query handlers for settings, toggles, and navigation.
"""

import logging
import time
from typing import TYPE_CHECKING

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes
from sqlalchemy import select

from database import Group, GroupSettings, db_manager
from helpers import verify_join_callback
from control_panel import control_panel
from i18n import get_text

if TYPE_CHECKING:
    from bot import AIGovernorBot

logger = logging.getLogger(__name__)


class CallbackHandlers:
    """Mixin for callback query handlers."""

    async def handle_set_autodelete(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    async def handle_set_edited_autodelete(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    async def handle_set_threshold(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    async def handle_set_mute_duration(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    async def handle_set_max_warnings(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    async def handle_callback(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    async def handle_toggle(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    async def handle_action(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    async def handle_language(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    async def handle_personality(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
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

        async with db_manager.get_session() as session:
            result = await session.execute(select(Group).where(Group.id == group_id))
            group = result.scalar_one_or_none()
            if group:
                group.personality_mode = personality
                await session.commit()

        await query.answer(f"Personality set to {personality}")
        await self.handle_callback(update, context)
