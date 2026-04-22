from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_RATE_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*s\s*$")


@dataclass(frozen=True)
class RateSpec:
    """Sliding-window rate spec: N requests per W seconds."""

    limit: int
    window_seconds: int

    @classmethod
    def parse(cls, raw: str) -> RateSpec:
        m = _RATE_RE.match(raw)
        if not m:
            raise ValueError(f"Invalid rate spec {raw!r}; expected '<N>/<W>s'")
        return cls(limit=int(m.group(1)), window_seconds=int(m.group(2)))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    BRIDGE_TOKEN: str
    HERMES_API_KEY: str
    HERMES_CHAT_URL: str = "http://hermes:8642"
    HERMES_DASH_URL: str = "http://hermes:9119"
    HERMES_HOME: str = "/opt/data"
    BRIDGE_HOST: str = "0.0.0.0"
    BRIDGE_PORT: int = 8080
    BRIDGE_LOG_LEVEL: str = "INFO"
    BRIDGE_AUDIT_LOG_PATH: str = "/opt/data/logs/bridge_audit.log"
    BRIDGE_RATE_WRITE: str = "30/10s"
    BRIDGE_RATE_READ: str = "300/10s"
    HERMES_CONTAINER_NAME: str = "hermes"

    @field_validator("BRIDGE_TOKEN", "HERMES_API_KEY")
    @classmethod
    def _min_length(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("must be at least 32 characters")
        return v

    @field_validator("BRIDGE_RATE_WRITE", "BRIDGE_RATE_READ")
    @classmethod
    def _rate_shape(cls, v: str) -> str:
        RateSpec.parse(v)
        return v

    @property
    def write_rate(self) -> RateSpec:
        return RateSpec.parse(self.BRIDGE_RATE_WRITE)

    @property
    def read_rate(self) -> RateSpec:
        return RateSpec.parse(self.BRIDGE_RATE_READ)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings


def reset_settings_for_tests() -> None:
    global _settings
    _settings = None
