"""Head-to-head enrichment.

Inputs
------
- ``matches``: a list of :class:`src.models.match.Match` objects. The caller is
  responsible for fetching these from the repository (this module is pure and
  performs no IO). The list may contain matches that do not involve either
  player; they are filtered out.
- ``player_a_id`` / ``player_b_id``: USTA player IDs identifying the two sides
  of the head-to-head. Must be distinct (a self-vs-self h2h is meaningless and
  raises :class:`ValueError`).

Output
------
A :class:`H2HResult` Pydantic model summarising the rivalry from player A's
perspective:

- ``total_matches`` — count of matches between the two players (including
  walkovers, defaults, and unfinished matches that mention both players).
- ``wins_a`` / ``wins_b`` — completed-or-awarded wins per side. A match
  contributes to a side's win count iff ``winner_id`` is set to that side.
- ``last_match`` — the chronologically most recent ``Match`` object (by
  ``scheduled_at``); ``None`` if no matches.
- ``last_match_winner_id`` — convenience accessor for ``last_match.winner_id``.
- ``match_list`` — every qualifying match, sorted descending by
  ``scheduled_at``. Matches with ``scheduled_at is None`` sort to the end of
  the list (most recent known dates first).
- ``streak_holder_id`` / ``streak_length`` — the current win streak: walking
  the match list from most recent backwards, count consecutive matches won by
  the same player. A match without a ``winner_id`` (e.g., an unfinished match
  or a walkover with no winner recorded) breaks the streak. If the most recent
  decided match has no clear winner, both fields are ``None`` / ``0``.

Edge cases
----------
- Walkover / default with ``winner_id`` set: counts toward ``total_matches``
  and the winner's tally; included in ``match_list`` and streak calculation.
- Walkover / default with ``winner_id`` unset: counts toward ``total_matches``
  and ``match_list`` but not toward win counts; in streak terms it is treated
  as "no winner" and breaks any prior streak.
- Outcome ``unfinished`` / ``unknown``: same as walkover-without-winner —
  included in totals and ``match_list`` but contributes no wins and breaks
  streaks.
- Either-side ordering: matches recorded as A vs B and as B vs A are both
  included (the underlying ``Match`` model documents that order is
  USTA-reported draw order, not winner-first).
- ``player_a_id == player_b_id`` raises :class:`ValueError`.
- No qualifying matches: returns an ``H2HResult`` with zeros and ``None``
  fields, never an exception.

Pure function: no DB, no network, no global state. The orchestrator is
expected to fetch the candidate match set and pass it in.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.models.match import Match


class H2HResult(BaseModel):
    """Summary of a head-to-head rivalry between two players, A's perspective."""

    player_a_id: str
    player_b_id: str
    total_matches: int = 0
    wins_a: int = 0
    wins_b: int = 0
    last_match: Match | None = None
    last_match_winner_id: str | None = None
    match_list: list[Match] = Field(default_factory=list)
    streak_holder_id: str | None = None
    streak_length: int = 0


def _involves_both(match: Match, a: str, b: str) -> bool:
    sides = {match.player_a_id, match.player_b_id}
    return a in sides and b in sides


def _sort_key(match: Match) -> tuple[int, datetime]:
    """Sort descending by ``scheduled_at``; ``None`` sorts to the end.

    Returns a tuple ``(0/1, datetime)`` where the first element forces
    ``None``-dated matches to the bottom regardless of the datetime sentinel.
    The tuple is consumed by ``sorted(..., reverse=True)``, so within the
    "has-date" group, larger datetimes come first.
    """
    if match.scheduled_at is None:
        # ``reverse=True`` flips the primary key: 0 must be > 1, so None entries
        # (which we want last) get the smaller primary value.
        return (0, datetime.min)
    return (1, match.scheduled_at)


def head_to_head(
    matches: list[Match], player_a_id: str, player_b_id: str
) -> H2HResult:
    """Compute the head-to-head summary for two players from a candidate match set.

    See module docstring for input/output semantics and edge-case handling.
    """
    if player_a_id == player_b_id:
        raise ValueError("player_a_id and player_b_id must be distinct")

    qualifying = [m for m in matches if _involves_both(m, player_a_id, player_b_id)]
    qualifying.sort(key=_sort_key, reverse=True)

    wins_a = 0
    wins_b = 0
    for match in qualifying:
        if match.winner_id == player_a_id:
            wins_a += 1
        elif match.winner_id == player_b_id:
            wins_b += 1
        # else: no winner recorded — does not contribute.

    last_match = qualifying[0] if qualifying else None
    last_match_winner_id = last_match.winner_id if last_match is not None else None

    streak_holder_id: str | None = None
    streak_length = 0
    for match in qualifying:
        winner = match.winner_id
        if winner not in (player_a_id, player_b_id):
            break
        if streak_holder_id is None:
            streak_holder_id = winner
            streak_length = 1
        elif winner == streak_holder_id:
            streak_length += 1
        else:
            break

    return H2HResult(
        player_a_id=player_a_id,
        player_b_id=player_b_id,
        total_matches=len(qualifying),
        wins_a=wins_a,
        wins_b=wins_b,
        last_match=last_match,
        last_match_winner_id=last_match_winner_id,
        match_list=qualifying,
        streak_holder_id=streak_holder_id,
        streak_length=streak_length,
    )
