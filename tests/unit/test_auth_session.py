"""Unit tests for src.auth.session.UstaSession.

Live login is skipped — these tests poke at the session object with the
Playwright context replaced by a fake. Anything that requires a real browser
is marked ``@pytest.mark.skip`` so it can be run on demand.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.auth.session import (
    AuthExpiredError,
    BotChallengeError,
    LoginConfigError,
    UstaSession,
    load_storage_state_file,
)

# ---------------------------------------------------------------------------
# LoginConfigError when no credentials are available anywhere
# ---------------------------------------------------------------------------


async def test_login_raises_config_error_without_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Force config to look empty.
    from src import auth as auth_pkg  # noqa: F401  - import to ensure module loaded
    from src.config import settings

    monkeypatch.setattr(settings, "usta_username", "")
    monkeypatch.setattr(settings, "usta_password", "")

    storage_path = tmp_path / "missing.json"
    session = UstaSession(storage_state_path=storage_path)

    # Stub _ensure_browser so we don't try to launch Chromium in this test.
    async def noop_ensure() -> None:
        return None

    session._ensure_browser = noop_ensure  # type: ignore[method-assign]
    # is_authenticated() returns False because there's no context.
    with pytest.raises(LoginConfigError):
        await session.login()


# ---------------------------------------------------------------------------
# cookies() returns a list shape (with a fake context)
# ---------------------------------------------------------------------------


async def test_cookies_returns_list_shape() -> None:
    session = UstaSession(username="u", password="p")
    fake_context = AsyncMock()
    fake_context.cookies.return_value = [
        {"name": "ASP.NET_SessionId", "value": "x", "domain": "usta.com", "path": "/"},
        {"name": "other", "value": "y", "domain": "usta.com", "path": "/"},
    ]
    session._context = fake_context

    cookies = await session.cookies()
    assert isinstance(cookies, list)
    assert all(isinstance(c, dict) for c in cookies)
    assert {c["name"] for c in cookies} == {"ASP.NET_SessionId", "other"}


async def test_cookies_raises_when_not_started() -> None:
    session = UstaSession(username="u", password="p")
    with pytest.raises(RuntimeError):
        await session.cookies()


# ---------------------------------------------------------------------------
# is_authenticated heuristics
# ---------------------------------------------------------------------------


async def test_is_authenticated_true_when_session_cookie_present() -> None:
    session = UstaSession(username="u", password="p")
    fake_context = AsyncMock()
    fake_context.cookies.return_value = [
        {"name": "ASP.NET_SessionId", "value": "x", "domain": "usta.com", "path": "/"}
    ]
    session._context = fake_context
    assert await session.is_authenticated() is True


async def test_is_authenticated_false_when_no_relevant_cookie() -> None:
    session = UstaSession(username="u", password="p")
    fake_context = AsyncMock()
    fake_context.cookies.return_value = [
        {"name": "junk", "value": "y", "domain": "usta.com", "path": "/"}
    ]
    session._context = fake_context
    assert await session.is_authenticated() is False


async def test_is_authenticated_false_when_no_context() -> None:
    session = UstaSession(username="u", password="p")
    assert await session.is_authenticated() is False


# ---------------------------------------------------------------------------
# Storage-state save/load round-trip
# ---------------------------------------------------------------------------


async def test_storage_state_save_load_round_trip(tmp_path: Path) -> None:
    sample_state: dict[str, Any] = {
        "cookies": [
            {
                "name": "ASP.NET_SessionId",
                "value": "abc",
                "domain": "usta.com",
                "path": "/",
                "expires": -1,
                "httpOnly": True,
                "secure": True,
                "sameSite": "Lax",
            }
        ],
        "origins": [],
    }

    state_path = tmp_path / "storage_state.json"

    async def fake_storage_state(path: str | None = None) -> dict[str, Any]:
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with Path(path).open("w", encoding="utf-8") as fh:
                json.dump(sample_state, fh)
            return sample_state
        return sample_state

    fake_context = AsyncMock()
    fake_context.storage_state.side_effect = fake_storage_state

    session = UstaSession(username="u", password="p", storage_state_path=state_path)
    session._context = fake_context

    await session.save_state(state_path)
    assert state_path.exists()

    reloaded = load_storage_state_file(state_path)
    assert reloaded == sample_state


# ---------------------------------------------------------------------------
# Fresh storage state detection respects max age
# ---------------------------------------------------------------------------


def test_fresh_storage_state_detection(tmp_path: Path) -> None:
    state_path = tmp_path / "storage.json"
    state_path.write_text("{}", encoding="utf-8")
    # Fresh by default
    session = UstaSession(
        username="u", password="p", storage_state_path=state_path, max_age_seconds=3600
    )
    assert session._fresh_storage_state_exists() is True

    # Make it ancient by rewinding the mtime by two hours.
    import os
    import time

    old = time.time() - 7200
    os.utime(state_path, (old, old))
    assert session._fresh_storage_state_exists() is False


# ---------------------------------------------------------------------------
# Names of the public exception classes are stable (downstream code imports them)
# ---------------------------------------------------------------------------


def test_exception_classes_exist() -> None:
    assert issubclass(AuthExpiredError, RuntimeError)
    assert issubclass(BotChallengeError, RuntimeError)
    assert issubclass(LoginConfigError, RuntimeError)


# ---------------------------------------------------------------------------
# Live login — skipped, runs manually
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="requires playwright browser; run manually")
async def test_real_login_smoke() -> None:  # pragma: no cover - manual only
    async with UstaSession(headless=True) as session:
        await session.login()
        assert await session.is_authenticated()
