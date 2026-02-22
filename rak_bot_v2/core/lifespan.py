"""Startup and shutdown lifecycle hooks."""

from __future__ import annotations

import asyncio
import logging

from telegram.ext import Application

from rak_bot_v2.config.settings import settings
from rak_bot_v2.services.ai_moderation import AiModerationService
from rak_bot_v2.services.cache_manager import CacheManager
from rak_bot_v2.services.promotion import PromoService
from rak_bot_v2.services.storage import RuntimeStore

LOGGER = logging.getLogger(__name__)


async def _periodic_cache_cleanup(app: Application) -> None:
    """Run cache cleanup every hour."""
    while True:
        try:
            await asyncio.sleep(3600)
            cache = app.bot_data.get("cache")
            if cache:
                await cache.cleanup_old_cache()
        except asyncio.CancelledError:
            break
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("cache_cleanup_error: %s", exc)


async def on_startup(app: Application) -> None:
    """Initialize services and attach to bot_data."""
    store = RuntimeStore(settings.database_path)
    await store.initialize()
    cache = CacheManager()
    await cache.initialize()
    ai = AiModerationService(settings.groq_api_key, settings.gemini_api_key)
    promo = PromoService(store)
    await promo.start(app)
    cleanup_task = app.create_task(_periodic_cache_cleanup(app))
    app.bot_data.update({"store": store, "ai": ai, "cache": cache, "promo": promo, "settings": settings, "cache_cleanup_task": cleanup_task})
    LOGGER.info("startup_complete")


async def on_shutdown(app: Application) -> None:
    """Close async resources gracefully."""
    ai: AiModerationService | None = app.bot_data.get("ai")
    promo: PromoService | None = app.bot_data.get("promo")
    cleanup_task = app.bot_data.get("cache_cleanup_task")
    if cleanup_task:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
    if ai:
        await ai.close()
    if promo:
        await promo.stop()
    LOGGER.info("shutdown_complete")
