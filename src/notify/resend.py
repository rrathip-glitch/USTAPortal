"""Resend HTTP backend for the notify module.

Talks to the Resend transactional email API
(``POST https://api.resend.com/emails``) over httpx, with tenacity-driven
retries on 5xx. 4xx errors fail fast — they indicate auth or payload problems
that a retry will not fix.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import settings
from src.notify import ConfigurationError, NotifyResult

if TYPE_CHECKING:
    from collections.abc import Iterable

RESEND_ENDPOINT = "https://api.resend.com/emails"

DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_BACKOFF_BASE = 1.0
DEFAULT_BACKOFF_CAP = 4.0
DEFAULT_TIMEOUT_SECONDS = 30.0


class _RetryableServerError(RuntimeError):
    """Internal marker driving tenacity retry on 5xx responses."""


class ResendBackend:
    def __init__(
        self,
        api_key: str | None = None,
        from_address: str | None = None,
        default_to: str | None = None,
        client: httpx.AsyncClient | None = None,
        max_attempts: int = DEFAULT_RETRY_ATTEMPTS,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        backoff_cap: float = DEFAULT_BACKOFF_CAP,
    ) -> None:
        self._api_key = api_key if api_key is not None else _resolve_api_key()
        self._from_address = from_address if from_address is not None else settings.notify_from
        self._default_to = default_to if default_to is not None else settings.notify_to
        self._client = client
        self._owns_client = client is None
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap

    async def send(
        self,
        subject: str,
        body: str,
        to: str | list[str] | None = None,
    ) -> NotifyResult:
        if self._api_key is None:
            raise ConfigurationError("RESEND_API_KEY is not configured.")

        recipients = _resolve_recipients(to, self._default_to)

        payload: dict[str, Any] = {
            "from": self._from_address,
            "to": recipients,
            "subject": subject,
            "text": body,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        client = self._client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS)
        try:
            try:
                async for attempt in AsyncRetrying(
                    stop=stop_after_attempt(self._max_attempts),
                    wait=wait_exponential(
                        multiplier=self._backoff_base,
                        max=self._backoff_cap,
                    ),
                    retry=retry_if_exception_type(_RetryableServerError),
                    reraise=False,
                ):
                    with attempt:
                        result = await self._send_once(client, headers, payload)
                        if result is not None:
                            return result
            except RetryError as exc:
                inner = exc.last_attempt.exception() if exc.last_attempt else None
                detail = str(inner) if inner else "server error"
                return NotifyResult(ok=False, provider_message_id=None, error=detail)
        finally:
            if self._owns_client:
                await client.aclose()

        return NotifyResult(
            ok=False,
            provider_message_id=None,
            error="Resend send exhausted retries without a response.",
        )

    async def _send_once(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> NotifyResult | None:
        try:
            response = await client.post(RESEND_ENDPOINT, json=payload, headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise _RetryableServerError(f"network error: {exc}") from exc

        status = response.status_code

        if 200 <= status < 300:
            message_id = _extract_message_id(response)
            return NotifyResult(ok=True, provider_message_id=message_id, error=None)

        if status in (401, 403):
            return NotifyResult(
                ok=False,
                provider_message_id=None,
                error=f"Resend auth error {status}: {_safe_error_text(response)}",
            )

        if 500 <= status < 600:
            raise _RetryableServerError(f"HTTP {status}: {_safe_error_text(response)}")

        return NotifyResult(
            ok=False,
            provider_message_id=None,
            error=f"Resend error {status}: {_safe_error_text(response)}",
        )


def _resolve_api_key() -> str | None:
    raw = settings.resend_api_key
    if raw is None:
        return None
    value = raw.get_secret_value()
    return value or None


def _resolve_recipients(
    to: str | list[str] | None,
    default_to: str | None,
) -> list[str]:
    chosen: str | Iterable[str] | None = to if to is not None else default_to
    if chosen is None:
        raise ConfigurationError(
            "No recipient provided and NOTIFY_TO is not configured."
        )
    if isinstance(chosen, str):
        return [chosen]
    recipients = list(chosen)
    if not recipients:
        raise ConfigurationError("Recipient list is empty.")
    return recipients


def _extract_message_id(response: httpx.Response) -> str | None:
    try:
        data = response.json()
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("id")
    return str(value) if value is not None else None


def _safe_error_text(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(data, dict):
        message = data.get("message") or data.get("error")
        if message:
            return str(message)
    return str(data)[:200]
