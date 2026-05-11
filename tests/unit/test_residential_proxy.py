"""Unit tests for :mod:`src.fetch.residential_proxy`.

Network is mocked via :mod:`respx`; tests never hit the real provider
endpoints. The Bright Data + ScrapFly URL formats and auth patterns are
asserted against the verified API shapes — Bright Data's was confirmed
live on 2026-05-11 (see ``data/reference/known_urls.md`` "Bright Data Web
Unlocker — verified API shape"). If a backend's production shape drifts
these tests should catch the mismatch.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from src.fetch.residential_proxy import (
    BRIGHT_DATA_API_URL,
    SCRAPFLY_API_URL,
    BrightDataWebUnlockerBackend,
    ResidentialProxyConfigError,
    ResidentialProxyError,
    ScrapflyBackend,
    get_residential_proxy,
)


# ---------------------------------------------------------------------------
# Bright Data
# ---------------------------------------------------------------------------


@respx.mock
async def test_bright_data_posts_with_bearer_auth_and_zone_payload() -> None:
    """Bright Data backend posts the verified zone payload with Bearer auth."""
    body_html = b"<html><body>real upstream body</body></html>"
    route = respx.post(BRIGHT_DATA_API_URL).mock(
        return_value=httpx.Response(
            200,
            content=body_html,
            headers={
                "x-brd-response-status": "200",
                "x-brd-response-url": "https://playtennis.usta.com/rankings",
            },
        )
    )

    backend = BrightDataWebUnlockerBackend(
        api_key="brd_test_token_abc",
        zone="web_unlocker1",
    )
    try:
        response = await backend.fetch(
            "https://playtennis.usta.com/rankings", country="us"
        )
    finally:
        await backend.close()

    assert route.called, "Bright Data endpoint must be hit exactly once"
    request: httpx.Request = route.calls.last.request

    # Bearer auth header — single API token, REST-mode (NOT Basic).
    assert request.headers["authorization"] == "Bearer brd_test_token_abc"

    # Payload should be JSON with the verified keys only.
    payload = json.loads(request.content)
    assert payload["url"] == "https://playtennis.usta.com/rankings"
    assert payload["zone"] == "web_unlocker1"
    assert payload["format"] == "raw"
    assert payload["country"] == "us"
    # Default method is GET so ``method`` key is omitted (matches verified probes).
    assert "method" not in payload
    # No body/headers for a plain GET.
    assert "body" not in payload
    assert "headers" not in payload
    # ``render`` is NOT a valid Bright Data key — must not be present.
    assert "render" not in payload

    # Response unwrap: upstream status + body + final_url surface correctly.
    assert response.status == 200
    assert response.body == body_html
    assert response.final_url == "https://playtennis.usta.com/rankings"


@respx.mock
async def test_bright_data_post_with_body_and_headers() -> None:
    """POST + body + extra_headers map to the verified payload keys."""
    upstream_json = b'{"data":{"publicPersons":{"items":[]}}}'
    route = respx.post(BRIGHT_DATA_API_URL).mock(
        return_value=httpx.Response(
            200,
            content=upstream_json,
            headers={
                "x-brd-response-status": "200",
                "x-brd-response-url": (
                    "https://prd-itf-kube.clubspark.pro/tods-gw-api/graphql"
                ),
            },
        )
    )

    backend = BrightDataWebUnlockerBackend(api_key="brd_token_xyz")
    graphql_query = json.dumps(
        {
            "query": (
                "query { publicPersons(filter: { search: "
                '{ term: "Rudy Quan" } }) { items { id } } }'
            )
        }
    )
    try:
        response = await backend.fetch(
            "https://prd-itf-kube.clubspark.pro/tods-gw-api/graphql",
            method="POST",
            body=graphql_query,
            extra_headers={"Content-Type": "application/json"},
            country="us",
        )
    finally:
        await backend.close()

    assert route.called
    request: httpx.Request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer brd_token_xyz"

    payload = json.loads(request.content)
    # The verified default zone kicks in when the caller doesn't override.
    assert payload["zone"] == "web_unlocker1"
    assert payload["url"] == (
        "https://prd-itf-kube.clubspark.pro/tods-gw-api/graphql"
    )
    assert payload["format"] == "raw"
    assert payload["country"] == "us"
    assert payload["method"] == "POST"
    # Key MUST be ``body`` — not ``data``/``payload`` (verified 2026-05-11).
    assert payload["body"] == graphql_query
    assert "data" not in payload
    assert payload["headers"] == {"Content-Type": "application/json"}

    assert response.status == 200
    assert response.body == upstream_json


@respx.mock
async def test_bright_data_render_js_flag_is_documented_no_op() -> None:
    """``render_js`` is accepted for protocol compat but never emitted."""
    route = respx.post(BRIGHT_DATA_API_URL).mock(
        return_value=httpx.Response(
            200,
            content=b"<html></html>",
            headers={"x-brd-response-status": "200"},
        )
    )

    backend = BrightDataWebUnlockerBackend(api_key="t")
    try:
        # Both True and False must produce the same minimal payload — the
        # flag is documented as a no-op for Bright Data.
        await backend.fetch("https://example.com", render_js=True)
        await backend.fetch("https://example.com", render_js=False)
    finally:
        await backend.close()

    assert route.call_count == 2
    for call in route.calls:
        payload = json.loads(call.request.content)
        assert "render" not in payload
        assert "render_js" not in payload


@respx.mock
async def test_bright_data_raises_on_provider_error() -> None:
    """A 5xx from Bright Data surfaces as ResidentialProxyError, not silent."""
    respx.post(BRIGHT_DATA_API_URL).mock(
        return_value=httpx.Response(503, text="quota exceeded")
    )

    backend = BrightDataWebUnlockerBackend(api_key="t", zone="web_unlocker1")
    try:
        with pytest.raises(ResidentialProxyError) as exc_info:
            await backend.fetch("https://playtennis.usta.com/", country="us")
    finally:
        await backend.close()

    assert "503" in str(exc_info.value)


# ---------------------------------------------------------------------------
# ScrapFly
# ---------------------------------------------------------------------------


@respx.mock
async def test_scrapfly_gets_with_url_and_key_and_asp_flag() -> None:
    """ScrapFly backend issues a GET with url+key+asp+render_js+country."""
    envelope = {
        "result": {
            "content": "<html>scrapfly upstream body</html>",
            "status_code": 200,
            "url": "https://playtennis.usta.com/rankings/final",
            "response_headers": {"Content-Type": "text/html"},
        }
    }
    route = respx.get(SCRAPFLY_API_URL).mock(
        return_value=httpx.Response(200, json=envelope)
    )

    backend = ScrapflyBackend(api_key="sf_abc123")
    try:
        response = await backend.fetch(
            "https://playtennis.usta.com/rankings", country="us"
        )
    finally:
        await backend.close()

    assert route.called
    request: httpx.Request = route.calls.last.request

    # Query string contains the documented keys.
    qs = dict(httpx.QueryParams(request.url.query.decode()))
    assert qs["url"] == "https://playtennis.usta.com/rankings"
    assert qs["key"] == "sf_abc123"
    assert qs["country"] == "us"
    assert qs["asp"] == "true"
    assert qs["render_js"] == "true"

    # Unwrap: status + body + final_url come from the JSON envelope, not
    # the proxy's outer headers.
    assert response.status == 200
    assert response.body == b"<html>scrapfly upstream body</html>"
    assert response.final_url == "https://playtennis.usta.com/rankings/final"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_factory_raises_when_provider_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without RESIDENTIAL_PROXY_PROVIDER the factory raises a config error."""
    from src import config as config_module

    monkeypatch.setattr(config_module.settings, "residential_proxy_provider", None)
    with pytest.raises(ResidentialProxyConfigError):
        get_residential_proxy()


