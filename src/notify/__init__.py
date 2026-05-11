"""Notifications scaffold.

Backends are pluggable via the ``Notifier`` protocol. Today only the
``StubNotifier`` (writes to a file) is wired; the SMTP and Resend
backends raise ``NotImplementedError`` and document their config keys.
"""

from src.notify.base import DeliveryRecord, Notification, Notifier
from src.notify.stub import StubNotifier

__all__ = ["DeliveryRecord", "Notification", "Notifier", "StubNotifier"]
