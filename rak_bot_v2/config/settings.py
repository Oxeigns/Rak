"""Environment-backed settings."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(alias="BOT_TOKEN", min_length=10)
    owner_id: int = Field(alias="OWNER_ID")
    log_group_id: int = Field(alias="LOG_GROUP_ID")
    force_channel_id: int = Field(alias="FORCE_CHANNEL_ID")
    force_channel_link: HttpUrl = Field(alias="FORCE_CHANNEL_LINK")
    groq_api_key: str = Field(alias="GROQ_API_KEY", min_length=10)
    gemini_api_key: str = Field(alias="GEMINI_API_KEY", min_length=10)
    port: int = Field(alias="PORT", default=8000, ge=1, le=65535)
    database_path: str = Field(default_factory=lambda: os.getenv("DATABASE_PATH", "/tmp/runtime_state.db"))


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance - validates on first call."""
    return Settings()


settings = get_settings()
