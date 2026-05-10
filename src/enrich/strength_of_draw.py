"""Strength-of-draw enrichment.

Inputs
------
- ``draw``: the :class:`src.models.draw.Draw` whose strength is being assessed.
  ``draw.format`` and ``draw.size`` shape the projected-path heuristic.
- ``entries``: every :class:`src.models.draw.DrawEntry` in the draw, including
  withdrawn ones. Withdrawn entries are excluded from field-size and rating
  aggregates but are still inspected when reconstructing the bracket from
  ``position``.
- ``ratings``: ``dict[player_id, float]`` mapping each player to a numeric
  rating where **lower is stronger** (mimicking the WTN scale, 1.0-40.0). The
  caller is responsible for resolving "WTN if available, sectional ranking
  otherwise" before invoking this function — this module is rating-agnostic and
  works on a single numeric axis.
- ``focal_player_id``: the player whose perspective the path metrics are
  computed from (the user). Must appear in ``entries``; otherwise
  :class:`ValueError` is raised.
- ``projected_path``: optional ordered list of opponent player IDs along the
  focal player's projected route through the bracket (round 1 first, final
  last). When ``None`` the function derives a heuristic path; see below.

Output
------
A :class:`StrengthOfDrawResult` Pydantic model. Every "rating" field uses the
same scale as ``ratings`` (lower = stronger). ``field_min_rating`` is the
strongest opponent in the field; ``field_max_rating`` is the weakest.

- ``draw_id``, ``focal_player_id`` — identifiers echoed back for caller
  convenience.
- ``field_size`` — count of entries with ``status != 'withdrawn'`` (the focal
  player counts toward field size; opponents are everyone else).
- ``average_opponent_rating`` / ``median_opponent_rating`` — mean / median of
  ratings across opponents in the field (the focal player is excluded).
  ``None`` when no opponent has a rating.
- ``field_min_rating`` — strongest opponent (smallest rating); ``None`` when
  no opponent has a rating.
- ``field_max_rating`` — weakest opponent (largest rating); ``None`` when no
  opponent has a rating.
- ``path_average_rating`` — mean rating along the projected path, ignoring
  unrated path opponents. ``None`` when the path is empty or fully unrated.
- ``hardest_path_opponent_id`` — path opponent with the smallest (strongest)
  rating; ``None`` when path is empty or fully unrated.
- ``easiest_path_opponent_id`` — path opponent with the largest (weakest)
  rating; ``None`` when path is empty or fully unrated.
- ``projected_path`` — the path actually used (echoed verbatim if supplied,
  derived if not). May contain unrated player IDs.
- ``unrated_count`` — count of in-field entries (including focal) whose
  ``player_id`` is not in ``ratings``. Missing ratings are never imputed as
  zero.

Projected-path heuristic
------------------------
When ``projected_path is None`` and ``draw.format`` is one of
``"single_elimination"`` or ``"single_elimination_with_consolation"``, the
function reconstructs the focal player's projected path from the standard
single-elimination pairing on entry ``position`` (1-indexed):

- Round 1: the entry adjacent to the focal player (positions ``2k-1`` and
  ``2k`` are paired). If no entry holds the adjacent position, the round
  contributes no opponent.
- Round 2 and onward: from each subsequent bracket "block" of the appropriate
  size on the focal player's side of the bracket, pick the entry with the
  best (lowest) rating as the projected winner. Ties on rating break by
  smaller ``position``. Unrated entries are treated as worse than any rated
  entry (i.e., a rated player is always projected to beat an unrated player).
  This is a rough scouting view, not a simulation — the assumption is
  documented here so callers know not to over-interpret the path.

For any non-single-elimination format (round_robin, compass, feed_in,
unknown), ``projected_path`` defaults to ``[]`` and the path aggregates
(``path_average_rating``, ``hardest_path_opponent_id``,
``easiest_path_opponent_id``) are ``None``. Callers wanting a round-robin
"opponent set" should pass ``projected_path`` explicitly with every other
in-field entry.

Edge cases
----------
- Withdrawn entries are excluded from ``field_size`` and from all field/path
  rating aggregates. They are also ignored when reconstructing the bracket.
- An entry whose ``player_id`` is not in ``ratings`` increments
  ``unrated_count`` and is excluded from rating aggregates; it is *not*
  treated as zero.
- A ``projected_path`` ID missing from ``ratings`` is preserved in the
  returned ``projected_path`` list but skipped from rating aggregates and from
  ``hardest_path_opponent_id`` / ``easiest_path_opponent_id`` selection.
- ``field_size == 0`` (every entry withdrawn): all aggregates are ``None``,
  ``unrated_count`` is 0, ``projected_path`` is ``[]``.
- ``focal_player_id`` not present in ``entries`` raises :class:`ValueError`.
- A focal entry with ``status == 'withdrawn'`` still counts as "present in
  entries" for the not-found check, but produces an empty derived path
  (the focal is not in the field, so there is no bracket position to walk).

Pure function: no DB, no network, no global state.
"""

from __future__ import annotations

from statistics import mean, median

from pydantic import BaseModel, Field

from src.models.draw import Draw, DrawEntry

_SINGLE_ELIM_FORMATS = frozenset(
    {"single_elimination", "single_elimination_with_consolation"}
)


