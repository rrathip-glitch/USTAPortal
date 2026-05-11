"""Anonymous client for the production USTA Play Tennis API.

This is the third — and **primary, current** — data source after the
2026-05-11 brute-force recon discovery that the AEM-rendered National
Search frontend (``playerapp.usta.com``) talks to an *unauthenticated*
AWS API Gateway at ``https://prod-api-playtennis.usta.com``.

What changes vs. the prior `tennislink` / `clubspark` shape:

- **No auth.** The endpoints we use are the same anonymous endpoints the
  public search page calls. No Auth0 dance, no Cloudflare interstitial
  to wrestle, no IP/ASN issue. The API Gateway's CORS allows-all and
  there is no rate limit beyond standard throttling.
- **JSON, not HTML.** Responses are ElasticSearch envelopes
  (``{"hits":{"hits":[...]}}``) — the parser maps ``_source`` shapes
  directly onto our models, no DOM walking.
- **Rich data.** Each tournament hit carries name, dates, geo,
  organization, events (singles/doubles/age/gender/surface), pricing,
  registration window. Enough to populate the dashboard, the
  tournaments list, and a per-tournament event/draw scaffold without
  a second fetch.

Endpoints in scope (only those that respond ``200`` without an
authentication token):

================================  =================  ===========================
Endpoint                          Method             Purpose
================================  =================  ===========================
/playtennis/tournaments/query     POST  (anonymous)  Tournament search (ES)
/playtennis/programs/query        POST  (anonymous)  Programs search (ES)
/product/api-courts/v1/courts/    POST  (anonymous)  Court inventory
inventory
================================  =================  ===========================

Endpoints that require auth (and therefore are NOT implemented here):

- ``/playtennis/players/query`` — 403 MissingAuthenticationToken
- ``/playtennis/tournaments/<id>`` (detail) — 403
- any ``/playtennis/<*>`` not in the table above — 403

The router fall-through to TennisLink / Clubspark remains intact for
the player-detail and draw-detail paths that need auth.

The cache layout mirrors :mod:`src.fetch.tennislink_client` so the
``inspect`` CLI and the reparse pipeline don't need a special case:
``data/raw/usta_api/<first-2-hex>/<sha256>.json``.

For full request/response shape and the discovery transcript see
``RECON.md`` (2026-05-11 section) and ``API_CONTRACTS.md`` (USTA-API
table).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
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
    "PATH_COURTS_INVENTORY",
    "PATH_PROGRAMS_QUERY",
    "PATH_TOURNAMENTS_QUERY",
    "BlockedEgressError",
    "BotChallengeError",
    "TournamentSelection",
    "TransientNetworkError",
    "UstaApiClient",
    "compute_usta_api_cache_key",
]


logger = logging.getLogger(__name__)


BASE_URL = "https://prod-api-playtennis.usta.com"
PLAYERAPP_ORIGIN = "https://playerapp.usta.com"

# Anonymous endpoints discovered via reverse-engineering the public
# National Search frontend at https://playerapp.usta.com/. See
# API_CONTRACTS.md for the response-shape contract.
PATH_TOURNAMENTS_QUERY = "/playtennis/tournaments/query"
PATH_PROGRAMS_QUERY = "/playtennis/programs/query"
PATH_COURTS_INVENTORY = "/product/api-courts/v1/courts/inventory"

ALLOWED_HOSTS: frozenset[str] = frozenset({"prod-api-playtennis.usta.com"})

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_RETRIES = 4
DEFAULT_BACKOFF_BASE = 1.0
DEFAULT_BACKOFF_CAP = 16.0

# ElasticSearch's max ``from + size`` is 10000 by default; the API
# clamps page size to 50. With 528 hits in a typical FL Junior search,
# 50/page × 211 pages = ~10.6k results — we cap pagination at 200
# pages to stay inside ES's window without explicit configuration.
MAX_PAGES = 200
DEFAULT_PAGE_SIZE = 50


class _TransientForRetryError(RuntimeError):
    """Internal marker for tenacity retries; not exported."""


class TournamentSelection(dict[str, Any]):
    """Convenience wrapper for the ``selection`` payload of a tournament query.

    The API requires ``d`` (distance, miles), ``lat``, and ``lon`` — every
    other field is optional. Keeping it a dict-subclass lets callers spread
    extra filters in without a builder DSL while still nudging them toward
    the canonical key names.
    """

    def __init__(
        self,
        lat: float,
        lon: float,
        distance_miles: float = 50.0,
        **extra: Any,
    ) -> None:
        super().__init__(d=distance_miles, lat=lat, lon=lon, **extra)


class UstaApiClient:
    """Anonymous, rate-limited, retried client for the Play Tennis API.

    Public methods conform to the :class:`src.fetch.router._SourceClient`
    protocol so the :class:`FetchRouter` can dispatch through it. Methods
    that the API can answer return JSON dicts; methods the API cannot
    answer without auth raise :class:`NotImplementedError` so the router
    falls through to TennisLink.
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
                "Content-Type": "application/json",
                "Origin": PLAYERAPP_ORIGIN,
                "Referer": f"{PLAYERAPP_ORIGIN}/",
            },
            follow_redirects=False,
        )
        self._owns_client: bool = client is None

        self._last_request_at: float | None = None
        self._lock = asyncio.Lock()

    # -- async context management ---------------------------------------------

    async def __aenter__(self) -> UstaApiClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # -- public fetch surface -------------------------------------------------

    async def search_tournaments(
        self,
        filters: dict[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Issue a tournament search and return the parsed JSON response.

        Accepts either a positional ``filters`` dict (the
        :class:`FetchRouter` calling convention) or keyword arguments;
        kwargs win on key collision. ``filters`` may be either a fully-
        formed payload (``{"selection": {...}, "sort": {...}}``) or a
        flat selection (``{"d": 50, "lat": 27.66, "lon": -81.5, ...}``)
        — the latter is wrapped under ``selection``.

        Required selection keys: ``d`` (miles), ``lat``, ``lon``.
        Optional selection keys: ``type`` ("Junior" / "Adult" / "Wheelchair"),
        ``q`` (keyword), ``registrationOpen`` (bool),
        ``startDateTime`` (ISO-8601), ``page`` (1-indexed),
        ``size`` (1..50), and the elastic-search filter fields
        (``events.division.gender``, ``events.surface``, etc.).

        Returns the ES envelope verbatim:

            {"took": ..., "hits": {"total": {"value": N}, "hits": [...]}, ...}
        """
        payload = self._build_query_payload(filters, kwargs)
        return await self._post(PATH_TOURNAMENTS_QUERY, payload)

    async def search_tournaments_paginated(
        self,
        filters: dict[str, Any] | None = None,
        /,
        max_pages: int = MAX_PAGES,
        page_size: int = DEFAULT_PAGE_SIZE,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Walk every page of a tournament search; return the merged hits list.

        Stops when the server returns fewer than ``page_size`` hits, the
        total count is exhausted, or ``max_pages`` is reached (whichever
        comes first). Suitable for daily bulk discovery against a small
        geo radius; not appropriate for nation-wide crawls.
        """
        # Build a base payload once; we'll bump `selection.page` per
        # iteration. We deliberately do not pass `sort` so the API uses
        # its default (distance asc) — that gives the most stable
        # pagination across multiple fetches.
        base_payload = self._build_query_payload(filters, kwargs)
        sel = dict(base_payload.get("selection", {}))
        sel.setdefault("size", page_size)
        all_hits: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        total: int | None = None
        for page in range(1, max_pages + 1):
            sel["page"] = page
            page_payload = {**base_payload, "selection": sel}
            envelope = await self._post(PATH_TOURNAMENTS_QUERY, page_payload)
            hits = envelope.get("hits", {}).get("hits", [])
            if not hits:
                break
            if total is None:
                total = int(envelope.get("hits", {}).get("total", {}).get("value", 0) or 0)
            for hit in hits:
                hid = str(hit.get("_id") or "")
                if hid and hid in seen_ids:
                    # The server returned an already-seen id (typically
                    # when the result set is smaller than `page_size` and
                    # we asked for a page past the end). Stop.
                    return all_hits
                if hid:
                    seen_ids.add(hid)
                all_hits.append(hit)
            if total is not None and len(all_hits) >= total:
                break
            if len(hits) < int(sel.get("size", page_size)):
                break
        return all_hits

    async def search_programs(
        self,
        filters: dict[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Issue a programs search. Same selection shape as tournaments."""
        payload = self._build_query_payload(filters, kwargs)
        return await self._post(PATH_PROGRAMS_QUERY, payload)

    async def search_courts(
        self,
        filters: dict[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Issue a courts-inventory search. Same selection shape as tournaments."""
        payload = self._build_query_payload(filters, kwargs)
        return await self._post(PATH_COURTS_INVENTORY, payload)

    # ---------- router protocol surface (delegates / not-implemented) --------

    async def get_tournament(self, usta_id: str) -> dict[str, Any]:
        """Return the search-result envelope for a single tournament id.

        Implementation note: the API has no public per-id GET; we issue
        a degenerate ``ids: [usta_id]`` search instead, which the server
        does honor for GUID-shaped ids. For TennisLink-shaped numeric
        ids we raise :class:`NotImplementedError` immediately without
        issuing a request — the GUID-indexed commingled ES table will
        never carry them, so the request would be pure waste.

        The router treats ``NotImplementedError`` as a clean fallthrough
        signal per ADR-005, so the orchestrator will hand the id off to
        TennisLink.
        """
        # GUID-shaped ids are what the commingled ES index keys on; bare
        # numeric ids are TennisLink-only. Fall through cleanly for the
        # numeric shape so we don't spam the API with guaranteed-misses.
        if not _looks_like_guid(usta_id):
            raise NotImplementedError(
                f"UstaApiClient: id {usta_id!r} is not GUID-shaped; "
                "falling through to TennisLink."
            )

        payload: dict[str, Any] = {
            "selection": {"d": 25000, "lat": 0, "lon": 0, "ids": [usta_id]}
        }
        envelope = await self._post(PATH_TOURNAMENTS_QUERY, payload)
        hits = envelope.get("hits", {}).get("hits", [])
        if not hits:
            raise NotImplementedError(
                f"UstaApiClient: tournament {usta_id!r} not in commingled index; "
                "falling through to TennisLink."
            )
        return envelope

    async def get_draw(self, draw_id: str) -> dict[str, Any]:
        """Per-draw fetch is not exposed anonymously; fall through."""
        raise NotImplementedError(
            "UstaApiClient: per-draw detail is gated behind auth; "
            "falling through to TennisLink."
        )

    async def get_player(self, player_id: str) -> dict[str, Any]:
        """Per-player fetch is not exposed anonymously; fall through."""
        raise NotImplementedError(
            "UstaApiClient: per-player detail is gated behind auth; "
            "falling through to TennisLink."
        )

    # -- internals ------------------------------------------------------------

    def _build_query_payload(
        self,
        filters: dict[str, Any] | None,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge a positional dict + kwargs into the query-payload shape.

        Accepts either:
          - A fully-formed payload: ``{"selection": {...}, "sort": {...}}``
          - A flat selection dict: ``{"d": 50, "lat": ..., "lon": ...}``
        """
        merged: dict[str, Any] = {}
        merged.update(filters or {})
        merged.update(kwargs)

        if "selection" in merged or "sort" in merged:
            return merged

        # Flat selection shape. Reject obviously-bad payloads up front so
        # the server doesn't have to.
        for required in ("d", "lat", "lon"):
            if required not in merged:
                raise ValueError(
                    f"UstaApiClient.search_*: required selection field "
                    f"{required!r} missing; got keys {sorted(merged)}."
                )
        return {"selection": merged}

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Token-bucketed, retried, cached POST. Returns parsed JSON."""
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
                    return await self._post_once(path, payload)
        except RetryError as exc:
            inner = exc.last_attempt.exception() if exc.last_attempt else None
            raise TransientNetworkError(
                f"USTA API POST {path} failed after {DEFAULT_RETRIES} attempts: {inner!r}"
            ) from exc
        # Unreachable; mypy reassurance.
        raise TransientNetworkError(  # pragma: no cover
            f"USTA API POST {path} produced no result"
        )

    async def _post_once(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{BASE_URL}{path}"
        _check_allowed_host(url)
        await self._respect_rate_limit()
        try:
            response = await self._client.post(url, content=json.dumps(payload))
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise _TransientForRetryError(f"network error: {exc}") from exc

        status = response.status_code

        if status == 403:
            try:
                self._write_cache(url, payload, response)
            except OSError:
                pass
            raise BlockedEgressError(
                f"USTA API returned 403 on {path}; the endpoint may now require auth."
            )

        if status in (408, 429) or 500 <= status < 600:
            raise _TransientForRetryError(f"HTTP {status} on {path}")

        try:
            self._write_cache(url, payload, response)
        except OSError as exc:  # pragma: no cover - defensive
            logger.warning("UstaApiClient cache write failed (%s); continuing.", exc)

        if status >= 400:
            raise TransientNetworkError(
                f"USTA API returned {status} on {path}: "
                f"{response.text[:200]!r}"
            )

        try:
            data: Any = response.json()
        except ValueError as exc:
            raise TransientNetworkError(
                f"USTA API returned non-JSON body on {path}: {response.text[:200]!r}"
            ) from exc
        if not isinstance(data, dict):
            raise TransientNetworkError(
                f"USTA API returned non-object JSON on {path}: {type(data).__name__}"
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
        payload: dict[str, Any],
        response: httpx.Response,
    ) -> Path:
        digest = compute_usta_api_cache_key(url, payload)
        target_dir = self.raw_cache_dir / "usta_api" / digest[:2]
        target_dir.mkdir(parents=True, exist_ok=True)
        cache_path = target_dir / f"{digest}.json"

        try:
            body: Any = response.json()
        except ValueError:
            body = response.text

        envelope: dict[str, Any] = {
            "fetched_at": datetime.now(UTC).isoformat(),
            "source": "usta_api",
            "request": {
                "method": "POST",
                "url": url,
                "params": None,
                "body": payload,
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


def compute_usta_api_cache_key(absolute_url: str, payload: dict[str, Any]) -> str:
    """Stable SHA-256 over (absolute URL, sorted payload)."""
    norm = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(f"{absolute_url}|{norm}".encode()).hexdigest()


def _check_allowed_host(url: str) -> None:
    host = urlparse(url).hostname or ""
    if host not in ALLOWED_HOSTS:
        raise ValueError(
            f"UstaApiClient refuses to fetch host {host!r}; "
            f"allowed: {sorted(ALLOWED_HOSTS)}"
        )


_GUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _looks_like_guid(value: str) -> bool:
    return bool(_GUID_RE.match(value or ""))


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
