import io
import logging
import os
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict

from sqlalchemy import select
from telegram import ChatPermissions, Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from models.database import GroupUser, db_manager
from services.ai_service import moderation_service
from utils.helpers import ensure_user_joined

logger = logging.getLogger(__name__)

TOXIC_THRESHOLD = 0.7
ILLEGAL_THRESHOLD = 0.6
MUTE_HOURS = 24  # Standard mute duration
DELETE_ADMIN_MESSAGES = os.getenv("DELETE_ADMIN_MESSAGES", "false").lower() in {"1", "true", "yes", "on"}

async def moderate_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Moderate text-only messages with Groq."""
    if not update.message or not update.message.text or not update.effective_chat or not update.effective_user:
        return

    message = update.message
    user = update.effective_user
    chat = update.effective_chat

    if user.is_bot: return

    # Private chat check
    if chat.type == ChatType.PRIVATE:
        if not await ensure_user_joined(update, context):
            return

    # Call AI Service
    text_result = await moderation_service.analyze_text(message.text, caption=message.caption)
    
    # Violation Check Logic
    is_safe = text_result.get("is_safe", True)
    toxic_score = float(text_result.get("toxic_score", 0.0))
    illegal_score = float(text_result.get("illegal_score", 0.0))

    if is_safe is False or toxic_score > TOXIC_THRESHOLD or illegal_score > ILLEGAL_THRESHOLD:
        is_admin = await _is_user_admin(update, context)
        await _process_violation(
            update=update,
            context=context,
            is_admin=is_admin,
            reason=text_result.get("reason", "Policy Violation"),
        )

async def moderate_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Moderate photo and caption via Gemini + Groq."""
    if not update.message or not update.message.photo or not update.effective_chat or not update.effective_user:
        return

    message = update.message
    chat = update.effective_chat

    if chat.type == ChatType.PRIVATE:
        if not await ensure_user_joined(update, context):
            return

    # 1. Analyze Caption first (Groq)
    caption_result = await moderation_service.analyze_text("", caption=message.caption or "")
    
    # 2. Analyze Image (Gemini)
    try:
        largest_photo = message.photo[-1]
        telegram_file = await largest_photo.get_file()
        buffer = io.BytesIO()
        await telegram_file.download_to_memory(out=buffer)
        image_bytes = buffer.getvalue()
        image_result = await moderation_service.analyze_image(image_bytes)
    except Exception as e:
        logger.error(f"Image Download/Process Error: {e}")
        image_result = {"is_safe": True} # Fallback to safe if download fails to avoid false positives

    # Violation triggers
    image_unsafe = image_result.get("is_safe") is False
    caption_unsafe = caption_result.get("is_safe") is False or \
                     float(caption_result.get("toxic_score", 0.0)) > TOXIC_THRESHOLD

    if image_unsafe or caption_unsafe:
        reason = image_result.get("reason") if image_unsafe else caption_result.get("reason")
        is_admin = await _is_user_admin(update, context)
        await _process_violation(update, context, is_admin, reason)

async def _process_violation(update: Update, context: ContextTypes.DEFAULT_TYPE, is_admin: bool, reason: str) -> None:
    chat = update.effective_chat
    user = update.effective_user
    message = update.message

    # 1. Delete Logic
    if not is_admin or DELETE_ADMIN_MESSAGES:
        try:
            await message.delete()
        except Exception as e:
            logger.warning(f"Could not delete message: {e}")

    if is_admin:
        await context.bot.send_message(chat.id, f"🛡️ Admin @{user.username}, aapka content AI ne risky bataya: {reason}")
        return

    # 2. Warning System
    warn_count = await _increment_warning(chat.id, user.id)
    mention = user.mention_html()

    if warn_count == 1:
        await context.bot.send_message(
            chat.id, 
            f"⚠️ {mention}, Warning 1/3: AI ne aapke message ko unsafe paya.\n<b>Reason:</b> {reason}",
            parse_mode="HTML"
        )
    elif warn_count == 2:
        await context.bot.send_message(
            chat.id,
            f"⚠️ {mention}, Warning 2/3: Sudhar jao bhai, agle pe mute ho jaoge!",
            parse_mode="HTML"
        )
    else:
        # Mute for 24 hours
        try:
            # Re-calculating to ensure fresh timestamp
            mute_until = datetime.now(timezone.utc) + timedelta(hours=MUTE_HOURS)
            await context.bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=mute_until
            )
            await context.bot.send_message(
                chat_id=chat.id,
                text=f"🚫 {mention} ko violation ki wajah se {MUTE_HOURS} ghante ke liye mute kar diya gaya.",
                parse_mode="HTML"
            )
            # Reset warnings after mute
            await _reset_warnings(chat.id, user.id)
        except TelegramError as e:
            logger.error(f"Failed to mute user {user.id}: {e}")

async def _is_user_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_chat.type == ChatType.PRIVATE: return False
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except: return False

async def _increment_warning(chat_id: int, user_id: int) -> int:
    async with db_manager.get_session() as session:
        stmt = select(GroupUser).where(GroupUser.group_id == chat_id, GroupUser.user_id == user_id)
        res = await session.execute(stmt)
        user_record = res.scalar_one_or_none()

        if not user_record:
            user_record = GroupUser(group_id=chat_id, user_id=user_id, violation_count=1)
            session.add(user_record)
        else:
            user_record.violation_count += 1
        
        await session.commit()
        return user_record.violation_count

async def _reset_warnings(chat_id: int, user_id: int):
    async with db_manager.get_session() as session:
        stmt = select(GroupUser).where(GroupUser.group_id == chat_id, GroupUser.user_id == user_id)
        res = await session.execute(stmt)
        record = res.scalar_one_or_none()
        if record:
            record.violation_count = 0
            await session.commit()
