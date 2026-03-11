"""SQLite runtime storage service."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path


class RuntimeStore:
    """Stores warnings and group preferences in SQLite."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = asyncio.Lock()

    # ── Init ───────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Initialize tables and enable WAL mode."""
        async with self._lock:
            await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self._db_path).touch(exist_ok=True)
        with sqlite3.connect(self._db_path, timeout=30.0) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=30000;")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS warnings (
                    chat_id INTEGER,
                    user_id INTEGER,
                    count   INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (chat_id, user_id)
                );"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS group_config (
                    chat_id      INTEGER PRIMARY KEY,
                    delete_delay INTEGER NOT NULL DEFAULT 60
                );"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS tracked_chats (
                    chat_id    INTEGER PRIMARY KEY,
                    chat_type  TEXT    NOT NULL,
                    first_seen INTEGER NOT NULL
                );"""
            )
            conn.commit()

    # ── Retry Helper ───────────────────────────────────────────────────────

    @staticmethod
    def _execute_with_retry(func, *args, max_retries: int = 3):
        """Execute DB operation with retries on SQLite lock contention.
        NOTE: This runs inside asyncio.to_thread so time.sleep() is safe.
        """
        for attempt in range(max_retries):
            try:
                return func(*args)
            except sqlite3.OperationalError as exc:
                if "database is locked" in str(exc).lower() and attempt < max_retries - 1:
                    time.sleep(0.1 * (attempt + 1))
                    continue
                raise

    # ── Delete Delay ───────────────────────────────────────────────────────

    async def get_delete_delay(self, chat_id: int) -> int:
        async with self._lock:
            return await asyncio.to_thread(
                self._execute_with_retry, self._get_delete_delay_sync, chat_id
            )

    def _get_delete_delay_sync(self, chat_id: int) -> int:
        with sqlite3.connect(self._db_path, timeout=30.0) as conn:
            row = conn.execute(
                "SELECT delete_delay FROM group_config WHERE chat_id = ?", (chat_id,)
            ).fetchone()
            return int(row[0]) if row else 60

    async def set_delete_delay(self, chat_id: int, seconds: int) -> None:
        async with self._lock:
            await asyncio.to_thread(
                self._execute_with_retry, self._set_delete_delay_sync, chat_id, seconds
            )

    def _set_delete_delay_sync(self, chat_id: int, seconds: int) -> None:
        with sqlite3.connect(self._db_path, timeout=30.0) as conn:
            conn.execute(
                """INSERT INTO group_config (chat_id, delete_delay) VALUES (?, ?)
                   ON CONFLICT(chat_id) DO UPDATE SET delete_delay = excluded.delete_delay""",
                (chat_id, seconds),
            )
            conn.commit()

    # ── Warnings ───────────────────────────────────────────────────────────

    async def increment_warning(self, chat_id: int, user_id: int) -> int:
        """Increment warning count. Returns new total."""
        async with self._lock:
            return await asyncio.to_thread(
                self._execute_with_retry, self._increment_warning_sync, chat_id, user_id
            )

    def _increment_warning_sync(self, chat_id: int, user_id: int) -> int:
        with sqlite3.connect(self._db_path, timeout=30.0) as conn:
            conn.execute(
                """INSERT INTO warnings (chat_id, user_id, count) VALUES (?, ?, 1)
                   ON CONFLICT(chat_id, user_id) DO UPDATE SET count = count + 1""",
                (chat_id, user_id),
            )
            row = conn.execute(
                "SELECT count FROM warnings WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            ).fetchone()
            conn.commit()
            return int(row[0]) if row else 0

    async def get_user_warnings(self, chat_id: int, user_id: int) -> int:
        """Return current warning count for a specific user in a chat."""
        async with self._lock:
            return await asyncio.to_thread(
                self._execute_with_retry, self._get_user_warnings_sync, chat_id, user_id
            )

    def _get_user_warnings_sync(self, chat_id: int, user_id: int) -> int:
        with sqlite3.connect(self._db_path, timeout=30.0) as conn:
            row = conn.execute(
                "SELECT count FROM warnings WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            ).fetchone()
            return int(row[0]) if row else 0

    async def reset_warning(self, chat_id: int, user_id: int) -> None:
        """Reset (delete) all warnings for a user in a chat."""
        async with self._lock:
            await asyncio.to_thread(
                self._execute_with_retry, self._reset_warning_sync, chat_id, user_id
            )

    def _reset_warning_sync(self, chat_id: int, user_id: int) -> None:
        with sqlite3.connect(self._db_path, timeout=30.0) as conn:
            conn.execute(
                "DELETE FROM warnings WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)
            )
            conn.commit()

    async def get_total_warnings(self) -> int:
        """Return total accumulated warning count across all chats."""
        async with self._lock:
            return await asyncio.to_thread(
                self._execute_with_retry, self._get_total_warnings_sync
            )

    def _get_total_warnings_sync(self) -> int:
        with sqlite3.connect(self._db_path, timeout=30.0) as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(count), 0) FROM warnings"
            ).fetchone()
            return int(row[0]) if row else 0

    # ── Chat Tracking ──────────────────────────────────────────────────────

    async def track_chat(self, chat_id: int, chat_type: str) -> None:
        """Track chat metadata (idempotent – IGNORE on conflict)."""
        async with self._lock:
            await asyncio.to_thread(
                self._execute_with_retry, self._track_chat_sync, chat_id, chat_type
            )

    def _track_chat_sync(self, chat_id: int, chat_type: str) -> None:
        with sqlite3.connect(self._db_path, timeout=30.0) as conn:
            conn.execute(
                """INSERT OR IGNORE INTO tracked_chats (chat_id, chat_type, first_seen)
                   VALUES (?, ?, ?)""",
                (chat_id, chat_type, int(time.time())),
            )
            conn.commit()

    async def get_all_chats(self) -> list[tuple[int, str]]:
        """Return list of (chat_id, chat_type) for all tracked chats."""
        async with self._lock:
            return await asyncio.to_thread(
                self._execute_with_retry, self._get_all_chats_sync
            )

    def _get_all_chats_sync(self) -> list[tuple[int, str]]:
        with sqlite3.connect(self._db_path, timeout=30.0) as conn:
            rows = conn.execute(
                "SELECT chat_id, chat_type FROM tracked_chats"
            ).fetchall()
            return [(int(row[0]), str(row[1])) for row in rows]

    async def get_group_chats(self) -> list[tuple[int, str]]:
        """Return only group/supergroup chats (excludes private DMs)."""
        async with self._lock:
            return await asyncio.to_thread(
                self._execute_with_retry, self._get_group_chats_sync
            )

    def _get_group_chats_sync(self) -> list[tuple[int, str]]:
        with sqlite3.connect(self._db_path, timeout=30.0) as conn:
            rows = conn.execute(
                "SELECT chat_id, chat_type FROM tracked_chats WHERE chat_type IN ('group', 'supergroup')"
            ).fetchall()
            return [(int(row[0]), str(row[1])) for row in rows]
