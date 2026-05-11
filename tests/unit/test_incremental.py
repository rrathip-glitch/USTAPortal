"""Unit tests for :mod:`src.sync.incremental`.

Covers the :class:`IncrementalFilter` decision matrix plus the two
"recently fetched" helpers that read from the SQLite store. The DB
fixture comes from ``tests/conftest.py::in_memory_db`` — it gives us a
fully-schema'd connection without touching disk.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from src.sync.incremental import (
    IncrementalFilter,
    existing_draw_ids_recently_fetched,
    existing_tournament_ids_recently_fetched,
)

# ---------------------------------------------------------------------------
# IncrementalFilter.should_refresh
# ---------------------------------------------------------------------------


def test_should_refresh_when_last_fetched_is_none() -> None:
    now = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    f = IncrementalFilter(now=now, refresh_window=timedelta(hours=1))
    assert f.should_refresh(None) is True


def test_should_refresh_when_force_true_even_if_recent() -> None:
    now = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    recent = now - timedelta(minutes=1)
    f = IncrementalFilter(now=now, refresh_window=timedelta(hours=1), force=True)
    assert f.should_refresh(recent) is True


def test_should_not_refresh_when_inside_window() -> None:
    now = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    last = now - timedelta(minutes=30)
    f = IncrementalFilter(now=now, refresh_window=timedelta(hours=1))
    assert f.should_refresh(last) is False


def test_should_refresh_when_outside_window() -> None:
    now = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    last = now - timedelta(hours=2)
    f = IncrementalFilter(now=now, refresh_window=timedelta(hours=1))
    assert f.should_refresh(last) is True


# ---------------------------------------------------------------------------
# existing_tournament_ids_recently_fetched
# ---------------------------------------------------------------------------


def _insert_tournament(
    conn: sqlite3.Connection,
    *,
    usta_id: str,
    last_fetched_at: datetime | None,
) -> None:
    conn.execute(
        """
        INSERT INTO tournaments (usta_id, name, last_fetched_at)
        VALUES (?, ?, ?)
        """,
        (usta_id, f"Tournament {usta_id}", last_fetched_at.isoformat() if last_fetched_at else None),
    )


def _insert_draw(
    conn: sqlite3.Connection,
    *,
    usta_id: str,
    tournament_id: str,
    last_fetched_at: datetime | None,
) -> None:
    conn.execute(
        """
        INSERT INTO draws (usta_id, tournament_id, name, last_fetched_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            usta_id,
            tournament_id,
            f"Draw {usta_id}",
            last_fetched_at.isoformat() if last_fetched_at else None,
        ),
    )


def test_existing_tournament_ids_returns_recent_row(
    in_memory_db: sqlite3.Connection,
) -> None:
    now = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    _insert_tournament(in_memory_db, usta_id="t-1", last_fetched_at=now)

    one_hour_ago = now - timedelta(hours=1)
    found = existing_tournament_ids_recently_fetched(in_memory_db, since=one_hour_ago)
    assert found == {"t-1"}


def test_existing_tournament_ids_empty_when_since_is_in_the_future(
    in_memory_db: sqlite3.Connection,
) -> None:
    now = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    _insert_tournament(in_memory_db, usta_id="t-1", last_fetched_at=now)

    one_hour_ahead = now + timedelta(hours=1)
    found = existing_tournament_ids_recently_fetched(in_memory_db, since=one_hour_ahead)
    assert found == set()


def test_existing_tournament_ids_skips_null_last_fetched_at(
    in_memory_db: sqlite3.Connection,
) -> None:
    now = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    _insert_tournament(in_memory_db, usta_id="t-null", last_fetched_at=None)
    _insert_tournament(in_memory_db, usta_id="t-fresh", last_fetched_at=now)

    one_hour_ago = now - timedelta(hours=1)
    found = existing_tournament_ids_recently_fetched(in_memory_db, since=one_hour_ago)
    assert found == {"t-fresh"}


# ---------------------------------------------------------------------------
# existing_draw_ids_recently_fetched
# ---------------------------------------------------------------------------


def test_existing_draw_ids_returns_recent_row(
    in_memory_db: sqlite3.Connection,
) -> None:
    now = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    _insert_tournament(in_memory_db, usta_id="t-1", last_fetched_at=now)
    _insert_draw(in_memory_db, usta_id="t-1:d-1", tournament_id="t-1", last_fetched_at=now)

    one_hour_ago = now - timedelta(hours=1)
    found = existing_draw_ids_recently_fetched(in_memory_db, since=one_hour_ago)
    assert found == {"t-1:d-1"}


def test_existing_draw_ids_empty_when_since_is_in_the_future(
    in_memory_db: sqlite3.Connection,
) -> None:
    now = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    _insert_tournament(in_memory_db, usta_id="t-1", last_fetched_at=now)
    _insert_draw(in_memory_db, usta_id="t-1:d-1", tournament_id="t-1", last_fetched_at=now)

    one_hour_ahead = now + timedelta(hours=1)
    found = existing_draw_ids_recently_fetched(in_memory_db, since=one_hour_ahead)
    assert found == set()
