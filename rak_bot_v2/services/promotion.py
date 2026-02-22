"""Self-promotion loop service."""

from __future__ import annotations

import asyncio
import logging

from telegram.error import RetryAfter
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
        """Indestructible promotion loop."""
        await asyncio.sleep(60)
        while True:
            try:
                await self._send_promotions(application)
            except asyncio.CancelledError:
                LOGGER.info("promo_loop_cancelled")
                break
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("promo_send_failed: %s", exc)

            try:
                await asyncio.sleep(PROMO_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break

    async def _send_promotions(self, application: Application) -> None:
        """Send with per-chat resilience and flood-wait handling."""
        try:
            chats = await self.store.get_all_chats()
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("get_chats_failed: %s", exc)
            return

        for chat_id, _chat_type in chats:
            try:
                await application.bot.send_message(
                    chat_id,
                    PROMO_MESSAGE_HINGLISH,
                    parse_mode="HTML",
                    disable_notification=True,
                )
                LOGGER.debug("promo_sent chat=%s", chat_id)
                await asyncio.sleep(0.1)
            except RetryAfter as exc:
                LOGGER.warning("promo_flood_wait chat=%s retry=%s", chat_id, exc.retry_after)
                await asyncio.sleep(exc.retry_after)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("promo_failed chat=%s: %s", chat_id, exc)
