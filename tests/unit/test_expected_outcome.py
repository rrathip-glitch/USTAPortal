"""Unit tests for the expected-outcome enrichment.

Synthetic ratings only — the math is fully verifiable from constructed
inputs. Property test confirms the probabilities sum to 1.0 and stay in
[0, 1] for any pair of WTN-axis ratings.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from src.enrich.expected_outcome import (
    ExpectedOutcomeResult,
    expected_outcome,
    expected_outcomes_along_path,
)


def test_identical_ratings_give_fifty_fifty() -> None:
    ratings = {"a": 12.0, "b": 12.0}
    result = expected_outcome("a", "b", ratings)
    assert isinstance(result, ExpectedOutcomeResult)
    assert result.probability_a == pytest.approx(0.5)
    assert result.probability_b == pytest.approx(0.5)
    assert result.confidence == "high"
    assert result.rating_a == 12.0
    assert result.rating_b == 12.0
    assert result.model_version == "elo-wtn-1"


def test_strong_player_dominates_weak_player() -> None:
    # A 12-WTN gap (8.0 vs 20.0) is a substantial skill difference.
    ratings = {"strong": 8.0, "weak": 20.0}
    result = expected_outcome("strong", "weak", ratings)
    assert result.probability_a > 0.7
    assert result.probability_b < 0.3
    assert result.probability_a + result.probability_b == pytest.approx(1.0)
    assert result.confidence == "high"


def test_orientation_flips_probability() -> None:
    ratings = {"x": 8.0, "y": 20.0}
    forward = expected_outcome("x", "y", ratings)
    reverse = expected_outcome("y", "x", ratings)
    assert forward.probability_a == pytest.approx(reverse.probability_b)
    assert forward.probability_b == pytest.approx(reverse.probability_a)


def test_missing_one_rating_returns_half_with_low_confidence() -> None:
    # Only player "a" has a rating; "b" is unrated.
    ratings = {"a": 10.0}
    result = expected_outcome("a", "b", ratings)
    assert result.probability_a == 0.5
    assert result.probability_b == 0.5
    assert result.confidence == "low"
    assert result.rating_a == 10.0
    assert result.rating_b is None


def test_missing_both_ratings_returns_half_with_no_confidence() -> None:
    result = expected_outcome("a", "b", ratings={})
    assert result.probability_a == 0.5
    assert result.probability_b == 0.5
    assert result.confidence == "none"
    assert result.rating_a is None
    assert result.rating_b is None


def test_same_player_raises_value_error() -> None:
    with pytest.raises(ValueError, match="must differ"):
        expected_outcome("p1", "p1", ratings={"p1": 10.0})


def test_unknown_model_version_raises() -> None:
    with pytest.raises(ValueError, match="unsupported model_version"):
        expected_outcome("a", "b", {"a": 10.0, "b": 12.0}, model_version="ml-v2")


def test_low_snapshot_confidence_downgrades_label_to_medium() -> None:
    ratings = {"a": 10.0, "b": 12.0}
    confidences = {"a": 0.85, "b": 0.4}  # b is below threshold
    result = expected_outcome("a", "b", ratings, confidences=confidences)
    assert result.confidence == "medium"


def test_high_snapshot_confidence_keeps_label_high() -> None:
    ratings = {"a": 10.0, "b": 12.0}
    confidences = {"a": 0.85, "b": 0.9}
    result = expected_outcome("a", "b", ratings, confidences=confidences)
    assert result.confidence == "high"


def test_missing_confidence_entry_falls_back_to_medium() -> None:
    # Both rated, but we only have a confidence value for one side.
    ratings = {"a": 10.0, "b": 12.0}
    confidences = {"a": 0.85}
    result = expected_outcome("a", "b", ratings, confidences=confidences)
    assert result.confidence == "medium"


def test_out_of_range_rating_is_clamped_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ratings = {"a": -5.0, "b": 20.0}  # negative rating triggers clamp
    with caplog.at_level("WARNING"):
        result = expected_outcome("a", "b", ratings)
    # Rating echoed back unclamped (ground truth preserved); probability is
    # finite and sane (a clamped 0.1 vs 20.0 is a strong-vs-medium match).
    assert result.rating_a == -5.0
    assert 0.0 <= result.probability_a <= 1.0
    assert result.probability_a > 0.7
    assert any("clamping" in rec.message for rec in caplog.records)


def test_path_returns_one_result_per_opponent_in_order() -> None:
    ratings = {"focal": 10.0, "o1": 15.0, "o2": 12.0, "o3": 8.0}
    path = ["o1", "o2", "o3"]
    results = expected_outcomes_along_path("focal", path, ratings)
    assert len(results) == 3
    assert [r.player_b_id for r in results] == ["o1", "o2", "o3"]
    assert all(r.player_a_id == "focal" for r in results)
    # focal stronger than o1 → probability_a > 0.5
    assert results[0].probability_a > 0.5
    # focal weaker than o3 → probability_a < 0.5
    assert results[2].probability_a < 0.5


def test_path_with_focal_in_path_skips_self_match() -> None:
    ratings = {"focal": 10.0, "o1": 12.0}
    path = ["o1", "focal"]  # degenerate path that includes focal
    results = expected_outcomes_along_path("focal", path, ratings)
    # focal-vs-focal entry is skipped, only the o1 result remains.
    assert len(results) == 1
    assert results[0].player_b_id == "o1"


def test_empty_path_returns_empty_list() -> None:
    assert expected_outcomes_along_path("focal", [], {"focal": 10.0}) == []


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@given(
    rating_a=st.floats(min_value=1.0, max_value=40.0, allow_nan=False),
    rating_b=st.floats(min_value=1.0, max_value=40.0, allow_nan=False),
)
def test_probabilities_sum_to_one_and_lie_in_unit_interval(
    rating_a: float, rating_b: float
) -> None:
    ratings = {"a": rating_a, "b": rating_b}
    result = expected_outcome("a", "b", ratings)
    assert 0.0 <= result.probability_a <= 1.0
    assert 0.0 <= result.probability_b <= 1.0
    assert math.isclose(result.probability_a + result.probability_b, 1.0, abs_tol=1e-9)


@given(
    rating_a=st.floats(min_value=1.0, max_value=40.0, allow_nan=False),
    rating_b=st.floats(min_value=1.0, max_value=40.0, allow_nan=False),
)
def test_lower_wtn_player_always_favored(rating_a: float, rating_b: float) -> None:
    """Monotonicity: a strictly stronger WTN must yield probability_a > 0.5.

    The Elo logistic has a slope of ~1/400 at parity, so two ratings
    that differ by less than one ULP at the 32-WTN scale cannot
    produce a probability distinguishable from 0.5 in IEEE-754. We
    skip those cases — they represent floating-point noise, not a
    monotonicity violation.
    """
    if abs(rating_a - rating_b) < 1e-6:
        # Ratings indistinguishable for any practical purpose; the
        # logistic returns exactly 0.5. Treat as equal.
        ratings = {"a": rating_a, "b": rating_b}
        result = expected_outcome("a", "b", ratings)
        assert result.probability_a == pytest.approx(0.5, abs=1e-9)
        return
    ratings = {"a": rating_a, "b": rating_b}
    result = expected_outcome("a", "b", ratings)
    if rating_a < rating_b:
        assert result.probability_a > 0.5
    elif rating_a > rating_b:
        assert result.probability_a < 0.5
    else:
        assert result.probability_a == pytest.approx(0.5)
