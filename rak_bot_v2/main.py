"""Entry point for AI Governor bot v2."""

from __future__ import annotations

import logging
import signal
import sys

from rak_bot_v2.core.bot import build_application

LOGGER = logging.getLogger(__name__)


def main() -> int:
    """Run bot polling with graceful shutdown. Returns 0 on success, 1 on error."""
    try:
        app = build_application()

        def signal_handler(_sig, _frame):
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
        # BUG FIX: was silently returning 1; now logs the full traceback
        LOGGER.exception("fatal_startup_error")
        return 1


if __name__ == "__main__":
    sys.exit(main())
