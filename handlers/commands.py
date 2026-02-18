from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError
from telegram.ext import ContextTypes

from core.security import CallbackSigner
from utils.safe_telegram import safe_send_message


class CommandHandlers:
    def __init__(self, signer: CallbackSigner) -> None:
        self.signer = signer

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.effective_chat:
            return

        user = update.effective_user

        callback_data = self.signer.sign(user.id, 'open_panel')
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton('Open Panel', callback_data=callback_data)]])

        await safe_send_message(
            context,
            chat_id=update.effective_chat.id,
            text='Bot is online. Use the secure panel button below.',
            action='cmd_start',
            user_id=user.id,
            handler_name='CommandHandlers.start',
            reply_markup=keyboard,
        )

    async def panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat or not update.effective_user:
            return

        chat = update.effective_chat
        user = update.effective_user

        if chat.type == ChatType.PRIVATE:
            await safe_send_message(
                context,
                chat_id=chat.id,
                text='Use /panel in a group where you are admin.',
                action='cmd_panel_private',
                user_id=user.id,
                handler_name='CommandHandlers.panel',
            )
            return

        try:
            member = await context.bot.get_chat_member(chat.id, user.id)
        except RetryAfter:
            await safe_send_message(
                context,
                chat_id=chat.id,
                text='Telegram is rate-limiting admin checks. Retry in a moment.',
                action='cmd_panel_retry_after',
                user_id=user.id,
                handler_name='CommandHandlers.panel',
            )
            return
        except (BadRequest, Forbidden, NetworkError, TelegramError):
            await safe_send_message(
                context,
                chat_id=chat.id,
                text='Could not validate your admin permissions. Please retry.',
                action='cmd_panel_member_lookup_failed',
                user_id=user.id,
                handler_name='CommandHandlers.panel',
            )
            return

        if member.status not in ('administrator', 'creator'):
            await safe_send_message(
                context,
                chat_id=chat.id,
                text='Admin only command.',
                action='cmd_panel_denied',
                user_id=user.id,
                handler_name='CommandHandlers.panel',
            )
            return

        await safe_send_message(
            context,
            chat_id=chat.id,
            text='Panel loaded. Use /start in private for secure controls.',
            action='cmd_panel',
            user_id=user.id,
            handler_name='CommandHandlers.panel',
        )
