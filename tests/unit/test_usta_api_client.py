"""Unit tests for :mod:`src.fetch.usta_api_client`.

Drives the client with respx-mocked responses (no real network). Validates:

- Required-field validation on ``search_tournaments`` selection.
- Cache envelope write (path layout, body redaction).
- Retry-on-5xx via tenacity.
- BlockedEgressError on 403.
- ``get_tournament`` short-circuits to NotImplementedError for non-GUID ids.
- Pagination walks across multiple pages and de-duplicates.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from src.fetch.usta_api_client import (
    BASE_URL,
    PATH_TOURNAMENTS_QUERY,
    BlockedEgressError,
    TransientNetworkError,
    UstaApiClient,
    compute_usta_api_cache_key,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _envelope(hit_ids: list[str], total: int | None = None) -> dict[str, Any]:
    if total is None:
        total = len(hit_ids)
    return {
        "took": 5,
        "hits": {
            "total": {"value": total, "relation": "eq"},
            "hits": [
                {
                    "_id": hid,
                    "_source": {
                        "id": hid,
                        "name": f"Tournament {hid}",
                        "events": [],
                        "primaryLocation": {"town": "Sebring", "county": "FL"},
                    },
                }
                for hid in hit_ids
            ],
        },
    }


# ---------------------------------------------------------------------------
# Selection validation
# ---------------------------------------------------------------------------


async def test_search_tournaments_requires_d_lat_lon(tmp_path: Path) -> None:
    async with UstaApiClient(raw_cache_dir=tmp_path / "raw", interval_seconds=0) as client:
        with pytest.raises(ValueError, match="d"):
            await client.search_tournaments({"lat": 1.0, "lon": 2.0})
        with pytest.raises(ValueError, match="lat"):
            await client.search_tournaments({"d": 50, "lon": 2.0})


async def test_search_tournaments_accepts_already_wrapped_payload(tmp_path: Path) -> None:
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(f"{BASE_URL}{PATH_TOURNAMENTS_QUERY}").mock(
            return_value=httpx.Response(200, json=_envelope(["a"]))
        )
        async with UstaApiClient(
            raw_cache_dir=tmp_path / "raw", interval_seconds=0
        ) as client:
            result = await client.search_tournaments(
                {"selection": {"d": 50, "lat": 27.6, "lon": -81.5}}
            )
        assert route.called
        # The body sent to the API preserved the caller's selection shape.
        body = json.loads(route.calls.last.request.content)
        assert body == {"selection": {"d": 50, "lat": 27.6, "lon": -81.5}}
        assert result["hits"]["hits"][0]["_id"] == "a"


# ---------------------------------------------------------------------------
# Cache write
# ---------------------------------------------------------------------------


async def test_search_tournaments_writes_cache_envelope(tmp_path: Path) -> None:
    with respx.mock() as mock:
        mock.post(f"{BASE_URL}{PATH_TOURNAMENTS_QUERY}").mock(
            return_value=httpx.Response(200, json=_envelope(["abc"]))
        )
        async with UstaApiClient(
            raw_cache_dir=tmp_path / "raw", interval_seconds=0
        ) as client:
            await client.search_tournaments({"d": 50, "lat": 27.6, "lon": -81.5})

    cache_root = tmp_path / "raw" / "usta_api"
    assert cache_root.exists()
    digests = [p for p in cache_root.rglob("*.json")]
    assert len(digests) == 1
    envelope = json.loads(digests[0].read_text())
    assert envelope["source"] == "usta_api"
    assert envelope["request"]["method"] == "POST"
    assert envelope["response"]["status"] == 200
    assert envelope["response"]["body"]["hits"]["hits"][0]["_id"] == "abc"


def test_compute_usta_api_cache_key_is_stable() -> None:
    url = f"{BASE_URL}{PATH_TOURNAMENTS_QUERY}"
    payload = {"selection": {"d": 50, "lat": 27.6, "lon": -81.5}}
    a = compute_usta_api_cache_key(url, payload)
    b = compute_usta_api_cache_key(url, {"selection": {"lon": -81.5, "lat": 27.6, "d": 50}})
    assert a == b
    # SHA-256 hex digest length.
    assert len(a) == 64


# ---------------------------------------------------------------------------
# 403 → BlockedEgressError
# ---------------------------------------------------------------------------


async def test_403_raises_blocked_egress(tmp_path: Path) -> None:
    with respx.mock() as mock:
        mock.post(f"{BASE_URL}{PATH_TOURNAMENTS_QUERY}").mock(
            return_value=httpx.Response(403, json={"message": "Forbidden"})
        )
        async with UstaApiClient(
            raw_cache_dir=tmp_path / "raw", interval_seconds=0
        ) as client:
            with pytest.raises(BlockedEgressError):
                await client.search_tournaments({"d": 50, "lat": 0, "lon": 0})


# ---------------------------------------------------------------------------
# 5xx retry (via tenacity)
# ---------------------------------------------------------------------------


async def test_5xx_retries_then_succeeds(tmp_path: Path) -> None:
    with respx.mock() as mock:
        route = mock.post(f"{BASE_URL}{PATH_TOURNAMENTS_QUERY}").mock(
            side_effect=[
                httpx.Response(503, text="oops"),
                httpx.Response(200, json=_envelope(["x"])),
            ]
        )
        async with UstaApiClient(
            raw_cache_dir=tmp_path / "raw", interval_seconds=0
        ) as client:
            result = await client.search_tournaments({"d": 50, "lat": 0, "lon": 0})
    assert route.call_count == 2
    assert result["hits"]["hits"][0]["_id"] == "x"


async def test_5xx_retries_exhausted_raises_transient(tmp_path: Path) -> None:
    with respx.mock() as mock:
        mock.post(f"{BASE_URL}{PATH_TOURNAMENTS_QUERY}").mock(
            return_value=httpx.Response(502, text="bad gateway")
        )
        async with UstaApiClient(
            raw_cache_dir=tmp_path / "raw", interval_seconds=0
        ) as client:
            with pytest.raises(TransientNetworkError):
                await client.search_tournaments({"d": 50, "lat": 0, "lon": 0})


# ---------------------------------------------------------------------------
# get_tournament short-circuits for non-GUID
# ---------------------------------------------------------------------------


async def test_get_tournament_non_guid_short_circuits(tmp_path: Path) -> None:
    """Numeric (TennisLink) ids never reach the API; client raises
    NotImplementedError immediately so the router falls through."""
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(f"{BASE_URL}{PATH_TOURNAMENTS_QUERY}").mock(
            return_value=httpx.Response(200, json=_envelope(["x"]))
        )
        async with UstaApiClient(
            raw_cache_dir=tmp_path / "raw", interval_seconds=0
        ) as client:
            with pytest.raises(NotImplementedError):
                await client.get_tournament("12345678")
        assert not route.called


async def test_get_tournament_guid_queries_and_returns_envelope(tmp_path: Path) -> None:
    guid = "CB005855-CDEF-4A4A-8885-4D3A52C9B413"
    with respx.mock() as mock:
        mock.post(f"{BASE_URL}{PATH_TOURNAMENTS_QUERY}").mock(
            return_value=httpx.Response(200, json=_envelope([guid]))
        )
        async with UstaApiClient(
            raw_cache_dir=tmp_path / "raw", interval_seconds=0
        ) as client:
            envelope = await client.get_tournament(guid)
    assert envelope["hits"]["hits"][0]["_id"] == guid


async def test_get_tournament_guid_not_found_falls_through(tmp_path: Path) -> None:
    guid = "CB005855-CDEF-4A4A-8885-4D3A52C9B413"
    with respx.mock() as mock:
        mock.post(f"{BASE_URL}{PATH_TOURNAMENTS_QUERY}").mock(
            return_value=httpx.Response(200, json=_envelope([]))
        )
        async with UstaApiClient(
            raw_cache_dir=tmp_path / "raw", interval_seconds=0
        ) as client:
            with pytest.raises(NotImplementedError, match="not in commingled"):
                await client.get_tournament(guid)


# ---------------------------------------------------------------------------
# Player / draw → NotImplementedError
# ---------------------------------------------------------------------------


async def test_get_player_raises_not_implemented(tmp_path: Path) -> None:
    async with UstaApiClient(raw_cache_dir=tmp_path / "raw", interval_seconds=0) as client:
        with pytest.raises(NotImplementedError):
            await client.get_player("anything")


async def test_get_draw_raises_not_implemented(tmp_path: Path) -> None:
    async with UstaApiClient(raw_cache_dir=tmp_path / "raw", interval_seconds=0) as client:
        with pytest.raises(NotImplementedError):
            await client.get_draw("anything")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


async def test_paginated_walks_until_short_page(tmp_path: Path) -> None:
    """The walker stops when the API returns fewer than `size` hits."""
    page1 = _envelope([f"p1-{i}" for i in range(50)], total=80)
    page2 = _envelope([f"p2-{i}" for i in range(30)], total=80)
    with respx.mock() as mock:
        mock.post(f"{BASE_URL}{PATH_TOURNAMENTS_QUERY}").mock(
            side_effect=[
                httpx.Response(200, json=page1),
                httpx.Response(200, json=page2),
            ]
        )
        async with UstaApiClient(
            raw_cache_dir=tmp_path / "raw", interval_seconds=0
        ) as client:
            hits = await client.search_tournaments_paginated(
                {"d": 50, "lat": 0, "lon": 0}, page_size=50
            )
    assert len(hits) == 80


async def test_paginated_de_duplicates_when_server_repeats(tmp_path: Path) -> None:
    """If the server returns the same id on a subsequent page (off-by-one
    pagination), the walker stops rather than emitting duplicates."""
    page1 = _envelope(["a", "b"], total=10)
    page2 = _envelope(["a", "b"], total=10)  # same ids: server didn't paginate
    with respx.mock() as mock:
        mock.post(f"{BASE_URL}{PATH_TOURNAMENTS_QUERY}").mock(
            side_effect=[
                httpx.Response(200, json=page1),
                httpx.Response(200, json=page2),
            ]
        )
        async with UstaApiClient(
            raw_cache_dir=tmp_path / "raw", interval_seconds=0
        ) as client:
            hits = await client.search_tournaments_paginated(
                {"d": 50, "lat": 0, "lon": 0}, page_size=2, max_pages=5
            )
    # Walker stops on first repeated id; we got page1 in full only.
    assert [h["_id"] for h in hits] == ["a", "b"]
