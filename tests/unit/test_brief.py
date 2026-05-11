"""Unit tests for the scouting-brief helpers in :mod:`src.reports.brief`."""

from __future__ import annotations

from datetime import date

from src.models.match import Match
from src.models.player import Player
from src.models.tournament import Tournament
from src.reports.brief import (
    ScoutingBrief,
    build_scouting_brief,
    h2h_summary_text,
)


def _match(
    winner_id: str | None,
    *,
    a: str = "USER",
    b: str = "OPP",
    draw_id: str = "D1",
) -> Match:
    """Build a minimal Match record for h2h-summary testing.

    All non-relevant fields are left at their model defaults — only the
    participants and the winner are pinned for these assertions.
    """
    return Match(
        draw_id=draw_id,
        player_a_id=a,
        player_b_id=b,
        winner_id=winner_id,
    )


def test_h2h_summary_no_matches() -> None:
    assert h2h_summary_text("USER", []) == "no prior meetings"


def test_h2h_summary_two_wins_for_user() -> None:
    matches = [_match("USER"), _match("USER")]
    assert h2h_summary_text("USER", matches) == "2-0 in your favor"


def test_h2h_summary_two_losses() -> None:
    matches = [_match("OPP"), _match("OPP")]
    assert h2h_summary_text("USER", matches) == "0-2 against"


def test_h2h_summary_one_one_split() -> None:
    matches = [_match("USER"), _match("OPP")]
    assert h2h_summary_text("USER", matches) == "1-1 split"


def test_build_scouting_brief_minimal_args_returns_populated_dataclass() -> None:
    user = Player(usta_id="USER", full_name="Janav Doe")
    opponent = Player(usta_id="OPP", full_name="Sam Smith")
    tournament = Tournament(
        usta_id="T1",
        name="Spring Open",
        start_date=date(2026, 5, 1),
        location_city="Orlando",
        location_state="FL",
    )

    brief = build_scouting_brief(
        user,
        opponent,
        tournament=tournament,
        draw=None,
        h2h_matches=[],
        opponent_recent=[],
        opponent_wtn=None,
    )

    assert isinstance(brief, ScoutingBrief)
    assert brief.user.usta_id == "USER"
    assert brief.opponent.usta_id == "OPP"
    assert brief.tournament is tournament
    assert brief.draw is None
    assert brief.h2h_summary == "no prior meetings"
    assert brief.h2h_matches == []
    assert brief.opponent_recent == []
    assert brief.opponent_wtn is None
    assert brief.common_opponents == []
    assert brief.pre_match_notes is None
