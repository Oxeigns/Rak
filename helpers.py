"""Shared helper utilities for join-gating, styling, and group settings."""

from __future__ import annotations

import asyncio
import logging
from functools import wraps
from typing import Any, Awaitable, Callable, TypeVar

from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ContextTypes

from database import Group, GroupSettings, db_manager
from settings import get_settings
from styled_helpers import (
    font_times,
    styled_alert,
    styled_info,
    styled_panel_title,
    styled_success,
)

logger = logging.getLogger(__name__)
settings = get_settings()

FORCE_JOIN_CHANNEL_ID = settings.FORCE_JOIN_CHANNEL_ID
FORCE_JOIN_CHANNEL_LINK = settings.FORCE_JOIN_CHANNEL_LINK
VERIFY_CALLBACK_DATA = "verify_join"

_ALLOWED_STATUSES = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.OWNER,
}

HandlerFunc = TypeVar("HandlerFunc", bound=Callable[..., Awaitable[None]])

DEFAULT_GROUP_SETTINGS: dict[str, Any] = {
    "language": "en",
    "strict_mode": False,
    "text_filter": True,
    "image_filter": True,
    "sticker_filter": True,
    "gif_filter": True,
    "link_filter": True,
    "ai_moderation_enabled": True,
    "bot_moderation": True,
    "auto_delete": True,
    "auto_delete_time": settings.AUTO_DELETE_BOT_MSG,
    "auto_delete_violation": settings.AUTO_DELETE_VIOLATION,
    "auto_delete_edited": settings.AUTO_DELETE_EDITED,
    "toxic_threshold": 0.7,
    "mute_duration": 24,
    "max_warnings": 3,
}


def _localized_force_join_text(language: str) -> str:
    if language == "hi":
        return styled_alert(
            "Access Denied",
            "Rak bot इस्तेमाल करने से पहले official channel join करें।\nJoin के बाद Verify दबाएं।",
        )
    return styled_alert(
        "Access Denied",
        "Join the official channel to continue using Rak.\nAfter joining, tap Verify.",
    )


def styled_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(font_times("🧠 Moderation"), callback_data="panel_moderation")],
            [InlineKeyboardButton(font_times("🛡️ Security"), callback_data="panel_security")],
            [InlineKeyboardButton(font_times("⚙️ Settings"), callback_data="panel_settings")],
        ]
    )


def moderation_actions_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(font_times("🔇 Mute"), callback_data=f"mute_{user_id}")],
            [InlineKeyboardButton(font_times("⛔ Ban"), callback_data=f"ban_{user_id}")],
            [InlineKeyboardButton(font_times("⚠️ Warn"), callback_data=f"warn_{user_id}")],
            [InlineKeyboardButton(font_times("🔓 Unmute"), callback_data=f"unmute_{user_id}")],
        ]
    )


def _force_join_keyboard() -> InlineKeyboardMarkup:
    rows = []
    if FORCE_JOIN_CHANNEL_LINK:
        rows.append([InlineKeyboardButton(font_times("📢 Join Official Channel"), url=FORCE_JOIN_CHANNEL_LINK)])
    rows.append([InlineKeyboardButton(font_times("✅ Done / Verify"), callback_data=VERIFY_CALLBACK_DATA)])
    return InlineKeyboardMarkup(rows)


