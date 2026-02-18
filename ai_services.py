"""Centralized AI service bindings with safe fallbacks.

Use this module for importing AI services in bot handlers so runtime import
errors (missing optional SDKs, bad env, etc.) do not break the whole bot.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class _SafeModerationService:
    """Fallback moderation service used when ai_service import fails."""

    async def analyze_text(self, text: str, caption: Optional[str] = None) -> Dict[str, Any]:
        return {
            "is_safe": True,
            "toxic_score": 0.0,
            "illegal_score": 0.0,
            "spam_score": 0.0,
            "reason": "Fallback: text moderation unavailable",
        }

    async def analyze_image(self, image_bytes: bytes) -> Dict[str, Any]:
        return {"is_safe": True, "reason": "Fallback: image moderation unavailable"}

    async def analyze_sticker(self, sticker_bytes: bytes, is_animated: bool, set_name: str = None) -> Dict[str, Any]:
        return {"is_safe": True, "reason": "Fallback: sticker moderation unavailable"}

    async def analyze_animation(self, anim_bytes: bytes, mime_type: str, file_name: str = None) -> Dict[str, Any]:
        return {"is_safe": True, "reason": "Fallback: animation moderation unavailable"}


class _SafeAIModerationService:
    """Fallback ai_moderation service used when ai_moderation import fails."""

    async def analyze_message(self, text: str, context: Optional[Dict[str, Any]] = None, use_cache: bool = True) -> Dict[str, Any]:
        return {
            "is_safe": True,
            "spam_score": 0.0,
            "toxicity_score": 0.0,
            "illegal_score": 0.0,
            "reason": "Fallback: AI moderation unavailable",
            "processing_time_ms": 0.0,
        }


try:
    from ai_service import moderation_service as _moderation_service
except Exception as exc:  # noqa: BLE001 - prevent bot boot failure
    logger.exception("Failed to import moderation_service from ai_service: %s", exc)
    moderation_service = _SafeModerationService()
else:
    moderation_service = _moderation_service


try:
    from ai_moderation import ai_moderation_service as _ai_moderation_service
except Exception as exc:  # noqa: BLE001 - prevent bot boot failure
    logger.exception("Failed to import ai_moderation_service from ai_moderation: %s", exc)
    ai_moderation_service = _SafeAIModerationService()
else:
    ai_moderation_service = _ai_moderation_service


__all__ = ["moderation_service", "ai_moderation_service"]
