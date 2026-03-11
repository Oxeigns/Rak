"""
Unified AI Moderation Service
Features: XML Sandboxing, Deep Regex Normalization, Multi-Model Fallback,
          Strict JSON Enforcement, proper warn/delete/allow passthrough.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ModerationResult:
    """Normalized moderation response for handlers."""

    action: str   # "allow" | "warn" | "delete"
    reason: str


class ModerationService:
    """Dual moderation service: Groq (text) + Gemini (image) fallback."""

    GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, groq_api_key: str = "", gemini_api_key: str = "") -> None:
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY", "")
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY", "")

        self.groq_model = os.getenv("GROQ_TEXT_MODERATION_MODEL", "llama-3.3-70b-versatile")
        self.gemini_model = (
            os.getenv("GEMINI_IMAGE_MODERATION_MODEL", "gemini-2.0-flash")
            .replace("models/", "")
        )

        self.timeout = float(os.getenv("AI_TIMEOUT", "20.0"))
        self._http_client: httpx.AsyncClient | None = None

    async def initialize(self) -> None:
        """Create shared HTTP client (idempotent)."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self.timeout)

    async def cleanup(self) -> None:
        """Close HTTP client."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _sanitize_for_sandbox(value: str, max_length: int = 2000) -> str:
        """Protect against prompt injection and XML tag injection."""
        if not value:
            return ""
        sanitized = re.sub(
            r"</?content>|<!\[CDATA\[|ignore previous instructions",
            "",
            value,
            flags=re.IGNORECASE,
        )
        return " ".join(sanitized.split())[:max_length]

    def _deep_regex_scan(self, text: str) -> ModerationResult | None:
        """
        Fast local deterministic check before hitting AI.
        Normalizes text to catch obfuscated patterns like 'd.r.u.g.s'.
        """
        normalized = re.sub(r"[^a-zA-Z0-9]", "", text.lower())

        critical_patterns: dict[str, str] = {
            r"porn|nude|sex|xxx|nsfw|onlyfans": "NSFW/Adult content",
            r"drugs?|ganja|weed|charas|heroin|meth|nasha": "Illegal substances",
            r"scam|fraud|phishing|cryptoqr|invest2x": "Scam or Fraud",
            r"kill|murder|behead|suicide|deaththreat": "Violence or Self-harm",
        }

        for pattern, reason in critical_patterns.items():
            if re.search(pattern, normalized):
                return ModerationResult(action="delete", reason=f"[Auto-Filter] {reason}")
        return None

    # ── Text Moderation ────────────────────────────────────────────────────

    async def moderate_text(self, text: str, caption: str | None = None) -> ModerationResult:
        """
        Moderate text via:
         1. Fast local regex scan
         2. Groq LLM (returns allow / warn / delete with reason)
        """
        combined = f"{text or ''} {caption or ''}".strip()
        if not combined:
            return ModerationResult(action="allow", reason="Empty content")

        # 1. Deterministic fast check
        local_result = self._deep_regex_scan(combined)
        if local_result:
            return local_result

        # 2. AI check
        if not self.groq_api_key:
            return ModerationResult(action="allow", reason="API key missing")

        await self.initialize()
        sanitized = self._sanitize_for_sandbox(combined)
        prompt = (
            "Analyze the content within <content> tags for Telegram policy violations.\n"
            "Return ONLY valid JSON: {\"action\":\"allow|warn|delete\",\"reason\":\"...\"}\n"
            f"<content>\n{sanitized}\n</content>"
        )
        return await self._call_groq_api(prompt)

    async def _call_groq_api(self, prompt: str) -> ModerationResult:
        """Call Groq API with native JSON mode. Returns ModerationResult directly."""
        if self._http_client is None:
            raise RuntimeError("HTTP client not initialized; call initialize() first")

        payload = {
            "model": self.groq_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a strict Telegram content moderation AI. "
                        "Classify the given content. "
                        "action must be exactly one of: allow, warn, delete. "
                        "Output ONLY valid JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }

        response = await self._http_client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.groq_api_key}"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        parsed: dict[str, Any] = json.loads(data["choices"][0]["message"]["content"])

        raw_action = str(parsed.get("action", "allow")).lower()
        action = raw_action if raw_action in {"allow", "warn", "delete"} else "allow"
        return ModerationResult(action=action, reason=str(parsed.get("reason", "Verified safe")))

    # ── Image Moderation ───────────────────────────────────────────────────

    async def moderate_image(self, image_bytes: bytes, caption: str = "") -> ModerationResult:
        """
        Analyse image via Gemini, then optionally check caption text too.
        Falls back to allow on any failure.
        """
        if not image_bytes:
            return ModerationResult(action="allow", reason="No image data")

        await self.initialize()

        img_result = await self._analyze_image_with_gemini(image_bytes)
        if img_result and img_result.action != "allow":
            return img_result

        # Check caption separately via text moderation
        if caption:
            return await self.moderate_text(caption)

        return ModerationResult(action="allow", reason="Clean content")

    async def _analyze_image_with_gemini(self, image_bytes: bytes) -> ModerationResult | None:
        """Send image to Gemini for NSFW/violence/scam analysis."""
        if not self.gemini_api_key:
            return None

        url = (
            f"{self.GEMINI_API_BASE}/models/{self.gemini_model}"
            f":generateContent?key={self.gemini_api_key}"
        )
        prompt_text = (
            "Analyze this image for: NSFW content, Drugs, Violence, Scams, or policy violations.\n"
            'Return ONLY JSON: {"action":"allow|warn|delete","reason":"string"}'
        )
        body = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt_text},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": base64.b64encode(image_bytes).decode("utf-8"),
                            }
                        },
                    ]
                }
            ]
        }

        if self._http_client is None:
            return None

        try:
            response = await self._http_client.post(url, json=body)
            if response.status_code != 200:
                LOGGER.warning("gemini_image_failed status=%s", response.status_code)
                return None

            text_output = response.json()["candidates"][0]["content"]["parts"][0]["text"]
            match = re.search(r"\{.*\}", text_output, re.DOTALL)
            if not match:
                return None
            parsed: dict[str, Any] = json.loads(match.group())
            raw_action = str(parsed.get("action", "allow")).lower()
            action = raw_action if raw_action in {"allow", "warn", "delete"} else "allow"
            return ModerationResult(action=action, reason=str(parsed.get("reason", "")))
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("gemini_image_error: %s", exc)
            return None


class AiModerationService:
    """Production wrapper – thin façade used by message handlers."""

    # Shared semaphore to cap concurrent upstream AI calls
    AI_SEMAPHORE = asyncio.Semaphore(int(os.getenv("AI_MAX_CONCURRENT_CALLS", "5")))

    def __init__(self, groq_api_key: str, gemini_api_key: str) -> None:
        self._service = ModerationService(groq_api_key, gemini_api_key)

    async def close(self) -> None:
        """Release HTTP resources."""
        await self._service.cleanup()

    async def moderate_text(self, text: str) -> ModerationResult:
        """Moderate plain text. Returns allow / warn / delete result."""
        try:
            async with self.AI_SEMAPHORE:
                return await self._service.moderate_text(text)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("text_moderation_failed: %s", exc)
            return ModerationResult(action="allow", reason="AI moderation unavailable")

    async def moderate_media(
        self, data: bytes, mime_type: str, caption: str = ""
    ) -> ModerationResult:
        """Moderate image/media bytes. Returns allow / warn / delete result."""
        try:
            async with self.AI_SEMAPHORE:
                return await self._service.moderate_image(data, caption)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("media_moderation_failed: %s", exc)
            return ModerationResult(action="allow", reason="AI moderation unavailable")
