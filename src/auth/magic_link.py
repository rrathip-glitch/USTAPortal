"""Magic-link signing utilities.

Minimal helpers — no DB, no SMTP — so the route layer can encode a token to put
in an email and decode/verify it on click without pulling a JWT library. Built
on stdlib HMAC-SHA256 over a URL-safe base64 JSON payload.

Token format::

    <urlsafe_b64(payload_json)>.<hex hmac>

The base64 payload uses ``urlsafe_b64encode`` with ``=`` padding stripped, so
the entire token is safe to embed in a URL query string without further
encoding (no ``+``, ``/``, or ``=`` characters).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

__all__ = ["MagicLinkError", "MagicLinkPayload", "decode_magic_link", "encode_magic_link"]


@dataclass(frozen=True)
class MagicLinkPayload:
    user_id: str
    email: str
    issued_at: int  # unix seconds
    expires_at: int


class MagicLinkError(RuntimeError):
    """Raised on invalid signature, expired token, or malformed input."""


def _b64url_encode(raw: bytes) -> str:
    """URL-safe base64 without ``=`` padding."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(token: str) -> bytes:
    # Re-pad — base64 needs length % 4 == 0.
    pad = (-len(token)) % 4
    return base64.urlsafe_b64decode(token + ("=" * pad))


def _sign(payload_b64: str, secret: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256)
    return mac.hexdigest()


def encode_magic_link(
    *,
    user_id: str,
    email: str,
    secret: str,
    ttl_seconds: int = 900,
    now: int | None = None,
) -> str:
    """Return a URL-safe token: ``<b64payload>.<hex hmac>``."""

    issued_at = int(now) if now is not None else int(time.time())
    expires_at = issued_at + int(ttl_seconds)
    payload = {
        "user_id": user_id,
        "email": email,
        "issued_at": issued_at,
        "expires_at": expires_at,
    }
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64url_encode(payload_json)
    sig = _sign(payload_b64, secret)
    return f"{payload_b64}.{sig}"


def decode_magic_link(
    token: str,
    *,
    secret: str,
    now: int | None = None,
) -> MagicLinkPayload:
    """Decode + verify HMAC + check expiry.

    Raises:
        MagicLinkError: on invalid signature, expired token, or malformed input.
    """

    if not isinstance(token, str) or token.count(".") != 1:
        raise MagicLinkError("Malformed token.")

    payload_b64, sig = token.split(".", 1)
    if not payload_b64 or not sig:
        raise MagicLinkError("Malformed token.")

    expected_sig = _sign(payload_b64, secret)
    if not hmac.compare_digest(expected_sig, sig):
        raise MagicLinkError("Invalid signature.")

    try:
        payload_raw = _b64url_decode(payload_b64)
    except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
        raise MagicLinkError("Malformed token payload.") from exc

    try:
        data = json.loads(payload_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MagicLinkError("Malformed token payload.") from exc

    if not isinstance(data, dict):
        raise MagicLinkError("Malformed token payload.")

    try:
        user_id = str(data["user_id"])
        email = str(data["email"])
        issued_at = int(data["issued_at"])
        expires_at = int(data["expires_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MagicLinkError("Malformed token payload.") from exc

    current = int(now) if now is not None else int(time.time())
    if current >= expires_at:
        raise MagicLinkError("Token expired.")

    return MagicLinkPayload(
        user_id=user_id,
        email=email,
        issued_at=issued_at,
        expires_at=expires_at,
    )
