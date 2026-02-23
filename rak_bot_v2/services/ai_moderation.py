"""Unified AI moderation service with cache and rate limiting."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import random
import re
import time
import logging
from collections import OrderedDict, deque
from dataclasses import dataclass

import httpx

from rak_bot_v2.config.constants import (
    AI_RATE_LIMIT_PER_MINUTE,
    CACHE_MAX_SIZE,
    CACHE_TTL_SECONDS,
    GEMINI_MODEL,
    GEMINI_MODEL_FALLBACKS,
    TEXT_MODEL,
)

LOGGER = logging.getLogger(__name__)


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
        self._client = httpx.AsyncClient(timeout=30.0)
        self._cache: OrderedDict[str, tuple[float, ModerationResult]] = OrderedDict()
        self._calls = deque[float]()
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        """Close HTTP resources."""
        await self._client.aclose()

    async def moderate_text(self, text: str) -> ModerationResult:
        """Moderate plain text with retries and resilient fallback."""
        key = self._cache_key("text", text)
        cached = self._get_cached(key)
        if cached:
            return cached

        for attempt in range(3):
            try:
                await self._acquire_rate_slot()
                result = await self._call_groq_api(text)
                self._set_cached(key, result)
                return result
            except httpx.TimeoutException:
                LOGGER.warning("groq_timeout_attempt_%s", attempt + 1)
                if attempt < 2:
                    await asyncio.sleep((2**attempt) + random.random())
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    retry_after = int(exc.response.headers.get("retry-after", 60))
                    LOGGER.warning("groq_rate_limited, waiting %s", retry_after)
                    await asyncio.sleep(retry_after)
                else:
                    LOGGER.error("groq_http_error: %s", exc)
                    break
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("groq_unexpected_error: %s", exc)
                break

        return ModerationResult(action="allow", reason="Moderation service unavailable - allowing message")

    async def _call_groq_api(self, text: str) -> ModerationResult:
        """Execute Groq request with conservative moderation."""
        payload = {
            "model": TEXT_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a strict content moderator. Analyze text for ONLY these categories:\n"
                        "1. Hate speech / threats / harassment\n"
                        "2. Spam / scams / phishing\n"
                        "3. Adult/NSFW content\n"
                        "4. Illegal activities (drugs, weapons, etc.)\n\n"
                        "Rules:\n"
                        "- 'delete': ONLY for clear violations (hate speech, threats, explicit adult, scams)\n"
                        "- 'warn': Borderline cases or mild issues\n"
                        "- 'allow': Normal conversation, greetings, questions, opinions\n\n"
                        "Return JSON: {\"action\":\"allow|warn|delete\",\"reason\":\"brief reason\"}\n"
                        "Be conservative - when in doubt, use 'allow' or 'warn', never 'delete'."
                    ),
                },
                {"role": "user", "content": f"Analyze this message: {text}"},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        response = await self._client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {self._groq_key}"},
            json=payload,
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return ModerationResult(
            action=parsed.get("action", "allow"),
            reason=parsed.get("reason", "No reason provided"),
        )

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
                {"text": (
                    "Analyze this image for: 1) Explicit adult content, 2) Violence/gore, 3) Hate symbols. "
                    "Only return 'delete' for CLEAR violations. Otherwise 'allow'. "
                    "Return JSON: {\"action\":\"allow|delete\",\"reason\":\"...\"}"
                )},
                {"inline_data": {"mime_type": mime_type, "data": encoded}},
            ]}]
        }
        try:
            text = await self._call_gemini_with_fallback(payload)
            match = re.search(r"\{.*\}", text, re.DOTALL)
            parsed = json.loads(match.group()) if match else {}
            result = ModerationResult(action=parsed.get("action", "allow"), reason=parsed.get("reason", "No analysis"))
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("media_moderation_failed: %s", exc)
            result = ModerationResult(action="allow", reason="Media scan failed - allowing")
        self._set_cached(key, result)
        return result

    async def _call_gemini_with_fallback(self, payload: dict) -> str:
        """Call Gemini API with model fallback and retries for transient failures."""
        models = (GEMINI_MODEL, *GEMINI_MODEL_FALLBACKS)
        last_error: Exception | None = None

        for model in models:
            for attempt in range(3):
                try:
                    response = await self._client.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self._gemini_key}",
                        json=payload,
                    )
                    response.raise_for_status()
                    return response.json()["candidates"][0]["content"]["parts"][0]["text"]
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code

                    # 404 indicates a deprecated or unavailable model name: switch models immediately.
                    if status_code == 404:
                        LOGGER.warning("gemini_model_not_found: %s", model)
                        last_error = exc
                        break

                    # Retry transient/quota pressure errors before trying the next model.
                    if status_code in {429, 500, 502, 503, 504}:
                        retry_after = exc.response.headers.get("retry-after")
                        try:
                            delay = float(retry_after) if retry_after is not None else float(min(2**attempt, 8))
                        except ValueError:
                            delay = float(min(2**attempt, 8))
                        LOGGER.warning(
                            "gemini_request_retry model=%s status=%s attempt=%s delay=%ss",
                            model,
                            status_code,
                            attempt + 1,
                            delay,
                        )
                        last_error = exc
                        if attempt < 2:
                            await asyncio.sleep(delay)
                            continue
                        break

                    raise
                except httpx.TimeoutException as exc:
                    last_error = exc
                    if attempt < 2:
                        delay = min(2**attempt, 8)
                        LOGGER.warning(
                            "gemini_timeout_retry model=%s attempt=%s delay=%ss",
                            model,
                            attempt + 1,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    break

        if last_error:
            raise last_error
        raise RuntimeError("Gemini API call failed without response")

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
