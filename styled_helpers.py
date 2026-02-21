"""Premium Times New Roman styling helpers for Telegram HTML responses."""

from __future__ import annotations

from html import escape

__all__ = [
    "font_times",
    "styled_card",
    "styled_alert",
    "styled_success",
    "styled_error",
    "styled_info",
    "styled_violation_card",
    "styled_mute_card",
    "styled_bot_welcome",
    "styled_panel_title",
]


def font_times(text: str) -> str:
    """Wrap text in Times New Roman HTML font tag."""
    return f'<font face="Times New Roman">{text}</font>'


def styled_card(title: str, body: str) -> str:
    """Render a bordered card with title/body sections."""
    card = (
        "╔════════════════════════════╗\n"
        f"║ <b>{escape(title)}</b>\n"
        "╠════════════════════════════╣\n"
        f"║ {body}\n"
        "╚════════════════════════════╝"
    )
    return font_times(card)


def styled_alert(title: str, body: str) -> str:
    return styled_card(f"⚠️ {title}", body)


def styled_success(title: str, body: str) -> str:
    return styled_card(f"✅ {title}", body)


def styled_error(title: str, body: str) -> str:
    return styled_card(f"❌ {title}", body)


def styled_info(title: str, body: str) -> str:
    return styled_card(f"ℹ️ {title}", body)


def styled_violation_card(
    user_mention: str,
    reason: str,
    warning_count: int,
    max_warnings: int,
    action_taken: str,
    *,
    is_bot_user: bool = False,
) -> str:
    """Render a violation card with structured moderation details."""
    bot_tag = "<b>[BOT MESSAGE]</b> " if is_bot_user else ""
    body = (
        f"{bot_tag}👤 User: {user_mention}\n"
        f"🚫 Reason: {escape(reason)}\n"
        f"🧾 Warnings: {warning_count}/{max_warnings}\n"
        f"⚙️ Action: {escape(action_taken)}"
    )
    return styled_alert("Content Violation", body)


def styled_mute_card(user_mention: str, reason: str, mute_hours: int, warning_count: int) -> str:
    body = (
        f"👤 User: {user_mention}\n"
        f"🔇 Duration: {mute_hours} hour(s)\n"
        f"🚫 Reason: {escape(reason)}\n"
        f"🧾 Warnings: {warning_count}"
    )
    return styled_alert("User Muted", body)


def styled_bot_welcome(bot_name: str) -> str:
    return styled_success(
        f"Welcome to {bot_name}",
        "Enterprise-grade AI moderation is active with premium UI styling.",
    )


def styled_panel_title(title: str) -> str:
    return font_times(f"<b>╔═ {escape(title)} ═╗</b>")
