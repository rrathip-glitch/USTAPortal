"""Round-trip CRUD tests for :class:`RankingListRepository`.

Uses the existing ``in_memory_db`` fixture from :mod:`tests.conftest` so
the schema is the same one the production migrations build.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime

from src.models.player import Player
from src.models.ranking import RankingList, RankingListEntry
from src.store.repositories import PlayerRepository, RankingListRepository


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _list(list_id: str = "u12-boys-national-2026-05-11") -> RankingList:
    return RankingList(
        id=list_id,
        age_category="Boys 12s",
        gender="M",
        scope="national",
        section=None,
        as_of=date(2026, 5, 11),
        source="clubspark",
        total_players=2,
        fetched_at=datetime(2026, 5, 11, 12, 0, tzinfo=UTC),
    )


def _entry(
    list_id: str,
    position: int,
    player_usta_id: str = "971BA48D-A2EA-4FB7-8305-F42EA466F6DF",
) -> RankingListEntry:
    return RankingListEntry(
        list_id=list_id,
        position=position,
        player_usta_id=player_usta_id,
        player_name_raw="Thasen, Janav",
        points=1500,
        section="Florida",
        wtn_singles=12.3,
        wtn_doubles=15.7,
    )


def _seed_player(conn: sqlite3.Connection, usta_id: str, name: str) -> None:
    """Insert a player so the FK on ``ranking_list_entries`` is satisfied."""
    PlayerRepository(conn).upsert(Player(usta_id=usta_id, full_name=name))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_list_round_trip(in_memory_db: sqlite3.Connection) -> None:
    repo = RankingListRepository(in_memory_db)
    original = _list()
    repo.upsert_list(original)
    loaded = repo.get_list(original.id)
    assert loaded == original


def test_list_by_filter_returns_newest_first(in_memory_db: sqlite3.Connection) -> None:
    repo = RankingListRepository(in_memory_db)
    older = _list("u12-boys-national-2026-04-01").model_copy(
        update={"as_of": date(2026, 4, 1)}
    )
    newer = _list("u12-boys-national-2026-05-11")
    repo.upsert_list(older)
    repo.upsert_list(newer)

    results = repo.list_by_filter(
        age_category="Boys 12s",
        gender="M",
        scope="national",
        section=None,
    )
    assert [r.id for r in results] == [newer.id, older.id]


def test_list_by_filter_respects_section(in_memory_db: sqlite3.Connection) -> None:
    repo = RankingListRepository(in_memory_db)
    national = _list("u12-boys-national-2026-05-11")
    sectional = _list("u12-boys-florida-2026-05-11").model_copy(
        update={"scope": "sectional", "section": "Florida"}
    )
    repo.upsert_list(national)
    repo.upsert_list(sectional)

    nat_results = repo.list_by_filter("Boys 12s", "M", "national")
    sec_results = repo.list_by_filter("Boys 12s", "M", "sectional", section="Florida")

    assert [r.id for r in nat_results] == [national.id]
    assert [r.id for r in sec_results] == [sectional.id]


def test_entries_round_trip_in_position_order(
    in_memory_db: sqlite3.Connection,
) -> None:
    repo = RankingListRepository(in_memory_db)
    parent = _list()
    repo.upsert_list(parent)

    _seed_player(in_memory_db, "p-aaa", "Alpha One")
    _seed_player(in_memory_db, "p-bbb", "Beta Two")

    e2 = _entry(parent.id, position=2, player_usta_id="p-bbb")
    e1 = _entry(parent.id, position=1, player_usta_id="p-aaa")
    repo.upsert_entry(e2)
    repo.upsert_entry(e1)

    loaded = repo.get_entries(parent.id)
    assert [e.position for e in loaded] == [1, 2]
    assert loaded[0] == e1
    assert loaded[1] == e2
