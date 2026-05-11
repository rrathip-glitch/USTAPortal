"""Observability scaffold for the USTA Portal.

This module produces a :class:`HealthSnapshot` describing current
operational state of the app — DB connectivity, the latest sync run,
and (optionally) live-probed status of each upstream source. The
``/health`` endpoint in :mod:`src.main` will delegate here; CLI and
dashboard surfaces can call :func:`health_snapshot` directly.

Design notes
------------
* **Failure-tolerant by construction.** Every read is wrapped in
  try/except so a half-initialised DB, missing table, or upstream
  hiccup degrades the response rather than 500'ing the endpoint.
  ``/health`` is the last thing that should be flaky — Railway's
  deploy probe points at it.
* **Live probes are opt-in.** :func:`probe_source` does real
  network I/O, so callers must pass ``probe_sources=True`` to
  :func:`health_snapshot`. The default keeps the endpoint quick
  and side-effect free.
* **Plain-dict output.** ``HealthSnapshot.model_dump()`` returns a
  JSON-serialisable ``dict[str, Any]`` so FastAPI's default JSON
  encoder is enough — no Pydantic round-trip needed.
"""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from src.fetch.coretennis_client import BASE_URL as CORETENNIS_BASE_URL
from src.fetch.tennislink_client import BASE_URL as TENNISLINK_BASE_URL
from src.fetch.tennislink_client import PATH_SEARCH_FORM as TENNISLINK_SEARCH_PATH
from src.fetch.usta_api_client import (
    BASE_URL as USTA_API_BASE_URL,
)
from src.fetch.usta_api_client import (
    PATH_TOURNAMENTS_QUERY as USTA_API_TOURNAMENTS_PATH,
)
from src.fetch.utr_client import BASE_URL as UTR_BASE_URL
from src.fetch.utr_client import PATH_SEARCH_PLAYERS as UTR_SEARCH_PATH

__all__ = ["HealthSnapshot", "SourceStatus", "health_snapshot", "probe_source"]


# Sources we publish status for. ``clubspark`` is always "deferred"
# today — kept in the list so the response shape doesn't change when
# we light it up later.
SOURCE_NAMES: tuple[str, ...] = (
    "usta_api",
    "tennislink",
    "coretennis",
    "utr",
    "clubspark",
)

_PROBE_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class SourceStatus:
    """One source's current operational state.

    ``name``  -- one of ``usta_api`` / ``tennislink`` / ``coretennis``
    / ``utr`` / ``clubspark``.
    ``status`` -- ``"ok"`` (reachable), ``"blocked"`` (403 / WAF),
    ``"error"`` (5xx / network), ``"deferred"`` (intentionally not
    probed), or ``"unknown"`` (probe not yet run).
    """

    name: str
    status: str
    detail: str | None = None
    last_checked_at: datetime | None = None


@dataclass(frozen=True)
class HealthSnapshot:
    """Aggregate snapshot of app health."""

    overall_status: str
    db_connected: bool
    db_path: str | None
    schema_version: int | None
    latest_sync_at: datetime | None
    latest_sync_status: str | None
    sources: list[SourceStatus] = field(default_factory=list)
    app_version: str = "0.1.0"
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def model_dump(self) -> dict[str, Any]:
        """Return a JSON-serialisable plain-dict representation.

        ``datetime`` instances are rendered with :py:meth:`isoformat`
        so :func:`json.dumps` accepts the result without a custom
        encoder.
        """
        return {
            "overall_status": self.overall_status,
            "db_connected": self.db_connected,
            "db_path": self.db_path,
            "schema_version": self.schema_version,
            "latest_sync_at": (
                self.latest_sync_at.isoformat() if self.latest_sync_at else None
            ),
            "latest_sync_status": self.latest_sync_status,
            "sources": [
                {
                    "name": s.name,
                    "status": s.status,
                    "detail": s.detail,
                    "last_checked_at": (
                        s.last_checked_at.isoformat() if s.last_checked_at else None
                    ),
                }
                for s in self.sources
            ],
            "app_version": self.app_version,
            "generated_at": self.generated_at.isoformat(),
        }


