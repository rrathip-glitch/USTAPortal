"""Repository round-trip and query tests against the in-memory DB fixture."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime

import pytest

from src.models.draw import Draw, DrawEntry
from src.models.match import Match, SetScore
from src.models.player import Player
from src.models.ranking import RankingSnapshot
from src.models.tournament import Tournament
from src.models.wtn import WTNSnapshot
from src.store.repositories import (
    DrawEntryRepository,
    DrawRepository,
    MatchRepository,
    PlayerRepository,
    RankingSnapshotRepository,
    TournamentRepository,
    WTNSnapshotRepository,
)

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _player(usta_id: str = "p-1", full_name: str = "Alex Rivera") -> Player:
    return Player(
        usta_id=usta_id,
        full_name=full_name,
        first_name=full_name.split()[0],
        last_name=full_name.split()[-1],
        gender="M",
        section="Southern",
        district="Atlanta",
        age_category="Boys' 16s",
        profile_url=f"https://playtennis.usta.com/player/{usta_id}",
        last_fetched_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
    )


def _tournament(usta_id: str = "t-1", status: str = "upcoming") -> Tournament:
    return Tournament(
        usta_id=usta_id,
        name="Spring Open",
        level="L4",
        sanction_body="USTA",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 5),
        location_city="Atlanta",
        location_state="GA",
        surface="hard",
        ball="Wilson US Open",
        entry_deadline=datetime(2026, 5, 20, 23, 59, tzinfo=UTC),
        status=status,  # type: ignore[arg-type]
        last_fetched_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
    )


def _draw(usta_id: str = "d-1", tournament_id: str = "t-1") -> Draw:
    return Draw(
        usta_id=usta_id,
        tournament_id=tournament_id,
        name="Boys 16 Singles",
        format="single_elimination",
        size=32,
        gender="M",
        age_group="16",
        division="singles",
        status="open",
        last_fetched_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# PlayerRepository
# ---------------------------------------------------------------------------


def test_player_round_trip(in_memory_db: sqlite3.Connection) -> None:
    repo = PlayerRepository(in_memory_db)
    original = _player()
    repo.upsert(original)
    loaded = repo.get(original.usta_id)
    assert loaded == original


def test_player_get_missing_returns_none(in_memory_db: sqlite3.Connection) -> None:
    repo = PlayerRepository(in_memory_db)
    assert repo.get("nope") is None


def test_player_upsert_is_idempotent(in_memory_db: sqlite3.Connection) -> None:
    repo = PlayerRepository(in_memory_db)
    p = _player()
    repo.upsert(p)
    repo.upsert(p)
    rows = in_memory_db.execute(
        "SELECT COUNT(*) FROM players WHERE usta_id = ?", (p.usta_id,)
    ).fetchone()
    assert rows[0] == 1


def test_player_upsert_overwrites_changed_fields(in_memory_db: sqlite3.Connection) -> None:
    repo = PlayerRepository(in_memory_db)
    repo.upsert(_player(full_name="Old Name"))
    repo.upsert(_player(full_name="New Name"))
    loaded = repo.get("p-1")
    assert loaded is not None
    assert loaded.full_name == "New Name"


def test_player_list_all_orders_by_name(in_memory_db: sqlite3.Connection) -> None:
    repo = PlayerRepository(in_memory_db)
    repo.upsert(_player("p-1", "Zoe Adams"))
    repo.upsert(_player("p-2", "Ann Baker"))
    names = [p.full_name for p in repo.list_all()]
    assert names == ["Ann Baker", "Zoe Adams"]


def test_player_search_by_name_is_case_insensitive(in_memory_db: sqlite3.Connection) -> None:
    repo = PlayerRepository(in_memory_db)
    repo.upsert(_player("p-1", "Alex Rivera"))
    repo.upsert(_player("p-2", "Bob Stone"))
    results = repo.search_by_name("ALEX")
    assert [p.usta_id for p in results] == ["p-1"]


def test_player_search_by_name_partial_match(in_memory_db: sqlite3.Connection) -> None:
    repo = PlayerRepository(in_memory_db)
    repo.upsert(_player("p-1", "Alex Rivera"))
    repo.upsert(_player("p-2", "Maria Riveros"))
    results = repo.search_by_name("River")
    assert {p.usta_id for p in results} == {"p-1", "p-2"}


def test_player_nfc_normalization_on_write(in_memory_db: sqlite3.Connection) -> None:
    repo = PlayerRepository(in_memory_db)
    # NFD-encoded "é" (e + combining acute)
    nfd_name = "André Agassi"
    repo.upsert(_player("p-1", nfd_name))
    loaded = repo.get("p-1")
    assert loaded is not None
    # Stored in NFC: precomposed "é"
    assert loaded.full_name == "André Agassi"


# ---------------------------------------------------------------------------
# TournamentRepository
# ---------------------------------------------------------------------------


def test_tournament_round_trip(in_memory_db: sqlite3.Connection) -> None:
    repo = TournamentRepository(in_memory_db)
    original = _tournament()
    repo.upsert(original)
    loaded = repo.get(original.usta_id)
    assert loaded == original


def test_tournament_upsert_is_idempotent(in_memory_db: sqlite3.Connection) -> None:
    repo = TournamentRepository(in_memory_db)
    repo.upsert(_tournament())
    repo.upsert(_tournament())
    rows = in_memory_db.execute("SELECT COUNT(*) FROM tournaments").fetchone()
    assert rows[0] == 1


def test_tournament_list_upcoming_filters_by_status(in_memory_db: sqlite3.Connection) -> None:
    repo = TournamentRepository(in_memory_db)
    repo.upsert(_tournament("t-1", "upcoming"))
    repo.upsert(_tournament("t-2", "completed"))
    repo.upsert(_tournament("t-3", "in_progress"))
    upcoming = repo.list_upcoming()
    assert [t.usta_id for t in upcoming] == ["t-1"]


def test_tournament_list_in_progress_filters_by_status(in_memory_db: sqlite3.Connection) -> None:
    repo = TournamentRepository(in_memory_db)
    repo.upsert(_tournament("t-1", "upcoming"))
    repo.upsert(_tournament("t-2", "in_progress"))
    in_progress = repo.list_in_progress()
    assert [t.usta_id for t in in_progress] == ["t-2"]


# ---------------------------------------------------------------------------
# DrawRepository
# ---------------------------------------------------------------------------


def test_draw_round_trip(in_memory_db: sqlite3.Connection) -> None:
    TournamentRepository(in_memory_db).upsert(_tournament())
    repo = DrawRepository(in_memory_db)
    original = _draw()
    repo.upsert(original)
    loaded = repo.get(original.usta_id)
    assert loaded == original


def test_draw_upsert_is_idempotent(in_memory_db: sqlite3.Connection) -> None:
    TournamentRepository(in_memory_db).upsert(_tournament())
    repo = DrawRepository(in_memory_db)
    repo.upsert(_draw())
    repo.upsert(_draw())
    rows = in_memory_db.execute("SELECT COUNT(*) FROM draws").fetchone()
    assert rows[0] == 1


def test_draw_list_for_tournament(in_memory_db: sqlite3.Connection) -> None:
    TournamentRepository(in_memory_db).upsert(_tournament("t-1"))
    TournamentRepository(in_memory_db).upsert(_tournament("t-2"))
    repo = DrawRepository(in_memory_db)
    repo.upsert(_draw("d-1", "t-1"))
    repo.upsert(_draw("d-2", "t-1"))
    repo.upsert(_draw("d-3", "t-2"))
    results = repo.list_for_tournament("t-1")
    assert {d.usta_id for d in results} == {"d-1", "d-2"}


# ---------------------------------------------------------------------------
# DrawEntryRepository
# ---------------------------------------------------------------------------


def _seed_draw_entry_world(conn: sqlite3.Connection) -> None:
    TournamentRepository(conn).upsert(_tournament())
    DrawRepository(conn).upsert(_draw())
    PlayerRepository(conn).upsert(_player("p-1", "Alex Rivera"))
    PlayerRepository(conn).upsert(_player("p-2", "Bob Stone"))


def test_draw_entry_round_trip(in_memory_db: sqlite3.Connection) -> None:
    _seed_draw_entry_world(in_memory_db)
    repo = DrawEntryRepository(in_memory_db)
    entry = DrawEntry(draw_id="d-1", player_id="p-1", seed=2, position=1, status="entered")
    repo.upsert(entry)
    [loaded] = repo.list_for_draw("d-1")
    assert loaded == entry


def test_draw_entry_upsert_is_idempotent(in_memory_db: sqlite3.Connection) -> None:
    _seed_draw_entry_world(in_memory_db)
    repo = DrawEntryRepository(in_memory_db)
    entry = DrawEntry(draw_id="d-1", player_id="p-1", seed=2, position=1)
    repo.upsert(entry)
    repo.upsert(entry)
    rows = in_memory_db.execute("SELECT COUNT(*) FROM draw_entries").fetchone()
    assert rows[0] == 1


def test_draw_entry_list_for_draw(in_memory_db: sqlite3.Connection) -> None:
    _seed_draw_entry_world(in_memory_db)
    repo = DrawEntryRepository(in_memory_db)
    repo.upsert(DrawEntry(draw_id="d-1", player_id="p-1", position=1))
    repo.upsert(DrawEntry(draw_id="d-1", player_id="p-2", position=2))
    results = repo.list_for_draw("d-1")
    assert [e.player_id for e in results] == ["p-1", "p-2"]


def test_draw_entry_list_for_player(in_memory_db: sqlite3.Connection) -> None:
    _seed_draw_entry_world(in_memory_db)
    DrawRepository(in_memory_db).upsert(_draw("d-2"))
    repo = DrawEntryRepository(in_memory_db)
    repo.upsert(DrawEntry(draw_id="d-1", player_id="p-1"))
    repo.upsert(DrawEntry(draw_id="d-2", player_id="p-1"))
    repo.upsert(DrawEntry(draw_id="d-1", player_id="p-2"))
    results = repo.list_for_player("p-1")
    assert {e.draw_id for e in results} == {"d-1", "d-2"}


# ---------------------------------------------------------------------------
# MatchRepository
# ---------------------------------------------------------------------------


def _seed_match_world(conn: sqlite3.Connection) -> None:
    TournamentRepository(conn).upsert(_tournament())
    DrawRepository(conn).upsert(_draw())
    DrawRepository(conn).upsert(_draw("d-2"))
    PlayerRepository(conn).upsert(_player("p-1", "Alex Rivera"))
    PlayerRepository(conn).upsert(_player("p-2", "Bob Stone"))
    PlayerRepository(conn).upsert(_player("p-3", "Carla Wu"))


def _match(
    usta_id: str = "m-1",
    *,
    draw_id: str = "d-1",
    player_a_id: str | None = "p-1",
    player_b_id: str | None = "p-2",
    scheduled_at: datetime | None = None,
    sets: list[SetScore] | None = None,
) -> Match:
    return Match(
        usta_id=usta_id,
        draw_id=draw_id,
        round="QF",
        scheduled_at=scheduled_at or datetime(2026, 6, 2, 9, 0, tzinfo=UTC),
        court="Court 5",
        player_a_id=player_a_id,
        player_b_id=player_b_id,
        score_raw="6-3 6-4",
        sets=sets if sets is not None else [SetScore(games_a=6, games_b=3), SetScore(games_a=6, games_b=4)],
        outcome="completed",
        winner_id=player_a_id,
        last_fetched_at=datetime(2026, 6, 2, 11, 0, tzinfo=UTC),
    )


def test_match_round_trip(in_memory_db: sqlite3.Connection) -> None:
    _seed_match_world(in_memory_db)
    repo = MatchRepository(in_memory_db)
    original = _match()
    repo.upsert(original)
    loaded = repo.get("m-1")
    assert loaded == original


def test_match_round_trip_preserves_sets_json(in_memory_db: sqlite3.Connection) -> None:
    _seed_match_world(in_memory_db)
    repo = MatchRepository(in_memory_db)
    sets = [
        SetScore(games_a=7, games_b=6, tiebreak_a=7, tiebreak_b=4),
        SetScore(games_a=4, games_b=6),
        SetScore(games_a=6, games_b=2),
    ]
    repo.upsert(_match(sets=sets))
    loaded = repo.get("m-1")
    assert loaded is not None
    assert loaded.sets == sets


def test_match_round_trip_with_empty_sets(in_memory_db: sqlite3.Connection) -> None:
    _seed_match_world(in_memory_db)
    repo = MatchRepository(in_memory_db)
    repo.upsert(_match(sets=[]))
    loaded = repo.get("m-1")
    assert loaded is not None
    assert loaded.sets == []


def test_match_upsert_is_idempotent(in_memory_db: sqlite3.Connection) -> None:
    _seed_match_world(in_memory_db)
    repo = MatchRepository(in_memory_db)
    repo.upsert(_match())
    repo.upsert(_match())
    rows = in_memory_db.execute("SELECT COUNT(*) FROM matches").fetchone()
    assert rows[0] == 1


def test_match_upsert_rejects_missing_id(in_memory_db: sqlite3.Connection) -> None:
    _seed_match_world(in_memory_db)
    repo = MatchRepository(in_memory_db)
    m = Match(draw_id="d-1", player_a_id="p-1", player_b_id="p-2")
    with pytest.raises(ValueError):
        repo.upsert(m)


def test_match_list_for_draw(in_memory_db: sqlite3.Connection) -> None:
    _seed_match_world(in_memory_db)
    repo = MatchRepository(in_memory_db)
    repo.upsert(_match("m-1", draw_id="d-1"))
    repo.upsert(_match("m-2", draw_id="d-1"))
    repo.upsert(_match("m-3", draw_id="d-2"))
    results = repo.list_for_draw("d-1")
    assert {m.usta_id for m in results} == {"m-1", "m-2"}


def test_match_list_for_player_finds_either_side(in_memory_db: sqlite3.Connection) -> None:
    _seed_match_world(in_memory_db)
    repo = MatchRepository(in_memory_db)
    # p-1 is on side A in m-1
    repo.upsert(_match("m-1", player_a_id="p-1", player_b_id="p-2"))
    # p-1 is on side B in m-2
    repo.upsert(_match("m-2", player_a_id="p-3", player_b_id="p-1"))
    # p-1 not in m-3
    repo.upsert(_match("m-3", player_a_id="p-2", player_b_id="p-3"))
    results = repo.list_for_player("p-1")
    assert {m.usta_id for m in results} == {"m-1", "m-2"}


def test_match_list_h2h_returns_either_order(in_memory_db: sqlite3.Connection) -> None:
    _seed_match_world(in_memory_db)
    repo = MatchRepository(in_memory_db)
    # p-1 v p-2
    repo.upsert(_match("m-1", player_a_id="p-1", player_b_id="p-2"))
    # p-2 v p-1 (reverse order)
    repo.upsert(_match("m-2", player_a_id="p-2", player_b_id="p-1"))
    # p-1 v p-3 (not h2h)
    repo.upsert(_match("m-3", player_a_id="p-1", player_b_id="p-3"))
    results = repo.list_h2h("p-1", "p-2")
    assert {m.usta_id for m in results} == {"m-1", "m-2"}


# ---------------------------------------------------------------------------
# RankingSnapshotRepository
# ---------------------------------------------------------------------------


def _seed_ranking_world(conn: sqlite3.Connection) -> None:
    PlayerRepository(conn).upsert(_player("p-1"))
    PlayerRepository(conn).upsert(_player("p-2", "Bob Stone"))


def test_ranking_round_trip(in_memory_db: sqlite3.Connection) -> None:
    _seed_ranking_world(in_memory_db)
    repo = RankingSnapshotRepository(in_memory_db)
    snap = RankingSnapshot(
        player_id="p-1",
        category="Boys 16 Singles",
        scope="sectional",
        section="Southern",
        position=12,
        points=480.5,
        as_of=date(2026, 4, 1),
    )
    repo.upsert(snap)
    loaded = repo.latest_for_player("p-1", "Boys 16 Singles")
    assert loaded == snap


def test_ranking_upsert_is_idempotent(in_memory_db: sqlite3.Connection) -> None:
    _seed_ranking_world(in_memory_db)
    repo = RankingSnapshotRepository(in_memory_db)
    snap = RankingSnapshot(
        player_id="p-1",
        category="Boys 16 Singles",
        scope="sectional",
        as_of=date(2026, 4, 1),
    )
    repo.upsert(snap)
    repo.upsert(snap)
    rows = in_memory_db.execute("SELECT COUNT(*) FROM ranking_snapshots").fetchone()
    assert rows[0] == 1


def test_ranking_latest_returns_most_recent(in_memory_db: sqlite3.Connection) -> None:
    _seed_ranking_world(in_memory_db)
    repo = RankingSnapshotRepository(in_memory_db)
    repo.upsert(
        RankingSnapshot(
            player_id="p-1",
            category="Boys 16 Singles",
            scope="sectional",
            position=20,
            as_of=date(2026, 1, 1),
        )
    )
    repo.upsert(
        RankingSnapshot(
            player_id="p-1",
            category="Boys 16 Singles",
            scope="sectional",
            position=12,
            as_of=date(2026, 4, 1),
        )
    )
    latest = repo.latest_for_player("p-1", "Boys 16 Singles")
    assert latest is not None
    assert latest.position == 12


def test_ranking_history_orders_by_as_of(in_memory_db: sqlite3.Connection) -> None:
    _seed_ranking_world(in_memory_db)
    repo = RankingSnapshotRepository(in_memory_db)
    dates = [date(2026, 4, 1), date(2026, 1, 1), date(2026, 2, 1)]
    for d in dates:
        repo.upsert(
            RankingSnapshot(
                player_id="p-1",
                category="Boys 16 Singles",
                scope="sectional",
                as_of=d,
            )
        )
    history = repo.history_for_player("p-1", "Boys 16 Singles")
    assert [s.as_of for s in history] == sorted(dates)


def test_ranking_latest_filters_by_category(in_memory_db: sqlite3.Connection) -> None:
    _seed_ranking_world(in_memory_db)
    repo = RankingSnapshotRepository(in_memory_db)
    repo.upsert(
        RankingSnapshot(
            player_id="p-1",
            category="Boys 16 Singles",
            scope="sectional",
            position=5,
            as_of=date(2026, 4, 1),
        )
    )
    repo.upsert(
        RankingSnapshot(
            player_id="p-1",
            category="Boys 16 Doubles",
            scope="sectional",
            position=10,
            as_of=date(2026, 4, 1),
        )
    )
    singles = repo.latest_for_player("p-1", "Boys 16 Singles")
    doubles = repo.latest_for_player("p-1", "Boys 16 Doubles")
    assert singles is not None and singles.position == 5
    assert doubles is not None and doubles.position == 10


# ---------------------------------------------------------------------------
# WTNSnapshotRepository
# ---------------------------------------------------------------------------


def test_wtn_round_trip(in_memory_db: sqlite3.Connection) -> None:
    PlayerRepository(in_memory_db).upsert(_player("p-1"))
    repo = WTNSnapshotRepository(in_memory_db)
    snap = WTNSnapshot(
        player_id="p-1",
        type="singles",
        value=14.2,
        confidence=0.85,
        as_of=date(2026, 4, 1),
    )
    repo.upsert(snap)
    loaded = repo.latest_for_player("p-1", "singles")
    assert loaded == snap


def test_wtn_upsert_is_idempotent(in_memory_db: sqlite3.Connection) -> None:
    PlayerRepository(in_memory_db).upsert(_player("p-1"))
    repo = WTNSnapshotRepository(in_memory_db)
    snap = WTNSnapshot(player_id="p-1", type="singles", value=14.2, as_of=date(2026, 4, 1))
    repo.upsert(snap)
    repo.upsert(snap)
    rows = in_memory_db.execute("SELECT COUNT(*) FROM wtn_snapshots").fetchone()
    assert rows[0] == 1


def test_wtn_latest_returns_most_recent(in_memory_db: sqlite3.Connection) -> None:
    PlayerRepository(in_memory_db).upsert(_player("p-1"))
    repo = WTNSnapshotRepository(in_memory_db)
    repo.upsert(WTNSnapshot(player_id="p-1", type="singles", value=15.0, as_of=date(2026, 1, 1)))
    repo.upsert(WTNSnapshot(player_id="p-1", type="singles", value=14.2, as_of=date(2026, 4, 1)))
    latest = repo.latest_for_player("p-1", "singles")
    assert latest is not None
    assert latest.value == pytest.approx(14.2)


def test_wtn_history_orders_by_as_of(in_memory_db: sqlite3.Connection) -> None:
    PlayerRepository(in_memory_db).upsert(_player("p-1"))
    repo = WTNSnapshotRepository(in_memory_db)
    dates = [date(2026, 4, 1), date(2026, 1, 1), date(2026, 2, 1)]
    for d in dates:
        repo.upsert(WTNSnapshot(player_id="p-1", type="singles", value=14.0, as_of=d))
    history = repo.history_for_player("p-1", "singles")
    assert [s.as_of for s in history] == sorted(dates)


def test_wtn_singles_and_doubles_are_independent(in_memory_db: sqlite3.Connection) -> None:
    PlayerRepository(in_memory_db).upsert(_player("p-1"))
    repo = WTNSnapshotRepository(in_memory_db)
    repo.upsert(WTNSnapshot(player_id="p-1", type="singles", value=14.0, as_of=date(2026, 4, 1)))
    repo.upsert(WTNSnapshot(player_id="p-1", type="doubles", value=18.5, as_of=date(2026, 4, 1)))
    singles = repo.latest_for_player("p-1", "singles")
    doubles = repo.latest_for_player("p-1", "doubles")
    assert singles is not None and singles.value == pytest.approx(14.0)
    assert doubles is not None and doubles.value == pytest.approx(18.5)
