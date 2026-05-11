"""Centralized settings loaded from environment variables.

All other modules import `settings` from here. Do not read os.environ directly
elsewhere — when tests need to override config, they patch this module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
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
            "('tennislink,clubspark'). See ADR-005."
        ),
    )

    database_url: str = Field(default="sqlite:///./data/db/usta.db")
    raw_cache_dir: Path = Field(default=Path("./data/raw"))

    log_level: str = Field(default="INFO")
    request_interval_seconds: float = Field(default=2.0, ge=0.0)

    playwright_headless: bool = Field(default=True)

    port: int = Field(default=8000)
    environment: str = Field(default="development")

    resend_api_key: SecretStr | None = Field(default=None)
    notify_from: str = Field(default="noreply@example.com")
    notify_to: str | None = Field(default=None)

    # -----------------------------------------------------------------------
    # Residential-proxy provider for Clubspark egress.
    #
    # The Clubspark surface is IP/ASN-blocked from this environment (see
    # ADR-001). To reach it the caller routes via a residential-proxy
    # service. Only ONE provider's credentials should be supplied at a
    # time — the factory picks based on ``residential_proxy_provider``.
    # -----------------------------------------------------------------------
    residential_proxy_provider: Literal["brightdata", "scrapfly"] | None = Field(
        default=None,
        description=(
            "Which residential-proxy provider to use for Clubspark fetches. "
            "Set to 'brightdata' (primary) or 'scrapfly' (fallback). Leave "
            "unset to disable residential-proxy fetches entirely."
        ),
    )
    bright_data_api_key: SecretStr | None = Field(
        default=None,
        description=(
            "Bright Data API token (REST-mode Bearer auth). Sent as the "
            "``Authorization: Bearer <token>`` header on every "
            "``POST https://api.brightdata.com/request`` call. See "
            "data/reference/known_urls.md (Bright Data Web Unlocker — "
            "verified API shape) for the verified payload shape."
        ),
    )
    bright_data_zone: str = Field(
        default="web_unlocker1",
        description=(
            "Bright Data Web Unlocker zone name. Sent as the ``zone`` field "
            "in the JSON payload. Defaults to 'web_unlocker1' which matches "
            "the trial-account zone."
        ),
    )
    scrapfly_api_key: SecretStr | None = Field(
        default=None,
        description="ScrapFly API key — the 'key' query parameter on every request.",
    )


settings = Settings()
