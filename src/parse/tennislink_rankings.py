"""HTML parser for a TennisLink ranking list (RankingListsPrint.aspx).

The "print" view is the cleanest TennisLink endpoint: a single
``<table id="grdMain">`` with one row per ranked player, identified by
labelled ``<span>``s. The page also carries the list's identifying
header text (e.g. ``"*B14 2019 GA Standings (Combined)"``) which we
parse into the snapshot's ``category`` and ``as_of`` fields.
"""

from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup, Tag

from src.models.ranking import RankingSnapshot
from src.parse.players import ParseError

__all__ = ["ParseError", "parse_ranking_list"]

# Header text shape: "*B14 2019 GA Standings (Combined)"
# Where:
#   - leading "*" marks an unofficial/working list (informational only),
#   - "B14" / "G18" etc. is the division shorthand,
#   - "2019" is the snapshot year,
#   - "GA" is the section abbreviation,
#   - the trailing parenthesis names the list type.
HEADER_RE = re.compile(
    r"\*?\s*(?P<div>[BG]\d{1,2})\s+(?P<year>\d{4})\s+(?P<section>[A-Z]{2,})\s+(?P<list_type>[^()]+?)\s*(?:\((?P<note>[^)]+)\))?\s*$"
)

DIVISION_NAMES = {
    "B": "Boys",
    "G": "Girls",
}


def parse_ranking_list(html: str) -> list[RankingSnapshot]:
    """Parse a RankingListsPrint.aspx page into RankingSnapshot rows.

    Each row produces one snapshot. The ``as_of`` field is set to
    January 1 of the year encoded in the header (TennisLink does not
    publish a per-snapshot date in the print view); when the year is not
    parseable, ``as_of`` falls back to today.
    """

    if not html or not html.strip():
        raise ParseError("empty HTML passed to parse_ranking_list")

    soup = BeautifulSoup(html, "lxml")
    out: list[RankingSnapshot] = []

    grid = soup.find("table", id="grdMain")
    body_text = soup.get_text(" ", strip=True)
    if grid is None and "Ranking List" not in body_text:
        raise ParseError(
            "ranking_list: missing grdMain table AND no 'Ranking List' "
            "marker; not a TennisLink ranking-list page"
        )

    title = _extract_title(soup)
    parsed_header = HEADER_RE.search(title) if title else None
    category = _format_category(parsed_header)
    scope = _format_scope(parsed_header)
    as_of_year = parsed_header.group("year") if parsed_header else None
    try:
        as_of = date(int(as_of_year), 1, 1) if as_of_year else date.today()
    except (TypeError, ValueError):
        as_of = date.today()

    section_label = parsed_header.group("section") if parsed_header else None

    grid = soup.find("table", id="grdMain")
    if grid is None or not isinstance(grid, Tag):
        return out

    rows = grid.find_all("tr")
    if len(rows) <= 1:
        return out

    for row in rows[1:]:
        spans = row.find_all("span")
        if not spans:
            continue
        fields: dict[str, str] = {}
        for span in spans:
            sid = span.get("id", "")
            if not isinstance(sid, str):
                continue
            if "_lbl" not in sid:
                continue
            key = sid.rsplit("_lbl", 1)[-1]
            fields[key] = span.get_text(strip=True)

        full_name = fields.get("FullName", "").strip()
        if not full_name:
            continue
        # Player ID is the same synthetic slug used by
        # parse_player_search_results so the two surfaces stay joinable.
        slug = re.sub(r"[^A-Za-z0-9]+", "_", full_name).strip("_").lower()
        section = fields.get("Section") or section_label or ""
        player_id = f"tl-rank:{section}:{slug}"

        try:
            position = int(fields["Rank"]) if fields.get("Rank") else None
        except ValueError:
            position = None
        try:
            points: float | None = float(fields["Points"]) if fields.get("Points") else None
        except ValueError:
            points = None

        out.append(
            RankingSnapshot(
                player_id=player_id,
                category=category,
                scope=scope,
                section=section or None,
                position=position,
                points=points,
                as_of=as_of,
            )
        )

    return out


def _extract_title(soup: BeautifulSoup) -> str | None:
    """Find the page's title text — the cell labelled e.g. `*B14 2019 GA …`."""

    # The title sits in the first `<td class="FieldData">` of the outer
    # table, prefixed by `&nbsp;`. Strip the leading whitespace.
    for td in soup.find_all("td", class_="FieldData"):
        text = td.get_text(strip=True)
        # Filter out the column-header row (Rank, Name, …).
        if not text or text in {"Rank", "Name", "City", "State", "Section", "District", "Points"}:
            continue
        if HEADER_RE.search(text):
            return text
        # Soft fallback — any title-looking cell that isn't a column header.
        if any(ch.isdigit() for ch in text) and len(text) > 10:
            return text
    return None


def _format_category(m: re.Match[str] | None) -> str:
    """Render the human-readable category, e.g. ``"Boys 14 Singles"``."""

    if not m:
        return "Unknown"
    div = m.group("div")
    list_type = m.group("list_type").strip()
    gender = DIVISION_NAMES.get(div[0], div[0])
    age = div[1:]
    # The list_type usually carries Singles/Doubles + the list flavor; we
    # surface only the discipline keyword if present.
    discipline = "Doubles" if "doubles" in list_type.lower() else "Singles"
    return f"{gender} {age} {discipline}"


def _format_scope(m: re.Match[str] | None) -> str:
    """`national` if the header has no section abbreviation, else `sectional`."""

    if not m:
        return "national"
    section = m.group("section")
    if section.upper() in {"USA", "NATL", "NATIONAL"}:
        return "national"
    return "sectional"
