import asyncio
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
        
        self.gemini_model_name = "gemini-1.5-flash" 
        self.timeout_seconds = float(self.settings.AI_TIMEOUT)

        self._http_client: Optional[httpx.AsyncClient] = None
        self.GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
        self._gemini_model = None
        self._gemini_client = None

        if self.gemini_api_key:
            try:
                self._gemini_client = genai.Client(api_key=self.gemini_api_key)
                self._gemini_model = self.gemini_model_name
                logger.info(f"Gemini service initialized: {self.gemini_model_name}")
            except Exception as e:
                logger.error(f"Gemini Init Failed: {e}")

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
            content = data["choices"][0]["message"]["content"]
            return self._normalize_text_response(json.loads(content))
        except Exception as e:
            logger.error(f"Groq Request Error: {e}")
            return self._safe_result("Safe content, bhai, chill")

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

        def _call_gemini(model_name: str):
            res = self._gemini_client.models.generate_content(
                model=model_name,
                contents=[
                    {"inline_data": {"mime_type": mime_type, "data": image_bytes}},
                    prompt,
                ],
                config={"temperature": 0, "response_mime_type": "application/json"}
            )
            return json.loads(res.text)

        try:
            result = await asyncio.to_thread(_call_gemini, self._gemini_model)
            return self._normalize_image_response(result)
        except google_exceptions.NotFound:
            try:
                logger.warning("Retrying Gemini with full path...")
                fallback_model = "models/gemini-1.5-flash"
                result = await asyncio.to_thread(_call_gemini, fallback_model)
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
        image_base64 = __import__("base64").b64encode(sticker_bytes).decode("utf-8")
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
        image_base64 = __import__("base64").b64encode(anim_bytes).decode("utf-8")
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
        url = f"{self.GEMINI_API_BASE}/models/gemini-1.5-flash:generateContent"
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
        return {
            "is_safe": bool(raw.get("is_safe", True)),
            "toxic_score": float(raw.get("toxic_score", raw.get("toxicity_score", 0.0))),
            "illegal_score": float(raw.get("illegal_score", 0.0)),
            "spam_score": float(raw.get("spam_score", 0.0)),
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
    def _normalize_image_response(raw: Dict) -> Dict:
        return {"is_safe": bool(raw.get("is_safe", True)), "reason": str(raw.get("reason", "Safe"))}

moderation_service = ModerationService()
