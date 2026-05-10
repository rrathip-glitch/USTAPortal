"""FastAPI application entry point.

The dashboard pages live in ``src.ui.app`` and are mounted as a router. The
/health endpoint stays here because Railway's deploy config points at it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.config import settings
from src.ui.app import router as ui_router

app = FastAPI(title="USTA Portal", version="0.1.0")
app.mount("/static", StaticFiles(directory="src/ui/static"), name="static")
app.include_router(ui_router)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "db": "unknown",
            "last_sync": None,
            "environment": settings.environment,
            "checked_at": datetime.now(UTC).isoformat(),
        }
    )


def get_app() -> FastAPI:
    """Factory for tests and alternative entrypoints."""
    return app


__all__: list[str] = ["app", "get_app"]
