"""HTML parsers for TennisLink player pages.

TennisLink does NOT expose a standalone player profile page (see RECON.md
and API_CONTRACTS.md). The two parser entry points here are:

- :func:`parse_player_profile` — reads a PlayerTournamentHistory.aspx page
  and returns the best-effort :class:`Player` we can construct from it.
  The page itself doesn't print the player's name, so the returned
  Player carries only the MID (as `usta_id`) and a placeholder full_name.
  Callers should populate `full_name` from the draw context.
- :func:`parse_player_search_results` — reads a RankingListsPrint.aspx
  page (the only TennisLink endpoint that joins names with section/city)
  and returns one :class:`Player` per ranked entry. This is the *de
  facto* "player search" surface even though TennisLink calls it
  "rankings".
"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag

from src.models.player import Player
from src.parse.players import ParseError

__all__ = [
    "ParseError",
    "parse_player_profile",
    "parse_player_search_results",
]

MID_RE = re.compile(r"MID=(\d+)", re.IGNORECASE)


def parse_player_profile(html: str) -> Player:
    """Construct a :class:`Player` from a PlayerTournamentHistory page.

    Only `usta_id` (the MID from the form action) and `profile_url` are
    extractable from this page. The full_name is set to a placeholder
    string — callers MUST overwrite it from the referring draw or
    ranking list before persisting.
    """

    soup = BeautifulSoup(html, "lxml")

    mid = "0"
    form = soup.find("form")
    if form is not None and isinstance(form, Tag):
        action = form.get("action", "")
        if isinstance(action, str):
            m = MID_RE.search(action) or MID_RE.search(urlparse(action).query)
            if m:
                mid = m.group(1)
            else:
                qs = parse_qs(urlparse(action).query)
                if "MID" in qs:
                    mid = qs["MID"][0]

    return Player(
        usta_id=mid,
        full_name="(name not available on TennisLink history page)",
        profile_url=f"https://tennislink.usta.com/tournaments/Draws/PlayerTournamentHistory.aspx?MID={mid}",
        last_fetched_at=datetime.now(),
    )


def parse_player_search_results(html: str) -> list[Player]:
    """Parse a ranking-list page into a list of :class:`Player`.

    Reuses the row structure of :func:`parse_ranking_list` but discards
    the rank/points columns and keeps only what's needed to instantiate
    a Player. This makes a ranking list double as a player-search
    surface — useful for "find player named X in section Y" workflows.
    """

    soup = BeautifulSoup(html, "lxml")
    out: list[Player] = []

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
        # The grdMain layout puts each labelled span in a known suffix order:
        # lblRank, lblFullName, lblCity, lblState, lblSection, lblDistrict, lblPoints.
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
        first, last = _split_last_first(full_name)
        # Ranking-list pages do not expose MIDs anonymously. We synthesize
        # a placeholder ID composed of the section+name slug so this
        # listing can be joined to a real MID later via draw-page captures.
        slug = re.sub(r"[^A-Za-z0-9]+", "_", full_name).strip("_").lower()
        section = fields.get("Section", "")
        synthetic_id = f"tl-rank:{section}:{slug}"

        out.append(
            Player(
                usta_id=synthetic_id,
                full_name=_normalize_name(full_name),
                first_name=first,
                last_name=last,
                section=section or None,
                district=fields.get("District") or None,
                last_fetched_at=datetime.now(),
            )
        )

    return out


def _split_last_first(s: str) -> tuple[str | None, str | None]:
    """Parse ``"Taylor, Davis"`` into (first="Davis", last="Taylor")."""

    if "," not in s:
        return None, None
    last, _, first = s.partition(",")
    return first.strip() or None, last.strip() or None


def _normalize_name(s: str) -> str:
    """Convert ``"Taylor, Davis "`` into ``"Davis Taylor"``."""

    first, last = _split_last_first(s)
    if first and last:
        return f"{first} {last}".strip()
    return s.strip()
