"""Unit tests for :mod:`src.fetch.utr_client`.

Drives the client with respx-mocked responses (no real network). Validates:

- ``search_players`` returns the parsed JSON envelope.
- Sends ``Origin: https://app.utrsports.net`` on every request.
- Writes a cache envelope under ``<raw_cache_dir>/utr/<2hex>/<sha256>.json``.
- 403 raises :class:`BlockedEgressError`.
- 5xx retries via tenacity; exhausted retries raise :class:`TransientNetworkError`.
- Empty ``query`` raises ``ValueError`` before issuing any request.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from src.fetch.utr_client import (
    BASE_URL,
    PATH_SEARCH_PLAYERS,
    BlockedEgressError,
    TransientNetworkError,
    UTRClient,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _envelope(ids: list[str], total: int | None = None) -> dict[str, Any]:
    if total is None:
        total = len(ids)
    return {
        "hits": [
            {
                "id": hid,
                "score": 100.0,
                "source": {
                    "id": int(hid) if hid.isdigit() else 0,
                    "firstName": "Test",
                    "lastName": f"Player{hid}",
                    "displayName": f"Test Player{hid}",
                    "gender": "Male",
                    "singlesUtr": 0.0,
                    "doublesUtr": 0.0,
                    "location": {
                        "display": "Somewhere, FL",
                        "cityName": "Somewhere",
                        "stateName": "Florida",
                        "countryName": "United States",
                    },
                },
            }
            for hid in ids
        ],
        "total": total,
        "totalAllowed": total,
        "maxScore": 100.0,
        "aggregations": {},
    }


# ---------------------------------------------------------------------------
# Happy path: returns parsed envelope, sends correct headers
# ---------------------------------------------------------------------------


async def test_search_players_returns_envelope(tmp_path: Path) -> None:
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{BASE_URL}{PATH_SEARCH_PLAYERS}").mock(
            return_value=httpx.Response(200, json=_envelope(["3059480"]))
        )
        async with UTRClient(
            raw_cache_dir=tmp_path / "raw", interval_seconds=0
        ) as client:
            result = await client.search_players("Janav Thasen", top=10)

    assert route.called
    assert isinstance(result, dict)
    assert result["hits"][0]["id"] == "3059480"
    # Verify the request URL carries the query and top params.
    request = route.calls.last.request
    assert request.url.params["query"] == "Janav Thasen"
    assert request.url.params["top"] == "10"


async def test_search_players_sends_origin_header(tmp_path: Path) -> None:
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{BASE_URL}{PATH_SEARCH_PLAYERS}").mock(
            return_value=httpx.Response(200, json=_envelope(["1"]))
        )
        async with UTRClient(
            raw_cache_dir=tmp_path / "raw", interval_seconds=0
        ) as client:
            await client.search_players("anyone")

    headers = route.calls.last.request.headers
    assert headers.get("origin") == "https://app.utrsports.net"
    assert headers.get("referer") == "https://app.utrsports.net/"


# ---------------------------------------------------------------------------
# Cache write
# ---------------------------------------------------------------------------


async def test_search_players_writes_cache_envelope(tmp_path: Path) -> None:
    with respx.mock() as mock:
        mock.get(f"{BASE_URL}{PATH_SEARCH_PLAYERS}").mock(
            return_value=httpx.Response(200, json=_envelope(["abc"]))
        )
        async with UTRClient(
            raw_cache_dir=tmp_path / "raw", interval_seconds=0
        ) as client:
            await client.search_players("anyone", top=5)

    cache_root = tmp_path / "raw" / "utr"
    assert cache_root.exists()
    cached_files = list(cache_root.rglob("*.json"))
    assert len(cached_files) == 1

    # Cache path layout: utr/<first-2-hex>/<sha256>.json
    cached = cached_files[0]
    assert cached.parent.parent.name == "utr"
    assert len(cached.parent.name) == 2

    envelope = json.loads(cached.read_text())
    assert envelope["source"] == "utr"
    assert envelope["request"]["method"] == "GET"
    assert envelope["response"]["status"] == 200
    assert envelope["response"]["body"]["hits"][0]["id"] == "abc"


# ---------------------------------------------------------------------------
# 403 -> BlockedEgressError
# ---------------------------------------------------------------------------


async def test_403_raises_blocked_egress(tmp_path: Path) -> None:
    with respx.mock() as mock:
        mock.get(f"{BASE_URL}{PATH_SEARCH_PLAYERS}").mock(
            return_value=httpx.Response(403, json={"message": "Forbidden"})
        )
        async with UTRClient(
            raw_cache_dir=tmp_path / "raw", interval_seconds=0
        ) as client:
            with pytest.raises(BlockedEgressError):
                await client.search_players("anyone")


# ---------------------------------------------------------------------------
# 5xx retry / exhaustion
# ---------------------------------------------------------------------------


async def test_5xx_retries_then_succeeds(tmp_path: Path) -> None:
    with respx.mock() as mock:
        route = mock.get(f"{BASE_URL}{PATH_SEARCH_PLAYERS}").mock(
            side_effect=[
                httpx.Response(503, text="oops"),
                httpx.Response(200, json=_envelope(["x"])),
            ]
        )
        async with UTRClient(
            raw_cache_dir=tmp_path / "raw", interval_seconds=0
        ) as client:
            result = await client.search_players("anyone")
    assert route.call_count == 2
    assert result["hits"][0]["id"] == "x"


async def test_5xx_retries_exhausted_raises_transient(tmp_path: Path) -> None:
    with respx.mock() as mock:
        mock.get(f"{BASE_URL}{PATH_SEARCH_PLAYERS}").mock(
            return_value=httpx.Response(502, text="bad gateway")
        )
        async with UTRClient(
            raw_cache_dir=tmp_path / "raw", interval_seconds=0
        ) as client:
            with pytest.raises(TransientNetworkError):
                await client.search_players("anyone")


# ---------------------------------------------------------------------------
# Empty query
# ---------------------------------------------------------------------------


async def test_empty_query_raises_value_error_before_request(tmp_path: Path) -> None:
    """An empty/whitespace query must not issue any HTTP request."""
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(f"{BASE_URL}{PATH_SEARCH_PLAYERS}").mock(
            return_value=httpx.Response(200, json=_envelope([]))
        )
        async with UTRClient(
            raw_cache_dir=tmp_path / "raw", interval_seconds=0
        ) as client:
            with pytest.raises(ValueError, match="non-empty"):
                await client.search_players("")
            with pytest.raises(ValueError, match="non-empty"):
                await client.search_players("   ")
        assert not route.called
