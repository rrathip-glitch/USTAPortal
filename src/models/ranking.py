from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class RankingSnapshot(BaseModel):
    """Per-player ranking observation at a point in time.

    This is the row-shape for ``ranking_snapshots`` (one player + category
    + scope per date). For the *whole captured list* (e.g. "Boys 12 National
    on 2026-05-11, all 1,298 players"), see :class:`RankingList` and
    :class:`RankingListEntry`.
    """

    player_id: str
    category: str = Field(description="e.g., 'Boys 16 Singles', 'Adult Open Doubles'.")
    scope: str = Field(description="'national' | 'sectional' | 'district'.")
    section: str | None = None
    position: int | None = None
    points: float | None = None
    as_of: date


# ---------------------------------------------------------------------------
# Captured ranking list (e.g. "Boys 12s National Standings, 2026-05-11")
# ---------------------------------------------------------------------------


Gender = Literal["M", "F", "X"]
Scope = Literal["national", "sectional", "district"]


class RankingList(BaseModel):
    """Header row for one captured ranking list.

    A :class:`RankingList` is the *whole list* (header + total player count),
    paired with N :class:`RankingListEntry` rows for the individual players.
    The list ``id`` is a slug-style identifier that's stable for the
    (age_category, gender, scope, section, as_of) tuple, so re-fetches
    upsert cleanly rather than duplicating.
    """

    id: str = Field(description="Slug identifier, e.g. 'u12-boys-national-2026-05-11'.")
    age_category: str = Field(description="e.g. 'Boys 12s', 'Girls 14s', 'Adult Open'.")
    gender: Gender = Field(description="'M', 'F', or 'X' (mixed).")
    scope: Scope = Field(description="'national', 'sectional', or 'district'.")
    section: str | None = Field(
        default=None,
        description="Section name (e.g. 'Florida'); None for national-scope lists.",
    )
    as_of: date = Field(description="Publication date of the ranking list itself.")
    source: str = Field(description="'clubspark' or 'tennislink'.")
    total_players: int = Field(description="Number of entries in the captured list.")
    fetched_at: datetime = Field(description="When this app last fetched the list.")


class RankingListEntry(BaseModel):
    """One row in a captured ranking list (position + player + scores).

    Each entry references the parent :class:`RankingList` via ``list_id``
    and the canonical player via ``player_usta_id``. The ``player_name_raw``
    column captures the name as it appeared on the source page — useful
    for traceability when a player record hasn't yet been hydrated.

    WTN columns (``wtn_singles`` / ``wtn_doubles``) are optional because
    not every ranking source exposes them; the Clubspark surface does,
    TennisLink does not.
    """

    list_id: str = Field(description="FK to RankingList.id.")
    position: int = Field(description="1-indexed rank within the list.")
    player_usta_id: str = Field(description="FK to players.usta_id.")
    player_name_raw: str = Field(description="Player name as it appeared on the source.")
    points: int | None = Field(default=None, description="Ranking points, if any.")
    section: str | None = Field(
        default=None,
        description="Player's section, often shown alongside the rank.",
    )
    wtn_singles: float | None = Field(
        default=None, description="World Tennis Number — singles."
    )
    wtn_doubles: float | None = Field(
        default=None, description="World Tennis Number — doubles."
    )
