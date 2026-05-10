"""Unit tests for :class:`src.fetch.tennislink_client.TennisLinkClient`.

Network is mocked via ``respx``; tests never hit ``tennislink.usta.com``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from src.fetch.client import BotChallengeError, TransientNetworkError
from src.fetch.router import BlockedEgressError
from src.fetch.tennislink_client import (
    BASE_URL,
    PATH_RANKING_PRINT,
    PATH_SEARCH_RESULTS,
    PATH_TOURNAMENT_DETAIL,
    TennisLinkClient,
    compute_tennislink_cache_key,
)


@pytest.fixture
def fast_client(tmp_path: Path) -> Iterator[TennisLinkClient]:
    """A TennisLinkClient with no rate limit and tmp_path cache dir."""
    client = TennisLinkClient(
        raw_cache_dir=tmp_path,
        interval_seconds=0.0,
    )
    yield client
    # Cleanup the underlying httpx client synchronously is harmless because
    # nothing was actually opened in tests that did not call into the
    # transport layer; we leave async close to per-test teardown when used.


# ---------------------------------------------------------------------------
# get_tournament — happy path + cache write
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_tournament_caches_response(tmp_path: Path) -> None:
    body_html = "<html><body><h1>Tournament</h1></body></html>"
    route = respx.get(f"{BASE_URL}{PATH_TOURNAMENT_DETAIL}", params={"T": "211365"}).mock(
        return_value=httpx.Response(200, text=body_html, headers={"Content-Type": "text/html"})
    )

    async with TennisLinkClient(
        raw_cache_dir=tmp_path, interval_seconds=0.0
    ) as client:
        out = await client.get_tournament("211365")

    assert route.called
    assert out == body_html

    # The cache directory is laid out as raw_cache_dir/tennislink/<2hex>/<hash>.json.
    digest = compute_tennislink_cache_key(
        f"{BASE_URL}{PATH_TOURNAMENT_DETAIL}", {"T": "211365"}
    )
    cache_path = tmp_path / "tennislink" / digest[:2] / f"{digest}.json"
    assert cache_path.exists(), f"expected cache file at {cache_path}"
    envelope: dict[str, Any] = json.loads(cache_path.read_text())
    assert envelope["response"]["status"] == 200
    assert envelope["response"]["body"] == body_html
    assert envelope["request"]["url"].startswith(BASE_URL)


# ---------------------------------------------------------------------------
# 403 -> BlockedEgressError (router fallthrough trigger)
# ---------------------------------------------------------------------------


@respx.mock
async def test_403_raises_blocked_egress(tmp_path: Path) -> None:
    respx.get(f"{BASE_URL}{PATH_TOURNAMENT_DETAIL}").mock(
        return_value=httpx.Response(403, text="forbidden")
    )

    async with TennisLinkClient(
        raw_cache_dir=tmp_path, interval_seconds=0.0
    ) as client:
        with pytest.raises(BlockedEgressError):
            await client.get_tournament("211365")


# ---------------------------------------------------------------------------
# 503 -> retry, then success
# ---------------------------------------------------------------------------


@respx.mock
async def test_retries_on_503_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # tenacity's default wait is exponential — patch asyncio.sleep so the
    # test doesn't wait the real backoff seconds.
    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _no_sleep)

    body_html = "<html><body>OK</body></html>"
    route = respx.get(f"{BASE_URL}{PATH_TOURNAMENT_DETAIL}").mock(
        side_effect=[
            httpx.Response(503, text="busy"),
            httpx.Response(503, text="busy"),
            httpx.Response(200, text=body_html, headers={"Content-Type": "text/html"}),
        ]
    )

    async with TennisLinkClient(
        raw_cache_dir=tmp_path, interval_seconds=0.0
    ) as client:
        out = await client.get_tournament("211365")

    # Three calls hit the route — two 503s + one 200.
    assert route.call_count == 3
    assert out == body_html


# ---------------------------------------------------------------------------
# Retries exhausted -> TransientNetworkError
# ---------------------------------------------------------------------------


@respx.mock
async def test_persistent_503_raises_transient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _no_sleep)

    respx.get(f"{BASE_URL}{PATH_TOURNAMENT_DETAIL}").mock(
        return_value=httpx.Response(503, text="busy")
    )

    async with TennisLinkClient(
        raw_cache_dir=tmp_path, interval_seconds=0.0
    ) as client:
        with pytest.raises(TransientNetworkError):
            await client.get_tournament("211365")


# ---------------------------------------------------------------------------
# Bot-wall body -> BotChallengeError
# ---------------------------------------------------------------------------


@respx.mock
async def test_bot_wall_body_raises_bot_challenge(tmp_path: Path) -> None:
    respx.get(f"{BASE_URL}{PATH_TOURNAMENT_DETAIL}").mock(
        return_value=httpx.Response(
            200,
            text=(
                "<html><body><h1>Sorry, you have been blocked</h1>"
                "Cloudflare Ray ID: abc123</body></html>"
            ),
            headers={"Content-Type": "text/html"},
        )
    )

    async with TennisLinkClient(
        raw_cache_dir=tmp_path, interval_seconds=0.0
    ) as client:
        with pytest.raises(BotChallengeError):
            await client.get_tournament("211365")


# ---------------------------------------------------------------------------
# search_tournaments and get_ranking_list both work
# ---------------------------------------------------------------------------


@respx.mock
async def test_search_tournaments_uses_results_path(tmp_path: Path) -> None:
    body = "<html><body>results</body></html>"
    route = respx.get(f"{BASE_URL}{PATH_SEARCH_RESULTS}").mock(
        return_value=httpx.Response(200, text=body, headers={"Content-Type": "text/html"})
    )

    async with TennisLinkClient(
        raw_cache_dir=tmp_path, interval_seconds=0.0
    ) as client:
        out = await client.search_tournaments({"State": "FL", "Year": "2018"})

    assert route.called
    request = route.calls[0].request
    assert request.url.params["State"] == "FL"
    assert request.url.params["Year"] == "2018"
    # Defaults applied — typeofsubmit defaults to "advanced".
    assert request.url.params["typeofsubmit"] == "advanced"
    assert out == body


@respx.mock
async def test_get_ranking_list_passes_id(tmp_path: Path) -> None:
    body = "<html>list</html>"
    route = respx.get(f"{BASE_URL}{PATH_RANKING_PRINT}").mock(
        return_value=httpx.Response(200, text=body, headers={"Content-Type": "text/html"})
    )

    async with TennisLinkClient(
        raw_cache_dir=tmp_path, interval_seconds=0.0
    ) as client:
        out = await client.get_ranking_list("2102615")

    assert route.called
    req = route.calls[0].request
    assert req.url.params["id"] == "2102615"
    assert req.url.params["e"] == "1"
    assert req.url.params["sortby"] == "rank"
    assert out == body


# ---------------------------------------------------------------------------
# Rate-limit enforced — second call sleeps
# ---------------------------------------------------------------------------


@respx.mock
async def test_rate_limit_sleeps_between_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two back-to-back calls must invoke the client's sleep helper."""
    body = "<html/>"
    respx.get(f"{BASE_URL}{PATH_TOURNAMENT_DETAIL}").mock(
        return_value=httpx.Response(200, text=body, headers={"Content-Type": "text/html"})
    )

    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    # Patch the staticmethod on the class itself so both call sites
    # observe the same fake.
    monkeypatch.setattr(
        "src.fetch.tennislink_client.TennisLinkClient._sleep",
        staticmethod(fake_sleep),
    )

    async with TennisLinkClient(
        raw_cache_dir=tmp_path, interval_seconds=2.0
    ) as client:
        await client.get_tournament("1")
        await client.get_tournament("2")

    # The second call must have slept ~2s (with a tiny jitter).
    assert any(s > 1.0 for s in sleeps), f"expected a >1s sleep on second call, got {sleeps}"


