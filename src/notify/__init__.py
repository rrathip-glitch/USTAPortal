"""Notification module.

Public surface:

    send(subject, body, to=None) -> NotifyResult

Backed by Resend (see :mod:`src.notify.resend`). The backend is intentionally
swappable: ``send`` is the one entry point callers should use.
"""

from __future__ import annotations

from dataclasses import dataclass


class ConfigurationError(RuntimeError):
    """Raised when required notification settings are missing."""


@dataclass(frozen=True)
class NotifyResult:
    ok: bool
    provider_message_id: str | None
    error: str | None


async def send(
    subject: str,
    body: str,
    to: str | list[str] | None = None,
) -> NotifyResult:
    from src.notify.resend import ResendBackend

    backend = ResendBackend()
    return await backend.send(subject, body, to=to)


__all__ = ["ConfigurationError", "NotifyResult", "send"]
