"""USTA authentication session.

Drives Playwright Chromium for the login dance, then exposes the resulting
cookies / storage state for httpx to use for bulk fetches. This is the
"Strategy A" / "Strategy C" shape from ADR-001 (still pending recon): a real
browser owns the auth handshake, and a thin httpx layer makes the actual data
calls through the warmed cookie jar.

Many concrete bits — the exact login URL, the form selectors, the success
indicator, the session cookie name — depend on findings the recon subagent
captures into RECON.md. Anything that needs to be confirmed against the live
site is marked ``# TODO(recon):`` so it's grep-able post-recon.

Public interface:

    async with UstaSession() as session:
        await session.login()
        cookies = await session.cookies()
        ...
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from src.config import settings

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright


class AuthExpiredError(RuntimeError):
    """Raised when the USTA session has expired and re-login is required."""


class BotChallengeError(RuntimeError):
    """Raised when the USTA site presents a captcha or bot-mitigation page."""


class LoginConfigError(RuntimeError):
    """Raised when no credentials are available to perform a login."""


# TODO(recon): replace defaults once recon has pinned these.
DEFAULT_LOGIN_URL = "https://playtennis.usta.com/"
DEFAULT_USERNAME_SELECTOR = "input[name='username'], input[type='email']"
DEFAULT_PASSWORD_SELECTOR = "input[name='password'], input[type='password']"
DEFAULT_SUBMIT_SELECTOR = "button[type='submit']"
DEFAULT_SUCCESS_INDICATOR = "text=Sign Out"
DEFAULT_SESSION_COOKIE_NAME = "ASP.NET_SessionId"  # TODO(recon): confirm

# Patterns that suggest we hit a captcha or bot wall instead of the real site.
BOT_CHALLENGE_PATTERNS: tuple[str, ...] = (
    "captcha",
    "verify you are human",
    "challenge",
    "are you a robot",
    "cf-challenge",
)

DEFAULT_STORAGE_STATE_PATH = Path("data/state/storage_state.json")
DEFAULT_MAX_AGE_SECONDS = 12 * 60 * 60  # 12 hours


class UstaSession:
    """A Playwright-driven USTA login session.

    Use as an async context manager so the underlying browser is always
    cleaned up even on errors.
    """

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        headless: bool = True,
        storage_state_path: Path | None = None,
        max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    ) -> None:
        self._username = username if username is not None else settings.usta_username
        self._password = password if password is not None else settings.usta_password
        self._headless = headless
        self._storage_state_path = storage_state_path or DEFAULT_STORAGE_STATE_PATH
        self._max_age_seconds = max_age_seconds

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    # -- async context management --------------------------------------------------

    async def __aenter__(self) -> UstaSession:
        await self._ensure_browser()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    # -- public API ----------------------------------------------------------------

    async def login(self) -> None:
        """Log in. Idempotent: if a fresh storage state exists on disk, use it.

        Raises:
            LoginConfigError: when no credentials are configured.
            BotChallengeError: when the site shows a captcha / bot wall.
            AuthExpiredError: when the credentials are rejected.
        """

        if self._fresh_storage_state_exists():
            await self._load_storage_state()
            if await self.is_authenticated():
                return

        if not self._username or not self._password:
            raise LoginConfigError(
                "No USTA credentials provided. Set USTA_USERNAME and USTA_PASSWORD "
                "in the environment, or pass username= and password= explicitly."
            )

        await self._ensure_browser()
        assert self._context is not None
        page = await self._context.new_page()
        try:
            await self._perform_login(page)
        finally:
            await page.close()

        # Persist fresh state for next run.
        await self.save_state(self._storage_state_path)

    async def is_authenticated(self) -> bool:
        """Cheap check: do we have a session cookie that looks valid?"""

        try:
            cookies = await self.cookies()
        except RuntimeError:
            return False
        # TODO(recon): once we know the canonical session cookie name, check it
        # specifically and validate expiry. For now: any cookie matching the
        # default name *or* a generic 'session'-flavored cookie counts.
        for cookie in cookies:
            name = cookie.get("name", "")
            if name == DEFAULT_SESSION_COOKIE_NAME:
                return True
            if "session" in name.lower() or "auth" in name.lower():
                return True
        return False

    async def cookies(self) -> list[dict[str, Any]]:
        """Return the Playwright cookie jar in dict form (suitable for httpx)."""

        if self._context is None:
            raise RuntimeError("UstaSession is not started; call __aenter__ first.")
        raw = await self._context.cookies()
        return [dict(c) for c in raw]

    async def storage_state(self) -> dict[str, Any]:
        """Return the full Playwright storage_state dict (cookies + origins)."""

        if self._context is None:
            raise RuntimeError("UstaSession is not started; call __aenter__ first.")
        state = await self._context.storage_state()
        return cast(dict[str, Any], state)

    async def save_state(self, path: Path) -> None:
        """Persist the current storage state to disk for re-use on next run."""

        if self._context is None:
            raise RuntimeError("UstaSession is not started; call __aenter__ first.")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Playwright accepts a path= directly and writes JSON.
        await self._context.storage_state(path=str(path))

    async def close(self) -> None:
        """Tear down the browser. Safe to call repeatedly."""

        if self._context is not None:
            with suppress(Exception):
                await self._context.close()
            self._context = None
        if self._browser is not None:
            with suppress(Exception):
                await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            with suppress(Exception):
                await self._playwright.stop()
            self._playwright = None

    # -- internals -----------------------------------------------------------------

    async def _ensure_browser(self) -> None:
        """Lazily start Playwright + Chromium."""

        if self._context is not None:
            return

        # Local import: keeps import-time cheap for code paths that never need
        # the browser (e.g. unit tests that mock the context out wholesale).
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)

        if self._fresh_storage_state_exists():
            self._context = await self._browser.new_context(
                storage_state=str(self._storage_state_path)
            )
        else:
            self._context = await self._browser.new_context()

    def _fresh_storage_state_exists(self) -> bool:
        path = self._storage_state_path
        if not path.exists():
            return False
        age = time.time() - path.stat().st_mtime
        return age < self._max_age_seconds

    async def _load_storage_state(self) -> None:
        """Re-create the browser context off a fresh storage_state file."""

        # If we already have a context, replace it with one bound to the file.
        if self._context is not None:
            with suppress(Exception):
                await self._context.close()
            self._context = None
        await self._ensure_browser()

    async def _perform_login(self, page: Page) -> None:
        """Drive the login form. Selectors marked TODO until recon pins them."""

        # TODO(recon): replace DEFAULT_LOGIN_URL with the actual login page (the
        # site root may redirect to an OIDC provider; recon will tell us).
        await page.goto(DEFAULT_LOGIN_URL, wait_until="domcontentloaded")

        if await self._looks_like_bot_challenge(page):
            raise BotChallengeError("Bot-challenge page presented during login navigation.")

        # TODO(recon): pin the actual selectors. The defaults here are best-guess
        # fallbacks that work on most form-post login pages.
        try:
            await page.fill(DEFAULT_USERNAME_SELECTOR, self._username, timeout=10_000)
            await page.fill(DEFAULT_PASSWORD_SELECTOR, self._password, timeout=10_000)
            await page.click(DEFAULT_SUBMIT_SELECTOR, timeout=10_000)
        except Exception as exc:  # pragma: no cover - selector-dependent
            raise AuthExpiredError(f"Login form interaction failed: {exc}") from exc

        # Wait for navigation to settle.
        with suppress(Exception):
            await page.wait_for_load_state("networkidle", timeout=15_000)

        if await self._looks_like_bot_challenge(page):
            raise BotChallengeError("Bot-challenge page presented after login submit.")

        # TODO(recon): swap DEFAULT_SUCCESS_INDICATOR for whatever post-login
        # element actually appears (a profile menu, a "Sign Out" link, ...).
        if not await self.is_authenticated():
            raise AuthExpiredError("Login submitted but no session cookie was set.")

    async def _looks_like_bot_challenge(self, page: Page) -> bool:
        try:
            content = (await page.content()).lower()
        except Exception:  # pragma: no cover - defensive
            return False
        return any(pat in content for pat in BOT_CHALLENGE_PATTERNS)


# -- helpers exposed for tests ----------------------------------------------------


def load_storage_state_file(path: Path) -> dict[str, Any]:
    """Helper to read a storage_state.json from disk. Used by tests."""

    with path.open("r", encoding="utf-8") as fh:
        return cast(dict[str, Any], json.load(fh))


async def _yield() -> None:  # pragma: no cover - trivial
    """Yield control back to the event loop. Useful in tests that mock sleep."""
    await asyncio.sleep(0)
