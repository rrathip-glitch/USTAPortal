"""Unit tests for ``src.reports`` (iCalendar export + month grid)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from src.models.tournament import Tournament
from src.reports.calendar_grid import CalendarCell, build_month_grid, month_label
from src.reports.ics import tournaments_to_ics

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _tournament(
    usta_id: str = "t-1",
    name: str = "Spring Open",
    *,
    start_date: date | None = date(2026, 5, 10),
    end_date: date | None = date(2026, 5, 12),
    level: str | None = "L4",
    location_city: str | None = "Atlanta",
    location_state: str | None = "GA",
    surface: str = "hard",
    ball: str | None = "regular",
    status: str = "upcoming",
) -> Tournament:
    return Tournament(
        usta_id=usta_id,
        name=name,
        level=level,
        start_date=start_date,
        end_date=end_date,
        location_city=location_city,
        location_state=location_state,
        surface=surface,
        ball=ball,
        status=status,
    )


_FIXED_NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# ICS tests
# ---------------------------------------------------------------------------


def test_ics_single_tournament_basic_structure() -> None:
    ics = tournaments_to_ics([_tournament()], now=_FIXED_NOW)

    assert "BEGIN:VCALENDAR" in ics
    assert "END:VCALENDAR" in ics
    assert ics.count("BEGIN:VEVENT") == 1
    assert ics.count("END:VEVENT") == 1
    assert "DTSTART;VALUE=DATE:20260510" in ics
    # DTEND is exclusive: end_date 2026-05-12 -> 2026-05-13.
    assert "DTEND;VALUE=DATE:20260513" in ics
    assert "UID:t-1@usta-portal" in ics
    assert "SUMMARY:Spring Open" in ics
    assert "VERSION:2.0" in ics


def test_ics_escapes_commas_and_semicolons_in_summary() -> None:
    nasty = "Open, Junior; with \\backslash"
    ics = tournaments_to_ics([_tournament(name=nasty)], now=_FIXED_NOW)

    # In the SUMMARY line, comma, semicolon and backslash must be escaped.
    assert "SUMMARY:Open\\, Junior\\; with \\\\backslash" in ics
    # The raw, unescaped form must not appear on the SUMMARY line.
    assert "SUMMARY:Open, Junior" not in ics


def test_ics_missing_end_date_defaults_to_start_plus_one() -> None:
    t = _tournament(start_date=date(2026, 5, 10), end_date=None)
    ics = tournaments_to_ics([t], now=_FIXED_NOW)

    assert "DTSTART;VALUE=DATE:20260510" in ics
    # No end_date -> DTEND is start_date + 1.
    assert "DTEND;VALUE=DATE:20260511" in ics


def test_ics_skips_tournaments_with_no_start_date() -> None:
    keeper = _tournament(usta_id="keep")
    skipper = _tournament(usta_id="skip", start_date=None, end_date=None)

    ics = tournaments_to_ics([keeper, skipper], now=_FIXED_NOW)

    assert ics.count("BEGIN:VEVENT") == 1
    assert "UID:keep@usta-portal" in ics
    assert "UID:skip@usta-portal" not in ics


def test_ics_uses_crlf_line_endings() -> None:
    ics = tournaments_to_ics([_tournament()], now=_FIXED_NOW)

    # Every newline must be a CRLF, never a bare LF.
    assert "\r\n" in ics
    # No bare LF that is not preceded by CR.
    bare_lf_indexes = [
        i for i, ch in enumerate(ics) if ch == "\n" and (i == 0 or ics[i - 1] != "\r")
    ]
    assert bare_lf_indexes == []
    # And the document must end with CRLF.
    assert ics.endswith("\r\n")


def test_ics_folds_long_summary_lines() -> None:
    long_name = "A" * 200
    ics = tournaments_to_ics([_tournament(name=long_name)], now=_FIXED_NOW)

    # The folded continuation marker `\r\n ` must be present.
    assert "\r\n " in ics

    # Confirm no single content line exceeds 75 octets.
    for raw_line in ics.split("\r\n"):
        # Continuation lines start with a single space; that is part of
        # the folded representation, so the constraint still applies.
        assert len(raw_line.encode("utf-8")) <= 75, raw_line

    # Unfold the document (reverse the folding) and verify the original
    # SUMMARY survives intact.
    unfolded = ics.replace("\r\n ", "")
    assert f"SUMMARY:{long_name}" in unfolded


# ---------------------------------------------------------------------------
# Calendar grid tests
# ---------------------------------------------------------------------------


def test_build_month_grid_may_2026_bounds_sunday_start() -> None:
    grid = build_month_grid([], year=2026, month=5)

    assert grid, "grid must have at least one row"
    first_row = grid[0]
    last_row = grid[-1]
    assert len(first_row) == 7
    assert len(last_row) == 7

    # 2026-05-01 is a Friday. Sunday on/before is 2026-04-26.
    assert first_row[0].day == date(2026, 4, 26)
    assert first_row[0].in_current_month is False
    # The Friday cell holds May 1.
    assert first_row[5].day == date(2026, 5, 1)
    assert first_row[5].in_current_month is True
    # April days that fill the first week appear and are flagged out-of-month.
    for cell in first_row[:5]:
        assert cell.in_current_month is False
        assert cell.day.month == 4

    # The grid extends through Saturday on/after May 31. 2026-05-31 is a
    # Sunday, so the last row covers May 31 through June 6.
    assert last_row[0].day == date(2026, 5, 31)
    assert last_row[-1].day >= date(2026, 5, 31)
    assert last_row[-1].day == date(2026, 6, 6)


def test_build_month_grid_attaches_tournament_to_overlapping_days() -> None:
    t = _tournament(
        usta_id="overlap",
        start_date=date(2026, 5, 10),
        end_date=date(2026, 5, 12),
    )
    grid = build_month_grid([t], year=2026, month=5)

    days_with_event: list[date] = []
    for row in grid:
        for cell in row:
            if t in cell.tournaments:
                days_with_event.append(cell.day)

    assert days_with_event == [date(2026, 5, 10), date(2026, 5, 11), date(2026, 5, 12)]


def test_build_month_grid_spans_month_boundary() -> None:
    t = _tournament(
        usta_id="boundary",
        start_date=date(2026, 5, 31),
        end_date=date(2026, 6, 2),
    )
    grid = build_month_grid([t], year=2026, month=5)

    cells_by_day: dict[date, CalendarCell] = {
        cell.day: cell for row in grid for cell in row
    }

    may_31 = cells_by_day[date(2026, 5, 31)]
    jun_1 = cells_by_day[date(2026, 6, 1)]
    jun_2 = cells_by_day[date(2026, 6, 2)]

    assert may_31.in_current_month is True
    assert t in may_31.tournaments
    assert jun_1.in_current_month is False
    assert t in jun_1.tournaments
    assert jun_2.in_current_month is False
    assert t in jun_2.tournaments


def test_month_label_formats_month_name_and_year() -> None:
    assert month_label(2026, 5) == "May 2026"
    assert month_label(2026, 1) == "January 2026"
    assert month_label(2025, 12) == "December 2025"
