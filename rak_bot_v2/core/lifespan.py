"""Startup and shutdown lifecycle hooks."""

from __future__ import annotations

import logging

from telegram.ext import Application

from rak_bot_v2.config.settings import settings
from rak_bot_v2.services.ai_moderation import AiModerationService
from rak_bot_v2.services.cache_manager import CacheManager
from rak_bot_v2.services.promotion import PromoService
from rak_bot_v2.services.storage import RuntimeStore

LOGGER = logging.getLogger(__name__)


async def on_startup(app: Application) -> None:
    """Initialize services and attach to bot_data."""
    store = RuntimeStore(settings.database_path)
    await store.initialize()
    cache = CacheManager()
    await cache.initialize()
    ai = AiModerationService(settings.groq_api_key, settings.gemini_api_key)
    promo = PromoService(store)
    await promo.start(app)
    app.bot_data.update({"store": store, "ai": ai, "cache": cache, "promo": promo, "settings": settings})
    LOGGER.info("startup_complete")


async def on_shutdown(app: Application) -> None:
    """Close async resources gracefully."""
    ai: AiModerationService | None = app.bot_data.get("ai")
    promo: PromoService | None = app.bot_data.get("promo")
    if ai:
        await ai.close()
    if promo:
        await promo.stop()
    LOGGER.info("shutdown_complete")
