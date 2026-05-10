"""Tests for the Janav-centered dev seeder.

Runs the seeder against a temp SQLite DB (via the in-memory connection
fixture and a temp-file variant) and asserts that:

1. Row counts match the seeder's reported summary.
2. Janav is present with the expected profile fields.
3. The matches Janav played are retrievable by player ID.
4. WTN and ranking snapshots are queryable.
5. Re-running the seeder is a no-op (idempotent).
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
    TournamentRepository,
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
        # Sanity: counts match the row totals in the DB.
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
    finally:
        conn.close()


def test_seed_meets_minimum_volume() -> None:
    """The seeder must produce enough data for the dashboard to render."""
    conn = _fresh_conn()
    try:
        counts = seed(conn)
        # Spec floor: 5+ opponents, 3+ tournaments, 8+ matches.
        assert counts["players"] >= 6  # Janav + 5 opponents
        assert counts["tournaments"] >= 3
        assert counts["matches"] >= 8
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
        assert janav.age_category == "Boys' 12s"
        assert janav.profile_url is not None
        assert janav.profile_url.startswith("synthetic://")
        assert janav.last_fetched_at is not None
    finally:
        conn.close()


def test_seed_creates_matches_for_janav() -> None:
    conn = _fresh_conn()
    try:
        seed(conn)
        matches = MatchRepository(conn).list_for_player(JANAV_USTA_ID)
        assert len(matches) >= 8
        # Every match references Janav on one side.
        for m in matches:
            assert JANAV_USTA_ID in {m.player_a_id, m.player_b_id}
        # At least one match has a parsed score (non-empty sets).
        assert any(m.sets for m in matches)
        # At least one completed match has Janav as winner.
        assert any(m.winner_id == JANAV_USTA_ID for m in matches)
        # At least one completed match has Janav as loser.
        assert any(
            m.outcome == "completed" and m.winner_id is not None and m.winner_id != JANAV_USTA_ID
            for m in matches
        )
    finally:
        conn.close()


def test_seed_creates_upcoming_tournament() -> None:
    conn = _fresh_conn()
    try:
        seed(conn)
        upcoming = TournamentRepository(conn).list_upcoming()
        assert len(upcoming) >= 1
    finally:
        conn.close()


def test_seed_creates_wtn_history_for_janav() -> None:
    conn = _fresh_conn()
    try:
        seed(conn)
        repo = WTNSnapshotRepository(conn)
        singles_history = repo.history_for_player(JANAV_USTA_ID, "singles")
        doubles_history = repo.history_for_player(JANAV_USTA_ID, "doubles")
        assert len(singles_history) >= 2
        assert len(doubles_history) >= 1
        # WTN values plausible for a competitive U12 (band 10-25).
        for snap in singles_history + doubles_history:
            assert 10.0 <= snap.value <= 30.0
    finally:
        conn.close()


def test_seed_creates_ranking_history_for_janav() -> None:
    conn = _fresh_conn()
    try:
        seed(conn)
        history = RankingSnapshotRepository(conn).history_for_player(
            JANAV_USTA_ID, "Boys 12 Singles"
        )
        assert len(history) >= 2
        # History should be in ascending date order.
        assert history == sorted(history, key=lambda s: s.as_of)
    finally:
        conn.close()


def test_seed_draws_link_to_tournaments() -> None:
    conn = _fresh_conn()
    try:
        seed(conn)
        tournaments = list(conn.execute("SELECT usta_id FROM tournaments").fetchall())
        draw_repo = DrawRepository(conn)
        for (tid,) in tournaments:
            draws = draw_repo.list_for_tournament(tid)
            assert len(draws) >= 1, f"tournament {tid} has no draws"
    finally:
        conn.close()


def test_seed_is_idempotent() -> None:
    conn = _fresh_conn()
    try:
        first = seed(conn)
        second = seed(conn)
        assert first == second
        # Row counts unchanged after the second run.
        for table, key in (
            ("players", "players"),
            ("tournaments", "tournaments"),
            ("draws", "draws"),
            ("matches", "matches"),
            ("draw_entries", "draw_entries"),
            ("wtn_snapshots", "wtn_snapshots"),
            ("ranking_snapshots", "ranking_snapshots"),
        ):
            actual = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert actual == second[key], f"{table} count drifted on re-seed"
    finally:
        conn.close()


def test_seed_against_temp_file_db(tmp_path: Path, monkeypatch) -> None:
    """End-to-end run against a real on-disk SQLite path.

    Patches the configured database_url so ``seed()`` (the no-argument
    form) writes to a temp file and verifies the schema + row counts.
    """
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
        # Schema version row landed.
        version = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'version'"
        ).fetchone()
        assert version is not None
    finally:
        conn.close()
