"""Parser for UTR (Universal Tennis Rating) player-search responses.

Maps the ``/v2/search/players`` JSON envelope onto a list of
:class:`UTRPlayerHit` records and exposes a small ranking helper for
cross-referencing a known USTA player against the search results.

The envelope shape (truncated to fields we care about):

    {
      "hits": [
        {
          "id": "3059480",
          "source": {
            "firstName": "Janav",
            "lastName": "Thasen",
            "displayName": "Janav Thasen",
            "singlesUtr": 0.0,
            "doublesUtr": 0.0,
            "gender": "Male",
            "location": {
              "display": "Weston, FL",
              "cityName": "Weston",
              "stateName": "Florida",
              "countryName": "United States"
            }
          }
        },
        ...
      ],
      "total": 24,
      "totalAllowed": 20
    }

``singlesUtr`` / ``doublesUtr`` are kept as ``0.0`` (rather than collapsed to
``None``) when present so the dashboard can render "unrated" rather than
"unknown".
"""

from __future__ import annotations

from typing import Any

from src.models.utr import UTRPlayerHit

__all__ = ["find_best_match", "parse_utr_search"]


def parse_utr_search(envelope: dict[str, Any]) -> list[UTRPlayerHit]:
    """Map the UTR search envelope to a list of :class:`UTRPlayerHit`.

    Hits that lack both an id and a name are skipped — they're not useful
    to the dashboard and would otherwise produce a row with empty key
    fields that violate the Pydantic model. Every other hit is mapped
    even if individual optional fields are missing.
    """
    if not isinstance(envelope, dict):
        return []
    raw_hits = envelope.get("hits")
    if not isinstance(raw_hits, list):
        return []

    out: list[UTRPlayerHit] = []
    for hit in raw_hits:
        if not isinstance(hit, dict):
            continue
        parsed = _parse_single_hit(hit)
        if parsed is not None:
            out.append(parsed)
    return out


def find_best_match(
    envelope: dict[str, Any],
    *,
    first_name: str,
    last_name: str,
    state: str | None = None,
) -> UTRPlayerHit | None:
    """Return the best :class:`UTRPlayerHit` for the given identity, or None.

    Ranking:

    1. Filter to hits whose ``first_name`` and ``last_name`` both match
       case-insensitively (after stripping whitespace — the source data
       sometimes carries trailing spaces).
    2. If ``state`` is provided, prefer hits whose ``state`` either equals
       it exactly (case-insensitively) or whose ``state`` starts with the
       supplied prefix (case-insensitively) — that lets callers pass
       either "FL" or "Florida" and still match the source's full state
       name ("Florida").
    3. Among the remaining hits, prefer those with a non-zero
       ``singles_utr`` (i.e. actually rated).
    4. Return the first hit that survives all three filters; if a step
       eliminates everything, fall back to the prior step's set.
    """
    hits = parse_utr_search(envelope)
    if not hits:
        return None

    first_lc = first_name.strip().lower()
    last_lc = last_name.strip().lower()

    name_matches = [
        h for h in hits
        if (h.first_name or "").strip().lower() == first_lc
        and (h.last_name or "").strip().lower() == last_lc
    ]
    if not name_matches:
        return None

    candidates = name_matches
    if state is not None:
        state_lc = state.strip().lower()
        state_matches = [
            h for h in candidates
            if (h.state or "").strip().lower() == state_lc
            or (h.state or "").strip().lower().startswith(state_lc)
        ]
        if state_matches:
            candidates = state_matches

    rated = [h for h in candidates if (h.singles_utr or 0.0) > 0.0]
    if rated:
        candidates = rated

    return candidates[0]


# -----------------------------------------------------------------------------
# Internals
# -----------------------------------------------------------------------------


def _parse_single_hit(hit: dict[str, Any]) -> UTRPlayerHit | None:
    utr_id_raw = hit.get("id")
    if utr_id_raw is None:
        return None
    utr_id = str(utr_id_raw)

    source = hit.get("source") or {}
    if not isinstance(source, dict):
        source = {}

    first_name = _opt_str(source.get("firstName"))
    last_name = _opt_str(source.get("lastName"))
    display_name = _opt_str(source.get("displayName"))

    # Derive a non-empty full_name even if displayName is missing or blank.
    full_name = display_name or _join_name(first_name, last_name)
    if not full_name:
        # No usable identity for this hit — skip.
        return None

    location = source.get("location") or {}
    if not isinstance(location, dict):
        location = {}

    return UTRPlayerHit(
        utr_id=utr_id,
        full_name=full_name,
        first_name=first_name,
        last_name=last_name,
        singles_utr=_opt_float(source.get("singlesUtr")),
        doubles_utr=_opt_float(source.get("doublesUtr")),
        location_display=_opt_str(location.get("display")),
        city=_opt_str(location.get("cityName")),
        state=_opt_str(location.get("stateName")),
        country=_opt_str(location.get("countryName")),
        gender=_opt_str(source.get("gender")),
    )


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value)
    stripped = value.strip()
    return stripped or None


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        # ``bool`` is a subclass of ``int``; coerce defensively rather than
        # silently producing 0.0/1.0 from a JSON boolean.
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _join_name(first: str | None, last: str | None) -> str:
    parts = [p for p in (first, last) if p]
    return " ".join(parts)
