import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx
from config.settings import get_settings

logger = logging.getLogger(__name__)

class AIModerationService:
    """Groq-powered moderation service with in-memory LRU cache."""

    REQUIRED_RESPONSE_KEYS = {
        "is_safe",
        "spam_score",
        "toxicity_score",
        "illegal_score",
        "reason",
    }

    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.GROQ_API_KEY
        # 'llama-3.3-70b-versatile' best hai, isse change na karein
        self.model = "llama-3.3-70b-versatile"
        self.client: Optional[httpx.AsyncClient] = None
        self._cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._cache_lock = asyncio.Lock()

    async def initialize(self):
        if self.client is None:
            # Timeout settings ko environment variable se utha raha hai
            self.client = httpx.AsyncClient(timeout=float(self.settings.AI_TIMEOUT))

    async def cleanup(self):
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    async def analyze_message(
        self,
        text: str,
        context: Optional[Dict[str, Any]] = None,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """Analyze message text and return normalized JSON moderation output."""
        if not text or len(text.strip()) < 2:
            return self._empty_result()

        cache_key = self._generate_cache_key(text)
        if use_cache:
            cached = await self._get_cache(cache_key)
            if cached:
                logger.debug("AI cache hit: %s", cache_key[:12])
                return cached

        if not self.api_key:
            logger.error("GROQ_API_KEY not found in settings!")
            return self._fallback_analysis(text)

        await self.initialize()
        start_time = time.time()
        
        # Prompt ko strict rakha hai taaki hamesha JSON mile
        prompt = (
            "Analyze this Telegram message for safety. "
            "Return ONLY a valid JSON object in this format: "
            '{"is_safe": bool, "spam_score": float, "toxicity_score": float, '
            '"illegal_score": float, "reason": "string"}. '
            f"Message: {text!r}"
        )

        try:
            # FIX: Ensure URL is clean and headers are correct
            response = await self.client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.0, # 0.0 for consistent results
                },
            )
            response.raise_for_status()

            data = response.json()
            content = data["choices"][0]["message"]["content"]
            result_json = json.loads(content)
            
            normalized = self._normalize_result(result_json)
            normalized["processing_time_ms"] = (time.time() - start_time) * 1000

            if use_cache:
                await self._set_cache(cache_key, normalized)
            
            return normalized

        except Exception as e:
            logger.error(f"Groq API Error: {e}")
            return self._fallback_analysis(text)



    @staticmethod
    def _to_bool(value: Any, default: bool = True) -> bool:
        """Safely coerce model booleans, preserving explicit false values."""
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"false", "0", "no", "n", "unsafe"}:
                return False
            if normalized in {"true", "1", "yes", "y", "safe"}:
                return True
        return default

    def _normalize_result(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Ensures all keys are present and scores are between 0 and 1."""
        normalized = {
            "is_safe": self._to_bool(raw.get("is_safe"), default=True),
            "spam_score": float(raw.get("spam_score", 0.0)),
            "toxicity_score": float(raw.get("toxicity_score", 0.0)),
            "illegal_score": float(raw.get("illegal_score", 0.0)),
            "reason": str(raw.get("reason", "No reason")),
        }
        for key in ("spam_score", "toxicity_score", "illegal_score"):
            normalized[key] = max(0.0, min(1.0, normalized[key]))
        return normalized

    def _fallback_analysis(self, text: str) -> Dict[str, Any]:
        return {
            "is_safe": True,
            "spam_score": 0.0,
            "toxicity_score": 0.0,
            "illegal_score": 0.0,
            "reason": "Fallback: Service unavailable",
            "processing_time_ms": 0.0,
        }

    def _empty_result(self) -> Dict[str, Any]:
        return {
            "is_safe": True,
            "spam_score": 0.0,
            "toxicity_score": 0.0,
            "illegal_score": 0.0,
            "reason": "Short message",
            "processing_time_ms": 0.0,
        }

    def _generate_cache_key(self, text: str) -> str:
        return hashlib.sha256(text.lower().strip().encode()).hexdigest()

    async def _get_cache(self, key: str):
        async with self._cache_lock:
            cached = self._cache.get(key)
            if not cached:
                return None
            # Modern UTC check
            if cached.get("expires_at") <= datetime.now(timezone.utc):
                self._cache.pop(key, None)
                return None
            self._cache.move_to_end(key)
            return cached.get("data")

    async def _set_cache(self, key: str, data: Dict[str, Any]):
        async with self._cache_lock:
            self._cache[key] = {
                "data": data, 
                "expires_at": datetime.now(timezone.utc) + timedelta(hours=24)
            }
            self._cache.move_to_end(key)
            # LRU Cache Cleanup
            maxsize = int(self.settings.AI_MODERATION_CACHE_MAXSIZE or 100)
            while len(self._cache) > maxsize:
                self._cache.popitem(last=False)

ai_moderation_service = AIModerationService()
