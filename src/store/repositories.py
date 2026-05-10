"""Data access layer.

Each repository owns CRUD for one entity. Repositories never read from the
USTA site — they read/write the local SQLite DB and the raw cache. This is
the boundary that makes the app offline-first: every UI route hits a
repository, never a fetch client.
"""

from __future__ import annotations


class PlayerRepository:
    def upsert(self, _player: object) -> None:
        raise NotImplementedError


class TournamentRepository:
    def upsert(self, _tournament: object) -> None:
        raise NotImplementedError


class DrawRepository:
    def upsert(self, _draw: object) -> None:
        raise NotImplementedError


class MatchRepository:
    def upsert(self, _match: object) -> None:
        raise NotImplementedError
