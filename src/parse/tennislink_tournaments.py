"""HTML parsers for TennisLink tournament pages.

Two top-level entry points:

- :func:`parse_tournament_search_results` — reads a SearchResults.aspx page
  and yields one :class:`Tournament` per row in the result grid. Tournament
  IDs come from the page's ``javascript:Go(<id>)`` anchors; that integer is
  what the rest of the system uses as `Tournament.usta_id`.
- :func:`parse_tournament_detail` — reads a Tournament.aspx page (the
  tournament-home view) and returns a tuple of one fully-populated
  :class:`Tournament` plus a list of :class:`Draw` rows derived from the
  page's event dropdown.

These parsers use lxml for XPath and BeautifulSoup for forgiving HTML
parsing. TennisLink's HTML is server-rendered ASP.NET WebForms output —
deeply nested tables, inline styles, ad blocks — but the structural
selectors below have proven stable across the captured fixtures.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from bs4 import BeautifulSoup, Tag

from src.models.draw import Draw
from src.models.tournament import Surface, Tournament
from src.parse.players import ParseError

__all__ = [
    "ParseError",
    "parse_tournament_search_results",
    "parse_tournament_detail",
]

# Tournament rows in SearchResults.aspx have an anchor like:
#   <a href="javascript:Go(232435);">NAME - 150072518</a>
# The integer in Go() is the TennisLink tournament ID we use as usta_id.
GO_TOURNAMENT_RE = re.compile(r"Go\((\d+)\)")

# Tournament IDs are shown on the detail page as e.g. "150072518" — the
# USTA Tournament Number that the public uses, distinct from the internal
# `Go(...)` integer. We capture both.
EXTERNAL_TID_RE = re.compile(r"-\s*(\d{6,})\s*$")

# Event dropdown options like `<option value="#5">Boys' 14 Singles</option>`.
EVENT_OPTION_RE = re.compile(r"^#(\d+)$")

# Date strings on TennisLink come in several shapes:
#   "11/27/2018"
#   "November 27-29, 2018"
#   "December 26-28, 2018"
DATE_RANGE_RE = re.compile(
    r"^(?P<month>[A-Za-z]+)\s+(?P<d1>\d{1,2})(?:-(?P<d2>\d{1,2}))?,\s+(?P<year>\d{4})$"
)


def parse_tournament_search_results(html: str) -> list[Tournament]:
    """Parse a SearchResults.aspx page into a list of :class:`Tournament`.

    Each row of the result grid becomes one Tournament. Fields populated:
    ``usta_id`` (the integer from `Go(N)`), ``name``, ``location_city``,
    ``location_state``, ``start_date`` (when parseable). Other fields stay
    at their model defaults — the search page does not show them.
    """

    if not html or not html.strip():
        raise ParseError("empty HTML passed to parse_tournament_search_results")

    soup = BeautifulSoup(html, "lxml")
    out: list[Tournament] = []

    # Sanity-check the page is actually a TennisLink search results page.
    # Either the dgTournaments grid is present, or the "no results" banner.
    grid = soup.find("table", id=re.compile(r"dgTournaments$"))
    page_text = soup.get_text(" ", strip=True)
    if grid is None and "No tournaments results found" not in page_text:
        if "Tournaments - Search Results" not in page_text:
            raise ParseError(
                "tournament_search_results: dgTournaments table missing and "
                "page does not look like a TennisLink search results page"
            )

    # Each tournament occupies one <tr> inside the dgTournaments grid that
    # contains a `javascript:Go(<id>)` anchor. We pivot on those anchors
    # rather than CSS-classing because TennisLink's classes are inconsistent.
    for anchor in soup.find_all("a", href=GO_TOURNAMENT_RE):
        m = GO_TOURNAMENT_RE.search(anchor.get("href", ""))
        if not m:
            continue
        usta_id = m.group(1)

        # The row containing this anchor.
        row = anchor.find_parent("tr")
        if row is None:
            continue

        cells = row.find_all("td", recursive=False)
        if not cells:
            # Sometimes the cells live one level deeper; fall back to all <td>.
            cells = row.find_all("td")

        # Name + external ID come from the anchor text. The anchor text looks
        # like: "  WINTER CHMPS. - 100000202\n". Strip and split on the last
        # " - " to separate name from the visible USTA Tournament Number.
        name_text = anchor.get_text(separator=" ", strip=True)
        name, external_tid = _split_name_and_external_id(name_text)

        # First <td> typically has the start date.
        start_date = None
        if cells:
            start_date = _parse_short_date(cells[0].get_text(strip=True))

        # Location is in the cell after the anchor's containing cell.
        city = state = None
        anchor_cell = anchor.find_parent("td")
        if anchor_cell is not None:
            location_cell = anchor_cell.find_next_sibling("td")
            if location_cell is not None:
                city, state = _parse_location(location_cell.get_text(separator=" ", strip=True))

        out.append(
            Tournament(
                usta_id=usta_id,
                name=name,
                start_date=start_date,
                location_city=city,
                location_state=state,
                # Search page doesn't reveal these — fall back to model defaults.
                # The external USTA Tournament Number is preserved on the
                # Tournament's `level` field is wrong, so stash it elsewhere
                # later; for v1 we keep `usta_id` as the TennisLink int.
                level=external_tid,
            )
        )

    return out


def parse_tournament_detail(html: str) -> tuple[Tournament, list[Draw]]:
    """Parse a Tournament.aspx page into a Tournament + its Draws.

    The detail page is the canonical source for tournament metadata
    (dates, location, surface, sanction body). The events dropdown
    (``ddlEvents``) yields one Draw per option.
    """

    if not html or not html.strip():
        raise ParseError("empty HTML passed to parse_tournament_detail")

    soup = BeautifulSoup(html, "lxml")

    h1 = soup.select_one(".tournament_search h1")
    info_tables = soup.select("table.tournament_info")
    if h1 is None and not info_tables:
        raise ParseError(
            "tournament_detail: neither <h1> tournament name nor "
            "<table class='tournament_info'> present; not a TennisLink "
            "tournament detail page"
        )

    name = _text_or_none(h1) or "(unknown)"

    # The two `tournament_info` tables hold most metadata. We pluck named
    # cells by their preceding label rather than positional index because
    # TennisLink reorders cells across page versions.
    info = _extract_info_table(soup)

    external_tid = info.get("Tournament ID") or info.get("Tournament\xa0ID")
    dates_raw = info.get("Dates")
    start_date, end_date = _parse_date_range(dates_raw) if dates_raw else (None, None)

    # Second info table has section / district / surface.
    section_info = _extract_info_table_second(soup)
    surface_raw = section_info.get("Surface Type") or ""
    surface = _classify_surface(surface_raw)

    location_city, location_state = _parse_location_from_detail(soup)

    # `usta_id` here is the URL's `T=` value when callable code supplies it
    # via the caller; in pure-from-HTML parsing we fall back to the external
    # Tournament Number we read off the page.
    usta_id = external_tid or _guess_t_from_form(soup) or "0"

    tournament = Tournament(
        usta_id=str(usta_id),
        name=name,
        start_date=start_date,
        end_date=end_date,
        location_city=location_city,
        location_state=location_state,
        surface=surface,
        sanction_body=section_info.get("Section"),
        status=_infer_status(start_date, end_date, name),
        last_fetched_at=datetime.now(),
    )

    draws = _parse_draws_from_events_dropdown(soup, tournament.usta_id)
    return tournament, draws


# -- helpers ---------------------------------------------------------------------


def _split_name_and_external_id(text: str) -> tuple[str, str | None]:
    """Anchor text like ``"FOO TOURNAMENT - 100000202"``.

    Returns (name, external_id). External ID is the trailing 6+ digit run,
    if present; otherwise the whole string is the name.
    """

    m = EXTERNAL_TID_RE.search(text)
    if m:
        external = m.group(1)
        name = text[: m.start()].rstrip(" -")
        return name.strip(), external
    return text.strip(), None


def _parse_short_date(s: str) -> date | None:
    """Parse ``"11/27/2018"`` into a :class:`date`."""

    s = s.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_date_range(s: str) -> tuple[date | None, date | None]:
    """Parse ``"November 27-29, 2018"`` into (start, end) dates."""

    m = DATE_RANGE_RE.match(s.strip())
    if not m:
        # Fall back to a single date.
        single = _parse_short_date(s)
        return single, single
    month = m.group("month")
    d1 = int(m.group("d1"))
    d2 = int(m.group("d2")) if m.group("d2") else d1
    year = int(m.group("year"))
    try:
        start = datetime.strptime(f"{month} {d1} {year}", "%B %d %Y").date()
        end = datetime.strptime(f"{month} {d2} {year}", "%B %d %Y").date()
    except ValueError:
        return None, None
    return start, end


def _parse_location(text: str) -> tuple[str | None, str | None]:
    """Parse ``"Coral Springs, FL"`` into ("Coral Springs", "FL")."""

    text = text.strip()
    if "," in text:
        city, _, rest = text.partition(",")
        state = rest.strip().split()[0] if rest.strip() else None
        return city.strip(), state
    return text or None, None


def _text_or_none(node: Tag | None) -> str | None:
    if node is None:
        return None
    text = node.get_text(separator=" ", strip=True)
    return text or None


def _extract_info_table(soup: BeautifulSoup) -> dict[str, str]:
    """Read the first ``<table class="tournament_info">`` as label->value map.

    The Tournament ID cell typically nests its visible ID alongside skill-
    level metadata (Tournament ID, then a ``<br>``, then "Skill Level:",
    then a value). We split on whitespace and take the first run of digits
    for `Tournament ID` specifically so the value is usable as an ID.
    """

    table = soup.select_one("table.tournament_info")
    if table is None:
        return {}
    rows = table.find_all("tr", recursive=False)
    if len(rows) < 2:
        return {}
    labels = [c.get_text(strip=True).rstrip(":") for c in rows[0].find_all("td")]
    out: dict[str, str] = {}
    for label, cell in zip(labels, rows[1].find_all("td"), strict=False):
        # For the Tournament ID column, prefer the first numeric token so
        # we don't smuggle Skill-Level text into the ID field.
        if label.replace("\xa0", " ").strip() == "Tournament ID":
            m = re.search(r"\d{4,}", cell.get_text(separator=" ", strip=True))
            out[label] = m.group(0) if m else cell.get_text(separator=" ", strip=True)
        else:
            out[label] = cell.get_text(separator=" ", strip=True)
    return out


def _extract_info_table_second(soup: BeautifulSoup) -> dict[str, str]:
    """Read the second tournament_info table (section/district/surface)."""

    tables = soup.select("table.tournament_info")
    if len(tables) < 2:
        return {}
    table = tables[1]
    rows = table.find_all("tr", recursive=False)
    if len(rows) < 2:
        return {}
    labels = [c.get_text(strip=True).rstrip(":") for c in rows[0].find_all("td")]
    values = [c.get_text(separator=" ", strip=True) for c in rows[1].find_all("td")]
    return dict(zip(labels, values, strict=False))


def _classify_surface(s: str) -> Surface:
    s = s.lower()
    if "clay" in s and "indoor" in s:
        return "clay"  # no separate enum for indoor clay
    if "clay" in s:
        return "clay"
    if "grass" in s:
        return "grass"
    if "hard" in s and "indoor" in s:
        return "indoor_hard"
    if "hard" in s:
        return "hard"
    if "carpet" in s:
        return "carpet"
    return "unknown"


def _parse_location_from_detail(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Find the site-address line and split into (city, state)."""

    # The address is rendered as e.g. "2575 Sportsplex Drive<br>Coral Springs, FL 33065"
    # inside the more_info section. We find any <td> that contains a two-letter
    # state code preceded by a comma and a 5-digit ZIP after it. Pick the
    # final word-run before the comma so we don't smuggle the street into the
    # city slot.
    addr_re = re.compile(
        r"\b([A-Za-z][A-Za-z .'\-]{1,40}),\s+([A-Z]{2})\s+\d{5}"
    )
    for td in soup.find_all("td"):
        text = td.get_text(separator="\n", strip=True)
        for line in text.splitlines():
            m = addr_re.search(line)
            if m is not None:
                # Strip leading street-number/road-name remnants — keep
                # only the trailing run of word tokens before the comma.
                city = m.group(1).strip()
                # If multiple commas in the matched group, take the part
                # after the last comma as the "city".
                tokens = [t.strip() for t in city.split(",") if t.strip()]
                if tokens:
                    city = tokens[-1]
                return city, m.group(2)
    return None, None


