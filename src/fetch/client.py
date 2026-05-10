"""Rate-limited fetch layer.

Wraps :class:`UstaSession` with politeness controls (token bucket, jitter,
retry with exponential backoff on transient errors, ``Retry-After`` honoring)
and writes every successful response into the raw cache before returning it.

The cache key is a SHA-256 of the canonical request signature
(method + URL + sorted query params + sorted body keys). The path layout is
``<raw_cache_dir>/<first-2-hex>/<full-hex>.<ext>`` where the extension is
chosen from the response Content-Type. Body of the file is JSON with a
``request`` block (with sensitive headers redacted), a ``response`` block
(status, headers, body), and a ``fetched_at`` ISO-8601 UTC timestamp.

Recon-dependent decisions still pending — Strategy A vs B vs C from ADR-001 —
are TODO-tagged where they bite. The defaults here assume Strategy A (httpx
with replayed cookies) since that's what RESEARCH.md predicts.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import httpx

from src.config import settings

if TYPE_CHECKING:
    from src.auth.session import UstaSession

# Defaults wired in line with SPEC.md Section 6 ("rate limiting and politeness").
DEFAULT_RETRIES = 4
DEFAULT_BACKOFF_BASE = 1.0
DEFAULT_BACKOFF_CAP = 16.0
DEFAULT_JITTER_RATIO = 0.2  # +/- 20%
DEFAULT_GRAPHQL_ENDPOINT = "https://prod-us-kube.clubspark.io/usta/tournaments/api/graphql"

# Header names whose values must never reach the cache.
REDACTED_HEADERS: frozenset[str] = frozenset({"cookie", "authorization"})
REDACTED_HEADER_PREFIXES: tuple[str, ...] = ("x-auth",)
REDACTED_PLACEHOLDER = "[REDACTED]"

# Lowercase substrings in the response body that hint at a captcha / bot wall.
BOT_CHALLENGE_BODY_PATTERNS: tuple[str, ...] = (
    "captcha",
    "verify you are human",
    "are you a robot",
    "access denied",
    "cf-challenge",
)


class RateLimitedError(RuntimeError):
    """Raised when the server signals rate limiting (429) and retries are exhausted."""


class TransientNetworkError(RuntimeError):
    """Raised on connect/read timeouts and 5xx after retries are exhausted."""


class BotChallengeError(RuntimeError):
    """Raised when the response looks like a captcha / bot mitigation page."""


class AuthExpiredError(RuntimeError):
    """Raised on 401/403 — the caller should re-login and retry."""


class FetchClient:
    """Async, rate-limited, cookie-aware HTTP client with raw-response caching."""

    def __init__(
        self,
        session: UstaSession | None = None,
        raw_cache_dir: Path | None = None,
        interval_seconds: float | None = None,
        max_retries: int = DEFAULT_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        backoff_cap: float = DEFAULT_BACKOFF_CAP,
        jitter_ratio: float = DEFAULT_JITTER_RATIO,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._session = session
        self.raw_cache_dir = Path(raw_cache_dir) if raw_cache_dir else settings.raw_cache_dir
        self.interval_seconds = (
            interval_seconds
            if interval_seconds is not None
            else settings.request_interval_seconds
        )
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self.jitter_ratio = jitter_ratio

        self._client: httpx.AsyncClient = client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = client is None

        self._last_request_at: float | None = None
        self._lock = asyncio.Lock()

    # -- async context management --------------------------------------------------

    async def __aenter__(self) -> FetchClient:
        if self._session is not None:
            await self._sync_cookies_from_session()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # -- public API ----------------------------------------------------------------

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return await self._request("GET", url, params=params, headers=headers)

    async def post(
        self,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return await self._request(
            "POST", url, json_body=json, data=data, headers=headers
        )

    async def fetch_graphql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        endpoint: str = DEFAULT_GRAPHQL_ENDPOINT,
    ) -> dict[str, Any]:
        """Convenience: POST a GraphQL query and return the parsed JSON body."""

        body: dict[str, Any] = {"query": query, "variables": variables or {}}
        response = await self.post(
            endpoint,
            json=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        return cast(dict[str, Any], response.json())

    # -- internals -----------------------------------------------------------------

    async def _sync_cookies_from_session(self) -> None:
        """Pull the auth session's cookies into the httpx client cookie jar."""

        assert self._session is not None
        cookies = await self._session.cookies()
        for c in cookies:
            name = c.get("name")
            value = c.get("value")
            if not name or value is None:
                continue
            self._client.cookies.set(
                name,
                str(value),
                domain=c.get("domain", "") or "",
                path=c.get("path", "/") or "/",
            )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """One outbound request, with rate-limit + retry + cache."""

        attempt = 0
        last_exc: Exception | None = None

        while attempt < self.max_retries:
            attempt += 1
            await self._respect_rate_limit()

            try:
                response = await self._client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    data=data,
                    headers=headers,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    raise TransientNetworkError(
                        f"Network error after {attempt} attempts: {exc}"
                    ) from exc
                await self._sleep(self._backoff_for(attempt))
                continue

            # 429 — honor Retry-After if present, then back off.
            if response.status_code == 429:
                retry_after = self._parse_retry_after(response)
                if attempt >= self.max_retries:
                    raise RateLimitedError(
                        f"429 Too Many Requests after {attempt} attempts: {url}"
                    )
                wait = retry_after if retry_after is not None else self._backoff_for(attempt)
                await self._sleep(wait)
                continue

            # 5xx — retry with backoff.
            if 500 <= response.status_code < 600:
                if attempt >= self.max_retries:
                    raise TransientNetworkError(
                        f"{response.status_code} after {attempt} attempts: {url}"
                    )
                await self._sleep(self._backoff_for(attempt))
                continue

            # 401/403 — surface as auth expired (caller decides to re-login).
            if response.status_code in (401, 403):
                self._maybe_cache(method, url, params, json_body, data, headers, response)
                raise AuthExpiredError(
                    f"{response.status_code} on {url}; session likely expired."
                )

            # Bot wall heuristic on otherwise-OK responses.
            if self._looks_like_bot_challenge(response):
                self._maybe_cache(method, url, params, json_body, data, headers, response)
                raise BotChallengeError(f"Bot-challenge content returned from {url}.")

            # Success-ish (2xx, 3xx, 4xx other than 401/403/429): cache + return.
            if response.status_code < 500:
                self._maybe_cache(method, url, params, json_body, data, headers, response)
                return response

        # Unreachable in practice; keeps mypy honest.
        raise TransientNetworkError(
            f"Request to {url} failed after {self.max_retries} attempts: {last_exc!r}"
        )

    async def _respect_rate_limit(self) -> None:
        """Token-bucket-lite: ensure at least `interval_seconds` between requests."""

        async with self._lock:
            now = time.monotonic()
            if self._last_request_at is not None:
                elapsed = now - self._last_request_at
                jitter = self.interval_seconds * self.jitter_ratio
                target = self.interval_seconds + random.uniform(-jitter, jitter)
                wait = target - elapsed
                if wait > 0:
                    await self._sleep(wait)
            self._last_request_at = time.monotonic()

    @staticmethod
    async def _sleep(seconds: float) -> None:
        # Indirection so tests can mock asyncio.sleep cleanly.
        await asyncio.sleep(max(0.0, seconds))

    def _backoff_for(self, attempt: int) -> float:
        # Exponential backoff with jitter, capped.
        raw: float = min(self.backoff_cap, self.backoff_base * float(2 ** (attempt - 1)))
        jitter: float = raw * self.jitter_ratio
        return float(raw + random.uniform(-jitter, jitter))

    @staticmethod
    def _parse_retry_after(response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            # HTTP-date form not supported here — recon will tell us if USTA
            # ever returns it; for now we treat that as "use default backoff".
            return None

    def _looks_like_bot_challenge(self, response: httpx.Response) -> bool:
        ct = response.headers.get("content-type", "").lower()
        if "html" not in ct:
            return False
        try:
            text = response.text.lower()
        except Exception:  # pragma: no cover - defensive
            return False
        return any(pat in text for pat in BOT_CHALLENGE_BODY_PATTERNS)

    # -- cache writer --------------------------------------------------------------

    def _maybe_cache(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None,
        json_body: dict[str, Any] | None,
        data: dict[str, Any] | None,
        headers: dict[str, str] | None,
        response: httpx.Response,
    ) -> Path | None:
        try:
            return self._write_cache(method, url, params, json_body, data, headers, response)
        except OSError:
            # Cache write failures must not fail the fetch.
            return None

    def _write_cache(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None,
        json_body: dict[str, Any] | None,
        data: dict[str, Any] | None,
        headers: dict[str, str] | None,
        response: httpx.Response,
    ) -> Path:
        body = json_body if json_body is not None else data
        digest = compute_cache_key(method, url, params, body)
        ext = self._extension_for(response)
        cache_path = self.raw_cache_dir / digest[:2] / f"{digest}{ext}"
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        envelope: dict[str, Any] = {
            "fetched_at": datetime.now(UTC).isoformat(),
            "request": {
                "method": method,
                "url": url,
                "params": params,
                "headers": redact_headers(headers or {}),
                "body": body,
            },
            "response": {
                "status": response.status_code,
                "headers": dict(response.headers),
                "body": self._serialize_body(response),
            },
        }

        with cache_path.open("w", encoding="utf-8") as fh:
            json.dump(envelope, fh, ensure_ascii=False, indent=2, default=str)

        return cache_path

    @staticmethod
    def _extension_for(response: httpx.Response) -> str:
        ct = response.headers.get("content-type", "").lower()
        if "json" in ct:
            return ".json"
        if "html" in ct:
            return ".html"
        return ".bin.json"

    @staticmethod
    def _serialize_body(response: httpx.Response) -> Any:
        ct = response.headers.get("content-type", "").lower()
        if "json" in ct:
            try:
                return response.json()
            except ValueError:
                return response.text
        if "html" in ct or "text" in ct:
            return response.text
        # Binary body: fall back to a length-only marker. Recon will tell us
        # whether any USTA response is binary; if so we'll switch to base64.
        return {"_binary_length": len(response.content)}


# -- module-level helpers ---------------------------------------------------------


def compute_cache_key(
    method: str,
    url: str,
    params: dict[str, Any] | None,
    body: dict[str, Any] | None,
) -> str:
    """Stable SHA-256 over (method, url, sorted-params, sorted-body-keys)."""

    norm_params = _stable_json(params or {})
    # Spec says "sorted body keys" — we hash the sorted keys plus their values
    # (sorted on serialization) so identical bodies produce identical keys.
    norm_body_keys = sorted((body or {}).keys())
    norm_body = _stable_json({k: (body or {})[k] for k in norm_body_keys})

    payload = "|".join([method.upper(), url, norm_params, norm_body])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy of ``headers`` with sensitive fields blanked out."""

    out: dict[str, str] = {}
    for key, value in headers.items():
        lower = key.lower()
        if lower in REDACTED_HEADERS or any(
            lower.startswith(prefix) for prefix in REDACTED_HEADER_PREFIXES
        ):
            out[key] = REDACTED_PLACEHOLDER
        else:
            out[key] = value
    return out
