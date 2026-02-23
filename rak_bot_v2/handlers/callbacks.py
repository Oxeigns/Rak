"""Callback query handlers."""

from __future__ import annotations

from telegram import ChatPermissions, Update
from telegram.ext import ContextTypes

from rak_bot_v2.config.constants import CALLBACK_RATE_LIMIT_CLICKS, CALLBACK_RATE_LIMIT_WINDOW_SECONDS
from rak_bot_v2.config.settings import get_settings

settings = get_settings()
from rak_bot_v2.utils.helpers import callback_allowed, enforce_force_join, is_admin, safe_edit_message_text, safe_handler


@safe_handler
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
        return
    if query.data and query.data.startswith("mod:unmute:"):
        target = query.data.rsplit(":", 1)[-1]
        if target.isdigit():
            await _handle_unmute(update, context, int(target))
        return


async def _handle_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int) -> None:
    """Allow admins to unmute warned users from inline button."""
    query = update.callback_query
    if not query or not update.effective_chat:
        return
    if not await is_admin(update, context):
        await query.answer("sɪʀꜰ ᴀᴅᴍɪɴ ᴜɴᴍᴜᴛᴇ ᴋᴀʀ ꜱᴀᴋᴛᴇ ʜᴀɪɴ.", show_alert=True)
        return
    await context.bot.restrict_chat_member(
        update.effective_chat.id,
        target_user_id,
        permissions=ChatPermissions(can_send_messages=True, can_send_other_messages=True, can_add_web_page_previews=True, can_send_photos=True, can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True, can_send_polls=True, can_send_audios=True, can_send_documents=True),
    )
    await query.answer("✓ ᴜsᴇʀ ᴜɴᴍᴜᴛᴇᴅ")
