"""UI routes. Mounted from src/main.py.

Every page renders even with an empty database: repository calls and
enrichment helpers are wrapped in defensive try/except so missing data,
missing tables, or a missing repository module all fall through to a friendly
empty state. The dashboard never 500s on a fresh checkout.

When the DB *is* populated (typically by ``scripts/seed_dev_data.py`` in
development, or by a real sync in production), routes hydrate templates with
real Player / Tournament / WTNSnapshot / RankingSnapshot / Match objects plus
the derived intelligence the briefing pages need:

- ``recent_form`` from ``src.enrich.form`` for win/loss strips.
- ``strength_of_draw`` from ``src.enrich.strength_of_draw`` for the user's
  projected path through a bracket.
- ``H2H`` summary counts derived inline (the full enrichment module is also
  available but the route only needs aggregates).

Routes read; they do not write. The /sync POST handler is the only mutator
and currently produces a placeholder log entry — the real sync worker writes
the same file in production.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.config import settings
from src.enrich.expected_outcome import (
    ExpectedOutcomeResult,
    expected_outcomes_along_path,
)
from src.enrich.form import FormResult, recent_form
from src.enrich.strength_of_draw import StrengthOfDrawResult, strength_of_draw
from src.models.draw import Draw, DrawEntry
from src.models.match import Match
from src.models.player import Player
from src.models.sync_run import SyncRun
from src.models.tournament import Tournament
from src.models.wtn import WTNSnapshot
from src.store.repositories import (
    DrawEntryRepository,
    DrawRepository,
    MatchRepository,
    PlayerRepository,
    RankingSnapshotRepository,
    SyncRunRepository,
    TournamentRepository,
    WTNSnapshotRepository,
)
from src.ui.helpers import (
    days_until,
    db_has_synthetic_data,
    format_record,
    resolve_user_player,
    wtn_tier,
)

router = APIRouter()
templates = Jinja2Templates(directory="src/ui/templates")

# Templates lean on these helpers — register them globally so they don't need
# to be threaded through every context dict.
templates.env.globals["wtn_tier"] = wtn_tier
templates.env.globals["days_until"] = days_until
templates.env.globals["format_record"] = format_record

# Sync state is now read from the ``sync_runs`` table populated by
# ``usta sync`` (see ``src.cli.main``). The legacy ``data/sync.log`` file is
# no longer consulted.


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _open_conn() -> sqlite3.Connection | None:
    """Open SQLite, returning ``None`` on any failure.

    Routes that cannot open the DB fall through to the empty state — the UI
    must never 500 just because no sync has run.
    """
    try:
        from src.store.db import connect, init_schema
    except Exception:  # pragma: no cover - import-time safety net
        return None
    try:
        conn = connect()
        init_schema(conn)
        return conn
    except Exception:
        return None


def _last_sync_label(conn: sqlite3.Connection | None) -> str:
    """Best-effort label for the header badge.

    Uses the max ``last_fetched_at`` across the tournaments table as a proxy
    for "when was a sync last meaningful". Returns ``"never"`` when there is
    nothing to show.
    """
    if conn is None:
        return "never"
    try:
        row = conn.execute(
            "SELECT MAX(last_fetched_at) FROM tournaments"
        ).fetchone()
    except Exception:
        return "never"
    if row is None or row[0] is None:
        return "never"
    try:
        dt = datetime.fromisoformat(row[0])
    except ValueError:
        return str(row[0])
    return dt.strftime("%Y-%m-%d %H:%M")


def _base_context(conn: sqlite3.Connection | None, **extra: Any) -> dict[str, Any]:
    synthetic = False
    if conn is not None:
        try:
            synthetic = db_has_synthetic_data(conn)
        except Exception:
            synthetic = False
    ctx: dict[str, Any] = {
        "last_sync_label": _last_sync_label(conn),
        "synthetic_data": synthetic,
        "app_version": "0.1.0",
    }
    ctx.update(extra)
    return ctx


def _latest_wtn(
    conn: sqlite3.Connection, player_id: str
) -> tuple[WTNSnapshot | None, WTNSnapshot | None]:
    repo = WTNSnapshotRepository(conn)
    try:
        return repo.latest_for_player(player_id, "singles"), repo.latest_for_player(
            player_id, "doubles"
        )
    except Exception:
        return None, None


def _player_form(conn: sqlite3.Connection, player_id: str, window: int = 8) -> FormResult:
    """Compute recent form for a player, swallowing repository failures."""
    try:
        matches = MatchRepository(conn).list_for_player(player_id)
    except Exception:
        matches = []
    return recent_form(matches, player_id, window=window)


def _ratings_for_draw(
    conn: sqlite3.Connection, entries: list[DrawEntry]
) -> dict[str, float]:
    """Pull singles WTN per entry; used as the rating axis for SoD.

    Falls back silently — missing WTN for a player just means that player
    is unrated for the purpose of the projected-path computation.
    """
    repo = WTNSnapshotRepository(conn)
    ratings: dict[str, float] = {}
    for e in entries:
        try:
            snap = repo.latest_for_player(e.player_id, "singles")
        except Exception:
            snap = None
        if snap is not None:
            ratings[e.player_id] = snap.value
    return ratings


def _scouting_snippet(
    conn: sqlite3.Connection, player_id: str
) -> dict[str, Any]:
    """Mini scouting card data for embedding inside the dashboard / draw views."""
    repo = PlayerRepository(conn)
    try:
        player = repo.get(player_id)
    except Exception:
        player = None
    singles, doubles = _latest_wtn(conn, player_id) if player is not None else (None, None)
    form = _player_form(conn, player_id, window=8) if player is not None else None
    return {
        "player": player,
        "player_id": player_id,
        "singles_wtn": singles,
        "doubles_wtn": doubles,
        "form": form,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    user: Player | None = None
    next_tournament: Tournament | None = None
    singles_wtn: WTNSnapshot | None = None
    doubles_wtn: WTNSnapshot | None = None
    form: FormResult | None = None
    sectional_ranking: Any = None
    next_opponent_card: dict[str, Any] | None = None
    recent_tournaments: list[Tournament] = []

    conn = _open_conn()
    if conn is not None:
        try:
            user = resolve_user_player(conn, settings.usta_user_player_id)
            t_repo = TournamentRepository(conn)
            upcoming = t_repo.list_upcoming()
            next_tournament = upcoming[0] if upcoming else None

            try:
                rows = conn.execute(
                    "SELECT * FROM tournaments WHERE status = 'completed' "
                    "ORDER BY start_date DESC LIMIT 3"
                ).fetchall()
                recent_tournaments = [
                    TournamentRepository._row_to_tournament(r) for r in rows
                ]
            except Exception:
                recent_tournaments = []

            if user is not None:
                singles_wtn, doubles_wtn = _latest_wtn(conn, user.usta_id)
                form = _player_form(conn, user.usta_id, window=8)
                # Sectional ranking — pick the first category we find.
                try:
                    row = conn.execute(
                        "SELECT player_id, category, scope, section, position, points, as_of "
                        "FROM ranking_snapshots WHERE player_id = ? AND scope = 'sectional' "
                        "ORDER BY as_of DESC LIMIT 1",
                        (user.usta_id,),
                    ).fetchone()
                    if row is not None:
                        sectional_ranking = RankingSnapshotRepository._row_to_snapshot(row)
                except Exception:
                    sectional_ranking = None

                # Projected R1 opponent in the next tournament, if discoverable.
                if next_tournament is not None:
                    try:
                        draws = DrawRepository(conn).list_for_tournament(
                            next_tournament.usta_id
                        )
                    except Exception:
                        draws = []
                    for draw in draws:
                        try:
                            entries = DrawEntryRepository(conn).list_for_draw(
                                draw.usta_id
                            )
                        except Exception:
                            entries = []
                        if not any(e.player_id == user.usta_id for e in entries):
                            continue
                        ratings = _ratings_for_draw(conn, entries)
                        try:
                            sod = strength_of_draw(
                                draw, entries, ratings, user.usta_id
                            )
                        except Exception:
                            sod = None
                        if sod is not None and sod.projected_path:
                            next_opponent_card = _scouting_snippet(
                                conn, sod.projected_path[0]
                            )
                            break
        except Exception:
            # Anything unexpected: render the empty state. We swallow rather
            # than raise so a partial DB never blocks the dashboard.
            pass
        finally:
            conn.close()

    countdown = days_until(next_tournament.start_date) if next_tournament else None

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        _base_context(
            None,  # we already closed conn; pass through cached values
            user=user,
            next_tournament=next_tournament,
            countdown=countdown,
            singles_wtn=singles_wtn,
            doubles_wtn=doubles_wtn,
            form=form,
            sectional_ranking=sectional_ranking,
            next_opponent_card=next_opponent_card,
            recent_tournaments=recent_tournaments,
        ),
    )


@router.get("/tournaments", response_class=HTMLResponse)
async def tournaments_list(request: Request) -> HTMLResponse:
    upcoming: list[Tournament] = []
    in_progress: list[Tournament] = []
    completed: list[Tournament] = []

    conn = _open_conn()
    if conn is not None:
        try:
            repo = TournamentRepository(conn)
            upcoming = repo.list_upcoming()
            in_progress = repo.list_in_progress()
            try:
                rows = conn.execute(
                    "SELECT * FROM tournaments WHERE status = 'completed' "
                    "ORDER BY start_date DESC"
                ).fetchall()
                completed = [TournamentRepository._row_to_tournament(r) for r in rows]
            except Exception:
                completed = []
        except Exception:
            upcoming, in_progress, completed = [], [], []
        finally:
            conn.close()

    return templates.TemplateResponse(
        request,
        "tournaments_list.html",
        _base_context(
            None,
            upcoming=upcoming,
            in_progress=in_progress,
            completed=completed,
        ),
    )


@router.get("/tournaments/{usta_id}", response_class=HTMLResponse)
async def tournament_detail(request: Request, usta_id: str) -> HTMLResponse:
    tournament: Tournament | None = None
    draws: list[Draw] = []

    conn = _open_conn()
    if conn is not None:
        try:
            tournament = TournamentRepository(conn).get(usta_id)
            if tournament is not None:
                draws = DrawRepository(conn).list_for_tournament(usta_id)
        except Exception:
            tournament, draws = None, []
        finally:
            conn.close()

    return templates.TemplateResponse(
        request,
        "tournament_detail.html",
        _base_context(
            None,
            tournament=tournament,
            draws=draws,
            message=f"No tournament with ID {usta_id} has been synced.",
        ),
    )


@router.get("/draws/{usta_id}", response_class=HTMLResponse)
async def draw_detail(request: Request, usta_id: str) -> HTMLResponse:
    draw: Draw | None = None
    tournament: Tournament | None = None
    entries: list[DrawEntry] = []
    players_by_id: dict[str, Player] = {}
    wtn_by_id: dict[str, WTNSnapshot | None] = {}
    sod: StrengthOfDrawResult | None = None
    path_cards: list[dict[str, Any]] = []
    path_outcomes: list[ExpectedOutcomeResult] = []
    user: Player | None = None
    user_entry: DrawEntry | None = None

    conn = _open_conn()
    if conn is not None:
        try:
            draw = DrawRepository(conn).get(usta_id)
            if draw is not None:
                entries = DrawEntryRepository(conn).list_for_draw(usta_id)
                tournament = TournamentRepository(conn).get(draw.tournament_id)
                p_repo = PlayerRepository(conn)
                wtn_repo = WTNSnapshotRepository(conn)
                for e in entries:
                    try:
                        p = p_repo.get(e.player_id)
                    except Exception:
                        p = None
                    if p is not None:
                        players_by_id[e.player_id] = p
                    try:
                        wtn_by_id[e.player_id] = wtn_repo.latest_for_player(
                            e.player_id, "singles"
                        )
                    except Exception:
                        wtn_by_id[e.player_id] = None

                user = resolve_user_player(conn, settings.usta_user_player_id)
                if user is not None:
                    user_entry = next(
                        (e for e in entries if e.player_id == user.usta_id), None
                    )
                    if user_entry is not None:
                        ratings = {
                            pid: snap.value
                            for pid, snap in wtn_by_id.items()
                            if snap is not None
                        }
                        try:
                            sod = strength_of_draw(
                                draw, entries, ratings, user.usta_id
                            )
                        except Exception:
                            sod = None
                        if sod is not None:
                            for opp_id in sod.projected_path:
                                path_cards.append(_scouting_snippet(conn, opp_id))
                            try:
                                path_outcomes = expected_outcomes_along_path(
                                    user.usta_id,
                                    list(sod.projected_path),
                                    ratings,
                                )
                            except Exception:
                                path_outcomes = []
        except Exception:
            draw, tournament, entries = None, None, []
        finally:
            conn.close()

    return templates.TemplateResponse(
        request,
        "draw_detail.html",
        _base_context(
            None,
            draw=draw,
            tournament=tournament,
            entries=entries,
            players_by_id=players_by_id,
            wtn_by_id=wtn_by_id,
            sod=sod,
            path_cards=path_cards,
            path_outcomes=path_outcomes,
            user=user,
            user_entry=user_entry,
            message=f"No draw with ID {usta_id} has been synced.",
        ),
    )


@router.get("/players/{usta_id}", response_class=HTMLResponse)
async def player_card(request: Request, usta_id: str) -> HTMLResponse:
    player: Player | None = None
    matches: list[Match] = []
    opponents_by_id: dict[str, Player] = {}
    singles_wtn: WTNSnapshot | None = None
    doubles_wtn: WTNSnapshot | None = None
    form: FormResult | None = None
    ranking_history: list[Any] = []
    user: Player | None = None
    h2h_total: int = 0

    conn = _open_conn()
    if conn is not None:
        try:
            p_repo = PlayerRepository(conn)
            player = p_repo.get(usta_id)
            if player is not None:
                matches = MatchRepository(conn).list_for_player(usta_id)
                singles_wtn, doubles_wtn = _latest_wtn(conn, usta_id)
                form = recent_form(matches, usta_id, window=8)

                # Hydrate opponents so the recent-form pills show real names.
                opponent_ids = {
                    (m.player_b_id if m.player_a_id == usta_id else m.player_a_id)
                    for m in matches
                }
                for oid in opponent_ids:
                    if oid is None:
                        continue
                    try:
                        opp = p_repo.get(oid)
                    except Exception:
                        opp = None
                    if opp is not None:
                        opponents_by_id[oid] = opp

                # Ranking trajectory — concatenate every category we find.
                try:
                    rows = conn.execute(
                        "SELECT DISTINCT category FROM ranking_snapshots "
                        "WHERE player_id = ? ORDER BY category",
                        (usta_id,),
                    ).fetchall()
                except Exception:
                    rows = []
                rs_repo = RankingSnapshotRepository(conn)
                for (cat,) in rows:
                    try:
                        history = rs_repo.history_for_player(usta_id, cat)
                    except Exception:
                        history = []
                    if history:
                        ranking_history.append({"category": cat, "snapshots": history})

                user = resolve_user_player(conn, settings.usta_user_player_id)
                if user is not None and user.usta_id != usta_id:
                    try:
                        h2h_matches = MatchRepository(conn).list_h2h(
                            user.usta_id, usta_id
                        )
                        h2h_total = len(h2h_matches)
                    except Exception:
                        h2h_total = 0
        except Exception:
            player = None
            matches = []
        finally:
            conn.close()

    return templates.TemplateResponse(
        request,
        "player_card.html",
        _base_context(
            None,
            player=player,
            matches=matches,
            opponents_by_id=opponents_by_id,
            singles_wtn=singles_wtn,
            doubles_wtn=doubles_wtn,
            form=form,
            ranking_history=ranking_history,
            user=user,
            h2h_total=h2h_total,
            message=f"No player with ID {usta_id} has been synced.",
        ),
    )


@router.get("/h2h/{a}/{b}", response_class=HTMLResponse)
async def h2h(request: Request, a: str, b: str) -> HTMLResponse:
    player_a: Player | None = None
    player_b: Player | None = None
    matches: list[Match] = []
    wins_a = 0
    wins_b = 0
    streak_kind: str = "none"
    streak_length: int = 0
    last_match: Match | None = None

    conn = _open_conn()
    if conn is not None:
        try:
            p_repo = PlayerRepository(conn)
            player_a = p_repo.get(a)
            player_b = p_repo.get(b)
            matches = MatchRepository(conn).list_h2h(a, b)
            for m in matches:
                if m.winner_id == a:
                    wins_a += 1
                elif m.winner_id == b:
                    wins_b += 1
            # Most recent first for display + streak.
            decided = [m for m in matches if m.scheduled_at is not None]
            decided.sort(key=lambda m: m.scheduled_at or datetime.min, reverse=True)
            if decided:
                last_match = decided[0]
                # Streak: walk newest-to-oldest while winner is constant.
                holder = last_match.winner_id
                if holder is not None:
                    streak_kind = "a" if holder == a else "b"
                    for m in decided:
                        if m.winner_id == holder:
                            streak_length += 1
                        else:
                            break
        except Exception:
            player_a, player_b, matches = None, None, []
            wins_a = wins_b = 0
        finally:
            conn.close()

    return templates.TemplateResponse(
        request,
        "h2h.html",
        _base_context(
            None,
            player_a_id=a,
            player_b_id=b,
            player_a=player_a,
            player_b=player_b,
            matches=matches,
            wins_a=wins_a,
            wins_b=wins_b,
            last_match=last_match,
            streak_kind=streak_kind,
            streak_length=streak_length,
            message="No prior meetings between these players have been synced.",
        ),
    )


# ---------------------------------------------------------------------------
# Sync — backed by the ``sync_runs`` table.
# ---------------------------------------------------------------------------
#
# The previous design mirrored a tail of ``data/sync.log`` on disk and posted
# a placeholder "queued" message. That has been replaced with a SQLite-backed
# log: the CLI's ``usta sync`` command writes ``sync_runs`` rows, and this
# route reads them back. The legacy ``data/sync.log`` file is no longer
# written, but is preserved on disk if it exists from a prior session
# (read-only — we don't truncate or migrate it).


def _format_run_summary(run: SyncRun) -> str:
    """Human-friendly one-liner for the "Last sync" header on /sync."""
    when = (run.finished_at or run.started_at).isoformat(timespec="seconds")
    return (
        f"{run.status} at {when} "
        f"(fetched={run.fetched_count}, parsed={run.parsed_count}, "
        f"persisted={run.persisted_count}, errored={run.errored_count})"
    )


def _format_duration(run: SyncRun) -> str:
    """Compute a duration label for a run, or ``"--"`` if it's still running."""
    if run.finished_at is None:
        return "in flight"
    delta = run.finished_at - run.started_at
    seconds = max(0.0, delta.total_seconds())
    if seconds < 1.0:
        return "<1s"
    if seconds < 60.0:
        return f"{seconds:.1f}s"
    minutes, sec = divmod(int(seconds), 60)
    return f"{minutes}m{sec:02d}s"


