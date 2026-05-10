"""Fetch layer.

Multi-source design (per ADR-005):

- :class:`FetchClient` (``client.py``) is the generic httpx building block:
  rate limit, retry/backoff, raw-cache writer, header redaction. It is the
  primitive used by source-specific clients.
- :class:`TennisLinkClient` (``tennislink_client.py``, owned by the
  TennisLink subagent) is the **primary** source today — ``tennislink.usta.com``
  is a legacy ASP.NET surface that is reachable from this environment.
- :class:`ClubsparkClient` (``clubspark_client.py``) is the **deferred**
  Strategy-C Clubspark path. Every method raises ``NotImplementedError``
  until residential egress (Q-011) lights up.
- :class:`FetchRouter` (``router.py``) dispatches per-entity calls to the
  best available source given the configured preference order and the
  shape of the supplied identifier.

Errors:

- :class:`BlockedEgressError` — the current source's edge (e.g. Cloudflare
  on Clubspark) refused the egress. Triggers fallthrough to the next source
  in the router's preference order.
- Other transport errors (``AuthExpiredError``, ``BotChallengeError``,
  ``RateLimitedError``, ``TransientNetworkError``) come from ``client.py``
  and are re-exported here for convenience.
"""

from __future__ import annotations

from src.fetch.client import (
    AuthExpiredError,
    BotChallengeError,
    FetchClient,
    RateLimitedError,
    TransientNetworkError,
    compute_cache_key,
    redact_headers,
)
from src.fetch.router import BlockedEgressError, FetchRouter

__all__ = [
    "AuthExpiredError",
    "BlockedEgressError",
    "BotChallengeError",
    "FetchClient",
    "FetchRouter",
    "RateLimitedError",
    "TransientNetworkError",
    "compute_cache_key",
    "redact_headers",
]
