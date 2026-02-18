import io
import logging
import os
import re
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from telegram import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from database import GroupUser, db_manager
from ai_services import moderation_service
from helpers import auto_delete_message, ensure_user_joined, get_group_settings

logger = logging.getLogger(__name__)

TOXIC_THRESHOLD = 0.7
ILLEGAL_THRESHOLD = 0.6
MUTE_HOURS = 24
DELETE_ADMIN_MESSAGES = os.getenv("DELETE_ADMIN_MESSAGES", "false").lower() in {"1", "true", "yes", "on"}
URL_PATTERN = re.compile(r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+")


async def moderate_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.effective_user:
        return

    message = update.message or update.edited_message
    if not message or not message.text:
        return

    user = update.effective_user
    chat = update.effective_chat

    if user.is_bot:
        return

    if chat.type == ChatType.PRIVATE:
        if not await ensure_user_joined(update, context):
            return
        return

    if await _is_user_admin(update, context):
        return

    settings = await get_group_settings(chat.id)

    if settings.get("link_filter", True):
        urls = await detect_links(message.text)
        for url in urls:
            result = await check_link_safety(url)
            if not result.get("is_safe", True):
                await message.delete()
                warn_count = await _increment_warning(chat.id, user.id)
                await _send_violation_notice(context, chat.id, user, "link blocked", warn_count, "link")
                return

    result = await moderation_service.analyze_text(message.text, caption=message.caption)
    is_safe = bool(result.get("is_safe", True))
    toxic_score = float(result.get("toxic_score", 0.0))
    illegal_score = float(result.get("illegal_score", 0.0))
    threshold = float(settings.get("toxic_threshold", TOXIC_THRESHOLD))

    if is_safe and toxic_score <= threshold and illegal_score <= ILLEGAL_THRESHOLD:
        return

    await message.delete()
    warn_count = await _increment_warning(chat.id, user.id)
    await _send_violation_notice(context, chat.id, user, result.get("reason", "violation"), warn_count, "text")


async def moderate_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.photo or not update.effective_chat or not update.effective_user:
        return

    message = update.message
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == ChatType.PRIVATE:
        if not await ensure_user_joined(update, context):
            return

    if chat.type != ChatType.PRIVATE and await _is_user_admin(update, context):
        return

    caption_result = await moderation_service.analyze_text("", caption=message.caption or "")

    try:
        largest_photo = message.photo[-1]
        telegram_file = await largest_photo.get_file()
        buffer = io.BytesIO()
        await telegram_file.download_to_memory(out=buffer)
        image_bytes = buffer.getvalue()
        image_result = await moderation_service.analyze_image(image_bytes)
    except Exception as e:
        logger.error(f"Image Download/Process Error: {e}")
        image_result = {"is_safe": True}

    image_unsafe = image_result.get("is_safe") is False
    caption_unsafe = caption_result.get("is_safe") is False or float(caption_result.get("toxic_score", 0.0)) > TOXIC_THRESHOLD

    if image_unsafe or caption_unsafe:
        reason = image_result.get("reason") if image_unsafe else caption_result.get("reason")
        if chat.type != ChatType.PRIVATE:
            await message.delete()
            warn_count = await _increment_warning(chat.id, user.id)
            await _send_violation_notice(context, chat.id, user, reason or "violation", warn_count, "photo")


async def moderate_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.effective_user:
        return
    message = update.message
    if not message or not message.sticker:
        return
    chat = update.effective_chat
    user = update.effective_user
    if await _is_user_admin(update, context):
        return
    settings = await get_group_settings(chat.id)
    if not settings.get("sticker_filter", True):
        return
    try:
        sticker_file = await message.sticker.get_file()
        buffer = io.BytesIO()
        await sticker_file.download_to_memory(out=buffer)
        result = await moderation_service.analyze_sticker(buffer.getvalue(), message.sticker.is_animated, message.sticker.set_name)
        if not result.get("is_safe", True):
            await message.delete()
            warn_count = await _increment_warning(chat.id, user.id)
            await _send_violation_notice(context, chat.id, user, result.get("reason", "sticker blocked"), warn_count, "sticker")
    except Exception as e:
        logger.error(f"Sticker error: {e}")


async def moderate_animation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.effective_user:
        return
    message = update.message
    if not message or not message.animation:
        return
    chat = update.effective_chat
    user = update.effective_user
    if await _is_user_admin(update, context):
        return
    settings = await get_group_settings(chat.id)
    if not settings.get("gif_filter", True):
        return
    try:
        anim_file = await message.animation.get_file()
        buffer = io.BytesIO()
        await anim_file.download_to_memory(out=buffer)
        result = await moderation_service.analyze_animation(buffer.getvalue(), message.animation.mime_type, message.animation.file_name)
        if not result.get("is_safe", True):
            await message.delete()
            warn_count = await _increment_warning(chat.id, user.id)
            await _send_violation_notice(context, chat.id, user, result.get("reason", "gif blocked"), warn_count, "gif")
    except Exception as e:
        logger.error(f"Animation error: {e}")


async def moderate_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    return


async def moderate_edited_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.edited_message:
        return
    message = update.edited_message
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user or not message.text:
        return
    if await _is_user_admin(update, context):
        return
    result = await moderation_service.analyze_text(message.text)
    if not result.get("is_safe", True):
        await message.delete()
        notice = await context.bot.send_message(
            chat_id=chat.id,
            text=f"""◆ ᴇᴅɪᴛᴇᴅ ᴍsɢ ʀᴇᴍᴏᴠᴇᴅ ✏️🚫

━━━━━━━━━━━━━━━━━━━━━━━━━━

👤 ᴜsᴇʀ : {user.mention_html()}
⚠️ ʀᴇᴀsᴏɴ : {result.get('reason')}

━━━━━━━━━━━━━━━━━━━━━━━━━━""",
            parse_mode="HTML",
        )
        asyncio.create_task(auto_delete_message(notice, int((await get_group_settings(chat.id)).get("auto_delete_edited", 300))))


async def moderate_edited_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.edited_message:
        return
    message = update.edited_message
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user or not message.photo:
        return
    if await _is_user_admin(update, context):
        return
    try:
        if message.caption:
            cap = await moderation_service.analyze_text(message.caption)
            if not cap.get("is_safe", True):
                await message.delete()
                notice = await context.bot.send_message(chat_id=chat.id, text=f"""◆ ᴇᴅɪᴛᴇᴅ ᴘʜᴏᴛᴏ ʀᴇᴍᴏᴠᴇᴅ ✏️🚫

👤 {user.mention_html()}""", parse_mode="HTML")
                asyncio.create_task(auto_delete_message(notice, int((await get_group_settings(chat.id)).get("auto_delete_edited", 300))))
                return
        largest_photo = message.photo[-1]
        telegram_file = await largest_photo.get_file()
        buffer = io.BytesIO()
        await telegram_file.download_to_memory(out=buffer)
        image_bytes = buffer.getvalue()
        result = await moderation_service.analyze_image(image_bytes)
        if not result.get("is_safe", True):
            await message.delete()
            notice = await context.bot.send_message(chat_id=chat.id, text=f"""◆ ᴇᴅɪᴛᴇᴅ ᴘʜᴏᴛᴏ ʀᴇᴍᴏᴠᴇᴅ ✏️🚫

👤 {user.mention_html()}""", parse_mode="HTML")
            asyncio.create_task(auto_delete_message(notice, int((await get_group_settings(chat.id)).get("auto_delete_edited", 300))))
    except Exception as e:
        logger.error(f"Edited photo error: {e}")


async def detect_links(text: str) -> list:
    if not text:
        return []
    return URL_PATTERN.findall(text)


async def check_link_safety(url: str) -> dict:
    suspicious = [
        r"bit\.ly", r"tinyurl", r"short\.link",
        r"free.*money", r"click.*here", r"urgent.*action",
        r"verify.*account", r"suspend.*account",
    ]
    url_lower = url.lower()
    for pattern in suspicious:
        if re.search(pattern, url_lower):
            return {"is_safe": False, "reason": "suspicious link"}
    return {"is_safe": True}


async def _send_violation_notice(context, chat_id, user, reason, warn_count, content_type):
    settings = await get_group_settings(chat_id)
    max_warnings = int(settings.get("max_warnings", 3))
    if warn_count < max_warnings:
        text = f"""◆ ᴄᴏɴᴛᴇɴᴛ ʀᴇᴍᴏᴠᴇᴅ 🚫

━━━━━━━━━━━━━━━━━━━━━━━━━━

👤 ᴜsᴇʀ : {user.mention_html()}
⚠️ ʀᴇᴀsᴏɴ : {reason}
📝 ᴡᴀʀɴɪɴɢ : {warn_count}/{max_warnings}

━━━━━━━━━━━━━━━━━━━━━━━━━━"""
        keyboard = None
    else:
        mute_duration = int(settings.get("mute_duration", MUTE_HOURS))
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=datetime.now(timezone.utc) + timedelta(hours=mute_duration),
        )
        text = f"""◆ ᴜsᴇʀ ᴍᴜᴛᴇᴅ 🔇

━━━━━━━━━━━━━━━━━━━━━━━━━━

👤 ᴜsᴇʀ : {user.mention_html()}
⏱️ ᴅᴜʀᴀᴛɪᴏɴ : {mute_duration}ʜ
⚠️ ʀᴇᴀsᴏɴ : {max_warnings}/{max_warnings} ᴡᴀʀɴɪɴɢs

━━━━━━━━━━━━━━━━━━━━━━━━━━"""
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 ᴜɴᴍᴜᴛᴇ", callback_data=f"unmute_{user.id}")]])

    notice = await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=keyboard)
    asyncio.create_task(auto_delete_message(notice, int(settings.get("auto_delete_violation", 30))))


async def _is_user_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_chat.type == ChatType.PRIVATE:
        return False
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except Exception:
        return False


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
