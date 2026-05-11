"""Unit tests for :mod:`src.enrich.common_opponents`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from src.enrich.common_opponents import (
    CommonOpponentEntry,
    CommonOpponentsResult,
    common_opponents,
)
from src.models.match import Match, MatchOutcome

_BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _match(
    *,
    player_a_id: str | None,
    player_b_id: str | None,
    winner_id: str | None = None,
    days_offset: int = 0,
    outcome: MatchOutcome = "completed",
    draw_id: str = "draw-1",
    usta_id: str | None = None,
) -> Match:
    """Construct a ``Match`` with sensible defaults for tests."""
    return Match(
        usta_id=usta_id,
        draw_id=draw_id,
        round="R32",
        scheduled_at=_BASE + timedelta(days=days_offset),
        player_a_id=player_a_id,
        player_b_id=player_b_id,
        score_raw=None,
        sets=[],
        outcome=outcome,
        winner_id=winner_id,
    )


# ---------------------------------------------------------------------------
# Basic shape and edge cases
# ---------------------------------------------------------------------------


def test_empty_inputs_yield_empty_result() -> None:
    result = common_opponents([], [], "A", "B")

    assert isinstance(result, CommonOpponentsResult)
    assert result.player_a_id == "A"
    assert result.player_b_id == "B"
    assert result.common == []
    assert result.a_edge_count == 0
    assert result.b_edge_count == 0
    assert result.even_count == 0


def test_one_sided_history_yields_no_common_opponents() -> None:
    matches_a = [
        _match(player_a_id="A", player_b_id="X", winner_id="A", days_offset=0),
    ]
    matches_b: list[Match] = []

    result = common_opponents(matches_a, matches_b, "A", "B")

    assert result.common == []
    assert result.a_edge_count == result.b_edge_count == result.even_count == 0


def test_no_overlap_yields_no_common_opponents() -> None:
    matches_a = [
        _match(player_a_id="A", player_b_id="X", winner_id="A", days_offset=0),
        _match(player_a_id="A", player_b_id="Y", winner_id="A", days_offset=1),
    ]
    matches_b = [
        _match(player_a_id="B", player_b_id="Z", winner_id="B", days_offset=0),
    ]

    result = common_opponents(matches_a, matches_b, "A", "B")

    assert result.common == []


# ---------------------------------------------------------------------------
# Scoreline math
# ---------------------------------------------------------------------------


def test_single_common_opponent_2_0_vs_0_1_yields_edge_score_3() -> None:
    """Spec example: a went 2-0 vs X, b went 0-1 vs X → a_minus_b_score == 3."""
    matches_a = [
        _match(player_a_id="A", player_b_id="X", winner_id="A", days_offset=0),
        _match(player_a_id="A", player_b_id="X", winner_id="A", days_offset=1),
    ]
    matches_b = [
        _match(player_a_id="B", player_b_id="X", winner_id="X", days_offset=2),
    ]

    result = common_opponents(matches_a, matches_b, "A", "B")

    assert len(result.common) == 1
    entry = result.common[0]
    assert entry.opponent_id == "X"
    assert entry.a_record == (2, 0)
    assert entry.b_record == (0, 1)
    assert entry.a_minus_b_score == 3  # (2 - 0) - (0 - 1)
    assert result.a_edge_count == 1
    assert result.b_edge_count == 0
    assert result.even_count == 0


def test_two_common_opponents_opposite_edges_balanced_counts() -> None:
    """One opponent A dominates, one opponent B dominates → 1/1/0 edge counts."""
    matches_a = [
        # vs X: A is 2-0
        _match(player_a_id="A", player_b_id="X", winner_id="A", days_offset=0),
        _match(player_a_id="A", player_b_id="X", winner_id="A", days_offset=1),
        # vs Y: A is 0-1
        _match(player_a_id="A", player_b_id="Y", winner_id="Y", days_offset=2),
    ]
    matches_b = [
        # vs X: B is 0-1
        _match(player_a_id="B", player_b_id="X", winner_id="X", days_offset=3),
        # vs Y: B is 2-0
        _match(player_a_id="B", player_b_id="Y", winner_id="B", days_offset=4),
        _match(player_a_id="B", player_b_id="Y", winner_id="B", days_offset=5),
    ]

    result = common_opponents(matches_a, matches_b, "A", "B")

    assert result.a_edge_count == 1
    assert result.b_edge_count == 1
    assert result.even_count == 0

    by_opp = {e.opponent_id: e for e in result.common}
    assert by_opp["X"].a_minus_b_score == 3  # (2 - 0) - (0 - 1)
    assert by_opp["Y"].a_minus_b_score == -3  # (0 - 1) - (2 - 0)


def test_even_common_opponent_increments_even_count() -> None:
    """Both A and B went 1-1 against the same opponent → score 0, even bucket."""
    matches_a = [
        _match(player_a_id="A", player_b_id="X", winner_id="A", days_offset=0),
        _match(player_a_id="A", player_b_id="X", winner_id="X", days_offset=1),
    ]
    matches_b = [
        _match(player_a_id="B", player_b_id="X", winner_id="B", days_offset=2),
        _match(player_a_id="B", player_b_id="X", winner_id="X", days_offset=3),
    ]

    result = common_opponents(matches_a, matches_b, "A", "B")

    assert len(result.common) == 1
    entry = result.common[0]
    assert entry.a_record == (1, 1)
    assert entry.b_record == (1, 1)
    assert entry.a_minus_b_score == 0
    assert result.even_count == 1
    assert result.a_edge_count == 0
    assert result.b_edge_count == 0


# ---------------------------------------------------------------------------
# Match-record orientation: opponent can sit on either side of Match
# ---------------------------------------------------------------------------


def test_player_on_b_side_of_match_record_is_recognised() -> None:
    """Spec edge case: a match where player_a_id sits in Match.player_b_id."""
    matches_a = [
        # Player A is on the b-side of this match record; opponent X is on a-side.
        _match(player_a_id="X", player_b_id="A", winner_id="A", days_offset=0),
    ]
    matches_b = [
        _match(player_a_id="B", player_b_id="X", winner_id="X", days_offset=1),
    ]

    result = common_opponents(matches_a, matches_b, "A", "B")

    assert len(result.common) == 1
    entry = result.common[0]
    assert entry.opponent_id == "X"
    assert entry.a_record == (1, 0)
    assert entry.b_record == (0, 1)
    assert entry.a_minus_b_score == 2  # (1 - 0) - (0 - 1)


# ---------------------------------------------------------------------------
# Null / missing-data handling
# ---------------------------------------------------------------------------


def test_winner_none_still_counts_opponent_as_faced() -> None:
    """A walkover-no-winner against X still makes X a common opponent if
    the other player has also faced X. The unfinished match contributes 0 to
    the record itself.
    """
    matches_a = [
        _match(
            player_a_id="A",
            player_b_id="X",
            winner_id=None,
            outcome="unfinished",
            days_offset=0,
        ),
    ]
    matches_b = [
        _match(player_a_id="B", player_b_id="X", winner_id="B", days_offset=1),
    ]

    result = common_opponents(matches_a, matches_b, "A", "B")

    assert len(result.common) == 1
    entry = result.common[0]
    assert entry.opponent_id == "X"
    # The winnerless match did not increment either tally.
    assert entry.a_record == (0, 0)
    assert entry.b_record == (1, 0)
    assert entry.a_minus_b_score == -1  # (0 - 0) - (1 - 0)
    assert result.b_edge_count == 1


def test_none_opponent_id_is_skipped() -> None:
    """A match whose opposing side is unset (player_b_id is None) cannot
    introduce a common opponent — we drop it on the way in.
    """
    matches_a = [
        _match(player_a_id="A", player_b_id=None, winner_id=None, days_offset=0),
        _match(player_a_id="A", player_b_id="X", winner_id="A", days_offset=1),
    ]
    matches_b = [
        _match(player_a_id="B", player_b_id="X", winner_id="X", days_offset=2),
    ]

    result = common_opponents(matches_a, matches_b, "A", "B")

    assert {e.opponent_id for e in result.common} == {"X"}


# ---------------------------------------------------------------------------
# Self-match exclusion
# ---------------------------------------------------------------------------


def test_self_match_between_principals_is_excluded() -> None:
    """A direct A-vs-B match is the h2h enrichment's territory; it must not
    appear in the common-opponents intersection even though A "faced" B and
    B "faced" A.
    """
    matches_a = [
        _match(player_a_id="A", player_b_id="B", winner_id="A", days_offset=0),
        _match(player_a_id="A", player_b_id="X", winner_id="A", days_offset=1),
    ]
    matches_b = [
        _match(player_a_id="B", player_b_id="A", winner_id="A", days_offset=0),
        _match(player_a_id="B", player_b_id="X", winner_id="B", days_offset=2),
    ]

    result = common_opponents(matches_a, matches_b, "A", "B")

    opponent_ids = {e.opponent_id for e in result.common}
    assert "A" not in opponent_ids
    assert "B" not in opponent_ids
    assert opponent_ids == {"X"}


# ---------------------------------------------------------------------------
# Sort order
# ---------------------------------------------------------------------------


def test_common_sorted_by_abs_edge_desc_then_opponent_id_asc() -> None:
    matches_a = [
        # vs X: A 1-0  → contributes +1 to a_minus_b
        _match(player_a_id="A", player_b_id="X", winner_id="A", days_offset=0),
        # vs Y: A 3-0  → contributes +3
        _match(player_a_id="A", player_b_id="Y", winner_id="A", days_offset=1),
        _match(player_a_id="A", player_b_id="Y", winner_id="A", days_offset=2),
        _match(player_a_id="A", player_b_id="Y", winner_id="A", days_offset=3),
        # vs Z: A 0-1  → contributes -1
        _match(player_a_id="A", player_b_id="Z", winner_id="Z", days_offset=4),
        # vs W: A 1-0  → contributes +1; tie-break test against X
        _match(player_a_id="A", player_b_id="W", winner_id="A", days_offset=5),
    ]
    matches_b = [
        _match(player_a_id="B", player_b_id="X", winner_id="X", days_offset=0),
        _match(player_a_id="B", player_b_id="Y", winner_id="Y", days_offset=1),
        _match(player_a_id="B", player_b_id="Z", winner_id="B", days_offset=2),
        _match(player_a_id="B", player_b_id="W", winner_id="W", days_offset=3),
    ]

    result = common_opponents(matches_a, matches_b, "A", "B")

    ordered = [(e.opponent_id, e.a_minus_b_score) for e in result.common]
    # Y has |score| = 4, then W and X both have |score| = 2 (tie → sort by
    # opponent_id asc), then Z with |score| = 2 too. Recompute:
    # X: (1 - 0) - (0 - 1) = 2
    # Y: (3 - 0) - (0 - 1) = 4
    # Z: (0 - 1) - (1 - 0) = -2
    # W: (1 - 0) - (0 - 1) = 2
    # |score|: Y=4, X=2, Z=2, W=2 → Y first, then alphabetical (W, X, Z).
    assert ordered == [("Y", 4), ("W", 2), ("X", 2), ("Z", -2)]


def test_entries_are_frozen_dataclasses() -> None:
    """Surface a regression if we ever lose the immutability invariant."""
    matches_a = [
        _match(player_a_id="A", player_b_id="X", winner_id="A", days_offset=0),
    ]
    matches_b = [
        _match(player_a_id="B", player_b_id="X", winner_id="B", days_offset=0),
    ]

    result = common_opponents(matches_a, matches_b, "A", "B")
    entry = result.common[0]

    assert isinstance(entry, CommonOpponentEntry)
    # Frozen dataclasses raise dataclasses.FrozenInstanceError (a subclass of
    # AttributeError) on attribute assignment.
    import dataclasses as _dc

    try:
        entry.opponent_id = "Z"  # type: ignore[misc]
    except _dc.FrozenInstanceError:
        pass
    else:  # pragma: no cover - guard against regression
        raise AssertionError("CommonOpponentEntry should be frozen")


# ---------------------------------------------------------------------------
# Property test: swapping the two players negates every edge score and
# swaps a_edge_count with b_edge_count. even_count is invariant.
# ---------------------------------------------------------------------------


@st.composite
def _co_match_strategy(
    draw: st.DrawFn, principal: str, opponents: list[str]
) -> Match:
    """Generate a match between ``principal`` and one of ``opponents``."""
    opp = draw(st.sampled_from(opponents))
    principal_first = draw(st.booleans())
    winner = draw(st.sampled_from([principal, opp, None]))
    day = draw(st.integers(min_value=0, max_value=365))
    return _match(
        player_a_id=principal if principal_first else opp,
        player_b_id=opp if principal_first else principal,
        winner_id=winner,
        days_offset=day,
    )


@given(
    matches_a=st.lists(
        _co_match_strategy(principal="A", opponents=["X", "Y", "Z", "W"]),
        min_size=0,
        max_size=15,
    ),
    matches_b=st.lists(
        _co_match_strategy(principal="B", opponents=["X", "Y", "Z", "Q"]),
        min_size=0,
        max_size=15,
    ),
)
def test_perspective_swap_negates_edges_and_swaps_counts(
    matches_a: list[Match], matches_b: list[Match]
) -> None:
    """Property: swapping (player_a, player_b) negates every a_minus_b_score
    and swaps the a/b edge counts; the even count and the set of common
    opponents are invariant.
    """
    forward = common_opponents(matches_a, matches_b, "A", "B")
    reverse = common_opponents(matches_b, matches_a, "B", "A")

    assert {e.opponent_id for e in forward.common} == {
        e.opponent_id for e in reverse.common
    }
    assert forward.even_count == reverse.even_count
    assert forward.a_edge_count == reverse.b_edge_count
    assert forward.b_edge_count == reverse.a_edge_count

    forward_scores = {e.opponent_id: e.a_minus_b_score for e in forward.common}
    reverse_scores = {e.opponent_id: e.a_minus_b_score for e in reverse.common}
    for opp_id, score in forward_scores.items():
        assert reverse_scores[opp_id] == -score
        # Records also swap.
    forward_records = {
        e.opponent_id: (e.a_record, e.b_record) for e in forward.common
    }
    reverse_records = {
        e.opponent_id: (e.a_record, e.b_record) for e in reverse.common
    }
    for opp_id, (a_rec, b_rec) in forward_records.items():
        assert reverse_records[opp_id] == (b_rec, a_rec)
