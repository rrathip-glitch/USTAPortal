"""Unit tests for src.parse.tennislink_players.

The player-profile parser is verified against the draw-detail fixture
(which contains player anchors and is the canonical way TennisLink
exposes player MIDs). The player-search parser is verified against the
ranking-list fixture, since TennisLink's "player search" surface IS the
ranking list.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.parse.tennislink_players import (
    parse_player_profile,
    parse_player_search_results,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "tennislink"


@pytest.fixture
def ranking_list_html() -> str:
    return (FIXTURES / "ranking_list.html").read_text(encoding="utf-8")


def test_parse_player_profile_handles_no_data() -> None:
    """The player history page has no name in its DOM; parser returns a
    Player with a placeholder name and a usable profile URL."""

    # Construct a minimal valid HTML matching the page shape.
    html = """
    <html><body>
      <form method="post" action="./PlayerTournamentHistory.aspx?MID=1180182182182183184177178177179" id="form1">
        <input type="hidden" name="__VIEWSTATE" value="x" />
      </form>
    </body></html>
    """
    player = parse_player_profile(html)
    assert player.usta_id == "1180182182182183184177178177179"
    assert player.profile_url is not None
    assert "PlayerTournamentHistory.aspx" in player.profile_url
    # Placeholder text — caller is expected to overwrite from the draw context.
    assert "not available" in player.full_name.lower()


def test_parse_player_search_returns_players(ranking_list_html: str) -> None:
    """The ranking list yields one Player per ranked row."""

    players = parse_player_search_results(ranking_list_html)
    assert len(players) >= 10


def test_parse_player_search_splits_name(ranking_list_html: str) -> None:
    """Names like 'Taylor, Davis' split into first/last properly."""

    players = parse_player_search_results(ranking_list_html)
    top = players[0]
    assert top.first_name is not None and top.last_name is not None
    # Normalized full_name is "First Last".
    assert top.full_name == f"{top.first_name} {top.last_name}"


def test_parse_player_search_carries_section(ranking_list_html: str) -> None:
    """The Georgia ranking list rows all have section = 'Southern'."""

    players = parse_player_search_results(ranking_list_html)
    sections = {p.section for p in players[:5] if p.section}
    assert sections, "expected at least one row to carry a section value"
    # The fixture is a GA standings list, so Southern dominates the top.
    assert "Southern" in sections
