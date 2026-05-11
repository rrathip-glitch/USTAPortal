"""FastAPI application entry point.

The dashboard pages live in ``src.ui.app`` and are mounted as a router.
``/health`` stays here because Railway's deploy config points at it.

Schema initialization runs inside an asyncio task fired from the
startup hook so uvicorn can bind to ``$PORT`` immediately — Railway's
healthcheck probes the moment the port opens, and a slow init-db at
container boot was making the probe time out.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.config import settings
from src.ui.app import router as ui_router

logger = logging.getLogger(__name__)

app = FastAPI(title="USTA Portal", version="0.1.0")

# Mount static files only when the directory exists — protects fresh
# checkouts and tests where the static dir might not be present.
_STATIC_DIR = Path(__file__).parent / "ui" / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.include_router(ui_router)


def _init_schema_safely() -> None:
    """Best-effort schema init. Never raises so it can't crash uvicorn."""
    try:
        from src.store.db import init_schema

        init_schema()
        logger.info("init_schema: ok")
    except Exception as exc:  # noqa: BLE001
        logger.warning("init_schema: skipped (%s: %s)", type(exc).__name__, exc)


@app.on_event("startup")
async def _on_startup() -> None:
    # Run schema init in a background thread so the event loop is free
    # to start accepting requests. Railway's healthcheck fires as soon
    # as the port is bound.
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _init_schema_safely)


@app.get("/health")
async def health() -> JSONResponse:
    """Cheap, always-200 health probe for Railway.

    Returns immediately with no DB I/O so the healthcheck can't time
    out. Richer diagnostics live at ``/health/full``.
    """
    return JSONResponse({"status": "ok"})


@app.get("/health/full")
async def health_full() -> JSONResponse:
    """Verbose health view — does best-effort DB introspection."""
    db_state: str = "unknown"
    last_sync: str | None = None
    tournament_count: int | None = None
    try:
        from src.store.db import connect, init_schema

        conn = connect()
        try:
            init_schema(conn)
            db_state = "connected"
            row = conn.execute(
                "SELECT MAX(last_fetched_at) FROM tournaments"
            ).fetchone()
            if row and row[0]:
                last_sync = row[0]
            row = conn.execute("SELECT COUNT(*) FROM tournaments").fetchone()
            if row:
                tournament_count = int(row[0])
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - /health must never raise
        db_state = f"error: {type(exc).__name__}"

    return JSONResponse(
        {
            "status": "ok",
            "db": db_state,
            "last_sync": last_sync,
            "tournaments": tournament_count,
            "environment": settings.environment,
            "checked_at": datetime.now(UTC).isoformat(),
            "version": "0.1.0",
        }
    )


def get_app() -> FastAPI:
    """Factory for tests and alternative entrypoints."""
    return app


__all__: list[str] = ["app", "get_app"]
