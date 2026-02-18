from __future__ import annotations

import logging
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError
from telegram.ext import ApplicationHandlerStop, ContextTypes

from core.config import AppConfig
from core.security import CooldownManager, UserRateLimiter

logger = logging.getLogger(__name__)

_ALLOWED = {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}


class ForceJoinMiddleware:
    def __init__(self, config: AppConfig, limiter: UserRateLimiter, cooldown: CooldownManager) -> None:
        self.config = config
        self.limiter = limiter
        self.cooldown = cooldown

    async def __call__(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not user or not self.config.REQUIRE_FORCE_JOIN:
            return

        if not self.limiter.check(user.id):
            await self._rate_limit_response(update, context)
            raise ApplicationHandlerStop

        joined = await self._check_membership(user.id, context)
        if joined:
            return

        if not self.cooldown.should_prompt(user.id):
            raise ApplicationHandlerStop

        await self._prompt_force_join(update, context)
        raise ApplicationHandlerStop

    async def _check_membership(self, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
        try:
            member = await context.bot.get_chat_member(self.config.FORCE_JOIN_CHANNEL_ID, user_id)
            return member.status in _ALLOWED
        except RetryAfter as exc:
            logger.warning('RetryAfter in force-join membership check.', extra={'user_id': user_id, 'action': 'force_join_check', 'error_type': type(exc).__name__})
            return False
        except (BadRequest, Forbidden) as exc:
            logger.warning('Membership check denied/misconfigured.', extra={'user_id': user_id, 'chat_id': self.config.FORCE_JOIN_CHANNEL_ID, 'action': 'force_join_check', 'error_type': type(exc).__name__})
            return False
        except (NetworkError, TelegramError) as exc:
            logger.error('Telegram API failure in membership check.', exc_info=exc, extra={'user_id': user_id, 'chat_id': self.config.FORCE_JOIN_CHANNEL_ID, 'action': 'force_join_check', 'error_type': type(exc).__name__})
            return False

    async def _rate_limit_response(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query:
            await query.answer('Too many requests. Please slow down.', show_alert=True)
            return
        message = update.effective_message
        if message:
            await message.reply_text('⚠️ Slow down. You are sending too many requests.')

    def _join_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton('Join Channel', url=self.config.FORCE_JOIN_CHANNEL_LINK)],
                [InlineKeyboardButton('Verify Join', callback_data='force_join:verify')],
            ]
        )

    async def _prompt_force_join(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        msg_text = 'Access denied. Join the required channel first, then tap Verify Join.'

        if query:
            await query.answer('Join channel first.', show_alert=True)
            if query.message:
                await query.message.reply_text(msg_text, reply_markup=self._join_keyboard())
            return

        message = update.effective_message
        if message:
            await message.reply_text(msg_text, reply_markup=self._join_keyboard())


async def safe_send_message(context: ContextTypes.DEFAULT_TYPE, *, chat_id: int, text: str, action: str, user_id: Optional[int] = None, **kwargs):
    try:
        return await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
    except RetryAfter as exc:
        logger.warning('RetryAfter while sending message.', extra={'user_id': user_id, 'chat_id': chat_id, 'action': action, 'error_type': type(exc).__name__})
        raise
    except (BadRequest, Forbidden, NetworkError, TelegramError) as exc:
        logger.error('Failed to send message.', exc_info=exc, extra={'user_id': user_id, 'chat_id': chat_id, 'action': action, 'error_type': type(exc).__name__})
        raise


async def safe_edit_message(query, *, text: str, action: str, user_id: Optional[int] = None, **kwargs):
    if not query or not query.message:
        raise BadRequest('Callback query message is missing or deleted.')
    try:
        return await query.edit_message_text(text=text, **kwargs)
    except RetryAfter as exc:
        logger.warning('RetryAfter while editing message.', extra={'user_id': user_id, 'chat_id': query.message.chat_id, 'action': action, 'error_type': type(exc).__name__})
        raise
    except (BadRequest, Forbidden, NetworkError, TelegramError) as exc:
        logger.error('Failed to edit message.', exc_info=exc, extra={'user_id': user_id, 'chat_id': query.message.chat_id, 'action': action, 'error_type': type(exc).__name__})
        raise