def _sync_context(
    *,
    status_message: str | None,
    latest: SyncRun | None,
    recent_runs: list[SyncRun],
) -> dict[str, Any]:
    """Build the template context dict shared by GET /sync and POST /sync."""
    if latest is None:
        last_label = "No sync runs yet"
        log_lines: list[str] = []
        duration_label = "--"
    else:
        last_label = _format_run_summary(latest)
        # Render up to the last 200 lines so the UI is bounded.
        log_lines = [line for line in latest.log_text.splitlines() if line.strip()][-200:]
        duration_label = _format_duration(latest)
    return {
        "status_message": status_message,
        "last_sync_full": last_label,
        "duration_label": duration_label,
        "latest_run": latest,
        "recent_runs": recent_runs,
        "sync_log": log_lines,
    }


def _load_sync_state() -> tuple[SyncRun | None, list[SyncRun]]:
    """Read the latest run + the most recent 10 runs, falling through to empty."""
    conn = _open_conn()
    if conn is None:
        return None, []
    try:
        repo = SyncRunRepository(conn)
        try:
            latest = repo.latest()
        except Exception:
            latest = None
        try:
            recent = repo.recent(limit=10)
        except Exception:
            recent = []
        return latest, recent
    finally:
        conn.close()


@router.get("/sync", response_class=HTMLResponse)
async def sync_page(request: Request) -> HTMLResponse:
    latest, recent = _load_sync_state()
    return templates.TemplateResponse(
        request,
        "sync.html",
        _base_context(
            None,
            **_sync_context(
                status_message=None,
                latest=latest,
                recent_runs=recent,
            ),
        ),
    )


