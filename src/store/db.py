"""SQLite connection and schema management.

For v1 we hand-roll the schema with raw SQL because the data model is small
and stable, the ergonomics of SQLAlchemy ORM aren't earning their complexity
yet, and being close to the SQL helps when debugging schema-drift fallout.

If the model grows past ~12 tables or we need richer migrations, switch to
SQLAlchemy 2.x + Alembic. ADR-002 (deferred) will record that decision.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.config import settings


SCHEMA_VERSION = 2

SCHEMA_SQL = """
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

CREATE TABLE IF NOT EXISTS draw_entries (
    draw_id TEXT NOT NULL REFERENCES draws(usta_id),
    player_id TEXT NOT NULL REFERENCES players(usta_id),
    seed INTEGER,
    position INTEGER,
    status TEXT,
    PRIMARY KEY (draw_id, player_id)
);

CREATE TABLE IF NOT EXISTS matches (
    usta_id TEXT PRIMARY KEY,
    draw_id TEXT NOT NULL REFERENCES draws(usta_id),
    round TEXT,
    scheduled_at TEXT,
    court TEXT,
    player_a_id TEXT,
    player_b_id TEXT,
    score_raw TEXT,
    sets_json TEXT,
    outcome TEXT,
    winner_id TEXT,
    last_fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS ranking_snapshots (
    player_id TEXT NOT NULL REFERENCES players(usta_id),
    category TEXT NOT NULL,
    scope TEXT NOT NULL,
    section TEXT,
    position INTEGER,
    points REAL,
    as_of TEXT NOT NULL,
    PRIMARY KEY (player_id, category, scope, as_of)
);

CREATE TABLE IF NOT EXISTS wtn_snapshots (
    player_id TEXT NOT NULL REFERENCES players(usta_id),
    type TEXT NOT NULL,
    value REAL NOT NULL,
    confidence REAL,
    as_of TEXT NOT NULL,
    PRIMARY KEY (player_id, type, as_of)
);

CREATE INDEX IF NOT EXISTS idx_matches_draw ON matches(draw_id);
CREATE INDEX IF NOT EXISTS idx_matches_player_a ON matches(player_a_id);
CREATE INDEX IF NOT EXISTS idx_matches_player_b ON matches(player_b_id);
"""


def db_path() -> Path:
    url = settings.database_url
    if url.startswith("sqlite:///"):
        return Path(url.replace("sqlite:///", "", 1))
    raise ValueError(f"Unsupported DATABASE_URL: {url}")


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _current_schema_version(conn: sqlite3.Connection) -> int | None:
    """Return the recorded schema version, or ``None`` for a fresh DB.

    Treats a missing ``schema_meta`` table or a missing ``version`` row as
    "unknown" (None). A row that fails to parse as an int is also None.
    """
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


def init_schema(conn: sqlite3.Connection | None = None) -> None:
    """Apply the current schema, running idempotent migrations as needed.

    The schema is structured so that every ``CREATE`` is gated on
    ``IF NOT EXISTS``; running this on a fresh DB or against a v1 DB
    converges on the same end state. The ``schema_meta.version`` row is
    bumped to :data:`SCHEMA_VERSION` after the script runs.

    Migrations performed:

    - **v1 → v2:** add ``sync_runs`` table and its index. No data migration
      is required because the table is new and only operational metadata —
      no historical reconstruction needed.
    """
    own_conn = conn is None
    conn = conn or connect()
    try:
        previous_version = _current_schema_version(conn)
        conn.executescript(SCHEMA_SQL)

        # v1 → v2: the new ``sync_runs`` table is created by the script
        # above (CREATE TABLE IF NOT EXISTS). No data migration; just bump
        # the recorded version below.
        if previous_version is not None and previous_version < SCHEMA_VERSION:
            # Reserved spot for future destructive migrations; v1→v2 is
            # idempotent so nothing runs here today.
            pass

        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
    finally:
        if own_conn:
            conn.close()
