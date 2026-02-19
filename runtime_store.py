from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Optional


class RuntimeStore:
    """Small persistent async-safe store for moderation runtime state."""

    def __init__(self, db_path: str = "runtime_state.db") -> None:
        self.db_path = Path(db_path)
        self._lock = asyncio.Lock()

    async def init(self) -> None:
        await asyncio.to_thread(self._init_sync)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_sync(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS warnings (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    warning_message_id INTEGER,
                    PRIMARY KEY (chat_id, user_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS promotion_state (
                    chat_id INTEGER PRIMARY KEY,
                    chat_type TEXT NOT NULL,
                    last_sent_ts INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS flagged_users (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    PRIMARY KEY (chat_id, user_id)
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    async def upsert_chat(self, chat_id: int, chat_type: str) -> None:
        async with self._lock:
            await asyncio.to_thread(self._upsert_chat_sync, chat_id, chat_type)

    def _upsert_chat_sync(self, chat_id: int, chat_type: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO promotion_state(chat_id, chat_type, last_sent_ts)
                VALUES (?, ?, 0)
                ON CONFLICT(chat_id) DO UPDATE SET chat_type=excluded.chat_type
                """,
                (chat_id, chat_type),
            )
            conn.commit()
        finally:
            conn.close()

    async def get_due_chats(self, now_ts: int, group_interval_h: int, dm_interval_h: int) -> list[tuple[int, str]]:
        async with self._lock:
            return await asyncio.to_thread(self._get_due_chats_sync, now_ts, group_interval_h, dm_interval_h)

    def _get_due_chats_sync(self, now_ts: int, group_interval_h: int, dm_interval_h: int) -> list[tuple[int, str]]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT chat_id, chat_type, last_sent_ts FROM promotion_state").fetchall()
            due: list[tuple[int, str]] = []
            for row in rows:
                interval = group_interval_h * 3600 if row["chat_type"] in {"group", "supergroup"} else dm_interval_h * 3600
                if now_ts - int(row["last_sent_ts"]) >= interval:
                    due.append((int(row["chat_id"]), str(row["chat_type"])))
            return due
        finally:
            conn.close()

    async def set_last_sent(self, chat_id: int, ts: int) -> None:
        async with self._lock:
            await asyncio.to_thread(self._set_last_sent_sync, chat_id, ts)

    def _set_last_sent_sync(self, chat_id: int, ts: int) -> None:
        conn = self._connect()
        try:
            conn.execute("UPDATE promotion_state SET last_sent_ts=? WHERE chat_id=?", (ts, chat_id))
            conn.commit()
        finally:
            conn.close()

    async def increment_warning(self, chat_id: int, user_id: int) -> int:
        async with self._lock:
            return await asyncio.to_thread(self._increment_warning_sync, chat_id, user_id)

    def _increment_warning_sync(self, chat_id: int, user_id: int) -> int:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO warnings(chat_id, user_id, count)
                VALUES(?, ?, 1)
                ON CONFLICT(chat_id, user_id)
                DO UPDATE SET count=count+1
                """,
                (chat_id, user_id),
            )
            row = conn.execute("SELECT count FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
            conn.commit()
            return int(row["count"]) if row else 1
        finally:
            conn.close()

    async def reset_warning(self, chat_id: int, user_id: int) -> None:
        async with self._lock:
            await asyncio.to_thread(self._reset_warning_sync, chat_id, user_id)

    def _reset_warning_sync(self, chat_id: int, user_id: int) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO warnings(chat_id, user_id, count)
                VALUES(?, ?, 0)
                ON CONFLICT(chat_id, user_id)
                DO UPDATE SET count=0
                """,
                (chat_id, user_id),
            )
            conn.commit()
        finally:
            conn.close()

    async def get_warning_message_id(self, chat_id: int, user_id: int) -> Optional[int]:
        async with self._lock:
            return await asyncio.to_thread(self._get_warning_message_id_sync, chat_id, user_id)

    def _get_warning_message_id_sync(self, chat_id: int, user_id: int) -> Optional[int]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT warning_message_id FROM warnings WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
            if not row:
                return None
            value = row["warning_message_id"]
            return int(value) if value is not None else None
        finally:
            conn.close()

    async def set_warning_message_id(self, chat_id: int, user_id: int, message_id: int) -> None:
        async with self._lock:
            await asyncio.to_thread(self._set_warning_message_id_sync, chat_id, user_id, message_id)

    def _set_warning_message_id_sync(self, chat_id: int, user_id: int, message_id: int) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO warnings(chat_id, user_id, count, warning_message_id)
                VALUES(?, ?, 0, ?)
                ON CONFLICT(chat_id, user_id)
                DO UPDATE SET warning_message_id=excluded.warning_message_id
                """,
                (chat_id, user_id, message_id),
            )
            conn.commit()
        finally:
            conn.close()

    async def flag_illegal_user(self, chat_id: int, user_id: int, reason: str) -> None:
        async with self._lock:
            await asyncio.to_thread(self._flag_illegal_user_sync, chat_id, user_id, reason)

    def _flag_illegal_user_sync(self, chat_id: int, user_id: int, reason: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO flagged_users(chat_id, user_id, reason)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET reason=excluded.reason
                """,
                (chat_id, user_id, reason),
            )
            conn.commit()
        finally:
            conn.close()

    async def is_illegal_user(self, chat_id: int, user_id: int) -> bool:
        async with self._lock:
            return await asyncio.to_thread(self._is_illegal_user_sync, chat_id, user_id)

    def _is_illegal_user_sync(self, chat_id: int, user_id: int) -> bool:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT 1 FROM flagged_users WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
            return row is not None
        finally:
            conn.close()
