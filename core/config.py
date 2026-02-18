from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import AliasChoices, Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(ValueError):
    """Raised when mandatory production configuration is invalid."""


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

    # ================= REQUIRED =================

    BOT_TOKEN: str = Field(min_length=30)

    FORCE_JOIN_CHANNEL: str = Field(
        min_length=2,
        validation_alias=AliasChoices("FORCE_JOIN_CHANNEL", "FORCE_CHANNEL_LINK")
    )

    FORCE_JOIN_CHANNEL_ID: int = Field(
        lt=0,
        validation_alias=AliasChoices("FORCE_JOIN_CHANNEL_ID", "FORCE_CHANNEL_ID")
    )

    LOG_GROUP_ID: int = Field(lt=0)

    CALLBACK_SECRET: str = Field(min_length=16)

    ADMIN_IDS: str = Field(min_length=1)

    # ================= OPTIONAL =================

    DATABASE_URL: str | None = None
    DATABASE_REQUIRED: bool = False

    WEBHOOK_URL: str = ""
    WEBHOOK_SECRET: str = ""

    REQUIRE_FORCE_JOIN: bool = True
    REQUIRE_CHANNEL_ADMIN: bool = True

    COOLDOWN_SECONDS: int = Field(default=8, ge=2, le=600)
    SPAM_WINDOW_SECONDS: int = Field(default=15, ge=5, le=120)
    SPAM_MAX_REQUESTS: int = Field(default=6, ge=2, le=50)

    CALLBACK_TTL_SECONDS: int = Field(default=600, ge=30, le=7200)
    CALLBACK_ALLOWED_ACTIONS: tuple[str, ...] = ("open_panel",)

    LOG_LEVEL: str = "INFO"

    # ==========================================================
    # ================== VALIDATORS ============================
    # ==========================================================

    @field_validator("FORCE_JOIN_CHANNEL", mode="before")
    @classmethod
    def normalize_channel_username(cls, value: Any) -> str:
        if not value:
            raise ConfigError("FORCE_JOIN_CHANNEL is required.")

        channel = str(value).strip()

        if channel.startswith("https://t.me/"):
            channel = channel.replace("https://t.me/", "")

        if channel.startswith("t.me/"):
            channel = channel.replace("t.me/", "")

        if not channel.startswith("@"):
            channel = f"@{channel}"

        if len(channel) < 2:
            raise ConfigError("Invalid FORCE_JOIN_CHANNEL username.")

        return channel

    @field_validator("FORCE_JOIN_CHANNEL_ID", "LOG_GROUP_ID", mode="before")
    @classmethod
    def validate_negative_ids(cls, value: Any, info) -> int:
        if value is None or value == "":
            raise ConfigError(f"{info.field_name} is required.")

        try:
            parsed = int(str(value).strip())
        except ValueError:
            raise ConfigError(f"{info.field_name} must be numeric (-100xxxx).")

        if parsed >= 0:
            raise ConfigError(f"{info.field_name} must be negative (-100xxxx).")

        return parsed

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: Any) -> str:
        if not value:
            raise ConfigError("ADMIN_IDS required.")

        raw = str(value).split(",")

        try:
            ids = sorted(set(int(x.strip()) for x in raw if x.strip()))
        except ValueError:
            raise ConfigError("ADMIN_IDS must contain only numeric Telegram user IDs.")

        if not ids:
            raise ConfigError("At least one ADMIN_ID required.")

        if any(i <= 0 for i in ids):
            raise ConfigError("ADMIN_IDS must be positive Telegram user IDs.")

        return ",".join(map(str, ids))

    @field_validator("WEBHOOK_URL")
    @classmethod
    def enforce_https(cls, value: str) -> str:
        if value and not value.startswith("https://"):
            raise ConfigError("WEBHOOK_URL must start with https://")
        return value

    @model_validator(mode="after")
    def cross_validation(self):
        if self.DATABASE_REQUIRED and not self.DATABASE_URL:
            raise ConfigError("DATABASE_URL required because DATABASE_REQUIRED=true")

        if self.REQUIRE_FORCE_JOIN:
            if not self.FORCE_JOIN_CHANNEL or not self.FORCE_JOIN_CHANNEL_ID:
                raise ConfigError("Force join enabled but channel config missing.")

        return self

    # ==========================================================
    # ================== HELPERS ===============================
    # ==========================================================

    @property
    def admin_ids_list(self) -> list[int]:
        return [int(x) for x in self.ADMIN_IDS.split(",")]

    @property
    def force_join_channel_link(self) -> str:
        return f"https://t.me/{self.FORCE_JOIN_CHANNEL.lstrip('@')}"

    def startup_report(self) -> dict[str, Any]:
        return {
            "bot_token_set": bool(self.BOT_TOKEN),
            "force_join_channel": self.FORCE_JOIN_CHANNEL,
            "force_join_channel_id": self.FORCE_JOIN_CHANNEL_ID,
            "log_group_id": self.LOG_GROUP_ID,
            "admin_ids_count": len(self.admin_ids_list),
            "database_required": self.DATABASE_REQUIRED,
            "database_url_set": bool(self.DATABASE_URL),
            "webhook_enabled": bool(self.WEBHOOK_URL),
            "callback_ttl": self.CALLBACK_TTL_SECONDS,
            "allowed_actions": list(self.CALLBACK_ALLOWED_ACTIONS),
        }


# ================= LOADER =================

def load_config() -> AppConfig:
    try:
        return AppConfig()
    except ValidationError as exc:
        raise ConfigError(f"Configuration validation failed:\n{exc}") from exc


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return load_config()