def _guess_t_from_form(soup: BeautifulSoup) -> str | None:
    form = soup.find("form")
    if form is None or not isinstance(form, Tag):
        return None
    action = form.get("action", "")
    if not isinstance(action, str):
        return None
    m = re.search(r"[?&]T=(\d+)", action)
    return m.group(1) if m else None


def _infer_status(
    start: date | None,
    end: date | None,
    name: str,
) -> str:
    if "*CANCELLED*" in name.upper() or "*CANCELED*" in name.upper():
        return "cancelled"
    if start is None or end is None:
        return "upcoming"
    today = date.today()
    if today < start:
        return "upcoming"
    if start <= today <= end:
        return "in_progress"
    return "completed"


def _parse_draws_from_events_dropdown(
    soup: BeautifulSoup,
    tournament_id: str,
) -> list[Draw]:
    """Pull one Draw per option in the events `<select>` dropdown.

    The events dropdown lives in two places: the Draws tab and the
    summary header. We prefer the Draws tab's `ddlEvents` because it
    includes the canonical event IDs.
    """

    select = soup.find("select", id=re.compile(r"ddlEvents$"))
    if select is None or not isinstance(select, Tag):
        return []
    draws: list[Draw] = []
    for option in select.find_all("option"):
        value: Any = option.get("value", "")
        if not isinstance(value, str):
            continue
        value = value.strip()
        m = EVENT_OPTION_RE.match(value)
        if not m:
            # Skip the placeholder options like "" / "-1" (All Draws).
            continue
        event_id = m.group(1)
        label = option.get_text(strip=True)
        gender = _infer_gender(label)
        age_group = _infer_age_group(label)
        draws.append(
            Draw(
                usta_id=f"{tournament_id}:{event_id}",
                tournament_id=tournament_id,
                name=label,
                gender=gender,
                age_group=age_group,
                division=label,
            )
        )
    return draws


def _infer_gender(label: str) -> str | None:
    lower = label.lower()
    if "boys" in lower or "men" in lower:
        return "M"
    if "girls" in lower or "women" in lower:
        return "F"
    return None


def _infer_age_group(label: str) -> str | None:
    m = re.search(r"\b(\d{1,2})\b", label)
    return m.group(1) if m else None
