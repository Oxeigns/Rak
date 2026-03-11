"""Unified AI moderation service with Groq text + Gemini/OpenAI image fallback."""

from __future__ import annotations

import asyncio
import base64
import imghdr
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from rak_bot_v2.config.constants import TEXT_MODEL
from rak_bot_v2.config.settings import get_settings

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ModerationResult:
    """Normalized moderation response for handlers."""

    action: str
    reason: str


class ModerationService:
    """Dual moderation service: Groq (text) + Gemini (image) with OpenAI fallback."""

    GEMINI_FALLBACK_MODELS = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-flash-8b"]
    GEMINI_BACKOFF_DELAYS_SECONDS = (2, 4, 8)

    def __init__(self, groq_api_key: str = "", gemini_api_key: str = "") -> None:
        self.settings = get_settings()
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY", "")
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY", "")
        self.groq_model = os.getenv("GROQ_TEXT_MODERATION_MODEL", TEXT_MODEL)

        self.gemini_base_url = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/models/")
        self.timeout_seconds = float(os.getenv("AI_TIMEOUT", "30"))

        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.openai_model = os.getenv("OPENAI_IMAGE_MODERATION_MODEL", "gpt-4o-mini")

        self._http_client: httpx.AsyncClient | None = None
        self._last_successful_gemini_model: str | None = None

    async def initialize(self) -> None:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self.timeout_seconds)

    async def cleanup(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    @staticmethod
    def _sanitize_prompt_text(value: str, max_length: int = 4000) -> str:
        sanitized = (value or "").replace("```", "").replace(chr(0), "")
        sanitized = " ".join(sanitized.split())
        return sanitized[:max_length]

    async def analyze_text(self, text: str, caption: str | None = None) -> dict[str, Any]:
        """Analyze text with Groq using high-security moderation policy."""
        text_value = self._sanitize_prompt_text((text or "").strip())
        caption_value = self._sanitize_prompt_text((caption or "").strip())
        combined_text = f"{text_value} {caption_value}".strip()

        if not combined_text:
            return self._safe_result("Safe content, bhai, chill")

        strict_result = self._rule_based_high_security_scan(combined_text)
        if strict_result is not None:
            return strict_result

        if not self.groq_api_key:
            LOGGER.error("Groq API key missing for text moderation")
            return self._safe_result("Safe content, bhai, chill")

        await self.initialize()

        try:
            result = await self._call_groq_api(f"Text: {text_value}\nCaption: {caption_value}")
            return {
                "is_safe": result.action != "delete",
                "toxic_score": 0.0,
                "illegal_score": 1.0 if result.action == "delete" else 0.0,
                "spam_score": 0.0,
                "reason": result.reason,
            }
        except Exception as error:  # noqa: BLE001
            LOGGER.error("Groq request error: %s", error)
            return self._safe_result("Safe content, bhai, chill")

    async def _call_groq_api(self, text: str) -> ModerationResult:
        payload = {
            "model": self.groq_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an elite Telegram moderation AI.\n\n"
                        "The group contains multilingual users:\n"
                        "- Indian languages (Hindi, Hinglish, Tamil, Bengali)\n"
                        "- Russian\n"
                        "- English\n\n"
                        "Strictly detect:\n"
                        "1. Hate speech (religion, caste, race, nationality)\n"
                        "2. Harassment or threats\n"
                        "3. Slang abuse (Indian & Russian)\n"
                        "4. Spam / scams / crypto fraud / betting links\n"
                        "5. Phishing URLs\n"
                        "6. Adult/NSFW content\n"
                        "7. Drugs / weapons / illegal trade\n"
                        "8. Flooding / repeated characters\n\n"
                        "Be context aware.\n"
                        "Friendly joking = warn.\n"
                        "Clear violation = delete.\n"
                        "Safe message = allow.\n\n"
                        "Return ONLY valid JSON:\n"
                        '{"action":"allow|warn|delete","reason":"short explanation","confidence":0.0-1.0}'
                    ),
                },
                {"role": "user", "content": text},
            ],
            "temperature": 0,
            "max_tokens": 300,
            "top_p": 1,
        }

        assert self._http_client is not None
        try:
            response = await self._http_client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.groq_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            response.raise_for_status()

        except httpx.HTTPStatusError as exc:
            LOGGER.error("Groq error body: %s", exc.response.text)
            raise

        data = response.json()

        if "choices" not in data or not data["choices"]:
            LOGGER.error("Groq empty response: %s", data)
            return ModerationResult("allow", "Empty AI response")

        content = data["choices"][0]["message"]["content"]

        parsed = self._safe_parse_json_object(content)

        action = str(parsed.get("action", "allow")).lower()
        reason = str(parsed.get("reason", "No reason provided"))

        try:
            confidence = float(parsed.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5

        if action not in {"allow", "warn", "delete"}:
            action = "allow"

        if action == "delete" and confidence < 0.65:
            action = "warn"

        return ModerationResult(action=action, reason=reason)

    @staticmethod
    def _safe_parse_json_object(content: str) -> dict[str, Any]:
        parsed = ModerationService._parse_json_like_response(content)
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _normalize_result(payload: dict[str, Any]) -> ModerationResult:
        action = str(payload.get("action", "allow")).strip().lower()
        if action not in {"allow", "warn", "delete"}:
            action = "allow"
        reason = str(payload.get("reason", "Safe content, bhai, chill")).strip() or "Safe content, bhai, chill"
        return ModerationResult(action=action, reason=reason)

    async def analyze_image(self, image_bytes: bytes) -> dict[str, Any]:
        """Analyze image with Gemini and fallback to OpenAI."""
        if not image_bytes:
            return self._safe_result("Image missing - allowing")

        await self.initialize()

        prompt = (
            "You are an image safety analyzer for Telegram. Analyze the image and return STRICT JSON ONLY.\n\n"
            "STRICT RULES - Mark UNSAFE (is_safe: false) ONLY for:\n"
            "1. ILLEGAL DRUGS: Actual narcotics, pills, drug paraphernalia, or drug deals visible\n"
            "2. NSFW: Explicit nudity, sexual content, pornography\n"
            "3. VIOLENCE/GORE: Graphic violence, weapons being used, blood/gore\n"
            "4. SCAMS: Phishing QR codes, fake crypto schemes visible in image\n\n"
            "MARK SAFE (is_safe: true) for:\n"
            "- Normal selfies, group photos\n"
            "- Food, nature, animals, cars\n"
            "- Memes, anime, gaming screenshots\n"
            "- Medical pills shown for health questions\n"
            "- Artistic/educational content\n\n"
            "OUTPUT FORMAT (STRICT JSON):\n"
            "{\n"
            '  "is_safe": boolean,\n'
            '  "toxic_score": float (0.0-1.0),\n'
            '  "illegal_score": float (0.0-1.0),\n'
            '  "spam_score": float (0.0-1.0),\n'
            '  "reason": "Hinglish explanation only if unsafe"\n'
            "}\n\n"
            "IMPORTANT: When in doubt, mark SAFE. Minimize false positives."
        )

        gemini_result = await self._analyze_image_with_gemini(image_bytes=image_bytes, prompt=prompt)
        if gemini_result is not None:
            return self._normalize_image_response(gemini_result)

        openai_result = await self._analyze_image_with_openai(image_bytes=image_bytes, prompt=prompt)
        if openai_result is not None:
            LOGGER.warning("Gemini failed; OpenAI fallback succeeded")
            return self._normalize_image_response(openai_result)

        return self._safe_result("Image moderation temporarily unavailable")

    async def _analyze_image_with_gemini(self, image_bytes: bytes, prompt: str) -> dict[str, Any] | None:
        if not self.gemini_api_key:
            LOGGER.warning("Gemini API key missing; skipping Gemini")
            return None

        response_text = await self.generate_gemini_content(prompt=prompt, image_bytes=image_bytes)
        if response_text == "All Gemini models unavailable":
            return None
        return self._parse_json_like_response(response_text)

    async def generate_gemini_content(self, prompt: str, image_bytes: bytes | None = None) -> str:
        """Generate Gemini content with model failover and exponential backoff."""
        await self.initialize()

        model_candidates = self._get_model_candidates()
        retries = 0

        for index, model in enumerate(model_candidates):
            LOGGER.info("Gemini request using model=%s", model)

            status_code, response_text = await self._gemini_generate_with_model(model=model, prompt=prompt, image_bytes=image_bytes)
            if response_text:
                self._last_successful_gemini_model = model
                LOGGER.info("Gemini request succeeded with model=%s", model)
                return response_text

            should_fallback = status_code == 429 or (status_code is not None and 500 <= status_code < 600)
            if not should_fallback:
                LOGGER.warning("Gemini non-retryable failure with model=%s (status=%s)", model, status_code)
                continue

            if index == len(model_candidates) - 1:
                LOGGER.warning("Gemini fallback unavailable after model=%s", model)
                break

            delay = self.GEMINI_BACKOFF_DELAYS_SECONDS[min(retries, len(self.GEMINI_BACKOFF_DELAYS_SECONDS) - 1)]
            next_model = model_candidates[index + 1]
            LOGGER.warning(
                "Gemini fallback switch: model=%s -> %s (status=%s). Retrying in %ss",
                model,
                next_model,
                status_code,
                delay,
            )
            retries += 1
            await asyncio.sleep(delay)

        return "All Gemini models unavailable"

    def _get_model_candidates(self) -> list[str]:
        if not self._last_successful_gemini_model:
            return list(self.GEMINI_FALLBACK_MODELS)

        ordered = [self._last_successful_gemini_model]
        ordered.extend(model for model in self.GEMINI_FALLBACK_MODELS if model != self._last_successful_gemini_model)
        return ordered

    async def _gemini_generate_with_model(
        self,
        model: str,
        prompt: str,
        image_bytes: bytes | None = None,
    ) -> tuple[int | None, str | None]:
        image_format = imghdr.what(None, h=image_bytes) if image_bytes else None
        mime_type = f"image/{image_format}" if image_format else "image/jpeg"

        base_url = self.gemini_base_url.rstrip("/") + "/"
        url = f"{base_url}{model}:generateContent"
        params = {"key": self.gemini_api_key}
        parts: list[dict[str, Any]] = [{"text": prompt}]
        if image_bytes:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": base64.b64encode(image_bytes).decode("utf-8"),
                    }
                }
            )

        body = {
            "contents": [
                {
                    "parts": parts,
                }
            ],
            "generationConfig": {"temperature": 0},
        }

        try:
            assert self._http_client is not None
            response = await self._http_client.post(url, params=params, json=body)

            if response.status_code == 429 or 500 <= response.status_code < 600:
                LOGGER.warning("Gemini retryable status=%s for model=%s", response.status_code, model)
                return response.status_code, None

            response.raise_for_status()

            response_payload = response.json() if response.content else {}
            text = self._extract_gemini_text(response_payload)
            if not text:
                LOGGER.error("Gemini returned empty response text for model=%s", model)
                return response.status_code, None

            return response.status_code, text
        except httpx.HTTPStatusError as error:
            status_code = error.response.status_code if error.response is not None else None
            LOGGER.error("Gemini HTTP status error for model=%s status=%s", model, status_code)
            return status_code, None
        except httpx.HTTPError as error:
            LOGGER.error("Gemini transport error for model=%s: %s", model, error)
            return 503, None
        except Exception as error:  # noqa: BLE001
            LOGGER.error("Gemini unexpected error for model=%s: %s", model, error)
            return None, None

    @staticmethod
    def _extract_gemini_text(payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates") or []
        for candidate in candidates:
            content = candidate.get("content") or {}
            parts = content.get("parts") or []
            for part in parts:
                text = part.get("text")
                if text:
                    return str(text)
        return ""

    async def _analyze_image_with_openai(self, image_bytes: bytes, prompt: str) -> dict[str, Any] | None:
        if not self.openai_api_key:
            LOGGER.warning("OpenAI API key missing; cannot run fallback")
            return None

        image_format = imghdr.what(None, h=image_bytes)
        mime_type = f"image/{image_format}" if image_format else "image/jpeg"
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")

        payload = {
            "model": self.openai_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{image_base64}"},
                        },
                    ],
                }
            ],
        }

        try:
            assert self._http_client is not None
            response = await self._http_client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not content:
                return None
            return self._parse_json_like_response(content)
        except Exception as error:  # noqa: BLE001
            LOGGER.error("OpenAI fallback failed: %s", error)
            return None

    @staticmethod
    def _normalize_text_response(raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "is_safe": bool(raw.get("is_safe", True)),
            "toxic_score": float(raw.get("toxic_score", raw.get("toxicity_score", 0.0))),
            "illegal_score": float(raw.get("illegal_score", 0.0)),
            "spam_score": float(raw.get("spam_score", 0.0)),
            "reason": str(raw.get("reason", "Safe content, bhai, chill")),
        }

    @staticmethod
    def _safe_result(reason: str) -> dict[str, Any]:
        return {
            "is_safe": True,
            "toxic_score": 0.0,
            "illegal_score": 0.0,
            "spam_score": 0.0,
            "reason": reason,
        }

    @staticmethod
    def _rule_based_high_security_scan(text: str) -> dict[str, Any] | None:
        lowered = text.lower()

        critical_patterns = {
            "Bhai, drugs/nasha ki baatein strictly mana hain": r"\b(drugs?|ganja|weed|charas|heroin|cocaine|crack|mdma|meth|pills?|lsd|ecstasy|dope|smack|nasha|cocain|marijuana|opioid|fentanyl)\b",
            "Bhai, ye content NSFW hain": r"\b(nsfw|porn|nude|sex|xxx|onlyfans)\b",
            "Bhai, ye scam ya fraud hain": r"\b(scam|fraud|phishing|crypto\s+qr|get\s+rich\s+quick|double\s+money)\b",
            "Bhai, ye bahut violent hain, mana hain": r"\b(kill|murder|behead|gore|shoot\s+him|death\s+threat)\b",
        }

        for reason, pattern in critical_patterns.items():
            if re.search(pattern, lowered):
                toxic = 1.0 if reason != "Bhai, ye scam ya fraud hain" else 0.7
                return {
                    "is_safe": False,
                    "toxic_score": toxic,
                    "illegal_score": 1.0,
                    "spam_score": 0.0,
                    "reason": reason,
                }
        return None

    @staticmethod
    def _normalize_image_response(raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "is_safe": bool(raw.get("is_safe", True)),
            "toxic_score": float(raw.get("toxic_score", 0.0)),
            "illegal_score": float(raw.get("illegal_score", 0.0)),
            "spam_score": float(raw.get("spam_score", 0.0)),
            "reason": str(raw.get("reason", "Safe content")),
        }

    @staticmethod
    def _parse_json_like_response(value: str) -> dict[str, Any]:
        """Parse LLM text output into JSON, tolerating markdown fenced payloads."""
        text = (value or "").strip()
        if not text:
            return {}

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if fenced:
                try:
                    return json.loads(fenced.group(1))
                except json.JSONDecodeError:
                    pass

            first = text.find("{")
            last = text.rfind("}")
            if first != -1 and last != -1 and first < last:
                try:
                    return json.loads(text[first : last + 1])
                except json.JSONDecodeError:
                    pass

        return {}


class AiModerationService:
    """Compatibility wrapper to expose existing moderate_text/moderate_media API."""

    def __init__(self, groq_api_key: str, gemini_api_key: str) -> None:
        self._service = ModerationService(groq_api_key=groq_api_key, gemini_api_key=gemini_api_key)

    async def close(self) -> None:
        await self._service.cleanup()

    async def moderate_text(self, text: str) -> ModerationResult:
        result = await self._service.analyze_text(text)
        return self._to_result(result)

    async def moderate_media(self, data: bytes, mime_type: str, caption: str = "") -> ModerationResult:
        del mime_type  # Gemini endpoint infers from byte signature.
        result = await self._service.analyze_image(data)
        if caption:
            caption_result = await self._service.analyze_text(caption)
            if not caption_result.get("is_safe", True):
                return self._to_result(caption_result)
        return self._to_result(result)

    @staticmethod
    def _to_result(payload: dict[str, Any]) -> ModerationResult:
        is_safe = bool(payload.get("is_safe", True))
        reason = str(payload.get("reason", "Safe content"))
        return ModerationResult(action="allow" if is_safe else "delete", reason=reason)
