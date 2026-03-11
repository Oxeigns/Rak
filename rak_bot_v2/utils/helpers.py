"""Reusable helper functions."""

from __future__ import annotations

import asyncio
import functools
import logging
import traceback
from collections import defaultdict, deque
from time import monotonic

from telegram import ChatMemberAdministrator, ChatMemberOwner, Update, User
from telegram.error import BadRequest, Forbidden, RetryAfter
from telegram.ext import ContextTypes

from rak_bot_v2.config.settings import get_settings


LOGGER = logging.getLogger(__name__)
_CALLBACK_HITS: dict[int, deque[float]] = defaultdict(deque)


# ── Admin / Role Checks ────────────────────────────────────────────────────

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Return True if the effective user is a chat administrator or owner."""
    if not update.effective_chat or not update.effective_user:
        return False
    try:
        member = await context.bot.get_chat_member(
            update.effective_chat.id, update.effective_user.id
        )
        return isinstance(member, (ChatMemberAdministrator, ChatMemberOwner))
    except (Forbidden, BadRequest):
        return False


async def is_owner(user_id: int) -> bool:
    """Return True if user_id matches the configured bot owner."""
    return user_id == get_settings().owner_id


async def is_owner_or_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Return True if effective user is the owner or a chat admin."""
    if not update.effective_user:
        return False
    if await is_owner(update.effective_user.id):
        return True
    return await is_admin(update, context)


async def is_target_admin(
    chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Return True if the *target* user (not the command sender) is admin."""
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return isinstance(member, (ChatMemberAdministrator, ChatMemberOwner))
    except (Forbidden, BadRequest):
        return False


# ── Reply Target Resolver ──────────────────────────────────────────────────

def get_reply_target(update: Update) -> User | None:
    """
    Return the User object that the command is targeting.
    Looks at the replied-to message's sender first,
    then falls back to command argument (not implemented here – extend as needed).
    """
    msg = update.effective_message
    if msg and msg.reply_to_message and msg.reply_to_message.from_user:
        return msg.reply_to_message.from_user
    return None


# ── Message Helpers ────────────────────────────────────────────────────────

async def safe_delete(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int
) -> None:
    """Delete a message, silently ignoring Telegram permission/not-found errors."""
    try:
        await context.bot.delete_message(chat_id, message_id)
    except (Forbidden, BadRequest, RetryAfter) as exc:
        LOGGER.warning("delete_failed chat=%s msg=%s err=%s", chat_id, message_id, exc)


async def safe_edit_message_text(
    update: Update, text: str, parse_mode: str = "HTML", **kwargs
) -> None:
    """Edit callback message text, gracefully ignoring 'not modified' errors."""
    query = update.callback_query
    if not query or not query.message:
        return
    if getattr(query.message, "text", "") == text:
        return
    try:
        await query.edit_message_text(text, parse_mode=parse_mode, **kwargs)
    except BadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


async def safe_send_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    parse_mode: str = "HTML",
    max_retries: int = 3,
    **kwargs,
) -> None:
    """Send message with flood-wait handling and bounded retries."""
    for _attempt in range(max_retries):
        try:
            await context.bot.send_message(
                chat_id, text, parse_mode=parse_mode, disable_notification=True, **kwargs
            )
            return
        except RetryAfter as exc:
            LOGGER.warning("flood_wait chat=%s retry=%s", chat_id, exc.retry_after)
            await asyncio.sleep(exc.retry_after)
        except (Forbidden, BadRequest) as exc:
            LOGGER.error("send_failed chat=%s: %s", chat_id, exc)
            return


# ── Force-Join ─────────────────────────────────────────────────────────────

async def enforce_force_join(
    update: Update, context: ContextTypes.DEFAULT_TYPE, channel_id: int
) -> bool:
    """
    Return True if user is already a member of the required channel,
    or if force-join is disabled (channel_id == 0).
    """
    if channel_id == 0 or not update.effective_user:
        return True
    try:
        member = await context.bot.get_chat_member(channel_id, update.effective_user.id)
        return member.status in {"member", "administrator", "creator"}
    except (Forbidden, BadRequest, RetryAfter):
        return False


# ── Rate Limiter ───────────────────────────────────────────────────────────

def callback_allowed(user_id: int, limit: int, window_seconds: int) -> bool:
    """Simple per-user sliding-window callback rate limiter."""
    now = monotonic()
    q = _CALLBACK_HITS[user_id]
    while q and now - q[0] > window_seconds:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


# ── Safe Handler Decorator ─────────────────────────────────────────────────

def safe_handler(func):
    """
    Decorator that catches all unhandled exceptions inside a handler,
    logs them, and prevents them from bubbling up to the polling loop.
    Does NOT send a generic error reply to avoid spamming chats.
    """

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            return await func(update, context)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception(
                "handler_crash: %s.%s - %s\n%s",
                func.__module__,
                func.__name__,
                exc,
                traceback.format_exc(),
            )
        return None

    return wrapper
