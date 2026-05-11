"""Unit tests for :mod:`src.parse.usta_api`.

Drives the parser with the captured live fixtures in
``tests/fixtures/usta_api/`` and validates the shape mapping.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.parse.usta_api import (
    ParseError,
    parse_tournament_hit,
    parse_tournaments_envelope,
)


FIXTURES = Path(__file__).parent.parent / "fixtures" / "usta_api"


def _load(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text())  # type: ignore[no-any-return]


def test_parse_florida_junior_envelope_maps_50_tournaments() -> None:
    envelope = _load("tournaments_query_florida_junior.json")
    pairs = parse_tournaments_envelope(envelope)
    assert len(pairs) == 50

    tournament, draws = pairs[0]
    assert tournament.usta_id == "4d734b7e-140a-483e-adfa-1f0a516bce7d"
    assert tournament.name == "2025 Heartland Conference"
    assert tournament.location_state == "FL"
    assert tournament.location_city == "SEBRING"
    assert tournament.surface == "hard"
    assert tournament.ball == "yellow"
    assert tournament.sanction_body == "USTA"
    assert tournament.start_date is not None
    assert tournament.end_date is not None
    assert tournament.entry_deadline is not None
    # 4 events in the source → 4 Draw rows.
    assert len(draws) == 4
    for d in draws:
        assert d.tournament_id == tournament.usta_id
        assert d.usta_id.startswith(f"{tournament.usta_id}:")
        assert d.age_group == "U18"
        assert d.gender in {"Boys", "Girls"}


def test_parse_florida_adult_envelope_returns_50_tournaments() -> None:
    envelope = _load("tournaments_query_florida_adult.json")
    pairs = parse_tournaments_envelope(envelope)
    assert len(pairs) == 50
    assert all(t.sanction_body == "USTA" for t, _ in pairs)


def test_parse_empty_envelope_returns_empty_list() -> None:
    envelope = {
        "took": 1,
        "hits": {"total": {"value": 0, "relation": "eq"}, "hits": []},
    }
    assert parse_tournaments_envelope(envelope) == []


def test_parse_non_dict_envelope_raises() -> None:
    with pytest.raises(ParseError):
        parse_tournaments_envelope("not a dict")  # type: ignore[arg-type]


def test_parse_hit_without_id_returns_none() -> None:
    pair = parse_tournament_hit({"_source": {"name": "name only"}})
    assert pair is None


def test_parse_hit_status_derives_from_dates() -> None:
    now = datetime(2026, 5, 11, tzinfo=UTC)
    upcoming = {
        "_id": "u",
        "_source": {
            "id": "u",
            "name": "Future event",
            "startDateTime": "2030-01-01T00:00:00+00:00",
            "endDateTime": "2030-01-02T00:00:00+00:00",
        },
    }
    completed = {
        "_id": "c",
        "_source": {
            "id": "c",
            "name": "Past event",
            "startDateTime": "2020-01-01T00:00:00+00:00",
            "endDateTime": "2020-01-02T00:00:00+00:00",
        },
    }
    in_progress = {
        "_id": "p",
        "_source": {
            "id": "p",
            "name": "Live event",
            "startDateTime": "2026-05-10T00:00:00+00:00",
            "endDateTime": "2026-05-12T00:00:00+00:00",
        },
    }
    cancelled = {
        "_id": "x",
        "_source": {
            "id": "x",
            "name": "Cancelled event",
            "isCancelled": True,
            "startDateTime": "2030-01-01T00:00:00+00:00",
            "endDateTime": "2030-01-02T00:00:00+00:00",
        },
    }
    assert parse_tournament_hit(upcoming, fetched_at=now)[0].status == "upcoming"  # type: ignore[index]
    assert parse_tournament_hit(completed, fetched_at=now)[0].status == "completed"  # type: ignore[index]
    assert parse_tournament_hit(in_progress, fetched_at=now)[0].status == "in_progress"  # type: ignore[index]
    assert parse_tournament_hit(cancelled, fetched_at=now)[0].status == "cancelled"  # type: ignore[index]


def test_parse_hit_surface_picks_most_common() -> None:
    hit = {
        "_id": "x",
        "_source": {
            "id": "x",
            "name": "Mixed surfaces",
            "events": [
                {"id": "e1", "surface": "hard"},
                {"id": "e2", "surface": "hard"},
                {"id": "e3", "surface": "clay"},
            ],
        },
    }
    tournament, _ = parse_tournament_hit(hit)  # type: ignore[misc]
    assert tournament.surface == "hard"


def test_parse_hit_event_to_draw_handles_doubles() -> None:
    hit = {
        "_id": "x",
        "_source": {
            "id": "x",
            "name": "Doubles only",
            "events": [
                {
                    "id": "e1",
                    "surface": "clay",
                    "division": {
                        "ageCategory": {"todsCode": "U16", "maximumAge": 16},
                        "eventType": "doubles",
                        "gender": "girls",
                    },
                    "isPublished": True,
                    "ballColour": "yellow",
                }
            ],
        },
    }
    tournament, draws = parse_tournament_hit(hit)  # type: ignore[misc]
    assert tournament.surface == "clay"
    assert len(draws) == 1
    d = draws[0]
    assert d.age_group == "U16"
    assert d.gender == "Girls"
    assert d.division == "Girls U16 Doubles"
    assert d.status == "published"


def test_parse_wheelchair_envelope() -> None:
    envelope = _load("tournaments_query_wheelchair.json")
    pairs = parse_tournaments_envelope(envelope)
    # Some hits in this fixture lack events or have non-standard shapes
    # — just make sure we don't crash and we return at least one row.
    assert len(pairs) >= 1
