"""Pydantic model for a post-match journal entry.

The match journal is Janav's perspective on a match: a free-text body, an
optional self-rating (1-5), and a small set of tags for later filtering.

Identity is ``(player_id, match_id)`` — at most one journal entry per
player per match. ``match_id`` is nullable so a player can record a
general training note unattached to a specific match (e.g. a practice
session, a non-USTA scrimmage). Such entries collide on
``(player_id, NULL)``; SQLite treats NULLs as distinct in UNIQUE
constraints so multiple untethered notes per player are permitted.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MatchJournalEntry(BaseModel):
    id: int | None = None
    match_id: str | None = None
    player_id: str
    created_at: datetime
    updated_at: datetime
    body: str = ""
    self_rating: int | None = Field(default=None, ge=1, le=5)
    tags: list[str] = Field(default_factory=list)