class StrengthOfDrawResult(BaseModel):
    """Strength-of-draw summary for one focal player in one draw."""

    draw_id: str
    focal_player_id: str
    field_size: int = 0
    average_opponent_rating: float | None = None
    median_opponent_rating: float | None = None
    field_min_rating: float | None = None
    field_max_rating: float | None = None
    path_average_rating: float | None = None
    hardest_path_opponent_id: str | None = None
    easiest_path_opponent_id: str | None = None
    projected_path: list[str] = Field(default_factory=list)
    unrated_count: int = 0


def _is_in_field(entry: DrawEntry) -> bool:
    return entry.status != "withdrawn"


def _round_up_pow2(n: int) -> int:
    """Smallest power of two >= ``n`` (with ``n >= 1``)."""
    p = 1
    while p < n:
        p <<= 1
    return p


def _derive_path(
    draw: Draw,
    entries: list[DrawEntry],
    ratings: dict[str, float],
    focal_player_id: str,
) -> list[str]:
    """Reconstruct the focal player's projected single-elim path.

    See module docstring for the full heuristic. Returns an empty list when
    the format isn't single-elim, when the focal player has no position, or
    when the focal player has been withdrawn.
    """
    if draw.format not in _SINGLE_ELIM_FORMATS:
        return []

    in_field = [e for e in entries if _is_in_field(e)]
    by_position: dict[int, DrawEntry] = {
        e.position: e for e in in_field if e.position is not None
    }
    focal_entry = next(
        (e for e in entries if e.player_id == focal_player_id),
        None,
    )
    if focal_entry is None or focal_entry.position is None:
        return []
    if not _is_in_field(focal_entry):
        return []

    # Bracket size: prefer the declared draw.size, otherwise round up the
    # highest occupied position. We need a power of two so that the
    # "block size doubles each round" walk terminates cleanly.
    declared = draw.size if draw.size and draw.size > 0 else max(by_position)
    bracket_size = _round_up_pow2(max(declared, focal_entry.position))
    if bracket_size < 2:
        return []

    focal_pos = focal_entry.position
    path: list[str] = []
    block_size = 2
    while block_size <= bracket_size:
        # Bracket "block" containing the focal at this round: [block_lo, block_hi].
        block_index = (focal_pos - 1) // block_size
        block_lo = block_index * block_size + 1
        block_hi = block_lo + block_size - 1
        # Opponent half = the half of [block_lo, block_hi] that does not
        # contain focal_pos.
        half = block_size // 2
        mid = block_lo + half
        if focal_pos < mid:
            opp_lo, opp_hi = mid, block_hi
        else:
            opp_lo, opp_hi = block_lo, mid - 1

        candidates = [
            by_position[p] for p in range(opp_lo, opp_hi + 1) if p in by_position
        ]
        if not candidates:
            block_size <<= 1
            continue
        # Best (lowest) rating wins; unrated treated as +inf (worst); break
        # ties by smaller position.
        candidates.sort(
            key=lambda e: (
                ratings.get(e.player_id, float("inf")),
                e.position if e.position is not None else 10**9,
            )
        )
        path.append(candidates[0].player_id)
        block_size <<= 1
    return path


def strength_of_draw(
    draw: Draw,
    entries: list[DrawEntry],
    ratings: dict[str, float],
    focal_player_id: str,
    projected_path: list[str] | None = None,
) -> StrengthOfDrawResult:
    """Compute strength-of-draw metrics for one focal player.

    See module docstring for input/output semantics, edge cases, and the
    projected-path heuristic.
    """
    if not any(e.player_id == focal_player_id for e in entries):
        raise ValueError(
            f"focal_player_id {focal_player_id!r} not present in entries"
        )

    in_field = [e for e in entries if _is_in_field(e)]
    field_size = len(in_field)

    opponent_ratings = [
        ratings[e.player_id]
        for e in in_field
        if e.player_id != focal_player_id and e.player_id in ratings
    ]
    unrated_count = sum(1 for e in in_field if e.player_id not in ratings)

    avg_opp = mean(opponent_ratings) if opponent_ratings else None
    med_opp = median(opponent_ratings) if opponent_ratings else None
    field_min = min(opponent_ratings) if opponent_ratings else None
    field_max = max(opponent_ratings) if opponent_ratings else None

    if projected_path is None:
        path = _derive_path(draw, entries, ratings, focal_player_id)
    else:
        path = list(projected_path)

    rated_path = [(pid, ratings[pid]) for pid in path if pid in ratings]
    if rated_path:
        path_avg: float | None = mean(r for _, r in rated_path)
        hardest = min(rated_path, key=lambda pr: pr[1])[0]
        easiest = max(rated_path, key=lambda pr: pr[1])[0]
    else:
        path_avg = None
        hardest = None
        easiest = None

    return StrengthOfDrawResult(
        draw_id=draw.usta_id,
        focal_player_id=focal_player_id,
        field_size=field_size,
        average_opponent_rating=avg_opp,
        median_opponent_rating=med_opp,
        field_min_rating=field_min,
        field_max_rating=field_max,
        path_average_rating=path_avg,
        hardest_path_opponent_id=hardest,
        easiest_path_opponent_id=easiest,
        projected_path=path,
        unrated_count=unrated_count,
    )
