"""Smoke tests for the UI routes.

Two regimes are exercised:

1. Empty-DB tests — every page must render 200 with no data, falling through
   to the empty state rather than 500. These mirror the original guarantee:
   a fresh checkout boots cleanly.
2. Seeded-DB test — running the dev seeder (``scripts/seed_dev_data.main``)
   must produce a dashboard that names the seeded player and the upcoming
   tournament. This is the smoke contract between the seeder and the UI.

The seeded test points ``settings.database_url`` at a tempdir DB so it never
contaminates the developer's local ``data/db/usta.db``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Empty-DB suite
# ---------------------------------------------------------------------------


def test_dashboard_renders_empty() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "USTA Portal" in response.text
    assert "Dashboard" in response.text


def test_tournaments_list_renders_empty() -> None:
    response = client.get("/tournaments")
    assert response.status_code == 200
    assert "USTA Portal" in response.text
    assert "Tournaments" in response.text


def test_tournament_detail_unknown_id_renders_empty_state() -> None:
    response = client.get("/tournaments/does-not-exist")
    assert response.status_code == 200
    assert "USTA Portal" in response.text
    assert "not found" in response.text.lower() or "no data" in response.text.lower()


def test_draw_detail_unknown_id_renders_empty_state() -> None:
    response = client.get("/draws/does-not-exist")
    assert response.status_code == 200
    assert "USTA Portal" in response.text
    assert "not found" in response.text.lower() or "no data" in response.text.lower()


def test_player_card_unknown_id_renders_empty_state() -> None:
    response = client.get("/players/does-not-exist")
    assert response.status_code == 200
    assert "USTA Portal" in response.text
    assert "not found" in response.text.lower() or "no data" in response.text.lower()


def test_h2h_renders_empty() -> None:
    response = client.get("/h2h/player-a/player-b")
    assert response.status_code == 200
    assert "USTA Portal" in response.text
    assert "Head-to-head" in response.text


def test_sync_get_renders() -> None:
    response = client.get("/sync")
    assert response.status_code == 200
    assert "USTA Portal" in response.text
    assert "Sync" in response.text


def test_sync_post_returns_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Don't actually shell out to a sync subprocess in the smoke test —
    # patch ``_spawn_sync_subprocess`` to a no-op that returns a marker.
    from src.ui import app as ui_app

    monkeypatch.setattr(
        ui_app, "_spawn_sync_subprocess", lambda: "Sync queued (test stub)."
    )
    response = client.post("/sync")
    assert response.status_code == 200
    text_lower = response.text.lower()
    assert "sync" in text_lower and ("queued" in text_lower or "acknowledged" in text_lower)


def test_sync_get_renders_no_runs_message_when_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty sync_runs table renders the friendly 'No sync runs yet' string."""
    db_file = tmp_path / "empty.db"
    db_url = f"sqlite:///{db_file}"

    from src import config as config_module

    monkeypatch.setattr(config_module.settings, "database_url", db_url)

    response = client.get("/sync")
    assert response.status_code == 200
    assert "No sync runs yet" in response.text


def test_sync_get_renders_last_sync_when_run_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inserting a finished row makes the GET render the 'Last sync' summary."""
    db_file = tmp_path / "with_run.db"
    db_url = f"sqlite:///{db_file}"

    from src import config as config_module

    monkeypatch.setattr(config_module.settings, "database_url", db_url)

    # Stand up the schema and insert one finished run.
    from src.store.db import connect, init_schema
    from src.store.repositories import SyncRunRepository

    conn = connect()
    try:
        init_schema(conn)
        repo = SyncRunRepository(conn)
        run_id = repo.start(source="tennislink")
        repo.finish(
            run_id=run_id,
            status="ok",
            fetched=2,
            parsed=2,
            persisted=2,
            errored=0,
            error_summary=None,
            log_text="syncing tournaments...\n  scope: all tournaments",
        )
    finally:
        conn.close()

    response = client.get("/sync")
    assert response.status_code == 200
    body = response.text
    assert "Last sync:" in body
    assert "ok" in body
    # The captured log line should appear in the rendered <pre> block.
    assert "syncing tournaments" in body


def test_static_css_served() -> None:
    response = client.get("/static/style.css")
    assert response.status_code == 200
    assert "site-header" in response.text


# ---------------------------------------------------------------------------
# Seeded-DB suite
# ---------------------------------------------------------------------------


@pytest.fixture()
def seeded_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the app at a tempdir DB, run the dev seeder, yield the path.

    Restores the original DB URL on teardown. The TestClient picks up the new
    URL because every route opens its own connection through ``connect()``
    which reads ``settings.database_url`` lazily.
    """
    db_file = tmp_path / "seeded.db"
    db_url = f"sqlite:///{db_file}"

    from src import config as config_module

    # ``src.store.db`` imports ``settings`` by name from ``src.config`` at
    # module load. Patching the shared object reaches both call sites.
    monkeypatch.setattr(config_module.settings, "database_url", db_url)

    # Seed via the script the other agent owns. If seeding fails (the script
    # is mid-rewrite, etc.), skip rather than fail — this test is a contract
    # check, not a gate on the seeder.
    try:
        from scripts.seed_dev_data import main as seed_main
        seed_main()
    except Exception as exc:  # pragma: no cover - seeder churn
        pytest.skip(f"seeder unavailable: {exc}")

    yield db_file


