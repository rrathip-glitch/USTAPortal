"""Schema smoke test — verifies the SQL applies cleanly to a fresh DB."""

from __future__ import annotations

import sqlite3


def test_schema_applies(in_memory_db: sqlite3.Connection) -> None:
    cursor = in_memory_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {row[0] for row in cursor.fetchall()}
    expected = {
        "schema_meta",
        "players",
        "tournaments",
        "draws",
        "draw_entries",
        "matches",
        "ranking_snapshots",
        "wtn_snapshots",
    }
    assert expected.issubset(tables), f"missing: {expected - tables}"
