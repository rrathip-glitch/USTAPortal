"""UI routes. Mounted from src/main.py.

Every page renders even with an empty database — repository calls are wrapped
in try/except so missing data, missing tables, or a missing repository module
all fall through to a friendly empty state. Sync is a placeholder until the
worker process is wired up.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="src/ui/templates")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _last_sync_label() -> str:
    """Return a human-readable last-sync label.

    Placeholder — once the sync worker writes a timestamp to the DB or a
    status file, this will read from there.
    """
    return "never"


def _base_context(**extra: Any) -> dict[str, Any]:
    ctx: dict[str, Any] = {"last_sync_label": _last_sync_label()}
    ctx.update(extra)
    return ctx


def _open_conn() -> sqlite3.Connection | None:
    """Try to open the SQLite DB. Returns None on any failure.

    Routes that fail to open the DB fall through to the empty state — the UI
    must never 500 just because no sync has run.
    """
    try:
        from src.store.db import connect, init_schema
    except Exception:  # pragma: no cover - import-time safety net
        return None
    try:
        conn = connect()
        # init_schema is idempotent.
        init_schema(conn)
        return conn
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    next_tournament: Any = None
    conn = _open_conn()
    if conn is not None:
        try:
            from src.store.repositories import TournamentRepository

            upcoming = TournamentRepository(conn).list_upcoming()
            if upcoming:
                next_tournament = upcoming[0]
        except Exception:
            next_tournament = None
        finally:
            conn.close()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        _base_context(
            next_tournament=next_tournament,
            message="No tournaments synced yet. Run a sync to populate the dashboard.",
        ),
    )


@router.get("/tournaments", response_class=HTMLResponse)
async def tournaments_list(request: Request) -> HTMLResponse:
    upcoming: list[Any] = []
    in_progress: list[Any] = []
    completed: list[Any] = []
    conn = _open_conn()
    if conn is not None:
        try:
            from src.store.repositories import TournamentRepository

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
            upcoming=upcoming,
            in_progress=in_progress,
            completed=completed,
            message="No tournaments synced yet.",
        ),
    )


@router.get("/tournaments/{usta_id}", response_class=HTMLResponse)
async def tournament_detail(request: Request, usta_id: str) -> HTMLResponse:
    tournament: Any = None
    draws: list[Any] = []
    conn = _open_conn()
    if conn is not None:
        try:
            from src.store.repositories import DrawRepository, TournamentRepository

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
            tournament=tournament,
            draws=draws,
            message=f"No tournament with ID {usta_id} has been synced.",
        ),
    )


@router.get("/draws/{usta_id}", response_class=HTMLResponse)
async def draw_detail(request: Request, usta_id: str) -> HTMLResponse:
    draw: Any = None
    tournament: Any = None
    entries: list[Any] = []
    conn = _open_conn()
    if conn is not None:
        try:
            from src.store.repositories import (
                DrawEntryRepository,
                DrawRepository,
                TournamentRepository,
            )

            draw = DrawRepository(conn).get(usta_id)
            if draw is not None:
                entries = DrawEntryRepository(conn).list_for_draw(usta_id)
                tournament = TournamentRepository(conn).get(draw.tournament_id)
        except Exception:
            draw, tournament, entries = None, None, []
        finally:
            conn.close()

    return templates.TemplateResponse(
        request,
        "draw_detail.html",
        _base_context(
            draw=draw,
            tournament=tournament,
            entries=entries,
            message=f"No draw with ID {usta_id} has been synced.",
        ),
    )


@router.get("/players/{usta_id}", response_class=HTMLResponse)
async def player_card(request: Request, usta_id: str) -> HTMLResponse:
    player: Any = None
    matches: list[Any] = []
    singles_wtn: Any = None
    doubles_wtn: Any = None
    conn = _open_conn()
    if conn is not None:
        try:
            from src.store.repositories import (
                MatchRepository,
                PlayerRepository,
                WTNSnapshotRepository,
            )

            player = PlayerRepository(conn).get(usta_id)
            if player is not None:
                matches = MatchRepository(conn).list_for_player(usta_id)
                wtn_repo = WTNSnapshotRepository(conn)
                singles_wtn = wtn_repo.latest_for_player(usta_id, "singles")
                doubles_wtn = wtn_repo.latest_for_player(usta_id, "doubles")
        except Exception:
            player, matches, singles_wtn, doubles_wtn = None, [], None, None
        finally:
            conn.close()

    return templates.TemplateResponse(
        request,
        "player_card.html",
        _base_context(
            player=player,
            matches=matches,
            singles_wtn=singles_wtn,
            doubles_wtn=doubles_wtn,
            message=f"No player with ID {usta_id} has been synced.",
        ),
    )


@router.get("/h2h/{a}/{b}", response_class=HTMLResponse)
async def h2h(request: Request, a: str, b: str) -> HTMLResponse:
    player_a: Any = None
    player_b: Any = None
    matches: list[Any] = []
    wins_a = 0
    wins_b = 0
    conn = _open_conn()
    if conn is not None:
        try:
            from src.store.repositories import MatchRepository, PlayerRepository

            player_repo = PlayerRepository(conn)
            player_a = player_repo.get(a)
            player_b = player_repo.get(b)
            matches = MatchRepository(conn).list_h2h(a, b)
            for m in matches:
                if m.winner_id == a:
                    wins_a += 1
                elif m.winner_id == b:
                    wins_b += 1
        except Exception:
            player_a, player_b, matches = None, None, []
            wins_a = wins_b = 0
        finally:
            conn.close()

    return templates.TemplateResponse(
        request,
        "h2h.html",
        _base_context(
            player_a_id=a,
            player_b_id=b,
            player_a=player_a,
            player_b=player_b,
            matches=matches,
            wins_a=wins_a,
            wins_b=wins_b,
            message="No prior meetings between these players have been synced.",
        ),
    )


@router.get("/sync", response_class=HTMLResponse)
async def sync_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "sync.html",
        _base_context(status_message=None),
    )


@router.post("/sync", response_class=HTMLResponse)
async def sync_trigger(request: Request) -> HTMLResponse:
    # Placeholder: real sync runs in a worker process. For now, acknowledge.
    return templates.TemplateResponse(
        request,
        "sync.html",
        _base_context(status_message="Sync queued (not yet implemented)."),
    )
