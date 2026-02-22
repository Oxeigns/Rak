"""Reusable helper functions."""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from time import monotonic

from telegram import ChatMemberAdministrator, ChatMemberOwner, Update
from telegram.error import BadRequest, Forbidden, RetryAfter
from telegram.ext import ContextTypes

from rak_bot_v2.config.settings import settings

LOGGER = logging.getLogger(__name__)
_CALLBACK_HITS: dict[int, deque[float]] = defaultdict(deque)


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check whether command user is chat admin."""
    if not update.effective_chat or not update.effective_user:
        return False
    member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    return isinstance(member, (ChatMemberAdministrator, ChatMemberOwner))


async def is_owner(user_id: int) -> bool:
    """Return whether the provided user id is bot owner."""
    return user_id == settings.owner_id


async def is_owner_or_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Return True if effective user is owner or chat admin."""
    if not update.effective_user:
        return False
    if await is_owner(update.effective_user.id):
        return True
    return await is_admin(update, context)


async def safe_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> None:
    """Delete message with graceful Telegram error handling."""
    try:
        await context.bot.delete_message(chat_id, message_id)
    except (Forbidden, BadRequest, RetryAfter) as exc:
        LOGGER.warning("delete_failed chat=%s msg=%s err=%s", chat_id, message_id, exc)


async def safe_edit_message_text(update: Update, text: str, parse_mode: str = "HTML") -> None:
    """Safely edit callback message only when it is changed."""
    query = update.callback_query
    if not query or not query.message:
        return
    if getattr(query.message, "text", "") == text:
        return
    try:
        await query.edit_message_text(text, parse_mode=parse_mode)
    except BadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


async def enforce_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE, channel_id: int) -> bool:
    """Return True if user is member or check disabled."""
    if channel_id == 0 or not update.effective_user:
        return True
    try:
        member = await context.bot.get_chat_member(channel_id, update.effective_user.id)
        return member.status in {"member", "administrator", "creator"}
    except (Forbidden, BadRequest, RetryAfter):
        return False


def callback_allowed(user_id: int, limit: int, window_seconds: int) -> bool:
    """Simple per-user callback click rate limiter."""
    now = monotonic()
    q = _CALLBACK_HITS[user_id]
    while q and now - q[0] > window_seconds:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True
