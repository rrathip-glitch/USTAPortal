"""Unit tests for the recent-form enrichment.

Synthetic match data — no fixtures. The math is verifiable from the inputs.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from src.enrich.form import FormResult, recent_form
from src.models.match import Match, MatchOutcome

PLAYER = "player-self"
OPP = "opponent-x"
DRAW = "draw-1"


def _match(
    *,
    match_id: str,
    when: datetime | None,
    a: str = PLAYER,
    b: str = OPP,
    winner: str | None = PLAYER,
    outcome: MatchOutcome = "completed",
    score: str | None = "6-0 6-0",
) -> Match:
    return Match(
        usta_id=match_id,
        draw_id=DRAW,
        scheduled_at=when,
        player_a_id=a,
        player_b_id=b,
        winner_id=winner,
        outcome=outcome,
        score_raw=score,
    )


def _series(n: int, *, base: datetime | None = None) -> list[datetime]:
    """Return `n` ascending timestamps, one per day from `base`."""
    base = base or datetime(2026, 1, 1)
    return [base + timedelta(days=i) for i in range(n)]


# ---------------------------------------------------------------------------
# Spec-required cases
# ---------------------------------------------------------------------------


def test_clean_five_match_window_win_rate() -> None:
    times = _series(5)
    matches = [
        _match(match_id="m1", when=times[0], winner=PLAYER),
        _match(match_id="m2", when=times[1], winner=OPP),
        _match(match_id="m3", when=times[2], winner=PLAYER),
        _match(match_id="m4", when=times[3], winner=PLAYER),
        _match(match_id="m5", when=times[4], winner=OPP),
    ]
    result = recent_form(matches, PLAYER, window=8)
    assert result.matches_considered == 5
    assert result.wins == 3
    assert result.losses == 2
    assert result.win_rate == pytest.approx(3 / 5)
    # Most recent first → m5 (L), m4 (W), m3 (W), m2 (L), m1 (W).
    assert [r.match_id for r in result.recent_results] == ["m5", "m4", "m3", "m2", "m1"]


def test_window_caps_match_count() -> None:
    times = _series(12)
    matches = [
        _match(match_id=f"m{i}", when=times[i], winner=PLAYER if i % 2 == 0 else OPP)
        for i in range(12)
    ]
    result = recent_form(matches, PLAYER, window=8)
    assert result.window_size == 8
    assert result.matches_considered == 8
    assert len(result.recent_results) == 8
    # The 8 newest are indices 4..11 (oldest dropped).
    assert {r.match_id for r in result.recent_results} == {f"m{i}" for i in range(4, 12)}


def test_streak_three_wins_then_loss_interrupts() -> None:
    times = _series(4)
    matches = [
        _match(match_id="m_old", when=times[0], winner=OPP),
        _match(match_id="m1", when=times[1], winner=PLAYER),
        _match(match_id="m2", when=times[2], winner=PLAYER),
        _match(match_id="m3", when=times[3], winner=PLAYER),
    ]
    result = recent_form(matches, PLAYER)
    assert result.current_streak == ("W", 3)

    # Now interrupt: most recent is a loss → streak is ("L", 1) regardless of
    # the prior wins.
    later = times[3] + timedelta(days=1)
    matches.append(_match(match_id="m4", when=later, winner=OPP))
    result2 = recent_form(matches, PLAYER)
    assert result2.current_streak == ("L", 1)


def test_walkover_with_winner_counts_without_winner_does_not() -> None:
    times = _series(3)
    matches = [
        _match(
            match_id="wo_with",
            when=times[0],
            winner=PLAYER,
            outcome="walkover",
            score=None,
        ),
        _match(
            match_id="wo_without",
            when=times[1],
            winner=None,
            outcome="walkover",
            score=None,
        ),
        _match(match_id="reg", when=times[2], winner=OPP, outcome="completed"),
    ]
    result = recent_form(matches, PLAYER)
    # All three are present in the window — outcome="walkover" is not dropped.
    assert result.matches_considered == 3
    assert result.wins == 1  # the walkover with winner=PLAYER
    assert result.losses == 1  # the regular completed loss
    # The walkover-without-winner contributes "unknown".
    by_id = {r.match_id: r.result for r in result.recent_results}
    assert by_id["wo_with"] == "W"
    assert by_id["wo_without"] == "unknown"
    assert by_id["reg"] == "L"
    assert result.win_rate == pytest.approx(0.5)


def test_either_side_ordering_player_a_or_player_b() -> None:
    times = _series(2)
    # Same logical record, but PLAYER is on opposite sides in the two matches.
    matches = [
        _match(match_id="as_a", when=times[0], a=PLAYER, b=OPP, winner=PLAYER),
        _match(match_id="as_b", when=times[1], a=OPP, b=PLAYER, winner=PLAYER),
    ]
    result = recent_form(matches, PLAYER)
    assert result.wins == 2
    assert result.losses == 0
    # Opponent is reported correctly from PLAYER's POV in both cases.
    assert all(r.opponent_id == OPP for r in result.recent_results)


def test_window_zero_or_negative_raises() -> None:
    with pytest.raises(ValueError):
        recent_form([], PLAYER, window=0)
    with pytest.raises(ValueError):
        recent_form([], PLAYER, window=-3)


# ---------------------------------------------------------------------------
# Additional safety nets
# ---------------------------------------------------------------------------


def test_unfinished_and_unknown_are_dropped_from_window() -> None:
    times = _series(3)
    matches = [
        _match(match_id="done", when=times[0], winner=PLAYER, outcome="completed"),
        _match(match_id="live", when=times[1], winner=None, outcome="unfinished"),
        _match(match_id="huh", when=times[2], winner=None, outcome="unknown"),
    ]
    result = recent_form(matches, PLAYER)
    assert result.matches_considered == 1
    assert [r.match_id for r in result.recent_results] == ["done"]


def test_empty_input_yields_zeroed_result() -> None:
    result = recent_form([], PLAYER)
    assert result == FormResult(
        player_id=PLAYER,
        window_size=8,
        matches_considered=0,
    )
    assert result.win_rate == 0.0
    assert result.current_streak == ("none", 0)


def test_streak_skips_unknown_but_continues_through_it() -> None:
    times = _series(3)
    matches = [
        _match(match_id="oldest_w", when=times[0], winner=PLAYER, outcome="completed"),
        _match(
            match_id="middle_unk",
            when=times[1],
            winner=None,
            outcome="walkover",
            score=None,
        ),
        _match(match_id="newest_w", when=times[2], winner=PLAYER, outcome="completed"),
    ]
    result = recent_form(matches, PLAYER)
    # newest is W, middle is unknown (skipped), oldest is W → streak ("W", 2).
    assert result.current_streak == ("W", 2)


def test_matches_without_scheduled_at_sort_last() -> None:
    times = _series(2)
    matches = [
        _match(match_id="dated_old", when=times[0], winner=PLAYER),
        _match(match_id="dated_new", when=times[1], winner=OPP),
        _match(match_id="undated", when=None, winner=PLAYER),
    ]
    result = recent_form(matches, PLAYER, window=8)
    # dated_new first, then dated_old, then undated (None).
    assert [r.match_id for r in result.recent_results] == [
        "dated_new",
        "dated_old",
        "undated",
    ]


def test_all_unknown_outcomes_yield_none_streak() -> None:
    times = _series(2)
    matches = [
        _match(
            match_id="wo1", when=times[0], winner=None, outcome="walkover", score=None
        ),
        _match(
            match_id="wo2", when=times[1], winner=None, outcome="walkover", score=None
        ),
    ]
    result = recent_form(matches, PLAYER)
    assert result.wins == 0
    assert result.losses == 0
    assert result.win_rate == 0.0
    assert result.current_streak == ("none", 0)


# ---------------------------------------------------------------------------
# Property test: monotonicity in wins.
# ---------------------------------------------------------------------------

ResultLabel = Literal["W", "L"]


@given(
    base=st.lists(st.sampled_from(["W", "L"]), min_size=0, max_size=20),
    window=st.integers(min_value=1, max_value=12),
)
def test_adding_a_recent_win_never_decreases_win_count(
    base: list[ResultLabel], window: int
) -> None:
    """Appending a fresh win to a player's history cannot lower `wins`.

    Within a fixed window cap, adding the most recent match as a win can
    only either (a) bump the win count by 1 (when the window had room or
    when an older win was displaced — in which case the count is preserved
    rather than reduced) or (b) hold it steady (when an older *win* fell
    out as the new win came in).
    """
    times = _series(len(base) + 1)
    matches = [
        _match(
            match_id=f"m{i}",
            when=times[i],
            winner=PLAYER if label == "W" else OPP,
        )
        for i, label in enumerate(base)
    ]
    before = recent_form(matches, PLAYER, window=window)

    # Append the new win as the most recent match.
    matches.append(_match(match_id="m_new", when=times[-1], winner=PLAYER))
    after = recent_form(matches, PLAYER, window=window)

    assert after.wins >= before.wins
    # And the most recent result is always a win.
    assert after.recent_results[0].result == "W"
