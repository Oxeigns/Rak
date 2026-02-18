from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(ValueError):
    """Raised when mandatory production configuration is invalid."""


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', case_sensitive=True, extra='ignore')

    BOT_TOKEN: str = Field(min_length=30)
    FORCE_JOIN_CHANNEL: str = Field(min_length=2)
    FORCE_JOIN_CHANNEL_ID: int = Field(lt=0)
    CALLBACK_SECRET: str = Field(min_length=16)
    ADMIN_IDS: str = Field(min_length=1)

    DATABASE_URL: str | None = None
    DATABASE_REQUIRED: bool = False

    WEBHOOK_URL: str = ""
    WEBHOOK_SECRET: str = ""
    LOG_GROUP_ID: int = 0

    REQUIRE_FORCE_JOIN: bool = True
    REQUIRE_CHANNEL_ADMIN: bool = True

    COOLDOWN_SECONDS: int = Field(default=8, ge=2, le=600)
    SPAM_WINDOW_SECONDS: int = Field(default=15, ge=5, le=120)
    SPAM_MAX_REQUESTS: int = Field(default=6, ge=2, le=50)

    CALLBACK_TTL_SECONDS: int = Field(default=600, ge=30, le=7200)
    CALLBACK_ALLOWED_ACTIONS: tuple[str, ...] = ('open_panel',)

    LOG_LEVEL: str = 'INFO'

    @field_validator('FORCE_JOIN_CHANNEL', mode='before')
    @classmethod
    def normalize_channel_username(cls, value: Any) -> str:
        if value is None:
            raise ConfigError('FORCE_JOIN_CHANNEL is required and must be a Telegram channel username.')
        channel = str(value).strip()
        if not channel:
            raise ConfigError('FORCE_JOIN_CHANNEL is required and cannot be empty.')
        if channel.startswith('https://t.me/'):
            channel = channel.removeprefix('https://t.me/')
        if channel.startswith('t.me/'):
            channel = channel.removeprefix('t.me/')
        if not channel.startswith('@'):
            channel = f'@{channel}'
        if len(channel) < 2:
            raise ConfigError('FORCE_JOIN_CHANNEL must be a valid Telegram username (e.g., @my_channel).')
        return channel

    @field_validator('ADMIN_IDS', mode='before')
    @classmethod
    def parse_admin_ids(cls, value: Any) -> str:
        if value is None or value == '':
            raise ConfigError('ADMIN_IDS is required (comma separated IDs).')

        if isinstance(value, list):
            raw_items = [str(item).strip() for item in value if str(item).strip()]
        else:
            raw_items = [item.strip() for item in str(value).split(',') if item.strip()]

        try:
            parsed = [int(item) for item in raw_items]
        except ValueError as exc:
            raise ConfigError('ADMIN_IDS must contain only numeric Telegram user IDs.') from exc

        if not parsed:
            raise ConfigError('ADMIN_IDS must contain at least one Telegram user ID.')
        if any(item <= 0 for item in parsed):
            raise ConfigError('ADMIN_IDS values must be positive Telegram user IDs.')

        return ','.join(str(item) for item in sorted(set(parsed)))

    @field_validator('WEBHOOK_URL')
    @classmethod
    def webhook_url_requires_https(cls, value: str) -> str:
        if value and not value.startswith('https://'):
            raise ConfigError('WEBHOOK_URL must be https:// in production.')
        return value

    @model_validator(mode='after')
    def force_join_requirements(self) -> 'AppConfig':
        if self.REQUIRE_FORCE_JOIN and self.FORCE_JOIN_CHANNEL_ID >= 0:
            raise ConfigError('FORCE_JOIN_CHANNEL_ID must be a negative channel/supergroup ID (e.g., -1001234567890).')

        if self.DATABASE_REQUIRED and not self.DATABASE_URL:
            raise ConfigError('DATABASE_URL is required because DATABASE_REQUIRED=true.')
        return self

    @property
    def force_join_channel_link(self) -> str:
        return f'https://t.me/{self.FORCE_JOIN_CHANNEL.lstrip("@")}'

    @property
    def admin_ids_list(self) -> list[int]:
        return [int(item) for item in self.ADMIN_IDS.split(',') if item]

    def startup_report(self) -> dict[str, Any]:
        return {
            'bot_token_set': bool(self.BOT_TOKEN),
            'force_join_channel': self.FORCE_JOIN_CHANNEL,
            'force_join_channel_id': self.FORCE_JOIN_CHANNEL_ID,
            'callback_secret_set': bool(self.CALLBACK_SECRET),
            'admin_ids_count': len(self.admin_ids_list),
            'database_required': self.DATABASE_REQUIRED,
            'database_url_set': bool(self.DATABASE_URL),
            'webhook_enabled': bool(self.WEBHOOK_URL),
            'callback_ttl_seconds': self.CALLBACK_TTL_SECONDS,
            'allowed_actions': list(self.CALLBACK_ALLOWED_ACTIONS),
        }


def load_config() -> AppConfig:
    try:
        return AppConfig()
    except ValidationError as exc:
        missing = [
            '.'.join(str(part) for part in err.get('loc', []))
            for err in exc.errors()
            if err.get('type') == 'missing'
        ]
        if missing:
            missing_vars = ', '.join(missing)
            raise ConfigError(f'Missing required environment variables: {missing_vars}') from exc
        raise ConfigError(f'Configuration validation failed: {exc}') from exc


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return load_config()
