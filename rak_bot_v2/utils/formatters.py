"""UI formatting helpers."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


# ── Keyboards ──────────────────────────────────────────────────────────────

def panel_keyboard() -> InlineKeyboardMarkup:
    """Create admin control panel keyboard."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⏱ sᴇᴛ ᴅᴇʟᴀʏ", callback_data="cfg:delay:prompt")],
            [InlineKeyboardButton("◆ ᴠᴇʀɪғʏ ᴊᴏɪɴ", callback_data="verify:join")],
            [InlineKeyboardButton("📊 sᴛᴀᴛs", callback_data="cfg:stats")],
        ]
    )


def force_join_keyboard(link: str) -> InlineKeyboardMarkup:
    """Create force-join CTA keyboard."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("◆ ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ", url=str(link))],
            [InlineKeyboardButton("✓ ᴠᴇʀɪғʏ", callback_data="verify:join")],
        ]
    )


def add_to_group_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    """Create 'add to group' deep-link button."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✓ ᴀᴅᴅ ᴛᴏ ɢʀᴏᴜᴘ", url=f"https://t.me/{bot_username}?startgroup=true")]]
    )


def unmute_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Create admin-only unmute action button."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔊 ᴜɴᴍᴜᴛᴇ ᴜsᴇʀ", callback_data=f"mod:unmute:{user_id}")]]
    )


def warn_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Create admin-only warn-reset button."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🗑 ᴄʟᴇᴀʀ ᴡᴀʀɴɪɴɢs", callback_data=f"mod:clearwarn:{user_id}")]]
    )


def promo_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    """Create consistent promotion keyboard."""
    return add_to_group_keyboard(bot_username)


# ── Text Cards ─────────────────────────────────────────────────────────────

def styled_card(title: str, body: str) -> str:
    """Return aesthetic Hinglish text card."""
    return f"◆ <b>{title}</b>\n\n━━━━━━━━━━━━\n\n{body}"


def help_text() -> str:
    """Full help text for /help command."""
    return styled_card(
        "ᴀɪ ɢᴏᴠᴇʀɴᴏʀ ʜᴇʟᴘ",
        (
            "<b>👤 ᴜsᴇʀ ᴄᴏᴍᴍᴀɴᴅs</b>\n"
            "/start – ʙᴏᴛ sᴛᴀʀᴛ ᴋᴀʀᴏ\n"
            "/help  – ʏᴇʜ ᴍᴇɴᴜ ᴅᴇᴋʜᴏ\n\n"
            "<b>🛡 ᴀᴅᴍɪɴ ᴄᴏᴍᴍᴀɴᴅs</b>\n"
            "/panel      – ᴄᴏɴᴛʀᴏʟ ᴘᴀɴᴇʟ\n"
            "/setdelay &lt;sec&gt; – ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ ᴅᴇʟᴀʏ\n"
            "/warn       – ʀᴇᴘʟʏ ᴍᴇɪɴ ᴜsᴇ ᴋᴀʀᴏ → ᴡᴀʀɴ\n"
            "/unwarn     – ʀᴇᴘʟʏ ᴍᴇɪɴ → ᴡᴀʀɴ ʜᴀᴛᴀᴏ\n"
            "/mute       – ʀᴇᴘʟʏ ᴍᴇɪɴ → ᴍᴜᴛᴇ\n"
            "/unmute     – ʀᴇᴘʟʏ ᴍᴇɪɴ → ᴜɴᴍᴜᴛᴇ\n"
            "/kick       – ʀᴇᴘʟʏ ᴍᴇɪɴ → ᴋɪᴄᴋ\n"
            "/ban        – ʀᴇᴘʟʏ ᴍᴇɪɴ → ʙᴀɴ\n"
            "/unban      – ʀᴇᴘʟʏ ᴍᴇɪɴ → ᴜɴʙᴀɴ\n\n"
            "<b>👑 ᴏᴡɴᴇʀ ᴄᴏᴍᴍᴀɴᴅs</b>\n"
            "/stats        – ʙᴏᴛ sᴛᴀᴛs\n"
            "/broadcast    – sᴀʙ ɢʀᴏᴜᴘs ᴍᴇɪɴ ᴍᴇssᴀɢᴇ\n"
            "/reloadwords  – ᴡᴏʀᴅ ʟɪsᴛ ʀᴇʟᴏᴀᴅ"
        ),
    )
