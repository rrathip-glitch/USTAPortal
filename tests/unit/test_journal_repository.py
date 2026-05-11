"""Tests for :class:`MatchJournalRepository`.

The journal table is keyed by ``(player_id, match_id)`` and stores
post-match notes from the player's perspective. These tests exercise
upsert semantics (id stable, ``created_at`` preserved, ``updated_at``
advanced), tag JSON round-trip, NFC normalization on the body, and the
``self_rating`` Pydantic bounds (1..5).
"""

from __future__ import annotations

import sqlite3
import time
import unicodedata
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.models.journal import MatchJournalEntry
from src.models.player import Player
from src.store.repositories import MatchJournalRepository, PlayerRepository

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _seed_player(conn: sqlite3.Connection, usta_id: str = "janav") -> None:
    PlayerRepository(conn).upsert(
        Player(usta_id=usta_id, full_name=f"Player {usta_id}")
    )


def _entry(
    *,
    player_id: str = "janav",
    match_id: str | None = "m-1",
    body: str = "Played a clean baseline match.",
    self_rating: int | None = 4,
    tags: list[str] | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> MatchJournalEntry:
    now = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    return MatchJournalEntry(
        match_id=match_id,
        player_id=player_id,
        created_at=created_at or now,
        updated_at=updated_at or now,
        body=body,
        self_rating=self_rating,
        tags=tags if tags is not None else ["serve", "forehand"],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_journal_insert_and_get(in_memory_db: sqlite3.Connection) -> None:
    """Test 1: insert returns an id; get by id round-trips the entry."""
    _seed_player(in_memory_db)
    repo = MatchJournalRepository(in_memory_db)

    entry = _entry()
    new_id = repo.upsert(entry)
    assert isinstance(new_id, int)
    assert new_id > 0

    loaded = repo.get(new_id)
    assert loaded is not None
    assert loaded.id == new_id
    assert loaded.player_id == "janav"
    assert loaded.match_id == "m-1"
    assert loaded.body == "Played a clean baseline match."
    assert loaded.self_rating == 4
    assert loaded.tags == ["serve", "forehand"]


def test_journal_upsert_twice_keeps_id_and_created_at(
    in_memory_db: sqlite3.Connection,
) -> None:
    """Test 2: re-upserting (player_id, match_id) updates in place.

    ``id`` is stable, ``body`` is updated, ``created_at`` is preserved,
    ``updated_at`` is advanced.
    """
    _seed_player(in_memory_db)
    repo = MatchJournalRepository(in_memory_db)

    first = _entry(body="initial")
    first_id = repo.upsert(first)
    loaded_first = repo.get(first_id)
    assert loaded_first is not None
    created_at_first = loaded_first.created_at
    updated_at_first = loaded_first.updated_at

    # Sleep just long enough for the ISO-8601 microsecond stamp to change.
    time.sleep(0.01)

    second = _entry(body="revised")
    second_id = repo.upsert(second)
    assert second_id == first_id, "upsert must return the same row id"

    loaded_second = repo.get(second_id)
    assert loaded_second is not None
    assert loaded_second.body == "revised"
    assert loaded_second.created_at == created_at_first, (
        "created_at must be preserved across updates"
    )
    assert loaded_second.updated_at > updated_at_first, (
        "updated_at must advance on update"
    )


def test_journal_list_for_player_orders_by_created_at_desc(
    in_memory_db: sqlite3.Connection,
) -> None:
    """Test 3: list_for_player returns most-recent-first."""
    _seed_player(in_memory_db)
    repo = MatchJournalRepository(in_memory_db)

    earlier = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    later = datetime(2026, 5, 10, 10, 0, tzinfo=UTC)
    middle = datetime(2026, 5, 5, 10, 0, tzinfo=UTC)

    repo.upsert(_entry(match_id="m-a", created_at=earlier, updated_at=earlier))
    repo.upsert(_entry(match_id="m-b", created_at=later, updated_at=later))
    repo.upsert(_entry(match_id="m-c", created_at=middle, updated_at=middle))

    entries = repo.list_for_player("janav")
    match_ids = [e.match_id for e in entries]
    assert match_ids == ["m-b", "m-c", "m-a"]


def test_journal_for_match_missing_returns_none(in_memory_db: sqlite3.Connection) -> None:
    """Test 4: for_match with an unknown pair returns None."""
    _seed_player(in_memory_db)
    repo = MatchJournalRepository(in_memory_db)
    repo.upsert(_entry(match_id="m-1"))
    assert repo.for_match("janav", "m-999") is None
    assert repo.for_match("other-player", "m-1") is None


def test_journal_delete_returns_true_on_hit_false_on_miss(
    in_memory_db: sqlite3.Connection,
) -> None:
    """Test 5: delete reports whether a row was actually removed."""
    _seed_player(in_memory_db)
    repo = MatchJournalRepository(in_memory_db)

    new_id = repo.upsert(_entry())
    assert repo.delete(new_id) is True
    assert repo.get(new_id) is None
    # Deleting again is a miss.
    assert repo.delete(new_id) is False
    # Random unused id is also a miss.
    assert repo.delete(987654) is False


def test_journal_tags_persist_as_json_and_preserve_order(
    in_memory_db: sqlite3.Connection,
) -> None:
    """Test 6: tags round-trip preserves insertion order.

    The column stores JSON text; JSON arrays are ordered, so a round-trip
    should not silently reshuffle the list.
    """
    _seed_player(in_memory_db)
    repo = MatchJournalRepository(in_memory_db)

    tags = ["return", "approach", "net", "footwork", "mental"]
    new_id = repo.upsert(_entry(tags=tags))
    loaded = repo.get(new_id)
    assert loaded is not None
    assert loaded.tags == tags

    # Sanity: the raw column actually contains JSON text we can parse.
    raw = in_memory_db.execute(
        "SELECT tags FROM match_journal WHERE id = ?", (new_id,)
    ).fetchone()
    assert raw is not None
    import json

    assert json.loads(raw[0]) == tags


def test_journal_self_rating_out_of_range_raises_validation_error() -> None:
    """Test 7: self_rating must be in [1, 5]; Pydantic guards the bounds."""
    base_kwargs = {
        "player_id": "janav",
        "match_id": "m-1",
        "created_at": datetime(2026, 5, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 5, 1, tzinfo=UTC),
    }
    with pytest.raises(ValidationError):
        MatchJournalEntry(**base_kwargs, self_rating=0)
    with pytest.raises(ValidationError):
        MatchJournalEntry(**base_kwargs, self_rating=6)


def test_journal_body_is_nfc_normalized(in_memory_db: sqlite3.Connection) -> None:
    """Test 8: NFD-decomposable characters in the body land in storage as NFC."""
    _seed_player(in_memory_db)
    repo = MatchJournalRepository(in_memory_db)

    # NFD: "é" as "e" + COMBINING ACUTE ACCENT (U+0301).
    nfd_body = "Café chat after match"
    nfc_body = unicodedata.normalize("NFC", nfd_body)
    assert nfd_body != nfc_body, "guard: the two forms must differ pre-normalization"

    new_id = repo.upsert(_entry(body=nfd_body))
    raw = in_memory_db.execute(
        "SELECT body FROM match_journal WHERE id = ?", (new_id,)
    ).fetchone()
    assert raw is not None
    assert raw[0] == nfc_body, "body must be NFC-normalized on write"

    loaded = repo.get(new_id)
    assert loaded is not None
    assert loaded.body == nfc_body