@router.post("/sync", response_class=HTMLResponse)
async def sync_trigger(request: Request) -> HTMLResponse:
    """Spawn a sync subprocess and return a 'queued' acknowledgement.

    Running ``asyncio.run(_run_sync(...))`` synchronously inside the FastAPI
    event loop would block every other request for as long as the sync
    takes. Instead we shell out to the CLI in a detached subprocess —
    ``Popen`` with no ``wait()`` — and report back immediately. The CLI
    records its own ``sync_runs`` row, so the next GET on /sync (or htmx
    poll, etc.) will surface the result.
    """
    status_message = _spawn_sync_subprocess()
    latest, recent = _load_sync_state()
    context = _sync_context(
        status_message=status_message,
        latest=latest,
        recent_runs=recent,
    )

    # htmx posts return just the swappable fragment. Plain form posts get the
    # full page.
    if request.headers.get("hx-request") == "true":
        return templates.TemplateResponse(request, "_sync_log.html", context)

    return templates.TemplateResponse(
        request,
        "sync.html",
        _base_context(None, **context),
    )


def _spawn_sync_subprocess() -> str:
    """Detach a ``usta sync`` subprocess; return a status message for the UI.

    On any failure to spawn (e.g. the python executable is unavailable in
    a hostile sandbox), we fall through to a friendly note rather than
    raising — the /sync page must always render.
    """
    cmd = [sys.executable, "-m", "src.cli.main", "sync"]
    try:
        subprocess.Popen(  # noqa: S603 - inputs are static, not user-supplied
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError as exc:
        return f"Sync could not be queued ({exc.strerror or exc!r})."
    return "Sync queued; refresh in a moment to see results."


__all__ = ["router"]
