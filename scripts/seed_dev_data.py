"""Seed a fresh local DB with synthetic fixtures for development.

Lets you spin up the dashboard end-to-end without ever touching the real USTA
site. Every entity is stamped with id prefix `dev-` so it's never confused
with real data.

Usage:
    python scripts/seed_dev_data.py
"""

from __future__ import annotations

from src.store.db import connect, init_schema


def main() -> int:
    init_schema()
    conn = connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO players(usta_id, full_name, gender) VALUES (?, ?, ?)",
            ("dev-player-001", "Janav Thasen (dev)", "M"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO players(usta_id, full_name, gender) VALUES (?, ?, ?)",
            ("dev-player-002", "Test Opponent", "M"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO tournaments(usta_id, name, status) VALUES (?, ?, ?)",
            ("dev-tourney-001", "Dev Tournament", "upcoming"),
        )
        conn.commit()
        print("Seeded dev data.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
