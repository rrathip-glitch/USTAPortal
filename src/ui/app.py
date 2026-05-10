"""UI routes. Mounted from src/main.py once Phase 3 begins.

For now src/main.py serves a minimal landing page directly. As pages land,
they move here and main.py will `app.include_router(ui.router)`.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()
