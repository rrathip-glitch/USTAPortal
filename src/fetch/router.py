"""Multi-source fetch router.

The router exposes the *entity-level* fetch surface used by the sync
orchestrator:

    router = FetchRouter()
    html_or_json = await router.get_tournament(usta_id)

Under the hood it dispatches to one of:

- :class:`src.fetch.usta_api_client.UstaApiClient` — primary today
  (2026-05-11). Anonymous AWS API Gateway behind the playerapp.usta.com
  National Search. Reachable from any egress; no Cloudflare block.
- :class:`src.fetch.tennislink_client.TennisLinkClient` — secondary;
  historical archive (frozen post-2018) for matches and rankings.
- :class:`src.fetch.clubspark_client.ClubsparkClient` — deferred; raises
  :class:`NotImplementedError` until residential egress (Q-011).

Dispatch logic (per ADR-005, updated 2026-05-11):

1. Honor the configured source preference order (default
   ``["usta_api", "tennislink", "clubspark"]``).
2. As a tie-break heuristic, if the entity id *looks* like a Clubspark GUID
   (``8-4-4-4-12`` hex) and ``usta_api`` is in the preference list, try
   ``usta_api`` first — the AEM index is keyed by GUID. TennisLink ids
   are short numeric strings; we leave the configured order for them.
3. If the current source raises :class:`BlockedEgressError` (Cloudflare 403
   on Clubspark, or any "the edge refused our IP" signal), the router
   falls through to the next source and logs a clean message.
4. If the current source raises :class:`NotImplementedError` (the
   Clubspark stub today, or the USTA API for per-id detail), same
   fallthrough.

Errors that are *not* fallthrough-worthy (auth expired, transient network,
parse failure) propagate to the caller — the orchestrator is the one that
decides whether to retry, re-auth, or skip.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# A GUID looks like ``CB005855-CDEF-4A4A-8885-4D3A52C9B413``. Compare
# case-insensitively. TennisLink ids in the wild are typically 6-10 digit
# numeric strings — anything that matches both digits-only and short-ish.
_GUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_TENNISLINK_ID_RE = re.compile(r"^\d{4,12}$")

DEFAULT_SOURCE_PREFERENCE: tuple[str, ...] = ("usta_api", "tennislink", "clubspark")
KNOWN_SOURCES: frozenset[str] = frozenset({"usta_api", "tennislink", "clubspark"})


class BlockedEgressError(RuntimeError):
    """Raised when the source's edge refuses our request (e.g. Cloudflare 403).

    Distinct from auth failure: this means *the request never got past the
    CDN*, regardless of who we claim to be. The router uses it as the
    fallthrough trigger.
    """


class _SourceClient(Protocol):
    """The shape every source client conforms to.

    Defined as a structural protocol so the router doesn't depend on
    the concrete class symbols — useful since ``TennisLinkClient`` is
    written by a separate agent and may land with minor signature
    variations.
    """

    async def search_tournaments(self, filters: dict[str, Any]) -> Any: ...
    async def get_tournament(self, usta_id: str) -> Any: ...
    async def get_draw(self, draw_id: str) -> Any: ...
    async def get_player(self, player_id: str) -> Any: ...
    async def close(self) -> None: ...


def looks_like_guid(value: str) -> bool:
    """Heuristic: does ``value`` look like a Clubspark GUID?"""
    return bool(_GUID_RE.match(value))


def looks_like_tennislink_id(value: str) -> bool:
    """Heuristic: does ``value`` look like a TennisLink numeric id?"""
    return bool(_TENNISLINK_ID_RE.match(value))


class FetchRouter:
    """Entity-level fetch surface that dispatches across data sources.

    Construct once per sync run. Call :meth:`close` (or use as an async
    context manager) to drain the underlying clients.
    """

    def __init__(
        self,
        tennislink: _SourceClient | None = None,
        clubspark: _SourceClient | None = None,
        usta_api: _SourceClient | None = None,
        source_preference: tuple[str, ...] | None = None,
    ) -> None:
        # Lazy-instantiate the source clients only when first needed; this
        # keeps the router cheap to construct in tests and in `where-am-i`.
        self._tennislink: _SourceClient | None = tennislink
        self._clubspark: _SourceClient | None = clubspark
        self._usta_api: _SourceClient | None = usta_api

        prefs = source_preference if source_preference is not None else DEFAULT_SOURCE_PREFERENCE
        for name in prefs:
            if name not in KNOWN_SOURCES:
                raise ValueError(
                    f"Unknown source {name!r}; expected one of {sorted(KNOWN_SOURCES)}."
                )
        self._source_preference: tuple[str, ...] = tuple(prefs)

    # -- async context management --------------------------------------------------

    async def __aenter__(self) -> FetchRouter:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        for client in (self._usta_api, self._tennislink, self._clubspark):
            if client is None:
                continue
            try:
                await client.close()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("FetchRouter: error closing source client: %s", exc)

    # -- public properties ---------------------------------------------------------

    @property
    def source_preference(self) -> tuple[str, ...]:
        return self._source_preference

    # -- public fetch surface ------------------------------------------------------

    async def get_tournament(self, usta_id: str) -> Any:
        return await self._dispatch("get_tournament", usta_id)

    async def get_draw(self, draw_id: str) -> Any:
        return await self._dispatch("get_draw", draw_id)

    async def get_player(self, player_id: str) -> Any:
        return await self._dispatch("get_player", player_id)

    async def search_tournaments(self, filters: dict[str, Any]) -> Any:
        """Search has no id shape — walk the preference list directly."""
        return await self._dispatch_search(filters)

    # -- internals -----------------------------------------------------------------

    def _ordered_sources_for_id(self, entity_id: str) -> list[str]:
        """Return the source-name list to try for this id.

        Honors :attr:`source_preference` but bumps GUID-aware sources to
        the front when the id is GUID-shaped (the caller clearly has
        Clubspark / USTA-API data). Preference among GUID-aware sources:
        ``usta_api`` first if available (anonymously reachable, low
        latency), then ``clubspark`` (authenticated, residential-only).
        """
        prefs = list(self._source_preference)
        if looks_like_guid(entity_id):
            for guid_source in ("clubspark", "usta_api"):
                # Move each GUID-aware source to the front, in order;
                # the loop's order ensures ``usta_api`` ends up first.
                if guid_source in prefs:
                    prefs.remove(guid_source)
                    prefs.insert(0, guid_source)
        return prefs

    async def _dispatch(self, method: str, entity_id: str) -> Any:
        ordered = self._ordered_sources_for_id(entity_id)
        return await self._try_sources(ordered, method, (entity_id,), {})

    async def _dispatch_search(self, filters: dict[str, Any]) -> Any:
        ordered = list(self._source_preference)
        return await self._try_sources(ordered, "search_tournaments", (filters,), {})

    async def _try_sources(
        self,
        ordered: list[str],
        method: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        last_exc: Exception | None = None
        for source_name in ordered:
            client = self._get_client(source_name)
            if client is None:
                logger.info(
                    "FetchRouter: source %s is not configured/available; skipping.",
                    source_name,
                )
                continue
            try:
                func = getattr(client, method)
                return await func(*args, **kwargs)
            except BlockedEgressError as exc:
                logger.warning(
                    "FetchRouter: %s.%s blocked at egress (%s); falling through.",
                    source_name,
                    method,
                    exc,
                )
                last_exc = exc
                continue
            except NotImplementedError as exc:
                logger.info(
                    "FetchRouter: %s.%s is not yet implemented (%s); falling through.",
                    source_name,
                    method,
                    exc,
                )
                last_exc = exc
                continue

        # Exhausted every source. Surface whatever the last source said.
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(
            f"FetchRouter: no source was able to handle {method} "
            f"(preference={self._source_preference})."
        )

    def _get_client(self, source_name: str) -> _SourceClient | None:
        if source_name == "tennislink":
            if self._tennislink is None:
                self._tennislink = self._build_tennislink()
            return self._tennislink
        if source_name == "clubspark":
            if self._clubspark is None:
                self._clubspark = self._build_clubspark()
            return self._clubspark
        if source_name == "usta_api":
            if self._usta_api is None:
                self._usta_api = self._build_usta_api()
            return self._usta_api
        return None

    @staticmethod
    def _build_tennislink() -> _SourceClient | None:
        """Lazily import and instantiate the TennisLink client.

        Imported lazily because the module is authored by a separate agent
        and may not have landed at the moment this router is first used.
        Returns ``None`` if the import fails — the router will log and
        skip the source rather than crash the whole sync.
        """
        try:
            from src.fetch.tennislink_client import TennisLinkClient
        except ImportError as exc:
            logger.warning(
                "FetchRouter: TennisLink client not importable yet (%s); skipping.",
                exc,
            )
            return None

        try:
            instance: _SourceClient = TennisLinkClient()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("FetchRouter: TennisLinkClient instantiation failed: %s", exc)
            return None
        return instance

    @staticmethod
    def _build_clubspark() -> _SourceClient | None:
        """Instantiate the (deferred) Clubspark client stub."""
        from src.fetch.clubspark_client import ClubsparkClient

        instance: _SourceClient = ClubsparkClient()
        return instance

    @staticmethod
    def _build_usta_api() -> _SourceClient | None:
        """Lazily import and instantiate the anonymous USTA API client.

        Returns ``None`` if the import fails (e.g. during partial check-
        out / refactor) so the router can fall through to TennisLink.
        """
        try:
            from src.fetch.usta_api_client import UstaApiClient
        except ImportError as exc:
            logger.warning(
                "FetchRouter: USTA API client not importable (%s); skipping.",
                exc,
            )
            return None

        try:
            instance: _SourceClient = UstaApiClient()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("FetchRouter: UstaApiClient instantiation failed: %s", exc)
            return None
        return instance


def configured_source_preference() -> tuple[str, ...]:
    """Return the source preference order from settings, or the default.

    Reads ``src.config.settings`` *at call time* so test reloads of the
    config module are picked up. ``USTA_SOURCE_PREFERENCE=clubspark,tennislink``
    in the environment overrides the default.
    """
    # Import locally so we always see the current module reference even if
    # a test has reloaded `src.config` after this module was loaded.
    from src.config import settings as live_settings

    raw = getattr(live_settings, "usta_source_preference", None)
    if not raw:
        return DEFAULT_SOURCE_PREFERENCE
    if isinstance(raw, str):
        parts = tuple(p.strip().lower() for p in raw.split(",") if p.strip())
    else:
        parts = tuple(str(p).strip().lower() for p in raw if str(p).strip())
    return parts or DEFAULT_SOURCE_PREFERENCE
