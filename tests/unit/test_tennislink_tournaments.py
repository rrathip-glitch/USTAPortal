"""Unit tests for src.parse.tennislink_tournaments.

These tests exercise the parser against real captured TennisLink fixtures
(see tests/fixtures/tennislink/). The fixtures are anonymous public pages
captured 2026-05-10.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.parse.tennislink_tournaments import (
    parse_tournament_detail,
    parse_tournament_search_results,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "tennislink"


@pytest.fixture
def search_results_html() -> str:
    return (FIXTURES / "tournament_search_results.html").read_text(encoding="utf-8")


@pytest.fixture
def detail_html() -> str:
    return (FIXTURES / "tournament_detail.html").read_text(encoding="utf-8")


def test_parse_search_results_returns_many_tournaments(search_results_html: str) -> None:
    """A search-results page should yield many tournaments — the GB16 query
    that produced the fixture returns at least a full page of results."""

    tournaments = parse_tournament_search_results(search_results_html)
    assert len(tournaments) >= 10


def test_parse_search_results_extracts_integer_usta_id(search_results_html: str) -> None:
    """TennisLink tournament IDs are integers, not GUIDs — confirm shape."""

    tournaments = parse_tournament_search_results(search_results_html)
    for t in tournaments[:5]:
        assert t.usta_id.isdigit(), f"expected numeric usta_id, got {t.usta_id!r}"


def test_parse_search_results_populates_name(search_results_html: str) -> None:
    """Every result row should yield a non-empty name."""

    tournaments = parse_tournament_search_results(search_results_html)
    for t in tournaments[:5]:
        assert t.name, f"empty name for tournament {t.usta_id}"
        # The visible USTA Tournament Number is stashed on `level` —
        # confirm at least one row has one.
    assert any(t.level for t in tournaments)


def test_parse_detail_extracts_title(detail_html: str) -> None:
    """The detail page's H1 carries the tournament name."""

    tournament, _draws = parse_tournament_detail(detail_html)
    assert "TriTennis" in tournament.name
    assert "Holiday" in tournament.name


def test_parse_detail_extracts_date_range(detail_html: str) -> None:
    """Dates render as 'December 26-28, 2018' on the detail page."""

    tournament, _draws = parse_tournament_detail(detail_html)
    assert tournament.start_date == date(2018, 12, 26)
    assert tournament.end_date == date(2018, 12, 28)


def test_parse_detail_extracts_draws(detail_html: str) -> None:
    """The events dropdown yields one Draw per option."""

    tournament, draws = parse_tournament_detail(detail_html)
    # The TriTennis Holiday Series fixture renders four singles events
    # in its ddlEvents dropdown: Boys' 12 Singles, Boys' 14 Singles,
    # Girls' 12 Singles, Girls' 14 Singles.
    assert len(draws) >= 4
    # Each draw is tied to the tournament.
    for d in draws:
        assert d.tournament_id == tournament.usta_id
    # Genders are inferred from event labels.
    genders = {d.gender for d in draws}
    assert "M" in genders and "F" in genders
