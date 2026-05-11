"""Seed a local DB anchored on Janav Thasen's REAL CoreTennis match data.

The seeder produces a tight, realistic SQLite snapshot that lets the FastAPI
dashboard render meaningful pages today without depending on the live USTA
fetch pipeline. Every row is grounded in data the project already has on
disk:

1. Janav's player row uses his real Clubspark USTA GUID
   (``971BA48D-A2EA-4FB7-8305-F42EA466F6DF``) and the facts attested by
   ``tests/fixtures/coretennis/janav_profile.html`` (Boys 12, USTA Florida).
2. The four tournaments Janav actually played, as parsed from
   ``tests/fixtures/coretennis/janav_results.html``, are upserted with
   their real names, dates, and locations.
3. A representative sample of 50 Florida junior tournaments is parsed from
   ``tests/fixtures/usta_api/tournaments_query_florida_junior.json`` via
   :func:`src.parse.usta_api.parse_tournaments_envelope`.
4. One Boys 12 Singles draw per real-match tournament with Janav + the
   real opponent as draw entries.
5. Four match rows mirroring the real CoreTennis-attested losses (deterministic
   ``match-coretennis-<slug>-1of32`` IDs, scores parsed via
   :func:`src.parse.matches.parse_score`).
6. A synthesized but plausible WTN trajectory + a sectional ranking trajectory.
7. One ``ok`` sync_runs row summarizing the discovery walk.

Usage::

    python scripts/seed_dev_data.py

Idempotent: every write uses upsert semantics (``INSERT OR REPLACE``) and
the sync_run row is upserted by deleting any prior seeder run first.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path

from src.models.draw import Draw, DrawEntry
from src.models.match import Match
from src.models.player import Player
from src.models.ranking import RankingSnapshot
from src.models.tournament import Tournament
from src.models.wtn import WTNSnapshot
from src.parse.matches import parse_score
from src.parse.usta_api import parse_tournaments_envelope
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
# Constants — Janav identity grounded in CoreTennis + Clubspark
# ---------------------------------------------------------------------------

JANAV_USTA_ID = "971BA48D-A2EA-4FB7-8305-F42EA466F6DF"
JANAV_FULL_NAME = "Janav Thasen"
JANAV_PROFILE_URL = f"https://playtennis.usta.com/profiles/{JANAV_USTA_ID}"
JANAV_AGE_CATEGORY = "Boys 12"
JANAV_SECTION = "Florida"

# Path to the captured USTA Play Tennis junior fixture used to seed the
# upcoming-tournaments panel.
FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
USTA_FIXTURE = FIXTURE_ROOT / "usta_api" / "tournaments_query_florida_junior.json"

# How many real-USTA-API tournaments to fold into the seeded DB.
USTA_FIXTURE_CAP = 50


# ---------------------------------------------------------------------------
# Match-data DTOs — anchored to tests/fixtures/coretennis/janav_results.html
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RealMatch:
    """One real CoreTennis-attested match for Janav."""

    slug: str  # short, URL-safe identifier used to derive match/tournament ids
    tournament_name: str
    start_date: date
    end_date: date
    location_city: str
    location_state: str
    round_label: str  # CoreTennis label, e.g. "R1/32", "R1/16"
    opponent_full_name: str
    opponent_first: str
    opponent_last: str
    score_raw: str


# Janav lost all four of his completed matches per CoreTennis.
REAL_MATCHES: tuple[RealMatch, ...] = (
    RealMatch(
        slug="saddlebrook-2026-01",
        tournament_name="USTA National Level 3 Tournament — Saddlebrook",
        start_date=date(2026, 1, 17),
        end_date=date(2026, 1, 19),
        location_city="Wesley Chapel",
        location_state="FL",
        round_label="R1/32",
        opponent_full_name="Gustavo Lipinski",
        opponent_first="Gustavo",
        opponent_last="Lipinski",
        score_raw="7-5 2-6 [10-12]",
    ),
    RealMatch(
        slug="city-club-river-ranch-2025-09",
        tournament_name="USTA National Level 3 Tournament — City Club at River Ranch",
        start_date=date(2025, 9, 13),
        end_date=date(2025, 9, 15),
        location_city="Lafayette",
        location_state="LA",
        round_label="R1/16",
        opponent_full_name="Satvik Challa",
        opponent_first="Satvik",
        opponent_last="Challa",
        score_raw="6-1 6-3",
    ),
    RealMatch(
        slug="usta-national-campus-2025-06",
        tournament_name="USTA National Level 3 Tournament — USTA National Campus",
        start_date=date(2025, 6, 14),
        end_date=date(2025, 6, 18),
        location_city="Orlando",
        location_state="FL",
        round_label="R1/32",
        opponent_full_name="Jaxon Carpenter",
        opponent_first="Jaxon",
        opponent_last="Carpenter",
        score_raw="6-1 6-3",
    ),
    RealMatch(
        slug="saddlebrook-2025-01",
        tournament_name="USTA National Level 3 Tournament — Saddlebrook",
        start_date=date(2025, 1, 18),
        end_date=date(2025, 1, 20),
        location_city="Wesley Chapel",
        location_state="FL",
        round_label="R1/32",
        opponent_full_name="Raziel Rubenstein",
        opponent_first="Raziel",
        opponent_last="Rubenstein",
        score_raw="6-0 6-0",
    ),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _opponent_id(full_name: str) -> str:
    """Deterministic synthetic GUID for a CoreTennis-attested opponent.

    Using ``uuid5(NAMESPACE_URL, "coretennis:<name>")`` means re-running the
    seeder produces stable opponent IDs without inventing fictitious
    USTA-shaped GUIDs that might collide with real records.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"coretennis:{full_name}"))


