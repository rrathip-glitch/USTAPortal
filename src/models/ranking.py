from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class RankingSnapshot(BaseModel):
    player_id: str
    category: str = Field(description="e.g., 'Boys 16 Singles', 'Adult Open Doubles'.")
    scope: str = Field(description="'national' | 'sectional' | 'district'.")
    section: str | None = None
    position: int | None = None
    points: float | None = None
    as_of: date
