from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import time
from collections import defaultdict, deque


class CallbackSecurityError(ValueError):
    pass


class CallbackSigner:
    def __init__(self, secret: str, ttl_seconds: int) -> None:
        self._secret = secret.encode('utf-8')
        self._ttl = ttl_seconds
        self._consumed: set[str] = set()
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def sign(self, owner_user_id: int, action: str, nonce: str) -> str:
        issued_at = int(time.time())
        payload = f'{owner_user_id}:{action}:{nonce}:{issued_at}'
        digest = hmac.new(self._secret, payload.encode('utf-8'), hashlib.sha256).digest()
        token = base64.urlsafe_b64encode(digest[:10]).decode('utf-8').rstrip('=')
        return f'v1|{owner_user_id}|{action}|{nonce}|{issued_at}|{token}'

    async def verify(self, callback_data: str, user_id: int, required_action: str | None = None) -> dict[str, str]:
        parts = callback_data.split('|')
        if len(parts) != 6 or parts[0] != 'v1':
            raise CallbackSecurityError('Malformed callback payload.')

        owner, action, nonce, issued_at, token = parts[1:]
        if required_action and action != required_action:
            raise CallbackSecurityError('Unexpected callback action.')
        if int(owner) != user_id:
            raise CallbackSecurityError('This button does not belong to you.')

        age = int(time.time()) - int(issued_at)
        if age < 0 or age > self._ttl:
            raise CallbackSecurityError('This button has expired. Please run command again.')

        expected = self.sign(int(owner), action, nonce).split('|')[-1]
        if not hmac.compare_digest(expected, token):
            raise CallbackSecurityError('Invalid callback signature.')

        unique_key = f'{owner}:{action}:{nonce}:{issued_at}'
        async with self._locks[unique_key]:
            if unique_key in self._consumed:
                raise CallbackSecurityError('This button was already used.')
            self._consumed.add(unique_key)

        return {'owner_user_id': owner, 'action': action, 'nonce': nonce, 'issued_at': issued_at}


class UserRateLimiter:
    def __init__(self, window_seconds: int, max_requests: int) -> None:
        self._window_seconds = window_seconds
        self._max_requests = max_requests
        self._events: dict[int, deque[float]] = defaultdict(deque)

    def check(self, user_id: int) -> bool:
        now = time.time()
        items = self._events[user_id]
        while items and now - items[0] > self._window_seconds:
            items.popleft()
        if len(items) >= self._max_requests:
            return False
        items.append(now)
        return True


class CooldownManager:
    def __init__(self, cooldown_seconds: int) -> None:
        self._cooldown_seconds = cooldown_seconds
        self._last_prompt: dict[int, float] = {}

    def should_prompt(self, user_id: int) -> bool:
        now = time.time()
        last = self._last_prompt.get(user_id, 0.0)
        if now - last < self._cooldown_seconds:
            return False
        self._last_prompt[user_id] = now
        return True
