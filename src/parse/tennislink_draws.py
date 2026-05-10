"""HTML parser for a TennisLink draw page.

The draw page is Tournament.aspx with ``T=<tid>&E=<eid>&tab=Draws`` — it
renders one event's full bracket inline as nested tables. Players appear
as anchors of the form::

    <a href="/tournaments/Draws/PlayerTournamentHistory.aspx?MID=...">NAME</a>

Player MIDs are ~30-digit numeric strings; we treat them opaquely. Match
scores appear in adjacent ``<div>``s as semicolon-separated set strings::

    <div>6-3; 6-2</div>
    <div>6-7(3); 6-3; 10-7</div>

Round labels (Finals, SF, QF, Round of 16, …) appear as plain text headers.

This parser does NOT attempt to reconstruct the bracket geometry (which
match feeds into which). It extracts the flat list of unique players +
the flat list of matches with score strings. Bracket reconstruction is
a Phase-2 enrichment concern, not a parse concern.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag

from src.models.draw import Draw, DrawEntry
from src.models.match import Match, MatchOutcome, SetScore
from src.models.player import Player
from src.parse.players import ParseError

__all__ = ["ParseError", "parse_draw"]

# Anchor href shape: /tournaments/Draws/PlayerTournamentHistory.aspx?MID=...
MID_RE = re.compile(r"MID=(\d+)", re.IGNORECASE)

# Score string shape: "6-3; 6-2" or "6-7(3); 6-3; 10-7" or "6-2; 6-3"
SET_RE = re.compile(
    r"(?P<a>\d+)-(?P<b>\d+)(?:\((?P<tb>\d+)\))?"
)

# Seeded players show a parenthesized seed after their name: "BURROWS (1)".
SEED_RE = re.compile(r"\((\d+)\)")


def parse_draw(html: str) -> tuple[Draw, list[DrawEntry], list[Match]]:
    """Parse a draw page into (Draw, [DrawEntry], [Match]).

    The Draw object's ``usta_id`` is composed of ``"<tournament_id>:<event_id>"``
    (the same convention used by
    :func:`src.parse.tennislink_tournaments.parse_tournament_detail`) so
    a draw row written by the search/detail parser can be merged with the
    one written here.
    """

    if not html or not html.strip():
        raise ParseError("empty HTML passed to parse_draw")

    soup = BeautifulSoup(html, "lxml")

    # Sanity check: a real TennisLink draw page either has a DrawTableList
    # or at least a Tournament.aspx form action with T= and E= params.
    has_draw_table = soup.find("table", class_="DrawTableList") is not None
    form = soup.find("form")
    has_form_t = (
        isinstance(form, Tag)
        and isinstance(form.get("action", ""), str)
        and "T=" in (form.get("action", "") or "")
    )
    if not has_draw_table and not has_form_t:
        raise ParseError(
            "draw: neither DrawTableList nor a Tournament.aspx form action "
            "is present; not a TennisLink draw page"
        )

    tournament_id, event_id = _extract_tids(soup)
    draw_name = _extract_draw_name(soup)

    players, entries = _extract_players(soup, draw_id=f"{tournament_id}:{event_id}")
    matches = _extract_matches(soup, draw_id=f"{tournament_id}:{event_id}", players=players)

    draw = Draw(
        usta_id=f"{tournament_id}:{event_id}",
        tournament_id=tournament_id,
        name=draw_name or "Draw",
        size=len(players),
        gender=_infer_gender(draw_name or ""),
        age_group=_infer_age_group(draw_name or ""),
        division=draw_name,
    )
    return draw, entries, matches


def _extract_tids(soup: BeautifulSoup) -> tuple[str, str]:
    """Read tournament + event ID from the form's POST-back action URL."""

    form = soup.find("form")
    tournament_id = "0"
    event_id = "0"
    if form is not None and isinstance(form, Tag):
        action = form.get("action", "")
        if isinstance(action, str):
            qs = parse_qs(urlparse(action).query)
            if "T" in qs:
                tournament_id = qs["T"][0]
            if "E" in qs:
                event_id = qs["E"][0]
    return tournament_id, event_id


def _extract_draw_name(soup: BeautifulSoup) -> str | None:
    """The draw heading appears in a ``<td>`` near the top of the bracket.

    Shape::

        <td><font color="#000000">Boys' 14 Singles   - Final Rounds</font></td>
    """

    # Anything inside a <font color="#000000"> at the bracket header.
    for td in soup.find_all("td"):
        font = td.find("font")
        if font is not None and "Singles" in font.get_text():
            text = font.get_text(strip=True)
            # Strip trailing " - Final Rounds" etc.
            return text.split(" - ")[0].strip() or text.strip()
        elif font is not None and "Doubles" in font.get_text():
            text = font.get_text(strip=True)
            return text.split(" - ")[0].strip() or text.strip()
    # Fall back to the tournament's overall H1 if the bracket header is missing.
    h1 = soup.find("h1")
    if h1 is not None:
        return h1.get_text(strip=True)
    return None


