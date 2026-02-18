from __future__ import annotations

import logging
from typing import Optional

from telegram import CallbackQuery
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

_DELETED_MESSAGE_ERRORS = {
    'message to edit not found',
    'message to delete not found',
    'message to be replied not found',
}


async def safe_send_message(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    text: str,
    action: str,
    user_id: Optional[int] = None,
    handler_name: Optional[str] = None,
    **kwargs,
):
    try:
        return await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
    except RetryAfter as exc:
        logger.warning(
            'RetryAfter while sending message.',
            extra={'user_id': user_id, 'chat_id': chat_id, 'action': action, 'handler_name': handler_name, 'error_type': type(exc).__name__},
            exc_info=exc,
        )
        raise
    except (BadRequest, Forbidden, NetworkError, TelegramError) as exc:
        logger.error(
            'Failed to send message.',
            extra={'user_id': user_id, 'chat_id': chat_id, 'action': action, 'handler_name': handler_name, 'error_type': type(exc).__name__},
            exc_info=exc,
        )
        raise


async def safe_edit_message(
    query: CallbackQuery,
    *,
    text: str,
    action: str,
    user_id: Optional[int] = None,
    handler_name: Optional[str] = None,
    **kwargs,
):
    if not query.message:
        raise BadRequest('Callback query message is missing or deleted.')

    try:
        return await query.edit_message_text(text=text, **kwargs)
    except RetryAfter as exc:
        logger.warning(
            'RetryAfter while editing message.',
            extra={
                'user_id': user_id,
                'chat_id': query.message.chat_id,
                'action': action,
                'handler_name': handler_name,
                'error_type': type(exc).__name__,
            },
            exc_info=exc,
        )
        raise
    except BadRequest as exc:
        message = str(exc).lower()
        if any(error in message for error in _DELETED_MESSAGE_ERRORS):
            logger.warning(
                'Edit target message no longer exists.',
                extra={
                    'user_id': user_id,
                    'chat_id': query.message.chat_id,
                    'action': action,
                    'handler_name': handler_name,
                    'error_type': type(exc).__name__,
                },
                exc_info=exc,
            )
            return None
        logger.error(
            'BadRequest while editing message.',
            extra={
                'user_id': user_id,
                'chat_id': query.message.chat_id,
                'action': action,
                'handler_name': handler_name,
                'error_type': type(exc).__name__,
            },
            exc_info=exc,
        )
        raise
    except (Forbidden, NetworkError, TelegramError) as exc:
        logger.error(
            'Telegram error while editing message.',
            extra={
                'user_id': user_id,
                'chat_id': query.message.chat_id,
                'action': action,
                'handler_name': handler_name,
                'error_type': type(exc).__name__,
            },
            exc_info=exc,
        )
        raise
