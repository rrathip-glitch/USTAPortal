"""Centralized settings loaded from environment variables.

All other modules import `settings` from here. Do not read os.environ directly
elsewhere — when tests need to override config, they patch this module.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    usta_username: str = Field(default="", description="USTA login username/email.")
    usta_password: str = Field(default="", description="USTA login password.")
    usta_user_player_id: str = Field(
        default="",
        description="The primary user's USTA player ID. Captured during recon.",
    )

    database_url: str = Field(default="sqlite:///./data/db/usta.db")
    raw_cache_dir: Path = Field(default=Path("./data/raw"))

    log_level: str = Field(default="INFO")
    request_interval_seconds: float = Field(default=2.0, ge=0.0)

    playwright_headless: bool = Field(default=True)

    port: int = Field(default=8000)
    environment: str = Field(default="development")


settings = Settings()
