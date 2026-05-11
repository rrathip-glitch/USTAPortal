"""Single-page "scouting brief" generator.

The brief is a pure-data dataclass plus a small text helper that the Jinja
template ``brief.html`` consumes. It is intentionally a server-rendered
HTML page (not a PDF) — the print stylesheet on the template carries the
single-page Letter-portrait layout, so a user can hit Cmd-P / Ctrl-P and
save a PDF without us needing a binary PDF dependency.

This module is pure: no IO, no global state, no template rendering. The
caller (a route handler) is responsible for fetching the inputs from the
repository, computing head-to-head match lists via :mod:`src.enrich.h2h`,
and surfacing the result via Jinja.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.models.draw import Draw
from src.models.match import Match
from src.models.player import Player
from src.models.tournament import Tournament
from src.models.wtn import WTNSnapshot


@dataclass(frozen=True)
class ScoutingBrief:
    """Pre-computed view-model for the ``brief.html`` template.

    All fields are populated by :func:`build_scouting_brief`. The template
    does not perform any computation beyond pure rendering — every label,
    record, and summary text is precomputed here so the page is trivially
    testable end-to-end.
    """

    user: Player
    opponent: Player
    tournament: Tournament | None
    draw: Draw | None
    h2h_summary: str
    h2h_matches: list[Match]
    opponent_recent: list[Match]
    opponent_wtn: WTNSnapshot | None
    common_opponents: list[tuple[Player, str, str]] = field(default_factory=list)
    pre_match_notes: str | None = None


def h2h_summary_text(user_id: str, h2h_matches: list[Match]) -> str:
    """Render a one-line head-to-head summary from ``user_id``'s perspective.

    Examples
    --------
    * No matches → ``"no prior meetings"``.
    * User has won every recorded match → ``"N-0 in your favor"``.
    * User has lost every recorded match → ``"0-N against"``.
    * Mixed → ``"W-L in your favor"`` if ``W > L``,
      ``"W-L against"`` if ``L > W``, ``"W-L split"`` if equal.

    Matches without a winner (walkover with no ``winner_id``, unfinished,
    etc.) do not contribute to either tally but still count toward the
    "prior meetings" criterion — we use the length of the list to decide
    whether to fall back to the "no prior meetings" phrasing.
    """
    if not h2h_matches:
        return "no prior meetings"

    wins = 0
    losses = 0
    for match in h2h_matches:
        if match.winner_id == user_id:
            wins += 1
        elif match.winner_id is not None and match.winner_id in (
            match.player_a_id,
            match.player_b_id,
        ):
            # Winner was the other side.
            losses += 1
        # else: no winner — does not contribute.

    if wins == 0 and losses == 0:
        # We have matches but no decided winners: still surface the count
        # so the brief doesn't claim "no prior meetings" when there were.
        return f"{wins}-{losses} split"
    if wins > losses:
        return f"{wins}-{losses} in your favor"
    if losses > wins:
        return f"{wins}-{losses} against"
    return f"{wins}-{losses} split"


def build_scouting_brief(
    user: Player,
    opponent: Player,
    *,
    tournament: Tournament | None,
    draw: Draw | None,
    h2h_matches: list[Match],
    opponent_recent: list[Match],
    opponent_wtn: WTNSnapshot | None,
    common_opponents: list[tuple[Player, str, str]] = (),  # type: ignore[assignment]
    pre_match_notes: str | None = None,
) -> ScoutingBrief:
    """Assemble a :class:`ScoutingBrief` from the supplied inputs.

    The function is a thin orchestrator: it precomputes the
    head-to-head summary text and packages every argument into the
    frozen dataclass. All filtering / sorting / record arithmetic
    happens upstream (typically in the route handler that pulls the
    underlying objects from the repository layer).
    """
    summary = h2h_summary_text(user.usta_id, h2h_matches)
    return ScoutingBrief(
        user=user,
        opponent=opponent,
        tournament=tournament,
        draw=draw,
        h2h_summary=summary,
        h2h_matches=list(h2h_matches),
        opponent_recent=list(opponent_recent),
        opponent_wtn=opponent_wtn,
        common_opponents=list(common_opponents),
        pre_match_notes=pre_match_notes,
    )


__all__ = ["ScoutingBrief", "build_scouting_brief", "h2h_summary_text"]
