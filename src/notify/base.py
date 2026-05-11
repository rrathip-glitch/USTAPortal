"""Core notification types and the ``Notifier`` protocol.

The protocol is intentionally minimal — concrete backends (stub, SMTP, Resend,
SES, ...) only need to implement an awaitable ``send`` that returns a delivery
identifier. The dataclasses are frozen so a ``Notification`` can be hashed /
shared between producers and consumers without surprise mutation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

__all__ = ["DeliveryRecord", "Notification", "Notifier"]


NotificationKind = str  # "info" | "warning" | "critical" — kept loose on purpose.


@dataclass(frozen=True)
class Notification:
    """A single message to deliver.

    ``metadata`` is for routing / templating hints; backends should treat it as
    opaque and forward it where they can (e.g. SMTP custom headers).
    """

    subject: str
    body: str
    to: str
    kind: NotificationKind = "info"  # info | warning | critical
    metadata: Mapping[str, str] = field(default_factory=dict)


@runtime_checkable
class Notifier(Protocol):
    """Backend protocol — any object that can deliver a ``Notification``."""

    async def send(self, n: Notification) -> str:
        """Deliver ``n`` and return a backend-specific delivery id."""
        ...


@dataclass(frozen=True)
class DeliveryRecord:
    """Persistent record of a delivered notification.

    Backends that keep a log (e.g. ``StubNotifier``) produce these from their
    underlying storage so tests and the audit trail can introspect what was
    actually sent.
    """

    delivery_id: str
    sent_at: datetime
    notification: Notification
