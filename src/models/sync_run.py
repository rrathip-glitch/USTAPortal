"""Pydantic model for an operational sync run.

Each invocation of ``usta sync`` (CLI) or the ``/sync`` POST handler (UI)
records a ``SyncRun`` row capturing what happened — when it started, when it
finished, what it counted, and the captured log. The UI's ``/sync`` page
renders the most recent run plus a tail of the captured log so the user can
see the operational state of the data plane without tailing files on the
server.

The status taxonomy is intentionally narrow:

- ``running``  — a sync is in flight; ``finished_at`` is null.
- ``ok``       — the sync finished and reported zero ``errored`` items.
- ``partial``  — the sync finished but reported one or more ``errored`` items.
- ``failed``   — an unhandled exception aborted the sync; ``error_summary``
                 carries the top-level error message.

``source`` mirrors :class:`src.fetch.router.FetchRouter`'s source taxonomy:
``tennislink``, ``clubspark``, or ``multi`` (the typical case where the
router can dispatch across both).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SyncRunSource = Literal["tennislink", "clubspark", "multi"]
SyncRunStatus = Literal["running", "ok", "partial", "failed"]


class SyncRun(BaseModel):
    id: int
    started_at: datetime
    finished_at: datetime | None = None
    source: SyncRunSource
    status: SyncRunStatus
    fetched_count: int = 0
    parsed_count: int = 0
    persisted_count: int = 0
    errored_count: int = 0
    error_summary: str | None = None
    log_text: str = Field(default="", description="Multi-line log captured during the run.")