def _tournament_id_for(slug: str) -> str:
    """Tournament ID derived from the CoreTennis slug.

    Real-match tournaments use the ``tournament-coretennis-<slug>`` shape so
    they cannot collide with the USTA-API GUIDs harvested from the fixture.
    """
    return f"tournament-coretennis-{slug}"


def _draw_id_for(slug: str) -> str:
    """Composite draw ID following the ``<tournament-id>:<event-id>`` shape."""
    return f"{_tournament_id_for(slug)}:singles-b12"


def _match_id_for(slug: str) -> str:
    """Match ID derived from the CoreTennis slug + round position."""
    return f"match-coretennis-{slug}-1of32"


def _round_label(coretennis_round: str) -> str:
    """Normalize CoreTennis round labels to the project's ``R<n>`` shape.

    ``R1/32 -> "R32"``; ``R1/16 -> "R16"`` (the suffix is the draw size).
    """
    mapping = {
        "R1/32": "R32",
        "R1/16": "R16",
        "R1/8": "QF",
        "QF": "QF",
        "SF": "SF",
        "F": "F",
    }
    return mapping.get(coretennis_round, coretennis_round)


def _derive_status(start: date, end: date, today: date) -> str:
    if end < today:
        return "completed"
    if start <= today <= end:
        return "in_progress"
    return "upcoming"


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
        district=None,
        age_category=JANAV_AGE_CATEGORY,
        profile_url=JANAV_PROFILE_URL,
        last_fetched_at=_now(),
    )


def _build_opponents() -> list[Player]:
    """One Player row per real CoreTennis-attested opponent."""
    opponents: list[Player] = []
    for rm in REAL_MATCHES:
        opponents.append(
            Player(
                usta_id=_opponent_id(rm.opponent_full_name),
                full_name=rm.opponent_full_name,
                first_name=rm.opponent_first,
                last_name=rm.opponent_last,
                gender="M",
                section=None,
                district=None,
                age_category=JANAV_AGE_CATEGORY,
                profile_url=None,
                last_fetched_at=_now(),
            )
        )
    return opponents


