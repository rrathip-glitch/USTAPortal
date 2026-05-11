"""Data access layer.

Each repository owns CRUD for one entity. Repositories never read from the
USTA site — they read/write the local SQLite DB and the raw cache. This is
the boundary that makes the app offline-first: every UI route hits a
repository, never a fetch client.

Implementation notes (per DATA_MODEL.md and ADR-002):
- Raw sqlite3 (no ORM). Parameterized queries everywhere.
- All upserts use ``INSERT OR REPLACE`` for consistency. The repositories
  do not commit — the caller decides transaction boundaries.
- Strings are NFC-normalized on write per DATA_MODEL.md.
- Datetimes/dates serialize to ISO-8601 TEXT and parse back on read.
- Match ``sets`` serializes to JSON in the ``sets_json`` column.
- No silent imputation: missing fields stay ``None``.
"""

from __future__ import annotations

import json
import sqlite3
import unicodedata
from datetime import UTC, date, datetime
from typing import Any

from src.models.draw import Draw, DrawEntry
from src.models.journal import MatchJournalEntry
from src.models.match import Match, SetScore
from src.models.player import Player
from src.models.ranking import RankingSnapshot
from src.models.sync_run import SyncRun, SyncRunSource, SyncRunStatus
from src.models.tournament import Tournament
from src.models.wtn import WTNSnapshot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _nfc(value: str | None) -> str | None:
    """NFC-normalize a string per DATA_MODEL.md, passing None through."""
    if value is None:
        return None
    return unicodedata.normalize("NFC", value)


def _iso(value: datetime | date | None) -> str | None:
    """Serialize a datetime/date to ISO-8601, passing None through."""
    if value is None:
        return None
    return value.isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


# ---------------------------------------------------------------------------
# PlayerRepository
# ---------------------------------------------------------------------------


class PlayerRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # Explicit column list — never ``SELECT *`` — so that adding columns
    # in a later migration doesn't quietly break ``_row_to_player``'s
    # positional unpacking.
    _PLAYER_COLUMNS = (
        "usta_id, full_name, first_name, last_name, gender, "
        "section, district, age_category, profile_url, last_fetched_at, coach_notes"
    )

    def upsert(self, player: Player) -> None:
        self._conn.execute(
            f"""
            INSERT OR REPLACE INTO players (
                {self._PLAYER_COLUMNS}
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                player.usta_id,
                _nfc(player.full_name),
                _nfc(player.first_name),
                _nfc(player.last_name),
                player.gender,
                _nfc(player.section),
                _nfc(player.district),
                _nfc(player.age_category),
                player.profile_url,
                _iso(player.last_fetched_at),
                _nfc(player.coach_notes),
            ),
        )

    def get(self, usta_id: str) -> Player | None:
        row = self._conn.execute(
            f"SELECT {self._PLAYER_COLUMNS} FROM players WHERE usta_id = ?",
            (usta_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_player(row)

    def list_all(self) -> list[Player]:
        rows = self._conn.execute(
            f"SELECT {self._PLAYER_COLUMNS} FROM players ORDER BY full_name"
        ).fetchall()
        return [self._row_to_player(r) for r in rows]

    def search_by_name(self, query: str) -> list[Player]:
        normalized = _nfc(query) or ""
        like = f"%{normalized.lower()}%"
        rows = self._conn.execute(
            f"""
            SELECT {self._PLAYER_COLUMNS} FROM players
            WHERE LOWER(full_name) LIKE ?
            ORDER BY full_name
            """,
            (like,),
        ).fetchall()
        return [self._row_to_player(r) for r in rows]

    def set_coach_notes(self, player_id: str, notes: str | None) -> None:
        """Set or clear the ``coach_notes`` field for a single player.

        Targeted setter so UI write-paths don't need to read the row,
        mutate the Pydantic model, and round-trip the whole thing back
        through :meth:`upsert`. ``notes`` is NFC-normalized; ``None``
        clears the column.
        """
        self._conn.execute(
            "UPDATE players SET coach_notes = ? WHERE usta_id = ?",
            (_nfc(notes), player_id),
        )

    @staticmethod
    def _row_to_player(row: tuple[Any, ...]) -> Player:
        (
            usta_id,
            full_name,
            first_name,
            last_name,
            gender,
            section,
            district,
            age_category,
            profile_url,
            last_fetched_at,
            coach_notes,
        ) = row
        return Player(
            usta_id=usta_id,
            full_name=full_name,
            first_name=first_name,
            last_name=last_name,
            gender=gender,
            section=section,
            district=district,
            age_category=age_category,
            profile_url=profile_url,
            last_fetched_at=_parse_datetime(last_fetched_at),
            coach_notes=coach_notes,
        )


# ---------------------------------------------------------------------------
# TournamentRepository
# ---------------------------------------------------------------------------


class TournamentRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, t: Tournament) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO tournaments (
                usta_id, name, level, sanction_body, start_date, end_date,
                location_city, location_state, surface, ball, entry_deadline,
                status, last_fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                t.usta_id,
                _nfc(t.name),
                _nfc(t.level),
                _nfc(t.sanction_body),
                _iso(t.start_date),
                _iso(t.end_date),
                _nfc(t.location_city),
                _nfc(t.location_state),
                t.surface,
                _nfc(t.ball),
                _iso(t.entry_deadline),
                t.status,
                _iso(t.last_fetched_at),
            ),
        )

    def get(self, usta_id: str) -> Tournament | None:
        row = self._conn.execute(
            "SELECT * FROM tournaments WHERE usta_id = ?", (usta_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_tournament(row)

    def list_upcoming(self) -> list[Tournament]:
        rows = self._conn.execute(
            "SELECT * FROM tournaments WHERE status = 'upcoming' ORDER BY start_date"
        ).fetchall()
        return [self._row_to_tournament(r) for r in rows]

    def list_in_progress(self) -> list[Tournament]:
        rows = self._conn.execute(
            "SELECT * FROM tournaments WHERE status = 'in_progress' ORDER BY start_date"
        ).fetchall()
        return [self._row_to_tournament(r) for r in rows]

    @staticmethod
    def _row_to_tournament(row: tuple[Any, ...]) -> Tournament:
        (
            usta_id,
            name,
            level,
            sanction_body,
            start_date,
            end_date,
            location_city,
            location_state,
            surface,
            ball,
            entry_deadline,
            status,
            last_fetched_at,
        ) = row
        return Tournament(
            usta_id=usta_id,
            name=name,
            level=level,
            sanction_body=sanction_body,
            start_date=_parse_date(start_date),
            end_date=_parse_date(end_date),
            location_city=location_city,
            location_state=location_state,
            surface=surface or "unknown",
            ball=ball,
            entry_deadline=_parse_datetime(entry_deadline),
            status=status or "upcoming",
            last_fetched_at=_parse_datetime(last_fetched_at),
        )


# ---------------------------------------------------------------------------
# DrawRepository
# ---------------------------------------------------------------------------


class DrawRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, d: Draw) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO draws (
                usta_id, tournament_id, name, format, size, gender,
                age_group, division, status, last_fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                d.usta_id,
                d.tournament_id,
                _nfc(d.name),
                d.format,
                d.size,
                _nfc(d.gender),
                _nfc(d.age_group),
                _nfc(d.division),
                _nfc(d.status),
                _iso(d.last_fetched_at),
            ),
        )

    def get(self, usta_id: str) -> Draw | None:
        row = self._conn.execute(
            "SELECT * FROM draws WHERE usta_id = ?", (usta_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_draw(row)

    def list_for_tournament(self, tournament_id: str) -> list[Draw]:
        rows = self._conn.execute(
            "SELECT * FROM draws WHERE tournament_id = ? ORDER BY name",
            (tournament_id,),
        ).fetchall()
        return [self._row_to_draw(r) for r in rows]

    @staticmethod
    def _row_to_draw(row: tuple[Any, ...]) -> Draw:
        (
            usta_id,
            tournament_id,
            name,
            fmt,
            size,
            gender,
            age_group,
            division,
            status,
            last_fetched_at,
        ) = row
        return Draw(
            usta_id=usta_id,
            tournament_id=tournament_id,
            name=name,
            format=fmt or "unknown",
            size=size,
            gender=gender,
            age_group=age_group,
            division=division,
            status=status,
            last_fetched_at=_parse_datetime(last_fetched_at),
        )


# ---------------------------------------------------------------------------
# DrawEntryRepository
# ---------------------------------------------------------------------------


class DrawEntryRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, e: DrawEntry) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO draw_entries (
                draw_id, player_id, seed, position, status
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                e.draw_id,
                e.player_id,
                e.seed,
                e.position,
                e.status,
            ),
        )

    def list_for_draw(self, draw_id: str) -> list[DrawEntry]:
        rows = self._conn.execute(
            """
            SELECT draw_id, player_id, seed, position, status
            FROM draw_entries
            WHERE draw_id = ?
            ORDER BY position IS NULL, position, player_id
            """,
            (draw_id,),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def list_for_player(self, player_id: str) -> list[DrawEntry]:
        rows = self._conn.execute(
            """
            SELECT draw_id, player_id, seed, position, status
            FROM draw_entries
            WHERE player_id = ?
            ORDER BY draw_id
            """,
            (player_id,),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    @staticmethod
    def _row_to_entry(row: tuple[Any, ...]) -> DrawEntry:
        draw_id, player_id, seed, position, status = row
        return DrawEntry(
            draw_id=draw_id,
            player_id=player_id,
            seed=seed,
            position=position,
            status=status or "entered",
        )


# ---------------------------------------------------------------------------
# MatchRepository
# ---------------------------------------------------------------------------


class MatchRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, m: Match) -> None:
        if m.usta_id is None:
            # The schema declares usta_id as PRIMARY KEY (NOT NULL implied).
            # Per DATA_MODEL.md a Match without a USTA-assigned ID isn't yet
            # persistable. Surface the ambiguity rather than fabricate a key.
            raise ValueError("Match.usta_id is required to persist; got None")
        sets_json = json.dumps([s.model_dump() for s in m.sets]) if m.sets else None
        self._conn.execute(
            """
            INSERT OR REPLACE INTO matches (
                usta_id, draw_id, round, scheduled_at, court,
                player_a_id, player_b_id, score_raw, sets_json,
                outcome, winner_id, last_fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                m.usta_id,
                m.draw_id,
                _nfc(m.round),
                _iso(m.scheduled_at),
                _nfc(m.court),
                m.player_a_id,
                m.player_b_id,
                m.score_raw,
                sets_json,
                m.outcome,
                m.winner_id,
                _iso(m.last_fetched_at),
            ),
        )

    def get(self, usta_id: str) -> Match | None:
        row = self._conn.execute(
            "SELECT * FROM matches WHERE usta_id = ?", (usta_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_match(row)

    def list_for_draw(self, draw_id: str) -> list[Match]:
        rows = self._conn.execute(
            "SELECT * FROM matches WHERE draw_id = ? ORDER BY scheduled_at IS NULL, scheduled_at",
            (draw_id,),
        ).fetchall()
        return [self._row_to_match(r) for r in rows]

    def list_for_player(self, player_id: str) -> list[Match]:
        rows = self._conn.execute(
            """
            SELECT * FROM matches
            WHERE player_a_id = ? OR player_b_id = ?
            ORDER BY scheduled_at IS NULL, scheduled_at
            """,
            (player_id, player_id),
        ).fetchall()
        return [self._row_to_match(r) for r in rows]

    def list_h2h(self, player_a_id: str, player_b_id: str) -> list[Match]:
        rows = self._conn.execute(
            """
            SELECT * FROM matches
            WHERE (player_a_id = ? AND player_b_id = ?)
               OR (player_a_id = ? AND player_b_id = ?)
            ORDER BY scheduled_at IS NULL, scheduled_at
            """,
            (player_a_id, player_b_id, player_b_id, player_a_id),
        ).fetchall()
        return [self._row_to_match(r) for r in rows]

    @staticmethod
    def _row_to_match(row: tuple[Any, ...]) -> Match:
        (
            usta_id,
            draw_id,
            round_label,
            scheduled_at,
            court,
            player_a_id,
            player_b_id,
            score_raw,
            sets_json,
            outcome,
            winner_id,
            last_fetched_at,
        ) = row
        sets: list[SetScore] = []
        if sets_json:
            sets = [SetScore(**item) for item in json.loads(sets_json)]
        return Match(
            usta_id=usta_id,
            draw_id=draw_id,
            round=round_label,
            scheduled_at=_parse_datetime(scheduled_at),
            court=court,
            player_a_id=player_a_id,
            player_b_id=player_b_id,
            score_raw=score_raw,
            sets=sets,
            outcome=outcome or "unknown",
            winner_id=winner_id,
            last_fetched_at=_parse_datetime(last_fetched_at),
        )


# ---------------------------------------------------------------------------
# RankingSnapshotRepository
# ---------------------------------------------------------------------------


class RankingSnapshotRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, s: RankingSnapshot) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO ranking_snapshots (
                player_id, category, scope, section, position, points, as_of
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                s.player_id,
                _nfc(s.category),
                _nfc(s.scope),
                _nfc(s.section),
                s.position,
                s.points,
                _iso(s.as_of),
            ),
        )

    def latest_for_player(self, player_id: str, category: str) -> RankingSnapshot | None:
        row = self._conn.execute(
            """
            SELECT player_id, category, scope, section, position, points, as_of
            FROM ranking_snapshots
            WHERE player_id = ? AND category = ?
            ORDER BY as_of DESC
            LIMIT 1
            """,
            (player_id, _nfc(category)),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_snapshot(row)

    def history_for_player(self, player_id: str, category: str) -> list[RankingSnapshot]:
        rows = self._conn.execute(
            """
            SELECT player_id, category, scope, section, position, points, as_of
            FROM ranking_snapshots
            WHERE player_id = ? AND category = ?
            ORDER BY as_of
            """,
            (player_id, _nfc(category)),
        ).fetchall()
        return [self._row_to_snapshot(r) for r in rows]

    @staticmethod
    def _row_to_snapshot(row: tuple[Any, ...]) -> RankingSnapshot:
        player_id, category, scope, section, position, points, as_of = row
        return RankingSnapshot(
            player_id=player_id,
            category=category,
            scope=scope,
            section=section,
            position=position,
            points=points,
            as_of=_parse_date(as_of) or date.min,
        )


# ---------------------------------------------------------------------------
# WTNSnapshotRepository
# ---------------------------------------------------------------------------


class WTNSnapshotRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, s: WTNSnapshot) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO wtn_snapshots (
                player_id, type, value, confidence, as_of
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                s.player_id,
                s.type,
                s.value,
                s.confidence,
                _iso(s.as_of),
            ),
        )

    def latest_for_player(self, player_id: str, type: str) -> WTNSnapshot | None:
        row = self._conn.execute(
            """
            SELECT player_id, type, value, confidence, as_of
            FROM wtn_snapshots
            WHERE player_id = ? AND type = ?
            ORDER BY as_of DESC
            LIMIT 1
            """,
            (player_id, type),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_snapshot(row)

    def history_for_player(self, player_id: str, type: str) -> list[WTNSnapshot]:
        rows = self._conn.execute(
            """
            SELECT player_id, type, value, confidence, as_of
            FROM wtn_snapshots
            WHERE player_id = ? AND type = ?
            ORDER BY as_of
            """,
            (player_id, type),
        ).fetchall()
        return [self._row_to_snapshot(r) for r in rows]

    @staticmethod
    def _row_to_snapshot(row: tuple[Any, ...]) -> WTNSnapshot:
        player_id, type_, value, confidence, as_of = row
        return WTNSnapshot(
            player_id=player_id,
            type=type_,
            value=value,
            confidence=confidence,
            as_of=_parse_date(as_of) or date.min,
        )


# ---------------------------------------------------------------------------
# SyncRunRepository
# ---------------------------------------------------------------------------


# Field names that ``update`` accepts. Keeping this an explicit allowlist
# prevents the **fields kwargs path from reaching arbitrary columns.
_SYNC_RUN_UPDATABLE_FIELDS = frozenset(
    {
        "started_at",
        "finished_at",
        "source",
        "status",
        "fetched_count",
        "parsed_count",
        "persisted_count",
        "errored_count",
        "error_summary",
        "log_text",
    }
)


def _utcnow_iso() -> str:
    """Return current UTC time as ISO-8601 (with timezone)."""
    return datetime.now(UTC).isoformat()


class SyncRunRepository:
    """CRUD for the operational ``sync_runs`` table.

    Unlike the entity repositories above this one **does** commit on its
    own, because callers tend to be operational code paths (CLI, UI) that
    want each row durable as soon as it's written rather than batched into
    a wider transaction. The row is small and the writes are infrequent, so
    the per-call commit is not a contention concern.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def start(self, source: str) -> int:
        """Insert a new ``running`` row and return its autoincrement id."""
        cursor = self._conn.execute(
            """
            INSERT INTO sync_runs (
                started_at, finished_at, source, status,
                fetched_count, parsed_count, persisted_count, errored_count,
                error_summary, log_text
            ) VALUES (?, NULL, ?, 'running', 0, 0, 0, 0, NULL, '')
            """,
            (_utcnow_iso(), source),
        )
        self._conn.commit()
        run_id = cursor.lastrowid
        if run_id is None:  # pragma: no cover - sqlite always returns one
            raise RuntimeError("SyncRunRepository.start: lastrowid was None")
        return int(run_id)

    def update(self, run_id: int, **fields: Any) -> None:
        """Patch a subset of columns on an existing run row.

        Only fields in :data:`_SYNC_RUN_UPDATABLE_FIELDS` are permitted;
        anything else raises ``ValueError`` so a caller's typo doesn't
        silently no-op.
        """
        if not fields:
            return
        unknown = set(fields) - _SYNC_RUN_UPDATABLE_FIELDS
        if unknown:
            raise ValueError(f"SyncRunRepository.update: unknown fields {sorted(unknown)}")
        assignments = ", ".join(f"{k} = ?" for k in fields)
        params = [*fields.values(), run_id]
        self._conn.execute(
            f"UPDATE sync_runs SET {assignments} WHERE id = ?",
            params,
        )
        self._conn.commit()

    def finish(
        self,
        run_id: int,
        status: str,
        fetched: int,
        parsed: int,
        persisted: int,
        errored: int,
        error_summary: str | None,
        log_text: str,
    ) -> None:
        """Final UPDATE that stamps ``finished_at`` and writes the captured log."""
        self._conn.execute(
            """
            UPDATE sync_runs
               SET finished_at    = ?,
                   status         = ?,
                   fetched_count  = ?,
                   parsed_count   = ?,
                   persisted_count = ?,
                   errored_count  = ?,
                   error_summary  = ?,
                   log_text       = ?
             WHERE id = ?
            """,
            (
                _utcnow_iso(),
                status,
                fetched,
                parsed,
                persisted,
                errored,
                error_summary,
                log_text,
                run_id,
            ),
        )
        self._conn.commit()

    def latest(self) -> SyncRun | None:
        row = self._conn.execute(
            "SELECT * FROM sync_runs ORDER BY started_at DESC, id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return self._row_to_run(row)

    def recent(self, limit: int = 10) -> list[SyncRun]:
        rows = self._conn.execute(
            "SELECT * FROM sync_runs ORDER BY started_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_run(r) for r in rows]

    def running(self) -> SyncRun | None:
        """Return the first row whose ``status`` is ``running``, or ``None``."""
        row = self._conn.execute(
            "SELECT * FROM sync_runs WHERE status = 'running' "
            "ORDER BY started_at DESC, id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return self._row_to_run(row)

    @staticmethod
    def _row_to_run(row: tuple[Any, ...]) -> SyncRun:
        (
            id_,
            started_at,
            finished_at,
            source,
            status,
            fetched_count,
            parsed_count,
            persisted_count,
            errored_count,
            error_summary,
            log_text,
        ) = row
        # The Pydantic model's Literal types are narrower than the column
        # storage. Defensive cast: if the DB has somehow stored an unknown
        # value (manual surgery, stray migration), surface it as-is and let
        # Pydantic validate.
        return SyncRun(
            id=id_,
            started_at=_parse_datetime(started_at) or datetime.min,
            finished_at=_parse_datetime(finished_at),
            source=_safe_source(source),
            status=_safe_status(status),
            fetched_count=fetched_count or 0,
            parsed_count=parsed_count or 0,
            persisted_count=persisted_count or 0,
            errored_count=errored_count or 0,
            error_summary=error_summary,
            log_text=log_text or "",
        )


def _safe_source(value: str) -> SyncRunSource:
    if value in {"usta_api", "tennislink", "clubspark", "multi"}:
        return value  # type: ignore[return-value]
    # Anything stored outside the taxonomy is treated as "multi" — the
    # generic bucket — so the UI never crashes on a stray value.
    return "multi"


def _safe_status(value: str) -> SyncRunStatus:
    if value in {"running", "ok", "partial", "failed"}:
        return value  # type: ignore[return-value]
    return "failed"


# ---------------------------------------------------------------------------
# MatchJournalRepository
# ---------------------------------------------------------------------------


class MatchJournalRepository:
    """CRUD for post-match journal entries.

    Identity in the DB is ``(player_id, match_id)`` enforced by a UNIQUE
    constraint with ``ON CONFLICT REPLACE``, but we don't rely on the
    REPLACE behavior for upserts because it would lose ``created_at`` (the
    REPLACE deletes the old row and inserts a new one with a new
    ``id``/``created_at``). Instead :meth:`upsert` does an explicit lookup
    + UPDATE/INSERT so ``created_at`` is preserved across edits and the
    autoincrement id is stable across the entry's lifetime.
    """

    _COLUMNS = (
        "id, match_id, player_id, created_at, updated_at, "
        "body, self_rating, tags"
    )

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, entry: MatchJournalEntry) -> int:
        """Insert or update by ``(player_id, match_id)``. Returns row id.

        ``updated_at`` is bumped on every upsert; ``created_at`` is set on
        first insert and preserved on update.
        """
        body = _nfc(entry.body) or ""
        tags_json = json.dumps(list(entry.tags))
        now_iso = _utcnow_iso()
        # Look up the existing row (player_id, match_id) — using IS for
        # NULL-safe equality so untethered notes (match_id=NULL) match.
        existing = self._conn.execute(
            """
            SELECT id, created_at FROM match_journal
            WHERE player_id = ? AND match_id IS ?
            """,
            (entry.player_id, entry.match_id),
        ).fetchone()
        if existing is not None:
            existing_id, existing_created_at = existing
            self._conn.execute(
                """
                UPDATE match_journal
                   SET updated_at = ?,
                       body = ?,
                       self_rating = ?,
                       tags = ?
                 WHERE id = ?
                """,
                (now_iso, body, entry.self_rating, tags_json, existing_id),
            )
            return int(existing_id)

        created_at_iso = _iso(entry.created_at) or now_iso
        cursor = self._conn.execute(
            """
            INSERT INTO match_journal (
                match_id, player_id, created_at, updated_at,
                body, self_rating, tags
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.match_id,
                entry.player_id,
                created_at_iso,
                now_iso,
                body,
                entry.self_rating,
                tags_json,
            ),
        )
        new_id = cursor.lastrowid
        if new_id is None:  # pragma: no cover - sqlite always returns one
            raise RuntimeError("MatchJournalRepository.upsert: lastrowid was None")
        return int(new_id)

    def get(self, entry_id: int) -> MatchJournalEntry | None:
        row = self._conn.execute(
            f"SELECT {self._COLUMNS} FROM match_journal WHERE id = ?",
            (entry_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_entry(row)

    def list_for_player(self, player_id: str) -> list[MatchJournalEntry]:
        rows = self._conn.execute(
            f"""
            SELECT {self._COLUMNS} FROM match_journal
            WHERE player_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (player_id,),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def for_match(self, player_id: str, match_id: str) -> MatchJournalEntry | None:
        row = self._conn.execute(
            f"""
            SELECT {self._COLUMNS} FROM match_journal
            WHERE player_id = ? AND match_id = ?
            """,
            (player_id, match_id),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_entry(row)

    def delete(self, entry_id: int) -> bool:
        """Delete by id. Returns True on hit, False on miss."""
        cursor = self._conn.execute(
            "DELETE FROM match_journal WHERE id = ?", (entry_id,)
        )
        return cursor.rowcount > 0

    @staticmethod
    def _row_to_entry(row: tuple[Any, ...]) -> MatchJournalEntry:
        (
            id_,
            match_id,
            player_id,
            created_at,
            updated_at,
            body,
            self_rating,
            tags,
        ) = row
        parsed_tags: list[str] = json.loads(tags) if tags else []
        return MatchJournalEntry(
            id=id_,
            match_id=match_id,
            player_id=player_id,
            created_at=_parse_datetime(created_at) or datetime.min,
            updated_at=_parse_datetime(updated_at) or datetime.min,
            body=body or "",
            self_rating=self_rating,
            tags=parsed_tags,
        )
