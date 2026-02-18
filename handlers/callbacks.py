from __future__ import annotations

import logging

from telegram import Update
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
        if not query or not update.effective_user:
            return
        await query.answer('Verification is automatic. Retry your command.')

    async def secure_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user = update.effective_user
        if not query or not user:
            return

        try:
            await self.signer.verify(query.data or '', user.id, required_action='open_panel')
            await safe_edit_message(
                query,
                text='Secure panel opened successfully.',
                action='secure_callback',
                user_id=user.id,
                handler_name='CallbackHandlers.secure_callback',
            )
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
