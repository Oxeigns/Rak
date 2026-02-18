"""
AI Governor Bot - Enterprise Configuration
Clean Version: Removed hardcoded secrets for security.
"""

import os
from typing import List, Dict, Any
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Enterprise-grade configuration with Environment Variable priority."""
    
    # Bot Identity
    BOT_NAME: str = "AI Governor"
    BOT_VERSION: str = "2.2.1"
    BOT_DESCRIPTION: str = "Revolutionary AI-Powered Group Governance"
    
    # Telegram Configuration
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    API_ID: int = int(os.getenv("API_ID", "0"))
    API_HASH: str = os.getenv("API_HASH", "")
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")
    PORT: int = int(os.getenv("PORT", "8000"))

    # Force-join configuration
    FORCE_JOIN_CHANNEL_ID: int = int(os.getenv("FORCE_JOIN_CHANNEL_ID", "-1002574289485"))
    FORCE_JOIN_CHANNEL_LINK: str = os.getenv("FORCE_JOIN_CHANNEL_LINK", "https://t.me/aghoris")
    
    # AI API Configuration (PROPER SECURE LOADING)
    # No hardcoded keys here. Set GROQ_API_KEY in Heroku/Settings.
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    HUGGINGFACE_TOKEN: str = os.getenv("HUGGINGFACE_TOKEN", "")

    # Model Configuration
    GROQ_TEXT_MODERATION_MODEL: str = "llama-3.3-70b-versatile"
    GEMINI_IMAGE_MODERATION_MODEL: str = "gemini-1.5-flash"

    # Backward-compatible model aliases
    AI_MODEL_PRIMARY: str = "llama-3.3-70b-versatile" 
    AI_MODEL_FALLBACK: str = "llama-3.1-8b-instant"
    
    AI_TEMPERATURE: float = 0.1
    AI_MAX_TOKENS: int = 256  
    AI_TIMEOUT: int = 15      
    
    # Database Configuration
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost/governor")
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    
    # Redis Configuration
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    REDIS_POOL_SIZE: int = 10
    
    # Risk Scoring Weights
    RISK_WEIGHT_SPAM: float = 0.18
    RISK_WEIGHT_TOXIC: float = 0.14
    RISK_WEIGHT_SCAM: float = 0.16
    RISK_WEIGHT_ILLEGAL: float = 0.18
    RISK_WEIGHT_PHISHING: float = 0.14
    RISK_WEIGHT_NSFW: float = 0.12
    RISK_WEIGHT_FLOOD: float = 0.10
    RISK_WEIGHT_USER_HISTORY: float = 0.10
    RISK_WEIGHT_SIMILARITY: float = 0.08
    RISK_WEIGHT_LINK_SUSPICIOUS: float = 0.10
    
    # Risk Thresholds
    RISK_THRESHOLD_CRITICAL: int = 85
    RISK_THRESHOLD_HIGH: int = 70
    RISK_THRESHOLD_MEDIUM: int = 50
    
    # Trust Score Configuration
    TRUST_INITIAL: int = 50
    TRUST_MAX: int = 100
    TRUST_MIN: int = 0
    TRUST_BONUS_POSITIVE: float = 0.8
    TRUST_PENALTY_VIOLATION: int = 5
    TRUST_PENALTY_MUTE: int = 8
    TRUST_PENALTY_BAN: int = 15
    TRUST_AUTO_RESTRICT_MEDIA: int = 25
    TRUST_AUTO_BAN: int = 10
    
    # Anti-Raid Configuration
    RAID_JOIN_THRESHOLD: int = 10
    RAID_TIME_WINDOW: int = 30
    RAID_NEW_ACCOUNT_DAYS: int = 7
    RAID_SIMILARITY_THRESHOLD: float = 0.7
    
    # Engagement Engine
    ENGAGEMENT_DAILY_QUESTION_HOUR: int = 10
    ENGAGEMENT_WEEKLY_POLL_DAY: int = 6 
    ENGAGEMENT_INACTIVE_DAYS: int = 7
    ENGAGEMENT_LEADERBOARD_SIZE: int = 10
    
    # Media Processing
    MEDIA_MAX_SIZE_MB: int = 20
    MEDIA_NSFW_THRESHOLD: float = 0.7
    MEDIA_VIOLENCE_THRESHOLD: float = 0.6
    MEDIA_SCAN_INTERVAL: int = 3
    
    # Personality Modes
    PERSONALITY_MODES: List[str] = ["friendly", "strict", "corporate", "funny", "owner"]
    DEFAULT_PERSONALITY: str = "friendly"
    
    # Supported Languages
    SUPPORTED_LANGUAGES: List[str] = ["en", "hi", "hinglish"]
    DEFAULT_LANGUAGE: str = "en"
    
    # Logging & Monitoring
    LOG_LEVEL: str = "INFO"
    SENTRY_DSN: str = os.getenv("SENTRY_DSN", "")
    METRICS_ENABLED: bool = True
    
    # Rate Limiting
    RATE_LIMIT_AI_CALLS: int = 100
    RATE_LIMIT_DB_QUERIES: int = 1000
    RATE_LIMIT_TELEGRAM_API: int = 30

    # Safety and cache limits
    AI_MODERATION_CACHE_MAXSIZE: int = int(os.getenv("AI_MODERATION_CACHE_MAXSIZE", "2000"))
    BUTTON_CLICK_RATE_LIMIT_WINDOW_SECONDS: int = int(os.getenv("BUTTON_CLICK_RATE_LIMIT_WINDOW_SECONDS", "2"))
    BUTTON_CLICK_RATE_LIMIT_MAX: int = int(os.getenv("BUTTON_CLICK_RATE_LIMIT_MAX", "8"))
    IMAGE_MAX_BYTES: int = int(os.getenv("IMAGE_MAX_BYTES", str(20 * 1024 * 1024)))
    
    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Optimized global access for Risk Weights
_settings = get_settings()
RISK_WEIGHTS = {
    "spam": _settings.RISK_WEIGHT_SPAM,
    "toxic": _settings.RISK_WEIGHT_TOXIC,
    "scam": _settings.RISK_WEIGHT_SCAM,
    "illegal": _settings.RISK_WEIGHT_ILLEGAL,
    "phishing": _settings.RISK_WEIGHT_PHISHING,
    "nsfw": _settings.RISK_WEIGHT_NSFW,
    "flood": _settings.RISK_WEIGHT_FLOOD,
    "user_history": _settings.RISK_WEIGHT_USER_HISTORY,
    "similarity": _settings.RISK_WEIGHT_SIMILARITY,
    "link_suspicious": _settings.RISK_WEIGHT_LINK_SUSPICIOUS,
}
