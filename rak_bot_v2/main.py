"""Entry point for AI Governor bot v2."""

from __future__ import annotations

import signal
import time

from rak_bot_v2.core.bot import build_application


class BotHealthMonitor:
    """Simple runtime health monitor counters."""

    def __init__(self) -> None:
        self.last_activity = time.time()
        self.message_count = 0
        self.error_count = 0

    def record_activity(self) -> None:
        self.last_activity = time.time()
        self.message_count += 1

    def record_error(self) -> None:
        self.error_count += 1

    def is_healthy(self) -> bool:
        return (time.time() - self.last_activity) < 600


health = BotHealthMonitor()


def main() -> int:
    """Run bot polling with basic monitoring and graceful shutdown hooks."""
    try:
        app = build_application()

        def signal_handler(sig, frame):  # noqa: ANN001, ARG001
            app.stop_running()

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        app.run_polling(
            allowed_updates=["message", "edited_message", "callback_query", "chat_member"],
            drop_pending_updates=True,
            read_timeout=30,
            write_timeout=30,
            connect_timeout=30,
            pool_timeout=30,
        )
        return 0
    except Exception:
        health.record_error()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
