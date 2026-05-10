"""FastAPI application entry point.

The dashboard is intentionally thin in v0 — most pages are placeholders that
render after Phase 1's sync pipeline lands. The /health endpoint is wired up
now because Railway's deploy config points at it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from src.config import settings

app = FastAPI(title="USTA Portal", version="0.1.0")


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "db": "unknown",
            "last_sync": None,
            "environment": settings.environment,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    )


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(
        """
        <!doctype html>
        <html>
          <head><title>USTA Portal</title></head>
          <body style="font-family: system-ui; max-width: 720px; margin: 4rem auto;">
            <h1>USTA Portal</h1>
            <p>Bootstrap scaffold. See <code>SPEC.md</code> for the full plan and
            <code>STATE.md</code> for current status.</p>
            <ul>
              <li><a href="/health">/health</a></li>
              <li><a href="/docs">/docs</a> (FastAPI)</li>
            </ul>
          </body>
        </html>
        """
    )


def get_app() -> FastAPI:
    """Factory for tests and alternative entrypoints."""
    return app


__all__: list[str] = ["app", "get_app"]
_ = Any  # keep typing import warm for downstream extensions
