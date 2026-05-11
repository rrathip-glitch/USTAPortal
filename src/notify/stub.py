"""File-backed ``Notifier`` for development and tests.

Each ``send`` appends a JSON line to ``log_path`` (default
``data/notifications/stub.log.jsonl``). ``records`` parses the file back into
``DeliveryRecord`` objects for assertions.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from src.notify.base import DeliveryRecord, Notification

__all__ = ["StubNotifier"]


DEFAULT_LOG_PATH = Path("data/notifications/stub.log.jsonl")


class StubNotifier:
    """Writes deliveries to a newline-delimited JSON file.

    Useful in development and tests; production swaps to SMTP/Resend.
    """

    def __init__(self, log_path: Path | None = None) -> None:
        self._log_path: Path = log_path if log_path is not None else DEFAULT_LOG_PATH

    @property
    def log_path(self) -> Path:
        return self._log_path

    async def send(self, n: Notification) -> str:
        delivery_id = uuid.uuid4().hex
        sent_at = datetime.now(UTC)
        entry = {
            "delivery_id": delivery_id,
            "sent_at": sent_at.isoformat(),
            "notification": {
                "subject": n.subject,
                "body": n.body,
                "to": n.to,
                "kind": n.kind,
                "metadata": dict(n.metadata),
            },
        }
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return delivery_id

    def records(self) -> list[DeliveryRecord]:
        """Parse the log file back into ``DeliveryRecord`` objects.

        Returns an empty list when the log doesn't exist yet.
        """

        if not self._log_path.exists():
            return []

        out: list[DeliveryRecord] = []
        with self._log_path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                entry = json.loads(raw)
                note_raw = entry["notification"]
                note = Notification(
                    subject=note_raw["subject"],
                    body=note_raw["body"],
                    to=note_raw["to"],
                    kind=note_raw.get("kind", "info"),
                    metadata=dict(note_raw.get("metadata", {})),
                )
                out.append(
                    DeliveryRecord(
                        delivery_id=entry["delivery_id"],
                        sent_at=datetime.fromisoformat(entry["sent_at"]),
                        notification=note,
                    )
                )
        return out
