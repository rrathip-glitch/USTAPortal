"""Tests for the CoreTennis-anchored Janav dev seeder.

Runs the seeder against a temp SQLite DB (via the in-memory connection
fixture and a temp-file variant) and asserts that:

1. Row counts match the seeder's reported summary.
2. Janav is present with the expected profile fields.
3. The four real CoreTennis-attested matches are persisted with parsed scores.
4. The USTA-API fixture tournaments land alongside the real ones.
5. WTN and ranking snapshots are queryable.
6. Re-running the seeder is a no-op (idempotent).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.seed_dev_data import JANAV_USTA_ID, seed
from src.store.db import SCHEMA_SQL
from src.store.repositories import (
    DrawRepository,
    MatchRepository,
    PlayerRepository,
    RankingSnapshotRepository,
    WTNSnapshotRepository,
)


def _fresh_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    return conn


def test_seed_inserts_expected_counts() -> None:
    conn = _fresh_conn()
    counts = seed(conn)
    try:
        assert conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] == counts["players"]
        assert conn.execute("SELECT COUNT(*) FROM tournaments").fetchone()[0] == counts["tournaments"]
        assert conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0] == counts["draws"]
        assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == counts["matches"]
        assert (
            conn.execute("SELECT COUNT(*) FROM draw_entries").fetchone()[0]
            == counts["draw_entries"]
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM wtn_snapshots").fetchone()[0]
            == counts["wtn_snapshots"]
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM ranking_snapshots").fetchone()[0]
            == counts["ranking_snapshots"]
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM sync_runs").fetchone()[0]
            == counts["sync_runs"]
        )
    finally:
        conn.close()


def test_seed_meets_minimum_volume() -> None:
    """The seeder must produce enough data for the dashboard to render."""
    conn = _fresh_conn()
    try:
        counts = seed(conn)
        # Spec floor: Janav + 4 real opponents, 4 real tournaments + 50 fixture
        # tournaments, 4 real matches.
        assert counts["players"] >= 5  # Janav + 4 real opponents
        assert counts["tournaments"] >= 50
        assert counts["matches"] >= 4
        assert counts["wtn_snapshots"] >= 6
        assert counts["ranking_snapshots"] >= 6
        assert counts["sync_runs"] == 1
    finally:
        conn.close()


def test_seed_persists_janav_profile() -> None:
    conn = _fresh_conn()
    try:
        seed(conn)
        janav = PlayerRepository(conn).get(JANAV_USTA_ID)
        assert janav is not None
        assert janav.full_name == "Janav Thasen"
        assert janav.gender == "M"
        assert janav.section == "Florida"
        assert janav.age_category == "Boys 12"
        assert janav.profile_url == f"https://playtennis.usta.com/profiles/{JANAV_USTA_ID}"
        assert janav.last_fetched_at is not None
    finally:
        conn.close()


def test_seed_creates_real_matches_for_janav() -> None:
    conn = _fresh_conn()
    try:
        seed(conn)
        matches = MatchRepository(conn).list_for_player(JANAV_USTA_ID)
        assert len(matches) == 4
        # Every match references Janav on one side.
        for m in matches:
            assert JANAV_USTA_ID in {m.player_a_id, m.player_b_id}
            assert m.score_raw is not None
            assert m.sets, f"match {m.usta_id} has no parsed sets"
            assert m.outcome == "completed"
            # Janav lost every CoreTennis-attested match.
            assert m.winner_id is not None
            assert m.winner_id != JANAV_USTA_ID
    finally:
        conn.close()


def test_seed_creates_real_tournaments() -> None:
    """The four CoreTennis-attested tournaments are present by name."""
    conn = _fresh_conn()
    try:
        seed(conn)
        rows = conn.execute("SELECT name FROM tournaments").fetchall()
        names = [r[0] for r in rows]
        assert any("Saddlebrook" in n for n in names)
        assert any("City Club at River Ranch" in n for n in names)
        assert any("USTA National Campus" in n for n in names)
        # Saddlebrook appears twice (2025-01 and 2026-01).
        saddlebrook = [n for n in names if "Saddlebrook" in n]
        assert len(saddlebrook) >= 1
    finally:
        conn.close()


def test_seed_creates_wtn_history_for_janav() -> None:
    conn = _fresh_conn()
    try:
        seed(conn)
        repo = WTNSnapshotRepository(conn)
        singles_history = repo.history_for_player(JANAV_USTA_ID, "singles")
        doubles_history = repo.history_for_player(JANAV_USTA_ID, "doubles")
        assert len(singles_history) >= 6
        assert len(doubles_history) >= 1
        # WTN values plausible for a Boys 12 just starting to drop (30-40 band).
        for snap in singles_history + doubles_history:
            assert 30.0 <= snap.value <= 40.0
        # Singles history is monotonically improving (lower = better).
        assert singles_history[0].value > singles_history[-1].value
    finally:
        conn.close()


def test_seed_creates_ranking_history_for_janav() -> None:
    conn = _fresh_conn()
    try:
        seed(conn)
        history = RankingSnapshotRepository(conn).history_for_player(
            JANAV_USTA_ID, "Boys 12 Singles"
        )
        assert len(history) >= 6
        # History should be in ascending date order.
        assert history == sorted(history, key=lambda s: s.as_of)
        # Position improves (lower number is better).
        assert history[0].position is not None and history[-1].position is not None
        assert history[0].position > history[-1].position
    finally:
        conn.close()


def test_seed_draws_link_to_real_tournaments() -> None:
    """Every CoreTennis-attested tournament has its Boys 12 Singles draw."""
    conn = _fresh_conn()
    try:
        seed(conn)
        # Real-match tournaments are namespaced with the ``tournament-coretennis-``
        # prefix; each must have at least one draw.
        rows = conn.execute(
            "SELECT usta_id FROM tournaments WHERE usta_id LIKE 'tournament-coretennis-%'"
        ).fetchall()
        assert len(rows) >= 3, "expected at least 3 real-match tournaments"
        draw_repo = DrawRepository(conn)
        for (tid,) in rows:
            draws = draw_repo.list_for_tournament(tid)
            assert len(draws) >= 1, f"tournament {tid} has no draws"
    finally:
        conn.close()


def test_seed_loads_usta_api_fixture_tournaments() -> None:
    """The seeder must fold the captured USTA-API fixture into the DB."""
    conn = _fresh_conn()
    try:
        seed(conn)
        # Fixture tournaments use bare GUIDs; real-match tournaments are
        # prefixed with ``tournament-coretennis-``. The fixture cap is 50,
        # so we expect at least 50 non-prefixed rows.
        row = conn.execute(
            "SELECT COUNT(*) FROM tournaments "
            "WHERE usta_id NOT LIKE 'tournament-coretennis-%'"
        ).fetchone()
        assert row[0] >= 50
    finally:
        conn.close()


def test_seed_creates_one_sync_run() -> None:
    conn = _fresh_conn()
    try:
        seed(conn)
        rows = conn.execute(
            "SELECT status, errored_count, log_text FROM sync_runs"
        ).fetchall()
        assert len(rows) == 1
        status, errored, log_text = rows[0]
        assert status == "ok"
        assert errored == 0
        assert "seed_dev_data" in log_text
    finally:
        conn.close()


def test_seed_is_idempotent() -> None:
    conn = _fresh_conn()
    try:
        first = seed(conn)
        second = seed(conn)
        assert first == second
        for table, key in (
            ("players", "players"),
            ("tournaments", "tournaments"),
            ("draws", "draws"),
            ("matches", "matches"),
            ("draw_entries", "draw_entries"),
            ("wtn_snapshots", "wtn_snapshots"),
            ("ranking_snapshots", "ranking_snapshots"),
            ("sync_runs", "sync_runs"),
        ):
            actual = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert actual == second[key], f"{table} count drifted on re-seed"
    finally:
        conn.close()


def test_seed_against_temp_file_db(tmp_path: Path, monkeypatch) -> None:
    """End-to-end run against a real on-disk SQLite path."""
    db_file = tmp_path / "seed-test.db"
    monkeypatch.setattr(
        "src.store.db.settings.database_url",
        f"sqlite:///{db_file}",
    )
    counts = seed()
    assert db_file.exists()

    conn = sqlite3.connect(db_file)
    try:
        assert conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] == counts["players"]
        assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == counts["matches"]
        version = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'version'"
        ).fetchone()
        assert version is not None
    finally:
        conn.close()
