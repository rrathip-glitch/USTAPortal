"""Unit tests for :mod:`src.fetch.router`."""

from __future__ import annotations

import logging
import sys
import types
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.fetch.router import (
    DEFAULT_SOURCE_PREFERENCE,
    BlockedEgressError,
    FetchRouter,
    configured_source_preference,
    looks_like_guid,
    looks_like_tennislink_id,
)

# ---------------------------------------------------------------------------
# id-shape heuristics
# ---------------------------------------------------------------------------


def test_looks_like_guid_matches_clubspark_shape() -> None:
    assert looks_like_guid("CB005855-CDEF-4A4A-8885-4D3A52C9B413")
    assert looks_like_guid("cb005855-cdef-4a4a-8885-4d3a52c9b413")
    assert not looks_like_guid("12345678")
    assert not looks_like_guid("not-a-guid")
    assert not looks_like_guid("CB005855CDEF4A4A88854D3A52C9B413")  # no dashes


def test_looks_like_tennislink_id_matches_numeric() -> None:
    assert looks_like_tennislink_id("12345678")
    assert looks_like_tennislink_id("1234")
    assert not looks_like_tennislink_id("123")  # too short
    assert not looks_like_tennislink_id("abc12345")
    assert not looks_like_tennislink_id("CB005855-CDEF-4A4A-8885-4D3A52C9B413")


# ---------------------------------------------------------------------------
# Fake source clients
# ---------------------------------------------------------------------------


class FakeClient:
    """Configurable fake matching the source-client protocol."""

    def __init__(
        self,
        *,
        name: str,
        get_tournament_returns: Any = None,
        get_tournament_raises: Exception | None = None,
        get_player_returns: Any = None,
        get_player_raises: Exception | None = None,
        get_draw_returns: Any = None,
        get_draw_raises: Exception | None = None,
        search_returns: Any = None,
        search_raises: Exception | None = None,
    ) -> None:
        self.name = name
        self.get_tournament = AsyncMock(
            return_value=get_tournament_returns,
            side_effect=get_tournament_raises,
        )
        self.get_player = AsyncMock(
            return_value=get_player_returns,
            side_effect=get_player_raises,
        )
        self.get_draw = AsyncMock(
            return_value=get_draw_returns,
            side_effect=get_draw_raises,
        )
        self.search_tournaments = AsyncMock(
            return_value=search_returns,
            side_effect=search_raises,
        )
        self.close = AsyncMock()


# ---------------------------------------------------------------------------
# Dispatch: numeric id -> TennisLink first
# ---------------------------------------------------------------------------


async def test_dispatch_numeric_id_picks_tennislink() -> None:
    tl = FakeClient(name="tl", get_tournament_returns="<html>tournament</html>")
    cs = FakeClient(name="cs", get_tournament_returns="should not be called")
    api = FakeClient(
        name="api",
        get_tournament_raises=NotImplementedError("numeric id"),
    )
    router = FetchRouter(tennislink=tl, clubspark=cs, usta_api=api)

    result = await router.get_tournament("12345678")
    assert result == "<html>tournament</html>"
    tl.get_tournament.assert_awaited_once_with("12345678")
    cs.get_tournament.assert_not_awaited()


async def test_dispatch_player_id_routes_via_router() -> None:
    tl = FakeClient(name="tl", get_player_returns="player-html")
    cs = FakeClient(name="cs")
    api = FakeClient(
        name="api",
        get_player_raises=NotImplementedError("auth-only"),
    )
    router = FetchRouter(tennislink=tl, clubspark=cs, usta_api=api)

    result = await router.get_player("87654321")
    assert result == "player-html"
    tl.get_player.assert_awaited_once_with("87654321")


# ---------------------------------------------------------------------------
# Dispatch: GUID id -> Clubspark first
# ---------------------------------------------------------------------------