def health_snapshot(
    *,
    conn: sqlite3.Connection | None = None,
    app_version: str = "0.1.0",
    now: datetime | None = None,
    probe_sources: bool = False,
) -> HealthSnapshot:
    """Build a :class:`HealthSnapshot`.

    Safe to call when the DB is missing or half-initialised — every
    step is wrapped in try/except, so the worst case is a snapshot
    full of ``None`` / ``"unknown"`` values rather than a raised
    exception.

    Parameters
    ----------
    conn:
        Optional open SQLite connection. When ``None`` the snapshot
        records ``db_connected=False`` and skips the sync-run read;
        we deliberately don't open a connection here because the
        caller (FastAPI route) should manage the lifecycle.
    app_version:
        Surfaced verbatim in the response. Defaults to ``"0.1.0"``
        to match the FastAPI app's declared version.
    now:
        Override for the ``generated_at`` field; useful in tests for
        deterministic output. ``None`` uses :py:func:`datetime.now`.
    probe_sources:
        When ``True``, calls :func:`probe_source` for each entry in
        :data:`SOURCE_NAMES`. The probes do real network I/O so this
        is off by default — Railway's deploy probe must remain quick
        and side-effect free.
    """
    generated_at = now or datetime.now(UTC)

    db_connected = False
    db_path = _safe_db_path()
    schema_version: int | None = None
    latest_sync_at: datetime | None = None
    latest_sync_status: str | None = None

    if conn is not None:
        try:
            # Cheap query that proves the connection is usable.
            conn.execute("SELECT 1").fetchone()
            db_connected = True
        except sqlite3.DatabaseError:
            db_connected = False

        if db_connected:
            schema_version = _safe_schema_version(conn)
            latest_sync_at, latest_sync_status = _safe_latest_sync(conn)

    sources = _collect_sources(probe_sources=probe_sources)
    overall = _compute_overall_status(db_connected=db_connected, sources=sources)

    return HealthSnapshot(
        overall_status=overall,
        db_connected=db_connected,
        db_path=db_path,
        schema_version=schema_version,
        latest_sync_at=latest_sync_at,
        latest_sync_status=latest_sync_status,
        sources=sources,
        app_version=app_version,
        generated_at=generated_at,
    )


async def probe_source(name: str) -> SourceStatus:
    """Live-probe one source and return a :class:`SourceStatus`.

    Each probe is a single short-timeout HTTP call:

    * ``usta_api`` -- POST a tiny tournaments query; ``200`` -> ok,
      ``403`` -> blocked, anything else -> error.
    * ``tennislink`` -- GET the search form; ``200`` -> ok.
    * ``coretennis`` -- GET the site root.
    * ``utr`` -- GET the anonymous player-search endpoint.
    * ``clubspark`` -- always returns ``"deferred"`` without
      issuing any network request.

    Unknown source names produce ``status="unknown"``.
    """
    checked_at = datetime.now(UTC)
    if name == "clubspark":
        return SourceStatus(
            name=name,
            status="deferred",
            detail="ClubSpark probe not implemented yet.",
            last_checked_at=checked_at,
        )

    if name == "usta_api":
        return await _probe_http(
            name=name,
            method="POST",
            url=f"{USTA_API_BASE_URL}{USTA_API_TOURNAMENTS_PATH}",
            json_body={
                "selection": {
                    "d": 1,
                    "lat": 27.6648,
                    "lon": -81.5158,
                    "size": 1,
                }
            },
        )

    if name == "tennislink":
        return await _probe_http(
            name=name,
            method="GET",
            url=f"{TENNISLINK_BASE_URL}{TENNISLINK_SEARCH_PATH}",
        )

    if name == "coretennis":
        return await _probe_http(
            name=name,
            method="GET",
            url=f"{CORETENNIS_BASE_URL}/",
        )

    if name == "utr":
        return await _probe_http(
            name=name,
            method="GET",
            url=f"{UTR_BASE_URL}{UTR_SEARCH_PATH}",
            params={"query": "test", "top": "1"},
        )

    return SourceStatus(
        name=name,
        status="unknown",
        detail=f"Unrecognised source name: {name!r}",
        last_checked_at=checked_at,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_db_path() -> str | None:
    """Return the configured DB path as a string, ``None`` on failure.

    Wrapped because reading settings can fail mid-bootstrap and
    ``/health`` must still respond.
    """
    try:
        from src.store.db import db_path

        return str(db_path())
    except Exception:
        return None


def _safe_schema_version(conn: sqlite3.Connection) -> int | None:
    """Return the recorded schema version, swallowing all errors."""
    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'version'"
        ).fetchone()
    except sqlite3.DatabaseError:
        return None
    if row is None or row[0] is None:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def _safe_latest_sync(
    conn: sqlite3.Connection,
) -> tuple[datetime | None, str | None]:
    """Return ``(latest_sync.started_at, latest_sync.status)`` or ``(None, None)``."""
    try:
        row = conn.execute(
            "SELECT started_at, status FROM sync_runs "
            "ORDER BY started_at DESC, id DESC LIMIT 1"
        ).fetchone()
    except sqlite3.DatabaseError:
        return (None, None)
    if row is None:
        return (None, None)
    started_at_raw, status = row
    started_at: datetime | None
    try:
        started_at = (
            datetime.fromisoformat(started_at_raw) if started_at_raw else None
        )
    except (TypeError, ValueError):
        started_at = None
    return (started_at, status)


