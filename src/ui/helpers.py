"""UI helpers shared by route handlers and Jinja templates.

These functions are pure (no IO, no global state) and are unit-testable
through the route handlers themselves. They live separate from ``app.py`` so
that the route bodies read as orchestration, not arithmetic.

Two responsibilities here:

1. Resolve the "user" player record. ``USTA_USER_PLAYER_ID`` from settings is
   authoritative; when unset (typical in dev / synthetic seeding) we fall back
   to the first player whose ``usta_id`` starts with the synthetic Janav
   prefix written by ``scripts/seed_dev_data.py``.
2. Small classifiers used by templates: a WTN tier label
   (elite / strong / club / developing) used to color-code the dashboard
   chips, a coarse "synthetic-data" detector for the footer badge, and a
   days-until helper that gracefully handles ``None`` start dates.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Literal

from bs4 import BeautifulSoup, Tag

from src.models.player import Player
from src.store.repositories import PlayerRepository

# Synthetic-data prefixes are the seeder's contract with the UI: any player ID
# starting with one of these is a fixture, not real USTA data. Janav's own
# player row is keyed by his real Clubspark GUID (recovered via WebSearch on
# 2026-05-10) so the row's primary key already aligns with what residential
# Clubspark egress would return; everything *around* him (opponents, draws,
# matches) is still synthetic until real Clubspark data is reachable.
# The footer badge surfaces this so a viewer never confuses a demo run with
# reality.
SYNTHETIC_PREFIXES: tuple[str, ...] = (
    "OPP-SYNTHETIC",
    "T-SYNTH",
    "D-SYNTH",
    "M-SYNTH",
)
JANAV_REAL_USTA_ID = "971BA48D-A2EA-4FB7-8305-F42EA466F6DF"

WtnTier = Literal["elite", "strong", "club", "developing", "unrated"]


def wtn_tier(value: float | None) -> WtnTier:
    """Bucket a WTN value (1.0 strongest, 40.0 weakest) into a coarse tier.

    Boundaries chosen for a junior audience: under 15 is genuinely strong,
    15-25 is competitive sectional, 25-35 is club level, above that is
    developing. ``None`` returns the ``unrated`` tier so templates can render
    a neutral chip without a special case.
    """
    if value is None:
        return "unrated"
    if value <= 15.0:
        return "elite"
    if value <= 25.0:
        return "strong"
    if value <= 35.0:
        return "club"
    return "developing"


def days_until(d: date | None, today: date | None = None) -> int | None:
    """Days from ``today`` (or :func:`date.today`) until ``d``.

    Returns ``None`` when ``d`` is ``None`` so templates can render "TBD"
    without an ``if`` ladder. A negative result is preserved (the tournament
    is in the past) — callers decide whether to surface it.
    """
    if d is None:
        return None
    base = today or date.today()
    return (d - base).days


def resolve_user_player(conn: sqlite3.Connection, configured_id: str) -> Player | None:
    """Pick the player whose dashboard this is.

    Precedence:

    1. ``USTA_USER_PLAYER_ID`` from settings, if it resolves to a real row.
    2. Janav's real Clubspark GUID — the canonical seeded fallback.
    3. ``None`` — the dashboard then renders its empty state.
    """
    repo = PlayerRepository(conn)
    if configured_id:
        hit = repo.get(configured_id)
        if hit is not None:
            return hit

    return repo.get(JANAV_REAL_USTA_ID)


def db_has_synthetic_data(conn: sqlite3.Connection) -> bool:
    """True iff at least one player ID matches a synthetic prefix.

    Used by ``base.html`` to display the "synthetic data" footer badge so a
    viewer knows the dashboard is running on seeded fixtures.
    """
    for prefix in SYNTHETIC_PREFIXES:
        row = conn.execute(
            "SELECT 1 FROM players WHERE usta_id LIKE ? || '%' LIMIT 1",
            (prefix,),
        ).fetchone()
        if row is not None:
            return True
    return False


def format_record(wins: int, losses: int) -> str:
    """Render a W-L record. ``0-0`` becomes ``--`` to avoid noise on empty form."""
    if wins == 0 and losses == 0:
        return "--"
    return f"{wins}-{losses}"


# ---------------------------------------------------------------------------
# Rankings-page support
# ---------------------------------------------------------------------------
#
# The /rankings page renders match rows that need a tournament name and
# opponent name — fields that ``parse_coretennis_player`` does not surface
# directly (it folds the tournament name into ``draw_id`` and discards the
# opponent name). Rather than touch the parser (out of scope for the UI
# work), we do a tiny supplemental parse here over the same fixture.
#
# This is intentionally narrow: the parser is the authoritative source for
# match shape (sets, scheduled_at, winner_id). We only enrich those rows
# with two display strings.


_FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "tests"
    / "fixtures"
    / "coretennis"
)

# Year-tab divs wrap each year's tournaments.
_YEAR_DIV_RE = re.compile(r"yearContent(\d{4})")
_MONTH_DAY_RE = re.compile(r"([A-Za-z]{3})\s+(\d{1,2})")


def coretennis_match_rows(results_html: str) -> list[dict[str, str | None]]:
    """Extract display-only metadata for each ``pprRow`` in a results page.

    Returns a list of dicts (one per match, in DOM order) containing:

    - ``date``: human-readable date like "Jan 17, 2026"
    - ``tournament``: e.g. "USTA National Level 3 Tournament"
    - ``venue``: e.g. "Saddlebrook Tennis Resort, Wesley Chapel, FL"
    - ``round``: e.g. "1/32"
    - ``opponent``: e.g. "Gustavo Lipinski"
    - ``score``: normalised display string like "7-5 2-6 [10-12]"
    - ``result``: ``"W"`` or ``"L"`` (the listed player's outcome)

    Robust to a malformed row by skipping it. Empty/garbage HTML returns
    an empty list — the template falls through to a friendly empty state.
    """

    if not results_html or not results_html.strip():
        return []
    soup = BeautifulSoup(results_html, "lxml")

    rows: list[dict[str, str | None]] = []
    for tourn in soup.find_all("div", class_="plTourn"):
        if not isinstance(tourn, Tag):
            continue
        # Resolve year from the enclosing yearContentNNNN div.
        year: int | None = None
        parent: Tag | None = tourn
        while parent is not None:
            elem_id = parent.get("id") if isinstance(parent, Tag) else None
            if isinstance(elem_id, str):
                m = _YEAR_DIV_RE.match(elem_id)
                if m:
                    year = int(m.group(1))
                    break
            next_parent = parent.parent
            parent = next_parent if isinstance(next_parent, Tag) else None

        head = tourn.find("div", class_="pprHead")
        if not isinstance(head, Tag):
            continue

        # Date (start day only — the row also lists an end day on a 2nd line).
        date_div = head.find("div", class_="plM1")
        date_label: str | None = None
        if isinstance(date_div, Tag):
            txt = date_div.get_text(" ", strip=True)
            m = _MONTH_DAY_RE.search(txt)
            if m and year is not None:
                date_label = f"{m.group(1)} {int(m.group(2))}, {year}"
            elif m:
                date_label = f"{m.group(1)} {int(m.group(2))}"

        # Header descriptor — first plM2 inside pprHead.
        head_name_div = head.find("div", class_="plM2")
        tournament_name = ""
        venue_text = ""
        if isinstance(head_name_div, Tag):
            raw = head_name_div.get_text(" ", strip=True)
            raw = re.sub(r"\s*\([A-Z]{3}\)\s*", " ", raw)
            raw = re.sub(r"\s+", " ", raw).strip()
            # Format: "Tournament name - Venue, City, ST - Boys 12 - Hard"
            parts = [p.strip() for p in raw.split(" - ") if p.strip()]
            if parts:
                tournament_name = parts[0]
            if len(parts) >= 2:
                venue_text = parts[1]

        # Each pprRow inside this tournament is a match.
        for row in tourn.find_all("div", class_="pprRow"):
            if not isinstance(row, Tag):
                continue
            round_div = row.find("div", class_="plM1")
            round_label = (
                round_div.get_text(" ", strip=True)
                if isinstance(round_div, Tag)
                else None
            )

            wl: str | None = None
            for m4 in row.find_all("div", class_="plM4"):
                txt = m4.get_text(" ", strip=True).strip().upper()
                if txt in {"W", "L"}:
                    wl = txt
                    break

            opp_div = row.find("div", class_="plM2")
            opponent = None
            if isinstance(opp_div, Tag):
                raw = opp_div.get_text(" ", strip=True)
                opponent = re.sub(r"\s*\([A-Z]{3}\)\s*$", "", raw).strip() or None

            score_div = row.find("div", class_="plM3")
            if not isinstance(score_div, Tag):
                continue
            raw_score = score_div.get_text(" ", strip=True)
            display_score = _humanise_score(raw_score, player_lost=wl == "L")

            rows.append(
                {
                    "date": date_label,
                    "tournament": tournament_name or None,
                    "venue": venue_text or None,
                    "round": round_label,
                    "opponent": opponent,
                    "score": display_score,
                    "result": wl,
                }
            )
    return rows


def _humanise_score(raw: str, *, player_lost: bool) -> str:
    """Rehydrate "75 26 1210" into "7-5 2-6 [10-12]" for display.

    Mirrors the parser's normalisation but emits the bracketed form the
    template uses (square brackets around the match tiebreak). Unknown
    tokens are returned as-is so we never lose data — recon can clean up
    odd shapes later.
    """
    if not raw:
        return ""
    out: list[str] = []
    for token in raw.strip().split():
        if not token.isdigit():
            out.append(token)
            continue
        if len(token) == 2:
            out.append(f"{token[0]}-{token[1]}")
        elif len(token) >= 3:
            if int(token[:2]) >= 10:
                a, b = int(token[:2]), int(token[2:])
            else:
                a, b = int(token[:1]), int(token[1:])
            # Bracket-format the match tiebreak: convention is winner-first.
            # If the listed player lost the row, flip so listed-player digits
            # stay first in the rendered "[a-b]".
            if player_lost:
                out.append(f"[{b}-{a}]")
            else:
                out.append(f"[{a}-{b}]")
        else:
            out.append(token)
    return " ".join(out)


def load_rankings_context(*, live_data: bool = False) -> dict[str, Any]:
    """Build the context dict consumed by ``rankings.html``.

    Currently sources match data from the captured CoreTennis fixture
    (``tests/fixtures/coretennis/janav_results.html``). When ``live_data``
    is true a live CoreTennis fetch would go here — we leave a TODO marker
    and fall through to the fixture so the page always renders.

    Returned keys mirror the template's expectations: ``player_meta`` for
    the hero, ``rankings`` for the cross-platform strip, ``identifiers``
    for the ID card, ``matches`` for the results table, ``sister`` for the
    family-context block, and ``data_state`` for the data-sources footer.
    """

    player_meta = {
        "full_name": "Janav Thasen",
        "age_category": "Boys 12s",
        "section": "Florida",
        "district": "Broward County",
        "city": "Weston, FL",
        "class_of": 2032,
    }

    # Cross-platform rankings strip. Source labels are load-bearing — the
    # whole point of this UI is to show provenance, not just numbers.
    rankings = [
        {
            "label": "TennisRecruiting",
            "value": "146",
            "sub": "TR composite, US national (Boys class of 2032)",
            "source": "tennisrecruiting.net",
            "freshness": "2026-05-11 (manual capture)",
        },
        {
            "label": "CoreTennis",
            "value": "active",
            "sub": "Live profile, 4 tournaments tracked",
            "source": "coretennis.net",
            "freshness": "fixture 2026-05-11 03:08 UTC",
        },
        {
            "label": "USTA national",
            "value": "pending",
            "sub": "Auth-walled — see DEPLOY.md open lead",
            "source": "playtennis.usta.com",
            "freshness": "Akamai gate, not yet captured",
        },
        {
            "label": "UTR",
            "value": "3059480",
            "sub": "UTR ID, numeric rating gated",
            "source": "myutr.com",
            "freshness": "ID confirmed, rating fetch pending",
        },
    ]

    identifiers = [
        {
            "label": "Clubspark / USTA GUID",
            "value": "971BA48D-A2EA-4FB7-8305-F42EA466F6DF",
            "href": None,
        },
        {
            "label": "CoreTennis ID",
            "value": "203938 (janav-thasen)",
            "href": "https://www.coretennis.net/tennis-player/janav-thasen/203938/profile.html",
        },
        {
            "label": "UTR ID",
            "value": "3059480",
            "href": "https://app.utrsports.net/profiles/3059480",
        },
        {
            "label": "TennisRecruiting ID",
            "value": "1065914",
            "href": None,
        },
        {
            "label": "USTA Play Tennis (search)",
            "value": "Janav Thasen / Weston FL",
            "href": "https://playtennis.usta.com/",
        },
    ]

    matches: list[dict[str, Any]] = []
    coretennis_state = "fixture"
    results_html: str | None = None
    profile_html: str | None = None
    fixture_results = _FIXTURE_DIR / "janav_results.html"
    fixture_profile = _FIXTURE_DIR / "janav_profile.html"

    if live_data:
        # TODO: wire CoreTennisClient.get_profile/get_results here with a
        # short timeout and explicit error handling. For now we mark intent
        # but fall through to the fixture so the page always renders.
        coretennis_state = "live attempted (not yet wired) — using fixture"

    if fixture_results.exists():
        try:
            results_html = fixture_results.read_text(encoding="utf-8")
        except OSError:
            results_html = None
    if fixture_profile.exists():
        try:
            profile_html = fixture_profile.read_text(encoding="utf-8")
        except OSError:
            profile_html = None

    if results_html:
        try:
            matches = coretennis_match_rows(results_html)
        except Exception:
            matches = []

    sister = {
        "full_name": "Vihana Thasen",
        "relation": "Sister",
        "coretennis_id": "192850",
        "tennisrecruiting_id": "1020714",
        "wtn_singles": 27.97,
        "wtn_doubles": 31.55,
        "wtn_singles_confidence": 100,
        "wtn_doubles_confidence": 100,
        "wtn_source": "Bright Data + ITF GraphQL",
        "wtn_freshness": "2026-05-11 recon (wtn-prod-thasen-search-v2.json)",
    }

    data_state = {
        "coretennis_state": coretennis_state,
        "profile_loaded": bool(profile_html),
        "results_loaded": bool(results_html),
        "live_attempted": live_data,
        "live_sources": [
            {"name": "CoreTennis profile + results", "status": "live (fixture mirrored)"},
            {"name": "UTR ID lookup", "status": "live (rating gated)"},
            {"name": "USTA Play Tennis AWS API", "status": "live (tournament discovery)"},
            {"name": "WTN via Bright Data + ITF GraphQL", "status": "live (sister data)"},
        ],
        "gated_sources": [
            {
                "name": "USTA modern rankings (playtennis.usta.com)",
                "status": "Akamai auth-walled — open lead documented in DEPLOY.md",
            },
        ],
    }

    return {
        "player_meta": player_meta,
        "rankings": rankings,
        "identifiers": identifiers,
        "matches": matches,
        "sister": sister,
        "data_state": data_state,
    }


__all__ = [
    "SYNTHETIC_PREFIXES",
    "WtnTier",
    "coretennis_match_rows",
    "days_until",
    "db_has_synthetic_data",
    "format_record",
    "load_rankings_context",
    "resolve_user_player",
    "wtn_tier",
]
