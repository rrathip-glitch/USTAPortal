"""Smoke test that the FastAPI app boots and /health responds, plus unit
tests for the :mod:`src.observability` scaffold that the route layer
delegates to."""

from __future__ import annotations

import json
import sqlite3

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from src import observability
from src.main import app
from src.observability import (
    HealthSnapshot,
    SourceStatus,
    health_snapshot,
    probe_source,
)
from src.observability.health import SOURCE_NAMES
from src.store.db import SCHEMA_VERSION, init_schema

# ---------------------------------------------------------------------------
# Legacy endpoint smoke tests (kept for parity with the simple /health shape).
# The follow-up agent will replace the endpoint body to use
# ``health_snapshot``; until then these continue to exercise the wiring.
# ---------------------------------------------------------------------------


def test_health_returns_ok() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "checked_at" in body


def test_index_renders() -> None:
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "USTA Portal" in response.text


# ---------------------------------------------------------------------------
# health_snapshot()
# ---------------------------------------------------------------------------


def test_health_snapshot_without_conn_reports_down() -> None:
    snap = health_snapshot(conn=None)
    assert isinstance(snap, HealthSnapshot)
    assert snap.db_connected is False
    assert snap.overall_status == "down"
    assert snap.schema_version is None
    assert snap.latest_sync_at is None
    assert snap.latest_sync_status is None
    # Sources are populated with placeholder entries even without probing.
    assert {s.name for s in snap.sources} == set(SOURCE_NAMES)
    assert {s.status for s in snap.sources} <= {"unknown", "deferred"}


def test_health_snapshot_with_conn_reports_ok(
    in_memory_db: sqlite3.Connection,
) -> None:
    # The shared fixture only executes SCHEMA_SQL — bump the
    # version row through ``init_schema`` so the snapshot picks
    # it up.
    init_schema(in_memory_db)
    snap = health_snapshot(conn=in_memory_db)
    assert snap.db_connected is True
    assert snap.schema_version is not None
    assert snap.schema_version >= 2
    assert snap.latest_sync_at is None
    assert snap.latest_sync_status is None
    assert snap.overall_status == "ok"


def test_health_snapshot_picks_up_latest_sync_run(
    in_memory_db: sqlite3.Connection,
) -> None:
    init_schema(in_memory_db)
    started_at = "2026-05-11T12:00:00+00:00"
    in_memory_db.execute(
        "INSERT INTO sync_runs (started_at, source, status) "
        "VALUES (?, 'usta_api', 'ok')",
        (started_at,),
    )
    in_memory_db.commit()
    snap = health_snapshot(conn=in_memory_db)
    assert snap.latest_sync_status == "ok"
    assert snap.latest_sync_at is not None
    assert snap.latest_sync_at.isoformat() == started_at


def test_health_snapshot_model_dump_is_json_serialisable(
    in_memory_db: sqlite3.Connection,
) -> None:
    init_schema(in_memory_db)
    in_memory_db.execute(
        "INSERT INTO sync_runs (started_at, source, status) "
        "VALUES ('2026-05-11T12:00:00+00:00', 'usta_api', 'ok')"
    )
    in_memory_db.commit()
    snap = health_snapshot(conn=in_memory_db)
    payload = snap.model_dump()
    # Must round-trip through json.dumps without a custom encoder.
    encoded = json.dumps(payload)
    decoded = json.loads(encoded)
    assert decoded["overall_status"] == "ok"
    assert decoded["db_connected"] is True
    assert decoded["latest_sync_status"] == "ok"
    assert decoded["schema_version"] == SCHEMA_VERSION
    assert isinstance(decoded["sources"], list)
    assert "generated_at" in decoded


def test_health_snapshot_does_not_probe_when_probe_sources_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default ``probe_sources=False`` must not touch the network.

    We replace ``probe_source`` with a sentinel that raises if called
    and assert the snapshot still builds cleanly.
    """
    sentinel_called = False

    async def _sentinel(name: str) -> SourceStatus:
        nonlocal sentinel_called
        sentinel_called = True
        raise AssertionError("probe_source must not be called when probe_sources=False")

    monkeypatch.setattr(observability.health, "probe_source", _sentinel)
    snap = health_snapshot(conn=None, probe_sources=False)
    assert sentinel_called is False
    # Without probing the source entries are placeholders.
    statuses = {s.name: s.status for s in snap.sources}
    assert statuses["clubspark"] == "deferred"
    for other in ("usta_api", "tennislink", "coretennis", "utr"):
        assert statuses[other] == "unknown"


# ---------------------------------------------------------------------------
# probe_source()
# ---------------------------------------------------------------------------


async def test_probe_source_clubspark_is_deferred_without_network() -> None:
    # No respx mock; if this attempts to make a network call it will
    # raise (and the test will fail).
    result = await probe_source("clubspark")
    assert result.name == "clubspark"
    assert result.status == "deferred"
    assert result.last_checked_at is not None


async def test_probe_source_usta_api_ok() -> None:
    from src.fetch.usta_api_client import (
        BASE_URL as USTA_BASE,
    )
    from src.fetch.usta_api_client import (
        PATH_TOURNAMENTS_QUERY as USTA_PATH,
    )

    with respx.mock(assert_all_called=True) as mock:
        mock.post(f"{USTA_BASE}{USTA_PATH}").mock(
            return_value=httpx.Response(200, json={"hits": {"hits": []}})
        )
        result = await probe_source("usta_api")
    assert result.name == "usta_api"
    assert result.status == "ok"
    assert result.detail == "HTTP 200"


async def test_probe_source_usta_api_blocked_on_403() -> None:
    from src.fetch.usta_api_client import (
        BASE_URL as USTA_BASE,
    )
    from src.fetch.usta_api_client import (
        PATH_TOURNAMENTS_QUERY as USTA_PATH,
    )

    with respx.mock(assert_all_called=True) as mock:
        mock.post(f"{USTA_BASE}{USTA_PATH}").mock(
            return_value=httpx.Response(403, text="Forbidden")
        )
        result = await probe_source("usta_api")
    assert result.name == "usta_api"
    assert result.status == "blocked"
    assert result.detail == "HTTP 403"
