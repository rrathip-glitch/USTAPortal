"""UI helpers shared by route handlers and Jinja templates.

These functions are pure (no IO, no global state) and are unit-testable
through the route handlers themselves. They live separate from ``app.py`` so
that the route bodies read as orchestration, not arithmetic.

Two responsibilities here:

1. Resolve the "user" player record. ``USTA_USER_PLAYER_ID`` from settings is
   authoritative; when unset (typical in dev / synthetic seeding) we fall back
   to the first player whose ``usta_id`` starts with the synthetic Janav
   prefix written by ``scripts/seed_dev_data.py``.
2. Small classifiers used by templates: a WTN tier label
   (elite / strong / club / developing) used to color-code the dashboard
   chips, a coarse "synthetic-data" detector for the footer badge, and a
   days-until helper that gracefully handles ``None`` start dates.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Literal

from src.models.player import Player
from src.store.repositories import PlayerRepository

# Synthetic-data prefixes are the seeder's contract with the UI: any player ID
# starting with one of these is a fixture, not real USTA data. The footer
# badge surfaces this so a viewer never confuses a demo run with reality.
SYNTHETIC_PREFIXES: tuple[str, ...] = ("JANAV-SYNTHETIC", "OPP-SYNTHETIC")

WtnTier = Literal["elite", "strong", "club", "developing", "unrated"]


def wtn_tier(value: float | None) -> WtnTier:
    """Bucket a WTN value (1.0 strongest, 40.0 weakest) into a coarse tier.

    Boundaries chosen for a junior audience: under 15 is genuinely strong,
    15-25 is competitive sectional, 25-35 is club level, above that is
    developing. ``None`` returns the ``unrated`` tier so templates can render
    a neutral chip without a special case.
    """
    if value is None:
        return "unrated"
    if value <= 15.0:
        return "elite"
    if value <= 25.0:
        return "strong"
    if value <= 35.0:
        return "club"
    return "developing"


def days_until(d: date | None, today: date | None = None) -> int | None:
    """Days from ``today`` (or :func:`date.today`) until ``d``.

    Returns ``None`` when ``d`` is ``None`` so templates can render "TBD"
    without an ``if`` ladder. A negative result is preserved (the tournament
    is in the past) — callers decide whether to surface it.
    """
    if d is None:
        return None
    base = today or date.today()
    return (d - base).days


def resolve_user_player(conn: sqlite3.Connection, configured_id: str) -> Player | None:
    """Pick the player whose dashboard this is.

    Precedence:

    1. ``USTA_USER_PLAYER_ID`` from settings, if it resolves to a real row.
    2. The first synthetic-Janav player, by ``JANAV-SYNTHETIC`` prefix
       lexicographic order. This is the fallback the seeded dev DB hits.
    3. ``None`` — the dashboard then renders its empty state.
    """
    repo = PlayerRepository(conn)
    if configured_id:
        hit = repo.get(configured_id)
        if hit is not None:
            return hit

    row = conn.execute(
        "SELECT usta_id FROM players WHERE usta_id LIKE 'JANAV-SYNTHETIC%' "
        "ORDER BY usta_id LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return repo.get(row[0])


def db_has_synthetic_data(conn: sqlite3.Connection) -> bool:
    """True iff at least one player ID matches a synthetic prefix.

    Used by ``base.html`` to display the "synthetic data" footer badge so a
    viewer knows the dashboard is running on seeded fixtures.
    """
    for prefix in SYNTHETIC_PREFIXES:
        row = conn.execute(
            "SELECT 1 FROM players WHERE usta_id LIKE ? || '%' LIMIT 1",
            (prefix,),
        ).fetchone()
        if row is not None:
            return True
    return False


def format_record(wins: int, losses: int) -> str:
    """Render a W-L record. ``0-0`` becomes ``--`` to avoid noise on empty form."""
    if wins == 0 and losses == 0:
        return "--"
    return f"{wins}-{losses}"


__all__ = [
    "SYNTHETIC_PREFIXES",
    "WtnTier",
    "db_has_synthetic_data",
    "days_until",
    "format_record",
    "resolve_user_player",
    "wtn_tier",
]
