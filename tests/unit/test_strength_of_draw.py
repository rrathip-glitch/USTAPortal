"""Unit tests for strength-of-draw enrichment."""

from __future__ import annotations

from statistics import mean, median

import pytest

from src.enrich.strength_of_draw import StrengthOfDrawResult, strength_of_draw
from src.models.draw import Draw, DrawEntry, DrawFormat, EntryStatus


def _draw(
    fmt: DrawFormat = "single_elimination",
    size: int | None = 8,
    usta_id: str = "draw-1",
) -> Draw:
    return Draw(
        usta_id=usta_id,
        tournament_id="tourn-1",
        name="Test Draw",
        format=fmt,
        size=size,
    )


def _entry(
    player_id: str,
    position: int | None,
    status: EntryStatus = "entered",
    seed: int | None = None,
) -> DrawEntry:
    return DrawEntry(
        draw_id="draw-1",
        player_id=player_id,
        seed=seed,
        position=position,
        status=status,
    )


def test_field_aggregates_eight_player_draw_all_rated() -> None:
    draw = _draw(size=8)
    entries = [_entry(f"p{i}", i) for i in range(1, 9)]
    # Ratings (lower = stronger), p1 is the focal.
    ratings = {
        "p1": 5.0,
        "p2": 12.0,
        "p3": 8.0,
        "p4": 20.0,
        "p5": 7.0,
        "p6": 30.0,
        "p7": 10.0,
        "p8": 25.0,
    }
    result = strength_of_draw(draw, entries, ratings, focal_player_id="p1")

    opp = [12.0, 8.0, 20.0, 7.0, 30.0, 10.0, 25.0]
    assert isinstance(result, StrengthOfDrawResult)
    assert result.draw_id == "draw-1"
    assert result.focal_player_id == "p1"
    assert result.field_size == 8
    assert result.average_opponent_rating == pytest.approx(mean(opp))
    assert result.median_opponent_rating == pytest.approx(median(opp))
    assert result.field_min_rating == pytest.approx(7.0)
    assert result.field_max_rating == pytest.approx(30.0)
    assert result.unrated_count == 0


def test_unrated_count_tallies_when_some_entries_lack_ratings() -> None:
    draw = _draw(size=4)
    entries = [_entry(f"p{i}", i) for i in range(1, 5)]
    ratings = {"p1": 5.0, "p3": 8.0}  # p2 and p4 unrated
    result = strength_of_draw(draw, entries, ratings, focal_player_id="p1")

    assert result.field_size == 4
    assert result.unrated_count == 2
    # Only p3 (the rated opponent) contributes.
    assert result.average_opponent_rating == pytest.approx(8.0)
    assert result.median_opponent_rating == pytest.approx(8.0)
    assert result.field_min_rating == pytest.approx(8.0)
    assert result.field_max_rating == pytest.approx(8.0)


def test_withdrawn_entries_excluded_from_field_and_aggregates() -> None:
    draw = _draw(size=4)
    entries = [
        _entry("p1", 1),
        _entry("p2", 2),
        _entry("p3", 3, status="withdrawn"),
        _entry("p4", 4),
    ]
    ratings = {"p1": 5.0, "p2": 10.0, "p3": 1.0, "p4": 20.0}
    result = strength_of_draw(draw, entries, ratings, focal_player_id="p1")

    assert result.field_size == 3  # withdrawn excluded
    assert result.field_min_rating == pytest.approx(10.0)  # p3's 1.0 ignored
    assert result.field_max_rating == pytest.approx(20.0)
    assert result.average_opponent_rating == pytest.approx(15.0)
    assert result.unrated_count == 0
    # Withdrawn p3 must not appear in the projected path either.
    assert "p3" not in result.projected_path


