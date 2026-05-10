from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


TournamentStatus = Literal["upcoming", "in_progress", "completed", "cancelled"]
Surface = Literal["hard", "clay", "grass", "indoor_hard", "carpet", "unknown"]


class Tournament(BaseModel):
    usta_id: str = Field(description="Tournament GUID from USTA.")
    name: str
    level: str | None = Field(default=None, description="USTA level designation, e.g., 'L4'.")
    sanction_body: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    location_city: str | None = None
    location_state: str | None = None
    surface: Surface = "unknown"
    ball: str | None = None
    entry_deadline: datetime | None = None
    status: TournamentStatus = "upcoming"
    last_fetched_at: datetime | None = None
