"""Callback query handlers."""

from __future__ import annotations

import logging

from telegram import ChatPermissions, Update
from telegram.error import BadRequest, Forbidden, RetryAfter
from telegram.ext import ContextTypes

from rak_bot_v2.config.constants import CALLBACK_RATE_LIMIT_CLICKS, CALLBACK_RATE_LIMIT_WINDOW_SECONDS
from rak_bot_v2.config.settings import get_settings
from rak_bot_v2.utils.formatters import force_join_keyboard, styled_card
from rak_bot_v2.utils.helpers import (
    callback_allowed,
    enforce_force_join,
    is_admin,
    safe_edit_message_text,
    safe_handler,
)

LOGGER = logging.getLogger(__name__)

# Full permissions object used during unmute
_FULL_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_audios=True,
    can_send_documents=True,
)


@safe_handler
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route all inline-button callbacks to the correct handler."""
    query = update.callback_query
    if not query or not update.effective_user:
        return

    # 1. Rate Limiting Check
    if not callback_allowed(
        update.effective_user.id,
        CALLBACK_RATE_LIMIT_CLICKS,
        CALLBACK_RATE_LIMIT_WINDOW_SECONDS,
    ):
        await query.answer("Rate limit exceeded. Please wait a moment.", show_alert=True)
        return

    await query.answer()
    data = query.data or ""

    # ── Force-join verify ──────────────────────────────────────────────────
    if data == "verify:join":
        settings = get_settings()
        ok = await enforce_force_join(update, context, settings.force_channel_id)
        msg = (
            "Verification successful! You can now use the bot."
            if ok
            else "Access Denied: You have not joined the channel yet."
        )
        if ok:
            await safe_edit_message_text(update, styled_card("VERIFICATION", msg))
        else:
            await safe_edit_message_text(
                update,
                styled_card("VERIFICATION", msg),
                reply_markup=force_join_keyboard(str(settings.force_channel_link)),
            )
        return

    # ── Config: Delete Delay ───────────────────────────────────────────────
    if data == "cfg:delay:prompt":
        if not await is_admin(update, context):
            await query.answer("Only administrators can modify settings.", show_alert=True)
            return
        await safe_edit_message_text(
            update,
            styled_card(
                "SET AUTO-DELETE",
                "To change the delay, use the command:\n\n<code>/setdelay [seconds]</code>\n\nExample: <code>/setdelay 60</code>",
            ),
        )
        return

    # ── Inline stats ───────────────────────────────────────────────────────
    if data == "cfg:stats":
        if not await is_admin(update, context):
            await query.answer("Only administrators can view statistics.", show_alert=True)
            return
        store = context.application.bot_data.get("store")
        cache = context.application.bot_data.get("cache")
        
        total_chats = len(await store.get_all_chats()) if store else 0
        total_warn = await store.get_total_warnings() if store else 0
        cached_texts = cache.cached_text_count if cache is not None else 0
        cached_imgs = cache.cached_image_count if cache is not None else 0
        
        text = styled_card(
            "SYSTEM STATISTICS",
            (
                f"Total Tracked Chats: {total_chats}\n"
                f"Cached Illegal Texts: {cached_texts}\n"
                f"Cached Illegal Images: {cached_imgs}\n"
                f"Global Warnings Issued: {total_warn}"
            ),
        )
        await safe_edit_message_text(update, text)
        return

    # ── Unmute Action ──────────────────────────────────────────────────────
    if data.startswith("mod:unmute:"):
        target = data.rsplit(":", 1)[-1]
        if target.isdigit():
            await _handle_unmute(update, context, int(target))
        return

    # ── Clear Warnings Action ──────────────────────────────────────────────
    if data.startswith("mod:clearwarn:"):
        target = data.rsplit(":", 1)[-1]
        if target.isdigit():
            await _handle_clear_warn(update, context, int(target))
        return


async def _handle_unmute(
    update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int
) -> None:
    """Allow admins to unmute a user via inline button."""
    query = update.callback_query
    if not query or not update.effective_chat:
        return
    
    if not await is_admin(update, context):
        await query.answer("Administrative privileges required.", show_alert=True)
        return
        
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, target_user_id, permissions=_FULL_PERMISSIONS
        )
        await query.answer("User unmuted successfully.")
        await safe_edit_message_text(
            update,
            styled_card("USER UNMUTED", f"User <code>{target_user_id}</code> is now permitted to speak."),
        )
    except (Forbidden, BadRequest, RetryAfter) as exc:
        LOGGER.warning("unmute_failed user=%s err=%s", target_user_id, exc)
        await query.answer("Failed to unmute user. Check bot permissions.", show_alert=True)


async def _handle_clear_warn(
    update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int
) -> None:
    """Allow admins to reset a user's warning count via inline button."""
    query = update.callback_query
    if not query or not update.effective_chat:
        return
    
    if not await is_admin(update, context):
        await query.answer("Administrative privileges required.", show_alert=True)
        return
        
    store = context.application.bot_data.get("store")
    if store:
        await store.reset_warning(update.effective_chat.id, target_user_id)
        
    await query.answer("Warning count reset.")
    await safe_edit_message_text(
        update,
        styled_card("WARNINGS CLEARED", f"All warnings for user <code>{target_user_id}</code> have been removed."),
    )
