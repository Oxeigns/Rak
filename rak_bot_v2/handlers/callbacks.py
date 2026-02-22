"""Callback query handlers."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from rak_bot_v2.config.constants import CALLBACK_RATE_LIMIT_CLICKS, CALLBACK_RATE_LIMIT_WINDOW_SECONDS
from rak_bot_v2.config.settings import settings
from rak_bot_v2.utils.helpers import callback_allowed, enforce_force_join, safe_edit_message_text


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route inline button callbacks."""
    query = update.callback_query
    if not query or not update.effective_user:
        return
    if not callback_allowed(update.effective_user.id, CALLBACK_RATE_LIMIT_CLICKS, CALLBACK_RATE_LIMIT_WINDOW_SECONDS):
        await query.answer("Slow down bhai, thoda wait karo.", show_alert=True)
        return
    await query.answer()
    if query.data == "verify:join":
        ok = await enforce_force_join(update, context, settings.force_channel_id)
        msg = "✓ ᴠᴇʀɪғɪᴇᴅ! ᴀʙ ᴄᴏᴍᴍᴀɴᴅ ᴜsᴇ ᴋᴀʀᴏ." if ok else "🚫 ᴀʙʜɪ ᴛᴀᴋ ᴊᴏɪɴ ɴᴀʜɪ ᴋɪʏᴀ."
        await safe_edit_message_text(update, msg, parse_mode="HTML")
