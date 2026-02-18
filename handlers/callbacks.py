from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError
from telegram.ext import ContextTypes

from core.security import CallbackSecurityError, CallbackSigner
from utils.safe_telegram import safe_edit_message

logger = logging.getLogger(__name__)


class CallbackHandlers:
    def __init__(self, signer: CallbackSigner) -> None:
        self.signer = signer

    async def handle_force_join_verify(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user = update.effective_user
        if not query or not user:
            return

        try:
            member = await context.bot.get_chat_member(context.application.bot_data['force_join_channel_id'], user.id)
            if member.status in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}:
                await query.answer('Membership verified. Please retry your command.')
                return
            await query.answer('Join the required channel first.', show_alert=True)
        except RetryAfter as exc:
            await query.answer('Verification is rate-limited. Please retry shortly.', show_alert=True)
            logger.warning(
                'RetryAfter while verifying force-join from callback.',
                extra={
                    'user_id': user.id,
                    'chat_id': query.message.chat_id if query.message else None,
                    'action': 'force_join_verify',
                    'handler_name': 'CallbackHandlers.handle_force_join_verify',
                    'error_type': type(exc).__name__,
                },
                exc_info=exc,
            )
        except (BadRequest, Forbidden, NetworkError, TelegramError) as exc:
            await query.answer('Verification failed. Please retry in a moment.', show_alert=True)
            logger.error(
                'Failed force-join callback verification.',
                extra={
                    'user_id': user.id,
                    'chat_id': query.message.chat_id if query.message else None,
                    'action': 'force_join_verify',
                    'handler_name': 'CallbackHandlers.handle_force_join_verify',
                    'error_type': type(exc).__name__,
                },
                exc_info=exc,
            )

    async def secure_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user = update.effective_user
        if not query or not user:
            return

        try:
            await self.signer.verify(query.data or '', user.id, required_action='open_panel')
            edit_result = await safe_edit_message(
                query,
                text='Secure panel opened successfully.',
                action='secure_callback',
                user_id=user.id,
                handler_name='CallbackHandlers.secure_callback',
            )
            if edit_result is None:
                await query.answer('This panel message is stale. Please run /start again.', show_alert=True)
                return

            await query.answer('Done')
        except CallbackSecurityError as exc:
            await query.answer(str(exc), show_alert=True)
            logger.warning(
                'Blocked insecure callback interaction.',
                extra={
                    'user_id': user.id,
                    'chat_id': query.message.chat_id if query.message else None,
                    'action': 'secure_callback',
                    'handler_name': 'CallbackHandlers.secure_callback',
                    'error_type': type(exc).__name__,
                },
                exc_info=exc,
            )
        except RetryAfter as exc:
            await query.answer('Server busy, retry in a moment.', show_alert=True)
            logger.warning(
                'RetryAfter in secure callback.',
                extra={'user_id': user.id, 'action': 'secure_callback', 'handler_name': 'CallbackHandlers.secure_callback', 'error_type': type(exc).__name__},
                exc_info=exc,
            )
        except BadRequest as exc:
            await query.answer('Action failed, message is no longer editable.', show_alert=True)
            logger.error(
                'BadRequest in secure callback.',
                extra={'user_id': user.id, 'action': 'secure_callback', 'handler_name': 'CallbackHandlers.secure_callback', 'error_type': type(exc).__name__},
                exc_info=exc,
            )
        except (Forbidden, NetworkError, TelegramError) as exc:
            await query.answer('Action failed, try again.', show_alert=True)
            logger.error(
                'Telegram error in secure callback.',
                extra={'user_id': user.id, 'action': 'secure_callback', 'handler_name': 'CallbackHandlers.secure_callback', 'error_type': type(exc).__name__},
                exc_info=exc,
            )
