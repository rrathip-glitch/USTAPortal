"""Recent-form enrichment.

Computes a player's last-N match window: wins, losses, win-rate, the recent
results in reverse-chronological order, and the current win/loss streak.

Inputs
------
matches:
    A list of `Match` records. Order does not matter; the function will sort
    descending by `scheduled_at` (matches without a scheduled timestamp sort
    last). The function does not perform IO and does not consult the database
    or the network — pass whatever subset of matches the caller wants
    considered (typically every match a player has appeared in).
player_id:
    The USTA ID of the player whose form is being computed. The function
    treats `player_a_id` and `player_b_id` symmetrically: a match counts so
    long as either side equals `player_id`.
window:
    The maximum number of matches with a determined outcome to include in the
    window. Defaults to 8 (matching the spec's opponent scouting card). Must
    be > 0; a non-positive window raises `ValueError`.

Outputs
-------
A `FormResult` containing:

- `player_id`, `window_size` (the requested cap), `matches_considered`
  (how many actually contributed; may be < `window` if the player has
  fewer eligible matches).
- `wins`, `losses`, `win_rate` (0.0 if no determined wins or losses).
- `recent_results`: the windowed matches as `ResultEntry` rows, most recent
  first.
- `current_streak`: a (kind, length) tuple where kind is `"W"`, `"L"`, or
  `"none"`. The streak is the leading run of like-kind known results;
  `"unknown"` rows are skipped when scanning but a row of the opposite kind
  ends the streak.

Edge cases
----------
- Matches with `outcome` in {"unfinished", "unknown"} are dropped before the
  windowing step; they neither populate `recent_results` nor count toward
  `wins`/`losses`. (This is the v1 "no silent imputation" rule applied to
  form: an unscheduled or in-progress match is not a result.)
- Walkovers and defaults are included as long as `winner_id` is set; the
  side with `winner_id == player_id` records a win, the other side records
  a loss. A walkover/default with `winner_id is None` is treated as
  "unknown" — included in the window but does not contribute to wins,
  losses, win-rate, or the streak.
- Empty input or all-unknown outcomes produce a zeroed result with
  streak `("none", 0)`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.models.match import Match

ResultKind = Literal["W", "L", "unknown"]
StreakKind = Literal["W", "L", "none"]

_NON_RESULT_OUTCOMES: frozenset[str] = frozenset({"unfinished", "unknown"})


class ResultEntry(BaseModel):
    """One row of a player's recent-form window."""

    match_id: str | None = None
    opponent_id: str | None = None
    result: ResultKind = "unknown"
    score_raw: str | None = None
    scheduled_at: datetime | None = None


class FormResult(BaseModel):
    """A player's recent-form summary over the last `window_size` matches."""

    player_id: str
    window_size: int
    matches_considered: int
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    recent_results: list[ResultEntry] = Field(default_factory=list)
    current_streak: tuple[StreakKind, int] = ("none", 0)


def _classify(match: Match, player_id: str) -> tuple[ResultKind, str | None]:
    """Return (result, opponent_id) for a single match from `player_id`'s POV."""
    if match.player_a_id == player_id:
        opponent_id = match.player_b_id
    elif match.player_b_id == player_id:
        opponent_id = match.player_a_id
    else:
        # Should not happen — caller filters first — but stay defensive.
        return "unknown", None

    if match.winner_id is None:
        return "unknown", opponent_id
    if match.winner_id == player_id:
        return "W", opponent_id
    return "L", opponent_id


def _streak(results: list[ResultKind]) -> tuple[StreakKind, int]:
    """Compute the leading run of like-kind known results.

    `unknown` rows are skipped when scanning, but a row of the opposite kind
    ends the streak. If no known result exists, returns ("none", 0).
    """
    leader: StreakKind = "none"
    length = 0
    for kind in results:
        if kind == "unknown":
            continue
        if leader == "none":
            leader = kind
            length = 1
            continue
        if kind == leader:
            length += 1
        else:
            break
    return leader, length


def recent_form(
    matches: list[Match],
    player_id: str,
    window: int = 8,
) -> FormResult:
    """Compute the recent-form window for `player_id`.

    See module docstring for the full contract.
    """
    if window <= 0:
        raise ValueError(f"window must be > 0, got {window}")

    # Step 1: only matches involving the player.
    involving = [
        m for m in matches if m.player_a_id == player_id or m.player_b_id == player_id
    ]

    # Step 2: drop matches whose outcome is itself unfinished/unknown.
    eligible = [m for m in involving if m.outcome not in _NON_RESULT_OUTCOMES]

    # Step 3: sort descending by scheduled_at, with None going last.
    #     Python's sort is stable; using a (has_time, time) key puts Nones last
    #     under reverse=True without comparing None against datetime.
    eligible.sort(
        key=lambda m: (
            m.scheduled_at is not None,
            m.scheduled_at if m.scheduled_at is not None else datetime.min,
        ),
        reverse=True,
    )

    # Step 4: cap at the requested window size.
    windowed = eligible[:window]

    # Step 5: classify each row and tally.
    entries: list[ResultEntry] = []
    wins = 0
    losses = 0
    for m in windowed:
        result, opponent_id = _classify(m, player_id)
        if result == "W":
            wins += 1
        elif result == "L":
            losses += 1
        entries.append(
            ResultEntry(
                match_id=m.usta_id,
                opponent_id=opponent_id,
                result=result,
                score_raw=m.score_raw,
                scheduled_at=m.scheduled_at,
            )
        )

    decided = wins + losses
    win_rate = (wins / decided) if decided > 0 else 0.0

    streak = _streak([e.result for e in entries])

    return FormResult(
        player_id=player_id,
        window_size=window,
        matches_considered=len(windowed),
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        recent_results=entries,
        current_streak=streak,
    )
