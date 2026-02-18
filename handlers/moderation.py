from __future__ import annotations

import logging

from telegram import Update
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError
from telegram.ext import ContextTypes

from utils.safe_telegram import safe_send_message

logger = logging.getLogger(__name__)


class ModerationHandlers:
    async def moderate_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        user = update.effective_user
        chat = update.effective_chat

        if not message or not chat or not user or not message.text:
            return

        text = message.text.lower()
        if 'spam' in text or 'scam' in text:
            try:
                await message.delete()
                await safe_send_message(
                    context,
                    chat_id=chat.id,
                    text='Message removed by moderation policy.',
                    action='moderate_text_delete',
                    user_id=user.id,
                    handler_name='ModerationHandlers.moderate_text',
                )
            except RetryAfter as exc:
                logger.warning('RetryAfter during moderation delete.', extra={'user_id': user.id, 'chat_id': chat.id, 'action': 'moderate_text', 'error_type': type(exc).__name__})
            except (BadRequest, Forbidden, NetworkError, TelegramError) as exc:
                logger.error('Moderation action failed.', exc_info=exc, extra={'user_id': user.id, 'chat_id': chat.id, 'action': 'moderate_text', 'error_type': type(exc).__name__})

    async def report(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat = update.effective_chat
        user = update.effective_user
        if not message or not chat or not user:
            return

        if not message.reply_to_message:
            await safe_send_message(context, chat_id=chat.id, text='Reply to a message to report it.', action='report_missing_reply', user_id=user.id, handler_name='ModerationHandlers.report')
            return

        target = message.reply_to_message.from_user
        await safe_send_message(
            context,
            chat_id=chat.id,
            text=f'Report logged for user {target.id if target else "unknown"}.',
            action='report_submit',
            user_id=user.id,
            handler_name='ModerationHandlers.report',
        )
