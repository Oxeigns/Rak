import asyncio
import base64
import imghdr
import json
import logging
import os
import re
from typing import Any, Dict, Optional

import httpx
from google.api_core import exceptions as google_exceptions
from google import genai

from settings import get_settings

logger = logging.getLogger(__name__)


async def hf_text_moderation(text: str) -> Optional[float]:
    """Run first-layer text toxicity check using HuggingFace Toxic-BERT."""
    hf_token = os.getenv("HF_TOKEN")
    if not hf_token or not text.strip():
        return None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api-inference.huggingface.co/models/unitary/toxic-bert",
                headers={"Authorization": f"Bearer {hf_token}"},
                json={"inputs": text},
            )
    except httpx.TimeoutException:
        return None
    except Exception:
        return None

    if response.status_code != 200:
        return None

    try:
        payload = response.json()
    except Exception:
        return None

    if not isinstance(payload, list) or not payload:
        return None

    first = payload[0]
    if not isinstance(first, list):
        return None

    for item in first:
        if isinstance(item, dict) and str(item.get("label", "")).lower() == "toxic":
            try:
                return float(item.get("score", 0.0))
            except (TypeError, ValueError):
                return None

    return None

class ModerationService:
    """Dual moderation service: Groq (text) + Gemini (image)."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.groq_api_key = self.settings.GROQ_API_KEY
        self.gemini_api_key = self.settings.GEMINI_API_KEY
        self.groq_model = self.settings.GROQ_TEXT_MODERATION_MODEL
        
        self.gemini_model_name = self.settings.GEMINI_IMAGE_MODERATION_MODEL
        self.timeout_seconds = float(self.settings.AI_TIMEOUT)

        self._http_client: Optional[httpx.AsyncClient] = None
        self._gemini_api_version: Optional[str] = None
        self._gemini_model: Optional[str] = None
        self._gemini_client = None

        if self.gemini_api_key:
            try:
                self._gemini_client = genai.Client(api_key=self.gemini_api_key)
                logger.info("Gemini client initialized")
            except Exception as e:
                logger.error(f"Gemini Init Failed: {e}")

    async def _discover_gemini_model(self) -> Optional[str]:
        if not self._gemini_client:
            return None
        if self._gemini_model:
            return self._gemini_model

        preferred_prefixes = ("gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro")

        def _list_models() -> list[str]:
            names: list[str] = []
            for model in self._gemini_client.models.list():
                name = str(getattr(model, "name", "") or "")
                methods = [str(method) for method in (getattr(model, "supported_generation_methods", None) or [])]
                if "generateContent" not in methods:
                    continue
                if name.startswith("models/"):
                    name = name.split("models/", 1)[1]
                if name:
                    names.append(name)
            return names

        try:
            names = await asyncio.to_thread(_list_models)
        except Exception as exc:
            logger.warning("Gemini model discovery failed: %s", exc)
            self._gemini_model = self.gemini_model_name
            return self._gemini_model

        for preferred in preferred_prefixes:
            for name in names:
                if name.startswith(preferred):
                    self._gemini_model = name
                    logger.info("Gemini model selected dynamically: %s", name)
                    return self._gemini_model

        if names:
            self._gemini_model = names[0]
            logger.info("Gemini model selected dynamically: %s", self._gemini_model)
            return self._gemini_model

        self._gemini_model = self.gemini_model_name
        return self._gemini_model

    async def _discover_gemini_api_version(self) -> str:
        if self._gemini_api_version:
            return self._gemini_api_version

        await self.initialize()
        headers = {"x-goog-api-key": self.gemini_api_key}
        for version in ("v1", "v1beta"):
            url = f"https://generativelanguage.googleapis.com/{version}/models"
            try:
                response = await self._http_client.get(url, headers=headers)
                if response.is_success:
                    self._gemini_api_version = version
                    logger.info("Gemini API version selected dynamically: %s", version)
                    return version
            except Exception as exc:
                logger.warning("Gemini API version probe failed for %s: %s", version, exc)

        self._gemini_api_version = "v1beta"
        return self._gemini_api_version

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

    async def analyze_text(self, text: str, caption: Optional[str] = None) -> Dict[str, Any]:
        """Analyze text with Groq using high-security moderation policy."""
        text_value = self._sanitize_prompt_text((text or "").strip())
        caption_value = self._sanitize_prompt_text((caption or "").strip())
        combined_text = f"{text_value} {caption_value}".strip()

        if not combined_text:
            return self._safe_result("Safe content, bhai, chill")

        strict_result = self._rule_based_high_security_scan(combined_text)
        if strict_result is not None:
            return strict_result

        if text_value and not caption_value:
            hf_toxic_score = await hf_text_moderation(text_value)
            if hf_toxic_score is not None and hf_toxic_score > 0.85:
                return {
                    "is_safe": False,
                    "toxic_score": hf_toxic_score,
                    "illegal_score": 0.0,
                    "spam_score": 0.0,
                    "reason": "Bhai, toxic text detect hua",
                }

        if not self.groq_api_key:
            logger.error("Groq API key missing for text moderation")
            return self._safe_result("Safe content, bhai, chill")

        await self.initialize()
        
        system_prompt = (
            "ROLE: AIGovernor High-Security Sentinel. "
            "MISSION: Absolute group safety with zero false positives. "
            "STRICT DELETION RULES (is_safe: false): "
            "1) DRUGS: Flag ANY mention of narcotics (weed, ganja, charas, ice, pills, heroin). "
            "Even the single word 'drugs' = illegal_score 1.0. No context allowed. "
            "2) NSFW: Flag nudity, sexual slurs, pornographic imagery. "
            "3) SCAMS: Flag 'Double your crypto', fake giveaways, phishing QR codes. "
            "4) VIOLENCE: Flag graphic gore, weapons, direct death threats. "
            "SAFE LIST (is_safe: true): casual selfies, group photos, nature, food, cars, memes, anime, "
            "normal gaming screenshots, and medical discussion like 'I need a doctor'. "
            "OUTPUT FORMAT STRICT JSON ONLY: "
            "{\"is_safe\": bool, \"toxic_score\": float, \"illegal_score\": float, \"spam_score\": float, \"reason\": \"Short Hinglish reason\"}."
        )

        payload = {
            "model": self.groq_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Text: {text_value}\nCaption: {caption_value}"}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0
        }

        try:
            response = await self._http_client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.groq_api_key}"},
                json=payload
            )
            response.raise_for_status()
            data = response.json()
            content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "{}")
            parsed = self._parse_json_like_response(str(content))
            return self._normalize_text_response(parsed)
        except Exception as e:
            logger.error(f"Groq Request Error: {e}")
            fallback_result = self._rule_based_error_scan(combined_text)
            if fallback_result is not None:
                return fallback_result
            return {
                "is_safe": False,
                "toxic_score": 0.0,
                "illegal_score": 0.5,
                "spam_score": 0.0,
                "reason": "AI moderation error, message blocked for safety",
                "analysis_error": True,
            }

    async def analyze_image(self, image_bytes: bytes) -> Dict[str, Any]:
        """Analyze image with Gemini 1.5 Flash."""
        if not image_bytes or not self._gemini_client:
            return {"is_safe": False, "reason": "Gemini not ready"}

        image_format = imghdr.what(None, h=image_bytes)
        mime_type = f"image/{image_format}" if image_format else "image/jpeg"
        
        prompt = (
            "Return STRICT JSON ONLY: "
            "{\"is_safe\": bool, \"toxic_score\": float, \"illegal_score\": float, \"spam_score\": float, \"reason\": \"Short Hinglish reason\"}. "
            "Flag drugs/narcotics, NSFW nudity, scams/phishing QR and violence/weapons/gore."
        )

        model_name = await self._discover_gemini_model()
        if not model_name:
            return {"is_safe": False, "reason": "Gemini model unavailable", "analysis_error": True}

        def _call_gemini(selected_model: str):
            res = self._gemini_client.models.generate_content(
                model=selected_model,
                contents=[
                    {"inline_data": {"mime_type": mime_type, "data": image_bytes}},
                    prompt,
                ],
                config={"temperature": 0, "response_mime_type": "application/json"}
            )
            return json.loads(res.text)

        try:
            result = await asyncio.to_thread(_call_gemini, model_name)
            return self._normalize_image_response(result)
        except google_exceptions.NotFound:
            try:
                logger.warning("Retrying Gemini with explicit model path...")
                result = await asyncio.to_thread(_call_gemini, f"models/{model_name}")
                return self._normalize_image_response(result)
            except Exception:
                return {"is_safe": False, "reason": "Model 404", "analysis_error": True}
        except Exception as e:
            logger.error(f"Gemini Error: {e}")
            return {"is_safe": False, "reason": "Image analysis error", "analysis_error": True}

    async def analyze_sticker(self, sticker_bytes: bytes, is_animated: bool, set_name: str = None) -> Dict:
        if not self.gemini_api_key:
            return {"is_safe": True}

        await self.initialize()
        image_base64 = base64.b64encode(sticker_bytes).decode("utf-8")
        prompt = """Analyze sticker for: NSFW, violence, hate symbols, drugs, vulgar gestures.
