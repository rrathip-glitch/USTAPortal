from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


DrawFormat = Literal[
    "single_elimination",
    "single_elimination_with_consolation",
    "round_robin",
    "compass",
    "feed_in",
    "unknown",
]
EntryStatus = Literal["entered", "withdrawn", "walkover_in", "alternate", "unknown"]


class Draw(BaseModel):
    usta_id: str
    tournament_id: str
    name: str
    format: DrawFormat = "unknown"
    size: int | None = None
    gender: str | None = None
    age_group: str | None = None
    division: str | None = None
    status: str | None = None
    last_fetched_at: datetime | None = None


class DrawEntry(BaseModel):
    draw_id: str
    player_id: str
    seed: int | None = None
    position: int | None = Field(default=None, description="1-indexed line in the draw.")
    status: EntryStatus = "entered"