def _build_real_tournaments(today: date) -> list[Tournament]:
    """One Tournament row per CoreTennis-attested match.

    Surface is hard for every event Janav played per the fixture; level is
    USTA National Level 3; sanction body is USTA. Status is derived from
    today vs the tournament dates.
    """
    out: list[Tournament] = []
    seen: set[str] = set()
    for rm in REAL_MATCHES:
        tid = _tournament_id_for(rm.slug)
        if tid in seen:
            continue
        seen.add(tid)
        out.append(
            Tournament(
                usta_id=tid,
                name=rm.tournament_name,
                level="USTA National Level 3",
                sanction_body="USTA",
                start_date=rm.start_date,
                end_date=rm.end_date,
                location_city=rm.location_city,
                location_state=rm.location_state,
                surface="hard",
                ball=None,
                entry_deadline=None,
                status=_derive_status(rm.start_date, rm.end_date, today),
                last_fetched_at=_now(),
            )
        )
    return out


def _build_real_draws() -> list[Draw]:
    """One Boys 12 Singles draw per real tournament Janav played."""
    return [
        Draw(
            usta_id=_draw_id_for(rm.slug),
            tournament_id=_tournament_id_for(rm.slug),
            name="Boys 12 Singles",
            format="single_elimination",
            size=32,
            gender="Boys",
            age_group="U12",
            division="Boys U12 Singles",
            status="completed",
            last_fetched_at=_now(),
        )
        for rm in REAL_MATCHES
    ]


def _build_real_draw_entries() -> list[DrawEntry]:
    """Two DrawEntry rows per real draw: Janav (pos 1) + opponent (pos 2)."""
    entries: list[DrawEntry] = []
    for rm in REAL_MATCHES:
        draw_id = _draw_id_for(rm.slug)
        entries.append(
            DrawEntry(
                draw_id=draw_id,
                player_id=JANAV_USTA_ID,
                seed=None,
                position=1,
                status="entered",
            )
        )
        entries.append(
            DrawEntry(
                draw_id=draw_id,
                player_id=_opponent_id(rm.opponent_full_name),
                seed=None,
                position=2,
                status="entered",
            )
        )
    return entries


def _build_real_matches() -> list[Match]:
    """One Match row per CoreTennis-attested match (Janav lost all four)."""
    out: list[Match] = []
    for rm in REAL_MATCHES:
        sets, outcome, _residual = parse_score(rm.score_raw)
        scheduled = datetime.combine(rm.start_date, time(12, 0), tzinfo=UTC)
        opp_id = _opponent_id(rm.opponent_full_name)
        out.append(
            Match(
                usta_id=_match_id_for(rm.slug),
                draw_id=_draw_id_for(rm.slug),
                round=_round_label(rm.round_label),
                scheduled_at=scheduled,
                court=None,
                player_a_id=JANAV_USTA_ID,
                player_b_id=opp_id,
                score_raw=rm.score_raw,
                sets=sets,
                outcome=outcome if outcome != "unfinished" else "completed",
                winner_id=opp_id,  # Janav lost every match per CoreTennis.
                last_fetched_at=_now(),
            )
        )
    return out


def _load_usta_fixture_tournaments(
    *, cap: int = USTA_FIXTURE_CAP
) -> list[tuple[Tournament, list[Draw]]]:
    """Parse the captured USTA-API fixture into Tournament + Draw rows.

    Returns up to ``cap`` (Tournament, [Draw, ...]) pairs. The cap exists
    so the seeded DB stays tight regardless of how the fixture grows.
    """
    if not USTA_FIXTURE.exists():
        return []
    with USTA_FIXTURE.open(encoding="utf-8") as fh:
        envelope = json.load(fh)
    pairs = parse_tournaments_envelope(envelope, fetched_at=_now())
    return pairs[:cap]


# ---------------------------------------------------------------------------
# WTN + ranking snapshots — synthesized but plausible
# ---------------------------------------------------------------------------


