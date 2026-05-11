"""Parsers for the anonymous USTA Play Tennis API.

Maps the ElasticSearch envelope returned by
:class:`src.fetch.usta_api_client.UstaApiClient` into the existing
Pydantic models (``Tournament``, ``Draw``). Each hit's
``_source`` carries one tournament plus a nested ``events`` list; the
events become :class:`Draw` rows keyed off the composite
``<tournament-id>:<event-id>`` shape (mirroring TennisLink's
``T=<t>:E=<e>``).

Why composite ids: the rest of the system already speaks the
TennisLink composite convention (``DrawRepository`` uses it for FK
lookups; the sync orchestrator strips the prefix when it needs the
tournament id alone). Reusing the convention means the UI templates
and the enrichment pipeline don't branch on source.

Surface, age category, gender mapping is conservative — anything we
can't confidently map drops to the model's default rather than
producing a confidently-wrong value (per DATA_MODEL.md "no silent
imputation").
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

from src.models.draw import Draw, DrawFormat
from src.models.tournament import Surface, Tournament, TournamentStatus

__all__ = [
    "ParseError",
    "parse_tournament_hit",
    "parse_tournaments_envelope",
]


class ParseError(RuntimeError):
    """Raised when the envelope or hit cannot be mapped onto our models."""


# --------------------------------------------------------------------------
# Envelope-level entry point
# --------------------------------------------------------------------------


def parse_tournaments_envelope(
    envelope: dict[str, Any],
    *,
    fetched_at: datetime | None = None,
) -> list[tuple[Tournament, list[Draw]]]:
    """Parse a full ``/playtennis/tournaments/query`` ES envelope.

    Returns one ``(Tournament, [Draw, ...])`` pair per hit. Tournaments
    whose ``_source`` is missing or empty are skipped silently — the API
    has been observed to return placeholder hits in edge cases.
    """
    if not isinstance(envelope, dict):
        raise ParseError(
            f"parse_tournaments_envelope: expected dict, got {type(envelope).__name__}"
        )
    hits_block = envelope.get("hits") or {}
    raw_hits = hits_block.get("hits") if isinstance(hits_block, dict) else None
    if not raw_hits:
        return []
    out: list[tuple[Tournament, list[Draw]]] = []
    for hit in raw_hits:
        try:
            pair = parse_tournament_hit(hit, fetched_at=fetched_at)
        except ParseError:
            continue
        if pair is None:
            continue
        out.append(pair)
    return out


# --------------------------------------------------------------------------
# Hit-level parser
# --------------------------------------------------------------------------


def parse_tournament_hit(
    hit: dict[str, Any],
    *,
    fetched_at: datetime | None = None,
) -> tuple[Tournament, list[Draw]] | None:
    """Parse one hit into a (Tournament, [Draws]) pair.

    Returns ``None`` if the hit has no usable id or name. Raises
    :class:`ParseError` only for structurally malformed inputs.
    """
    if not isinstance(hit, dict):
        raise ParseError(
            f"parse_tournament_hit: expected dict, got {type(hit).__name__}"
        )
    src = hit.get("_source") or {}
    if not isinstance(src, dict):
        raise ParseError("parse_tournament_hit: _source is not a dict")

    usta_id = str(src.get("id") or hit.get("_id") or "").strip()
    name = (src.get("name") or "").strip()
    if not usta_id or not name:
        return None

    when_fetched = fetched_at or datetime.now(UTC)

    primary_loc = src.get("primaryLocation") or {}
    if not isinstance(primary_loc, dict):
        primary_loc = {}

    level_obj = src.get("level") or {}
    if not isinstance(level_obj, dict):
        level_obj = {}

    events = src.get("events") or []
    if not isinstance(events, list):
        events = []

    start = _parse_iso_datetime(src.get("startDateTime"))
    end = _parse_iso_datetime(src.get("endDateTime"))
    entries_close = _parse_iso_datetime(
        (src.get("registrationRestrictions") or {}).get("entriesCloseDateTime")
    )

    is_cancelled = bool(src.get("isCancelled"))

    tournament = Tournament(
        usta_id=usta_id,
        name=_clean_text(name),
        level=_clean_text(level_obj.get("name")) if level_obj else None,
        sanction_body="USTA",
        start_date=start.date() if start else None,
        end_date=end.date() if end else None,
        location_city=_clean_text(primary_loc.get("town")),
        location_state=_clean_text(primary_loc.get("county"))
        or _state_from_postcode(primary_loc.get("postcode")),
        surface=_choose_surface(events),
        ball=_choose_ball(events),
        entry_deadline=entries_close,
        status=_derive_status(start, end, is_cancelled, now=when_fetched),
        last_fetched_at=when_fetched,
    )

    draws = [
        _event_to_draw(
            event,
            tournament=tournament,
            fetched_at=when_fetched,
        )
        for event in events
        if isinstance(event, dict)
    ]
    # Drop events that didn't have a usable id.
    draws = [d for d in draws if d is not None]
    return tournament, draws  # type: ignore[return-value]


# --------------------------------------------------------------------------
# Event → Draw
# --------------------------------------------------------------------------


_DOUBLES_LABEL_RE = re.compile(r"doubles?", re.I)
_GENDER_NORMAL: dict[str, str] = {
    "boys": "Boys",
    "girls": "Girls",
    "men": "Men",
    "women": "Women",
    "male": "Boys",
    "female": "Girls",
    "mixed": "Mixed",
}


def _event_to_draw(
    event: dict[str, Any],
    *,
    tournament: Tournament,
    fetched_at: datetime,
) -> Draw | None:
    event_id = str(event.get("id") or "").strip()
    if not event_id:
        return None

    division = event.get("division") or {}
    if not isinstance(division, dict):
        division = {}
    age_cat = division.get("ageCategory") or {}
    if not isinstance(age_cat, dict):
        age_cat = {}

    event_type_raw = str(event.get("eventType") or division.get("eventType") or "").lower()
    is_doubles = bool(_DOUBLES_LABEL_RE.search(event_type_raw))

    gender_raw = (
        event.get("gender")
        or division.get("gender")
        or ""
    )
    gender_label = _GENDER_NORMAL.get(str(gender_raw).strip().lower(), str(gender_raw).strip() or None)

    age_label = _format_age_label(age_cat)
    level_block = event.get("level") or {}
    if not isinstance(level_block, dict):
        level_block = {}

    division_label = _build_division_label(gender_label, age_label, event_type_raw)
    name = division_label or _clean_text(level_block.get("name")) or "Event"

    return Draw(
        usta_id=f"{tournament.usta_id}:{event_id}",
        tournament_id=tournament.usta_id,
        name=name,
        format=_choose_draw_format(event),
        size=None,
        gender=gender_label,
        age_group=age_label,
        division=division_label,
        status="published" if event.get("isPublished") else "unpublished",
        last_fetched_at=fetched_at,
    )


def _format_age_label(age_cat: dict[str, Any]) -> str | None:
    tods = age_cat.get("todsCode")
    if isinstance(tods, str) and tods.strip():
        return tods.strip()
    max_age = age_cat.get("maximumAge")
    if isinstance(max_age, int):
        return f"U{max_age}"
    return None


def _build_division_label(
    gender: str | None, age: str | None, event_type: str
) -> str | None:
    parts: list[str] = []
    if gender:
        parts.append(gender)
    if age:
        parts.append(age)
    if event_type:
        parts.append(event_type.title())
    if not parts:
        return None
    return " ".join(parts).strip()


def _choose_draw_format(event: dict[str, Any]) -> DrawFormat:
    fmt = str(event.get("drawType") or event.get("format") or "").lower().strip()
    mapping: dict[str, DrawFormat] = {
        "single_elimination": "single_elimination",
        "single elimination": "single_elimination",
        "se": "single_elimination",
        "single_elimination_with_consolation": "single_elimination_with_consolation",
        "consolation": "single_elimination_with_consolation",
        "round_robin": "round_robin",
        "round robin": "round_robin",
        "rr": "round_robin",
        "compass": "compass",
        "feed_in": "feed_in",
        "feed in": "feed_in",
    }
    return mapping.get(fmt, "unknown")


# --------------------------------------------------------------------------
# Surface / ball mapping
# --------------------------------------------------------------------------


_SURFACE_MAP: dict[str, Surface] = {
    "hard": "hard",
    "clay": "clay",
    "grass": "grass",
    "indoor": "indoor_hard",
    "indoor_hard": "indoor_hard",
    "carpet": "carpet",
}


def _choose_surface(events: list[dict[str, Any]]) -> Surface:
    """Pick the most common surface across the tournament's events.

    Falls back to ``unknown`` if no event carries a known surface. The
    USTA API uses lowercase strings (``hard``, ``clay``, ``grass``).
    """
    counts: dict[Surface, int] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        raw = str(event.get("surface") or "").strip().lower()
        mapped = _SURFACE_MAP.get(raw)
        if mapped is not None:
            counts[mapped] = counts.get(mapped, 0) + 1
    if not counts:
        return "unknown"
    # Ties: prefer the canonical "hard" if it's in the running.
    if "hard" in counts and counts["hard"] == max(counts.values()):
        return "hard"
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _choose_ball(events: list[dict[str, Any]]) -> str | None:
    """Pick the most common ball colour across the tournament's events."""
    counts: dict[str, int] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        raw = str(event.get("ballColour") or event.get("ballColor") or "").strip().lower()
        if raw:
            counts[raw] = counts.get(raw, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            # Python 3.11+ fromisoformat handles trailing "Z".
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    return None


def _derive_status(
    start: datetime | None,
    end: datetime | None,
    cancelled: bool,
    *,
    now: datetime,
) -> TournamentStatus:
    if cancelled:
        return "cancelled"
    if start is None and end is None:
        return "upcoming"
    today: date = now.astimezone(UTC).date()
    if end is not None and end.date() < today:
        return "completed"
    if start is not None and start.date() <= today <= (end.date() if end else today):
        return "in_progress"
    return "upcoming"


_POSTCODE_TO_STATE_RE = re.compile(r"\b([A-Z]{2})\b")


def _state_from_postcode(value: Any) -> str | None:
    """Best-effort 2-letter state extraction from a postal-code field.

    The USTA payload's ``primaryLocation.county`` is sometimes the
    USPS state code (``"FL"``); when it isn't, the surrounding
    ``postcode`` field on rare records is ``"FL 33870"`` and we
    extract the prefix. Returns ``None`` if no 2-letter token is
    found.
    """
    if not isinstance(value, str):
        return None
    m = _POSTCODE_TO_STATE_RE.search(value.upper())
    if m:
        return m.group(1)
    return None
