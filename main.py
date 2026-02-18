"""Compatibility entry point that runs the unified bot implementation."""

from __future__ import annotations

import asyncio
import logging

from bot import run_bot

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)


if __name__ == "__main__":
    asyncio.run(run_bot())
