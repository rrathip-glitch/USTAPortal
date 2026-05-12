"""Smoke tests for the ``/rankings`` UI route.

The rankings page is the user-facing surface for cross-platform data on
Janav Thasen. Its data comes from a captured CoreTennis fixture plus a
handful of static identifiers; the route must therefore:

- Return 200 even when no DB is available.
- Surface the hero subject ("Janav Thasen", "Boys 12s").
- Surface the TR national rank (146) and at least one captured opponent
  ("Lipinski") so the table is rendered.
- Communicate the open-lead state for the USTA Akamai-walled rankings
  endpoint — opaque data is worse than transparent data.
- Have a "Rankings" link in the nav so the new section is reachable.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


def test_rankings_route_returns_200() -> None:
    response = client.get("/rankings")
    assert response.status_code == 200


def test_rankings_page_surfaces_hero_subject() -> None:
    response = client.get("/rankings")
    body = response.text
    assert "Janav Thasen" in body
    assert "Boys 12s" in body


def test_rankings_page_shows_tr_national_rank() -> None:
    response = client.get("/rankings")
    # TR composite ranking 146 — the only fully-public national number we
    # have until the USTA rankings endpoint is unblocked.
    assert "146" in response.text


def test_rankings_page_includes_coretennis_opponent() -> None:
    response = client.get("/rankings")
    # Gustavo Lipinski is the first opponent in the captured fixture; if
    # this surfaces, the CoreTennis fixture parse made it through to the
    # template.
    assert "Lipinski" in response.text


def test_rankings_page_communicates_open_lead() -> None:
    """The Akamai-walled USTA endpoint MUST be honestly labelled."""
    response = client.get("/rankings")
    body = response.text.lower()
    # Either word is acceptable — both appear in the data-sources card.
    assert "auth-walled" in body or "akamai" in body


def test_nav_includes_rankings_link() -> None:
    response = client.get("/")
    # The home page renders the shared nav; the link must appear there too.
    assert 'href="/rankings"' in response.text
    assert "Rankings" in response.text
