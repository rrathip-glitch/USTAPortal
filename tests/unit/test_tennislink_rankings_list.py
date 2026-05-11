"""Unit tests for :mod:`src.parse.tennislink_rankings_list`.

Fixture-driven: parses the recon-captured Boys' 12 Combined print HTML
(``data/recon/2026-05-11-janav-browse/tennislink-2072448.html``, 1,014
players) and asserts the parser hits the known top-3 rows and a few
sampled rows from the middle/end of the list. Empty/non-rankings HTML
is exercised separately to confirm the graceful-failure path.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.parse.tennislink_rankings_list import (
    ParseError,
    build_list_id,
    parse_tennislink_rankings_list,
)

# Resolve the recon fixture. We pin against the on-disk copy rather than
# copying it into tests/fixtures/ because the file is 1.4MB and already
# committed under data/recon/.
FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "recon"
    / "2026-05-11-janav-browse"
    / "tennislink-2072448.html"
)


@pytest.fixture(scope="module")
def b12_combined_html() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------


def test_parses_list_metadata(b12_combined_html: str) -> None:
    """The header ``*Boys 12 (Combined)`` resolves to age 12, gender M, national."""
    header, _ = parse_tennislink_rankings_list(
        b12_combined_html,
        list_id="2072448",
        fetched_at=datetime(2026, 5, 11, 12, 0, tzinfo=UTC),
    )
    assert header.id == "2072448"
    assert header.age_category == "Boys 12s"
    assert header.gender == "M"
    assert header.scope == "national"
    assert header.section is None
    assert header.source == "tennislink"
    assert header.total_players == 1014
    # The header had no year embedded — falls back to today (or, here,
    # the fetched_at-derived date for trace).
    assert isinstance(header.as_of, date)


def test_extracts_all_rows(b12_combined_html: str) -> None:
    """All 1,014 players in the captured B12 list parse cleanly."""
    _, entries = parse_tennislink_rankings_list(b12_combined_html, list_id="2072448")
    assert len(entries) == 1014


def test_top_three_match_known_urls_md(b12_combined_html: str) -> None:
    """Top-3 sanity check — Quan / Razeghi / Woestendick per known_urls.md."""
    _, entries = parse_tennislink_rankings_list(b12_combined_html, list_id="2072448")
    assert entries[0].position == 1
    assert entries[0].player_name_raw == "Quan, Rudy"
    assert entries[0].section == "No. California"
    assert entries[0].points == 19304

    assert entries[1].position == 2
    assert entries[1].player_name_raw == "Razeghi, Alexander"
    assert entries[1].section == "Texas"
    assert entries[1].points == 14563

    assert entries[2].position == 3
    assert entries[2].player_name_raw == "Woestendick, Cooper"
    assert entries[2].section == "Missouri Valley"
    assert entries[2].points == 8869


def test_sampled_rows_have_expected_section(b12_combined_html: str) -> None:
    """Spot-check a few mid-list and tail rows by name + section."""
    _, entries = parse_tennislink_rankings_list(b12_combined_html, list_id="2072448")
    by_position = {e.position: e for e in entries}

    # Position 4 — Exsted, Maxwell, MN / Northern.
    fourth = by_position[4]
    assert fourth.player_name_raw == "Exsted, Maxwell"
    assert fourth.section == "Northern"

    # Position 1014 — last row, Romito, Joseph, Eastern (per fixture tail).
    last = by_position[1014]
    assert last.player_name_raw == "Romito, Joseph"
    assert last.section == "Eastern"
    # Tail-end player typically has very low points; just sanity > 0.
    assert last.points is not None and last.points >= 1


def test_every_entry_carries_synthetic_usta_id(b12_combined_html: str) -> None:
    """Without a real USTA member id in the print view, we mint a slug."""
    _, entries = parse_tennislink_rankings_list(b12_combined_html, list_id="2072448")
    for entry in entries[:5]:
        assert entry.player_usta_id.startswith("tl-rank:")
        # Slug should embed the lowercased last_first form for traceability.
        assert "," not in entry.player_usta_id  # comma normalized away


def test_list_id_passes_through_to_entries(b12_combined_html: str) -> None:
    """``list_id`` from the caller is stamped onto every entry."""
    header, entries = parse_tennislink_rankings_list(
        b12_combined_html, list_id="custom-slug"
    )
    assert header.id == "custom-slug"
    assert all(e.list_id == "custom-slug" for e in entries)


def test_wtn_columns_are_none(b12_combined_html: str) -> None:
    """TennisLink does not expose WTN — both columns stay ``None``."""
    _, entries = parse_tennislink_rankings_list(b12_combined_html, list_id="2072448")
    assert all(e.wtn_singles is None for e in entries[:5])
    assert all(e.wtn_doubles is None for e in entries[:5])


# ---------------------------------------------------------------------------
# Slug builder
# ---------------------------------------------------------------------------


def test_build_list_id_national() -> None:
    slug = build_list_id(
        age_category="Boys 12s",
        gender="M",
        scope="national",
        section=None,
        as_of=date(2026, 5, 11),
    )
    assert slug == "u12-boys-national-2026-05-11"


def test_build_list_id_sectional() -> None:
    slug = build_list_id(
        age_category="Girls 14s",
        gender="F",
        scope="sectional",
        section="Florida",
        as_of=date(2026, 5, 11),
    )
    assert slug == "u14-girls-sectional-florida-2026-05-11"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_html_raises_parse_error() -> None:
    with pytest.raises(ParseError):
        parse_tennislink_rankings_list("")


def test_unrelated_html_raises_parse_error() -> None:
    """A page with neither ``grdMain`` nor the ``Ranking List`` marker fails."""
    with pytest.raises(ParseError):
        parse_tennislink_rankings_list(
            "<html><body><p>not a ranking page</p></body></html>"
        )


def test_ranking_list_marker_without_grid_returns_empty_entries() -> None:
    """A 'Ranking List' page with no rows yields a header + empty entries.

    TennisLink renders this shape when ``rankinglistid`` matches a
    historical id whose plane has since been retired. The parser must
    not crash — it returns a header with ``total_players=0`` and an
    empty list, so the upstream sync_runs row records the soft state.
    """
    html = """
        <html><head><title>Ranking List</title></head>
        <body>
          <table><tr><td class="FieldData">&nbsp;*Boys 14 (Combined)</td></tr></table>
        </body></html>
    """
    header, entries = parse_tennislink_rankings_list(
        html, list_id="0000000", fetched_at=datetime(2026, 5, 11, tzinfo=UTC)
    )
    assert header.id == "0000000"
    assert header.age_category == "Boys 14s"
    assert header.total_players == 0
    assert entries == []
