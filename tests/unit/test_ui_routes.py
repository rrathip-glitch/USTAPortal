"""Smoke tests for the UI routes.

Every page must render 200 against an empty database — repository calls fail
through to the empty state rather than 500.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


def test_dashboard_renders_empty() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "USTA Portal" in response.text
    assert "Dashboard" in response.text


def test_tournaments_list_renders_empty() -> None:
    response = client.get("/tournaments")
    assert response.status_code == 200
    assert "USTA Portal" in response.text
    assert "Tournaments" in response.text


def test_tournament_detail_unknown_id_renders_empty_state() -> None:
    response = client.get("/tournaments/does-not-exist")
    assert response.status_code == 200
    assert "USTA Portal" in response.text
    assert "not found" in response.text.lower() or "no data" in response.text.lower()


def test_draw_detail_unknown_id_renders_empty_state() -> None:
    response = client.get("/draws/does-not-exist")
    assert response.status_code == 200
    assert "USTA Portal" in response.text
    assert "not found" in response.text.lower() or "no data" in response.text.lower()


def test_player_card_unknown_id_renders_empty_state() -> None:
    response = client.get("/players/does-not-exist")
    assert response.status_code == 200
    assert "USTA Portal" in response.text
    assert "not found" in response.text.lower() or "no data" in response.text.lower()


def test_h2h_renders_empty() -> None:
    response = client.get("/h2h/player-a/player-b")
    assert response.status_code == 200
    assert "USTA Portal" in response.text
    assert "Head-to-head" in response.text


def test_sync_get_renders() -> None:
    response = client.get("/sync")
    assert response.status_code == 200
    assert "USTA Portal" in response.text
    assert "Sync" in response.text


def test_sync_post_returns_placeholder_message() -> None:
    response = client.post("/sync")
    assert response.status_code == 200
    assert "Sync queued" in response.text


def test_static_css_served() -> None:
    response = client.get("/static/style.css")
    assert response.status_code == 200
    assert "site-header" in response.text