def _build_wtn_snapshots() -> list[WTNSnapshot]:
    """Six monthly singles snapshots + one doubles snapshot for Janav.

    Singles drifts 38.5 -> 36.0 (lower is better) across 2025-12..2026-05;
    one doubles snapshot pinned at 39.2. These shapes match the project's
    convention of an improving junior just starting to drop WTN.
    """
    singles_values = [38.5, 38.0, 37.5, 37.0, 36.5, 36.0]
    months = [
        date(2025, 12, 1),
        date(2026, 1, 1),
        date(2026, 2, 1),
        date(2026, 3, 1),
        date(2026, 4, 1),
        date(2026, 5, 1),
    ]
    snaps: list[WTNSnapshot] = [
        WTNSnapshot(
            player_id=JANAV_USTA_ID,
            type="singles",
            value=v,
            confidence=0.80,
            as_of=as_of,
        )
        for as_of, v in zip(months, singles_values, strict=True)
    ]
    snaps.append(
        WTNSnapshot(
            player_id=JANAV_USTA_ID,
            type="doubles",
            value=39.2,
            confidence=0.70,
            as_of=date(2026, 5, 1),
        )
    )
    return snaps


def _build_ranking_snapshots() -> list[RankingSnapshot]:
    """Six monthly Florida sectional Boys 12 Singles ranking snapshots.

    Position trajectory 487 -> 412 -> 350 across six months (the in-between
    months interpolate linearly so the curve isn't a step function).
    """
    months = [
        date(2025, 12, 1),
        date(2026, 1, 1),
        date(2026, 2, 1),
        date(2026, 3, 1),
        date(2026, 4, 1),
        date(2026, 5, 1),
    ]
    positions = [487, 462, 437, 412, 381, 350]
    points = [12.0, 15.0, 19.0, 24.0, 31.0, 40.0]
    return [
        RankingSnapshot(
            player_id=JANAV_USTA_ID,
            category="Boys 12 Singles",
            scope="sectional",
            section=JANAV_SECTION,
            position=pos,
            points=pts,
            as_of=as_of,
        )
        for as_of, pos, pts in zip(months, positions, points, strict=True)
    ]


# ---------------------------------------------------------------------------
# Sync run bookkeeping
# ---------------------------------------------------------------------------


SEEDER_SOURCE_LABEL = "multi"
SEEDER_LOG_HEADER = "scripts/seed_dev_data.py"


