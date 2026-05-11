"""Anonymous client for the public UTR player-search API.

UTR's web app at ``https://app.utrsports.net`` talks to a JSON API at
``https://api.utrsports.net``. The player-search endpoint
(``/v2/search/players``) is **anonymous** — no auth token required — which
makes it a viable cross-reference source for matching a USTA player to their
UTR profile (and surfacing their singles / doubles UTR on the dashboard).

The deep-detail endpoints (``/v2/players/<id>``, match history, results) all
return ``400 Token is missing`` without an auth token; they are intentionally
**not** implemented here. The router protocol's ``get_player`` is left
unimplemented for the same reason.

Cache layout mirrors :mod:`src.fetch.usta_api_client`:
``<raw_cache_dir>/utr/<first-2-hex>/<sha256>.json`` with a request /
response envelope. The cache key is a SHA-256 of the absolute URL — for
this single-endpoint client the URL fully captures the request (the query
and ``top`` are both in the query string).

For full request / response shape and the discovery transcript see
``RECON.md`` (UTR section).
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
    "PATH_SEARCH_PLAYERS",
    "BlockedEgressError",
    "BotChallengeError",
    "TransientNetworkError",
    "UTRClient",
    "compute_utr_cache_key",
]


logger = logging.getLogger(__name__)


BASE_URL = "https://api.utrsports.net"
APP_ORIGIN = "https://app.utrsports.net"

PATH_SEARCH_PLAYERS = "/v2/search/players"

ALLOWED_HOSTS: frozenset[str] = frozenset({"api.utrsports.net"})

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_RETRIES = 4
DEFAULT_BACKOFF_BASE = 1.0
DEFAULT_BACKOFF_CAP = 16.0

# UTR's search endpoint accepts ``top`` in 1..50; the web app caps it at 50.
MIN_TOP = 1
MAX_TOP = 50


class _TransientForRetryError(RuntimeError):
    """Internal marker for tenacity retries; not exported."""


class UTRClient:
    """Anonymous, rate-limited, retried client for the UTR search API.

    The single public method, :meth:`search_players`, conforms loosely to
    the same shape as :class:`src.fetch.usta_api_client.UstaApiClient` so a
    future router can dispatch through it. Endpoints that require auth
    (player detail, match history, etc.) are intentionally absent — the
    router will fall through to another source for those needs.
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
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": APP_ORIGIN,
                "Referer": f"{APP_ORIGIN}/",
            },
            follow_redirects=False,
        )
        self._owns_client: bool = client is None

        self._last_request_at: float | None = None
        self._lock = asyncio.Lock()

    # -- async context management ---------------------------------------------

    async def __aenter__(self) -> UTRClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # -- public fetch surface -------------------------------------------------

    async def search_players(self, query: str, top: int = 10) -> dict[str, Any]:
        """Issue a player search and return the parsed JSON envelope.

        ``query`` is a free-text name (or fragment) — UTR's search uses an
        ElasticSearch-backed fuzzy match across first / last / display name.
        ``top`` is the maximum number of hits requested; UTR clamps it to
        ``[1, 50]``.

        Returns the envelope verbatim:

            {"hits": [{"id": "...", "source": {...}}, ...],
             "total": N, "totalAllowed": N, "maxScore": 0.0,
             "aggregations": {}}
        """
        if not query or not query.strip():
            raise ValueError("UTRClient.search_players: query must be non-empty.")
        if not (MIN_TOP <= top <= MAX_TOP):
            raise ValueError(
                f"UTRClient.search_players: top must be in [{MIN_TOP}, {MAX_TOP}]; "
                f"got {top!r}."
            )

        params = {"query": query, "top": str(top)}
        return await self._get(PATH_SEARCH_PLAYERS, params=params)

    # ---------- router protocol surface (delegates / not-implemented) --------

    async def get_player(self, player_id: str) -> dict[str, Any]:
        """Per-player detail is gated behind a UTR auth token; fall through."""
        raise NotImplementedError(
            "UTRClient: per-player detail endpoints require a UTR auth token; "
            "the router should fall through to another source."
        )

    # -- internals ------------------------------------------------------------

    async def _get(
        self,
        path: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Token-bucketed, retried, cached GET. Returns parsed JSON."""
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
                    return await self._get_once(path, params)
        except RetryError as exc:
            inner = exc.last_attempt.exception() if exc.last_attempt else None
            raise TransientNetworkError(
                f"UTR GET {path} failed after {DEFAULT_RETRIES} attempts: {inner!r}"
            ) from exc
        # Unreachable; mypy reassurance.
        raise TransientNetworkError(  # pragma: no cover
            f"UTR GET {path} produced no result"
        )

    async def _get_once(
        self,
        path: str,
        params: dict[str, str] | None,
    ) -> dict[str, Any]:
        url = f"{BASE_URL}{path}"
        _check_allowed_host(url)
        await self._respect_rate_limit()
        try:
            response = await self._client.get(url, params=params)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise _TransientForRetryError(f"network error: {exc}") from exc

        status = response.status_code

        if status == 403:
            try:
                self._write_cache(url, params, response)
            except OSError:
                pass
            raise BlockedEgressError(
                f"UTR returned 403 on {path}; the endpoint may now require auth "
                "or our IP/ASN is blocked."
            )

        if status in (408, 429) or 500 <= status < 600:
            raise _TransientForRetryError(f"HTTP {status} on {path}")

        try:
            self._write_cache(url, params, response)
        except OSError as exc:  # pragma: no cover - defensive
            logger.warning("UTRClient cache write failed (%s); continuing.", exc)

        if status >= 400:
            raise TransientNetworkError(
                f"UTR returned {status} on {path}: {response.text[:200]!r}"
            )

        try:
            data: Any = response.json()
        except ValueError as exc:
            raise TransientNetworkError(
                f"UTR returned non-JSON body on {path}: {response.text[:200]!r}"
            ) from exc
        if not isinstance(data, dict):
            raise TransientNetworkError(
                f"UTR returned non-object JSON on {path}: {type(data).__name__}"
            )
        return data

    async def _respect_rate_limit(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._last_request_at is not None:
                elapsed = now - self._last_request_at
                jitter = self.interval_seconds * 0.1
                target = self.interval_seconds + random.uniform(-jitter, jitter)
                wait = target - elapsed
                if wait > 0:
                    await self._sleep(wait)
            self._last_request_at = time.monotonic()

    @staticmethod
    async def _sleep(seconds: float) -> None:
        await asyncio.sleep(max(0.0, seconds))

    def _write_cache(
        self,
        url: str,
        params: dict[str, str] | None,
        response: httpx.Response,
    ) -> Path:
        digest = compute_utr_cache_key(url, params)
        target_dir = self.raw_cache_dir / "utr" / digest[:2]
        target_dir.mkdir(parents=True, exist_ok=True)
        cache_path = target_dir / f"{digest}.json"

        try:
            body: Any = response.json()
        except ValueError:
            body = response.text

        envelope: dict[str, Any] = {
            "fetched_at": datetime.now(UTC).isoformat(),
            "source": "utr",
            "request": {
                "method": "GET",
                "url": url,
                "params": params,
                "body": None,
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


# -----------------------------------------------------------------------------
# Module-level helpers (exported for tests + parsers)
# -----------------------------------------------------------------------------


def compute_utr_cache_key(
    absolute_url: str,
    params: dict[str, str] | None,
) -> str:
    """Stable SHA-256 over (absolute URL, sorted params)."""
    norm = json.dumps(params or {}, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(f"{absolute_url}|{norm}".encode()).hexdigest()


def _check_allowed_host(url: str) -> None:
    host = urlparse(url).hostname or ""
    if host not in ALLOWED_HOSTS:
        raise ValueError(
            f"UTRClient refuses to fetch host {host!r}; "
            f"allowed: {sorted(ALLOWED_HOSTS)}"
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
