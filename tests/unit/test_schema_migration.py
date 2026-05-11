"""Schema migration tests: v1 → v2 and v2 → v3.

The v1 schema lacks the ``sync_runs`` table introduced in v2. The v2
schema lacks ``players.coach_notes`` and the ``match_journal`` table
introduced in v3. These tests apply old-style schemas to a fresh DB,
then run ``init_schema`` and verify the new artifacts appear and the
recorded version is bumped.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.store.db import SCHEMA_VERSION, init_schema

# A snapshot of the v1 ``SCHEMA_SQL`` — kept here verbatim so the migration
# test exercises the exact pre-v2 shape regardless of how the live module
# evolves. If you find yourself updating this constant in lockstep with the
# live module, you're probably testing the wrong thing.
_V1_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS players (
    usta_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    gender TEXT,
    section TEXT,
    district TEXT,
    age_category TEXT,
    profile_url TEXT,
    last_fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS tournaments (
    usta_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    level TEXT,
    sanction_body TEXT,
    start_date TEXT,
    end_date TEXT,
    location_city TEXT,
    location_state TEXT,
    surface TEXT,
    ball TEXT,
    entry_deadline TEXT,
    status TEXT,
    last_fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS draws (
    usta_id TEXT PRIMARY KEY,
    tournament_id TEXT NOT NULL REFERENCES tournaments(usta_id),
    name TEXT NOT NULL,
    format TEXT,
    size INTEGER,
    gender TEXT,
    age_group TEXT,
    division TEXT,
    status TEXT,
    last_fetched_at TEXT
);
"""


def _apply_v1(conn: sqlite3.Connection) -> None:
    conn.executescript(_V1_SCHEMA_SQL)
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('version', '1')"
    )
    conn.commit()


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def test_v1_to_v2_migration_creates_sync_runs(tmp_path: Path) -> None:
    db_path = tmp_path / "v1.db"
    conn = sqlite3.connect(db_path)
    try:
        _apply_v1(conn)
        assert not _table_exists(conn, "sync_runs"), "v1 should not have sync_runs"

        # Run the live migration.
        init_schema(conn)

        assert _table_exists(conn, "sync_runs"), "v2 must add sync_runs"

        version_row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'version'"
        ).fetchone()
        assert version_row is not None
        assert version_row[0] == str(SCHEMA_VERSION)

        # Sanity: previously-existing tables still exist and accept inserts.
        conn.execute(
            "INSERT INTO players (usta_id, full_name) VALUES (?, ?)",
            ("p-1", "Migrated Player"),
        )
        conn.commit()
        kept = conn.execute(
            "SELECT full_name FROM players WHERE usta_id = 'p-1'"
        ).fetchone()
        assert kept is not None and kept[0] == "Migrated Player"
    finally:
        conn.close()


def test_v2_init_on_fresh_db_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh.db"
    conn = sqlite3.connect(db_path)
    try:
        init_schema(conn)
        init_schema(conn)  # second call must not error

        assert _table_exists(conn, "sync_runs")
        version_row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'version'"
        ).fetchone()
        assert version_row is not None
        assert version_row[0] == str(SCHEMA_VERSION)
    finally:
        conn.close()


def test_sync_runs_index_exists_after_migration(tmp_path: Path) -> None:
    db_path = tmp_path / "indexed.db"
    conn = sqlite3.connect(db_path)
    try:
        _apply_v1(conn)
        init_schema(conn)
        idx = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND name = 'idx_sync_runs_started'"
        ).fetchone()
        assert idx is not None, "idx_sync_runs_started must exist post-migration"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# v2 → v3
# ---------------------------------------------------------------------------

# Verbatim snapshot of the v2 schema so the v2 → v3 migration is tested
# against the exact pre-v3 shape regardless of how the live module evolves.
# Mirrors ``_V1_SCHEMA_SQL`` above.
_V2_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    fetched_count INTEGER NOT NULL DEFAULT 0,
    parsed_count INTEGER NOT NULL DEFAULT 0,
    persisted_count INTEGER NOT NULL DEFAULT 0,
    errored_count INTEGER NOT NULL DEFAULT 0,
    error_summary TEXT,
    log_text TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_sync_runs_started ON sync_runs(started_at DESC);

CREATE TABLE IF NOT EXISTS players (
    usta_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    gender TEXT,
    section TEXT,
    district TEXT,
    age_category TEXT,
    profile_url TEXT,
    last_fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS tournaments (
    usta_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    level TEXT,
    sanction_body TEXT,
    start_date TEXT,
    end_date TEXT,
    location_city TEXT,
    location_state TEXT,
    surface TEXT,
    ball TEXT,
    entry_deadline TEXT,
    status TEXT,
    last_fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS draws (
    usta_id TEXT PRIMARY KEY,
    tournament_id TEXT NOT NULL REFERENCES tournaments(usta_id),
    name TEXT NOT NULL,
    format TEXT,
    size INTEGER,
    gender TEXT,
    age_group TEXT,
    division TEXT,
    status TEXT,
    last_fetched_at TEXT
);
"""


def _apply_v2(conn: sqlite3.Connection) -> None:
    conn.executescript(_V2_SCHEMA_SQL)
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('version', '2')"
    )
    conn.commit()


def _player_has_column(conn: sqlite3.Connection, column: str) -> bool:
    rows = conn.execute("PRAGMA table_info(players)").fetchall()
    return any(row[1] == column for row in rows)


def test_v3_fresh_db_has_coach_notes_and_match_journal(tmp_path: Path) -> None:
    """Test 9: applying schema to a fresh DB yields v3 artifacts."""
    db_path = tmp_path / "fresh_v3.db"
    conn = sqlite3.connect(db_path)
    try:
        init_schema(conn)
        assert _player_has_column(conn, "coach_notes"), (
            "players.coach_notes must exist on a fresh v3 DB"
        )
        assert _table_exists(conn, "match_journal"), (
            "match_journal must exist on a fresh v3 DB"
        )
    finally:
        conn.close()


def test_v2_to_v3_migration_adds_coach_notes_and_match_journal(tmp_path: Path) -> None:
    """Test 10: a DB at v2 picks up the new column and table on init_schema."""
    db_path = tmp_path / "v2.db"
    conn = sqlite3.connect(db_path)
    try:
        _apply_v2(conn)
        assert not _player_has_column(conn, "coach_notes"), (
            "v2 must not have coach_notes — guards the test setup"
        )
        assert not _table_exists(conn, "match_journal"), (
            "v2 must not have match_journal — guards the test setup"
        )

        init_schema(conn)

        assert _player_has_column(conn, "coach_notes"), (
            "v2 → v3 must add players.coach_notes"
        )
        assert _table_exists(conn, "match_journal"), (
            "v2 → v3 must create match_journal"
        )

        version_row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'version'"
        ).fetchone()
        assert version_row is not None
        assert version_row[0] == str(SCHEMA_VERSION)
        assert version_row[0] == "3"
    finally:
        conn.close()


def test_v3_init_is_idempotent(tmp_path: Path) -> None:
    """Test 11: applying init_schema twice doesn't error (ALTER COLUMN guard)."""
    db_path = tmp_path / "idempotent_v3.db"
    conn = sqlite3.connect(db_path)
    try:
        init_schema(conn)
        init_schema(conn)  # the PRAGMA guard on ADD COLUMN must hold
        assert _player_has_column(conn, "coach_notes")
        assert _table_exists(conn, "match_journal")
    finally:
        conn.close()
