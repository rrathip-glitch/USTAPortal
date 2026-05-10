"""Rate-limited fetch layer.

Wraps the auth session with politeness controls (token bucket, jitter, retry
with exponential backoff on transient errors, Retry-After honoring) and writes
every successful response into the raw cache before returning it to callers.

Recon-dependent decisions still pending:

- Whether httpx alone suffices for data fetches (Strategy A in ADR-001) or
  whether Playwright contexts must drive the actual fetches (Strategy B/C).
- Concurrency model — for a single user the volume is small enough that
  serial fetches with 2-second intervals are fine, but if recon shows the
  SPA fans out 6+ XHRs per page render we may need to mirror that pattern.
"""

from __future__ import annotations

from pathlib import Path

from src.config import settings


class RateLimitedError(RuntimeError):
    """Raised when the server signals rate limiting (429 or equivalent)."""


class TransientNetworkError(RuntimeError):
    """Raised on connect/read timeouts and 5xx responses worth retrying."""


class FetchClient:
    """Stub. Real implementation lands after recon."""

    def __init__(self, raw_cache_dir: Path | None = None) -> None:
        self.raw_cache_dir = raw_cache_dir or settings.raw_cache_dir

    async def get(self, url: str, **_kwargs: object) -> object:
        raise NotImplementedError("Pending recon — see SPEC.md Section 4.")

    async def close(self) -> None:
        return None