def _upsert_sync_run(
    conn: sqlite3.Connection,
    *,
    fetched: int,
    parsed: int,
    persisted: int,
    log_text: str,
) -> None:
    """Insert one ``ok`` sync_runs row summarizing the seeder walk.

    Idempotent: any prior row whose ``log_text`` starts with the seeder
    header is deleted before the new row is inserted, so a re-run replaces
    the previous seeder row rather than appending a duplicate.
    """
    conn.execute(
        "DELETE FROM sync_runs WHERE log_text LIKE ?",
        (f"{SEEDER_LOG_HEADER}%",),
    )
    now_iso = _now().isoformat()
    conn.execute(
        """
        INSERT INTO sync_runs (
            started_at, finished_at, source, status,
            fetched_count, parsed_count, persisted_count, errored_count,
            error_summary, log_text
        ) VALUES (?, ?, ?, 'ok', ?, ?, ?, 0, NULL, ?)
        """,
        (
            now_iso,
            now_iso,
            SEEDER_SOURCE_LABEL,
            fetched,
            parsed,
            persisted,
            log_text,
        ),
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def seed(conn: sqlite3.Connection | None = None) -> dict[str, int]:
    """Seed the connected DB. Returns a count summary per table.

    If ``conn`` is None, opens a connection to the configured DB and closes
    it on return; otherwise uses the caller's connection (the test fixture
    does this and is responsible for schema init).
    """
    own_conn = conn is None
    if own_conn:
        init_schema()
        conn = connect()
    assert conn is not None

    try:
        today = date.today()

        janav = _build_janav()
        opponents = _build_opponents()
        real_tournaments = _build_real_tournaments(today)
        real_draws = _build_real_draws()
        real_entries = _build_real_draw_entries()
        real_matches = _build_real_matches()
        wtn_snaps = _build_wtn_snapshots()
        rank_snaps = _build_ranking_snapshots()

        fixture_pairs = _load_usta_fixture_tournaments(cap=USTA_FIXTURE_CAP)

        # --- Players ---
        player_repo = PlayerRepository(conn)
        player_repo.upsert(janav)
        for opp in opponents:
            player_repo.upsert(opp)

        # --- Tournaments (real first, then fixture; fixture cannot evict a
        # real-match tournament because the IDs are disjoint by prefix). ---
        tournament_repo = TournamentRepository(conn)
        for t in real_tournaments:
            tournament_repo.upsert(t)
        for t, _draws in fixture_pairs:
            tournament_repo.upsert(t)

        # --- Draws (real Boys 12 Singles draws + fixture-derived draws) ---
        draw_repo = DrawRepository(conn)
        for d in real_draws:
            draw_repo.upsert(d)
        fixture_draw_count = 0
        for _t, draws in fixture_pairs:
            for d in draws:
                draw_repo.upsert(d)
                fixture_draw_count += 1

        # --- Draw entries (only the real ones — fixture parser doesn't
        # produce entries because the USTA API surface lacks them). ---
        entry_repo = DrawEntryRepository(conn)
        for e in real_entries:
            entry_repo.upsert(e)

        # --- Matches ---
        match_repo = MatchRepository(conn)
        for m in real_matches:
            match_repo.upsert(m)

        # --- WTN + ranking snapshots ---
        wtn_repo = WTNSnapshotRepository(conn)
        for wsnap in wtn_snaps:
            wtn_repo.upsert(wsnap)
        rank_repo = RankingSnapshotRepository(conn)
        for rsnap in rank_snaps:
            rank_repo.upsert(rsnap)

        # --- Sync run bookkeeping ---
        total_tournaments = len(real_tournaments) + len(fixture_pairs)
        total_draws = len(real_draws) + fixture_draw_count
        persisted = (
            1
            + len(opponents)
            + total_tournaments
            + total_draws
            + len(real_entries)
            + len(real_matches)
            + len(wtn_snaps)
            + len(rank_snaps)
        )
        log_text = (
            f"{SEEDER_LOG_HEADER}: anchored seed run\n"
            f"  janav: {JANAV_USTA_ID} ({JANAV_FULL_NAME})\n"
            f"  coretennis matches: {len(real_matches)}\n"
            f"  coretennis tournaments: {len(real_tournaments)}\n"
            f"  usta_api fixture tournaments: {len(fixture_pairs)}\n"
            f"  usta_api fixture draws: {fixture_draw_count}\n"
            f"  wtn snapshots: {len(wtn_snaps)}\n"
            f"  ranking snapshots: {len(rank_snaps)}\n"
        )
        _upsert_sync_run(
            conn,
            fetched=len(fixture_pairs),
            parsed=len(fixture_pairs),
            persisted=persisted,
            log_text=log_text,
        )

        conn.commit()

        return {
            "players": 1 + len(opponents),
            "tournaments": total_tournaments,
            "draws": total_draws,
            "draw_entries": len(real_entries),
            "matches": len(real_matches),
            "wtn_snapshots": len(wtn_snaps),
            "ranking_snapshots": len(rank_snaps),
            "sync_runs": 1,
        }
    finally:
        if own_conn:
            conn.close()


def main() -> int:
    counts = seed()
    print(
        "Seeded "
        f"{counts['players']} players, "
        f"{counts['tournaments']} tournaments, "
        f"{counts['draws']} draws, "
        f"{counts['matches']} matches "
        f"({counts['draw_entries']} draw entries, "
        f"{counts['wtn_snapshots']} WTN snapshots, "
        f"{counts['ranking_snapshots']} ranking snapshots, "
        f"{counts['sync_runs']} sync run)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
