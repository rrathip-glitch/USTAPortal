"""Pydantic model for a UTR (Universal Tennis Rating) search hit.

UTR exposes an anonymous JSON player-search endpoint at
``https://api.utrsports.net/v2/search/players``. The endpoint returns an
ElasticSearch-style envelope; each hit's ``source`` block carries the player's
display name, location, gender, and a pair of ratings (``singlesUtr``,
``doublesUtr``). This model captures the small slice of that payload that the
dashboard cares about — enough to cross-reference a UTR account against a
USTA player without pulling in the long tail of pickleball / coaching /
club-membership fields.

Note: ``singlesUtr`` is a float in the source and frequently ``0.0`` for
unrated juniors. We intentionally preserve ``0.0`` rather than coercing it to
``None`` so the dashboard can distinguish "unrated" from "missing".

Deep-detail endpoints (``/v2/players/<id>``) require an auth token and are
**not** exposed via this model or its parser.
"""

from __future__ import annotations

from pydantic import BaseModel


class UTRPlayerHit(BaseModel):
    """A single result row from the UTR player-search endpoint."""

    utr_id: str
    full_name: str
    first_name: str | None = None
    last_name: str | None = None
    singles_utr: float | None = None
    doubles_utr: float | None = None
    location_display: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    gender: str | None = None