async def test_dispatch_guid_picks_clubspark_first_and_falls_through(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """For a GUID id, GUID-aware sources (``usta_api`` first, then
    ``clubspark``) are tried before TennisLink. When both fall through
    on NotImplementedError, TennisLink answers and the router logs a
    clean fallthrough line.
    """
    guid = "CB005855-CDEF-4A4A-8885-4D3A52C9B413"
    api = FakeClient(
        name="api",
        get_tournament_raises=NotImplementedError("Not in commingled index"),
    )
    cs = FakeClient(
        name="cs",
        get_tournament_raises=NotImplementedError("Deferred — see ADR-005"),
    )
    tl = FakeClient(name="tl", get_tournament_returns="tennislink html")
    router = FetchRouter(tennislink=tl, clubspark=cs, usta_api=api)

    with caplog.at_level(logging.INFO, logger="src.fetch.router"):
        result = await router.get_tournament(guid)

    assert result == "tennislink html"
    api.get_tournament.assert_awaited_once_with(guid)
    cs.get_tournament.assert_awaited_once_with(guid)
    tl.get_tournament.assert_awaited_once_with(guid)
    # We logged something explaining the fallthrough.
    assert any("not yet implemented" in r.message for r in caplog.records)


async def test_dispatch_guid_clubspark_only_raises_not_implemented() -> None:
    """If Clubspark is the only source and it's stubbed, the error propagates."""
    guid = "CB005855-CDEF-4A4A-8885-4D3A52C9B413"
    cs = FakeClient(
        name="cs",
        get_draw_raises=NotImplementedError("Deferred"),
    )
    router = FetchRouter(
        tennislink=None,
        clubspark=cs,
        source_preference=("clubspark",),
    )

    with pytest.raises(NotImplementedError):
        await router.get_draw(guid)


# ---------------------------------------------------------------------------
# Fallthrough on BlockedEgressError
# ---------------------------------------------------------------------------


async def test_fallthrough_on_blocked_egress(caplog: pytest.LogCaptureFixture) -> None:
    """If the primary source raises BlockedEgressError, the router tries the next."""
    tl = FakeClient(
        name="tl",
        get_tournament_raises=BlockedEgressError("Cloudflare 403"),
    )
    cs = FakeClient(name="cs", get_tournament_returns="from clubspark")
    api = FakeClient(
        name="api",
        get_tournament_raises=NotImplementedError("numeric id"),
    )
    router = FetchRouter(
        tennislink=tl,
        clubspark=cs,
        usta_api=api,
        source_preference=("tennislink", "clubspark"),
    )

    with caplog.at_level(logging.WARNING, logger="src.fetch.router"):
        result = await router.get_tournament("12345678")

    assert result == "from clubspark"
    tl.get_tournament.assert_awaited_once_with("12345678")
    cs.get_tournament.assert_awaited_once_with("12345678")
    assert any("blocked at egress" in r.message for r in caplog.records)


async def test_blocked_egress_exhausted_raises() -> None:
    """All sources blocked → the last BlockedEgressError surfaces."""
    tl = FakeClient(name="tl", get_tournament_raises=BlockedEgressError("a"))
    cs = FakeClient(name="cs", get_tournament_raises=BlockedEgressError("b"))
    api = FakeClient(name="api", get_tournament_raises=BlockedEgressError("c"))
    router = FetchRouter(tennislink=tl, clubspark=cs, usta_api=api)

    with pytest.raises(BlockedEgressError):
        await router.get_tournament("12345678")


# ---------------------------------------------------------------------------
# Source preference & configuration
# ---------------------------------------------------------------------------


def test_default_source_preference_puts_usta_api_first() -> None:
    """Since 2026-05-11 the anonymous USTA Play Tennis API leads the
    preference list (live, current, reachable). TennisLink is second
    (historical archive). Clubspark stays last (auth-required, deferred).
    """
    assert DEFAULT_SOURCE_PREFERENCE[0] == "usta_api"
    assert "tennislink" in DEFAULT_SOURCE_PREFERENCE
    assert "clubspark" in DEFAULT_SOURCE_PREFERENCE


def test_unknown_source_preference_raises() -> None:
    with pytest.raises(ValueError):
        FetchRouter(source_preference=("not-a-source",))


def test_configured_source_preference_defaults() -> None:
    assert configured_source_preference() == DEFAULT_SOURCE_PREFERENCE


def test_configured_source_preference_reads_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from src import config

    monkeypatch.setattr(config.settings, "usta_source_preference", "clubspark,tennislink", raising=False)
    assert configured_source_preference() == ("clubspark", "tennislink")


# ---------------------------------------------------------------------------
# Lazy import of TennisLinkClient
# ---------------------------------------------------------------------------


async def test_router_skips_tennislink_when_module_missing(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the TennisLink module hasn't landed, the router logs and skips."""
    # Hide any existing src.fetch.tennislink_client module.
    monkeypatch.setitem(sys.modules, "src.fetch.tennislink_client", None)

    api = FakeClient(
        name="api",
        get_tournament_raises=NotImplementedError("numeric id"),
    )
    router = FetchRouter(
        tennislink=None,
        clubspark=FakeClient(name="cs", get_tournament_returns="cs!"),
        usta_api=api,
    )

    with caplog.at_level(logging.WARNING, logger="src.fetch.router"):
        result = await router.get_tournament("12345678")

    assert result == "cs!"
    assert any(
        "TennisLink client not importable" in r.message for r in caplog.records
    )


async def test_router_uses_tennislink_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the TennisLink module is importable, the router instantiates it."""
    fake_module = types.ModuleType("src.fetch.tennislink_client")

    class _FakeTL:
        def __init__(self) -> None:
            pass

        async def search_tournaments(self, filters: dict[str, Any]) -> str:
            return "search"

        async def get_tournament(self, usta_id: str) -> str:
            return f"tournament:{usta_id}"

        async def get_draw(self, draw_id: str) -> str:
            return f"draw:{draw_id}"

        async def get_player(self, player_id: str) -> str:
            return f"player:{player_id}"

        async def close(self) -> None:
            return None

    fake_module.TennisLinkClient = _FakeTL  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "src.fetch.tennislink_client", fake_module)

    # For a numeric id, the USTA API fall-through is automatic (the client
    # raises NotImplementedError before any request); the router moves on
    # to TennisLink. We construct a router that exposes the lazy-import
    # path and lets the real UstaApiClient short-circuit.
    router = FetchRouter()
    result = await router.get_tournament("12345678")
    assert result == "tournament:12345678"


# ---------------------------------------------------------------------------
# close() drains underlying clients
# ---------------------------------------------------------------------------


async def test_close_calls_underlying_clients() -> None:
    tl = FakeClient(name="tl")
    cs = FakeClient(name="cs")
    api = FakeClient(name="api")
    router = FetchRouter(tennislink=tl, clubspark=cs, usta_api=api)
    await router.close()
    tl.close.assert_awaited_once()
    cs.close.assert_awaited_once()
    api.close.assert_awaited_once()
