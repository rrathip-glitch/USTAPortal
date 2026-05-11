"""Unit tests for the surface-preference enrichment.

Synthetic match data — no fixtures. Every expected number is derivable from
the constructed inputs.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from src.enrich.surface_preference import (
    SurfacePreferenceResult,
    SurfaceStat,
    surface_preference,
)
from src.models.match import Match
from src.models.tournament import Surface

PLAYER = "player-self"
OPP = "opponent-x"
DRAW = "draw-1"


def _match(
    *,
    match_id: str,
    court: str | None = "Hard",
    a: str = PLAYER,
    b: str = OPP,
    winner: str | None = PLAYER,
) -> Match:
    return Match(
        usta_id=match_id,
        draw_id=DRAW,
        court=court,
        player_a_id=a,
        player_b_id=b,
        winner_id=winner,
        outcome="completed",
        score_raw="6-0 6-0",
    )


# ---------------------------------------------------------------------------
# Spec-required cases
# ---------------------------------------------------------------------------


def test_empty_match_list_returns_zeroed_result() -> None:
    result = surface_preference([], PLAYER)
    assert result == SurfacePreferenceResult(
        player_id=PLAYER,
        by_surface={},
        best_surface=None,
        worst_surface=None,
        total_matches=0,
    )
    assert result.total_matches == 0
    assert result.best_surface is None
    assert result.worst_surface is None


def test_single_won_match_records_stat_but_best_is_none_below_gate() -> None:
    matches = [_match(match_id="m1", court="Hard", winner=PLAYER)]
    result = surface_preference(matches, PLAYER)
    assert result.total_matches == 1
    assert result.by_surface == {
        "hard": SurfaceStat(matches=1, wins=1, losses=0, win_rate=1.0)
    }
    # Sample size is 1; we refuse to recommend.
    assert result.best_surface is None
    assert result.worst_surface is None


def test_mixed_surfaces_pick_best_and_worst() -> None:
    # Hard: 3W / 2L → 0.600. Clay: 3W / 0L → 1.000. Both >= 3 matches, so
    # both are eligible for best/worst.
    matches = [
        _match(match_id="h1", court="Hard", winner=PLAYER),
        _match(match_id="h2", court="Hard", winner=PLAYER),
        _match(match_id="h3", court="Hard", winner=PLAYER),
        _match(match_id="h4", court="Hard", winner=OPP),
        _match(match_id="h5", court="Hard", winner=OPP),
        _match(match_id="c1", court="Clay", winner=PLAYER),
        _match(match_id="c2", court="Clay", winner=PLAYER),
        _match(match_id="c3", court="Clay", winner=PLAYER),
    ]
    result = surface_preference(matches, PLAYER)
    assert result.total_matches == 8
    assert result.by_surface["hard"] == SurfaceStat(
        matches=5, wins=3, losses=2, win_rate=0.6
    )
    assert result.by_surface["clay"] == SurfaceStat(
        matches=3, wins=3, losses=0, win_rate=1.0
    )
    assert result.best_surface == "clay"
    assert result.worst_surface == "hard"


def test_custom_surface_lookup_overrides_court_field() -> None:
    # Every match has court="Hard" — but the custom lookup forces them to
    # "grass". The result should be entirely on grass.
    matches = [
        _match(match_id="m1", court="Hard", winner=PLAYER),
        _match(match_id="m2", court="Hard", winner=PLAYER),
        _match(match_id="m3", court="Hard", winner=OPP),
    ]

    def lookup(_: Match) -> Surface:
        return "grass"

    result = surface_preference(matches, PLAYER, surface_lookup=lookup)
    assert "hard" not in result.by_surface
    assert result.by_surface["grass"] == SurfaceStat(
        matches=3, wins=2, losses=1, win_rate=round(2 / 3, 3)
    )
    assert result.total_matches == 3
    assert result.best_surface == "grass"  # only eligible surface
    assert result.worst_surface == "grass"


def test_unknown_surface_excluded_from_by_surface_but_counted_in_total() -> None:
    # Hard with 3 matches (valid surface) + 2 matches on a court string that
    # doesn't map (resolves to "unknown"). The unknown ones still increase
    # total_matches but never appear as a key.
    matches = [
        _match(match_id="h1", court="Hard", winner=PLAYER),
        _match(match_id="h2", court="Hard", winner=PLAYER),
        _match(match_id="h3", court="Hard", winner=OPP),
        _match(match_id="u1", court="Mystery", winner=PLAYER),
        _match(match_id="u2", court=None, winner=OPP),
    ]
    result = surface_preference(matches, PLAYER)
    assert result.total_matches == 5
    assert set(result.by_surface.keys()) == {"hard"}
    assert result.by_surface["hard"] == SurfaceStat(
        matches=3, wins=2, losses=1, win_rate=round(2 / 3, 3)
    )
    # "unknown" is never the best/worst recommendation either.
    assert result.best_surface == "hard"
    assert result.worst_surface == "hard"


def test_matches_with_no_winner_id_are_ignored() -> None:
    # Two real matches (one win, one loss) on Hard plus a no-winner row that
    # must not be counted anywhere.
    matches = [
        _match(match_id="h1", court="Hard", winner=PLAYER),
        _match(match_id="h2", court="Hard", winner=OPP),
        _match(match_id="wo", court="Hard", winner=None),
    ]
    result = surface_preference(matches, PLAYER)
    assert result.total_matches == 2
    assert result.by_surface["hard"] == SurfaceStat(
        matches=2, wins=1, losses=1, win_rate=0.5
    )


# ---------------------------------------------------------------------------
# Extra safety nets
# ---------------------------------------------------------------------------


def test_indoor_maps_to_indoor_hard_and_is_case_insensitive() -> None:
    matches = [
        _match(match_id="i1", court="Indoor", winner=PLAYER),
        _match(match_id="i2", court="INDOOR", winner=PLAYER),
        _match(match_id="i3", court="indoor", winner=OPP),
    ]
    result = surface_preference(matches, PLAYER)
    assert "indoor_hard" in result.by_surface
    assert result.by_surface["indoor_hard"] == SurfaceStat(
        matches=3, wins=2, losses=1, win_rate=round(2 / 3, 3)
    )


def test_player_can_be_on_either_side() -> None:
    matches = [
        _match(match_id="ab", court="Hard", a=PLAYER, b=OPP, winner=PLAYER),
        _match(match_id="ba", court="Hard", a=OPP, b=PLAYER, winner=PLAYER),
        _match(match_id="ab2", court="Hard", a=PLAYER, b=OPP, winner=OPP),
    ]
    result = surface_preference(matches, PLAYER)
    assert result.by_surface["hard"] == SurfaceStat(
        matches=3, wins=2, losses=1, win_rate=round(2 / 3, 3)
    )


def test_matches_not_involving_player_are_filtered_out() -> None:
    matches = [
        _match(match_id="mine", court="Hard", winner=PLAYER),
        _match(match_id="theirs", court="Clay", a="other-a", b="other-b", winner="other-a"),
    ]
    result = surface_preference(matches, PLAYER)
    assert result.total_matches == 1
    assert set(result.by_surface.keys()) == {"hard"}


def test_model_dump_round_trips_to_plain_dict() -> None:
    matches = [
        _match(match_id="h1", court="Hard", winner=PLAYER),
        _match(match_id="h2", court="Hard", winner=OPP),
        _match(match_id="h3", court="Hard", winner=PLAYER),
    ]
    dumped = surface_preference(matches, PLAYER).model_dump()
    assert dumped["player_id"] == PLAYER
    assert dumped["total_matches"] == 3
    assert dumped["by_surface"]["hard"] == {
        "matches": 3,
        "wins": 2,
        "losses": 1,
        "win_rate": round(2 / 3, 3),
    }


def test_win_rate_is_rounded_to_three_decimals() -> None:
    # 1 win, 2 losses → 0.3333... → rounded to 0.333.
    matches = [
        _match(match_id="h1", court="Hard", winner=PLAYER),
        _match(match_id="h2", court="Hard", winner=OPP),
        _match(match_id="h3", court="Hard", winner=OPP),
    ]
    result = surface_preference(matches, PLAYER)
    assert result.by_surface["hard"].win_rate == 0.333


def test_best_worst_tie_break_prefers_more_matches() -> None:
    # Hard: 6W / 0L. Clay: 1W / 0L (below gate, ineligible). Grass: 3W / 0L.
    # Hard and Grass are tied at 1.000 win rate; Hard has more matches and
    # should win the best slot.
    matches = (
        [_match(match_id=f"h{i}", court="Hard", winner=PLAYER) for i in range(6)]
        + [_match(match_id="c1", court="Clay", winner=PLAYER)]
        + [_match(match_id=f"g{i}", court="Grass", winner=PLAYER) for i in range(3)]
    )
    result = surface_preference(matches, PLAYER)
    # Clay is in by_surface (1 decided match) but never recommended.
    assert "clay" in result.by_surface
    assert result.best_surface == "hard"
    # Worst is also among the gated set; both Hard and Grass tie at 1.000
    # so the min is broken by *fewer* matches → grass wins.
    assert result.worst_surface == "grass"


# ---------------------------------------------------------------------------
# Property test: monotonicity in wins per surface.
# ---------------------------------------------------------------------------


@given(
    base_results=st.lists(st.sampled_from(["W", "L"]), min_size=0, max_size=20),
)
def test_adding_a_win_on_a_surface_never_lowers_that_surfaces_wins(
    base_results: list[str],
) -> None:
    """Appending a win on Hard cannot decrease the Hard win count.

    Form-style monotonicity property: the per-surface bucket only grows in
    one direction when fed an unambiguous win, regardless of what's there
    already.
    """
    matches = [
        _match(
            match_id=f"m{i}",
            court="Hard",
            winner=PLAYER if r == "W" else OPP,
        )
        for i, r in enumerate(base_results)
    ]
    before = surface_preference(matches, PLAYER)
    before_wins = before.by_surface.get("hard")
    before_count = before_wins.wins if before_wins is not None else 0

    matches.append(_match(match_id="m_new", court="Hard", winner=PLAYER))
    after = surface_preference(matches, PLAYER)
    assert "hard" in after.by_surface
    assert after.by_surface["hard"].wins == before_count + 1
    assert after.by_surface["hard"].wins >= before_count


def test_win_rate_value_in_unit_interval_for_arbitrary_inputs() -> None:
    # Spot check that win_rate stays in [0,1] across a couple of shapes.
    cases = [
        [_match(match_id="a", court="Hard", winner=PLAYER)],
        [_match(match_id="b", court="Hard", winner=OPP)],
        [
            _match(match_id="c", court="Clay", winner=PLAYER),
            _match(match_id="d", court="Clay", winner=OPP),
        ],
    ]
    for case in cases:
        result = surface_preference(case, PLAYER)
        for stat in result.by_surface.values():
            assert 0.0 <= stat.win_rate <= 1.0


def test_pytest_approx_handles_rounded_win_rate() -> None:
    # Sanity check that the win_rate value (0.333) is close to 1/3.
    matches = [
        _match(match_id="h1", court="Hard", winner=PLAYER),
        _match(match_id="h2", court="Hard", winner=OPP),
        _match(match_id="h3", court="Hard", winner=OPP),
    ]
    result = surface_preference(matches, PLAYER)
    assert result.by_surface["hard"].win_rate == pytest.approx(1 / 3, abs=1e-3)
