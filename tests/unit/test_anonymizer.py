"""Tests for the fixture anonymizer (tests/anonymize.py)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.anonymize import anonymize, anonymize_string

REAL_GUID = "11111111-2222-3333-4444-555555555555"
OTHER_GUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _sample_payload() -> dict[str, Any]:
    return {
        "playerId": REAL_GUID,
        "tournamentId": "12345678",
        "firstName": "Janav",
        "lastName": "Patel",
        "displayName": "Janav Patel",
        "email": "janav@example.com",
        "phone": "+1-555-123-4567",
        "wtnSingles": 18.4,  # rating, preserved
        "rating": 4.5,
        "scheduledAt": "2026-05-10T09:00:00Z",
        "score": "6-4 6-3",
        "notes": (
            f"Player {REAL_GUID} defeated opponent in tournament 12345678."
        ),
        "draws": [
            {
                "drawId": OTHER_GUID,
                "name": "Boys 16s Singles",  # 'name' field — anonymized
                "entries": [
                    {
                        "playerId": REAL_GUID,
                        "displayName": "Janav Patel",
                    },
                    {
                        "playerId": OTHER_GUID,
                        "displayName": "Other Person",
                    },
                ],
            }
        ],
        "metadata": {
            "createdBy": "system",  # not a name field, no scrubbing
            "active": True,
            "count": 5,
        },
    }


def test_round_trip_deterministic() -> None:
    """Anonymizing the same input twice produces identical output."""
    payload1 = _sample_payload()
    payload2 = _sample_payload()
    out1, map1 = anonymize(payload1)
    out2, map2 = anonymize(payload2)
    assert out1 == out2
    assert map1 == map2


def test_pii_fields_scrubbed() -> None:
    """Names, emails, phones, ids in a nested payload are scrubbed appropriately."""
    payload = _sample_payload()
    out, mapping = anonymize(payload)

    # IDs mapped, never equal to original.
    assert out["playerId"] != REAL_GUID
    assert out["playerId"] == mapping[REAL_GUID]
    assert out["tournamentId"] != "12345678"
    assert out["tournamentId"] == mapping["12345678"]

    # Names anonymized.
    assert out["firstName"].startswith("Player_")
    assert out["lastName"].startswith("Player_")
    assert out["displayName"].startswith("Player_")
    assert out["firstName"] != "Janav"

    # Email and phone zeroed.
    assert out["email"] == ""
    assert out["phone"] == ""

    # Ratings and timestamps preserved.
    assert out["wtnSingles"] == 18.4
    assert out["rating"] == 4.5
    assert out["scheduledAt"] == "2026-05-10T09:00:00Z"
    assert out["score"] == "6-4 6-3"

    # Free-form notes string had its embedded GUID and numeric ID swapped.
    assert REAL_GUID not in out["notes"]
    assert "12345678" not in out["notes"]
    assert mapping[REAL_GUID] in out["notes"]
    assert mapping["12345678"] in out["notes"]

    # Recursion into list of draws and nested entries.
    draw = out["draws"][0]
    assert draw["drawId"] == mapping[OTHER_GUID]
    assert draw["name"].startswith("Player_")
    assert draw["entries"][0]["playerId"] == mapping[REAL_GUID]
    assert draw["entries"][0]["displayName"].startswith("Player_")
    assert draw["entries"][1]["playerId"] == mapping[OTHER_GUID]

    # Metadata: non-PII scalars preserved.
    assert out["metadata"]["createdBy"] == "system"
    assert out["metadata"]["active"] is True
    assert out["metadata"]["count"] == 5


def test_anonymize_string_swaps_embedded_guid() -> None:
    """A free-form string with an embedded GUID gets the GUID swapped."""
    mapping: dict[str, str] = {}
    text = f"Match between {REAL_GUID} and {OTHER_GUID} on court 3."
    out = anonymize_string(text, mapping)
    assert REAL_GUID not in out
    assert OTHER_GUID not in out
    assert mapping[REAL_GUID] in out
    assert mapping[OTHER_GUID] in out
    # Non-id text preserved.
    assert "Match between" in out
    assert "on court 3." in out


def test_anonymize_string_swaps_embedded_numeric_id() -> None:
    """A free-form string with a 6+ digit number gets it swapped."""
    mapping: dict[str, str] = {}
    out = anonymize_string("user 12345678 logged in", mapping)
    assert "12345678" not in out
    assert mapping["12345678"] in out


def test_anonymize_string_preserves_short_numbers() -> None:
    """Short numbers (scores, dates fragments) are not treated as IDs."""
    mapping: dict[str, str] = {}
    out = anonymize_string("won 6-4 6-3 in 2 sets", mapping)
    assert out == "won 6-4 6-3 in 2 sets"
    assert mapping == {}


def test_mapping_persists_and_reloads(tmp_path: Path) -> None:
    """When mapping_path is supplied the mapping is written and reloaded."""
    map_path = tmp_path / "mapping.json"
    payload = _sample_payload()
    out1, map1 = anonymize(payload, mapping_path=map_path)

    assert map_path.exists()
    on_disk = json.loads(map_path.read_text())
    assert on_disk == map1
    assert REAL_GUID in on_disk

    # Reload: re-running uses the persisted mapping (deterministic anyway, but
    # this proves the round-trip).
    out2, map2 = anonymize(payload, mapping_path=map_path)
    assert out1 == out2
    assert map2 == map1


def test_numeric_id_under_id_key_as_int() -> None:
    """Integer values under id-shaped keys are mapped too."""
    payload: dict[str, Any] = {"playerId": 12345678}
    out, mapping = anonymize(payload)
    assert isinstance(out["playerId"], int)
    assert out["playerId"] != 12345678
    assert str(out["playerId"]).zfill(9) == mapping["12345678"]


def test_empty_input() -> None:
    out, mapping = anonymize({})
    assert out == {}
    assert mapping == {}


@pytest.mark.parametrize(
    "key",
    ["firstName", "lastName", "displayName", "fullName", "PlayerName"],
)
def test_name_keys_anonymized(key: str) -> None:
    out, _ = anonymize({key: "Real Person"})
    assert out[key].startswith("Player_")
    assert out[key] != "Real Person"