def test_projected_path_heuristic_four_player_focal_at_position_one() -> None:
    draw = _draw(size=4)
    entries = [
        _entry("p1", 1),
        _entry("p2", 2),
        _entry("p3", 3),
        _entry("p4", 4),
    ]
    # p3 is much stronger (lower rating) than p4, so the path projects p3
    # as the round-2 opponent.
    ratings = {"p1": 5.0, "p2": 12.0, "p3": 4.0, "p4": 20.0}
    result = strength_of_draw(draw, entries, ratings, focal_player_id="p1")

    assert result.projected_path == ["p2", "p3"]
    assert result.hardest_path_opponent_id == "p3"  # lowest rating on path
    assert result.easiest_path_opponent_id == "p2"
    assert result.path_average_rating == pytest.approx((12.0 + 4.0) / 2)


def test_round_robin_format_yields_empty_path_and_no_path_aggregates() -> None:
    draw = _draw(fmt="round_robin", size=4)
    entries = [_entry(f"p{i}", i) for i in range(1, 5)]
    ratings = {"p1": 5.0, "p2": 12.0, "p3": 8.0, "p4": 20.0}
    result = strength_of_draw(draw, entries, ratings, focal_player_id="p1")

    assert result.projected_path == []
    assert result.path_average_rating is None
    assert result.hardest_path_opponent_id is None
    assert result.easiest_path_opponent_id is None
    # Field aggregates still computed.
    assert result.field_size == 4
    assert result.average_opponent_rating == pytest.approx(mean([12.0, 8.0, 20.0]))


def test_focal_player_not_in_entries_raises_value_error() -> None:
    draw = _draw(size=4)
    entries = [_entry(f"p{i}", i) for i in range(1, 5)]
    ratings = {f"p{i}": float(i) for i in range(1, 5)}
    with pytest.raises(ValueError, match="focal_player_id"):
        strength_of_draw(draw, entries, ratings, focal_player_id="missing")


def test_unrated_path_opponents_skipped_from_aggregates_but_listed() -> None:
    draw = _draw(size=4)
    entries = [
        _entry("p1", 1),
        _entry("p2", 2),
        _entry("p3", 3),
        _entry("p4", 4),
    ]
    ratings = {"p1": 5.0, "p3": 8.0}  # p2 and p4 unrated
    result = strength_of_draw(
        draw, entries, ratings, focal_player_id="p1", projected_path=["p2", "p3"]
    )

    assert result.projected_path == ["p2", "p3"]
    # Only p3 contributes to the aggregates.
    assert result.path_average_rating == pytest.approx(8.0)
    assert result.hardest_path_opponent_id == "p3"
    assert result.easiest_path_opponent_id == "p3"


def test_empty_field_returns_none_aggregates() -> None:
    draw = _draw(size=2)
    entries = [
        _entry("p1", 1, status="withdrawn"),
        _entry("p2", 2, status="withdrawn"),
    ]
    result = strength_of_draw(draw, entries, ratings={}, focal_player_id="p1")

    assert result.field_size == 0
    assert result.average_opponent_rating is None
    assert result.median_opponent_rating is None
    assert result.field_min_rating is None
    assert result.field_max_rating is None
    assert result.path_average_rating is None
    assert result.hardest_path_opponent_id is None
    assert result.easiest_path_opponent_id is None
    assert result.projected_path == []
    assert result.unrated_count == 0


def test_explicit_projected_path_overrides_heuristic() -> None:
    draw = _draw(size=4)
    entries = [_entry(f"p{i}", i) for i in range(1, 5)]
    ratings = {"p1": 5.0, "p2": 12.0, "p3": 4.0, "p4": 20.0}
    # Caller forces a different bracket projection.
    result = strength_of_draw(
        draw, entries, ratings, focal_player_id="p1", projected_path=["p2", "p4"]
    )
    assert result.projected_path == ["p2", "p4"]
    assert result.hardest_path_opponent_id == "p2"
    assert result.easiest_path_opponent_id == "p4"


def test_round_two_picks_lower_rating_with_position_tiebreak() -> None:
    draw = _draw(size=4)
    entries = [_entry(f"p{i}", i) for i in range(1, 5)]
    # Equal ratings on p3/p4 — tiebreak picks the smaller position (p3).
    ratings = {"p1": 5.0, "p2": 12.0, "p3": 9.0, "p4": 9.0}
    result = strength_of_draw(draw, entries, ratings, focal_player_id="p1")
    assert result.projected_path == ["p2", "p3"]
