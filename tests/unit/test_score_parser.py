"""Unit + property tests for the score parser."""

from __future__ import annotations

import pytest
from hypothesis import given

from src.models.match import MatchOutcome, SetScore
from src.parse.matches import format_score, infer_winner, parse_score
from tests.strategies import valid_score_string

CONCRETE_CASES: list[tuple[str, list[SetScore], MatchOutcome]] = [
    (
        "6-4 6-3",
        [SetScore(games_a=6, games_b=4), SetScore(games_a=6, games_b=3)],
        "completed",
    ),
    (
        "7-6(3) 6-4",
        [
            SetScore(games_a=7, games_b=6, tiebreak_a=7, tiebreak_b=3),
            SetScore(games_a=6, games_b=4),
        ],
        "completed",
    ),
    (
        "6-4 4-6 7-5",
        [
            SetScore(games_a=6, games_b=4),
            SetScore(games_a=4, games_b=6),
            SetScore(games_a=7, games_b=5),
        ],
        "completed",
    ),
    (
        "6-4 4-6 7-6(3)",
        [
            SetScore(games_a=6, games_b=4),
            SetScore(games_a=4, games_b=6),
            SetScore(games_a=7, games_b=6, tiebreak_a=7, tiebreak_b=3),
        ],
        "completed",
    ),
    (
        "6-4 3-2 RET",
        [SetScore(games_a=6, games_b=4), SetScore(games_a=3, games_b=2)],
        "retired",
    ),
    (
        "6-4 3-2 ret.",
        [SetScore(games_a=6, games_b=4), SetScore(games_a=3, games_b=2)],
        "retired",
    ),
    ("W/O", [], "walkover"),
    ("walkover", [], "walkover"),
    ("DEF", [], "default"),
    ("", [], "unfinished"),
    ("-", [], "unfinished"),
    ("TBD", [], "unfinished"),
    ("8-6", [SetScore(games_a=8, games_b=6)], "completed"),
    (
        "6-4 4-6 [10-7]",
        [
            SetScore(games_a=6, games_b=4),
            SetScore(games_a=4, games_b=6),
            SetScore(games_a=1, games_b=0, tiebreak_a=10, tiebreak_b=7),
        ],
        "completed",
    ),
    (
        "6-4 4-6 1-0(7)",
        [
            SetScore(games_a=6, games_b=4),
            SetScore(games_a=4, games_b=6),
            SetScore(games_a=1, games_b=0, tiebreak_a=10, tiebreak_b=7),
        ],
        "completed",
    ),
    (
        "  6-4   6-3  ",
        [SetScore(games_a=6, games_b=4), SetScore(games_a=6, games_b=3)],
        "completed",
    ),
]


@pytest.mark.parametrize(("score_str", "expected_sets", "expected_outcome"), CONCRETE_CASES)
def test_concrete_parse_cases(
    score_str: str,
    expected_sets: list[SetScore],
    expected_outcome: MatchOutcome,
) -> None:
    sets, outcome, residual = parse_score(score_str)
    assert outcome == expected_outcome
    assert sets == expected_sets
    assert residual is None


def test_infer_winner_two_set_match() -> None:
    sets, outcome, _ = parse_score("6-4 6-3")
    assert infer_winner(sets, "A", "B", outcome) == "A"


def test_infer_winner_retirement() -> None:
    sets, outcome, _ = parse_score("6-4 3-2 RET")
    assert outcome == "retired"
    # A won set 1, set 2 was incomplete (3-2 with B serving or otherwise);
    # winner is the side with more completed sets — A.
    assert infer_winner(sets, "A", "B", outcome) == "A"


def test_infer_winner_walkover_returns_none() -> None:
    sets, outcome, _ = parse_score("W/O")
    assert infer_winner(sets, "A", "B", outcome) is None


def test_infer_winner_unfinished_returns_none() -> None:
    sets, outcome, _ = parse_score("")
    assert infer_winner(sets, "A", "B", outcome) is None


def test_infer_winner_split_sets_returns_none() -> None:
    # Even-set split (e.g., interrupted with no decider) — cannot infer.
    sets = [SetScore(games_a=6, games_b=4), SetScore(games_a=4, games_b=6)]
    assert infer_winner(sets, "A", "B", "completed") is None


@given(score=valid_score_string())
def test_round_trip_property(score: str) -> None:
    """Parsing a score, formatting it, and re-parsing yields the same structure."""
    sets1, outcome1, _ = parse_score(score)
    rendered = format_score(sets1, outcome1)
    sets2, outcome2, _ = parse_score(rendered)
    assert outcome1 == outcome2
    assert sets1 == sets2


@given(score=valid_score_string())
def test_completed_set_validity_property(score: str) -> None:
    """Every completed standard set has a winner with games in {6, 7} (or pro-set 8+)."""
    sets, outcome, _ = parse_score(score)
    if outcome not in {"completed", "retired"}:
        return
    for s in sets:
        # Skip pseudo-set match-tiebreak rows (1-0 with both tiebreak fields).
        if {s.games_a, s.games_b} == {0, 1} and s.tiebreak_a is not None:
            continue
        winner_games = max(s.games_a, s.games_b)
        loser_games = min(s.games_a, s.games_b)
        # In a retired match the final set may be partial (e.g., 3-2); only
        # assert validity for sets that look complete (winner >= 6).
        if winner_games < 6:
            assert outcome == "retired"
            continue
        assert winner_games in {6, 7} or winner_games >= 8
        assert loser_games < winner_games


@given(score=valid_score_string())
def test_tiebreak_property(score: str) -> None:
    """A 7-6 set always has a tiebreak; a 6-4 set never does."""
    sets, _outcome, _ = parse_score(score)
    for s in sets:
        if {s.games_a, s.games_b} == {0, 1} and s.tiebreak_a is not None:
            continue  # match-tiebreak pseudo-set
        if {s.games_a, s.games_b} == {7, 6}:
            assert s.tiebreak_a is not None and s.tiebreak_b is not None
        if {s.games_a, s.games_b} == {6, 4}:
            assert s.tiebreak_a is None and s.tiebreak_b is None


@given(score=valid_score_string())
def test_walkover_default_unfinished_have_no_sets(score: str) -> None:
    sets, outcome, _ = parse_score(score)
    if outcome in {"walkover", "default", "unfinished"}:
        assert sets == []
