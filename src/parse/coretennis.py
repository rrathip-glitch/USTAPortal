"""HTML parsers for CoreTennis.net player pages.

CoreTennis is a third-party tennis-results aggregator (see
``src/fetch/coretennis_client.py``). For each player it exposes a profile,
ranking and results page. The data-rich one is *results*: per-tournament
match rows with date, surface, round, opponent and a compact score string
(e.g. ``"75 26 1210"`` for ``7-5 2-6 [10-12]``).

This module exposes a single entry point :func:`parse_coretennis_player`
that consumes the captured HTML for both the profile and the results page
and produces a :class:`Player` plus a list of :class:`Match` records, one
per ``pprRow`` in the results page. CoreTennis does not expose stable
USTA GUIDs; we use the CoreTennis numeric id as the player's ``usta_id``
foreign key.

Match outcome modelling note: CoreTennis labels each row from the
*current player's* perspective as ``W`` or ``L``. Our :class:`Match`
model does not have ``"won"`` / ``"lost"`` outcome literals — its valid
:data:`MatchOutcome` values are ``"completed"``, ``"retired"``,
``"walkover"``, ``"default"``, ``"unfinished"``, ``"unknown"``. We
therefore encode finished CoreTennis matches as ``outcome="completed"``
and use ``winner_id`` to carry the W/L information (``winner_id ==
player_id`` for W; ``winner_id is None`` for L, since CoreTennis gives
us the opponent name but not a stable opponent id from this page alone).
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Iterable

from bs4 import BeautifulSoup, Tag

from src.models.match import Match, SetScore
from src.models.player import Gender, Player
from src.parse.matches import infer_winner, parse_score
from src.parse.players import ParseError

__all__ = [
    "ParseError",
    "parse_coretennis_player",
]

LOGGER = logging.getLogger(__name__)

# Year-tab anchors look like: <a href="#" rel="yearContent2026">2026</a>.
# We also accept the wrapping div id "yearContent2026" as a fallback.
_YEAR_REL_RE = re.compile(r"yearContent(\d{4})")

# Date strings on CoreTennis rows are "MMM DD" (sometimes with a <br> between
# start and end). We pick the first one and combine it with the active year.
_MONTH_DAY_RE = re.compile(r"([A-Za-z]{3})\s+(\d{1,2})")

# Category strings look like "12 & under, Boys" or "16 & under, Girls".
_CATEGORY_RE = re.compile(
    r"(?P<age>\d+)\s*&\s*under\s*,\s*(?P<gender>Boys|Girls)",
    re.IGNORECASE,
)

_MONTH_TO_NUM = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_coretennis_player(
    profile_html: str | None,
    results_html: str,
    *,
    player_id: str,
    fetched_at: datetime | None = None,
) -> tuple[Player, list[Match]]:
    """Parse a CoreTennis player profile + results into our domain models.

    Parameters
    ----------
    profile_html:
        Raw HTML of the player's ``profile.html`` page, or ``None`` if it
        wasn't captured. When provided, used to enrich the returned
        :class:`Player` with name/gender/age_category.
    results_html:
        Raw HTML of the player's ``results.html`` page. **Required.**
        Each ``pprRow`` becomes one :class:`Match`.
    player_id:
        CoreTennis numeric id (e.g. ``"203938"``). Used as
        ``Player.usta_id`` and ``Match.player_a_id``.
    fetched_at:
        When the upstream HTML was captured. Stamped onto the Player and
        each Match. Defaults to ``datetime.now(UTC)``.

    Returns
    -------
    (player, matches)
        A :class:`Player` (with placeholder name if ``profile_html`` was
        ``None``) and a list of :class:`Match` records, one per row in
        the results page, in document order.

    Raises
    ------
    ParseError
        If ``results_html`` is empty or doesn't contain the expected
        ``plTourn`` / ``pprRow`` structure at all. Per-row failures are
        logged and skipped, never escalated.
    """

    if not results_html or not results_html.strip():
        raise ParseError("empty results_html passed to parse_coretennis_player")

    stamped_at = fetched_at if fetched_at is not None else datetime.now(UTC)

    player = _parse_profile(profile_html, player_id=player_id, fetched_at=stamped_at)
    matches = list(
        _iter_matches(
            results_html,
            player_id=player_id,
            fetched_at=stamped_at,
        )
    )
    return player, matches


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


def _parse_profile(
    profile_html: str | None,
    *,
    player_id: str,
    fetched_at: datetime,
) -> Player:
    """Build the :class:`Player` from the profile HTML, or a placeholder."""

    profile_url = (
        f"https://www.coretennis.net/tennis-player/-/{player_id}/profile.html"
    )

    if not profile_html or not profile_html.strip():
        return Player(
            usta_id=player_id,
            full_name=f"(coretennis player {player_id})",
            profile_url=profile_url,
            last_fetched_at=fetched_at,
        )

    soup = BeautifulSoup(profile_html, "lxml")
    header = soup.find("div", class_="ppHeader")
    if not isinstance(header, Tag):
        # Page exists but doesn't carry the expected header — return a
        # placeholder rather than crash; recon should flag this.
        LOGGER.warning("coretennis profile %s: no ppHeader found", player_id)
        return Player(
            usta_id=player_id,
            full_name=f"(coretennis player {player_id})",
            profile_url=profile_url,
            last_fetched_at=fetched_at,
        )

    full_name = "(coretennis player " + player_id + ")"
    first_name: str | None = None
    last_name: str | None = None
    h1 = header.find("h1")
    if isinstance(h1, Tag):
        # The H1 also contains the country flag span. Strip the (USA) text.
        raw = h1.get_text(" ", strip=True)
        # Remove a trailing "(XXX)" country code if present.
        cleaned = re.sub(r"\s*\([A-Z]{3}\)\s*$", "", raw).strip()
        # Some pages append " Results" after the name (results.html-style
        # header reuse). Strip it defensively.
        cleaned = re.sub(r"\s+Results\s*$", "", cleaned).strip()
        if cleaned:
            full_name = cleaned
            parts = cleaned.split()
            if len(parts) >= 2:
                first_name = parts[0]
                last_name = " ".join(parts[1:])
            elif parts:
                first_name = parts[0]

    gender: Gender | None = None
    age_category: str | None = None
    detail_div = header.find("div")
    # The first <div> inside ppHeader after h1 is the "Country: ..., Category: ..." line.
    # We iterate divs to find one mentioning "Category".
    for div in header.find_all("div"):
        text = div.get_text(" ", strip=True)
        if "Category" in text:
            match = _CATEGORY_RE.search(text)
            if match:
                age = match.group("age")
                gender_word = match.group("gender").capitalize()
                gender = "M" if gender_word == "Boys" else "F"
                age_category = f"{gender_word} {age}"
            break

    return Player(
        usta_id=player_id,
        full_name=full_name,
        first_name=first_name,
        last_name=last_name,
        gender=gender,
        age_category=age_category,
        profile_url=profile_url,
        last_fetched_at=fetched_at,
    )


# ---------------------------------------------------------------------------
# Results / matches
# ---------------------------------------------------------------------------


def _iter_matches(
    results_html: str,
    *,
    player_id: str,
    fetched_at: datetime,
) -> Iterable[Match]:
    """Walk the results HTML and yield one :class:`Match` per ``pprRow``."""

    soup = BeautifulSoup(results_html, "lxml")

    # Sanity-check that this is actually a CoreTennis results page. We
    # don't want to silently emit zero matches when the HTML is some
    # unrelated page.
    if not soup.find("div", class_="plTourn") and not soup.find(
        "div", class_="pprRow"
    ):
        # Could still legitimately be empty (e.g., a player with no
        # tournaments). But if no recognised structural anchors AT ALL
        # exist, that's a parse error.
        if not soup.find("div", class_="ppHeader") and not soup.find(
            "ul", id="plTournTabs"
        ):
            raise ParseError(
                "results_html does not look like a CoreTennis results page "
                "(no plTourn/pprRow/ppHeader/plTournTabs found)"
            )
        return

    # Walk the document in order, tracking the most recent year-tab seen.
    # We rely on the year-tab content divs (id="yearContent2026" etc.)
    # so that whichever order BeautifulSoup hands us elements in, we can
    # resolve a row's year by walking up to its enclosing tab div.
    plTourn_nodes = soup.find_all("div", class_="plTourn")

    for tournament_index, tourn in enumerate(plTourn_nodes):
        if not isinstance(tourn, Tag):
            continue
        try:
            yield from _parse_tournament(
                tourn,
                tournament_index=tournament_index,
                player_id=player_id,
                fetched_at=fetched_at,
            )
        except Exception:  # noqa: BLE001 — per-tournament isolation
            LOGGER.exception(
                "coretennis: failed to parse plTourn #%d for player %s",
                tournament_index,
                player_id,
            )
            continue


def _parse_tournament(
    tourn: Tag,
    *,
    tournament_index: int,
    player_id: str,
    fetched_at: datetime,
) -> Iterable[Match]:
    """Yield matches for a single ``<div class="plTourn">`` block."""

    year = _resolve_year_for(tourn)

    head = tourn.find("div", class_="pprHead")
    if not isinstance(head, Tag):
        LOGGER.warning(
            "coretennis: plTourn #%d has no pprHead, skipping", tournament_index
        )
        return

    # Date columns. The plM1 carries "Jan 17<br>Jan 19" — use the first one.
    date_div = head.find("div", class_="plM1")
    start_month_day = None
    if isinstance(date_div, Tag):
        match = _MONTH_DAY_RE.search(date_div.get_text(" ", strip=True))
        if match:
            start_month_day = (match.group(1), int(match.group(2)))

    scheduled_at: datetime | None = None
    if start_month_day and year is not None:
        month_num = _MONTH_TO_NUM.get(start_month_day[0].lower()[:3])
        if month_num is not None:
            try:
                scheduled_at = datetime(
                    year, month_num, start_month_day[1], tzinfo=UTC
                )
            except ValueError:
                scheduled_at = None

    # Header descriptor: "Tournament name - Venue, City, ST (USA) - Boys 12 - Hard"
    name_div = head.find("div", class_="plM2")
    tournament_name = ""
    surface: str | None = None
    if isinstance(name_div, Tag):
        header_text = name_div.get_text(" ", strip=True)
        # Drop the "(USA)" / country tag noise.
        header_text = re.sub(r"\s*\([A-Z]{3}\)\s*", " ", header_text)
        header_text = re.sub(r"\s+", " ", header_text).strip()
        parts = [p.strip() for p in header_text.split(" - ") if p.strip()]
        if parts:
            tournament_name = parts[0]
        if parts:
            # Surface is the trailing segment when present (Hard/Clay/Grass/Carpet).
            last = parts[-1]
            if last in {"Hard", "Clay", "Grass", "Carpet"}:
                surface = last

    draw_id = _build_draw_id(
        year=year,
        scheduled_at=scheduled_at,
        tournament_name=tournament_name,
        tournament_index=tournament_index,
    )

    # Each pprRow inside this tournament is one match.
    rows = tourn.find_all("div", class_="pprRow")
    for row_index, row in enumerate(rows):
        if not isinstance(row, Tag):
            continue
        try:
            match = _parse_row(
                row,
                draw_id=draw_id,
                scheduled_at=scheduled_at,
                surface=surface,
                player_id=player_id,
                fetched_at=fetched_at,
            )
        except Exception:  # noqa: BLE001 — per-row isolation
            LOGGER.exception(
                "coretennis: failed to parse pprRow #%d in plTourn #%d (player %s)",
                row_index,
                tournament_index,
                player_id,
            )
            continue
        if match is not None:
            yield match


def _parse_row(
    row: Tag,
    *,
    draw_id: str,
    scheduled_at: datetime | None,
    surface: str | None,
    player_id: str,
    fetched_at: datetime,
) -> Match | None:
    """Parse a single ``<div class="pprRow">`` into a :class:`Match`.

    Returns ``None`` when the row is structurally too broken to be useful
    (e.g. missing score column). The caller logs and continues.
    """

    # plM1 = round (e.g. "1/32"), plM4 (first) = W/L, plM4 (second) = "vs",
    # plM2 = opponent (anchor text + country span), plM3 = score string.
    round_div = row.find("div", class_="plM1")
    round_label: str | None = None
    if isinstance(round_div, Tag):
        round_label = round_div.get_text(" ", strip=True) or None

    plM4_divs = row.find_all("div", class_="plM4")
    wl: str | None = None
    if plM4_divs:
        first_text = plM4_divs[0].get_text(" ", strip=True).strip().upper()
        if first_text in {"W", "L"}:
            wl = first_text

    score_div = row.find("div", class_="plM3")
    if not isinstance(score_div, Tag):
        LOGGER.warning(
            "coretennis: pprRow missing plM3 score column, skipping row"
        )
        return None
    score_raw = score_div.get_text(" ", strip=True)

    # The plM2 inside pprRow is the opponent. (It's a different plM2 than
    # the one inside pprHead, but BeautifulSoup's row-scoped find handles
    # the scoping for us.)
    opponent_div = row.find("div", class_="plM2")
    # Capture name text only (strip the trailing (USA) country span).
    opponent_name: str | None = None
    if isinstance(opponent_div, Tag):
        raw = opponent_div.get_text(" ", strip=True)
        opponent_name = re.sub(r"\s*\([A-Z]{3}\)\s*$", "", raw).strip() or None

    # Parse the score: CoreTennis emits concatenated set tokens with no
    # dashes ("75 26 1210"). We rehydrate to the canonical "7-5 2-6 [10-12]"
    # form that parse_score() understands. For the 10-point match
    # tiebreak, the score is from the listed player's perspective and the
    # bracketed convention puts the winner first; if the player lost we
    # flip so that the listed digits stay "listed-player first".
    normalized_score = _normalize_score(score_raw, player_lost=wl == "L")
    sets, score_outcome, _residual = parse_score(normalized_score)

    # Map CoreTennis row outcome -> our MatchOutcome literal. Note: the
    # Match model does not have "won"/"lost"; W/L is carried by winner_id.
    # See module docstring.
    outcome = score_outcome
    if outcome == "completed" and not sets:
        outcome = "unfinished"

    winner_id: str | None = None
    if wl == "W":
        winner_id = player_id
    elif wl == "L":
        # Opponent's stable id isn't on this page; leave winner_id None.
        winner_id = None
    else:
        # No W/L marker — try to infer from sets.
        winner_id = infer_winner(sets, player_id, None, outcome)

    # We attach the opponent name as a structured comment via score_raw —
    # we keep the original raw score (not the normalized one) so the
    # captured fixture is faithful. The opponent name itself isn't stored
    # on the Match model; recon will fuzzy-match it to an existing player
    # later.
    _ = opponent_name  # noqa: F841 — referenced for documentation/tests

    return Match(
        usta_id=None,
        draw_id=draw_id,
        round=round_label,
        scheduled_at=scheduled_at,
        court=surface,
        player_a_id=player_id,
        player_b_id=None,
        score_raw=score_raw or None,
        sets=sets,
        outcome=outcome,
        winner_id=winner_id,
        last_fetched_at=fetched_at,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_year_for(tourn: Tag) -> int | None:
    """Walk up the DOM to find the enclosing ``yearContentNNNN`` div."""

    parent: Tag | None = tourn
    while parent is not None:
        elem_id = parent.get("id") if isinstance(parent, Tag) else None
        if isinstance(elem_id, str):
            match = _YEAR_REL_RE.match(elem_id)
            if match:
                return int(match.group(1))
        next_parent = parent.parent
        if not isinstance(next_parent, Tag):
            return None
        parent = next_parent
    return None


def _build_draw_id(
    *,
    year: int | None,
    scheduled_at: datetime | None,
    tournament_name: str,
    tournament_index: int,
) -> str:
    """Build a deterministic CoreTennis draw id.

    CoreTennis doesn't expose a tournament id on the results page (only
    on the tournament-rounds page, which is a separate fetch), so we
    derive a stable composite key from (year, MM-DD, slug-of-name). When
    we can't resolve a date or name, we fall back to the row index so
    that two unparseable rows don't collide on the same key.
    """

    date_part = "noyear"
    if scheduled_at is not None:
        date_part = scheduled_at.strftime("%Y-%m-%d")
    elif year is not None:
        date_part = str(year)

    slug = _slugify(tournament_name) or f"row-{tournament_index}"
    return f"coretennis:{date_part}:{slug}"


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return cleaned[:80]


def _normalize_score(score_raw: str, *, player_lost: bool) -> str:
    """Rehydrate ``"75 26 1210"`` -> ``"7-5 2-6 [10-12]"`` for parse_score().

    CoreTennis writes each set's games as two concatenated digits with no
    dash. A "1210" token represents a 10-point match tiebreak; we render
    it as ``[10-12]`` when the listed player lost it and ``[12-10]``
    otherwise. Set-tiebreak scores (``"76(3)"``) carry a parenthesized
    losers' point count that we preserve verbatim.

    Any unrecognised token is passed through to parse_score() unchanged,
    which will treat it as residual.
    """

    if not score_raw:
        return ""

    out: list[str] = []
    for token in score_raw.strip().split():
        normalized = _normalize_token(token, player_lost=player_lost)
        out.append(normalized)
    return " ".join(out)


def _normalize_token(token: str, *, player_lost: bool) -> str:
    """Normalise a single concatenated-digit set token to dashed form."""

    # Match tiebreak: 3-4 digit token with leading "10" or "12" etc, e.g.
    # "1210" (one side reached 12, other 10), "107" (10-7), "1086" — we
    # treat any token of length >=3 starting with "10"-"19" as a match
    # tiebreak. Format: first 2 chars = winning side points if >=10, else
    # we split greedily.
    tiebreak_paren_match = re.match(r"^(\d{1,2})(\d{1,2})\((\d+)\)$", token)
    if tiebreak_paren_match:
        a = int(tiebreak_paren_match.group(1))
        b = int(tiebreak_paren_match.group(2))
        loser_pts = tiebreak_paren_match.group(3)
        return f"{a}-{b}({loser_pts})"

    if len(token) >= 3 and token.isdigit():
        # Try to split: greedily, the *higher* of the two scores is the
        # winning side; in CoreTennis the listed player's score comes
        # first. Examples seen: "1210" -> 12,10; "1086" -> 10,8 then trailing
        # "6"? No — actually "107" -> 10-7, "1210" -> 12-10. So we
        # always parse as (first-2-digits, remaining) when first 2 digits
        # form a number >= 10, else (first-1-digit, remaining).
        if int(token[:2]) >= 10:
            a_str, b_str = token[:2], token[2:]
        else:
            a_str, b_str = token[:1], token[1:]
        try:
            a = int(a_str)
            b = int(b_str)
        except ValueError:
            return token
        # Encode as a bracketed match tiebreak: the convention in
        # parse_score is "[winner-loser]". The listed player's score is
        # `a`; if the listed player LOST the match, then `a` is the
        # loser's count and we emit "[b-a]" to keep winner-first.
        if player_lost:
            return f"[{b}-{a}]"
        return f"[{a}-{b}]"

    # Plain 2-digit set token: "75" -> "7-5". 1-digit-per-side only.
    if len(token) == 2 and token.isdigit():
        return f"{token[0]}-{token[1]}"

    # Already-dashed or unknown shape: hand off to parse_score as-is.
    return token
