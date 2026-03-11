"""Application constants for AI Governor bot."""

from __future__ import annotations

from enum import StrEnum

# ── AI Models ──────────────────────────────────────────────────────────────
TEXT_MODEL = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_MODEL_FALLBACKS = ("gemini-2.0-flash-lite", "gemini-1.5-flash")

# ── Cache & Rate Limits ────────────────────────────────────────────────────
CACHE_MAX_SIZE = 1000
CACHE_TTL_SECONDS = 3600
AI_RATE_LIMIT_PER_MINUTE = 100
CALLBACK_RATE_LIMIT_CLICKS = 5
CALLBACK_RATE_LIMIT_WINDOW_SECONDS = 10

# ── Auto-delete Delays ─────────────────────────────────────────────────────
DEFAULT_DELETE_DELAY_SECONDS = 60
EDIT_DELETE_DELAY_SECONDS = 300
WARNING_DELETE_DELAY_SECONDS = 60
MIN_DELETE_DELAY_SECONDS = 1
MAX_DELETE_DELAY_SECONDS = 86400

# ── Moderation Thresholds ──────────────────────────────────────────────────
MAX_WARNINGS = 50                        # warnings before auto-mute
IMAGE_VIOLATION_MUTE_THRESHOLD = 3       # image violations before mute
MUTE_SECONDS = 600                       # 10 min mute duration
BAN_SECONDS = 0                          # 0 = permanent ban

# ── Broadcasting ───────────────────────────────────────────────────────────
BROADCAST_DELAY_SECONDS = 0.05          # delay between each broadcast send
PROMO_INTERVAL_SECONDS = 86400          # 24 hours between promo messages
PROMO_MESSAGE_HINGLISH = (
    "◆ <b>ᴘᴏᴡᴇʀᴇᴅ ʙʏ AI ɢᴏᴠᴇʀɴᴏʀ</b>\n\n"
    "━━━━━━━━━━━━\n\n"
    "ʙᴇsᴛ ᴍᴏᴅᴇʀᴀᴛɪᴏɴ ʙᴏᴛ ғᴏʀ ᴛᴇʟᴇɢʀᴀᴍ ɢʀᴏᴜᴘs ✓"
)

# ── Suspicious Word Patterns (for join-name check) ─────────────────────────
SUSPICIOUS_WORDS = ("admin", "support", "official", "moderator", "helper", "bot")

# ── Supported group chat types (excludes private DMs) ─────────────────────
GROUP_CHAT_TYPES = ("group", "supergroup")

# ── Media MIME types that go through AI image pipeline ────────────────────
IMAGE_MIME_TYPES = frozenset({
    "image/jpeg", "image/png", "image/webp", "image/gif",
    "image/bmp", "image/tiff",
})


class ModerationAction(StrEnum):
    """Moderation actions returned by AI."""

    ALLOW = "allow"
    WARN = "warn"
    DELETE = "delete"
    BAN = "ban"
