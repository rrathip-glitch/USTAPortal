"""Smoke tests for the ``/rankings/u12-boys-national`` UI route."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


def test_rankings_route_renders_empty_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no ranking list synced, the page renders the friendly empty state."""
    db_file = tmp_path / "empty.db"
    db_url = f"sqlite:///{db_file}"

    from src import config as config_module

    monkeypatch.setattr(config_module.settings, "database_url", db_url)

    response = client.get("/rankings/u12-boys-national")
    assert response.status_code == 200
    # Jinja autoescapes the apostrophe in "Boys' 12s" — unescape the body
    # for the readability assertion.
    from markupsafe import Markup

    body = Markup(response.text).unescape()
    assert "Boys' 12s" in body
    # Empty-state message points the user at the CLI command.
    assert "No ranking list synced yet" in body
    assert "sync-rankings" in body


def test_rankings_route_renders_entries_with_janav_highlight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A synthetic list renders the table with Janav's row marked as user-highlight."""
    db_file = tmp_path / "synth.db"
    db_url = f"sqlite:///{db_file}"
    janav_id = "971BA48D-A2EA-4FB7-8305-F42EA466F6DF"

    from src import config as config_module

    monkeypatch.setattr(config_module.settings, "database_url", db_url)
    monkeypatch.setattr(config_module.settings, "usta_user_player_id", janav_id)

    # Stand up the schema and seed one ranking list + 2 entries (one is
    # Janav, the other isn't).
    from src.models.player import Player
    from src.models.ranking import RankingList, RankingListEntry
    from src.store.db import connect, init_schema
    from src.store.repositories import (
        PlayerRepository,
        RankingListRepository,
    )

    conn = connect()
    try:
        init_schema(conn)

        player_repo = PlayerRepository(conn)
        player_repo.upsert(Player(usta_id=janav_id, full_name="Janav Thasen"))
        player_repo.upsert(Player(usta_id="other-1", full_name="Other Player"))

        repo = RankingListRepository(conn)
        list_obj = RankingList(
            id="u12-boys-national-2026-05-11",
            age_category="Boys 12s",
            gender="M",
            scope="national",
            section=None,
            as_of=date(2026, 5, 11),
            source="clubspark",
            total_players=2,
            fetched_at=datetime(2026, 5, 11, 12, 0, tzinfo=UTC),
        )
        repo.upsert_list(list_obj)
        repo.upsert_entry(
            RankingListEntry(
                list_id=list_obj.id,
                position=1,
                player_usta_id="other-1",
                player_name_raw="Other Player",
                points=1800,
                section="Southern",
                wtn_singles=10.4,
                wtn_doubles=12.1,
            )
        )
        repo.upsert_entry(
            RankingListEntry(
                list_id=list_obj.id,
                position=2,
                player_usta_id=janav_id,
                player_name_raw="Thasen, Janav",
                points=1500,
                section="Florida",
                wtn_singles=12.3,
                wtn_doubles=15.7,
            )
        )
        conn.commit()
    finally:
        conn.close()

    response = client.get("/rankings/u12-boys-national")
    assert response.status_code == 200
    # Unescape for readable assertions; Jinja autoescapes HTML-special chars.
    from markupsafe import Markup

    body = Markup(response.text).unescape()

    # Column headers
    assert "Rank" in body
    assert "Player" in body
    assert "Section" in body
    assert "Points" in body
    assert "WTN-S" in body
    assert "WTN-D" in body

    # Entries render — both players present
    assert "Other Player" in body
    assert "Thasen, Janav" in body

    # Janav's row carries the user-highlight class; the other player does
    # not. The simplest reliable check: the highlight class appears in
    # the body, and the link to Janav's player card appears alongside it.
    assert "user-highlight" in body
    assert f"/players/{janav_id}" in body

    # The WTN numbers render with one-decimal formatting.
    assert "12.3" in body
    assert "15.7" in body
