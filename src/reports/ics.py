"""iCalendar (RFC 5545) exporter for Tournament objects.

This module hand-rolls the small subset of RFC 5545 we need so we can
emit a ``text/calendar`` document from a list of :class:`Tournament`
without pulling in a third-party library.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from src.models.tournament import Tournament

__all__ = ["tournaments_to_ics"]

# RFC 5545 mandates CRLF line endings.
_CRLF = "\r\n"

# Max octet length of a single content line before folding (RFC 5545 §3.1).
# We fold at 74 so the continuation space prefix keeps the result <= 75 octets.
_FOLD_LIMIT = 74


def _escape_text(value: str) -> str:
    """Escape a TEXT value per RFC 5545 §3.3.11.

    The order matters: backslashes must be escaped first so the escapes
    we introduce for the other characters are not double-escaped.
    """
    return (
        value.replace("\\", "\\\\")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def _fold_line(line: str) -> str:
    """Fold a single content line to <= 75 octets per RFC 5545 §3.1.

    Folding is octet-based, not character-based, so we walk the UTF-8
    encoded bytes and split on a boundary that does not bisect a
    multibyte sequence.
    """
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line

    chunks: list[str] = []
    remaining = encoded
    # First chunk: up to _FOLD_LIMIT octets (no leading space).
    first = _take_octets(remaining, _FOLD_LIMIT)
    chunks.append(first.decode("utf-8"))
    remaining = remaining[len(first) :]

    while remaining:
        nxt = _take_octets(remaining, _FOLD_LIMIT)
        chunks.append(" " + nxt.decode("utf-8"))
        remaining = remaining[len(nxt) :]

    return _CRLF.join(chunks)


def _take_octets(buf: bytes, limit: int) -> bytes:
    """Return a prefix of ``buf`` up to ``limit`` octets that does not
    split a UTF-8 multibyte sequence."""
    if len(buf) <= limit:
        return buf
    end = limit
    # UTF-8 continuation bytes have the high bits 10xxxxxx; back off
    # until we land on a leading byte.
    while end > 0 and (buf[end] & 0xC0) == 0x80:
        end -= 1
    if end == 0:
        # Pathological: limit landed inside a sequence whose start is
        # before position 0. Fall back to the original limit; this
        # cannot actually happen for valid UTF-8 with limit >= 4.
        return buf[:limit]
    return buf[:end]


def _format_date(d: date) -> str:
    """Format a date as YYYYMMDD (RFC 5545 DATE value)."""
    return d.strftime("%Y%m%d")


def _format_datetime_utc(dt: datetime) -> str:
    """Format a UTC datetime as YYYYMMDDTHHMMSSZ (RFC 5545 DATE-TIME)."""
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _emit_line(buffer: list[str], line: str) -> None:
    """Append a (possibly folded) content line to ``buffer``."""
    buffer.append(_fold_line(line))


def _build_description(t: Tournament) -> str:
    """Build a human-readable DESCRIPTION value from tournament fields."""
    parts: list[str] = []
    if t.level:
        parts.append(f"Level: {t.level}")
    parts.append(f"Surface: {t.surface}")
    if t.ball:
        parts.append(f"Ball: {t.ball}")
    parts.append(f"Status: {t.status}")
    return "\n".join(parts)


def _build_location(t: Tournament) -> str | None:
    """Build a LOCATION value from the city/state fields."""
    city = t.location_city
    state = t.location_state
    if city and state:
        return f"{city}, {state}"
    if city:
        return city
    if state:
        return state
    return None


def tournaments_to_ics(
    tournaments: list[Tournament],
    *,
    calendar_name: str = "USTA Tournaments",
    prod_id: str = "-//USTA Portal//EN",
    now: datetime | None = None,
) -> str:
    """Return a valid iCalendar 2.0 (RFC 5545) document.

    One VEVENT per tournament. UID is ``f"{usta_id}@usta-portal"``.
    DTSTART is ``start_date`` (all-day DATE value). DTEND is
    ``end_date + 1 day`` (RFC 5545 exclusive end for all-day events);
    if ``end_date`` is None, ``start_date + 1`` is used. Tournaments
    without a ``start_date`` are skipped.
    """
    stamp = now if now is not None else datetime.now(UTC)
    dtstamp = _format_datetime_utc(stamp)

    lines: list[str] = []
    _emit_line(lines, "BEGIN:VCALENDAR")
    _emit_line(lines, "VERSION:2.0")
    _emit_line(lines, f"PRODID:{_escape_text(prod_id)}")
    _emit_line(lines, "CALSCALE:GREGORIAN")
    _emit_line(lines, "METHOD:PUBLISH")
    _emit_line(lines, f"X-WR-CALNAME:{_escape_text(calendar_name)}")

    for t in tournaments:
        if t.start_date is None:
            continue

        end = t.end_date if t.end_date is not None else t.start_date
        # RFC 5545 §3.6.1: DTEND is exclusive for DATE values, so add 1.
        dtend_value = end + timedelta(days=1)

        _emit_line(lines, "BEGIN:VEVENT")
        _emit_line(lines, f"UID:{t.usta_id}@usta-portal")
        _emit_line(lines, f"DTSTAMP:{dtstamp}")
        _emit_line(lines, f"DTSTART;VALUE=DATE:{_format_date(t.start_date)}")
        _emit_line(lines, f"DTEND;VALUE=DATE:{_format_date(dtend_value)}")
        _emit_line(lines, f"SUMMARY:{_escape_text(t.name)}")
        _emit_line(lines, f"DESCRIPTION:{_escape_text(_build_description(t))}")
        location = _build_location(t)
        if location:
            _emit_line(lines, f"LOCATION:{_escape_text(location)}")
        _emit_line(lines, "END:VEVENT")

    _emit_line(lines, "END:VCALENDAR")

    # Join with CRLF and add a trailing CRLF so the document ends on a
    # complete line (some consumers are strict about this).
    return _CRLF.join(lines) + _CRLF