async def _is_joined(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False
    if not FORCE_JOIN_CHANNEL_ID or FORCE_JOIN_CHANNEL_ID == 0:
        return True
    try:
        member = await context.bot.get_chat_member(FORCE_JOIN_CHANNEL_ID, user.id)
        return member.status in _ALLOWED_STATUSES
    except (Forbidden, BadRequest) as exc:
        logger.warning("Force-join membership check failed for user %s: %s", user.id, exc)
        return False
    except TelegramError as exc:
        logger.error("Telegram error during force-join check: %s", exc)
        return False


async def send_force_join_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send force-join prompt with styled Times New Roman card."""
    language = "en"
    if update.effective_chat and update.effective_chat.type != ChatType.PRIVATE:
        group_settings = await get_group_settings(update.effective_chat.id)
        language = group_settings.get("language", "en")

    params = {
        "text": _localized_force_join_text(language),
        "reply_markup": _force_join_keyboard(),
        "parse_mode": "HTML",
    }
    if update.callback_query and update.callback_query.message:
        await update.callback_query.message.reply_text(**params)
    elif update.message:
        await update.message.reply_text(**params)


async def ensure_user_joined(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if await _is_joined(update, context):
        return True
    await send_force_join_prompt(update, context)
    return False


def is_user_joined(func: HandlerFunc) -> HandlerFunc:
    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        if len(args) < 2:
            return await func(*args, **kwargs)

        update = args[0] if isinstance(args[0], Update) else args[1]
        context = args[1] if isinstance(args[0], Update) else args[2]

        if not isinstance(update, Update):
            return await func(*args, **kwargs)

        if not update.effective_chat:
            return await func(*args, **kwargs)

        is_private = update.effective_chat.type == ChatType.PRIVATE
        is_command = bool(update.message and update.message.text and update.message.text.startswith("/"))
        if (is_private or is_command) and not await _is_joined(update, context):
            await send_force_join_prompt(update, context)
            return None
        return await func(*args, **kwargs)

    return wrapper


async def verify_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    if await _is_joined(update, context):
        await query.answer(font_times("Verification successful."), show_alert=True)
        if query.message:
            try:
                await query.message.edit_text(
                    text=styled_success("Verification Successful", "You now have access to Rak controls."),
                    parse_mode="HTML",
                )
            except TelegramError:
                logger.debug("Could not edit verification prompt message", exc_info=True)
    else:
        await query.answer(font_times("Join channel first, then verify."), show_alert=True)


async def auto_delete_message(message: Message | None, delay_seconds: int) -> None:
    if not message or delay_seconds <= 0:
        return
    await asyncio.sleep(delay_seconds)
    try:
        await message.delete()
    except TelegramError:
        logger.debug("Auto-delete failed", exc_info=True)


async def get_group_settings(group_id: int) -> dict[str, Any]:
    config = {"group_id": group_id, **DEFAULT_GROUP_SETTINGS}
    try:
        async with db_manager.get_session() as session:
            group = (await session.execute(select(Group).where(Group.id == group_id))).scalar_one_or_none()
            group_settings = (
                await session.execute(select(GroupSettings).where(GroupSettings.group_id == group_id))
            ).scalar_one_or_none()

            if group:
                config["language"] = group.language or "en"
                config["strict_mode"] = bool(group.strict_mode)
            if group_settings:
                config["ai_moderation_enabled"] = bool(group_settings.ai_moderation_enabled)
                if group_settings.config:
                    config.update(group_settings.config)
    except Exception:
        logger.exception("Failed to fetch group settings for %s", group_id)
    return config


async def update_group_setting(group_id: int, setting: str, value: Any) -> bool:
    custom_settings = set(DEFAULT_GROUP_SETTINGS.keys())
    try:
        async with db_manager.get_session() as session:
            group_settings = (
                await session.execute(select(GroupSettings).where(GroupSettings.group_id == group_id))
            ).scalar_one_or_none()
            if setting in custom_settings:
                if not group_settings:
                    group_settings = GroupSettings(group_id=group_id, config={})
                    session.add(group_settings)
                group_settings.config = {**(group_settings.config or {}), setting: value}
            else:
                group = (await session.execute(select(Group).where(Group.id == group_id))).scalar_one_or_none()
                if not group or not hasattr(group, setting):
                    return False
                setattr(group, setting, value)
            await session.commit()
            return True
    except Exception:
        logger.exception("Failed to update group setting %s for %s", setting, group_id)
        return False


def styled_panel_title_text(title: str) -> str:
    return styled_panel_title(title)


def styled_info_message(title: str, body: str) -> str:
    return styled_info(title, body)
