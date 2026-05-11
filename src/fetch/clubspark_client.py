"""Clubspark client — DEFERRED stub.

This is the Strategy-C Clubspark client placeholder. The real implementation
will drive a long-lived Playwright :class:`BrowserContext` (see
``src.auth.session.UstaSession``) and route every data fetch through
``context.request.post(...)`` / ``page.goto(...)`` so each request inherits
the browser's TLS handshake, cookies, and warmed session.

Why it's a stub today: ``playtennis.usta.com`` and every other
Cloudflare-fronted Clubspark host (``prod-us-kube.clubspark.io``,
``prd-itf-kube.clubspark.pro``, ``worldtennisnumber.com``) returns HTTP 403
from this environment's egress IP — the block is at IP/ASN layer, not TLS
fingerprint or browser realism (live recon 2026-05-10 confirms a real
Chromium 141 with stripped automation tells reproduces the same 403 as
anonymous curl). See ADR-001 and ADR-005, and Q-011 in QUESTIONS.md.

When residential egress is available (the user re-runs
``scripts/live_recon.py`` from their own laptop or a tunnel) this stub is
fleshed out into the actual Playwright-resident client. The router
(``src.fetch.router.FetchRouter``) already knows to dispatch GUID-shaped
ids here and falls through cleanly when this stub raises.

Interface mirrors :class:`src.fetch.tennislink_client.TennisLinkClient`:
each method takes an id, returns the raw response body (HTML for HTML
endpoints, ``dict`` for GraphQL), and lets the parsers do the rest.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.auth.session import UstaSession


_DEFERRED_MSG = (
    "Clubspark client is deferred — see ADR-001 and ADR-005, gated on "
    "residential egress (QUESTIONS.md Q-011). Use the TennisLink source "
    "via FetchRouter today."
)


class ClubsparkClient:
    """Stub Clubspark client.

    Every public method raises :class:`NotImplementedError` with a pointer to
    the deferring ADR and the gating question. The shape exists so that the
    router can typecheck dispatch and so that the day-1 wiring is a one-file
    swap when residential egress arrives.
    """

    def __init__(self, session: UstaSession | None = None) -> None:
        # Held but unused while deferred — keeps the constructor signature
        # stable across the deferred-vs-implemented transition.
        self._session = session

    async def search_tournaments(self, filters: dict[str, Any]) -> str:
        """Search tournaments. Returns raw HTML/JSON body once implemented."""
        raise NotImplementedError(_DEFERRED_MSG)

    async def get_tournament(self, usta_id: str) -> str:
        """Fetch a tournament detail page by id."""
        raise NotImplementedError(_DEFERRED_MSG)

    async def get_draw(self, draw_id: str) -> str:
        """Fetch a single draw by id."""
        raise NotImplementedError(_DEFERRED_MSG)

    async def get_player(self, player_id: str) -> str:
        """Fetch a player profile page by id."""
        raise NotImplementedError(_DEFERRED_MSG)

    async def fetch_rankings(
        self,
        age: int,
        gender: str,
        scope: str,
        section: str | None = None,
    ) -> str:
        """Fetch a Clubspark ranking list (raw HTML/JSON body).

        Pending residential-proxy wiring. The shape exists so the
        Rankings-First CLI command can dispatch through this method and the
        moment proxy credentials arrive, the implementation drops in here
        without changing any caller.

        TODO: when the orchestrator provides residential-proxy credentials,
        wire this to:
            1. instantiate :class:`src.fetch.residential_proxy.ResidentialProxyBackend`
               via :func:`get_residential_proxy`,
            2. POST a GraphQL query (``rankings(...)``-shaped — confirm the
               exact field name once we can call the live endpoint) at
               ``https://prod-us-kube.clubspark.io/usta/tournaments/api/graphql``,
            3. return the response body as text.
        See ADR-001 and ``data/reference/known_urls.md``.
        """
        raise NotImplementedError(
            "Pending residential-proxy wiring — see TODO.md "
            "(Rankings-First wave). When credentials arrive, "
            "wire to src.fetch.residential_proxy.get_residential_proxy()."
        )

    async def close(self) -> None:
        """No-op while deferred; drains the (future) browser context later."""
        return None
