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

# Bright Data Web Unlocker — REST-mode endpoint. Verified live on 2026-05-11
# against playtennis.usta.com (static HTML) and prd-itf-kube.clubspark.pro
# (GraphQL POST). See data/reference/known_urls.md, "Bright Data Web Unlocker
# — verified API shape (2026-05-11)" for the exact payload schema and the
# header conventions (Authorization: Bearer; upstream status via
# ``x-brd-response-status``).
BRIGHT_DATA_API_URL = "https://api.brightdata.com/request"

# Default Bright Data zone. The trial account ships with a single zone named
# ``web_unlocker1``; the JSON payload's ``zone`` field is required, so this
# default keeps callers from having to pass it explicitly.
BRIGHT_DATA_DEFAULT_ZONE = "web_unlocker1"

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
      Clubspark targets (single-page React apps). Some providers (Bright
      Data Web Unlocker with ``format: "raw"``) render automatically and
      the flag is a no-op; conformers document their behaviour.
    - Honour the ``country`` flag: ISO-3166-1 alpha-2 (lowercase).
      ``"us"`` is the default since every USTA target is US-geographic.
    - Accept an optional HTTP ``method`` (``"GET"`` or ``"POST"``) plus a
      raw ``body`` and ``extra_headers`` for POST flows (Clubspark
      GraphQL goes through here).
    """

    async def fetch(
        self,
        url: str,
        *,
        method: Literal["GET", "POST"] = "GET",
        body: str | None = None,
        extra_headers: dict[str, str] | None = None,
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
    """Bright Data Web Unlocker adapter — REST-mode, Bearer auth.

    Bright Data's Web Unlocker exposes a JSON POST endpoint that takes a
    target URL plus optional ``method``/``body``/``headers`` for upstream
    POSTs, and returns the upstream body verbatim under ``format: "raw"``.
    All Cloudflare / JS-rendering ceremony is handled server-side.

    Authentication is REST-mode Bearer:
    ``Authorization: Bearer <api_token>``. (The older proxy-mode style
    used HTTP Basic with username ``brd-customer-<id>-zone-<zone>``;
    we're not using that.)

    Payload shape (verified live 2026-05-11 — see
    ``data/reference/known_urls.md`` "Bright Data Web Unlocker — verified
    API shape"):

    .. code-block:: json

        {
          "zone": "web_unlocker1",      // required
          "url": "<target>",            // required
          "format": "raw",              // returns upstream body verbatim
          "country": "us",              // ISO-2; controls residential exit IP
          "method": "POST",             // optional; default GET
          "body": "<raw post body>",    // optional; key is "body" not "data"
          "headers": { "...": "..." }   // optional; passed through to target
        }

    The API rejects unknown keys with
    ``{"error":"Request validation failed","error_code":"validation"}``,
    so this adapter only emits the documented keys.

    The ``render_js`` flag is a no-op for Bright Data Web Unlocker.
    ``format: "raw"`` already returns rendered upstream content (Bright
    Data executes JS and clears Cloudflare server-side without an
    explicit render flag — verified against Cloudflare-fronted Clubspark
    on 2026-05-11). The flag is retained for protocol compatibility with
    other backends (e.g. ScrapFly) that do require it.
    """

    def __init__(
        self,
        api_key: str,
        zone: str = BRIGHT_DATA_DEFAULT_ZONE,
        *,
        api_url: str = BRIGHT_DATA_API_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._zone = zone
        self._api_url = api_url
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client: bool = client is None

    async def fetch(
        self,
        url: str,
        *,
        method: Literal["GET", "POST"] = "GET",
        body: str | None = None,
        extra_headers: dict[str, str] | None = None,
        render_js: bool = True,
        country: str = "us",
    ) -> ResidentialProxyResponse:
        # ``render_js`` is accepted for protocol compatibility but ignored —
        # ``format: "raw"`` already returns rendered output. See class
        # docstring.
        del render_js

        payload: dict[str, object] = {
            "zone": self._zone,
            "url": url,
            "format": "raw",
            "country": country.lower(),
        }
        # Only emit ``method`` when it differs from the API default (GET).
        # The API treats an absent ``method`` as GET; omitting it keeps the
        # payload minimal and matches the verified probes.
        if method != "GET":
            payload["method"] = method
        # The verified key is ``body`` — NOT ``data`` / ``payload`` /
        # ``postdata``. The API rejects unknown keys with a validation error.
        if body is not None:
            payload["body"] = body
        if extra_headers:
            payload["headers"] = dict(extra_headers)

        try:
            response = await self._client.post(
                self._api_url,
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
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
            upstream_status = (
                int(upstream_status_hdr)
                if upstream_status_hdr
                else response.status_code
            )
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
        method: Literal["GET", "POST"] = "GET",
        body: str | None = None,
        extra_headers: dict[str, str] | None = None,
        render_js: bool = True,
        country: str = "us",
    ) -> ResidentialProxyResponse:
        # ScrapFly's GET-based scrape API does not support upstream POST
        # bodies through this adapter today. The Clubspark POST flow goes
        # through Bright Data; ScrapFly is the GET-only fallback.
        if method != "GET" or body is not None or extra_headers:
            raise ResidentialProxyError(
                "ScrapFly backend only supports GET fetches in this adapter; "
                "POST/body/headers passthrough is not wired."
            )
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

    api_key = (
        live_settings.bright_data_api_key.get_secret_value()
        if live_settings.bright_data_api_key is not None
        else ""
    )
    zone = live_settings.bright_data_zone or BRIGHT_DATA_DEFAULT_ZONE
    if not api_key:
        raise ResidentialProxyConfigError(
            "Bright Data backend missing required credential: "
            "BRIGHT_DATA_API_KEY (set the REST-mode Bearer token in .env)."
        )
    return BrightDataWebUnlockerBackend(api_key=api_key, zone=zone)


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
