"""Common-opponents enrichment.

Finds players that both ``player_a`` and ``player_b`` have faced, and for each
such opponent reports the two head-to-head scorelines side by side along with
a signed edge score so the UI can rank the opponents by who they discriminate
between the two players.

Inputs
------
matches_a:
    All :class:`src.models.match.Match` records involving ``player_a``. The
    caller is responsible for fetching these from the repository — this module
    is pure and performs no IO. Matches that do not actually involve
    ``player_a`` are tolerated and silently skipped (defensive — a strict
    filter is the caller's job).
matches_b:
    All :class:`src.models.match.Match` records involving ``player_b``, same
    contract as ``matches_a``.
player_a_id, player_b_id:
    USTA player IDs identifying the two sides whose opponent histories are
    being compared. Need not be distinct — passing the same id is a no-op
    because every "common opponent" then trivially is one player and the
    self-match guard excludes them all; the result is an empty list.

Outputs
-------
A :class:`CommonOpponentsResult` containing:

- ``player_a_id`` / ``player_b_id`` — echoed back for the UI.
- ``common`` — one :class:`CommonOpponentEntry` per opponent both players have
  faced. Each entry carries:

  - ``opponent_id``
  - ``a_record`` — ``(wins, losses)`` of ``player_a`` against this opponent.
    A win counts when ``match.winner_id == player_a_id``; a loss when
    ``match.winner_id == opponent_id``. Matches without a recorded winner
    are ignored for win/loss tallying but still cause the opponent to appear
    as "faced" (so they can still be a common opponent — the v1 "no silent
    imputation" rule applied to common-opponent discovery).
  - ``b_record`` — same shape, from ``player_b``'s perspective.
  - ``a_minus_b_score`` — signed integer
    ``(a_wins - a_losses) - (b_wins - b_losses)``; positive means
    ``player_a`` has the edge against this opponent.

  Sorted by ``abs(a_minus_b_score)`` descending (most discriminating
  opponents first), then by ``opponent_id`` ascending (stable, deterministic
  tie-break).
- ``a_edge_count`` — number of common opponents where ``a_minus_b_score > 0``.
- ``b_edge_count`` — number where ``a_minus_b_score < 0``.
- ``even_count`` — number where ``a_minus_b_score == 0``.

Edge cases
----------
- An empty ``matches_a`` or ``matches_b`` yields an empty ``common`` list and
  all three counts equal zero.
- Self-matches (a row where the opponent id resolves to ``player_a_id`` or
  ``player_b_id`` — i.e. the two principals played each other) are excluded
  from the common-opponents intersection. They're already covered by
  :mod:`src.enrich.h2h` and would otherwise pollute the comparison.
- Matches with a ``None`` opponent id (either side of the match unset) are
  skipped: an unidentified opponent cannot be a common opponent.
- Matches with ``winner_id is None`` (walkovers / unfinished records without
  a winner) still register the opponent as "faced" — so they can still be a
  common opponent — but contribute no wins or losses to either record.
- An opponent only appearing on one side (faced by A but not by B, or vice
  versa) is dropped before the entry is built; ``common`` lists strictly
  intersected opponents.

Pure function: no DB, no network, no global state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.models.match import Match


@dataclass(frozen=True)
class CommonOpponentEntry:
    """One opponent that both ``player_a`` and ``player_b`` have faced."""

    opponent_id: str
    a_record: tuple[int, int]  # (wins, losses) of player_a vs this opponent
    b_record: tuple[int, int]  # (wins, losses) of player_b vs this opponent
    a_minus_b_score: int  # signed; positive means player_a has the edge

    def model_dump(self) -> dict[str, Any]:
        """Parity with the Pydantic enrichments — returns a plain dict."""
        return {
            "opponent_id": self.opponent_id,
            "a_record": list(self.a_record),
            "b_record": list(self.b_record),
            "a_minus_b_score": self.a_minus_b_score,
        }


@dataclass(frozen=True)
class CommonOpponentsResult:
    """Side-by-side scoreline against every opponent both players have faced."""

    player_a_id: str
    player_b_id: str
    common: list[CommonOpponentEntry] = field(default_factory=list)
    a_edge_count: int = 0
    b_edge_count: int = 0
    even_count: int = 0

    def model_dump(self) -> dict[str, Any]:
        """Parity with the Pydantic enrichments — returns a plain dict."""
        return {
            "player_a_id": self.player_a_id,
            "player_b_id": self.player_b_id,
            "common": [entry.model_dump() for entry in self.common],
            "a_edge_count": self.a_edge_count,
            "b_edge_count": self.b_edge_count,
            "even_count": self.even_count,
        }


def _opponent_id(match: Match, player_id: str) -> str | None:
    """Return the id of the other side of the match, or ``None`` if the player
    isn't on either side or the opposing side is unset.
    """
    if match.player_a_id == player_id:
        return match.player_b_id
    if match.player_b_id == player_id:
        return match.player_a_id
    return None


def _record_against(
    matches: list[Match], player_id: str, opponent_id: str
) -> tuple[int, int]:
    """Return ``(wins, losses)`` of ``player_id`` against ``opponent_id``.

    Only matches whose two sides are exactly ``{player_id, opponent_id}`` are
    considered. ``winner_id`` decides which counter increments; a match with
    no recorded winner contributes nothing.
    """
    wins = 0
    losses = 0
    for match in matches:
        sides = {match.player_a_id, match.player_b_id}
        if sides != {player_id, opponent_id}:
            continue
        if match.winner_id == player_id:
            wins += 1
        elif match.winner_id == opponent_id:
            losses += 1
        # else: no recorded winner — ignored.
    return wins, losses


def _opponents_faced(matches: list[Match], player_id: str) -> set[str]:
    """Return the set of opponent ids ``player_id`` has faced.

    A ``None`` opponent id is skipped — an unidentified opponent can't be a
    common opponent. A match with no recorded winner still registers its
    opponent here (the "faced" relation is independent of who won).
    """
    faced: set[str] = set()
    for match in matches:
        opp = _opponent_id(match, player_id)
        if opp is not None:
            faced.add(opp)
    return faced


def common_opponents(
    matches_a: list[Match],
    matches_b: list[Match],
    player_a_id: str,
    player_b_id: str,
) -> CommonOpponentsResult:
    """Compute the common-opponents comparison between two players.

    See module docstring for input/output semantics and edge-case handling.
    """
    opps_a = _opponents_faced(matches_a, player_a_id)
    opps_b = _opponents_faced(matches_b, player_b_id)

    # Intersection minus the two principals themselves. A self-match (A vs B)
    # is already covered by the h2h enrichment and would otherwise inflate
    # both sides' "common opponent" view.
    shared = (opps_a & opps_b) - {player_a_id, player_b_id}

    entries: list[CommonOpponentEntry] = []
    a_edge_count = 0
    b_edge_count = 0
    even_count = 0

    for opponent_id in shared:
        a_wins, a_losses = _record_against(matches_a, player_a_id, opponent_id)
        b_wins, b_losses = _record_against(matches_b, player_b_id, opponent_id)
        score = (a_wins - a_losses) - (b_wins - b_losses)

        entries.append(
            CommonOpponentEntry(
                opponent_id=opponent_id,
                a_record=(a_wins, a_losses),
                b_record=(b_wins, b_losses),
                a_minus_b_score=score,
            )
        )

        if score > 0:
            a_edge_count += 1
        elif score < 0:
            b_edge_count += 1
        else:
            even_count += 1

    # Sort by |edge| desc (most discriminating first), then opponent_id asc as
    # a deterministic tie-break so the UI ordering is stable across runs.
    entries.sort(key=lambda e: (-abs(e.a_minus_b_score), e.opponent_id))

    return CommonOpponentsResult(
        player_a_id=player_a_id,
        player_b_id=player_b_id,
        common=entries,
        a_edge_count=a_edge_count,
        b_edge_count=b_edge_count,
        even_count=even_count,
    )
