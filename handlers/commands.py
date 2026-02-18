from __future__ import annotations

import secrets

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from core.middleware import safe_send_message
from core.security import CallbackSigner


class CommandHandlers:
    def __init__(self, signer: CallbackSigner) -> None:
        self.signer = signer

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.effective_chat:
            return

        user = update.effective_user
        deep_link_payload = context.args[0] if context.args else None
        if deep_link_payload:
            # Deep links are acknowledged but still processed under strict middleware.
            pass

        nonce = secrets.token_hex(4)
        callback_data = self.signer.sign(user.id, 'open_panel', nonce)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton('Open Panel', callback_data=callback_data)]])

        await safe_send_message(
            context,
            chat_id=update.effective_chat.id,
            text='Bot is online. Use the secure panel button below.',
            action='cmd_start',
            user_id=user.id,
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
            )
            return

        member = await context.bot.get_chat_member(chat.id, user.id)
        if member.status not in ('administrator', 'creator'):
            await safe_send_message(
                context,
                chat_id=chat.id,
                text='Admin only command.',
                action='cmd_panel_denied',
                user_id=user.id,
            )
            return

        await safe_send_message(
            context,
            chat_id=chat.id,
            text='Panel loaded. Use /start in private for secure controls.',
            action='cmd_panel',
            user_id=user.id,
        )
