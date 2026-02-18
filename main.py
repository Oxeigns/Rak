"""Compatibility entry point that runs the unified bot implementation."""

from __future__ import annotations

import asyncio

from bot import run_bot


if __name__ == "__main__":
    asyncio.run(run_bot())
