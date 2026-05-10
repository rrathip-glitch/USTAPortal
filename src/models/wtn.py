"""World Tennis Number (WTN) snapshot.

WTN is a 1-40 scale (lower = stronger). Each player has an independent singles
and doubles rating, plus a confidence score.

Open question for recon: is doubles WTN exposed via the same endpoint as
singles, or via a separate one? RESEARCH.md tracks this.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


WTNType = Literal["singles", "doubles"]


class WTNSnapshot(BaseModel):
    player_id: str
    type: WTNType
    value: float = Field(description="WTN rating, 1.0 (strongest) to 40.0 (weakest).")
    confidence: float | None = Field(
        default=None,
        description="Model confidence 0-1. Recon to confirm the exact field name.",
    )
    as_of: date
