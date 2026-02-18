from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError
from telegram.ext import ContextTypes

from core.security import CallbackSigner
from handlers.commands import SECURE_PANEL_TEXT, build_secure_panel_keyboard

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

        if query.data != 'secure_panel':
            await query.answer('Invalid panel action.', show_alert=True)
            return

        keyboard = build_secure_panel_keyboard('secure_panel')

        try:
            try:
                await query.message.edit_text(
                    text=SECURE_PANEL_TEXT,
                    reply_markup=keyboard,
                    parse_mode='Markdown',
                )
            except Exception as exc:
                logger.error('Panel render failed: %s', exc, exc_info=exc)
                await query.message.reply_text(
                    text=SECURE_PANEL_TEXT,
                    reply_markup=keyboard,
                    parse_mode='Markdown',
                )

            await query.answer()
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
