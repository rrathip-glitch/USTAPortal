"""Unit tests for ``src.auth.magic_link``."""

from __future__ import annotations

import re

import pytest

from src.auth.magic_link import (
    MagicLinkError,
    decode_magic_link,
    encode_magic_link,
)

SECRET = "super-secret"


def test_encode_decode_round_trip_preserves_user_id_and_email() -> None:
    token = encode_magic_link(
        user_id="user-42",
        email="player@example.com",
        secret=SECRET,
        ttl_seconds=900,
        now=1_700_000_000,
    )
    payload = decode_magic_link(token, secret=SECRET, now=1_700_000_001)

    assert payload.user_id == "user-42"
    assert payload.email == "player@example.com"
    assert payload.issued_at == 1_700_000_000
    assert payload.expires_at == 1_700_000_000 + 900


def test_decode_with_wrong_secret_raises() -> None:
    token = encode_magic_link(
        user_id="u",
        email="e@x.com",
        secret=SECRET,
        now=1_700_000_000,
    )
    with pytest.raises(MagicLinkError):
        decode_magic_link(token, secret="other-secret", now=1_700_000_001)


def test_decode_expired_token_raises() -> None:
    token = encode_magic_link(
        user_id="u",
        email="e@x.com",
        secret=SECRET,
        ttl_seconds=60,
        now=1_700_000_000,
    )
    # 61 seconds later — past the 60s TTL.
    with pytest.raises(MagicLinkError):
        decode_magic_link(token, secret=SECRET, now=1_700_000_061)


def test_decode_malformed_token_raises() -> None:
    # No dot separator.
    with pytest.raises(MagicLinkError):
        decode_magic_link("not-a-real-token", secret=SECRET, now=1_700_000_000)

    # Too many dots.
    with pytest.raises(MagicLinkError):
        decode_magic_link("a.b.c", secret=SECRET, now=1_700_000_000)

    # Empty halves.
    with pytest.raises(MagicLinkError):
        decode_magic_link(".sig", secret=SECRET, now=1_700_000_000)
    with pytest.raises(MagicLinkError):
        decode_magic_link("payload.", secret=SECRET, now=1_700_000_000)


def test_decode_tampered_payload_raises() -> None:
    token = encode_magic_link(
        user_id="u",
        email="e@x.com",
        secret=SECRET,
        now=1_700_000_000,
    )
    payload_b64, sig = token.split(".", 1)
    # Flip a character in the payload while keeping the original signature.
    tampered_char = "A" if payload_b64[0] != "A" else "B"
    tampered_payload = tampered_char + payload_b64[1:]
    tampered = f"{tampered_payload}.{sig}"

    with pytest.raises(MagicLinkError):
        decode_magic_link(tampered, secret=SECRET, now=1_700_000_001)


def test_encoded_token_is_url_safe() -> None:
    # Use values whose JSON encoding contains characters that would normally
    # produce '+' / '/' / '=' in standard base64.
    token = encode_magic_link(
        user_id="user-with-symbols-?&=",
        email="alex+tennis@example.com",
        secret=SECRET,
        now=1_700_000_000,
    )

    assert "+" not in token
    assert "/" not in token
    assert "=" not in token
    # Only URL-safe base64 characters plus the single dot separator.
    assert re.fullmatch(r"[A-Za-z0-9_\-]+\.[A-Fa-f0-9]+", token) is not None
