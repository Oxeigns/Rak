from __future__ import annotations

import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError
from telegram.ext import ApplicationHandlerStop, ContextTypes

from core.config import AppConfig
from core.security import CooldownManager, UserRateLimiter
from utils.safe_telegram import safe_send_message

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
            wait_seconds = max(1, int(exc.retry_after))
            logger.warning(
                'RetryAfter in force-join membership check; waiting before deny.',
                extra={'user_id': user_id, 'chat_id': self.config.FORCE_JOIN_CHANNEL_ID, 'action': 'force_join_check', 'error_type': type(exc).__name__},
                exc_info=exc,
            )
            await asyncio.sleep(wait_seconds)
            return False
        except Forbidden as exc:
            logger.error(
                'Bot lacks rights to verify force-join status.',
                extra={'user_id': user_id, 'chat_id': self.config.FORCE_JOIN_CHANNEL_ID, 'action': 'force_join_check', 'error_type': type(exc).__name__},
                exc_info=exc,
            )
            return False
        except BadRequest as exc:
            logger.error(
                'Force-join channel misconfigured or invalid.',
                extra={'user_id': user_id, 'chat_id': self.config.FORCE_JOIN_CHANNEL_ID, 'action': 'force_join_check', 'error_type': type(exc).__name__},
                exc_info=exc,
            )
            return False
        except (NetworkError, TelegramError) as exc:
            logger.error(
                'Telegram API failure in membership check.',
                extra={'user_id': user_id, 'chat_id': self.config.FORCE_JOIN_CHANNEL_ID, 'action': 'force_join_check', 'error_type': type(exc).__name__},
                exc_info=exc,
            )
            return False

    async def _rate_limit_response(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query:
            await query.answer('Too many requests. Please slow down.', show_alert=True)
            return

        message = update.effective_message
        if message:
            await safe_send_message(
                context,
                chat_id=message.chat_id,
                text='⚠️ Slow down. You are sending too many requests.',
                action='rate_limit_prompt',
                user_id=update.effective_user.id if update.effective_user else None,
                handler_name='ForceJoinMiddleware._rate_limit_response',
            )

    def _join_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton('Join Channel', url=self.config.force_join_channel_link)],
                [InlineKeyboardButton('Verify Join', callback_data='force_join:verify')],
            ]
        )

    async def _prompt_force_join(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg_text = 'Access denied. Join the required channel first, then tap Verify Join.'
        user_id = update.effective_user.id if update.effective_user else None

        query = update.callback_query
        if query:
            try:
                await query.answer('Join channel first.', show_alert=True)
            except (RetryAfter, BadRequest, Forbidden, NetworkError, TelegramError) as exc:
                logger.warning(
                    'Failed answering force-join callback prompt.',
                    extra={
                        'user_id': user_id,
                        'chat_id': query.message.chat_id if query.message else None,
                        'action': 'force_join_prompt_callback_answer',
                        'handler_name': 'ForceJoinMiddleware._prompt_force_join',
                        'error_type': type(exc).__name__,
                    },
                    exc_info=exc,
                )

            if query.message:
                await safe_send_message(
                    context,
                    chat_id=query.message.chat_id,
                    text=msg_text,
                    action='force_join_prompt_callback',
                    user_id=user_id,
                    handler_name='ForceJoinMiddleware._prompt_force_join',
                    reply_markup=self._join_keyboard(),
                )
            return

        message = update.effective_message
        if message:
            await safe_send_message(
                context,
                chat_id=message.chat_id,
                text=msg_text,
                action='force_join_prompt_message',
                user_id=user_id,
                handler_name='ForceJoinMiddleware._prompt_force_join',
                reply_markup=self._join_keyboard(),
            )
