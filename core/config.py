from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(ValueError):
    """Raised when mandatory production configuration is invalid."""


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', case_sensitive=True, extra='ignore')

    BOT_TOKEN: str = Field(min_length=30)
    WEBHOOK_URL: str = ""
    WEBHOOK_SECRET: str = ""

    FORCE_JOIN_CHANNEL_ID: int = 0
    FORCE_JOIN_CHANNEL_LINK: str = ""
    LOG_GROUP_ID: int = 0

    REQUIRE_FORCE_JOIN: bool = True
    REQUIRE_CHANNEL_ADMIN: bool = True

    COOLDOWN_SECONDS: int = Field(default=8, ge=2, le=600)
    SPAM_WINDOW_SECONDS: int = Field(default=15, ge=5, le=120)
    SPAM_MAX_REQUESTS: int = Field(default=6, ge=2, le=50)

    CALLBACK_SECRET: str = Field(min_length=16)
    CALLBACK_TTL_SECONDS: int = Field(default=600, ge=30, le=7200)

    LOG_LEVEL: str = "INFO"

    @field_validator('WEBHOOK_URL')
    @classmethod
    def webhook_url_requires_https(cls, value: str) -> str:
        if value and not value.startswith('https://'):
            raise ConfigError('WEBHOOK_URL must be https:// in production.')
        return value

    @model_validator(mode='after')
    def force_join_requirements(self) -> 'AppConfig':
        if self.REQUIRE_FORCE_JOIN:
            if self.FORCE_JOIN_CHANNEL_ID == 0:
                raise ConfigError('FORCE_JOIN_CHANNEL_ID is required when REQUIRE_FORCE_JOIN=true.')
            if not self.FORCE_JOIN_CHANNEL_LINK:
                raise ConfigError('FORCE_JOIN_CHANNEL_LINK is required when REQUIRE_FORCE_JOIN=true.')
        return self


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return AppConfig()
