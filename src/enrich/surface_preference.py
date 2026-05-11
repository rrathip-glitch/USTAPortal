"""Surface-preference enrichment.

Computes a player's wins, losses, and win-rate broken down by court surface.
The output exposes the per-surface roll-up plus a "best" / "worst" surface
selection that gates on a minimum sample size so the recommendation isn't
just noise.

Inputs
------
matches:
    A list of :class:`src.models.match.Match` records. Order does not matter.
    The function does not perform IO. Matches that don't involve the player
    are filtered out; matches that involve the player but have no recorded
    ``winner_id`` (walkover or unfinished records without a winner) are
    ignored — they would skew the win-rate either way without being a
    completed result.
player_id:
    The USTA ID of the player whose surface profile is being computed. The
    function treats ``player_a_id`` and ``player_b_id`` symmetrically.
surface_lookup:
    Optional callable ``Match -> Surface``. When supplied, the caller takes
    full responsibility for resolving a match to a surface (typically by
    joining through the parent draw to its tournament's ``surface`` field).
    When ``None``, the function falls back to ``match.court`` and maps the
    lower-cased string per the table below; anything else resolves to
    ``"unknown"``.

    Default ``court`` → ``Surface`` mapping:

    - ``"hard"`` → ``"hard"``
    - ``"clay"`` → ``"clay"``
    - ``"grass"`` → ``"grass"``
    - ``"indoor"`` → ``"indoor_hard"``
    - anything else (including ``None`` / blank) → ``"unknown"``

Outputs
-------
A :class:`SurfacePreferenceResult` with:

- ``player_id`` — echoed back for the UI.
- ``by_surface`` — ``dict[Surface, SurfaceStat]`` with one entry per surface
  the player has at least one decided match on. The ``"unknown"`` surface is
  always excluded from this map: a surface we couldn't identify is not a
  useful coaching signal. Each :class:`SurfaceStat` carries ``matches``,
  ``wins``, ``losses``, and ``win_rate`` (in ``[0.0, 1.0]``, rounded to
  three decimals; ``0.0`` when ``matches == 0``, though that branch is
  unreachable because empty buckets are pruned).
- ``best_surface`` / ``worst_surface`` — the ``Surface`` key in
  ``by_surface`` with the highest / lowest ``win_rate``, **gated on
  ``matches >= 3``**. Below that gate the player simply hasn't played
  enough to justify a recommendation. Ties on win-rate are broken by the
  largest match count (more data wins); if every surface fails the gate,
  both fields are ``None``.
- ``total_matches`` — total decided matches involving the player
  *including* matches mapped to ``"unknown"`` surface. This is the headline
  sample size; ``"unknown"`` rows are excluded from ``by_surface`` but
  still counted here so the caller can see how much of their history was
  un-attributable.

Edge cases
----------
- ``winner_id is None``: ignored entirely (not counted in ``total_matches``
  either — a record with no winner is not a result).
- ``"unknown"`` surface: counted in ``total_matches`` but excluded from
  ``by_surface``, ``best_surface``, and ``worst_surface``.
- Best/worst gate: a surface with a perfect 1.000 win rate over a single
  match never wins the ``best_surface`` slot — the gate (>= 3 matches)
  exists precisely to suppress that kind of phantom recommendation.
- Tie-break: when two surfaces share the same maximum (or minimum) win
  rate, the surface with the larger ``matches`` count wins; if that is
  still tied, the existing dict ordering is preserved (insertion order,
  which is the order surfaces were first encountered in the input list).

Pure function: no DB, no network, no global state.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from src.models.match import Match
from src.models.tournament import Surface

# Surfaces we *could* report but won't recommend on. ``"unknown"`` is always
# excluded from ``by_surface``; the constant exists to make the intent
# explicit at the filter sites below.
_EXCLUDED_FROM_BY_SURFACE: frozenset[Surface] = frozenset({"unknown"})

# Sample-size gate for best_surface / worst_surface — fewer than this many
# matches on a surface and we refuse to make a recommendation.
_MIN_MATCHES_FOR_RECOMMENDATION = 3

# Default mapping from a free-text ``Match.court`` value to a canonical
# Surface. Anything not listed falls through to ``"unknown"``.
_DEFAULT_COURT_TO_SURFACE: dict[str, Surface] = {
    "hard": "hard",
    "clay": "clay",
    "grass": "grass",
    "indoor": "indoor_hard",
}


@dataclass(frozen=True)
class SurfaceStat:
    """One row of the per-surface roll-up."""

    matches: int
    wins: int
    losses: int
    win_rate: float

    def model_dump(self) -> dict[str, Any]:
        """Parity with the Pydantic enrichments — returns a plain dict."""
        return asdict(self)


@dataclass(frozen=True)
class SurfacePreferenceResult:
    """A player's win-rate broken down by court surface."""

    player_id: str
    by_surface: dict[Surface, SurfaceStat] = field(default_factory=dict)
    best_surface: Surface | None = None
    worst_surface: Surface | None = None
    total_matches: int = 0

    def model_dump(self) -> dict[str, Any]:
        """Parity with the Pydantic enrichments — returns a plain dict.

        ``by_surface`` is unwound into nested dicts so callers can
        round-trip the result through JSON without custom encoders.
        """
        return {
            "player_id": self.player_id,
            "by_surface": {k: v.model_dump() for k, v in self.by_surface.items()},
            "best_surface": self.best_surface,
            "worst_surface": self.worst_surface,
            "total_matches": self.total_matches,
        }


