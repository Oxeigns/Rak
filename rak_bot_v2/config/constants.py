"""Application constants for AI Governor bot."""

from __future__ import annotations

from enum import StrEnum

TEXT_MODEL = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-1.5-flash"

CACHE_MAX_SIZE = 1000
CACHE_TTL_SECONDS = 3600
AI_RATE_LIMIT_PER_MINUTE = 100
CALLBACK_RATE_LIMIT_CLICKS = 5
CALLBACK_RATE_LIMIT_WINDOW_SECONDS = 10

DEFAULT_DELETE_DELAY_SECONDS = 60
EDIT_DELETE_DELAY_SECONDS = 300
WARNING_DELETE_DELAY_SECONDS = 30
MIN_DELETE_DELAY_SECONDS = 1
MAX_DELETE_DELAY_SECONDS = 86400

MAX_WARNINGS = 3
IMAGE_VIOLATION_MUTE_THRESHOLD = 3
MUTE_SECONDS = 600
PROMO_INTERVAL_SECONDS = 86400
PROMO_MESSAGE_HINGLISH = "◆ <b>ᴘᴏᴡᴇʀᴇᴅ ʙʏ AI ɢᴏᴠᴇʀɴᴏʀ</b>\n\n━━━━━━━━━━━━\n\nʙᴇsᴛ ᴍᴏᴅᴇʀᴀᴛɪᴏɴ ʙᴏᴛ ғᴏʀ ᴛᴇʟᴇɢʀᴀᴍ ɢʀᴏᴜᴘs ✓"

SUSPICIOUS_WORDS = ("admin", "support", "official")


class ModerationAction(StrEnum):
    """Moderation actions returned by AI."""

    ALLOW = "allow"
    WARN = "warn"
    DELETE = "delete"