def _collect_sources(*, probe_sources: bool) -> list[SourceStatus]:
    """Return a status list for every known source.

    When ``probe_sources`` is False, returns a fixed shape of
    ``"unknown"`` (and ``"deferred"`` for ClubSpark) entries — no
    network is touched. When True, fan-out probes run concurrently
    and any single-probe exception becomes a graceful
    ``status="error"`` entry rather than bubbling up.
    """
    if not probe_sources:
        return [
            (
                SourceStatus(name=name, status="deferred", detail=None)
                if name == "clubspark"
                else SourceStatus(name=name, status="unknown", detail=None)
            )
            for name in SOURCE_NAMES
        ]

    async def _gather() -> list[SourceStatus]:
        results = await asyncio.gather(
            *(probe_source(name) for name in SOURCE_NAMES),
            return_exceptions=True,
        )
        cleaned: list[SourceStatus] = []
        for name, result in zip(SOURCE_NAMES, results, strict=True):
            if isinstance(result, BaseException):
                cleaned.append(
                    SourceStatus(
                        name=name,
                        status="error",
                        detail=f"probe raised {type(result).__name__}: {result}",
                        last_checked_at=datetime.now(UTC),
                    )
                )
            else:
                cleaned.append(result)
        return cleaned

    try:
        # Detect a running event loop. If we're inside one we cannot
        # call ``asyncio.run``; in practice ``probe_sources=True``
        # from within an async route should pre-probe and inject the
        # results — but until that path exists, fall back to
        # "unknown" entries so we never hang the route.
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_gather())
    return [
        (
            SourceStatus(name=name, status="deferred", detail=None)
            if name == "clubspark"
            else SourceStatus(
                name=name,
                status="unknown",
                detail="probe skipped: cannot run sync probe inside running loop",
            )
        )
        for name in SOURCE_NAMES
    ]


def _compute_overall_status(
    *, db_connected: bool, sources: list[SourceStatus]
) -> str:
    """Roll the per-component statuses up to a single label.

    Rules (per spec):

    * ``"down"``     -- DB disconnected.
    * ``"ok"``       -- DB connected and no source in ``error`` /
      ``blocked``.
    * ``"degraded"`` -- DB connected but at least one source is
      ``blocked`` or in ``error``.
    """
    if not db_connected:
        return "down"
    degraded = any(s.status in {"error", "blocked"} for s in sources)
    return "degraded" if degraded else "ok"


async def _probe_http(
    *,
    name: str,
    method: str,
    url: str,
    params: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
) -> SourceStatus:
    """Issue a single short-timeout request and classify the result.

    * 200/2xx -> ``"ok"``
    * 403     -> ``"blocked"``
    * other 4xx / 5xx -> ``"error"`` (with HTTP code in detail)
    * network error / timeout -> ``"error"`` (with exception type)
    """
    checked_at = datetime.now(UTC)
    try:
        async with httpx.AsyncClient(
            timeout=_PROBE_TIMEOUT_SECONDS, follow_redirects=False
        ) as client:
            response = await client.request(
                method, url, params=params, json=json_body
            )
    except httpx.HTTPError as exc:
        return SourceStatus(
            name=name,
            status="error",
            detail=f"{type(exc).__name__}: {exc}",
            last_checked_at=checked_at,
        )
    except Exception as exc:  # defensive
        return SourceStatus(
            name=name,
            status="error",
            detail=f"{type(exc).__name__}: {exc}",
            last_checked_at=checked_at,
        )

    status_code = response.status_code
    if 200 <= status_code < 300:
        return SourceStatus(
            name=name,
            status="ok",
            detail=f"HTTP {status_code}",
            last_checked_at=checked_at,
        )
    if status_code == 403:
        return SourceStatus(
            name=name,
            status="blocked",
            detail="HTTP 403",
            last_checked_at=checked_at,
        )
    return SourceStatus(
        name=name,
        status="error",
        detail=f"HTTP {status_code}",
        last_checked_at=checked_at,
    )
