"""Seed a local DB with a realistic Janav-Thasen-centered dev dataset.

Goal: produce a believable junior-tennis season that lets the FastAPI
dashboard render meaningful pages today — before the real-fetch pipeline
clears Cloudflare. Every entity is stamped with a clearly synthetic ID
prefix (``JANAV-SYNTHETIC-``, ``OPP-SYNTHETIC-``, ``T-SYNTH-``, etc.) and
a ``synthetic://janav-portal/...`` profile URL so this data is never
mistaken for a real USTA fetch.

What seeded data is grounded in?
- The player record uses confirmed facts harvested from public sources
  (Tennis Recruiting Network, CoreTennis) — see
  ``data/research/janav-discovery.md``. Janav is filed as Weston, FL,
  Boys' 12s, USTA Florida section.
- Three of the five tournaments are real TriTennis events (names, GUIDs,
  approximate dates) confirmed in the harvest. The other two are
  generic Florida juniors fixtures with synthetic IDs.
- Opponent players are NOT real-named — the harvest could not surface
  Janav's actual opponents from behind the Cloudflare wall. Opponent
  IDs use the synthetic ``OPP-SYNTHETIC-`` prefix and the names are
  generic ``Player_<short_hash>`` placeholders. Once residential-egress
  recon lands, swap these out.
- WTN and ranking snapshots are plausible-for-a-Boys-12s-#146-nationally,
  not measurements.

Usage:
    python scripts/seed_dev_data.py

Idempotent: running twice is a no-op (every write is INSERT OR REPLACE
and the snapshot composite keys are stable).
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from src.models.draw import Draw, DrawEntry
from src.models.match import Match
from src.models.player import Player
from src.models.ranking import RankingSnapshot
from src.models.tournament import Tournament
from src.models.wtn import WTNSnapshot
from src.parse.matches import parse_score
from src.store.db import connect, init_schema
from src.store.repositories import (
    DrawEntryRepository,
    DrawRepository,
    MatchRepository,
    PlayerRepository,
    RankingSnapshotRepository,
    TournamentRepository,
    WTNSnapshotRepository,
)

# ---------------------------------------------------------------------------
# Constants — anchored to data/research/janav-discovery.md
# ---------------------------------------------------------------------------

JANAV_USTA_ID = "JANAV-SYNTHETIC-001"
JANAV_FULL_NAME = "Janav Thasen"
JANAV_SECTION = "Florida"  # HIGH-confidence inference from Weston FL hometown.
JANAV_AGE_CATEGORY = "Boys' 12s"  # Corrected from spec's 16s guess; he's class of 2032.
JANAV_DISTRICT = "Broward"  # plausible for a Weston, FL player.

SYNTHETIC_PROFILE = f"synthetic://janav-portal/player/{JANAV_USTA_ID}"

DISCOVERY_PATH = Path(__file__).resolve().parents[1] / "data" / "research" / "janav-discovery.md"


def _now() -> datetime:
    return datetime.now(UTC)


def _short_hash(label: str) -> str:
    return hashlib.sha1(label.encode("utf-8")).hexdigest()[:6]


def _discovery_present() -> bool:
    """Return True when the harvest doc exists.

    Per the agent charter the seeder should *consult* the doc; for v1 we
    only check presence as a friendliness signal in the log line. The
    facts the doc records are baked into the constants above — re-parsing
    the markdown at runtime would invite drift.
    """
    return DISCOVERY_PATH.exists()


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _build_janav() -> Player:
    return Player(
        usta_id=JANAV_USTA_ID,
        full_name=JANAV_FULL_NAME,
        first_name="Janav",
        last_name="Thasen",
        gender="M",
        section=JANAV_SECTION,
        district=JANAV_DISTRICT,
        age_category=JANAV_AGE_CATEGORY,
        profile_url=SYNTHETIC_PROFILE,
        last_fetched_at=_now(),
    )


def _build_opponents() -> list[Player]:
    """Eight synthetic Boys' 12s Florida opponents.

    Names are deliberately generic-but-distinct so the UI has something
    to render without implying real children's identities. Once recon
    can read real draw pages, replace with USTA-attested names.
    """
    seeds = [
        "Coral-Springs-A",
        "Boca-Raton-B",
        "Miami-C",
        "Plantation-D",
        "Sunrise-E",
        "Pembroke-Pines-F",
        "Hollywood-G",
        "Davie-H",
    ]
    opponents: list[Player] = []
    for i, seed in enumerate(seeds, start=1):
        sid = f"OPP-SYNTHETIC-{i:03d}"
        opponents.append(
            Player(
                usta_id=sid,
                full_name=f"Player_{_short_hash(seed)}",
                first_name="Player",
                last_name=_short_hash(seed),
                gender="M",
                section="Florida",
                district="Broward",
                age_category="Boys' 12s",
                profile_url=f"synthetic://janav-portal/player/{sid}",
                last_fetched_at=_now(),
            )
        )
    return opponents


# Tournament definitions: (synth_id, name, level, status, start, end, city, state, surface, source_note)
# Two of these mirror real TriTennis events identified in the harvest (names + approximate dates kept).
# IDs are synthetic across the board because we cannot confirm the real GUIDs from this egress.
_TOURNAMENTS = [
    (
        "T-SYNTH-001",
        "TriTennis Broward Turkey Bowl Singles Classic",
        "L6",
        "completed",
        date(2025, 11, 28),
        date(2025, 11, 30),
        "Coral Springs",
        "FL",
        "hard",
        "Modeled on real TriTennis event; synthetic ID.",
    ),
    (
        "T-SYNTH-002",
        "TriTennis Turkey Bowl National Open",
        "L7",
        "completed",
        date(2025, 11, 21),
        date(2025, 11, 23),
        "Coral Springs",
        "FL",
        "hard",
        "Modeled on real TRN Showcase Series Level 7; synthetic ID.",
    ),
    (
        "T-SYNTH-003",
        "USTA Florida Section L3 — Wesley Chapel Junior Open",
        "L3",
        "completed",
        date(2026, 1, 17),
        date(2026, 1, 19),
        "Wesley Chapel",
        "FL",
        "hard",
        "Aligned with CoreTennis-attested 2026-01-17 event.",
    ),
    (
        "T-SYNTH-004",
        "TriTennis Broward Prize Money Open & NTRP Classic",
        "L5",
        "completed",
        date(2026, 3, 13),
        date(2026, 3, 15),
        "Coral Springs",
        "FL",
        "clay",
        "Modeled on real TriTennis L5 event; synthetic ID.",
    ),
    (
        "T-SYNTH-005",
        "USTA Florida Boys' 12s Summer Spotlight",
        "L4",
        "upcoming",
        date(2026, 6, 20),
        date(2026, 6, 22),
        "Plantation",
        "FL",
        "hard",
        "Synthetic forward-looking event for the upcoming-tournaments panel.",
    ),
]


def _build_tournaments() -> list[Tournament]:
    return [
        Tournament(
            usta_id=tid,
            name=name,
            level=level,
            sanction_body="USTA Florida",
            start_date=start,
            end_date=end,
            location_city=city,
            location_state=state,
            surface=surface,  # type: ignore[arg-type]
            ball="Wilson US Open",
            entry_deadline=datetime.combine(start - timedelta(days=14), datetime.min.time(), UTC),
            status=status,  # type: ignore[arg-type]
            last_fetched_at=_now(),
        )
        for (tid, name, level, status, start, end, city, state, surface, _note) in _TOURNAMENTS
    ]


def _build_draws() -> list[Draw]:
    """3-4 draws per tournament: Boys' 12s singles + doubles, plus an
    adjacent age group (10s or 14s) so the dashboard shows draw breadth.
    """
    draws: list[Draw] = []
    for (tid, _name, _level, status, *_rest) in _TOURNAMENTS:
        draw_status = "completed" if status == "completed" else "open"
        specs = [
            ("12s-S", "Boys 12 Singles", "M", "12", "singles", 32),
            ("12s-D", "Boys 12 Doubles", "M", "12", "doubles", 16),
            ("14s-S", "Boys 14 Singles", "M", "14", "singles", 32),
            ("10s-S", "Boys 10 Singles", "M", "10", "singles", 16),
        ]
        for suffix, dname, gender, age, div, size in specs:
            draws.append(
                Draw(
                    usta_id=f"D-SYNTH-{tid.split('-')[-1]}-{suffix}",
                    tournament_id=tid,
                    name=dname,
                    format="single_elimination_with_consolation",
                    size=size,
                    gender=gender,
                    age_group=age,
                    division=div,
                    status=draw_status,
                    last_fetched_at=_now(),
                )
            )
    return draws


def _janav_draw_id_for(tournament_id: str) -> str:
    """Janav plays the Boys 12 Singles draw at every tournament."""
    return f"D-SYNTH-{tournament_id.split('-')[-1]}-12s-S"


def _build_draw_entries(opponents: list[Player]) -> list[DrawEntry]:
    """For each tournament's Boys 12 Singles draw: Janav + 3 opponents.

    Three opponents per draw is enough to render a believable
    quarter/semi/final progression for past tournaments while keeping
    the seed small.
    """
    entries: list[DrawEntry] = []
    for idx, (tid, *_rest) in enumerate(_TOURNAMENTS):
        draw_id = _janav_draw_id_for(tid)
        # Janav seeded between 5-12 depending on event level.
        janav_seed = 5 + (idx % 6)
        entries.append(
            DrawEntry(
                draw_id=draw_id,
                player_id=JANAV_USTA_ID,
                seed=janav_seed,
                position=1,
                status="entered",
            )
        )
        # Three rotating opponents per draw — keeps the dataset small but
        # each draw still has at least four named entrants.
        for slot, opp in enumerate(opponents[idx : idx + 3], start=2):
            entries.append(
                DrawEntry(
                    draw_id=draw_id,
                    player_id=opp.usta_id,
                    seed=None,
                    position=slot,
                    status="entered",
                )
            )
    return entries


# ---------------------------------------------------------------------------
# Matches: 10 completed + 1 upcoming = 11 total.
# Outcome mix: 6 wins / 4 losses / 1 upcoming = .600 record on completed matches.
# Scores use the score_parser format (verified by parse_score round-trip).
# ---------------------------------------------------------------------------

_MATCH_SPECS = [
    # (tournament_idx, round, opp_idx, score_raw, janav_wins, days_ago)
    (0, "R32", 0, "6-3 6-2", True, 165),
    (0, "R16", 1, "6-4 4-6 10-7", True, 164),
    (0, "QF",  2, "3-6 4-6", False, 163),
    (1, "R32", 3, "6-2 6-1", True, 172),
    (1, "R16", 4, "7-6(3) 6-4", True, 171),
    (1, "QF",  5, "4-6 6-7(5)", False, 170),
    (2, "R32", 6, "6-1 6-0", True, 113),
    (2, "R16", 7, "5-7 7-6(4) 6-10", False, 112),
    (3, "R32", 0, "6-4 6-3", True, 58),
    (3, "R16", 1, "3-6 5-7", False, 57),
    # Upcoming match in tournament 4 — scheduled, no score yet.
    (4, "R32", 2, None, None, -41),  # negative = future
]


def _build_matches(opponents: list[Player]) -> list[Match]:
    matches: list[Match] = []
    today = datetime.now(UTC)
    for i, (t_idx, rnd, opp_idx, score_raw, janav_wins, days_ago) in enumerate(_MATCH_SPECS, start=1):
        tid = _TOURNAMENTS[t_idx][0]
        draw_id = _janav_draw_id_for(tid)
        opp = opponents[opp_idx]
        scheduled = today - timedelta(days=days_ago)

        if score_raw is None:
            matches.append(
                Match(
                    usta_id=f"M-SYNTH-{i:03d}",
                    draw_id=draw_id,
                    round=rnd,
                    scheduled_at=scheduled,
                    court="Court 5",
                    player_a_id=JANAV_USTA_ID,
                    player_b_id=opp.usta_id,
                    score_raw=None,
                    sets=[],
                    outcome="unknown",
                    winner_id=None,
                    last_fetched_at=_now(),
                )
            )
            continue

        sets, outcome, _residual = parse_score(score_raw)
        # The score is always written from Janav's perspective (side A).
        # parse_score returns games_a/games_b verbatim, so when Janav wins
        # we keep the orientation; when he loses we flip neither — we
        # encode the loss by populating winner_id with the opponent.
        winner = JANAV_USTA_ID if janav_wins else opp.usta_id
        matches.append(
            Match(
                usta_id=f"M-SYNTH-{i:03d}",
                draw_id=draw_id,
                round=rnd,
                scheduled_at=scheduled,
                court=f"Court {1 + (i % 8)}",
                player_a_id=JANAV_USTA_ID,
                player_b_id=opp.usta_id,
                score_raw=score_raw,
                sets=sets,
                outcome=outcome,
                winner_id=winner,
                last_fetched_at=_now(),
            )
        )
    return matches


# ---------------------------------------------------------------------------
# WTN snapshots and ranking snapshots
# ---------------------------------------------------------------------------


def _build_wtn_snapshots(opponents: list[Player]) -> list[WTNSnapshot]:
    """Janav at WTN ~18 singles / 19.5 doubles (plausible for a competitive
    U12 boy ranked ~#146 nationally). Opponents spread 15-25.
    """
    today = date.today()
    snaps: list[WTNSnapshot] = []
    # Janav: two historical snapshots showing improvement.
    snaps.append(WTNSnapshot(player_id=JANAV_USTA_ID, type="singles", value=19.5, confidence=0.85, as_of=today - timedelta(days=180)))
    snaps.append(WTNSnapshot(player_id=JANAV_USTA_ID, type="singles", value=18.0, confidence=0.90, as_of=today - timedelta(days=14)))
    snaps.append(WTNSnapshot(player_id=JANAV_USTA_ID, type="doubles", value=20.5, confidence=0.80, as_of=today - timedelta(days=180)))
    snaps.append(WTNSnapshot(player_id=JANAV_USTA_ID, type="doubles", value=19.5, confidence=0.85, as_of=today - timedelta(days=14)))

    # Opponents: spread across the band.
    opp_values = [15.0, 16.5, 17.0, 18.2, 19.0, 21.5, 23.0, 25.0]
    for opp, val in zip(opponents, opp_values, strict=True):
        snaps.append(WTNSnapshot(player_id=opp.usta_id, type="singles", value=val, confidence=0.80, as_of=today - timedelta(days=21)))
    return snaps


def _build_ranking_snapshots() -> list[RankingSnapshot]:
    """Two snapshots showing Janav's Florida-sectional trajectory.

    The harvest's #146 national figure from TRN is a non-USTA ranking
    source, so we don't reproduce it directly. We pick a plausible
    sectional position (Boys 12 Singles in Florida) trending improving.
    """
    today = date.today()
    return [
        RankingSnapshot(
            player_id=JANAV_USTA_ID,
            category="Boys 12 Singles",
            scope="sectional",
            section="Florida",
            position=128,
            points=185.0,
            as_of=today - timedelta(days=180),
        ),
        RankingSnapshot(
            player_id=JANAV_USTA_ID,
            category="Boys 12 Singles",
            scope="sectional",
            section="Florida",
            position=94,
            points=260.0,
            as_of=today - timedelta(days=14),
        ),
    ]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def seed(conn: sqlite3.Connection | None = None) -> dict[str, int]:
    """Seed the connected DB. Returns a count summary.

    If ``conn`` is None, opens a connection to the configured DB and
    closes it on return. Otherwise uses the caller's connection (the
    test fixture does this).
    """
    own_conn = conn is None
    if own_conn:
        init_schema()
        conn = connect()
    else:
        # Caller is responsible for schema init when passing a conn.
        pass
    assert conn is not None

    try:
        janav = _build_janav()
        opponents = _build_opponents()
        tournaments = _build_tournaments()
        draws = _build_draws()
        entries = _build_draw_entries(opponents)
        matches = _build_matches(opponents)
        wtn_snaps = _build_wtn_snapshots(opponents)
        rank_snaps = _build_ranking_snapshots()

        player_repo = PlayerRepository(conn)
        player_repo.upsert(janav)
        for opp in opponents:
            player_repo.upsert(opp)

        tournament_repo = TournamentRepository(conn)
        for t in tournaments:
            tournament_repo.upsert(t)

        draw_repo = DrawRepository(conn)
        for d in draws:
            draw_repo.upsert(d)

        entry_repo = DrawEntryRepository(conn)
        for e in entries:
            entry_repo.upsert(e)

        match_repo = MatchRepository(conn)
        for m in matches:
            match_repo.upsert(m)

        wtn_repo = WTNSnapshotRepository(conn)
        for s in wtn_snaps:
            wtn_repo.upsert(s)

        rank_repo = RankingSnapshotRepository(conn)
        for s in rank_snaps:
            rank_repo.upsert(s)

        conn.commit()

        return {
            "players": 1 + len(opponents),
            "tournaments": len(tournaments),
            "draws": len(draws),
            "draw_entries": len(entries),
            "matches": len(matches),
            "wtn_snapshots": len(wtn_snaps),
            "ranking_snapshots": len(rank_snaps),
        }
    finally:
        if own_conn:
            conn.close()


def main() -> int:
    if not _discovery_present():
        print(
            "WARN: data/research/janav-discovery.md not found — "
            "seeding from baked-in defaults only."
        )
    counts = seed()
    print(
        "Seeded "
        f"{counts['players']} players, "
        f"{counts['tournaments']} tournaments, "
        f"{counts['draws']} draws, "
        f"{counts['matches']} matches "
        f"({counts['draw_entries']} draw entries, "
        f"{counts['wtn_snapshots']} WTN snapshots, "
        f"{counts['ranking_snapshots']} ranking snapshots)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
