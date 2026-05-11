"""Unit tests for the notifications scaffold."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.models.draw import Draw
from src.models.match import Match
from src.models.player import Player
from src.models.tournament import Tournament
from src.notify import Notification, StubNotifier
from src.notify.smtp import SmtpNotifier
from src.notify.templates import (
    new_opponent_body,
    sync_failure_body,
    tournament_reminder_body,
    weekly_digest_body,
)

# ---------------------------------------------------------------------------
# StubNotifier
# ---------------------------------------------------------------------------


async def test_stub_notifier_send_writes_and_reads_back(tmp_path: Path) -> None:
    log = tmp_path / "stub.jsonl"
    notifier = StubNotifier(log_path=log)

    note = Notification(
        subject="Hello",
        body="World",
        to="me@example.com",
        kind="info",
        metadata={"source": "test"},
    )
    delivery_id = await notifier.send(note)

    assert isinstance(delivery_id, str)
    assert delivery_id  # non-empty

    records = notifier.records()
    assert len(records) == 1
    rec = records[0]
    assert rec.delivery_id == delivery_id
    assert rec.notification.subject == "Hello"
    assert rec.notification.body == "World"
    assert rec.notification.to == "me@example.com"
    assert rec.notification.kind == "info"
    assert dict(rec.notification.metadata) == {"source": "test"}
    assert rec.sent_at.tzinfo is not None


async def test_stub_notifier_two_sends_produce_distinct_delivery_ids(tmp_path: Path) -> None:
    notifier = StubNotifier(log_path=tmp_path / "stub.jsonl")

    note = Notification(subject="s", body="b", to="t@example.com")
    id1 = await notifier.send(note)
    id2 = await notifier.send(note)

    assert id1 != id2

    records = notifier.records()
    assert len(records) == 2
    assert {records[0].delivery_id, records[1].delivery_id} == {id1, id2}


# ---------------------------------------------------------------------------
# SmtpNotifier
# ---------------------------------------------------------------------------


async def test_smtp_notifier_send_raises_not_implemented() -> None:
    notifier = SmtpNotifier(
        host="smtp.example.com",
        port=587,
        username="user",
        password="pw",
        sender="bot@example.com",
    )
    with pytest.raises(NotImplementedError):
        await notifier.send(Notification(subject="s", body="b", to="t@example.com"))


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


def test_tournament_reminder_body_contains_name_and_date() -> None:
    tournament = Tournament(
        usta_id="t-1",
        name="Spring Open",
        start_date=date(2026, 5, 15),
        location_city="Atlanta",
        location_state="GA",
    )
    subject, body = tournament_reminder_body("Alex", tournament)

    assert isinstance(subject, str) and subject
    assert isinstance(body, str) and body
    assert "Spring Open" in subject
    assert "Spring Open" in body
    assert "2026-05-15" in body
    assert "Alex" in body


def test_new_opponent_body_contains_opponent_name() -> None:
    opponent = Player(usta_id="p-2", full_name="Jamie Doe")
    draw = Draw(usta_id="d-1", tournament_id="t-1", name="Boys' 16s Singles")

    subject, body = new_opponent_body("Alex", opponent, draw)

    assert "Jamie Doe" in subject
    assert "Jamie Doe" in body
    assert "Boys' 16s Singles" in body


def test_sync_failure_body_includes_error() -> None:
    err = "ConnectionResetError: SSL handshake failed"
    when = datetime(2026, 5, 11, 3, 14, tzinfo=UTC)

    subject, body = sync_failure_body(err, when)

    assert "sync" in subject.lower()
    assert err in body
    assert "2026-05-11" in body


def test_weekly_digest_body_handles_empty_matches() -> None:
    subject, body = weekly_digest_body("Alex", [])

    assert subject
    assert "Alex" in body
    assert "no matches this week" in body.lower()


def test_weekly_digest_body_lists_matches() -> None:
    matches = [
        Match(
            draw_id="d-1",
            round="R32",
            scheduled_at=datetime(2026, 5, 12, 9, 0, tzinfo=UTC),
            court="Court 3",
        ),
        Match(
            draw_id="d-1",
            round="R16",
            scheduled_at=datetime(2026, 5, 13, 11, 0, tzinfo=UTC),
            court="Court 1",
        ),
    ]

    subject, body = weekly_digest_body("Alex", matches)

    assert subject
    assert "Alex" in body
    assert "R32" in body
    assert "R16" in body
    assert "Court 3" in body
    assert "Court 1" in body
