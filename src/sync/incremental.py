"""Incremental-sync helper primitives.

The sync orchestrator pulls tournament/draw rows from upstream APIs on a
schedule. We don't want to re-fetch every row every time — most tournament
data is effectively immutable once captured. These helpers encapsulate the
two decisions the orchestrator needs to make:

1. *Should I re-fetch this entity?* — :class:`IncrementalFilter` answers
   that based on a refresh window and an optional ``force`` override.
2. *Which entities have I already fetched recently?* —
   :func:`existing_tournament_ids_recently_fetched` and
   :func:`existing_draw_ids_recently_fetched` return the set of ids whose
   ``last_fetched_at`` falls within the refresh window, so the
   orchestrator can prune them from the work list before issuing any
   HTTP calls.

The two helpers are read-only against the DB and use parameterized
queries (no string interpolation). They live in this module rather than
on the repository classes because they're orchestration concerns: the
repositories themselves don't know about refresh windows.

The DB stores ``last_fetched_at`` as ISO-8601 TEXT (see
``src/store/db.py``). The helpers convert the caller's ``datetime`` to
the same ISO format before comparing — comparing ISO strings
lexicographically is correct *only* when the strings use the same
offset/zone normalization. Callers should pass tz-aware UTC datetimes
(which is what the repositories write).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

__all__ = [
    "IncrementalFilter",
    "existing_draw_ids_recently_fetched",
    "existing_tournament_ids_recently_fetched",
]


@dataclass(frozen=True)
class IncrementalFilter:
    """Decides whether a given entity row should be re-fetched.

    Attributes
    ----------
    now:
        Reference timestamp for the comparison. Pass a tz-aware UTC
        datetime — naive datetimes will compare-fail against the
        tz-aware ``last_fetched_at`` values written by the repositories.
    refresh_window:
        How stale a row is allowed to be before we re-fetch it. A row
        whose ``last_fetched_at`` is older than ``now - refresh_window``
        is considered stale.
    force:
        When ``True``, every row is treated as stale (i.e. the filter
        always returns ``True``). Used by the CLI's ``--force`` flag.
    """

    now: datetime
    refresh_window: timedelta
    force: bool = False

    def should_refresh(self, last_fetched_at: datetime | None) -> bool:
        """Return ``True`` iff this entity should be re-fetched now."""
        if self.force:
            return True
        if last_fetched_at is None:
            return True
        return (self.now - last_fetched_at) >= self.refresh_window


def existing_tournament_ids_recently_fetched(
    conn: sqlite3.Connection,
    *,
    since: datetime,
) -> set[str]:
    """Return tournament ``usta_id``s whose ``last_fetched_at`` >= ``since``.

    The orchestrator subtracts this set from the candidate id list so we
    don't re-fetch rows that are already inside the refresh window.
    """
    cutoff = since.isoformat()
    rows = conn.execute(
        "SELECT usta_id FROM tournaments "
        "WHERE last_fetched_at IS NOT NULL AND last_fetched_at >= ?",
        (cutoff,),
    ).fetchall()
    return {row[0] for row in rows}


def existing_draw_ids_recently_fetched(
    conn: sqlite3.Connection,
    *,
    since: datetime,
) -> set[str]:
    """Return draw ``usta_id``s whose ``last_fetched_at`` >= ``since``.

    Mirrors :func:`existing_tournament_ids_recently_fetched`.
    """
    cutoff = since.isoformat()
    rows = conn.execute(
        "SELECT usta_id FROM draws "
        "WHERE last_fetched_at IS NOT NULL AND last_fetched_at >= ?",
        (cutoff,),
    ).fetchall()
    return {row[0] for row in rows}