def _extract_players(
    soup: BeautifulSoup,
    draw_id: str,
) -> tuple[dict[str, Player], list[DrawEntry]]:
    """Walk the draw, collect each unique MID with its name + seed.

    Returns:
        players: keyed by MID for downstream join.
        entries: one :class:`DrawEntry` per unique player in this draw.
    """

    players: dict[str, Player] = {}
    entries: list[DrawEntry] = []
    seen: set[str] = set()
    position = 0

    for anchor in soup.find_all("a", href=MID_RE):
        href = anchor.get("href", "")
        if not isinstance(href, str):
            continue
        m = MID_RE.search(href)
        if not m:
            continue
        mid = m.group(1)
        # The first appearance of a player anchor is in the seeding column —
        # those rows are usually next to a city/state cell, so we infer the
        # "primary" entry from the longest-form anchor text (full name vs.
        # initial-form like "A. BURROWS"). We dedupe by MID.
        anchor_text = anchor.get_text(strip=True)
        seed: int | None = None
        # Peek at the surrounding span which holds the seed parenthesis.
        parent_span = anchor.find_parent("span")
        seed_source = parent_span.get_text() if parent_span is not None else anchor_text
        seed_match = SEED_RE.search(seed_source or "")
        if seed_match:
            try:
                seed = int(seed_match.group(1))
            except ValueError:
                seed = None

        # Keep the longest-named appearance (likely the seeding column).
        existing = players.get(mid)
        full_name = _clean_name(anchor_text)
        if existing is None or len(full_name) > len(existing.full_name):
            players[mid] = Player(
                usta_id=mid,
                full_name=full_name,
                profile_url=(
                    f"https://tennislink.usta.com{href}"
                    if href.startswith("/")
                    else href
                ),
            )

        if mid in seen:
            continue
        seen.add(mid)
        position += 1
        entries.append(
            DrawEntry(
                draw_id=draw_id,
                player_id=mid,
                seed=seed,
                position=position,
                status="entered",
            )
        )

    return players, entries


def _clean_name(s: str) -> str:
    """Strip seed annotation and normalize whitespace."""

    s = SEED_RE.sub("", s).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _extract_matches(
    soup: BeautifulSoup,
    draw_id: str,
    players: dict[str, Player],
) -> list[Match]:
    """Collect score strings as matches.

    TennisLink renders scores in narrow ``<div>``s near the winning slot
    of each pairing. We pick those up and pair them with the closest
    pair of player anchors. This is a best-effort flat extraction — we
    do NOT attempt to fully reconstruct who-played-whom; that is a draw
    geometry problem deferred to enrichment.
    """

    matches: list[Match] = []
    # A match score `<div>` lives inside a `<td>` that also contains the
    # players' anchors via its sibling cells. We pick up every `<div>` whose
    # text matches at least one set string (e.g. "6-3" or "6-7(3)").
    seen_scores: set[str] = set()
    for div in soup.find_all("div"):
        text = div.get_text(strip=True)
        if not text or len(text) > 80:
            continue
        # Must contain at least one set-shaped substring.
        if not SET_RE.search(text):
            continue
        # Must look like a score (digits + hyphen + digits, semicolon, etc.).
        if not re.fullmatch(r"[\d\-;\s\(\)]+(?:RET|RETD|DEF|WO)?", text, re.IGNORECASE):
            continue
        # Dedupe identical strings in the same draw (they appear in mirror
        # rows of the bracket).
        if text in seen_scores:
            continue
        seen_scores.add(text)

        sets, outcome = _parse_score_string(text)
        matches.append(
            Match(
                draw_id=draw_id,
                score_raw=text,
                sets=sets,
                outcome=outcome,
            )
        )

    return matches


def _parse_score_string(s: str) -> tuple[list[SetScore], MatchOutcome]:
    """Parse ``"6-3; 6-2"`` or ``"6-7(3); 6-3; 10-7"`` into SetScore list."""

    s = s.strip()
    outcome: MatchOutcome = "completed"
    if re.search(r"\bRET(D)?\b", s, re.IGNORECASE):
        outcome = "retired"
    elif re.search(r"\bWO\b", s, re.IGNORECASE):
        outcome = "walkover"
    elif re.search(r"\bDEF\b", s, re.IGNORECASE):
        outcome = "default"

    sets: list[SetScore] = []
    for chunk in re.split(r"[;,]", s):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = SET_RE.match(chunk)
        if not m:
            continue
        a = int(m.group("a"))
        b = int(m.group("b"))
        tb_a = tb_b = None
        if m.group("tb") is not None:
            # The (n) appears on the losing side. Without geometry context
            # we record the tiebreak point count on whichever side won fewer
            # games in that set — the parser is intentionally lossless: we
            # store the parenthesized value on the side with the LOWER games
            # total, which is the TennisLink convention.
            tb_loser = int(m.group("tb"))
            if a < b:
                tb_a = tb_loser
            else:
                tb_b = tb_loser
        sets.append(SetScore(games_a=a, games_b=b, tiebreak_a=tb_a, tiebreak_b=tb_b))
    return sets, outcome


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
