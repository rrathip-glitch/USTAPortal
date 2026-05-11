"""Provider-agnostic residential-proxy adapter layer.

The Clubspark surface (``playtennis.usta.com`` and the kube hosts at
``*.clubspark.io`` / ``*.clubspark.pro``) is Cloudflare-fronted with an
IP/ASN-layer block against this environment's egress (see ADR-001 and
``data/reference/known_urls.md``). To reach it from a CI/dev box the
caller must route the request through a residential-proxy provider that
gives us an IP a real consumer might own. Two providers are in scope:

- **Bright Data Web Unlocker** (primary). Pay-per-request unlocker service
  that handles TLS fingerprint, headers, and JavaScript rendering for
  Cloudflare-fronted targets.
- **ScrapFly** (fallback). Simpler GET-based scrape API with ``asp=true``
  for anti-scraping bypass and ``render_js=true`` for SPA rendering.

This module exposes a single abstract protocol :class:`ResidentialProxyBackend`
plus one concrete adapter per provider. The :func:`get_residential_proxy`
factory chooses one based on :attr:`src.config.settings.residential_proxy_provider`.

All adapters are async (``httpx.AsyncClient``-backed) and return a uniform
:class:`ResidentialProxyResponse` so the upstream Clubspark client doesn't
need to know which provider is in flight. When the user provides the API
keys, wiring is one ``RESIDENTIAL_PROXY_PROVIDER=<name>`` env var away.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

import httpx

__all__ = [
    "BrightDataWebUnlockerBackend",
    "ResidentialProxyBackend",
    "ResidentialProxyConfigError",
    "ResidentialProxyError",
    "ResidentialProxyResponse",
    "ScrapflyBackend",
    "get_residential_proxy",
]


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Endpoints / constants
# ---------------------------------------------------------------------------

# TODO: confirm exact endpoint shape against Bright Data's Web Unlocker
# docs when an API key is provided. Docs: https://docs.brightdata.com/scraping-automation/web-unlocker/overview
# The placeholder URL below follows Bright Data's public docs as of late 2025;
# the actual `format=raw` payload and Basic-auth scheme are documented at
# https://docs.brightdata.com/api-reference/web-unlocker/sending-requests .
BRIGHT_DATA_API_URL = "https://api.brightdata.com/request"

# ScrapFly's scrape endpoint is GET-based with query parameters. Docs:
# https://scrapfly.io/docs/scrape-api/getting-started
SCRAPFLY_API_URL = "https://api.scrapfly.io/scrape"

# Default per-request timeout. Cloudflare-fronted rendering can be slow.
DEFAULT_TIMEOUT_SECONDS = 60.0


# ---------------------------------------------------------------------------
# Response + error types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResidentialProxyResponse:
    """Uniform response returned by every backend.

    Attributes:
        status:    The HTTP status code as reported by the upstream origin
                   (NOT the proxy itself — providers unwrap that for us).
        headers:   Response headers from the upstream origin, lowercased keys.
        body:      Raw response body bytes from the upstream origin.
        final_url: The URL the upstream origin actually served (after redirects).
    """

    status: int
    headers: dict[str, str]
    body: bytes
    final_url: str


class ResidentialProxyError(RuntimeError):
    """Raised when the residential-proxy provider returns a non-success response.

    Distinct from :class:`httpx.HTTPError` so callers can catch proxy-level
    failures (auth, quota, malformed payload) separately from upstream-origin
    statuses, which are surfaced through :class:`ResidentialProxyResponse.status`.
    """


class ResidentialProxyConfigError(RuntimeError):
    """Raised when the chosen backend is missing required credentials.

    The factory raises this when ``RESIDENTIAL_PROXY_PROVIDER`` is set but
    one or more of the provider's credentials are unset, so the caller
    can surface a clear "please configure X" message rather than a 401
    from the provider.
    """


# ---------------------------------------------------------------------------
# Abstract protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ResidentialProxyBackend(Protocol):
    """Provider-agnostic fetch interface for residential-proxy services.

    Conformers are async and return a :class:`ResidentialProxyResponse`.
    All implementations must:

    - Issue requests via ``httpx.AsyncClient``.
    - Honour the ``render_js`` flag: ``True`` means render JavaScript /
      execute SPA bootstrap before snapshotting the DOM. Required for the
      Clubspark targets (single-page React apps).
    - Honour the ``country`` flag: ISO-3166-1 alpha-2 (lowercase).
      ``"us"`` is the default since every USTA target is US-geographic.
    """

    async def fetch(
        self,
        url: str,
        *,
        render_js: bool = True,
        country: str = "us",
    ) -> ResidentialProxyResponse:
        """Fetch ``url`` via the provider and return the unwrapped response."""
        ...

    async def close(self) -> None:
        """Release the underlying HTTP client. Safe to call multiple times."""
        ...


# ---------------------------------------------------------------------------
# Bright Data Web Unlocker
# ---------------------------------------------------------------------------


class BrightDataWebUnlockerBackend:
    """Bright Data Web Unlocker adapter.

    Bright Data's Web Unlocker exposes a JSON POST endpoint that takes a
    target URL, returns the rendered upstream body in ``format: "raw"``,
    and handles all the Cloudflare / JS-rendering ceremony server-side.

    Authentication is HTTP Basic with username
    ``brd-customer-<customer_id>-zone-<zone>`` and password being the
    zone's password — see
    https://docs.brightdata.com/api-reference/web-unlocker/sending-requests .

    TODO: validate against a real Bright Data zone once the orchestrator
    supplies credentials. The exact payload key names below
    (``zone`` / ``url`` / ``format`` / ``country`` / ``render``) follow
    Bright Data's public docs as of late 2025 — confirm + adjust on
    first live call. If the live payload differs, only this class needs
    to change; the protocol stays stable.
    """

    def __init__(
        self,
        *,
        customer_id: str,
        zone: str,
        password: str,
        api_url: str = BRIGHT_DATA_API_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._customer_id = customer_id
        self._zone = zone
        self._password = password
        self._api_url = api_url
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client: bool = client is None

    async def fetch(
        self,
        url: str,
        *,
        render_js: bool = True,
        country: str = "us",
    ) -> ResidentialProxyResponse:
        # The username pattern documented by Bright Data is
        # ``brd-customer-<id>-zone-<zone>``. The zone password is the
        # secret we pass alongside.
        username = f"brd-customer-{self._customer_id}-zone-{self._zone}"
        payload: dict[str, object] = {
            "zone": self._zone,
            "url": url,
            "format": "raw",
            "country": country.lower(),
        }
        if render_js:
            # Bright Data's Web Unlocker enables JS rendering when this flag
            # is set. The exact key name may be "render" or "render_js" —
            # confirm against live docs before shipping. See module-level
            # TODO.
            payload["render"] = True

        try:
            response = await self._client.post(
                self._api_url,
                json=payload,
                auth=(username, self._password),
            )
        except httpx.HTTPError as exc:
            raise ResidentialProxyError(
                f"Bright Data Web Unlocker request failed: {exc!r}"
            ) from exc

        if response.status_code >= 400:
            raise ResidentialProxyError(
                f"Bright Data Web Unlocker returned {response.status_code}: "
                f"{response.text[:200]!r}"
            )

        # ``format=raw`` returns the upstream origin body verbatim in the
        # response body. Bright Data surfaces upstream status via the
        # ``x-brd-response-status`` header (per their docs); fall back to
        # the proxy's own status if that header is missing.
        upstream_status_hdr = response.headers.get("x-brd-response-status")
        try:
            upstream_status = int(upstream_status_hdr) if upstream_status_hdr else response.status_code
        except ValueError:
            upstream_status = response.status_code

        final_url_hdr = response.headers.get("x-brd-response-url") or url

        return ResidentialProxyResponse(
            status=upstream_status,
            headers={k.lower(): v for k, v in response.headers.items()},
            body=response.content,
            final_url=final_url_hdr,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
            self._owns_client = False


# ---------------------------------------------------------------------------
# ScrapFly
# ---------------------------------------------------------------------------


class ScrapflyBackend:
    """ScrapFly adapter.

    ScrapFly exposes a GET-based scrape endpoint with query parameters.
    The ``asp=true`` flag toggles their anti-scraping-protection bypass
    layer (which is what we need for Cloudflare-fronted Clubspark);
    ``render_js=true`` triggers JS rendering; ``country=<iso>`` controls
    the proxy egress geography.

    Reference: https://scrapfly.io/docs/scrape-api/getting-started .
    """

    def __init__(
        self,
        *,
        api_key: str,
        api_url: str = SCRAPFLY_API_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._api_url = api_url
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client: bool = client is None

    async def fetch(
        self,
        url: str,
        *,
        render_js: bool = True,
        country: str = "us",
    ) -> ResidentialProxyResponse:
        params: dict[str, str] = {
            "url": url,
            "key": self._api_key,
            "country": country.lower(),
            "asp": "true",
            "render_js": "true" if render_js else "false",
        }
        try:
            response = await self._client.get(self._api_url, params=params)
        except httpx.HTTPError as exc:
            raise ResidentialProxyError(
                f"ScrapFly request failed: {exc!r}"
            ) from exc

        if response.status_code >= 400:
            raise ResidentialProxyError(
                f"ScrapFly returned {response.status_code}: "
                f"{response.text[:200]!r}"
            )

        # ScrapFly wraps the upstream response in a JSON envelope at
        # ``result.content`` plus metadata. Per docs:
        # https://scrapfly.io/docs/scrape-api/specification#response
        # The envelope contains:
        #   result.content      (str, the upstream body)
        #   result.status_code  (int, upstream HTTP status)
        #   result.url          (str, final upstream URL)
        #   result.response_headers (dict)
        # If parsing fails (e.g. content-type lies), fall back to the raw
        # body so the caller still sees something useful.
        try:
            envelope = response.json()
        except ValueError:
            return ResidentialProxyResponse(
                status=response.status_code,
                headers={k.lower(): v for k, v in response.headers.items()},
                body=response.content,
                final_url=url,
            )

        result: dict[str, object] = (
            envelope.get("result", {}) if isinstance(envelope, dict) else {}
        )
        upstream_content_raw: object = result.get("content", "")
        upstream_status_raw: object = result.get("status_code", response.status_code)
        upstream_final_url_raw: object = result.get("url", url)
        upstream_headers_raw: object = result.get("response_headers", {})

        # Normalise to bytes regardless of whether ScrapFly returned text or
        # base64-encoded binary; the upstream client always wants bytes.
        if isinstance(upstream_content_raw, bytes):
            body = upstream_content_raw
        else:
            body = str(upstream_content_raw).encode("utf-8")

        if isinstance(upstream_status_raw, int):
            upstream_status = upstream_status_raw
        elif isinstance(upstream_status_raw, str):
            try:
                upstream_status = int(upstream_status_raw)
            except ValueError:
                upstream_status = response.status_code
        else:
            upstream_status = response.status_code

        headers: dict[str, str]
        if isinstance(upstream_headers_raw, dict):
            headers = {str(k).lower(): str(v) for k, v in upstream_headers_raw.items()}
        else:
            headers = {}

        return ResidentialProxyResponse(
            status=upstream_status,
            headers=headers,
            body=body,
            final_url=str(upstream_final_url_raw),
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
            self._owns_client = False


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


ProviderName = Literal["brightdata", "scrapfly"]


def get_residential_proxy(
    provider: str | None = None,
) -> ResidentialProxyBackend:
    """Return a configured backend for ``provider``.

    Reads from :data:`src.config.settings` for credentials. If ``provider``
    is ``None``, falls back to :attr:`settings.residential_proxy_provider`.
    Raises :class:`ResidentialProxyConfigError` if the provider is unset or
    one of its required credentials is missing — the caller surfaces this
    as a friendly "please configure X" message.

    Settings are looked up dynamically (at call time, not at import time)
    so that test reloads of :mod:`src.config` are picked up — tests can
    monkeypatch ``src.config.settings`` between calls and see the new
    values reflected here. Mirrors :func:`src.fetch.router.configured_source_preference`.
    """
    from src.config import settings as live_settings

    chosen: str | None = provider or live_settings.residential_proxy_provider
    if not chosen:
        raise ResidentialProxyConfigError(
            "No residential-proxy provider configured. "
            "Set RESIDENTIAL_PROXY_PROVIDER=brightdata or =scrapfly in .env."
        )

    chosen_lower = chosen.lower()
    if chosen_lower == "brightdata":
        return _build_brightdata()
    if chosen_lower == "scrapfly":
        return _build_scrapfly()
    raise ResidentialProxyConfigError(
        f"Unknown residential-proxy provider {chosen!r}; "
        "expected 'brightdata' or 'scrapfly'."
    )


def _build_brightdata() -> BrightDataWebUnlockerBackend:
    from src.config import settings as live_settings

    customer_id = (
        live_settings.bright_data_customer_id.get_secret_value()
        if live_settings.bright_data_customer_id is not None
        else ""
    )
    zone = live_settings.bright_data_zone or ""
    password = (
        live_settings.bright_data_password.get_secret_value()
        if live_settings.bright_data_password is not None
        else ""
    )
    missing = [
        name
        for name, value in (
            ("BRIGHT_DATA_CUSTOMER_ID", customer_id),
            ("BRIGHT_DATA_ZONE", zone),
            ("BRIGHT_DATA_PASSWORD", password),
        )
        if not value
    ]
    if missing:
        raise ResidentialProxyConfigError(
            "Bright Data backend missing required credentials: "
            + ", ".join(missing)
        )
    return BrightDataWebUnlockerBackend(
        customer_id=customer_id,
        zone=zone,
        password=password,
    )


def _build_scrapfly() -> ScrapflyBackend:
    from src.config import settings as live_settings

    api_key = (
        live_settings.scrapfly_api_key.get_secret_value()
        if live_settings.scrapfly_api_key is not None
        else ""
    )
    if not api_key:
        raise ResidentialProxyConfigError(
            "ScrapFly backend missing required credential: SCRAPFLY_API_KEY"
        )
    return ScrapflyBackend(api_key=api_key)
