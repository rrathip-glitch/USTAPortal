"""FastAPI application entry point.

Optimized for Railway's healthcheck race: we register ``/health`` BEFORE
importing the UI router so the app object is ready in milliseconds.
Heavy imports (Jinja templates, repositories, enrichments) happen
afterward; if any of them fails, ``/health`` still answers 200 and the
deploy is marked healthy while the UI shows a friendly degraded page.
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse

logger = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


# ---------------------------------------------------------------------------
# Lifespan — schema init runs in the background, never blocks port-bind
# ---------------------------------------------------------------------------


def _init_schema_safely() -> None:
    """Best-effort schema init. Never raises so it can't crash uvicorn."""
    try:
        from src.store.db import init_schema

        init_schema()
        logger.info("init_schema: ok")
    except Exception as exc:
        logger.warning("init_schema: skipped (%s: %s)", type(exc).__name__, exc)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Fire schema init in a thread so the event loop is free to accept
    # connections immediately. Railway's healthcheck wins the race.
    import asyncio

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _init_schema_safely)
    yield


app = FastAPI(title="USTA Portal", version="0.1.0", lifespan=_lifespan)


# ---------------------------------------------------------------------------
# Health endpoints — registered FIRST so they always win imports
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> JSONResponse:
    """Cheap, always-200 health probe for Railway. Zero I/O."""
    return JSONResponse({"status": "ok"})


@app.get("/healthz")
async def healthz() -> PlainTextResponse:
    """Plaintext mirror of /health for kube-style probes."""
    return PlainTextResponse("ok")


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
    except Exception as exc:
        db_state = f"error: {type(exc).__name__}: {exc}"

    return JSONResponse(
        {
            "status": "ok",
            "db": db_state,
            "last_sync": last_sync,
            "tournaments": tournament_count,
            "environment": os.getenv("ENVIRONMENT", "production"),
            "checked_at": datetime.now(UTC).isoformat(),
            "version": "0.1.0",
            "python": sys.version.split()[0],
        }
    )


# ---------------------------------------------------------------------------
# Static + UI router — loaded AFTER /health is registered. Wrapped in
# try/except so a single bad import doesn't bring down /health.
# ---------------------------------------------------------------------------


_STATIC_DIR = Path(__file__).parent / "ui" / "static"
if _STATIC_DIR.is_dir():
    try:
        from fastapi.staticfiles import StaticFiles

        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    except Exception as exc:
        logger.warning("static mount failed (%s); /static will 404.", exc)


try:
    from src.ui.app import router as ui_router

    app.include_router(ui_router)
except Exception as exc:
    logger.warning("UI router import failed (%s); pages will 404.", exc)

    @app.get("/")
    async def _degraded_root() -> JSONResponse:
        return JSONResponse(
            {
                "status": "degraded",
                "detail": f"UI router unavailable: {type(exc).__name__}",
            },
            status_code=503,
        )


def get_app() -> FastAPI:
    """Factory for tests and alternative entrypoints."""
    return app


__all__: list[str] = ["app", "get_app"]
