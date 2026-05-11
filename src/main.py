"""FastAPI application entry point.

The dashboard pages live in ``src.ui.app`` and are mounted as a router.
``/health`` stays here because Railway's deploy config points at it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.config import settings
from src.ui.app import router as ui_router

app = FastAPI(title="USTA Portal", version="0.1.0")

# Mount static files only when the directory exists — protects fresh
# checkouts and tests where the static dir might not be present.
_STATIC_DIR = Path(__file__).parent / "ui" / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.include_router(ui_router)


@app.get("/health")
async def health() -> JSONResponse:
    """Health probe used by Railway's deploy config.

    Always returns 200 (Railway will mark the deploy healthy as long as
    the response code is in the 2xx range). The body carries best-effort
    diagnostics so a curl shows useful state without paging anyone.
    """
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
