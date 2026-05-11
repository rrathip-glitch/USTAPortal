"""Unit tests for :mod:`src.fetch.residential_proxy`.

Network is mocked via :mod:`respx`; tests never hit the real provider
endpoints. The Bright Data + ScrapFly URL formats and auth patterns are
asserted against the live provider docs as of late 2025; if a backend's
production shape drifts these tests should catch the mismatch.
"""

from __future__ import annotations

import base64

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
async def test_bright_data_posts_with_basic_auth_and_zone_payload() -> None:
    """Bright Data backend posts the documented zone payload with Basic auth."""
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
        customer_id="cust42",
        zone="web_unlocker1",
        password="hunter2",
    )
    try:
        response = await backend.fetch(
            "https://playtennis.usta.com/rankings", country="us"
        )
    finally:
        await backend.close()

    assert route.called, "Bright Data endpoint must be hit exactly once"
    request: httpx.Request = route.calls.last.request

    # Basic auth header — ``brd-customer-<id>-zone-<zone>:password`` base64.
    expected_token = base64.b64encode(
        b"brd-customer-cust42-zone-web_unlocker1:hunter2"
    ).decode()
    assert request.headers["authorization"] == f"Basic {expected_token}"

    # Payload should be JSON with the documented keys.
    import json as _json

    payload = _json.loads(request.content)
    assert payload["url"] == "https://playtennis.usta.com/rankings"
    assert payload["zone"] == "web_unlocker1"
    assert payload["format"] == "raw"
    assert payload["country"] == "us"
    # render_js=True (default) => render flag set
    assert payload.get("render") is True

    # Response unwrap: upstream status + body + final_url surface correctly.
    assert response.status == 200
    assert response.body == body_html
    assert response.final_url == "https://playtennis.usta.com/rankings"


@respx.mock
async def test_bright_data_raises_on_provider_error() -> None:
    """A 5xx from Bright Data surfaces as ResidentialProxyError, not silent."""
    respx.post(BRIGHT_DATA_API_URL).mock(
        return_value=httpx.Response(503, text="quota exceeded")
    )

    backend = BrightDataWebUnlockerBackend(
        customer_id="x", zone="y", password="z"
    )
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


def test_factory_raises_when_bright_data_credentials_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``brightdata`` without the three credentials raises a clear error."""
    from src import config as config_module

    monkeypatch.setattr(
        config_module.settings, "residential_proxy_provider", "brightdata"
    )
    monkeypatch.setattr(config_module.settings, "bright_data_customer_id", None)
    monkeypatch.setattr(config_module.settings, "bright_data_zone", None)
    monkeypatch.setattr(config_module.settings, "bright_data_password", None)

    with pytest.raises(ResidentialProxyConfigError) as exc_info:
        get_residential_proxy()
    msg = str(exc_info.value)
    assert "BRIGHT_DATA_CUSTOMER_ID" in msg
    assert "BRIGHT_DATA_ZONE" in msg
    assert "BRIGHT_DATA_PASSWORD" in msg


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
