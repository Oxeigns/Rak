from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from collections import defaultdict, deque


class CallbackSecurityError(ValueError):
    pass


class CallbackSigner:
    _SIGNATURE_HEX_LENGTH = 16
    _MAX_TRACKED_CALLBACKS = 4096

    def __init__(self, secret: str, ttl_seconds: int, allowed_actions: set[str]) -> None:
        self._secret = secret.encode('utf-8')
        self._ttl = ttl_seconds
        self._allowed_actions = allowed_actions
        self._consumed: dict[str, int] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _prune_expired(self) -> None:
        now = int(time.time())
        expired_keys = [key for key, issued_at in self._consumed.items() if now - issued_at > self._ttl]
        for key in expired_keys:
            self._consumed.pop(key, None)
            self._locks.pop(key, None)

        if len(self._consumed) <= self._MAX_TRACKED_CALLBACKS:
            return

        # Keep the newest entries when traffic is high.
        for key, _ in sorted(self._consumed.items(), key=lambda item: item[1])[:-self._MAX_TRACKED_CALLBACKS]:
            self._consumed.pop(key, None)
            self._locks.pop(key, None)

    def _signature(self, action: str, owner_user_id: int, issued_at: int) -> str:
        payload = f'{action}:{owner_user_id}:{issued_at}'.encode('utf-8')
        # Telegram callback_data has a strict 64-byte limit, so keep the
        # signature compact while preserving tamper detection.
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()[: self._SIGNATURE_HEX_LENGTH]

    def sign(self, owner_user_id: int, action: str) -> str:
        self._prune_expired()
        if action not in self._allowed_actions:
            raise CallbackSecurityError(f'Action {action!r} is not in callback allow-list.')
        issued_at = int(time.time())
        signature = self._signature(action, owner_user_id, issued_at)
        return f'{action}:{owner_user_id}:{issued_at}:{signature}'

    async def verify(self, callback_data: str, user_id: int, required_action: str | None = None) -> dict[str, int | str]:
        self._prune_expired()
        parts = callback_data.split(':')
        if len(parts) != 4:
            raise CallbackSecurityError('Malformed callback payload.')

        action, owner_raw, issued_at_raw, signature = parts
        if action not in self._allowed_actions:
            raise CallbackSecurityError('Callback action is not allowed.')
        if required_action and action != required_action:
            raise CallbackSecurityError('Unexpected callback action.')

        try:
            owner_user_id = int(owner_raw)
            issued_at = int(issued_at_raw)
        except ValueError as exc:
            raise CallbackSecurityError('Malformed callback payload numeric fields.') from exc

        if owner_user_id != user_id:
            raise CallbackSecurityError('This button does not belong to you.')

        age = int(time.time()) - issued_at
        if age < 0 or age > self._ttl:
            raise CallbackSecurityError('This button has expired. Please run command again.')

        expected_signature = self._signature(action, owner_user_id, issued_at)
        if not hmac.compare_digest(expected_signature, signature):
            raise CallbackSecurityError('Invalid callback signature.')

        callback_key = f'{action}:{owner_user_id}:{issued_at}:{signature}'
        async with self._locks[callback_key]:
            if callback_key in self._consumed:
                raise CallbackSecurityError('This button was already used.')
            self._consumed[callback_key] = issued_at

        return {'owner_user_id': owner_user_id, 'action': action, 'issued_at': issued_at}


class UserRateLimiter:
    _MAX_TRACKED_USERS = 10000

    def __init__(self, window_seconds: int, max_requests: int) -> None:
        self._window_seconds = window_seconds
        self._max_requests = max_requests
        self._events: dict[int, deque[float]] = defaultdict(deque)

    def _prune(self, now: float) -> None:
        stale_users = [user_id for user_id, events in self._events.items() if not events or now - events[-1] > self._window_seconds]
        for user_id in stale_users:
            self._events.pop(user_id, None)

        if len(self._events) <= self._MAX_TRACKED_USERS:
            return

        for user_id, _ in sorted(self._events.items(), key=lambda item: item[1][-1])[:-self._MAX_TRACKED_USERS]:
            self._events.pop(user_id, None)

    def check(self, user_id: int) -> bool:
        now = time.time()
        self._prune(now)
        items = self._events[user_id]
        while items and now - items[0] > self._window_seconds:
            items.popleft()
        if len(items) >= self._max_requests:
            return False
        items.append(now)
        return True


class CooldownManager:
    _MAX_TRACKED_USERS = 10000

    def __init__(self, cooldown_seconds: int) -> None:
        self._cooldown_seconds = cooldown_seconds
        self._last_prompt: dict[int, float] = {}

    def _prune(self, now: float) -> None:
        stale_users = [user_id for user_id, ts in self._last_prompt.items() if now - ts > self._cooldown_seconds]
        for user_id in stale_users:
            self._last_prompt.pop(user_id, None)

        if len(self._last_prompt) <= self._MAX_TRACKED_USERS:
            return

        for user_id, _ in sorted(self._last_prompt.items(), key=lambda item: item[1])[:-self._MAX_TRACKED_USERS]:
            self._last_prompt.pop(user_id, None)

    def should_prompt(self, user_id: int) -> bool:
        now = time.time()
        self._prune(now)
        last = self._last_prompt.get(user_id, 0.0)
        if now - last < self._cooldown_seconds:
            return False
        self._last_prompt[user_id] = now
        return True
