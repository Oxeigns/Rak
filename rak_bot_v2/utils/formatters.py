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
