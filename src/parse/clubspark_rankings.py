"""Clubspark ranking list parser — DEFERRED stub.

Pending residential-proxy wiring (ADR-001, Q-011, Rankings-First wave).
When the orchestrator supplies credentials, the residential-proxy adapter
in :mod:`src.fetch.residential_proxy` will return a Clubspark GraphQL
response and this parser will translate it into the
:class:`src.models.ranking.RankingList` + :class:`RankingListEntry` tuple.

Shape exists today so the ``usta sync-rankings`` CLI command can dispatch
through it. Calling :func:`parse_clubspark_rankings` today raises
:class:`NotImplementedError` with a pointer to the gating work item.
"""

from __future__ import annotations

from src.models.ranking import RankingList, RankingListEntry

_DEFERRED_MSG = (
    "Clubspark rankings parser is deferred — pending residential-proxy "
    "wiring. See TODO.md and data/reference/known_urls.md."
)


def parse_clubspark_rankings(
    body: str | bytes,
) -> tuple[RankingList, list[RankingListEntry]]:
    """Parse a Clubspark ranking-list response.

    Args:
        body: Raw response body from the Clubspark GraphQL endpoint
              (``prod-us-kube.clubspark.io``). The body is expected to be
              JSON with a ``data.rankings`` envelope; the exact field
              names need to be confirmed via live recon once
              residential-proxy credentials are available.

    Returns:
        A tuple of (RankingList, list[RankingListEntry]).

    Raises:
        NotImplementedError: while the implementation is deferred.
    """
    raise NotImplementedError(_DEFERRED_MSG)


__all__ = ["parse_clubspark_rankings"]
