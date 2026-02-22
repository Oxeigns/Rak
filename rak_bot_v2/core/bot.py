"""Telegram application setup."""

from __future__ import annotations

import logging

from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from rak_bot_v2.config.settings import settings
from rak_bot_v2.core.lifespan import on_shutdown, on_startup
from rak_bot_v2.handlers.callbacks import callback_router
from rak_bot_v2.handlers.commands import panel_command, set_delay_command, start_command
from rak_bot_v2.handlers.moderation import handle_edited, handle_message, handle_new_members


def configure_logging() -> None:
    """Configure structured logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s cid=%(message)s",
    )


def build_application() -> Application:
    """Create and configure Telegram application."""
    configure_logging()
    app = Application.builder().token(settings.bot_token).post_init(on_startup).post_shutdown(on_shutdown).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("panel", panel_command))
    app.add_handler(CommandHandler("setdelay", set_delay_command))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_members))
    app.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE, handle_edited))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND & ~filters.StatusUpdate.ALL, handle_message))
    return app
