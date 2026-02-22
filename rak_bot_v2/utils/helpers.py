"""Reusable helper functions."""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from contextvars import ContextVar
from time import monotonic
from uuid import uuid4

from telegram import ChatMemberAdministrator, ChatMemberOwner, Update
from telegram.error import BadRequest, Forbidden, RetryAfter
from telegram.ext import ContextTypes

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")
LOGGER = logging.getLogger(__name__)
_CALLBACK_HITS: dict[int, deque[float]] = defaultdict(deque)


def set_correlation_id() -> str:
    """Set and return request correlation ID."""
    cid = uuid4().hex[:10]
    correlation_id_var.set(cid)
    return cid


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check whether command user is chat admin."""
    if not update.effective_chat or not update.effective_user:
        return False
    member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    return isinstance(member, (ChatMemberAdministrator, ChatMemberOwner))


async def safe_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> None:
    """Delete message with graceful Telegram error handling."""
    try:
        await context.bot.delete_message(chat_id, message_id)
    except (Forbidden, BadRequest, RetryAfter) as exc:
        LOGGER.warning("delete_failed chat=%s msg=%s err=%s", chat_id, message_id, exc)


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
