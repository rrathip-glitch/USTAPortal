"""Unit tests for src.fetch.client.FetchClient."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from src.fetch.client import (
    AuthExpiredError,
    BotChallengeError,
    FetchClient,
    RateLimitedError,
    compute_cache_key,
    redact_headers,
)


@pytest.fixture()
def cache_dir(tmp_path: Path) -> Path:
    out = tmp_path / "raw"
    out.mkdir()
    return out


@pytest.fixture()
def fast_client(cache_dir: Path) -> FetchClient:
    """A FetchClient whose rate-limit interval is zero so tests don't sleep."""
    return FetchClient(
        raw_cache_dir=cache_dir,
        interval_seconds=0.0,
        max_retries=4,
        backoff_base=0.0,
        backoff_cap=0.0,
        jitter_ratio=0.0,
    )


def _read_only_cache_file(cache_dir: Path) -> dict[str, Any]:
    files = list(cache_dir.rglob("*"))
    json_files = [f for f in files if f.is_file()]
    assert len(json_files) == 1, f"expected one cache file, found {json_files}"
    with json_files[0].open("r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# GET writes a cache entry
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_writes_response_to_raw_cache(fast_client: FetchClient, cache_dir: Path) -> None:
    respx.get("https://example.test/data").mock(
        return_value=httpx.Response(
            200, json={"hello": "world"}, headers={"content-type": "application/json"}
        )
    )

    async with fast_client as client:
        response = await client.get("https://example.test/data")

    assert response.status_code == 200
    envelope = _read_only_cache_file(cache_dir)
    assert envelope["request"]["method"] == "GET"
    assert envelope["request"]["url"] == "https://example.test/data"
    assert envelope["response"]["status"] == 200
    assert envelope["response"]["body"] == {"hello": "world"}
    assert "fetched_at" in envelope


# ---------------------------------------------------------------------------
# Cache file path layout uses 2-char prefix dir
# ---------------------------------------------------------------------------


@respx.mock
async def test_cache_path_layout_uses_two_char_prefix(
    fast_client: FetchClient, cache_dir: Path
) -> None:
    respx.get("https://example.test/x").mock(
        return_value=httpx.Response(200, json={"a": 1}, headers={"content-type": "application/json"})
    )
    async with fast_client as client:
        await client.get("https://example.test/x")

    files = list(cache_dir.rglob("*.json"))
    assert len(files) == 1
    cache_file = files[0]
    # File lives in <cache_dir>/<two-hex>/<full-hex>.json
    assert cache_file.parent.parent == cache_dir
    assert len(cache_file.parent.name) == 2
    assert cache_file.stem.startswith(cache_file.parent.name)


# ---------------------------------------------------------------------------
# 429 with Retry-After is honored, then a retry succeeds
# ---------------------------------------------------------------------------


@respx.mock
async def test_429_retry_after_is_honored(fast_client: FetchClient) -> None:
    route = respx.get("https://example.test/limited")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "3"}, text="slow down"),
        httpx.Response(200, json={"ok": True}, headers={"content-type": "application/json"}),
    ]

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    with patch("src.fetch.client.asyncio.sleep", new=fake_sleep):
        async with fast_client as client:
            response = await client.get("https://example.test/limited")

    assert response.status_code == 200
    # Retry-After value of 3 must have been one of the sleeps.
    assert any(abs(s - 3.0) < 1e-6 for s in sleeps), sleeps


@respx.mock
async def test_429_exhausted_raises_rate_limited(cache_dir: Path) -> None:
    client = FetchClient(
        raw_cache_dir=cache_dir,
        interval_seconds=0.0,
        max_retries=2,
        backoff_base=0.0,
        backoff_cap=0.0,
        jitter_ratio=0.0,
    )
    respx.get("https://example.test/spam").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "1"}, text="nope")
    )
    async def fake_sleep(seconds: float) -> None:
        return None

    with patch("src.fetch.client.asyncio.sleep", new=fake_sleep):
        async with client as c:
            with pytest.raises(RateLimitedError):
                await c.get("https://example.test/spam")


# ---------------------------------------------------------------------------
# Rate limit enforces a minimum interval between requests
# ---------------------------------------------------------------------------


@respx.mock
async def test_rate_limit_enforces_minimum_interval(cache_dir: Path) -> None:
    client = FetchClient(
        raw_cache_dir=cache_dir,
        interval_seconds=2.0,
        max_retries=1,
        backoff_base=0.0,
        backoff_cap=0.0,
        jitter_ratio=0.0,  # deterministic
    )
    respx.get("https://example.test/a").mock(
        return_value=httpx.Response(200, json={}, headers={"content-type": "application/json"})
    )
    respx.get("https://example.test/b").mock(
        return_value=httpx.Response(200, json={}, headers={"content-type": "application/json"})
    )

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    with patch("src.fetch.client.asyncio.sleep", new=fake_sleep):
        async with client as c:
            await c.get("https://example.test/a")
            await c.get("https://example.test/b")

    # First request: no prior, so no rate-limit sleep is enforced (zero or near-zero).
    # Second request: must trigger a sleep close to interval_seconds (2.0).
    assert any(s > 1.5 for s in sleeps), sleeps


