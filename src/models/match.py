from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


MatchOutcome = Literal["completed", "retired", "walkover", "default", "unfinished", "unknown"]


class SetScore(BaseModel):
    games_a: int
    games_b: int
    tiebreak_a: int | None = None
    tiebreak_b: int | None = None


class Match(BaseModel):
    usta_id: str | None = None
    draw_id: str
    round: str | None = Field(default=None, description="e.g., 'R32', 'QF', 'F'.")
    scheduled_at: datetime | None = None
    court: str | None = None
    player_a_id: str | None = None
    player_b_id: str | None = None
    score_raw: str | None = Field(default=None, description="Original USTA score string.")
    sets: list[SetScore] = Field(default_factory=list)
    outcome: MatchOutcome = "unknown"
    winner_id: str | None = None
    last_fetched_at: datetime | None = None
