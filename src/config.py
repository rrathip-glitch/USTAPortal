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
    usta_source_preference: str = Field(
        default="",
        description=(
            "Comma-separated source preference for src.fetch.router.FetchRouter; "
            "empty falls back to the router's DEFAULT_SOURCE_PREFERENCE "
            "('usta_api,tennislink,clubspark'). See ADR-005."
        ),
    )
    # Anchor location for the anonymous USTA-API tournament discovery walk.
    # The API requires (d, lat, lon) so we keep a default that covers
    # Janav's home area (Florida) and is overridable per deploy.
    usta_anchor_lat: float = Field(default=27.6648)
    usta_anchor_lon: float = Field(default=-81.5158)
    usta_anchor_distance_miles: float = Field(default=50.0)
    usta_anchor_player_type: str = Field(
        default="Junior",
        description="USTA player type: 'Junior', 'Adult', or 'Wheelchair'.",
    )
    usta_discover_enabled: bool = Field(
        default=True,
        description=(
            "When true, ``usta sync`` walks the anonymous USTA Play Tennis "
            "API for nearby tournaments. Set to false in CI / hermetic "
            "tests to keep the orchestrator network-free."
        ),
    )
    coretennis_player_id: str = Field(
        default="",
        description=(
            "CoreTennis.net player id for the primary user. When set, "
            "``usta sync`` will pull the player's profile + results from "
            "CoreTennis and upsert their match history. Empty disables."
        ),
    )

    database_url: str = Field(default="sqlite:///./data/db/usta.db")
    raw_cache_dir: Path = Field(default=Path("./data/raw"))

    log_level: str = Field(default="INFO")
    request_interval_seconds: float = Field(default=2.0, ge=0.0)

    playwright_headless: bool = Field(default=True)

    port: int = Field(default=8000)
    environment: str = Field(default="development")


settings = Settings()
