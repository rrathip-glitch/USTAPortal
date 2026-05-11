"""Pydantic model for a USTA player.

Fields are conservative — only those we are certain exist in the public profile
view. Recon will likely add: section, district, age category, sectional points,
junior/adult flag, profile photo URL.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


Gender = Literal["M", "F", "X"]


class Player(BaseModel):
    usta_id: str = Field(description="USTA player identifier (likely a GUID; recon to confirm).")
    full_name: str
    first_name: str | None = None
    last_name: str | None = None
    gender: Gender | None = None
    section: str | None = Field(default=None, description="USTA section, e.g., 'Southern'.")
    district: str | None = None
    age_category: str | None = Field(
        default=None, description="e.g., 'Boys' 16s', 'Adult Open'."
    )
    profile_url: str | None = None
    last_fetched_at: datetime | None = None
    coach_notes: str | None = Field(
        default=None,
        description="Free-text coach notes (Janav's coach). Locally entered; not synced from USTA.",
    )