def test_factory_raises_when_bright_data_api_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``brightdata`` without BRIGHT_DATA_API_KEY raises a clear error."""
    from src import config as config_module

    monkeypatch.setattr(
        config_module.settings, "residential_proxy_provider", "brightdata"
    )
    monkeypatch.setattr(config_module.settings, "bright_data_api_key", None)
    # zone has a non-empty default; the missing piece is the API key.
    monkeypatch.setattr(
        config_module.settings, "bright_data_zone", "web_unlocker1"
    )

    with pytest.raises(ResidentialProxyConfigError) as exc_info:
        get_residential_proxy()
    msg = str(exc_info.value)
    assert "BRIGHT_DATA_API_KEY" in msg


def test_factory_builds_brightdata_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``brightdata`` with an API key returns a BrightDataWebUnlockerBackend."""
    from pydantic import SecretStr

    from src import config as config_module

    monkeypatch.setattr(
        config_module.settings, "residential_proxy_provider", "brightdata"
    )
    monkeypatch.setattr(
        config_module.settings,
        "bright_data_api_key",
        SecretStr("brd_token_factory"),
    )
    monkeypatch.setattr(
        config_module.settings, "bright_data_zone", "web_unlocker1"
    )

    backend = get_residential_proxy()
    assert isinstance(backend, BrightDataWebUnlockerBackend)


def test_factory_builds_scrapfly_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``scrapfly`` with a key returns a ScrapflyBackend instance."""
    from pydantic import SecretStr

    from src import config as config_module

    monkeypatch.setattr(
        config_module.settings, "residential_proxy_provider", "scrapfly"
    )
    monkeypatch.setattr(
        config_module.settings, "scrapfly_api_key", SecretStr("sf_test")
    )

    backend = get_residential_proxy()
    assert isinstance(backend, ScrapflyBackend)
