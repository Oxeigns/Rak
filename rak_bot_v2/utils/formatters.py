"""UI formatting helpers."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


# ── Keyboards ──────────────────────────────────────────────────────────────

def panel_keyboard() -> InlineKeyboardMarkup:
    """Create admin control panel keyboard."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("SET DELAY", callback_data="cfg:delay:prompt", style="primary")],
            [InlineKeyboardButton("VERIFY JOIN", callback_data="verify:join", style="success")],
            [InlineKeyboardButton("STATS", callback_data="cfg:stats", style="primary")],
        ]
    )


def force_join_keyboard(link: str) -> InlineKeyboardMarkup:
    """Create force-join CTA keyboard."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("JOIN CHANNEL", url=str(link), style="primary")],
            [InlineKeyboardButton("VERIFY", callback_data="verify:join", style="success")],
        ]
    )


def verify_keyboard() -> InlineKeyboardMarkup:
    """Create verify-only CTA keyboard."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("VERIFY", callback_data="verify:join", style="success")]]
    )


def add_to_group_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    """Create 'add to group' deep-link button."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(
            "ADD TO GROUP",
            url=f"https://t.me/{bot_username}?startgroup=true",
            style="primary",
        )]]
    )


def unmute_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Create admin-only unmute action button."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("UNMUTE USER", callback_data=f"mod:unmute:{user_id}", style="success")]]
    )


def warn_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Create admin-only warn-reset button."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("CLEAR WARNINGS", callback_data=f"mod:clearwarn:{user_id}", style="success")]]
    )


def moderation_actions_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """
    Create violation response keyboard.
    Shown when content is flagged - allows admin to choose action.
    """
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("DELETE + BAN", callback_data=f"mod:ban:{user_id}", style="danger")],
            [InlineKeyboardButton("DELETE + MUTE", callback_data=f"mod:mute:{user_id}", style="danger")],
            [InlineKeyboardButton("DELETE + WARN", callback_data=f"mod:warn:{user_id}")],
            [InlineKeyboardButton("DELETE ONLY", callback_data=f"mod:delete:{user_id}")],
            [InlineKeyboardButton("IGNORE", callback_data=f"mod:ignore:{user_id}", style="success")],
        ]
    )


def admin_commands_keyboard() -> InlineKeyboardMarkup:
    """
    Full admin control panel with sectioned colored buttons.
    Primary (Blue) | Success (Green) | Danger (Red)
    """
    return InlineKeyboardMarkup(
        [
            # Danger Zone - Destructive Actions
            [InlineKeyboardButton("BAN", callback_data="cmd:ban", style="danger")],
            [InlineKeyboardButton("KICK", callback_data="cmd:kick", style="danger")],
            [InlineKeyboardButton("MUTE", callback_data="cmd:mute", style="danger")],
            
            # Warning Zone - Caution Actions (Default Style)
            [InlineKeyboardButton("WARN", callback_data="cmd:warn")],
            
            # Success Zone - Restorative Actions
            [InlineKeyboardButton("UNMUTE", callback_data="cmd:unmute", style="success")],
            [InlineKeyboardButton("UNBAN", callback_data="cmd:unban", style="success")],
            [InlineKeyboardButton("CLEAR WARN", callback_data="cmd:clearwarn", style="success")],
            
            # Primary Zone - Navigation
            [InlineKeyboardButton("PANEL", callback_data="cmd:panel", style="primary")],
            [InlineKeyboardButton("STATS", callback_data="cmd:stats", style="primary")],
        ]
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
        "AI GOVERNOR HELP",
        (
            "<b>USER COMMANDS</b>\n"
            "<code>/start</code> – start bot\n"
            "<code>/help</code> – show this menu\n\n"
            "<b>ADMIN COMMANDS</b>\n"
            "<code>/panel</code> – control panel\n"
            "<code>/setdelay &lt;sec&gt;</code> – auto-delete delay\n"
            "<code>/warn</code> – reply to user → warn\n"
            "<code>/unwarn</code> – reply → remove warn\n"
            "<code>/mute</code> – reply → mute\n"
            "<code>/unmute</code> – reply → unmute\n"
            "<code>/kick</code> – reply → kick\n"
            "<code>/ban</code> – reply → ban\n"
            "<code>/unban</code> – reply → unban\n\n"
            "<b>OWNER COMMANDS</b>\n"
            "<code>/stats</code> – bot stats\n"
            "<code>/broadcast</code> – message all groups\n"
            "<code>/reloadwords</code> – reload word lists"
        ),
    )