# ---------------------------------------------------------------------------
# Composite draw id parsing
# ---------------------------------------------------------------------------


@respx.mock
async def test_get_draw_with_composite_id(tmp_path: Path) -> None:
    body = "<html>draw</html>"
    route = respx.get(f"{BASE_URL}{PATH_TOURNAMENT_DETAIL}").mock(
        return_value=httpx.Response(200, text=body, headers={"Content-Type": "text/html"})
    )

    async with TennisLinkClient(
        raw_cache_dir=tmp_path, interval_seconds=0.0
    ) as client:
        await client.get_draw("T=211365:E=5")

    req = route.calls[0].request
    assert req.url.params["T"] == "211365"
    assert req.url.params["E"] == "5"
    assert req.url.params["tab"] == "Draws"


# ---------------------------------------------------------------------------
# Disallowed host is rejected
# ---------------------------------------------------------------------------


async def test_disallowed_host_raises(tmp_path: Path) -> None:
    """The host allowlist refuses anything that's not a TennisLink hostname.

    ValueError isn't wrapped by tenacity (it isn't in the retry-eligible
    set), so it surfaces directly.
    """
    async with TennisLinkClient(
        raw_cache_dir=tmp_path, interval_seconds=0.0
    ) as client:
        with pytest.raises(ValueError) as excinfo:
            await client.get("https://example.com/")
        assert "refuses to fetch host" in str(excinfo.value)
