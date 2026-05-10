"""USTA authentication session.

Placeholder. Recon must answer the following before this module is real:

- Does playtennis.usta.com use a standard form-post login, OIDC, or a federated
  identity provider?
- What cookies hold the session (names, lifetime, HttpOnly, SameSite)?
- Are CSRF tokens required on subsequent calls?
- Does the SPA mint a short-lived bearer token after login, and if so where
  does it surface (XHR header? localStorage? embedded in HTML)?
- What's the refresh strategy — silent re-auth, or re-prompt?

Once recon resolves these, this module exposes:

    class UstaSession:
        async def login(self) -> None: ...
        async def fetch(self, url: str, **kwargs) -> httpx.Response: ...
        async def is_authenticated(self) -> bool: ...
        async def close(self) -> None: ...

The implementation is expected to be a Playwright + httpx hybrid: Playwright
performs the login dance to acquire cookies, then httpx makes bulk data calls
through those cookies for speed. See SPEC.md Section 4 (Reconnaissance Phase)
and ADR-001 (Extraction Strategy, pending recon).
"""

from __future__ import annotations


class AuthExpiredError(RuntimeError):
    """Raised when the USTA session has expired and re-login is required."""


class BotChallengeError(RuntimeError):
    """Raised when the USTA site presents a captcha or bot-mitigation page."""


class UstaSession:
    """Stub. Real implementation lands after recon."""

    async def login(self) -> None:
        raise NotImplementedError("Pending recon — see src/auth/session.py docstring.")

    async def is_authenticated(self) -> bool:
        return False

    async def close(self) -> None:
        return None
