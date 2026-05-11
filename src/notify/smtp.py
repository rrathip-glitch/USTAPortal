"""SMTP backend stub.

The actual SMTP wiring is gated on the email-vendor decision (Q-010 in
QUESTIONS.md). Until then we keep the class signature stable so the rest of the
notification pipeline can be plumbed against it; ``send`` raises
``NotImplementedError`` so any code that accidentally relies on it in
production fails loud.

Expected configuration keys (env vars / settings) once wired:

* ``SMTP_HOST``       — SMTP relay hostname (e.g. ``smtp.sendgrid.net``).
* ``SMTP_PORT``       — TCP port (587 for STARTTLS, 465 for implicit TLS).
* ``SMTP_USERNAME``   — Auth username (often ``apikey`` for SendGrid).
* ``SMTP_PASSWORD``   — Auth secret.
* ``SMTP_SENDER``     — From-address used on outgoing messages.
* ``SMTP_USE_TLS``    — Default True; flip to False only for local relays.
"""

from __future__ import annotations

from src.notify.base import Notification

__all__ = ["SmtpNotifier"]


class SmtpNotifier:
    """SMTP backend stub.

    Raises ``NotImplementedError`` for now — actual SMTP wiring is gated on the
    email-vendor decision (Q-010).
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        use_tls: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender
        self.use_tls = use_tls

    async def send(self, n: Notification) -> str:
        raise NotImplementedError("SMTP backend not yet wired; see Q-010.")
