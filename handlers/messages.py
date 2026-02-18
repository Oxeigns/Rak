"""
Message Handlers for AI Governor Bot.
Contains message processing, new member handling, and chat member updates.
"""

import logging
from typing import TYPE_CHECKING

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from database import Group, GroupUser, Message, RiskLevel, User, db_manager
from helpers import auto_delete_message, update_group_setting
from ai_moderation import ai_moderation_service
from anti_raid import anti_raid_system
from risk_engine import risk_engine
from trust_engine import trust_engine

if TYPE_CHECKING:
    from bot import AIGovernorBot

logger = logging.getLogger(__name__)


class MessageHandlers:
    """Mixin for message and member handlers."""

    async def handle_text_input(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                    await update.message.reply_text("❌ Must be between 1-100 percent!")
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

            context.user_data.pop("awaiting_input", None)

        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number!")

    async def handle_new_members(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle new chat members with raid detection."""
        if not update.effective_chat or not update.effective_message:
            return

        chat = update.effective_chat
        new_members = update.effective_message.new_chat_members

        if not new_members:
            return

        # Check for raid
        raid_result = await anti_raid_system.check_join_batch(chat.id, new_members)
        if raid_result.is_raid:
            await self._handle_raid_detection(update, context, raid_result)
            return

        # Log new members
        for member in new_members:
            if member.is_bot:
                continue
            await self._ensure_user_exists(member)
            logger.info(f"New member joined: {member.id} in chat {chat.id}")

    async def handle_chat_member(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle chat member updates."""
        if not update.effective_chat or not update.chat_member:
            return

        chat = update.effective_chat
        old_status = update.chat_member.old_chat_member.status
        new_status = update.chat_member.new_chat_member.status

        # Bot added to group
        if update.chat_member.new_chat_member.user.id == context.bot.id:
            if old_status in ["left", "kicked"] and new_status in ["member", "administrator"]:
                await self._create_group(chat)
                await self._send_welcome_message(update, context)

    async def handle_message(self: "AIGovernorBot", update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process incoming messages with AI moderation."""
        if not update.effective_message or not update.effective_chat:
            return

        message = update.effective_message
        chat = update.effective_chat
        user = update.effective_user

        # Skip private chats and non-text messages for moderation
        if chat.type == ChatType.PRIVATE or not message.text:
            return

        # Skip bot messages
        if user and user.is_bot:
            return

        # Ensure group exists in DB
        await self._create_group(chat)

        # Run AI moderation
        try:
            risk_assessment = await ai_moderation_service.analyze_message(
                message.text,
                chat_id=chat.id,
                user_id=user.id if user else None,
            )

            if risk_assessment.should_delete:
                await message.delete()
                await self._handle_violation(update, context, risk_assessment)
                return

            if risk_assessment.should_warn:
                await self._handle_warning(update, context, risk_assessment)

            # Log message
            if user:
                await self._log_message(message, risk_assessment, chat.id, user)

        except Exception as exc:
            logger.exception("Error in message moderation: %s", exc)

    async def handle_error(self: "AIGovernorBot", update: object, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors in handlers with richer diagnostics."""
        logger.error(
            "Exception while handling an update | update=%r | error=%r",
            update,
            context.error,
            exc_info=context.error,
        )

        if isinstance(update, Update) and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    "⚠️ An error occurred while processing your request. Please try again later."
                )
            except Exception:
                pass
