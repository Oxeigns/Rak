"""UI formatting helpers."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def panel_keyboard() -> InlineKeyboardMarkup:
    """Create admin panel keyboard."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✓ sᴇᴛ ᴅᴇʟᴀʏ", callback_data="cfg:delay")],
            [InlineKeyboardButton("◆ ᴠᴇʀɪғʏ ᴊᴏɪɴ", callback_data="verify:join")],
        ]
    )


def force_join_keyboard(link: str) -> InlineKeyboardMarkup:
    """Create force-join CTA keyboard."""
    link_str = str(link)
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("◆ ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ", url=link_str)],
            [InlineKeyboardButton("✓ ᴠᴇʀɪғʏ", callback_data="verify:join")],
        ]
    )


def styled_card(title: str, body: str) -> str:
    """Return aesthetic Hinglish text card."""
    return f"◆ <b>{title}</b> ✓\n\n━━━━━━━━━━━━\n\n{body}"


def add_to_group_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    """Create add-to-group deep-link button using existing font style."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✓ ᴀᴅᴅ ᴛᴏ ɢʀᴏᴜᴘ", url=f"https://t.me/{bot_username}?startgroup=true")]]
    )


def unmute_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Create admin-only unmute action button."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✓ ᴜɴᴍᴜᴛᴇ ᴜsᴇʀ", callback_data=f"mod:unmute:{user_id}")]]
    )


def promo_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    """Create consistent promotion keyboard for DM/group posts."""
    return add_to_group_keyboard(bot_username)
