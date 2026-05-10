"""Unit tests for src.parse.tennislink_draws."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.parse.tennislink_draws import ParseError, parse_draw

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "tennislink"


@pytest.fixture
def draw_html() -> str:
    return (FIXTURES / "draw_detail.html").read_text(encoding="utf-8")


def test_parse_draw_returns_draw_metadata(draw_html: str) -> None:
    """The draw fixture (T=211365, E=5) is Boys' 14 Singles."""

    draw, _entries, _matches = parse_draw(draw_html)
    assert draw.tournament_id == "211365"
    assert draw.usta_id == "211365:5"
    # Name surfaces from the bracket header font tag.
    assert draw.name and ("Boys" in draw.name or "14" in draw.name)


def test_parse_draw_extracts_entries(draw_html: str) -> None:
    """The Boys' 14 Singles bracket has multiple unique players."""

    _draw, entries, _matches = parse_draw(draw_html)
    # The bracket has at least 4 players (it's a tiered round-robin / SE).
    assert len(entries) >= 4
    # Every entry is associated with the draw ID.
    for e in entries:
        assert e.draw_id == "211365:5"


def test_parse_draw_finds_seeded_players(draw_html: str) -> None:
    """Seeded players carry a parenthesized seed in their span; at least
    one entry should have a non-None seed."""

    _draw, entries, _matches = parse_draw(draw_html)
    seeded = [e for e in entries if e.seed is not None]
    assert len(seeded) >= 1
    # Seeds are positive integers.
    for e in seeded:
        assert e.seed is not None and e.seed >= 1


def test_parse_draw_extracts_match_scores(draw_html: str) -> None:
    """The bracket contains semicolon-separated set scores in <div> tags."""

    _draw, _entries, matches = parse_draw(draw_html)
    assert len(matches) >= 1
    # Each match has a non-empty score_raw and at least one parsed set.
    for m in matches[:3]:
        assert m.score_raw
        assert len(m.sets) >= 1


def test_parse_draw_handles_tiebreak_scores(draw_html: str) -> None:
    """Tiebreak scores like "6-7(3); 6-3; 10-7" parse into 3 sets with one
    side carrying the tiebreak loser's point count."""

    _draw, _entries, matches = parse_draw(draw_html)
    tiebreak_matches = [m for m in matches if "(" in (m.score_raw or "")]
    if tiebreak_matches:
        m = tiebreak_matches[0]
        # At least one set must have a tiebreak value recorded.
        assert any(
            s.tiebreak_a is not None or s.tiebreak_b is not None for s in m.sets
        )


# --- edge cases --------------------------------------------------------------


def test_parse_draw_empty_html_raises_parse_error() -> None:
    with pytest.raises(ParseError):
        parse_draw("")


def test_parse_draw_wrong_page_raises_parse_error() -> None:
    bogus = "<html><body><h1>Some other page</h1></body></html>"
    with pytest.raises(ParseError):
        parse_draw(bogus)