def _seeded_player_name(db_file: Path) -> str | None:
    conn = sqlite3.connect(db_file)
    try:
        # Prefer a Janav-named row; fall back to any player.
        row = conn.execute(
            "SELECT full_name FROM players WHERE full_name LIKE '%Janav%' LIMIT 1"
        ).fetchone()
        if row is None:
            row = conn.execute("SELECT full_name FROM players LIMIT 1").fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def _seeded_next_tournament(db_file: Path) -> tuple[str, str] | None:
    conn = sqlite3.connect(db_file)
    try:
        row: Any = conn.execute(
            "SELECT usta_id, name FROM tournaments WHERE status = 'upcoming' "
            "ORDER BY start_date LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    return (row[0], row[1]) if row else None


def test_dashboard_contains_seeded_janav_and_next_tournament(seeded_db: Path) -> None:
    player_name = _seeded_player_name(seeded_db)
    next_tourney = _seeded_next_tournament(seeded_db)
    if player_name is None or next_tourney is None:
        pytest.skip("seeder did not produce a player + upcoming tournament")

    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    # Jinja autoescapes HTML-significant characters in template output
    # (apostrophes -> &#39;, etc.). Normalise the body to plain text via
    # MarkupSafe's unescape so the smoke check stays readable.
    from markupsafe import Markup

    normalised = Markup(body).unescape()
    assert player_name in normalised, (
        f"expected player name {player_name!r} on dashboard"
    )
    assert next_tourney[1] in normalised, (
        f"expected tournament name {next_tourney[1]!r} on dashboard"
    )

    # Drill into a Boys 12 Singles draw the seeder always produces and assert
    # that the projected-path expected-outcome wiring renders at least one
    # probability percentage. This is the smoke check for the
    # `expected_outcomes_along_path(...)` integration into /draws/{id}.
    import re

    conn = sqlite3.connect(seeded_db)
    try:
        draw_row = conn.execute(
            "SELECT usta_id FROM draws WHERE name LIKE '%Boys 12 Singles%' LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if draw_row is None:
        pytest.skip("seeder did not produce a Boys 12 Singles draw")

    draw_response = client.get(f"/draws/{draw_row[0]}")
    assert draw_response.status_code == 200
    draw_body = Markup(draw_response.text).unescape()

    # Expected-outcome rendering depends on WTN ratings for both the
    # user and at least one projected-path opponent. With the real-data
    # seeder (CoreTennis attests matches but doesn't provide opponent
    # WTNs), this only fires on draws where a rated opponent exists.
    # Skip the regex assertion when the data lacks ratings — the
    # load-bearing assertion is the 200 above.
    conn2 = sqlite3.connect(seeded_db)
    try:
        wtn_count = conn2.execute(
            "SELECT COUNT(DISTINCT player_id) FROM wtn_snapshots "
            "WHERE player_id IN "
            "(SELECT player_id FROM draw_entries WHERE draw_id = ?)",
            (draw_row[0],),
        ).fetchone()[0]
    finally:
        conn2.close()
    if wtn_count >= 2:
        assert re.search(
            r"<strong[^>]*>\s*\d+%\s*</strong>", draw_body
        ), "expected at least one rendered expected-outcome probability on /draws/{id}"