def _default_surface_lookup(match: Match) -> Surface:
    """Resolve ``match.court`` to a canonical :data:`Surface` literal."""
    court = match.court
    if court is None:
        return "unknown"
    key = court.strip().lower()
    return _DEFAULT_COURT_TO_SURFACE.get(key, "unknown")


def _involves(match: Match, player_id: str) -> bool:
    return match.player_a_id == player_id or match.player_b_id == player_id


def _round3(value: float) -> float:
    """Round to three decimals. Centralised so the gate-comparison and the
    stored ``win_rate`` use the same numeric resolution."""
    return round(value, 3)


def surface_preference(
    matches: list[Match],
    player_id: str,
    *,
    surface_lookup: Callable[[Match], Surface] | None = None,
) -> SurfacePreferenceResult:
    """Compute the per-surface win-rate breakdown for ``player_id``.

    See module docstring for the full contract.
    """
    lookup: Callable[[Match], Surface] = (
        surface_lookup if surface_lookup is not None else _default_surface_lookup
    )

    # Step 1: only matches involving the player AND with a recorded winner.
    # A walkover/unfinished row with ``winner_id is None`` is not a result
    # and contributes to neither ``total_matches`` nor any bucket.
    decided: list[tuple[Match, Surface]] = []
    for match in matches:
        if not _involves(match, player_id):
            continue
        if match.winner_id is None:
            continue
        decided.append((match, lookup(match)))

    total_matches = len(decided)

    # Step 2: accumulate per-surface (wins, losses) for surfaces other than
    # ``"unknown"`` — those count toward ``total_matches`` but never appear
    # in ``by_surface``.
    tally: dict[Surface, tuple[int, int]] = {}
    for match, surface in decided:
        if surface in _EXCLUDED_FROM_BY_SURFACE:
            continue
        wins, losses = tally.get(surface, (0, 0))
        if match.winner_id == player_id:
            wins += 1
        else:
            losses += 1
        tally[surface] = (wins, losses)

    # Step 3: realise the per-surface stats with rounded win-rates.
    by_surface: dict[Surface, SurfaceStat] = {}
    for surface, (wins, losses) in tally.items():
        n = wins + losses
        win_rate = _round3(wins / n) if n > 0 else 0.0
        by_surface[surface] = SurfaceStat(
            matches=n, wins=wins, losses=losses, win_rate=win_rate
        )

    # Step 4: pick best/worst from surfaces past the sample-size gate.
    eligible: list[tuple[Surface, SurfaceStat]] = [
        (s, stat)
        for s, stat in by_surface.items()
        if stat.matches >= _MIN_MATCHES_FOR_RECOMMENDATION
    ]
    best_surface: Surface | None = None
    worst_surface: Surface | None = None
    if eligible:
        # ``best_surface`` ties break on *more* matches (more data wins).
        # ``worst_surface`` is the literal mirror: ties break on *fewer*
        # matches (a small-sample loss record is more damning than a tied
        # rate stretched over a larger denominator). Dict insertion order
        # remains the final fall-through because ``max`` / ``min`` are stable.
        best_surface = max(
            eligible, key=lambda pair: (pair[1].win_rate, pair[1].matches)
        )[0]
        worst_surface = min(
            eligible, key=lambda pair: (pair[1].win_rate, pair[1].matches)
        )[0]

    return SurfacePreferenceResult(
        player_id=player_id,
        by_surface=by_surface,
        best_surface=best_surface,
        worst_surface=worst_surface,
        total_matches=total_matches,
    )


__all__ = [
    "SurfacePreferenceResult",
    "SurfaceStat",
    "surface_preference",
]
