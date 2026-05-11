"""Anonymous HTML scraping client for ``coretennis.net``.

CoreTennis is a third-party tennis-results aggregator with ~214k player
profiles and ~4.3M match records (per their own banner). For the Janav
use case it is the most useful source we can reach: it stores the
*outcome* of every USTA-sanctioned tournament match, including
opponents and scores, going back to 2018. CoreTennis is **not**
Cloudflare-fronted; anonymous httpx GETs work from any egress.

Coverage by page type:

================  ================================  ==================
Page              Path                              Returns
================  ================================  ==================
Profile           /tennis-player/<slug>/<id>/        Country, category
                  profile.html                      (e.g. "12 & under,
                                                    Boys"), summary
                                                    stats, latest
                                                    tournament.
Ranking           /tennis-player/<slug>/<id>/        ITF Junior or
                  ranking.html                      Pro rankings if
                                                    any.
Results           /tennis-player/<slug>/<id>/        Per-tournament
                  results.html                      list with date,
                                                    name, surface,
                                                    round, opponent,
                                                    score, W/L.
================  ================================  ==================

This client is read-only: it does not need or carry login state. To
discover a CoreTennis player id, search via the home page
(``/search.html?q=<name>``) — that's a separate concern not handled
here.

The cache envelope mirrors the TennisLink layout
(``data/raw/coretennis/<first-2-hex>/<sha256>.json``) so the reparse
CLI can inspect entries uniformly across sources.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import settings
from src.fetch.client import (
    REDACTED_HEADER_PREFIXES,
    REDACTED_HEADERS,
    REDACTED_PLACEHOLDER,
    BotChallengeError,
    TransientNetworkError,
)
from src.fetch.router import BlockedEgressError

__all__ = [
    "BASE_URL",
    "DEFAULT_USER_AGENT",
    "BlockedEgressError",
    "BotChallengeError",
    "CoreTennisClient",
    "TransientNetworkError",
    "compute_coretennis_cache_key",
]


logger = logging.getLogger(__name__)


BASE_URL = "https://www.coretennis.net"
ALLOWED_HOSTS: frozenset[str] = frozenset({"www.coretennis.net", "coretennis.net"})

# CoreTennis serves the same HTML to browsers and curl alike, but we
# present a browser UA out of politeness (and because the homepage
# inlines a JS that does an alert if the document.referrer mismatches —
# a no-op in our context but a tiny tell that the site cares about
# clients identifying themselves).
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_RETRIES = 4
DEFAULT_BACKOFF_BASE = 1.0
DEFAULT_BACKOFF_CAP = 16.0


class _TransientForRetryError(RuntimeError):
    """Internal marker exception driving tenacity retry."""


class CoreTennisClient:
    """Anonymous, rate-limited, retried client for ``coretennis.net``.

    Methods take a CoreTennis ``player_id`` (the integer in the path) and
    optionally a ``slug`` (the ``janav-thasen`` segment); we accept the
    combined string ``"slug/id"`` too. The CoreTennis path is
    forgiving: any slug that includes the id resolves to the same
    profile.
    """

    def __init__(
        self,
        raw_cache_dir: Path | None = None,
        interval_seconds: float | None = None,
        client: httpx.AsyncClient | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.raw_cache_dir: Path = (
            Path(raw_cache_dir) if raw_cache_dir is not None else settings.raw_cache_dir
        )
        self.interval_seconds: float = (
            interval_seconds
            if interval_seconds is not None
            else settings.request_interval_seconds
        )
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            follow_redirects=True,
        )
        self._owns_client: bool = client is None
        self._last_request_at: float | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> CoreTennisClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # -- public fetch surface ------------------------------------------------

    async def get_profile(self, player_id: str, slug: str = "player") -> str:
        return await self._get_player_page(player_id, slug, page="profile.html")

    async def get_ranking(self, player_id: str, slug: str = "player") -> str:
        return await self._get_player_page(player_id, slug, page="ranking.html")

    async def get_results(self, player_id: str, slug: str = "player") -> str:
        return await self._get_player_page(player_id, slug, page="results.html")

    # -- internals -----------------------------------------------------------

    async def _get_player_page(self, player_id: str, slug: str, *, page: str) -> str:
        pid = str(player_id).strip()
        if not pid.isdigit():
            raise ValueError(
                f"CoreTennisClient: player_id must be numeric; got {pid!r}"
            )
        slug = slug or "player"
        path = f"/tennis-player/{slug}/{pid}/{page}"
        return await self._fetch_with_retry(path)

    async def _fetch_with_retry(self, path: str) -> str:
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(DEFAULT_RETRIES),
                wait=wait_exponential(
                    multiplier=DEFAULT_BACKOFF_BASE,
                    max=DEFAULT_BACKOFF_CAP,
                ),
                retry=retry_if_exception_type(_TransientForRetryError),
                reraise=False,
            ):
                with attempt:
                    return await self._fetch_once(path)
        except RetryError as exc:
            inner = exc.last_attempt.exception() if exc.last_attempt else None
            raise TransientNetworkError(
                f"CoreTennis fetch failed after {DEFAULT_RETRIES} attempts: {inner!r}"
            ) from exc
        raise TransientNetworkError(  # pragma: no cover
            f"CoreTennis fetch produced no result for {path}"
        )

    async def _fetch_once(self, path: str) -> str:
        url = f"{BASE_URL}{path}"
        _check_allowed_host(url)
        await self._respect_rate_limit()
        try:
            response = await self._client.get(url)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise _TransientForRetryError(f"network error: {exc}") from exc

        status = response.status_code
        if status == 403:
            raise BlockedEgressError(f"CoreTennis returned 403 on {path}.")
        if status in (408, 429) or 500 <= status < 600:
            raise _TransientForRetryError(f"HTTP {status} on {path}")

        body = response.text
        try:
            self._write_cache(url, response, body)
        except OSError as exc:  # pragma: no cover - defensive
            logger.warning("CoreTennis cache write failed (%s); continuing.", exc)

        if status == 404:
            # Surface as TransientNetworkError so the caller distinguishes
            # missing-page from blocked / parse error.
            raise TransientNetworkError(f"CoreTennis returned 404 on {path}")
        if status >= 400:
            raise TransientNetworkError(f"CoreTennis returned {status} on {path}")
        return body

    async def _respect_rate_limit(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._last_request_at is not None:
                elapsed = now - self._last_request_at
                jitter = self.interval_seconds * 0.1
                target = self.interval_seconds + random.uniform(-jitter, jitter)
                wait = target - elapsed
                if wait > 0:
                    await asyncio.sleep(max(0.0, wait))
            self._last_request_at = time.monotonic()

    def _write_cache(
        self,
        url: str,
        response: httpx.Response,
        body: str,
    ) -> Path:
        digest = compute_coretennis_cache_key(url)
        target_dir = self.raw_cache_dir / "coretennis" / digest[:2]
        target_dir.mkdir(parents=True, exist_ok=True)
        cache_path = target_dir / f"{digest}.json"
        envelope: dict[str, Any] = {
            "fetched_at": datetime.now(UTC).isoformat(),
            "source": "coretennis",
            "request": {
                "method": "GET",
                "url": url,
                "params": None,
                "headers": _redact_headers(dict(response.request.headers)),
            },
            "response": {
                "status": response.status_code,
                "final_url": str(response.url),
                "headers": _redact_headers(dict(response.headers)),
                "body": body,
            },
        }
        with cache_path.open("w", encoding="utf-8") as fh:
            json.dump(envelope, fh, ensure_ascii=False, indent=2, default=str)
        return cache_path


def compute_coretennis_cache_key(absolute_url: str) -> str:
    return hashlib.sha256(absolute_url.encode("utf-8")).hexdigest()


def _check_allowed_host(url: str) -> None:
    host = urlparse(url).hostname or ""
    if host not in ALLOWED_HOSTS:
        raise ValueError(
            f"CoreTennisClient refuses to fetch host {host!r}; "
            f"allowed hosts: {sorted(ALLOWED_HOSTS)}"
        )


def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in headers.items():
        lower = key.lower()
        if lower in REDACTED_HEADERS or any(
            lower.startswith(prefix) for prefix in REDACTED_HEADER_PREFIXES
        ):
            out[key] = REDACTED_PLACEHOLDER
        else:
            out[key] = value
    return out
