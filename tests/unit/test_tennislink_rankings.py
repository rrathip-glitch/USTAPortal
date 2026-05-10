"""Unit tests for src.parse.tennislink_rankings."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.parse.tennislink_rankings import parse_ranking_list

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "tennislink"


@pytest.fixture
def ranking_list_html() -> str:
    return (FIXTURES / "ranking_list.html").read_text(encoding="utf-8")


def test_parse_ranking_list_returns_many_snapshots(ranking_list_html: str) -> None:
    """A standings list captures dozens-to-hundreds of players; the
    Georgia B14 fixture is a state list and should contain many."""

    snapshots = parse_ranking_list(ranking_list_html)
    assert len(snapshots) >= 10


def test_parse_ranking_list_extracts_position_and_points(ranking_list_html: str) -> None:
    """Rank=1 row should have position=1 and a numeric points value."""

    snapshots = parse_ranking_list(ranking_list_html)
    top = sorted((s for s in snapshots if s.position is not None), key=lambda s: s.position or 0)[0]
    assert top.position == 1
    assert top.points is not None and top.points > 0


def test_parse_ranking_list_classifies_category(ranking_list_html: str) -> None:
    """The header '*B14 2019 GA Standings (Combined)' yields category 'Boys 14 Singles'."""

    snapshots = parse_ranking_list(ranking_list_html)
    assert snapshots
    # All snapshots in one list share the same category.
    cats = {s.category for s in snapshots}
    assert cats == {"Boys 14 Singles"}


def test_parse_ranking_list_as_of_year(ranking_list_html: str) -> None:
    """The header year drives the snapshot's as_of (January 1 of that year)."""

    snapshots = parse_ranking_list(ranking_list_html)
    assert snapshots[0].as_of == date(2019, 1, 1)


def test_parse_ranking_list_scope_is_sectional(ranking_list_html: str) -> None:
    """A section-scoped list (GA -> Southern section) has scope='sectional'."""

    snapshots = parse_ranking_list(ranking_list_html)
    assert snapshots[0].scope == "sectional"
