"""Round-trip tests for :class:`SyncRunRepository`.

These exercise the public surface end-to-end against the in-memory DB
fixture: ``start`` inserts a ``running`` row, ``finish`` stamps the terminal
state, and ``latest``/``recent`` return rows in the documented order.
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from src.store.repositories import SyncRunRepository


def test_start_inserts_a_running_row(in_memory_db: sqlite3.Connection) -> None:
    repo = SyncRunRepository(in_memory_db)
    run_id = repo.start(source="tennislink")

    assert run_id >= 1
    row = in_memory_db.execute(
        "SELECT status, source, finished_at, fetched_count, parsed_count, "
        "persisted_count, errored_count, error_summary, log_text "
        "FROM sync_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    assert row is not None
    (
        status,
        source,
        finished_at,
        fetched,
        parsed,
        persisted,
        errored,
        error_summary,
        log_text,
    ) = row
    assert status == "running"
    assert source == "tennislink"
    assert finished_at is None
    assert (fetched, parsed, persisted, errored) == (0, 0, 0, 0)
    assert error_summary is None
    assert log_text == ""


def test_finish_populates_status_counts_and_finished_at(
    in_memory_db: sqlite3.Connection,
) -> None:
    repo = SyncRunRepository(in_memory_db)
    run_id = repo.start(source="multi")
    repo.finish(
        run_id=run_id,
        status="ok",
        fetched=3,
        parsed=2,
        persisted=2,
        errored=0,
        error_summary=None,
        log_text="line one\nline two",
    )

    row = in_memory_db.execute(
        "SELECT status, finished_at, fetched_count, parsed_count, "
        "persisted_count, errored_count, error_summary, log_text "
        "FROM sync_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    assert row is not None
    status, finished_at, fetched, parsed, persisted, errored, error_summary, log_text = row
    assert status == "ok"
    assert finished_at is not None  # ISO-8601 string
    assert (fetched, parsed, persisted, errored) == (3, 2, 2, 0)
    assert error_summary is None
    assert log_text == "line one\nline two"


def test_finish_sets_failed_status_with_error_summary(
    in_memory_db: sqlite3.Connection,
) -> None:
    repo = SyncRunRepository(in_memory_db)
    run_id = repo.start(source="tennislink")
    repo.finish(
        run_id=run_id,
        status="failed",
        fetched=0,
        parsed=0,
        persisted=0,
        errored=1,
        error_summary="ValueError: boom",
        log_text="",
    )

    run = repo.latest()
    assert run is not None
    assert run.status == "failed"
    assert run.error_summary == "ValueError: boom"
    assert run.errored_count == 1


def test_latest_returns_the_most_recent_run(in_memory_db: sqlite3.Connection) -> None:
    repo = SyncRunRepository(in_memory_db)
    first = repo.start(source="tennislink")
    # Sleep a hair so ISO timestamps differ on systems with sub-second clocks.
    time.sleep(0.01)
    second = repo.start(source="multi")

    latest = repo.latest()
    assert latest is not None
    assert latest.id == second
    assert latest.id != first


def test_recent_returns_descending_with_limit(in_memory_db: sqlite3.Connection) -> None:
    repo = SyncRunRepository(in_memory_db)
    ids: list[int] = []
    for _ in range(7):
        ids.append(repo.start(source="tennislink"))
        time.sleep(0.001)

    runs = repo.recent(limit=5)
    assert len(runs) == 5
    # Most recent first, oldest last; the last two ids should be missing.
    returned_ids = [r.id for r in runs]
    assert returned_ids == list(reversed(ids))[:5]


def test_running_returns_first_running_row(in_memory_db: sqlite3.Connection) -> None:
    repo = SyncRunRepository(in_memory_db)
    finished_id = repo.start(source="tennislink")
    repo.finish(
        run_id=finished_id,
        status="ok",
        fetched=1,
        parsed=1,
        persisted=1,
        errored=0,
        error_summary=None,
        log_text="done",
    )
    in_flight_id = repo.start(source="multi")

    running = repo.running()
    assert running is not None
    assert running.id == in_flight_id
    assert running.status == "running"


def test_running_returns_none_when_nothing_is_running(
    in_memory_db: sqlite3.Connection,
) -> None:
    repo = SyncRunRepository(in_memory_db)
    run_id = repo.start(source="tennislink")
    repo.finish(
        run_id=run_id,
        status="ok",
        fetched=0,
        parsed=0,
        persisted=0,
        errored=0,
        error_summary=None,
        log_text="",
    )
    assert repo.running() is None


def test_update_rejects_unknown_fields(in_memory_db: sqlite3.Connection) -> None:
    repo = SyncRunRepository(in_memory_db)
    run_id = repo.start(source="tennislink")
    with pytest.raises(ValueError, match="unknown fields"):
        repo.update(run_id, surface="hard")


def test_update_patches_known_columns(in_memory_db: sqlite3.Connection) -> None:
    repo = SyncRunRepository(in_memory_db)
    run_id = repo.start(source="tennislink")
    repo.update(run_id, fetched_count=5, parsed_count=4)

    run = repo.latest()
    assert run is not None
    assert run.fetched_count == 5
    assert run.parsed_count == 4
    assert run.status == "running"  # not touched


def test_latest_is_none_for_empty_table(in_memory_db: sqlite3.Connection) -> None:
    assert SyncRunRepository(in_memory_db).latest() is None
    assert SyncRunRepository(in_memory_db).recent() == []
