"""Player profile parser.

Inputs: cached raw responses from the player-profile endpoint(s) discovered
during recon. Outputs: `src.models.player.Player` instances plus optional
`WTNSnapshot` / `RankingSnapshot` records when the response embeds them.
"""

from __future__ import annotations


class ParseError(RuntimeError):
    """Generic parse failure."""


class SchemaDriftError(ParseError):
    """Raised when the response shape diverges from the last-known schema.

    The schema-drift canary (see TESTING.md) fires this when a field expected
    by the parser is missing or a new top-level field appears. Callers should
    log the drift, dump the offending raw response for inspection, and fail
    loudly rather than silently produce partial data.
    """


def parse_player(_raw: object) -> object:
    raise NotImplementedError("Pending recon and ADR-001.")
