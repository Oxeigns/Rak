from __future__ import annotations

import asyncio
import logging
import os

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
from core.logging import setup_logging
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
        self.signer = CallbackSigner(
            secret=self.config.CALLBACK_SECRET,
            ttl_seconds=self.config.CALLBACK_TTL_SECONDS,
            allowed_actions=set(self.config.CALLBACK_ALLOWED_ACTIONS),
        )
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
    app.bot_data['force_join_channel_id'] = container.config.FORCE_JOIN_CHANNEL_ID

    app.add_handler(TypeHandler(Update, container.middleware), group=-1)
    app.add_handler(CommandHandler('start', container.commands.start))
    app.add_handler(CommandHandler('panel', container.commands.panel))
    app.add_handler(CommandHandler('report', container.moderation.report))

    app.add_handler(CallbackQueryHandler(container.callbacks.handle_force_join_verify, pattern=r'^force_join:verify$'))
    app.add_handler(CallbackQueryHandler(container.callbacks.secure_callback, pattern=r'^secure_panel$'))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, container.moderation.moderate_text))
    app.add_error_handler(global_error_handler)
    return app


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id if isinstance(update, Update) and update.effective_user else None
    chat_id = update.effective_chat.id if isinstance(update, Update) and update.effective_chat else None

    err = context.error
    base = {'user_id': user_id, 'chat_id': chat_id, 'action': 'handler_error', 'handler_name': 'global_error_handler', 'error_type': type(err).__name__ if err else 'Unknown'}
    if isinstance(err, RetryAfter):
        logger.warning('RetryAfter in handler.', extra=base, exc_info=err)
    elif isinstance(err, (BadRequest, Forbidden, NetworkError, TelegramError)):
        logger.error('Telegram handler failure.', extra=base, exc_info=err)
    else:
        logger.exception('Unexpected non-telegram failure.', extra=base)


async def run() -> None:
    try:
        container = BotContainer()
    except ConfigError as exc:
        setup_logging('INFO')
        logging.getLogger(__name__).critical(
            'Configuration validation failed. Bot will not start.',
            extra={'action': 'startup_config', 'handler_name': 'run', 'error_type': type(exc).__name__},
            exc_info=exc,
        )
        raise

    setup_logging(container.config.LOG_LEVEL)
    logger.info(
        'Startup configuration validated.',
        extra={'action': 'startup_config_report', 'handler_name': 'run', **container.config.startup_report()},
    )
    app = build_application(container)
    port = int(os.getenv('PORT', '8443'))

    await app.initialize()
    try:
        await asyncio.wait_for(validate_startup_permissions(app.bot, container.config), timeout=20)
    except asyncio.TimeoutError as exc:
        logger.critical(
            'Startup permission validation timed out. Bot is stopping.',
            extra={'action': 'startup_validate', 'handler_name': 'run', 'error_type': type(exc).__name__},
            exc_info=exc,
        )
        await app.shutdown()
        raise
    except (ConfigError, PermissionValidationError) as exc:
        logger.critical(
            'Startup permission validation failed. Bot is stopping.',
            extra={'action': 'startup_validate', 'handler_name': 'run', 'error_type': type(exc).__name__},
            exc_info=exc,
        )
        await app.shutdown()
        raise

    if container.config.WEBHOOK_URL:
        await app.bot.set_webhook(
            url=container.config.WEBHOOK_URL,
            secret_token=container.config.WEBHOOK_SECRET or None,
            drop_pending_updates=True,
        )
        logger.info(
            'Webhook mode active.',
            extra={
                'action': 'startup',
                'handler_name': 'run',
                'webhook_url': container.config.WEBHOOK_URL,
                'webhook_port': port,
            },
        )
        await app.start()
        await app.updater.start_webhook(
            listen='0.0.0.0',
            port=port,
            webhook_url=container.config.WEBHOOK_URL,
            secret_token=container.config.WEBHOOK_SECRET or None,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        await asyncio.Event().wait()
    else:
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info('Polling mode active.', extra={'action': 'startup', 'handler_name': 'run'})
        await asyncio.Event().wait()


if __name__ == '__main__':
    asyncio.run(run())
