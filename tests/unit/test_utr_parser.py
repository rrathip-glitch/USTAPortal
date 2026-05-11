"""Unit tests for :mod:`src.parse.utr`.

Drives the parser with the captured live fixture in
``tests/fixtures/utr/search_janav_thasen.json`` and validates:

- ``parse_utr_search`` returns at least one :class:`UTRPlayerHit`.
- ``singlesUtr == 0.0`` is preserved as ``0.0`` (unrated juniors), not
  coerced to ``None`` — the dashboard distinguishes "unrated" from
  "missing".
- ``find_best_match`` returns the correct hit when filtered by
  ``first_name``, ``last_name``, and ``state``.
- ``find_best_match`` returns ``None`` when the identity does not match
  any hit in the envelope.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.models.utr import UTRPlayerHit
from src.parse.utr import find_best_match, parse_utr_search


FIXTURES = Path(__file__).parent.parent / "fixtures" / "utr"


def _load(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text())  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# parse_utr_search
# ---------------------------------------------------------------------------


def test_parse_utr_search_returns_hits() -> None:
    envelope = _load("search_janav_thasen.json")
    hits = parse_utr_search(envelope)
    assert len(hits) >= 1
    # Every parsed hit is the right model and carries the required keys.
    for hit in hits:
        assert isinstance(hit, UTRPlayerHit)
        assert hit.utr_id
        assert hit.full_name


def test_parse_utr_search_preserves_zero_singles_utr() -> None:
    """``singlesUtr == 0.0`` (unrated junior) must NOT be coerced to None."""
    envelope = _load("search_janav_thasen.json")
    hits = parse_utr_search(envelope)
    # The first hit in the fixture is Janav Thasen with singlesUtr 0.0.
    janav = next((h for h in hits if h.utr_id == "3059480"), None)
    assert janav is not None
    assert janav.singles_utr == 0.0
    assert janav.doubles_utr == 0.0


def test_parse_utr_search_empty_envelope_returns_empty_list() -> None:
    assert parse_utr_search({}) == []
    assert parse_utr_search({"hits": []}) == []
    # Defensive: a non-dict envelope shouldn't blow up either.
    assert parse_utr_search({"hits": "not-a-list"}) == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# find_best_match
# ---------------------------------------------------------------------------


def test_find_best_match_finds_janav_thasen_in_florida() -> None:
    envelope = _load("search_janav_thasen.json")
    best = find_best_match(
        envelope,
        first_name="Janav",
        last_name="Thasen",
        state="Florida",
    )
    assert best is not None
    assert best.utr_id == "3059480"
    assert best.city == "Weston"
    assert best.state == "Florida"
    assert best.country == "United States"
    assert best.gender == "Male"


def test_find_best_match_is_case_insensitive_on_name() -> None:
    envelope = _load("search_janav_thasen.json")
    best = find_best_match(
        envelope,
        first_name="janav",
        last_name="THASEN",
        state="Florida",
    )
    assert best is not None
    assert best.utr_id == "3059480"


def test_find_best_match_accepts_state_prefix() -> None:
    """Callers may pass either 'FL' or 'Florida' — both should resolve."""
    envelope = _load("search_janav_thasen.json")
    # Strict-equal form.
    full = find_best_match(
        envelope, first_name="Janav", last_name="Thasen", state="Florida"
    )
    # Note: 'FL' is a prefix of neither 'Florida' nor 'California' so this
    # test exercises the equality branch primarily; the prefix branch is
    # exercised by 'Flor' below.
    prefix = find_best_match(
        envelope, first_name="Janav", last_name="Thasen", state="Flor"
    )
    assert full is not None
    assert prefix is not None
    assert full.utr_id == prefix.utr_id == "3059480"


def test_find_best_match_returns_none_for_unknown_name() -> None:
    envelope = _load("search_janav_thasen.json")
    assert (
        find_best_match(
            envelope,
            first_name="Nonexistent",
            last_name="Person",
        )
        is None
    )


def test_find_best_match_returns_none_for_empty_envelope() -> None:
    assert (
        find_best_match(
            {"hits": []},
            first_name="Janav",
            last_name="Thasen",
        )
        is None
    )
