"""HTML parser for a TennisLink ranking list (``RankingListsPrint.aspx``).

This parser produces :class:`~src.models.ranking.RankingList` +
:class:`~src.models.ranking.RankingListEntry` rows from the print view of
``RankingListsPrint.aspx?id=<LIST_ID>``. It is the TennisLink counterpart
to :mod:`src.parse.clubspark_rankings` (deferred): together they let the
Rankings-First wave land real, persistable list captures regardless of
whether residential-proxy egress for Clubspark is configured yet.

This is distinct from :mod:`src.parse.tennislink_rankings`, which produces
per-player :class:`RankingSnapshot` rows (the older snapshot shape from
the same HTML). The newer ``RankingList`` shape captures the *whole list*
as a single header row plus N entry rows, which is what the
``/rankings/u12-boys-national`` UI route consumes.

Print-view structure
====================

A single ``<table id="grdMain">`` with 7 columns:

    Rank | Name | City | State | Section | District | Points

Each data cell is a ``<span id="grdMain_ctl{NN}_lbl{Field}" class="FieldLabel">``
where ``NN`` is a 2-digit row index starting at ``ctl02`` and ``Field`` is one of
``Rank``, ``FullName``, ``City``, ``State``, ``Section``, ``District``, ``Points``.
Names are rendered "Last, First" (no anchor tag, no USTA member id).

Header text (page title) lives in the first ``<td class="FieldData">`` of
the outer wrapper table, typically prefixed by ``&nbsp;`` and optionally a
``*`` star. Observed shapes (2026-05-11 recon):

- ``*Boys 12 (Combined)``                       — current B12 print
- ``Boys 14 Singles Seeding``                   — current B14 seeding
- ``Boys 12 Singles National Championship Seeding`` — pre-2021 archive
- ``*B14 2019 GA Standings (Combined)``         — older sectional standings

We parse the header pragmatically: lift age + gender from "Boys NN" /
"Girls NN" / "B14" / "G18" patterns, and try to recover a 4-digit year if
present. Without a year, the list's ``as_of`` defaults to today (the date
this parse was run) — the source data is historical but the *capture date*
is when we last fetched it.

Pure function: no IO, no network, no DB.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import TypedDict

from bs4 import BeautifulSoup, Tag

from src.models.ranking import Gender, RankingList, RankingListEntry, Scope
from src.parse.players import ParseError


class _ListMetadata(TypedDict):
    """Structured shape returned by :func:`_parse_metadata`.

    The narrow types here mirror the columns on
    :class:`~src.models.ranking.RankingList` so the caller can pass the
    dict straight into the model + the slug builder without ``cast``s.
    """

    age_category: str
    gender: Gender
    scope: Scope
    section: str | None
    as_of: date

__all__ = [
    "ParseError",
    "build_list_id",
    "parse_tennislink_rankings_list",
]


# Header shapes we recognize.
#
# 1. ``*B14 2019 GA Standings (Combined)``       — div + year + section abbr
# 2. ``Boys 12 Singles National Championship``   — verbose ``Boys NN``
# 3. ``*Boys 12 (Combined)``                     — verbose, no year/scope
# 4. ``Boys 14 Singles Seeding``                 — verbose, no year, scope-y noun
#
# The verbose ``Boys NN`` / ``Girls NN`` regex is the primary path; the
# old ``B14 2019 GA`` shape is the fallback that piggybacks the existing
# :mod:`src.parse.tennislink_rankings` parser.
_VERBOSE_HEADER_RE = re.compile(
    r"(?P<gender_word>Boys|Girls)\s+(?P<age>\d{1,2})\b\s*(?P<tail>.*)",
    re.IGNORECASE,
)
_LEGACY_HEADER_RE = re.compile(
    r"\*?\s*(?P<div>[BG])(?P<age>\d{1,2})\s+(?P<year>\d{4})\s+(?P<section_abbr>[A-Z]{2,})\s+(?P<tail>.+)",
)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

# Column-header strings used to detect (and skip) the column-header row.
_COLUMN_HEADERS = frozenset(
    {"Rank", "Name", "City", "State", "Section", "District", "Points"}
)

# Scope keywords. "National" beats sectional/district when both appear.
_SCOPE_KEYWORDS = (
    ("national", "national"),
    ("sectional", "sectional"),
    ("section", "sectional"),
    ("district", "district"),
)


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def parse_tennislink_rankings_list(
    html: str,
    *,
    list_id: str | None = None,
    fetched_at: datetime | None = None,
    source: str = "tennislink",
) -> tuple[RankingList, list[RankingListEntry]]:
    """Parse a print-view ranking list into header + entries.

    Args:
        html: Raw HTML body from ``RankingListsPrint.aspx?id=<LIST_ID>``.
        list_id: TennisLink ``LIST_ID`` (used to build the list's slug id).
            When ``None``, the slug is derived from the parsed metadata
            alone, which is enough for tests but means re-fetches of two
            distinct lists with identical metadata would collide.
        fetched_at: Override the "when we fetched this" stamp. Defaults to
            ``datetime.now(UTC)`` so each call is timestamped. Tests pin
            this for deterministic assertions.
        source: Source label written into ``RankingList.source``. Defaults
            to ``"tennislink"``.

    Returns:
        ``(RankingList, list[RankingListEntry])``. The list of entries is
        empty when the page has no ``grdMain`` rows (e.g. a "No ranking
        information for this list" landing). Callers should treat that as
        a soft state, not an error.

    Raises:
        ParseError: when the HTML is empty or clearly not a TennisLink
            rankings page (no ``grdMain`` AND no ``"Ranking List"`` marker).
    """
    if not html or not html.strip():
        raise ParseError("empty HTML passed to parse_tennislink_rankings_list")

    soup = BeautifulSoup(html, "lxml")
    body_text = soup.get_text(" ", strip=True)
    grid = soup.find("table", id="grdMain")
    if grid is None and "Ranking List" not in body_text:
        raise ParseError(
            "tennislink_rankings_list: missing grdMain table AND no "
            "'Ranking List' marker; not a TennisLink ranking-list page"
        )

    title = _extract_title(soup)
    metadata = _parse_metadata(title)
    when = fetched_at or datetime.now(UTC)

    entries = _extract_entries_with_pending_list_id(grid)

    resolved_list_id = list_id or build_list_id(
        age_category=metadata["age_category"],
        gender=metadata["gender"],
        scope=metadata["scope"],
        section=metadata["section"],
        as_of=metadata["as_of"],
    )
    # Stamp the resolved list_id onto each pending entry.
    bound_entries: list[RankingListEntry] = []
    for raw in entries:
        bound_entries.append(
            RankingListEntry(
                list_id=resolved_list_id,
                position=raw["position"],
                player_usta_id=raw["player_usta_id"],
                player_name_raw=raw["player_name_raw"],
                points=raw["points"],
                section=raw["section"],
                wtn_singles=None,  # TennisLink does not expose WTN.
                wtn_doubles=None,
            )
        )

    header = RankingList(
        id=resolved_list_id,
        age_category=metadata["age_category"],
        gender=metadata["gender"],
        scope=metadata["scope"],
        section=metadata["section"],
        as_of=metadata["as_of"],
        source=source,
        total_players=len(bound_entries),
        fetched_at=when,
    )
    return header, bound_entries


def build_list_id(
    *,
    age_category: str,
    gender: Gender,
    scope: Scope,
    section: str | None,
    as_of: date,
) -> str:
    """Build a stable slug id for a ranking list.

    The same (age_category, gender, scope, section, as_of) tuple always
    maps to the same slug, so re-fetching the same list upserts cleanly.

    Examples:

        >>> build_list_id(age_category="Boys 12s", gender="M",
        ...               scope="national", section=None,
        ...               as_of=date(2026, 5, 11))
        'u12-boys-national-2026-05-11'

        >>> build_list_id(age_category="Girls 14s", gender="F",
        ...               scope="sectional", section="Florida",
        ...               as_of=date(2026, 5, 11))
        'u14-girls-sectional-florida-2026-05-11'
    """
    age_token = _age_token(age_category) or "uXX"
    gender_token = {"M": "boys", "F": "girls", "X": "mixed"}.get(gender, "mixed")
    section_token: str | None = None
    if section:
        section_token = re.sub(r"[^A-Za-z0-9]+", "-", section.lower()).strip("-")
    parts = [age_token, gender_token, scope]
    if section_token:
        parts.append(section_token)
    parts.append(as_of.isoformat())
    return "-".join(parts)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


_RawEntry = dict[str, object]


def _extract_entries_with_pending_list_id(
    grid: Tag | None,
) -> list[dict[str, object]]:
    """Pull (position, player_id, name, points, section) tuples from grdMain.

    Returns entries with all fields populated *except* ``list_id``, which the
    caller stamps in once the slug is resolved. Rows missing a Name span
    are skipped silently — those are the column-header row and any
    decorative spacer rows ASP.NET sometimes emits.
    """
    if grid is None or not isinstance(grid, Tag):
        return []

    out: list[dict[str, object]] = []
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
            if not isinstance(sid, str) or "_lbl" not in sid:
                continue
            key = sid.rsplit("_lbl", 1)[-1]
            # Names are rendered with trailing whitespace ("Quan, Rudy ");
            # strip both ends so the persisted text is tight.
            fields[key] = span.get_text(strip=True)

        full_name = fields.get("FullName", "").strip()
        if not full_name:
            continue

        try:
            position = int(fields["Rank"]) if fields.get("Rank") else 0
        except ValueError:
            position = 0
        if position <= 0:
            # Defensive: a row with no parseable rank can't slot into a
            # PRIMARY KEY (list_id, position) row — skip it rather than
            # collide on position=0.
            continue

        points_raw = fields.get("Points", "")
        try:
            points: int | None = int(points_raw) if points_raw else None
        except ValueError:
            points = None

        section = fields.get("Section") or None

        # Player USTA id is not exposed on the print view. Mint a stable
        # synthetic id from the name + section so repeated parses upsert
        # cleanly. The Clubspark sync wave will eventually replace these
        # with real GUIDs via a name-match enrichment.
        slug = re.sub(r"[^A-Za-z0-9]+", "_", full_name).strip("_").lower()
        section_slug = re.sub(r"[^A-Za-z0-9]+", "_", (section or "")).strip("_").lower()
        synth_id = f"tl-rank:{section_slug}:{slug}" if section_slug else f"tl-rank::{slug}"

        out.append(
            {
                "position": position,
                "player_usta_id": synth_id,
                "player_name_raw": full_name,
                "points": points,
                "section": section,
            }
        )
    return out


def _extract_title(soup: BeautifulSoup) -> str | None:
    """Find the page's title text — the first FieldData cell with content."""
    for td in soup.find_all("td", class_="FieldData"):
        text = td.get_text(" ", strip=True)
        if not text:
            continue
        if text in _COLUMN_HEADERS:
            continue
        # The cell sometimes carries multiple noisy fragments joined by
        # &nbsp; — keep only the first non-empty line.
        first_line = text.splitlines()[0].strip()
        if not first_line:
            continue
        # Skip plain "Sort By" labels and similar.
        if first_line.lower().startswith("sort by"):
            continue
        return first_line
    return None


def _parse_metadata(title: str | None) -> _ListMetadata:
    """Best-effort metadata from the page's header line.

    Returns a dict with keys ``age_category`` (str), ``gender`` (Gender),
    ``scope`` (Scope), ``section`` (str | None), ``as_of`` (date).

    Defaults when the header is unparseable: ``"Unknown"`` /  ``"X"`` /
    ``"national"`` / ``None`` / today.
    """
    today = date.today()
    if not title:
        return {
            "age_category": "Unknown",
            "gender": "X",
            "scope": "national",
            "section": None,
            "as_of": today,
        }

    # Primary path: "Boys 12 (Combined)" / "Boys 14 Singles Seeding" / etc.
    m = _VERBOSE_HEADER_RE.search(title)
    if m:
        gender_word = m.group("gender_word").lower()
        gender: Gender = "M" if gender_word.startswith("boy") else "F"
        age = int(m.group("age"))
        tail = (m.group("tail") or "").strip()
        scope: Scope = _detect_scope(tail) or "national"
        section: str | None = None  # National lists do not name a section.
        year = _detect_year(title)
        as_of = date(year, 1, 1) if year else today
        return {
            "age_category": _age_category_label(gender, age),
            "gender": gender,
            "scope": scope,
            "section": section,
            "as_of": as_of,
        }

    # Fallback: legacy "*B14 2019 GA Standings (Combined)".
    legacy = _LEGACY_HEADER_RE.search(title)
    if legacy:
        div = legacy.group("div").upper()
        age = int(legacy.group("age"))
        year = int(legacy.group("year"))
        section_abbr = legacy.group("section_abbr").upper()
        gender = "M" if div == "B" else "F"
        scope = (
            "national"
            if section_abbr in {"USA", "NATL", "NATIONAL"}
            else "sectional"
        )
        section = None if scope == "national" else section_abbr
        return {
            "age_category": _age_category_label(gender, age),
            "gender": gender,
            "scope": scope,
            "section": section,
            "as_of": date(year, 1, 1),
        }

    # No structured header — capture the title verbatim as the age_category
    # so traceability survives the unparseable case.
    return {
        "age_category": title.strip() or "Unknown",
        "gender": "X",
        "scope": "national",
        "section": None,
        "as_of": today,
    }


def _age_category_label(gender: Gender, age: int) -> str:
    """Format the age-category label the way the rest of the app expects.

    Examples: ``"Boys 12s"``, ``"Girls 14s"``, ``"Mixed 10s"``.
    """
    word = {"M": "Boys", "F": "Girls", "X": "Mixed"}.get(gender, "Mixed")
    return f"{word} {age}s"


def _age_token(age_category: str) -> str | None:
    """Pull the ``"u12"``-style token from a label like ``"Boys 12s"``."""
    match = re.search(r"(\d{1,2})", age_category or "")
    if not match:
        return None
    return f"u{int(match.group(1))}"


def _detect_scope(text: str) -> Scope | None:
    """Best-effort scope detection from a free-text header tail."""
    lower = text.lower()
    for needle, scope in _SCOPE_KEYWORDS:
        if needle in lower:
            return scope  # type: ignore[return-value]
    return None


def _detect_year(text: str) -> int | None:
    """Extract a 4-digit year from a header string, or ``None`` if absent."""
    match = _YEAR_RE.search(text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:  # pragma: no cover - defensive
        return None