# ---------------------------------------------------------------------------
# Cookie / Authorization headers are redacted from cache
# ---------------------------------------------------------------------------


@respx.mock
async def test_sensitive_headers_redacted_in_cache(
    fast_client: FetchClient, cache_dir: Path
) -> None:
    respx.get("https://example.test/private").mock(
        return_value=httpx.Response(
            200, json={"ok": True}, headers={"content-type": "application/json"}
        )
    )

    async with fast_client as client:
        await client.get(
            "https://example.test/private",
            headers={
                "Cookie": "session=topsecret",
                "Authorization": "Bearer abc123",
                "X-Auth-Token": "xyz",
                "User-Agent": "ustaportal/1.0",
            },
        )

    envelope = _read_only_cache_file(cache_dir)
    headers = envelope["request"]["headers"]
    assert headers["Cookie"] == "[REDACTED]"
    assert headers["Authorization"] == "[REDACTED]"
    assert headers["X-Auth-Token"] == "[REDACTED]"
    assert headers["User-Agent"] == "ustaportal/1.0"


def test_redact_headers_handles_case_insensitively() -> None:
    out = redact_headers({"cookie": "v", "AUTHORIZATION": "v", "x-auth-foo": "v", "Accept": "*/*"})
    assert out["cookie"] == "[REDACTED]"
    assert out["AUTHORIZATION"] == "[REDACTED]"
    assert out["x-auth-foo"] == "[REDACTED]"
    assert out["Accept"] == "*/*"


# ---------------------------------------------------------------------------
# Cache key stability
# ---------------------------------------------------------------------------


def test_cache_key_is_stable_for_identical_requests() -> None:
    a = compute_cache_key("GET", "https://x/y", {"q": "1", "p": "2"}, None)
    b = compute_cache_key("GET", "https://x/y", {"p": "2", "q": "1"}, None)
    assert a == b


def test_cache_key_differs_when_method_or_url_changes() -> None:
    base = compute_cache_key("GET", "https://x/y", {}, None)
    assert base != compute_cache_key("POST", "https://x/y", {}, None)
    assert base != compute_cache_key("GET", "https://x/z", {}, None)


def test_cache_key_includes_body_keys() -> None:
    a = compute_cache_key("POST", "https://x/y", None, {"a": 1, "b": 2})
    b = compute_cache_key("POST", "https://x/y", None, {"b": 2, "a": 1})
    assert a == b
    c = compute_cache_key("POST", "https://x/y", None, {"a": 1})
    assert c != a


# ---------------------------------------------------------------------------
# 401/403 → AuthExpiredError, 5xx → retry, bot wall → BotChallengeError
# ---------------------------------------------------------------------------


@respx.mock
async def test_401_raises_auth_expired(fast_client: FetchClient) -> None:
    respx.get("https://example.test/me").mock(
        return_value=httpx.Response(401, json={"error": "expired"})
    )
    async with fast_client as client:
        with pytest.raises(AuthExpiredError):
            await client.get("https://example.test/me")


@respx.mock
async def test_5xx_then_success_recovers(fast_client: FetchClient) -> None:
    route = respx.get("https://example.test/flap")
    route.side_effect = [
        httpx.Response(503, text="busy"),
        httpx.Response(200, json={"ok": True}, headers={"content-type": "application/json"}),
    ]

    async def fake_sleep(seconds: float) -> None:
        return None

    with patch("src.fetch.client.asyncio.sleep", new=fake_sleep):
        async with fast_client as client:
            response = await client.get("https://example.test/flap")
    assert response.status_code == 200


@respx.mock
async def test_bot_challenge_html_raises(fast_client: FetchClient) -> None:
    respx.get("https://example.test/wall").mock(
        return_value=httpx.Response(
            200,
            text="<html><body>Please complete the captcha to continue.</body></html>",
            headers={"content-type": "text/html"},
        )
    )
    async with fast_client as client:
        with pytest.raises(BotChallengeError):
            await client.get("https://example.test/wall")


# ---------------------------------------------------------------------------
# fetch_graphql convenience
# ---------------------------------------------------------------------------


@respx.mock
async def test_fetch_graphql_posts_query_and_returns_parsed_json(
    fast_client: FetchClient,
) -> None:
    respx.post("https://gql.example.test/graphql").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"viewer": {"id": 42}}},
            headers={"content-type": "application/json"},
        )
    )
    async with fast_client as client:
        result = await client.fetch_graphql(
            "query { viewer { id } }",
            variables={},
            endpoint="https://gql.example.test/graphql",
        )
    assert result == {"data": {"viewer": {"id": 42}}}


# ---------------------------------------------------------------------------
# Cookies are pulled from session on enter
# ---------------------------------------------------------------------------


async def test_cookies_pulled_from_session_on_enter(cache_dir: Path) -> None:
    fake_session = AsyncMock()
    fake_session.cookies.return_value = [
        {"name": "session", "value": "abc", "domain": "example.test", "path": "/"}
    ]
    client = FetchClient(
        session=fake_session,
        raw_cache_dir=cache_dir,
        interval_seconds=0.0,
    )
    async with client as c:
        # httpx stores cookies on the client; make sure ours landed.
        assert c._client.cookies.get("session", domain="example.test") == "abc"
    fake_session.cookies.assert_awaited()
