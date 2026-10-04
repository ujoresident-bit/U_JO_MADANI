"""Configuration loaded from environment variables.

On Render: set the variables in the service's "Environment" tab.
Locally:   copy .env.example to .env and fill it in (.env is git-ignored).
Secrets are never printed: they are excluded from the dataclass repr.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

try:  # python-dotenv is only needed for local development
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


class ConfigError(RuntimeError):
    """Raised when a required environment variable is missing."""


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str = field(repr=False)
    supabase_url: str
    supabase_key: str = field(repr=False)
    log_level: str = "INFO"


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def load_config() -> Config:
    return Config(
        telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
        supabase_url=_require("SUPABASE_URL"),
        supabase_key=_require("SUPABASE_KEY"),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
    )
