"""Unified AI moderation service with cache and rate limiting."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import time
from collections import OrderedDict, deque
from dataclasses import dataclass

import httpx

from rak_bot_v2.config.constants import (
    AI_RATE_LIMIT_PER_MINUTE,
    CACHE_MAX_SIZE,
    CACHE_TTL_SECONDS,
    GEMINI_MODEL,
    TEXT_MODEL,
)


@dataclass(slots=True)
class ModerationResult:
    """Normalized moderation response."""

    action: str
    reason: str


class AiModerationService:
    """Calls Groq for text and Gemini for media moderation."""

    def __init__(self, groq_api_key: str, gemini_api_key: str) -> None:
        self._groq_key = groq_api_key
        self._gemini_key = gemini_api_key
        self._client = httpx.AsyncClient(timeout=15.0)
        self._cache: OrderedDict[str, tuple[float, ModerationResult]] = OrderedDict()
        self._calls = deque[float]()
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        """Close HTTP resources."""
        await self._client.aclose()

    async def moderate_text(self, text: str) -> ModerationResult:
        """Moderate plain text with Groq model."""
        key = self._cache_key("text", text)
        cached = self._get_cached(key)
        if cached:
            return cached
        await self._acquire_rate_slot()
        payload = {
            "model": TEXT_MODEL,
            "messages": [
                {"role": "system", "content": "Return strict JSON: {\"action\":\"allow|warn|delete\",\"reason\":\"...\"}."},
                {"role": "user", "content": f"Moderate this: {text}"},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        try:
            response = await self._client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._groq_key}"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            result = ModerationResult(action=parsed.get("action", "warn"), reason=parsed.get("reason", "Rule violation"))
        except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError, TypeError, ValueError):
            result = ModerationResult(action="warn", reason="AI service busy, safe mode warn applied")
        self._set_cached(key, result)
        return result

    async def moderate_media(self, data: bytes, mime_type: str, caption: str = "") -> ModerationResult:
        """Moderate media content with Gemini vision API."""
        key = self._cache_key("media", f"{caption}:{hashlib.sha256(data).hexdigest()}")
        cached = self._get_cached(key)
        if cached:
            return cached
        await self._acquire_rate_slot()
        encoded = base64.b64encode(data).decode("utf-8")
        payload = {
            "contents": [{"parts": [
                {"text": f"Analyze media for spam/toxic/illegal content. caption:{caption}. Return JSON action+reason."},
                {"inline_data": {"mime_type": mime_type, "data": encoded}},
            ]}]
        }
        try:
            response = await self._client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={self._gemini_key}",
                json=payload,
            )
            response.raise_for_status()
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            match = re.search(r"\{.*\}", text, re.DOTALL)
            parsed = json.loads(match.group()) if match else {}
            result = ModerationResult(action=parsed.get("action", "warn"), reason=parsed.get("reason", "Suspicious media"))
        except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError, TypeError, ValueError):
            result = ModerationResult(action="warn", reason="Media scan unavailable, cautious warning")
        self._set_cached(key, result)
        return result

    async def _acquire_rate_slot(self) -> None:
        async with self._lock:
            while True:
                now = time.time()
                while self._calls and now - self._calls[0] > 60:
                    self._calls.popleft()
                if len(self._calls) < AI_RATE_LIMIT_PER_MINUTE:
                    break
                await asyncio.sleep(0.5)
            self._calls.append(time.time())

    def _cache_key(self, prefix: str, content: str) -> str:
        return f"{prefix}:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"

    def _get_cached(self, key: str) -> ModerationResult | None:
        hit = self._cache.get(key)
        if not hit:
            return None
        ts, value = hit
        if time.time() - ts > CACHE_TTL_SECONDS:
            self._cache.pop(key, None)
            return None
        self._cache.move_to_end(key)
        return value

    def _set_cached(self, key: str, value: ModerationResult) -> None:
        self._cache[key] = (time.time(), value)
        self._cache.move_to_end(key)
        if len(self._cache) > CACHE_MAX_SIZE:
            self._cache.popitem(last=False)
