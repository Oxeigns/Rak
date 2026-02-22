"""SQLite runtime storage service."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path


class RuntimeStore:
    """Stores warnings and group preferences in SQLite."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def initialize(self) -> None:
        """Initialize tables and WAL mode."""
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        Path(self._db_path).touch(exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS warnings (chat_id INTEGER, user_id INTEGER, count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(chat_id, user_id));"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS group_config (chat_id INTEGER PRIMARY KEY, delete_delay INTEGER NOT NULL DEFAULT 60);"
            )
            conn.commit()

    async def get_delete_delay(self, chat_id: int) -> int:
        """Get configured delete delay for group."""
        return await asyncio.to_thread(self._get_delete_delay_sync, chat_id)

    def _get_delete_delay_sync(self, chat_id: int) -> int:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute("SELECT delete_delay FROM group_config WHERE chat_id = ?", (chat_id,)).fetchone()
            return int(row[0]) if row else 60

    async def set_delete_delay(self, chat_id: int, seconds: int) -> None:
        """Set delete delay for group."""
        await asyncio.to_thread(self._set_delete_delay_sync, chat_id, seconds)

    def _set_delete_delay_sync(self, chat_id: int, seconds: int) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO group_config (chat_id, delete_delay) VALUES (?, ?) ON CONFLICT(chat_id) DO UPDATE SET delete_delay = excluded.delete_delay",
                (chat_id, seconds),
            )
            conn.commit()

    async def increment_warning(self, chat_id: int, user_id: int) -> int:
        """Increment warning count for a user."""
        return await asyncio.to_thread(self._increment_warning_sync, chat_id, user_id)

    def _increment_warning_sync(self, chat_id: int, user_id: int) -> int:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO warnings (chat_id, user_id, count) VALUES (?, ?, 1) ON CONFLICT(chat_id, user_id) DO UPDATE SET count = count + 1",
                (chat_id, user_id),
            )
            row = conn.execute("SELECT count FROM warnings WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)).fetchone()
            conn.commit()
            return int(row[0]) if row else 0

    async def reset_warning(self, chat_id: int, user_id: int) -> None:
        """Reset warning count for a user."""
        await asyncio.to_thread(self._reset_warning_sync, chat_id, user_id)

    def _reset_warning_sync(self, chat_id: int, user_id: int) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM warnings WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
            conn.commit()
