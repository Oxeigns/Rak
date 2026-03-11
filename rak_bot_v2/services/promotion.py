"""Self-promotion loop service."""

from __future__ import annotations

import asyncio
import logging

from telegram.error import Forbidden, BadRequest, RetryAfter
from telegram.ext import Application

from rak_bot_v2.config.constants import PROMO_INTERVAL_SECONDS, PROMO_MESSAGE_HINGLISH
from rak_bot_v2.services.storage import RuntimeStore
from rak_bot_v2.utils.formatters import promo_keyboard

LOGGER = logging.getLogger(__name__)


class PromoService:
    """Sends periodic promotion messages to tracked *group* chats only."""

    def __init__(self, store: RuntimeStore) -> None:
        self.store = store
        self._task: asyncio.Task[None] | None = None

    async def start(self, application: Application) -> None:
        """Start the background promotion loop."""
        self._task = asyncio.create_task(self._promo_loop(application))

    async def stop(self) -> None:
        """Cancel the background promotion loop gracefully."""
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    async def _promo_loop(self, application: Application) -> None:
        """Run promo sends on PROMO_INTERVAL_SECONDS cadence."""
        # Initial delay so bot is fully ready before first promo run
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
        """
        Send promo message to group/supergroup chats only.
        Handles flood-waits per chat and silently skips removed/blocked chats.
        """
        try:
            # BUG FIX: was get_all_chats() – now we only target groups so we
            # don't spam users in private DMs (Telegram ToS violation).
            chats = await self.store.get_group_chats()
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("get_group_chats_failed: %s", exc)
            return

        me = await application.bot.get_me()
        for chat_id, _chat_type in chats:
            try:
                await application.bot.send_message(
                    chat_id,
                    PROMO_MESSAGE_HINGLISH,
                    parse_mode="HTML",
                    disable_notification=True,
                    reply_markup=promo_keyboard(me.username),
                )
                LOGGER.debug("promo_sent chat=%s", chat_id)
                await asyncio.sleep(0.1)
            except RetryAfter as exc:
                LOGGER.warning("promo_flood_wait chat=%s retry=%s", chat_id, exc.retry_after)
                await asyncio.sleep(exc.retry_after)
            except (Forbidden, BadRequest) as exc:
                # Bot removed from group or chat not found – skip silently
                LOGGER.info("promo_skipped chat=%s reason=%s", chat_id, exc)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("promo_failed chat=%s: %s", chat_id, exc)