Return JSON: {"is_safe": true/false, "reason": "brief"}"""
        try:
            result = await self._call_gemini_vision(image_base64, prompt, "image/webp")
            return self._normalize_image_response(result)
        except Exception as e:
            logger.error(f"Sticker analysis: {e}")
            return {"is_safe": True}

    async def analyze_animation(self, anim_bytes: bytes, mime_type: str, file_name: str = None) -> Dict:
        if not self.gemini_api_key:
            return {"is_safe": True}

        await self.initialize()
        image_base64 = base64.b64encode(anim_bytes).decode("utf-8")
        prompt = """Analyze GIF for: NSFW, violence, offensive gestures, flashing, hate symbols.
Return JSON: {"is_safe": true/false, "reason": "brief"}"""
        try:
            result = await self._call_gemini_vision(image_base64, prompt, mime_type or "image/gif")
            return self._normalize_image_response(result)
        except Exception as e:
            logger.error(f"Animation analysis: {e}")
            return {"is_safe": True}

    async def _call_gemini_vision(self, image_base64: str, prompt: str, mime_type: str) -> Dict:
        await self.initialize()
        api_version = await self._discover_gemini_api_version()
        model_name = await self._discover_gemini_model()
        model_path = model_name if model_name and model_name.startswith("models/") else f"models/{model_name or self.gemini_model_name}"
        url = f"https://generativelanguage.googleapis.com/{api_version}/{model_path}:generateContent"
        params = {"key": self.gemini_api_key}
        body = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime_type, "data": image_base64}}
                ]
            }],
            "generationConfig": {"temperature": 0}
        }
        response = await self._http_client.post(url, params=params, json=body)
        response.raise_for_status()
        payload = response.json()
        text = self._extract_gemini_text(payload)
        return self._parse_json_like_response(text)

    @staticmethod
    def _extract_gemini_text(payload: Dict[str, Any]) -> str:
        candidates = payload.get("candidates", [])
        if not candidates:
            return "{}"
        parts = (((candidates[0] or {}).get("content") or {}).get("parts") or [])
        for part in parts:
            if "text" in part:
                return str(part["text"])
        return "{}"

    @staticmethod
    def _parse_json_like_response(text: str) -> Dict[str, Any]:
        try:
            return json.loads(text)
        except Exception:
            cleaned = text.strip().removeprefix("```").removesuffix("```").strip()
            try:
                return json.loads(cleaned)
            except Exception:
                return {"is_safe": True, "reason": "Safe"}

    @staticmethod
    def _normalize_text_response(raw: Dict) -> Dict:
        def _score(value: Any) -> float:
            try:
                return max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                return 0.0

        return {
            "is_safe": bool(raw.get("is_safe", True)),
            "toxic_score": _score(raw.get("toxic_score", raw.get("toxicity_score", 0.0))),
            "illegal_score": _score(raw.get("illegal_score", 0.0)),
            "spam_score": _score(raw.get("spam_score", 0.0)),
            "reason": str(raw.get("reason", "Safe content, bhai, chill"))
        }

    @staticmethod
    def _safe_result(reason: str) -> Dict[str, Any]:
        return {
            "is_safe": True,
            "toxic_score": 0.0,
            "illegal_score": 0.0,
            "spam_score": 0.0,
            "reason": reason,
        }

    @staticmethod
    def _rule_based_high_security_scan(text: str) -> Optional[Dict[str, Any]]:
        lowered = text.lower()

        critical_patterns = {
            "Bhai, drugs ki baatein mana hain": r"\b(drugs?|ganja|weed|charas|heroin|mdma|meth|pills?)\b",
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
    def _rule_based_error_scan(text: str) -> Optional[Dict[str, Any]]:
        lowered = text.lower()
        patterns = {
            "Bhai, drugs ki baatein mana hain": r"\b(drugs?|ganja|weed|charas|heroin|mdma|meth|pills?)\b",
            "Bhai, ye content NSFW hain": r"\b(nsfw|porn|nude|sex|xxx|onlyfans)\b",
            "Bhai, ye scam ya fraud hain": r"\b(scam|fraud|phishing|crypto\s+qr|get\s+rich\s+quick|double\s+money)\b",
            "Bhai, ye bahut violent hain, mana hain": r"\b(kill|murder|behead|gore|shoot\s+him|death\s+threat)\b",
        }
        for reason, pattern in patterns.items():
            if re.search(pattern, lowered):
                return {
                    "is_safe": False,
                    "toxic_score": 0.8,
                    "illegal_score": 1.0,
                    "spam_score": 0.2,
                    "reason": reason,
                    "analysis_error": True,
                }
        return None

    @staticmethod
    def _normalize_image_response(raw: Dict) -> Dict:
        if not isinstance(raw, dict):
            return {"is_safe": True, "reason": "Safe"}
        return {"is_safe": bool(raw.get("is_safe", True)), "reason": str(raw.get("reason", "Safe"))}

moderation_service = ModerationService()
