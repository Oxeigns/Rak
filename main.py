from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

from core.config import ConfigError, get_config
from core.logging_setup import setup_logging
from core.middleware import ForceJoinMiddleware
from core.permissions import PermissionValidationError, validate_startup_permissions
from core.security import CallbackSigner, CooldownManager, UserRateLimiter
from handlers.callbacks import CallbackHandlers
from handlers.commands import CommandHandlers
from handlers.moderation import ModerationHandlers

logger = logging.getLogger(__name__)


class BotContainer:
    def __init__(self) -> None:
        self.config = get_config()
        self.signer = CallbackSigner(secret=self.config.CALLBACK_SECRET, ttl_seconds=self.config.CALLBACK_TTL_SECONDS)
        self.rate_limiter = UserRateLimiter(
            window_seconds=self.config.SPAM_WINDOW_SECONDS,
            max_requests=self.config.SPAM_MAX_REQUESTS,
        )
        self.cooldown = CooldownManager(self.config.COOLDOWN_SECONDS)

        self.commands = CommandHandlers(self.signer)
        self.callbacks = CallbackHandlers(self.signer)
        self.moderation = ModerationHandlers()
        self.middleware = ForceJoinMiddleware(self.config, self.rate_limiter, self.cooldown)


def build_application(container: BotContainer) -> Application:
    app = ApplicationBuilder().token(container.config.BOT_TOKEN).build()

    app.add_handler(TypeHandler(Update, container.middleware), group=-1)
    app.add_handler(CommandHandler('start', container.commands.start))
    app.add_handler(CommandHandler('panel', container.commands.panel))
    app.add_handler(CommandHandler('report', container.moderation.report))

    app.add_handler(CallbackQueryHandler(container.callbacks.handle_force_join_verify, pattern=r'^force_join:verify$'))
    app.add_handler(CallbackQueryHandler(container.callbacks.secure_callback, pattern=r'^v1\|'))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, container.moderation.moderate_text))
    app.add_error_handler(global_error_handler)
    return app


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id if isinstance(update, Update) and update.effective_user else None
    chat_id = update.effective_chat.id if isinstance(update, Update) and update.effective_chat else None

    err = context.error
    if isinstance(err, RetryAfter):
        logger.warning('RetryAfter in handler.', extra={'user_id': user_id, 'chat_id': chat_id, 'action': 'handler_error', 'error_type': type(err).__name__})
    elif isinstance(err, (BadRequest, Forbidden, NetworkError, TelegramError)):
        logger.error('Telegram handler failure.', exc_info=err, extra={'user_id': user_id, 'chat_id': chat_id, 'action': 'handler_error', 'error_type': type(err).__name__})
    else:
        logger.exception('Unexpected non-telegram failure.', extra={'user_id': user_id, 'chat_id': chat_id, 'action': 'handler_error', 'error_type': type(err).__name__ if err else 'Unknown'})


async def run() -> None:
    container = BotContainer()
    setup_logging(container.config.LOG_LEVEL)
    app = build_application(container)

    await app.initialize()
    try:
        await validate_startup_permissions(app.bot, container.config)
    except (ConfigError, PermissionValidationError):
        logger.critical('Startup validation failed. Bot is stopping.', exc_info=True, extra={'action': 'startup_validate'})
        await app.shutdown()
        raise

    if container.config.WEBHOOK_URL:
        await app.bot.set_webhook(url=container.config.WEBHOOK_URL, secret_token=container.config.WEBHOOK_SECRET or None)
        await app.start()
        logger.info('Webhook mode active.', extra={'action': 'startup'})
        await asyncio.Event().wait()
    else:
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info('Polling mode active.', extra={'action': 'startup'})
        await asyncio.Event().wait()


if __name__ == '__main__':
    asyncio.run(run())
