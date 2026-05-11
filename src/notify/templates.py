"""Pure functions that render notification subject/body pairs.

These helpers are deliberately framework-free: each returns a plain
``(subject, body)`` tuple so the orchestrator can wrap them in a
``Notification`` and hand off to whichever ``Notifier`` is wired.

Bodies are plain-text; HTML rendering is a follow-up once the email vendor is
chosen (Q-010).
"""

from __future__ import annotations

from datetime import datetime

from src.models.draw import Draw
from src.models.match import Match
from src.models.player import Player
from src.models.tournament import Tournament

__all__ = [
    "new_opponent_body",
    "sync_failure_body",
    "tournament_reminder_body",
    "weekly_digest_body",
]


def _fmt_date(value: object) -> str:
    """Render a date / datetime / None into a stable short string."""

    if value is None:
        return "TBD"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    # ``date`` from datetime — and anything else with isoformat.
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        return str(iso())
    return str(value)


def _location(t: Tournament) -> str:
    parts = [p for p in (t.location_city, t.location_state) if p]
    return ", ".join(parts) if parts else "location TBD"


def tournament_reminder_body(player_name: str, tournament: Tournament) -> tuple[str, str]:
    """Return ``(subject, body)`` for a day-before reminder."""

    when = _fmt_date(tournament.start_date)
    subject = f"Reminder: {tournament.name} starts {when}"
    body = (
        f"Hi {player_name},\n\n"
        f"This is a reminder that {tournament.name} starts {when} "
        f"({_location(tournament)}).\n\n"
        f"Good luck out there!\n"
    )
    return subject, body


def new_opponent_body(player_name: str, opponent: Player, draw: Draw) -> tuple[str, str]:
    """Return ``(subject, body)`` when a new player joins the draw."""

    subject = f"New opponent in {draw.name}: {opponent.full_name}"
    body = (
        f"Hi {player_name},\n\n"
        f"{opponent.full_name} just joined the {draw.name} draw.\n"
        f"Pull up their record and start prepping.\n"
    )
    return subject, body


def sync_failure_body(error: str, latest_attempt_at: datetime) -> tuple[str, str]:
    """Return ``(subject, body)`` for an admin notification on sync failure."""

    when = latest_attempt_at.strftime("%Y-%m-%d %H:%M UTC")
    subject = "USTA sync failed"
    body = (
        f"The USTA sync job failed at {when}.\n\n"
        f"Error:\n{error}\n\n"
        f"Check the sync_runs table and logs for details.\n"
    )
    return subject, body


def weekly_digest_body(player_name: str, weeks_matches: list[Match]) -> tuple[str, str]:
    """Return ``(subject, body)`` for the Sunday-night digest."""

    subject = "Your weekly USTA digest"

    if not weeks_matches:
        body = (
            f"Hi {player_name},\n\n"
            f"No matches this week. Enjoy the rest!\n"
        )
        return subject, body

    lines = [f"Hi {player_name},", "", f"You have {len(weeks_matches)} match(es) this week:"]
    for m in weeks_matches:
        when = _fmt_date(m.scheduled_at)
        round_label = m.round or "TBD"
        court = m.court or "court TBD"
        lines.append(f"- {when} | {round_label} | {court}")
    lines.append("")
    body = "\n".join(lines)
    return subject, body
