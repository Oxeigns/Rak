"""Entry point for AI Governor bot v2."""

from __future__ import annotations

from rak_bot_v2.core.bot import build_application


def main() -> None:
    """Run the Telegram polling loop."""
    app = build_application()
    app.run_polling(allowed_updates=["message", "edited_message", "callback_query", "chat_member"])


if __name__ == "__main__":
    main()
