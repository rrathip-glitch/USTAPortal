"""Month-grid layout helper for the HTML calendar view.

Builds a 5- or 6-row x 7-column grid of :class:`CalendarCell` objects
covering the calendar weeks that contain the requested month, with
tournaments attached to every day they overlap.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

from src.models.tournament import Tournament

__all__ = ["CalendarCell", "build_month_grid", "month_label"]


@dataclass(frozen=True)
class CalendarCell:
    """A single day cell in the month grid."""

    day: date
    in_current_month: bool
    tournaments: list[Tournament] = field(default_factory=list)


def _week_start(d: date, *, week_start_sunday: bool) -> date:
    """Return the start-of-week date on/before ``d``.

    ``date.weekday()`` returns Monday=0..Sunday=6. We want the offset
    back to Sunday (if ``week_start_sunday``) or Monday otherwise.
    """
    # Sunday-start: shift Monday=0..Sunday=6 into Sunday=0..Saturday=6.
    offset = (d.weekday() + 1) % 7 if week_start_sunday else d.weekday()
    return d - timedelta(days=offset)


def _week_end(d: date, *, week_start_sunday: bool) -> date:
    """Return the end-of-week date on/after ``d``."""
    start = _week_start(d, week_start_sunday=week_start_sunday)
    return start + timedelta(days=6)


def _overlaps(t: Tournament, day: date) -> bool:
    """Return True iff ``day`` falls within the tournament's date range."""
    if t.start_date is None:
        return False
    end = t.end_date if t.end_date is not None else t.start_date
    return t.start_date <= day <= end


def build_month_grid(
    tournaments: list[Tournament],
    *,
    year: int,
    month: int,
    week_start_sunday: bool = True,
) -> list[list[CalendarCell]]:
    """Return a grid of :class:`CalendarCell` rows covering ``month``.

    The grid starts on the Sunday (or Monday if ``week_start_sunday``
    is False) on/before the 1st of the month, and ends on the
    Saturday/Sunday on/after the last day of the month. Day cells
    outside the requested month carry ``in_current_month=False``.
    """
    first_of_month = date(year, month, 1)
    _, last_day = calendar.monthrange(year, month)
    last_of_month = date(year, month, last_day)

    grid_start = _week_start(first_of_month, week_start_sunday=week_start_sunday)
    grid_end = _week_end(last_of_month, week_start_sunday=week_start_sunday)

    rows: list[list[CalendarCell]] = []
    cursor = grid_start
    while cursor <= grid_end:
        row: list[CalendarCell] = []
        for _ in range(7):
            day_tournaments = [t for t in tournaments if _overlaps(t, cursor)]
            row.append(
                CalendarCell(
                    day=cursor,
                    in_current_month=(cursor.month == month and cursor.year == year),
                    tournaments=day_tournaments,
                )
            )
            cursor = cursor + timedelta(days=1)
        rows.append(row)

    return rows


_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def month_label(year: int, month: int) -> str:
    """Return e.g. ``"May 2026"`` for ``year=2026, month=5``."""
    if not 1 <= month <= 12:
        raise ValueError(f"month must be 1..12, got {month}")
    return f"{_MONTH_NAMES[month - 1]} {year}"
