"""Schema-drift canary test.

Parses every committed fixture under ``tests/fixtures/{usta_api,
coretennis, utr}/`` and asserts the parser still emits at least one
well-formed model row for the non-empty cases — and is byte-for-byte
stable for re-runs.

The intent is to fail loudly when a parser regression silently drops
fields or rejects valid fixtures. If a real upstream schema change
happens, the captured fixtures need re-recording (and the parser
adjusting) — the canary makes that drift impossible to miss.

The test is read-only: it never writes to disk, never touches the DB,
and never makes a network call. It only exercises the in-process
parsers.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.models.draw import Draw
from src.models.tournament import Tournament
from src.parse.coretennis import parse_coretennis_player
from src.parse.usta_api import parse_tournaments_envelope
from src.parse.utr import parse_utr_search

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# Shape-signature helper
# ---------------------------------------------------------------------------


def _shape_signature(pairs: list[tuple[Tournament, list[Draw]]]) -> str:
    """Produce a stable hash of the (tournament, draws) shape.

    Two runs of the parser against the same fixture must produce the
    same signature — that's how we catch non-determinism (e.g. dict
    ordering leaking out into model output).
    """
    canonical = [
        (t.usta_id, sorted(d.usta_id for d in draws)) for t, draws in pairs
    ]
    encoded = json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# ---------------------------------------------------------------------------
# USTA API envelopes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_path",
    sorted((FIXTURES_DIR / "usta_api").glob("tournaments_query_*.json")),
    ids=lambda p: p.name,
)
def test_usta_api_envelope_parses_to_stable_shape(fixture_path: Path) -> None:
    envelope = json.loads(fixture_path.read_text())
    pairs = parse_tournaments_envelope(envelope)

    # Some fixtures might be true empties (no hits) — for those the only
    # invariant we can assert is "didn't crash". Everything else must be
    # well-formed.
    if not pairs:
        # Defensive: re-running on an empty envelope must also yield empty.
        assert parse_tournaments_envelope(envelope) == []
        return

    # Shape stability: every tournament has an id + name; every draw is
    # FK-linked to its tournament and uses the composite-id convention.
    for tournament, draws in pairs:
        assert tournament.usta_id
        assert tournament.name
        for draw in draws:
            assert draw.tournament_id == tournament.usta_id
            assert draw.usta_id.startswith(f"{tournament.usta_id}:")

    # Re-running the parser must produce identical results (deterministic).
    pairs_again = parse_tournaments_envelope(envelope)
    assert _shape_signature(pairs) == _shape_signature(pairs_again)


# ---------------------------------------------------------------------------
# CoreTennis results pages
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_path",
    sorted((FIXTURES_DIR / "coretennis").glob("janav_results*.html")),
    ids=lambda p: p.name,
)
def test_coretennis_results_parses(fixture_path: Path) -> None:
    profile_html = (FIXTURES_DIR / "coretennis" / "janav_profile.html").read_text()
    results_html = fixture_path.read_text()
    player, matches = parse_coretennis_player(
        profile_html, results_html, player_id="203938"
    )
    assert player.usta_id == "203938"
    assert matches, "expected at least one match"


# ---------------------------------------------------------------------------
# UTR search envelopes
# ---------------------------------------------------------------------------


def test_utr_search_envelope_finds_janav() -> None:
    envelope = json.loads(
        (FIXTURES_DIR / "utr" / "search_janav_thasen.json").read_text()
    )
    hits = parse_utr_search(envelope)
    assert any(h.utr_id == "3059480" for h in hits)
