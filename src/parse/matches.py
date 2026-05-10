"""Match parser. Score parsing follows Jeff Sackmann's match-charting conventions.

Sets are space-separated, set scores like "6-4" or "7-6(3)" for tiebreaks (the
parenthesized number is the LOSER's tiebreak points), "RET" for retirements,
"W/O" for walkovers. The 10-point match tiebreak is encoded either as
"[10-7]" or as "1-0(7)" depending on data source. See RESEARCH.md.
"""

from __future__ import annotations

import re

from src.models.match import MatchOutcome, SetScore

WALKOVER_TOKENS = frozenset({"w/o", "wo", "walkover", "walk-over"})
DEFAULT_TOKENS = frozenset({"def", "default", "def."})
RETIRED_TOKENS = frozenset({"ret", "ret.", "retired"})
UNFINISHED_TOKENS = frozenset({"", "-", "tbd", "n/a", "na", "pending"})

# Match-tiebreak patterns: "[10-7]" or "[7-10]"
_BRACKET_TB_RE = re.compile(r"^\[(\d{1,3})-(\d{1,3})\]$")
# Standard set: "6-4" or "7-6(3)"
_SET_RE = re.compile(r"^(\d{1,2})-(\d{1,2})(?:\((\d{1,3})\))?$")


def parse_score(score: str) -> tuple[list[SetScore], MatchOutcome, str | None]:
    """Parse a USTA score string into (sets, outcome, residual).

    Returns the parsed sets, the match outcome, and any residual text we did
    not understand (or None when the entire input was consumed).
    """
    normalized = score.strip().lower() if score else ""
    if normalized in UNFINISHED_TOKENS:
        return [], "unfinished", None
    if normalized in WALKOVER_TOKENS:
        return [], "walkover", None
    if normalized in DEFAULT_TOKENS:
        return [], "default", None

    tokens = score.strip().split()
    if not tokens:
        return [], "unfinished", None

    outcome: MatchOutcome = "completed"
    residual_tokens: list[str] = []
    sets: list[SetScore] = []

    # Detect a trailing retirement marker.
    if tokens[-1].lower().rstrip(".") in {"ret", "retired"}:
        outcome = "retired"
        tokens = tokens[:-1]

    for token in tokens:
        parsed = _parse_set_token(token)
        if parsed is None:
            residual_tokens.append(token)
            continue
        sets.append(parsed)

    if not sets and outcome == "completed":
        outcome = "unfinished"

    residual = " ".join(residual_tokens) if residual_tokens else None
    return sets, outcome, residual


def _parse_set_token(token: str) -> SetScore | None:
    """Parse a single set token; return None if it's not a recognised shape."""
    bracket_match = _BRACKET_TB_RE.match(token)
    if bracket_match:
        a = int(bracket_match.group(1))
        b = int(bracket_match.group(2))
        # Bracketed tiebreak: encode as a 1-0 / 0-1 pseudo-set with the actual
        # tiebreak points carried in tiebreak_a/tiebreak_b. Loser's points are
        # the smaller of (a, b).
        if a > b:
            return SetScore(games_a=1, games_b=0, tiebreak_a=a, tiebreak_b=b)
        return SetScore(games_a=0, games_b=1, tiebreak_a=a, tiebreak_b=b)

    set_match = _SET_RE.match(token)
    if not set_match:
        return None

    games_a = int(set_match.group(1))
    games_b = int(set_match.group(2))
    tb_loser = set_match.group(3)

    # Match tiebreak shape "1-0(7)" / "0-1(7)" — tb_loser is the loser's points.
    if tb_loser is not None and {games_a, games_b} == {0, 1}:
        loser_pts = int(tb_loser)
        winner_pts = max(loser_pts + 2, 10)
        if games_a == 1:
            return SetScore(games_a=1, games_b=0, tiebreak_a=winner_pts, tiebreak_b=loser_pts)
        return SetScore(games_a=0, games_b=1, tiebreak_a=loser_pts, tiebreak_b=winner_pts)

    if tb_loser is not None:
        loser_pts = int(tb_loser)
        winner_pts = max(loser_pts + 2, 7)
        if games_a > games_b:
            return SetScore(games_a=games_a, games_b=games_b, tiebreak_a=winner_pts, tiebreak_b=loser_pts)
        return SetScore(games_a=games_a, games_b=games_b, tiebreak_a=loser_pts, tiebreak_b=winner_pts)

    return SetScore(games_a=games_a, games_b=games_b)


def format_score(sets: list[SetScore], outcome: MatchOutcome) -> str:
    """Render sets+outcome back into a canonical USTA-style score string."""
    if outcome == "walkover":
        return "W/O"
    if outcome == "default":
        return "DEF"
    if outcome == "unfinished" and not sets:
        return ""

    parts = [_format_set(s) for s in sets]
    if outcome == "retired":
        parts.append("RET")
    return " ".join(parts)


def _format_set(s: SetScore) -> str:
    """Render a single SetScore back to its canonical string form."""
    # Match-tiebreak pseudo-set: encoded as 1-0 or 0-1 with both tiebreaks set.
    if {s.games_a, s.games_b} == {0, 1} and s.tiebreak_a is not None and s.tiebreak_b is not None:
        return f"[{s.tiebreak_a}-{s.tiebreak_b}]"

    if s.tiebreak_a is not None and s.tiebreak_b is not None:
        loser = min(s.tiebreak_a, s.tiebreak_b)
        return f"{s.games_a}-{s.games_b}({loser})"

    return f"{s.games_a}-{s.games_b}"


def infer_winner(
    sets: list[SetScore],
    player_a_id: str | None,
    player_b_id: str | None,
    outcome: MatchOutcome,
) -> str | None:
    """Return the winning player's ID, or None if it can't be inferred."""
    if outcome in {"walkover", "default"}:
        # Walkover/default winner cannot be inferred from sets alone.
        return None
    if outcome in {"unfinished", "unknown"}:
        return None
    if not sets:
        return None

    sets_a = sum(1 for s in sets if s.games_a > s.games_b)
    sets_b = sum(1 for s in sets if s.games_b > s.games_a)
    if sets_a == sets_b:
        return None
    if sets_a > sets_b:
        return player_a_id
    return player_b_id


def parse_match(_raw: object) -> object:
    raise NotImplementedError("Pending recon and ADR-001.")
