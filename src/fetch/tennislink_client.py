"""Async HTTP client for the legacy ``tennislink.usta.com`` surface.

TennisLink (ASP.NET WebForms + Vue 2 overlay) is the primary reachable
data source from environments that cannot reach ``playtennis.usta.com``
(Clubspark, which is Cloudflare-fronted with an IP/ASN block — see
ADR-001 and RECON.md). TennisLink is NOT Cloudflare-fronted: stock
httpx works fine from any egress.

The shape of this client mirrors :class:`src.fetch.client.FetchClient`
in spirit: it is rate-limited, writes raw HTML responses into the same
on-disk cache layout, and retries on 429/5xx with backoff. It does NOT
inherit from that class because the two have different concerns —
``FetchClient`` is a GraphQL-leaning POST client paired with an
authenticated Playwright session, whereas ``TennisLinkClient`` is
anonymous-only and only ever issues GETs against
``tennislink.usta.com`` hosts.

The cache envelope mirrors the upstream ``FetchClient`` envelope (same
SHA-256 keying, same ``<first-2-hex>/<full-hex>.<ext>`` layout, same
redaction rules) so the parse layer can read either source uniformly.
We delegate header redaction to :mod:`src.fetch.client` to avoid drift.

This module conforms to the structural ``_SourceClient`` protocol that
:class:`src.fetch.router.FetchRouter` consumes: every entity-level
method returns the response **body as text** (HTML), so the router can
hand it straight to the matching parser without unwrapping a wrapper
object.
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
from urllib.parse import urlencode, urlparse

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
    "TennisLinkClient",
    "TransientNetworkError",
    "compute_tennislink_cache_key",
]


logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

BASE_URL = "https://tennislink.usta.com"

# Hosts this client is permitted to talk to. Any other host is a programmer
# error; we refuse the request rather than silently widening scope.
ALLOWED_HOSTS: frozenset[str] = frozenset(
    {"tennislink.usta.com", "m.tennislink.usta.com"}
)

# Canonical paths (see API_CONTRACTS.md "TennisLink endpoints").
PATH_SEARCH_FORM = "/tournaments/schedule/search.aspx"
PATH_SEARCH_RESULTS = "/tournaments/schedule/SearchResults.aspx"
PATH_TOURNAMENT_DETAIL = "/tournaments/TournamentHome/Tournament.aspx"
PATH_PLAYER_HISTORY = "/tournaments/Draws/PlayerTournamentHistory.aspx"
PATH_RANKING_HOME = "/tournaments/Rankings/RankingHome.aspx"
PATH_RANKING_PRINT = "/Tournaments/Rankings/RankingListsPrint.aspx"

# Browser-realistic UA. TennisLink does not enforce UA but well-behaved
# clients identify themselves.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Retry config — applied via tenacity. Tuned to ADR-005 / SPEC §6 defaults
# (4 attempts total, exponential backoff base 1s, cap 16s).
DEFAULT_RETRIES = 4
DEFAULT_BACKOFF_BASE = 1.0
DEFAULT_BACKOFF_CAP = 16.0

# TennisLink renders generic ASP.NET error pages on 500s; we only flag the
# Cloudflare-style interstitial language since TennisLink itself is not
# Cloudflare-fronted. Defensive heuristic.
_BOT_CHALLENGE_HINTS: tuple[str, ...] = (
    "sorry, you have been blocked",
    "cloudflare ray id",
    "captcha",
)


# -----------------------------------------------------------------------------
# Client
# -----------------------------------------------------------------------------


class TennisLinkClient:
    """Anonymous, rate-limited, retried HTTP client for TennisLink.

    Conforms to :class:`src.fetch.router._SourceClient`: every public
    entity-level method returns the response body as ``str`` (HTML).

    Construction is cheap (no I/O); the underlying ``httpx.AsyncClient``
    is created in :meth:`__init__` but no requests are issued until a
    fetch method is called. Use the class as an async context manager,
    or call :meth:`close` manually, to release the underlying client.
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
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
            follow_redirects=True,
        )
        self._owns_client: bool = client is None

        self._last_request_at: float | None = None
        self._lock = asyncio.Lock()

    # -- async context management ---------------------------------------------

    async def __aenter__(self) -> TennisLinkClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # -- public fetch surface -------------------------------------------------

    async def get(self, url: str, *, params: dict[str, Any] | None = None) -> str:
        """Low-level GET. ``url`` may be absolute or a TennisLink path.

        Returns the response body as text. Raises
        :class:`BlockedEgressError` on 403, :class:`BotChallengeError`
        on a Cloudflare-style interstitial body,
        :class:`TransientNetworkError` when retries are exhausted.
        """
        return await self._fetch_with_retry(url, params=params)

    async def search_tournaments(
        self,
        filters: dict[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> str:
        """Issue a tournament search and return the results-page HTML.

        Accepts either a positional ``filters`` dict (the
        :class:`FetchRouter` calling convention) or keyword arguments
        (the spec'd ergonomic shape). Both are merged, with kwargs
        taking precedence on key collision. Empty defaults are filled
        in for any keys the form expects but the caller omitted.

        Filter keys map 1:1 onto the SearchResults.aspx query
        parameters (see API_CONTRACTS.md): ``Keywords``, ``TournamentID``,
        ``SectionDistrict``, ``City``, ``State``, ``Zip``, ``Month``,
        ``Year``, ``StartDate``, ``EndDate``, ``Day``, ``Division``
        (e.g. ``"GB16"``), ``Category``, ``Surface``, ``OnlineEntry``,
        ``DrawsSheets``, ``UserTime``, ``Sanctioned``, ``Action``,
        ``typeofsubmit``.
        """
        defaults: dict[str, Any] = {
            "typeofsubmit": "advanced",
            "Action": "",
            "Keywords": "",
            "TournamentID": "",
            "SectionDistrict": "",
            "City": "",
            "State": "",
            "Zip": "",
            "Month": "",
            "StartDate": "",
            "EndDate": "",
            "Day": "",
            "Year": "",
            "Division": "",
            "Category": "",
            "Surface": "",
            "OnlineEntry": "",
            "DrawsSheets": "",
            "UserTime": "",
            "Sanctioned": "",
        }
        merged: dict[str, Any] = {**defaults, **(filters or {}), **kwargs}
        return await self._fetch_with_retry(PATH_SEARCH_RESULTS, params=merged)

    async def get_tournament(self, tournament_id: str) -> str:
        """Fetch a tournament detail page (``T=<id>``)."""
        return await self._fetch_with_retry(
            PATH_TOURNAMENT_DETAIL, params={"T": str(tournament_id)}
        )

    async def get_draw(self, draw_id: str) -> str:
        """Fetch a draw view (the ``Draws`` tab of a tournament).

        TennisLink does not have a standalone ``/draw/<id>`` URL — draws
        live on the tournament page with ``E=<event>`` selected.

        ``draw_id`` accepts:

        - ``"T=211365:E=5"`` — the canonical composite form,
        - ``"211365:5"``   — short composite,
        - ``"211365"``     — bare tournament id (returns the Draws tab
          with no event preselected; the parser will surface the first
          event in the dropdown).

        TODO: when the orchestrator migrates to fully-qualified
        composite draw ids (after recon's residential-egress pass),
        tighten this to require the composite form.
        """
        t_id, e_id = _split_draw_id(draw_id)
        params: dict[str, Any] = {"T": t_id, "tab": "Draws"}
        if e_id is not None:
            params["E"] = e_id
        return await self._fetch_with_retry(PATH_TOURNAMENT_DETAIL, params=params)

    async def get_player(self, player_id: str) -> str:
        """Fetch a player's tournament-history page (``MID=<id>``).

        TennisLink does NOT expose a standalone player profile — the
        closest equivalent is this history view. The page itself does
        not print the player's name; names must be carried in from the
        referring draw or ranking list. The parser handles the missing-
        name case explicitly.
        """
        return await self._fetch_with_retry(
            PATH_PLAYER_HISTORY, params={"MID": player_id, "Years": "-5"}
        )

    async def get_player_search(self, query: str) -> str:
        """Fetch a player search results page.

        TODO: TennisLink's actual player-search surface is the Rankings
        home form (``RankingHome.aspx``), which requires an ASP.NET
        ``__VIEWSTATE`` round-trip POST to run a name search. The
        public GET on ``RankingHome.aspx`` returns the empty form
        (which the parser handles), so for now this returns the form
        page and the caller treats "no results" as the normal case
        until the VIEWSTATE-bearing POST flow is wired (Q-016).
        """
        params: dict[str, Any] = {}
        if query:
            params["q"] = query
        return await self._fetch_with_retry(PATH_RANKING_HOME, params=params or None)

    async def get_ranking_list(
        self,
        list_id: str,
        *,
        eligibles_only: bool = True,
        sort_by: str = "rank",
    ) -> str:
        """Fetch a printable ranking list by id."""
        return await self._fetch_with_retry(
            PATH_RANKING_PRINT,
            params={
                "id": str(list_id),
                "e": "1" if eligibles_only else "0",
                "sortby": sort_by,
            },
        )

    # -- internals ------------------------------------------------------------

    async def _fetch_with_retry(
        self, url_or_path: str, *, params: dict[str, Any] | None = None
    ) -> str:
        """Token-bucketed, retried, cached fetch. Returns body text."""
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
                    return await self._fetch_once(url_or_path, params=params)
        except RetryError as exc:
            inner = exc.last_attempt.exception() if exc.last_attempt else None
            raise TransientNetworkError(
                f"TennisLink fetch failed after {DEFAULT_RETRIES} attempts: {inner!r}"
            ) from exc
        # Unreachable in practice; keeps mypy honest.
        raise TransientNetworkError(  # pragma: no cover
            f"TennisLink fetch produced no result for {url_or_path}"
        )

    async def _fetch_once(
        self, url_or_path: str, *, params: dict[str, Any] | None
    ) -> str:
        """One outbound request. Caches on success; surfaces errors."""
        absolute = _absolute_url(url_or_path)
        _check_allowed_host(absolute)

        await self._respect_rate_limit()

        try:
            response = await self._client.get(absolute, params=params)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise _TransientForRetryError(f"network error: {exc}") from exc

        status = response.status_code

        # 403 on TennisLink is rare (the surface is anonymously
        # crawlable); if it ever happens, treat it the same way as
        # Clubspark — surface it as BlockedEgressError so the router
        # falls through cleanly.
        if status == 403:
            raise BlockedEgressError(
                f"TennisLink returned 403 on {absolute}; egress likely blocked."
            )

        # Transient: 5xx, 408, 429 — hand off to tenacity to back off.
        if status in (408, 429) or 500 <= status < 600:
            raise _TransientForRetryError(f"HTTP {status} on {absolute}")

        # Anything else (200/3xx/non-403 4xx) — body in hand. Cache,
        # check for a bot-wall body, then return.
        body = response.text

        if _looks_like_bot_challenge(response, body):
            try:
                self._write_cache(absolute, params or {}, response, body)
            except OSError as exc:  # pragma: no cover - defensive
                logger.warning(
                    "TennisLink bot-wall cache write failed (%s); continuing.", exc
                )
            raise BotChallengeError(
                f"TennisLink returned a bot-challenge page at {absolute}."
            )

        try:
            self._write_cache(absolute, params or {}, response, body)
        except OSError as exc:  # pragma: no cover - defensive
            logger.warning("TennisLink cache write failed (%s); continuing.", exc)

        if status >= 400:
            # Non-403/408/429 4xx — surface as a transient error so the
            # caller sees a clear failure, not silently empty HTML.
            raise TransientNetworkError(
                f"TennisLink returned {status} on {absolute}"
            )

        return body

    async def _respect_rate_limit(self) -> None:
        """Token-bucket-lite: ensure ``interval_seconds`` between requests."""
        async with self._lock:
            now = time.monotonic()
            if self._last_request_at is not None:
                elapsed = now - self._last_request_at
                # Tiny jitter so we don't look like a metronome.
                jitter = self.interval_seconds * 0.1
                target = self.interval_seconds + random.uniform(-jitter, jitter)
                wait = target - elapsed
                if wait > 0:
                    await self._sleep(wait)
            self._last_request_at = time.monotonic()

    @staticmethod
    async def _sleep(seconds: float) -> None:
        await asyncio.sleep(max(0.0, seconds))

    # -- cache writer ---------------------------------------------------------

    def _write_cache(
        self,
        absolute_url: str,
        params: dict[str, Any],
        response: httpx.Response,
        body: str,
    ) -> Path:
        """Write the TennisLink raw-cache envelope; return the JSON path."""
        digest = compute_tennislink_cache_key(absolute_url, params)
        target_dir = self.raw_cache_dir / "tennislink" / digest[:2]
        target_dir.mkdir(parents=True, exist_ok=True)
        cache_path = target_dir / f"{digest}.json"

        envelope: dict[str, Any] = {
            "fetched_at": datetime.now(UTC).isoformat(),
            "source": "tennislink",
            "request": {
                "method": "GET",
                "url": absolute_url,
                "params": params,
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
# Module-level helpers (also used by the parsers and tests)
# -----------------------------------------------------------------------------


class _TransientForRetryError(RuntimeError):
    """Internal marker exception driving tenacity retry. Not exported."""


def compute_tennislink_cache_key(
    absolute_url: str, params: dict[str, Any]
) -> str:
    """Stable SHA-256 over (absolute URL, sorted query params)."""
    norm_params = json.dumps(params, sort_keys=True, default=str, ensure_ascii=False)
    payload = f"{absolute_url}|{norm_params}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_search_url(filters: dict[str, Any]) -> str:
    """Build the canonical search-results URL for a filter set.

    Used by integration tests that want to construct a deterministic
    respx route.
    """
    return f"{BASE_URL}{PATH_SEARCH_RESULTS}?{urlencode(filters)}"


def _absolute_url(url_or_path: str) -> str:
    if url_or_path.startswith(("http://", "https://")):
        return url_or_path
    if url_or_path.startswith("/"):
        return f"{BASE_URL}{url_or_path}"
    return f"{BASE_URL}/{url_or_path}"


def _check_allowed_host(url: str) -> None:
    host = urlparse(url).hostname or ""
    if host not in ALLOWED_HOSTS:
        raise ValueError(
            f"TennisLinkClient refuses to fetch host {host!r}; "
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


def _looks_like_bot_challenge(response: httpx.Response, body: str) -> bool:
    ct = response.headers.get("content-type", "").lower()
    if "html" not in ct:
        return False
    lower = body.lower()
    return any(hint in lower for hint in _BOT_CHALLENGE_HINTS)


def _split_draw_id(draw_id: str) -> tuple[str, str | None]:
    """Split a composite ``T=<t>:E=<e>`` id, or return (draw_id, None).

    Accepted forms (most-specific first):
    - ``"T=211365:E=5"`` -> (``"211365"``, ``"5"``)
    - ``"211365:5"``     -> (``"211365"``, ``"5"``)
    - ``"211365"``       -> (``"211365"``, ``None``)
    """
    raw = draw_id.strip()
    if not raw:
        return raw, None
    if ":" in raw:
        left, right = raw.split(":", 1)
        t = left.split("=", 1)[1] if "=" in left else left
        e = right.split("=", 1)[1] if "=" in right else right
        return t.strip(), (e.strip() or None)
    return raw, None
