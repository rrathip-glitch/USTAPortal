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


SCHEMA_VERSION = 1

SCHEMA_SQL = """
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


def init_schema(conn: sqlite3.Connection | None = None) -> None:
    own_conn = conn is None
    conn = conn or connect()
    try:
        conn.executescript(SCHEMA_SQL)
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
    finally:
        if own_conn:
            conn.close()
