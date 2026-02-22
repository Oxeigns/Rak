"""Self-promotion loop service."""

from __future__ import annotations

import asyncio
import logging

from telegram.ext import Application

from rak_bot_v2.config.constants import PROMO_INTERVAL_SECONDS, PROMO_MESSAGE_HINGLISH
from rak_bot_v2.services.storage import RuntimeStore

LOGGER = logging.getLogger(__name__)


class PromoService:
    """Sends periodic promotion messages to tracked chats."""

    def __init__(self, store: RuntimeStore) -> None:
        """Initialize promotion service.

        Args:
            store: Runtime storage dependency.
        """
        self.store = store
        self._task: asyncio.Task[None] | None = None

    async def start(self, application: Application) -> None:
        """Start background promotion loop."""
        self._task = asyncio.create_task(self._promo_loop(application))

    async def stop(self) -> None:
        """Stop background promotion loop gracefully."""
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            return

    async def _promo_loop(self, application: Application) -> None:
        """Sleep interval then send promotions forever."""
        while True:
            try:
                await asyncio.sleep(PROMO_INTERVAL_SECONDS)
                await self._send_promotions(application)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("promo_loop_error: %s", exc)
                await asyncio.sleep(3600)

    async def _send_promotions(self, application: Application) -> None:
        """Send promo message to every tracked chat."""
        for chat_id, _chat_type in await self.store.get_all_chats():
            try:
                await application.bot.send_message(chat_id, PROMO_MESSAGE_HINGLISH, parse_mode="HTML")
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("promo_failed chat=%s err=%s", chat_id, exc)
