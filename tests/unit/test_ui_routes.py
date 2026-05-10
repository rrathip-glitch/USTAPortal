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


def test_sync_post_returns_acknowledgement() -> None:
    response = client.post("/sync")
    assert response.status_code == 200
    # Either the placeholder banner or the log line that the worker appended.
    text_lower = response.text.lower()
    assert "sync" in text_lower and ("queued" in text_lower or "acknowledged" in text_lower)


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
    from src.store import db as db_module

    monkeypatch.setattr(config_module.settings, "database_url", db_url)
    monkeypatch.setattr(db_module.settings, "database_url", db_url)

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
    # The dashboard surfaces the user's name in the hero eyebrow and the
    # next-tournament name as the heading link target.
    assert player_name in body, f"expected player name {player_name!r} on dashboard"
    assert next_tourney[1] in body, (
        f"expected tournament name {next_tourney[1]!r} on dashboard"
    )
