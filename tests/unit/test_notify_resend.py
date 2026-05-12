"""Unit tests for src.notify.resend.ResendBackend."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
import respx

from src.notify import ConfigurationError, NotifyResult
from src.notify.resend import RESEND_ENDPOINT, ResendBackend


@respx.mock
async def test_send_success_posts_expected_payload() -> None:
    route = respx.post(RESEND_ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={"id": "msg_abc123"},
            headers={"content-type": "application/json"},
        )
    )

    backend = ResendBackend(
        api_key="re_test_key",
        from_address="alerts@example.test",
        default_to="user@example.test",
    )
    result = await backend.send("Sync failed", "Body text")

    assert isinstance(result, NotifyResult)
    assert result.ok is True
    assert result.provider_message_id == "msg_abc123"
    assert result.error is None

    assert route.called
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer re_test_key"
    assert request.headers["content-type"].startswith("application/json")
    body = request.read().decode("utf-8")
    assert '"from":"alerts@example.test"' in body
    assert '"to":["user@example.test"]' in body
    assert '"subject":"Sync failed"' in body
    assert '"text":"Body text"' in body


@respx.mock
async def test_send_retries_on_5xx_then_succeeds() -> None:
    route = respx.post(RESEND_ENDPOINT)
    route.side_effect = [
        httpx.Response(503, text="busy"),
        httpx.Response(503, text="busy"),
        httpx.Response(
            200,
            json={"id": "msg_after_retry"},
            headers={"content-type": "application/json"},
        ),
    ]

    backend = ResendBackend(
        api_key="re_test_key",
        from_address="alerts@example.test",
        default_to="user@example.test",
        backoff_base=0.0,
        backoff_cap=0.0,
    )

    async def fake_sleep(_seconds: float) -> None:
        return None

    with patch("tenacity.asyncio._portable_async_sleep", new=fake_sleep):
        result = await backend.send("Subject", "Body")

    assert result.ok is True
    assert result.provider_message_id == "msg_after_retry"
    assert route.call_count == 3


@respx.mock
async def test_send_fails_fast_on_401_without_retry() -> None:
    route = respx.post(RESEND_ENDPOINT).mock(
        return_value=httpx.Response(
            401,
            json={"message": "Invalid API key"},
            headers={"content-type": "application/json"},
        )
    )

    backend = ResendBackend(
        api_key="re_bad_key",
        from_address="alerts@example.test",
        default_to="user@example.test",
        backoff_base=0.0,
        backoff_cap=0.0,
    )

    result = await backend.send("Subject", "Body")

    assert result.ok is False
    assert result.provider_message_id is None
    assert result.error is not None
    assert "401" in result.error
    assert route.call_count == 1


async def test_send_raises_when_notify_to_unset_and_no_to_arg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.notify.resend.settings.notify_to", None)
    backend = ResendBackend(
        api_key="re_test_key",
        from_address="alerts@example.test",
        default_to=None,
    )

    with pytest.raises(ConfigurationError):
        await backend.send("Subject", "Body")


async def test_send_raises_when_api_key_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.notify.resend.settings.resend_api_key", None)
    backend = ResendBackend(
        api_key=None,
        from_address="alerts@example.test",
        default_to="user@example.test",
    )

    with pytest.raises(ConfigurationError):
        await backend.send("Subject", "Body")
