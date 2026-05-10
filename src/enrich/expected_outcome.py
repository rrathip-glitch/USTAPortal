"""Expected-outcome enrichment.

Computes a transparent Elo-style win probability for a single match between
two players, given each side's WTN-axis rating. v1 has no machine learning
(per SPEC.md Section 7) — the math is fully visible, the K-factor is fixed,
and the rating-to-Elo transform is documented inline so a coach can audit it.

Inputs
------
- ``player_a_id``, ``player_b_id``: USTA player IDs. Must differ; passing the
  same ID for both sides raises :class:`ValueError`. Order is significant —
  side A is the "you" perspective, side B is the opponent. The probabilities
  in the returned model are oriented from A's point of view.
- ``ratings``: ``dict[player_id, float]`` where each rating is a WTN value on
  the canonical 1.0-40.0 scale (lower = stronger). A player whose ID is not
  in the dict is treated as having no rating; we never silently impute a
  default. The caller resolves "WTN if available, ranking-derived synthetic
  rating otherwise" before calling this function — this module is rating-axis
  agnostic in the sense that any number on the WTN scale works.
- ``confidences`` (optional): ``dict[player_id, float]`` where each value is
  the WTN snapshot's confidence in [0, 1]. When provided, the
  confidence label downgrades from "high" to "medium" if either side's
  confidence is below 0.7. When ``None``, both-ratings-present implies
  "high"; this is the path the UI uses today.
- ``model_version``: identifier for the win-probability model. The only
  supported value in v1 is ``"elo-wtn-1"``; other values raise
  :class:`ValueError`. Future versions will live behind feature flags so the
  derivation is always reproducible from the model_version alone.

Output
------
An :class:`ExpectedOutcomeResult` with:

- ``player_a_id``, ``player_b_id``: echoed back for the UI to render.
- ``rating_a``, ``rating_b``: ``float | None``. The rating values that fed
  the computation, or ``None`` if missing. Echoed so the UI can show the
  derivation alongside the percentage.
- ``probability_a``: float in ``[0.0, 1.0]``. ``0.5`` whenever either rating
  is missing — the explicit "no signal" return value.
- ``probability_b``: ``1.0 - probability_a``, by construction.
- ``model_version``: identifier of the model used.
- ``confidence``: one of ``"high" | "medium" | "low" | "none"``:

  - ``"high"`` — both ratings present (and, when ``confidences`` is supplied,
    both >= 0.7).
  - ``"medium"`` — both ratings present but at least one snapshot's
    confidence is < 0.7 (only emitted when ``confidences`` is supplied).
  - ``"low"`` — exactly one rating present. The probability falls back to
    0.5; the UI should still show the bar shape but with reduced emphasis.
  - ``"none"`` — neither rating present. Probability is 0.5.

Algorithm (``model_version="elo-wtn-1"``)
-----------------------------------------
WTN is on a 1.0-40.0 scale where **lower is stronger**. The Elo formula
expects the opposite — higher is stronger — so we transform each WTN ``r``
into a synthetic Elo via::

    elo(r) = (40.0 - r) * 50.0

This places a top-of-scale player (WTN 1.0) at Elo 1950 and a bottom-of-scale
player (WTN 40.0) at Elo 0; the spread of 1950 Elo points across the 39-WTN
range roughly matches the spread observed in published Elo-axis ratings for
junior tennis. The 50.0 scale factor is a project constant — choosing a
larger factor stretches probability swings (a one-WTN gap becomes more
decisive); a smaller factor compresses them. 50.0 was picked as the smallest
round number that yields probability_a > 0.7 at a 12-WTN gap, which the
"Strong vs weak" unit test pins.

Win probability (logistic, classical Elo)::

    p_a = 1 / (1 + 10 ** ((elo_b - elo_a) / 400))

If either rating is missing, ``p_a`` returns ``0.5`` rather than guessing
from a default — see "no signal" handling above.

Companion function: ``expected_outcomes_along_path``
----------------------------------------------------
Given a focal player and an ordered list of opponent IDs (typically the
projected single-elimination path from
:func:`src.enrich.strength_of_draw.strength_of_draw`), returns one
``ExpectedOutcomeResult`` per opponent with the focal player as side A. Order
of the returned list matches ``projected_path_ids``. Used by the
``/draws/{id}`` UI to render a per-round probability strip alongside the
mini scouting cards.

Edge cases
----------
- ``player_a_id == player_b_id`` raises :class:`ValueError`. A self-match is
  never a meaningful scout target.
- A rating outside the documented [1.0, 40.0] WTN range (negative, > 100)
  produces a logged warning. The transform clamps the rating to ``[0.1, 40.0]``
  so the math still yields a finite, ordered probability instead of NaN.
  Clamping is intentionally permissive at the strong end: a synthetic rating
  derived from a national #1 ranking can theoretically resolve to <1.0 and
  we want it to render rather than crash.
- An unknown ``model_version`` raises :class:`ValueError` so the caller never
  silently records a meaningless derivation.

Pure function: no DB, no network, no global state.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

ConfidenceLabel = Literal["high", "medium", "low", "none"]

# Project constants for elo-wtn-1.
_ELO_SCALE_FACTOR = 50.0
_WTN_MAX = 40.0
_WTN_CLAMP_MIN = 0.1
_WTN_CLAMP_MAX = 40.0
_HIGH_CONFIDENCE_THRESHOLD = 0.7
_SUPPORTED_MODEL_VERSIONS = frozenset({"elo-wtn-1"})


class ExpectedOutcomeResult(BaseModel):
    """Win probability per side for a single match-up."""

    player_a_id: str
    player_b_id: str
    rating_a: float | None = None
    rating_b: float | None = None
    probability_a: float = Field(ge=0.0, le=1.0)
    probability_b: float = Field(ge=0.0, le=1.0)
    model_version: str
    confidence: ConfidenceLabel


def _clamp_rating(rating: float, *, player_id: str) -> float:
    """Clamp a WTN-axis rating into the supported transform window.

    Logs a warning when the input falls outside the canonical 1.0-40.0
    range; the transform is still applied so the caller never sees NaN.
    """
    if rating < _WTN_CLAMP_MIN or rating > _WTN_CLAMP_MAX:
        logger.warning(
            "rating for %s outside WTN range (%.3f); clamping to [%.1f, %.1f]",
            player_id,
            rating,
            _WTN_CLAMP_MIN,
            _WTN_CLAMP_MAX,
        )
    if rating < _WTN_CLAMP_MIN:
        return _WTN_CLAMP_MIN
    if rating > _WTN_CLAMP_MAX:
        return _WTN_CLAMP_MAX
    return rating


def _wtn_to_elo(rating: float) -> float:
    """Transform a clamped WTN rating onto the Elo axis (higher = stronger)."""
    return (_WTN_MAX - rating) * _ELO_SCALE_FACTOR


def _confidence_label(
    rating_a: float | None,
    rating_b: float | None,
    confidences: dict[str, float] | None,
    player_a_id: str,
    player_b_id: str,
) -> ConfidenceLabel:
    if rating_a is None and rating_b is None:
        return "none"
    if rating_a is None or rating_b is None:
        return "low"
    if confidences is None:
        return "high"
    ca = confidences.get(player_a_id)
    cb = confidences.get(player_b_id)
    if ca is None or cb is None:
        return "medium"
    if ca < _HIGH_CONFIDENCE_THRESHOLD or cb < _HIGH_CONFIDENCE_THRESHOLD:
        return "medium"
    return "high"


def expected_outcome(
    player_a_id: str,
    player_b_id: str,
    ratings: dict[str, float],
    model_version: str = "elo-wtn-1",
    confidences: dict[str, float] | None = None,
) -> ExpectedOutcomeResult:
    """Compute Elo-style win probability for a single A-vs-B match-up.

    See module docstring for inputs, outputs, algorithm, and edge cases.
    """
    if player_a_id == player_b_id:
        raise ValueError(f"player_a_id and player_b_id must differ (got {player_a_id!r})")
    if model_version not in _SUPPORTED_MODEL_VERSIONS:
        raise ValueError(
            f"unsupported model_version {model_version!r}; "
            f"expected one of {sorted(_SUPPORTED_MODEL_VERSIONS)}"
        )

    rating_a = ratings.get(player_a_id)
    rating_b = ratings.get(player_b_id)

    if rating_a is None or rating_b is None:
        probability_a = 0.5
    else:
        clamped_a = _clamp_rating(rating_a, player_id=player_a_id)
        clamped_b = _clamp_rating(rating_b, player_id=player_b_id)
        elo_a = _wtn_to_elo(clamped_a)
        elo_b = _wtn_to_elo(clamped_b)
        probability_a = 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))

    confidence = _confidence_label(rating_a, rating_b, confidences, player_a_id, player_b_id)

    return ExpectedOutcomeResult(
        player_a_id=player_a_id,
        player_b_id=player_b_id,
        rating_a=rating_a,
        rating_b=rating_b,
        probability_a=probability_a,
        probability_b=1.0 - probability_a,
        model_version=model_version,
        confidence=confidence,
    )


def expected_outcomes_along_path(
    focal_player_id: str,
    projected_path_ids: list[str],
    ratings: dict[str, float],
    model_version: str = "elo-wtn-1",
    confidences: dict[str, float] | None = None,
) -> list[ExpectedOutcomeResult]:
    """Run :func:`expected_outcome` once per opponent on a projected path.

    The focal player is side A in every result. Order of the returned list
    matches ``projected_path_ids``. An opponent ID equal to
    ``focal_player_id`` (which would be a degenerate self-match in the path)
    is skipped with a warning rather than raising — projected paths are a
    heuristic and the UI should still render the rest of the path.
    """
    results: list[ExpectedOutcomeResult] = []
    for opponent_id in projected_path_ids:
        if opponent_id == focal_player_id:
            logger.warning(
                "projected path contains focal player %s; skipping self-match",
                focal_player_id,
            )
            continue
        results.append(
            expected_outcome(
                focal_player_id,
                opponent_id,
                ratings,
                model_version=model_version,
                confidences=confidences,
            )
        )
    return results


__all__ = [
    "ConfidenceLabel",
    "ExpectedOutcomeResult",
    "expected_outcome",
    "expected_outcomes_along_path",
]
