"""Telegram application setup."""

from __future__ import annotations

import logging

from telegram.error import NetworkError, TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from rak_bot_v2.config.settings import get_settings
from rak_bot_v2.core.lifespan import on_shutdown, on_startup
from rak_bot_v2.handlers.callbacks import callback_router
from rak_bot_v2.handlers.commands import (
    ban_command,
    broadcast_command,
    help_command,
    kick_command,
    mute_command,
    panel_command,
    reload_words_command,
    set_delay_command,
    start_command,
    stats_command,
    unban_command,
    unmute_command,
    unwarn_command,
    warn_command,
)
from rak_bot_v2.handlers.moderation import handle_edited, handle_message, handle_new_members


LOGGER = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log unhandled exceptions so polling keeps running."""
    LOGGER.error("unhandled_exception: %s", context.error, exc_info=context.error)

    if isinstance(context.error, (NetworkError, TelegramError)):
        LOGGER.warning("telegram_api_error: %s", context.error)
        return

    # Notify owner of unexpected errors
    try:
        settings = get_settings()
        error_msg = (
            f"🚨 <b>Bot Error</b>\n\n"
            f"<code>{type(context.error).__name__}: {str(context.error)[:300]}</code>"
        )
        await context.bot.send_message(settings.owner_id, error_msg, parse_mode="HTML")
    except Exception:  # noqa: BLE001
        pass


def configure_logging() -> None:
    """Configure structured logging to stdout."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # Reduce noise from httpx / telegram internals
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext.Application").setLevel(logging.WARNING)


def build_application() -> Application:
    """Create and configure the Telegram application with all handlers."""
    configure_logging()
    settings = get_settings()

    app = (
        Application.builder()
        .token(settings.bot_token)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    # ── Info commands ──────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("panel", panel_command))

    # ── Config commands ────────────────────────────────────────────────────
    app.add_handler(CommandHandler("setdelay", set_delay_command))

    # ── Moderation commands (admin) ────────────────────────────────────────
    app.add_handler(CommandHandler("warn", warn_command))
    app.add_handler(CommandHandler("unwarn", unwarn_command))
    app.add_handler(CommandHandler("mute", mute_command))
    app.add_handler(CommandHandler("unmute", unmute_command))
    app.add_handler(CommandHandler("kick", kick_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))

    # ── Owner-only commands ────────────────────────────────────────────────
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("reloadwords", reload_words_command))

    # ── Callbacks ──────────────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(callback_router))

    # ── Message handlers (order matters) ──────────────────────────────────
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_members))
    app.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE, handle_edited))
    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND & ~filters.StatusUpdate.ALL,
            handle_message,
        )
    )

    app.add_error_handler(error_handler)
    return app
