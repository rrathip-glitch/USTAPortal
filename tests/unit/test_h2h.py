"""Unit tests for :mod:`src.enrich.h2h`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from src.enrich.h2h import H2HResult, head_to_head
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
    scheduled: bool = True,
) -> Match:
    """Construct a ``Match`` with sensible defaults for tests."""
    return Match(
        usta_id=usta_id,
        draw_id=draw_id,
        round="R32",
        scheduled_at=_BASE + timedelta(days=days_offset) if scheduled else None,
        player_a_id=player_a_id,
        player_b_id=player_b_id,
        score_raw=None,
        sets=[],
        outcome=outcome,
        winner_id=winner_id,
    )


def test_basic_three_match_h2h_a_wins_two() -> None:
    matches = [
        _match(player_a_id="A", player_b_id="B", winner_id="A", days_offset=0),
        _match(player_a_id="A", player_b_id="B", winner_id="B", days_offset=10),
        _match(player_a_id="A", player_b_id="B", winner_id="A", days_offset=20),
    ]

    result = head_to_head(matches, "A", "B")

    assert isinstance(result, H2HResult)
    assert result.total_matches == 3
    assert result.wins_a == 2
    assert result.wins_b == 1
    assert result.last_match is not None
    assert result.last_match.winner_id == "A"
    assert result.last_match_winner_id == "A"


def test_either_side_ordering_is_counted() -> None:
    matches = [
        _match(player_a_id="A", player_b_id="B", winner_id="A", days_offset=0),
        _match(player_a_id="B", player_b_id="A", winner_id="B", days_offset=5),
        _match(player_a_id="B", player_b_id="A", winner_id="A", days_offset=10),
    ]

    result = head_to_head(matches, "A", "B")

    assert result.total_matches == 3
    assert result.wins_a == 2
    assert result.wins_b == 1


def test_unrelated_matches_are_filtered_out() -> None:
    matches = [
        _match(player_a_id="A", player_b_id="B", winner_id="A", days_offset=0),
        _match(player_a_id="A", player_b_id="C", winner_id="A", days_offset=1),
        _match(player_a_id="C", player_b_id="D", winner_id="C", days_offset=2),
        _match(player_a_id="B", player_b_id="C", winner_id="B", days_offset=3),
    ]

    result = head_to_head(matches, "A", "B")

    assert result.total_matches == 1
    assert result.wins_a == 1
    assert result.wins_b == 0


def test_walkover_with_winner_counts() -> None:
    matches = [
        _match(
            player_a_id="A",
            player_b_id="B",
            winner_id="A",
            outcome="walkover",
            days_offset=0,
        ),
    ]

    result = head_to_head(matches, "A", "B")

    assert result.total_matches == 1
    assert result.wins_a == 1
    assert result.wins_b == 0


def test_walkover_without_winner_counts_in_total_only() -> None:
    matches = [
        _match(
            player_a_id="A",
            player_b_id="B",
            winner_id=None,
            outcome="walkover",
            days_offset=0,
        ),
        _match(
            player_a_id="A",
            player_b_id="B",
            winner_id="A",
            outcome="completed",
            days_offset=5,
        ),
    ]

    result = head_to_head(matches, "A", "B")

    assert result.total_matches == 2
    assert result.wins_a == 1
    assert result.wins_b == 0


def test_unfinished_and_unknown_outcomes_included_no_wins() -> None:
    matches = [
        _match(
            player_a_id="A",
            player_b_id="B",
            winner_id=None,
            outcome="unfinished",
            days_offset=0,
        ),
        _match(
            player_a_id="A",
            player_b_id="B",
            winner_id=None,
            outcome="unknown",
            days_offset=1,
        ),
    ]

    result = head_to_head(matches, "A", "B")

    assert result.total_matches == 2
    assert result.wins_a == 0
    assert result.wins_b == 0
    assert result.streak_holder_id is None
    assert result.streak_length == 0


def test_streak_detection_a_wins_last_two() -> None:
    matches = [
        _match(player_a_id="A", player_b_id="B", winner_id="B", days_offset=0),
        _match(player_a_id="A", player_b_id="B", winner_id="A", days_offset=10),
        _match(player_a_id="A", player_b_id="B", winner_id="A", days_offset=20),
    ]

    result = head_to_head(matches, "A", "B")

    assert result.streak_holder_id == "A"
    assert result.streak_length == 2


def test_streak_breaks_on_alternating_recent_results() -> None:
    matches = [
        _match(player_a_id="A", player_b_id="B", winner_id="A", days_offset=0),
        _match(player_a_id="A", player_b_id="B", winner_id="B", days_offset=10),
        _match(player_a_id="A", player_b_id="B", winner_id="A", days_offset=20),
    ]

    result = head_to_head(matches, "A", "B")

    # Most recent winner is A, then B before that, so streak == 1 (just the
    # latest match).
    assert result.streak_holder_id == "A"
    assert result.streak_length == 1


def test_streak_broken_by_unfinished_recent_match() -> None:
    matches = [
        _match(player_a_id="A", player_b_id="B", winner_id="A", days_offset=0),
        _match(
            player_a_id="A",
            player_b_id="B",
            winner_id=None,
            outcome="unfinished",
            days_offset=10,
        ),
        _match(player_a_id="A", player_b_id="B", winner_id="A", days_offset=20),
    ]

    result = head_to_head(matches, "A", "B")

    # Most recent (offset=20) is A's; the next match back has no winner, so
    # the streak stops at 1.
    assert result.streak_holder_id == "A"
    assert result.streak_length == 1


def test_streak_when_no_decided_matches() -> None:
    matches = [
        _match(
            player_a_id="A",
            player_b_id="B",
            winner_id=None,
            outcome="walkover",
            days_offset=0,
        ),
    ]

    result = head_to_head(matches, "A", "B")

    assert result.streak_holder_id is None
    assert result.streak_length == 0
    assert result.last_match is not None
    assert result.last_match_winner_id is None


def test_empty_match_list() -> None:
    result = head_to_head([], "A", "B")

    assert result.total_matches == 0
    assert result.wins_a == 0
    assert result.wins_b == 0
    assert result.last_match is None
    assert result.last_match_winner_id is None
    assert result.match_list == []
    assert result.streak_holder_id is None
    assert result.streak_length == 0


def test_no_matches_between_the_two_players() -> None:
    matches = [
        _match(player_a_id="A", player_b_id="C", winner_id="A", days_offset=0),
        _match(player_a_id="B", player_b_id="D", winner_id="B", days_offset=1),
    ]

    result = head_to_head(matches, "A", "B")

    assert result.total_matches == 0
    assert result.match_list == []
    assert result.last_match is None


def test_same_player_raises_value_error() -> None:
    with pytest.raises(ValueError, match="distinct"):
        head_to_head([], "A", "A")


def test_sort_order_descending_by_scheduled_at() -> None:
    # Inserted out of chronological order; result should put most recent first.
    matches = [
        _match(player_a_id="A", player_b_id="B", winner_id="B", days_offset=10),
        _match(player_a_id="A", player_b_id="B", winner_id="A", days_offset=30),
        _match(player_a_id="A", player_b_id="B", winner_id="A", days_offset=20),
    ]

    result = head_to_head(matches, "A", "B")

    offsets = [
        (m.scheduled_at - _BASE).days  # type: ignore[operator]
        for m in result.match_list
    ]
    assert offsets == [30, 20, 10]
    assert result.last_match is not None
    assert result.last_match.scheduled_at == _BASE + timedelta(days=30)


def test_unscheduled_matches_sort_to_end() -> None:
    matches = [
        _match(player_a_id="A", player_b_id="B", winner_id="A", days_offset=10),
        _match(
            player_a_id="A",
            player_b_id="B",
            winner_id="B",
            scheduled=False,
        ),
        _match(player_a_id="A", player_b_id="B", winner_id="A", days_offset=20),
    ]

    result = head_to_head(matches, "A", "B")

    assert result.match_list[0].scheduled_at == _BASE + timedelta(days=20)
    assert result.match_list[1].scheduled_at == _BASE + timedelta(days=10)
    assert result.match_list[2].scheduled_at is None
    # last_match is the chronologically most recent dated match.
    assert result.last_match is not None
    assert result.last_match.scheduled_at == _BASE + timedelta(days=20)


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@st.composite
def _h2h_match_strategy(draw: st.DrawFn) -> Match:
    """Generate a Match between players ``A`` and ``B`` with a possible winner."""
    a_first = draw(st.booleans())
    winner_choice = draw(st.sampled_from(["A", "B", None]))
    day = draw(st.integers(min_value=0, max_value=365))
    outcome: MatchOutcome = draw(
        st.sampled_from(["completed", "walkover", "default", "unfinished", "unknown"])
    )
    return _match(
        player_a_id="A" if a_first else "B",
        player_b_id="B" if a_first else "A",
        winner_id=winner_choice,
        days_offset=day,
        outcome=outcome,
    )


@given(st.lists(_h2h_match_strategy(), min_size=0, max_size=20))
def test_perspective_swap_swaps_win_counts(matches: list[Match]) -> None:
    """Switching A and B swaps wins_a and wins_b but preserves totals.

    Property: head-to-head is symmetric in player ordering except for which
    side is "you". Total matches, match_list contents (as a set), and the
    streak holder (an absolute player ID, not a perspective) must be invariant
    under perspective swap.
    """
    forward = head_to_head(matches, "A", "B")
    reverse = head_to_head(matches, "B", "A")

    assert forward.total_matches == reverse.total_matches
    assert forward.wins_a == reverse.wins_b
    assert forward.wins_b == reverse.wins_a
    # streak holder is an absolute player ID and should not depend on perspective
    assert forward.streak_holder_id == reverse.streak_holder_id
    assert forward.streak_length == reverse.streak_length
    # last match is the same Match object regardless of perspective
    assert forward.last_match_winner_id == reverse.last_match_winner_id
    # match_list contains the same matches (order is deterministic and identical)
    assert len(forward.match_list) == len(reverse.match_list)
