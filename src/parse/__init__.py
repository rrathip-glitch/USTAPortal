"""Parsers — HTML/JSON to Pydantic models.

Per-source modules live alongside generic ones:

- :mod:`src.parse.players` exposes the project-wide :class:`ParseError`.
- :mod:`src.parse.matches` carries the score parser used by every source.
- :mod:`src.parse.tennislink_tournaments`,
  :mod:`src.parse.tennislink_draws`,
  :mod:`src.parse.tennislink_players`, and
  :mod:`src.parse.tennislink_rankings` parse the legacy TennisLink HTML
  surface (per ADR-001 / ADR-005). They are the primary parsers used by
  the sync orchestrator today.

The Clubspark GraphQL parsers will land here once residential-egress
recon (Q-011) closes.
"""

from __future__ import annotations

from src.parse.players import ParseError, SchemaDriftError
from src.parse.tennislink_draws import parse_draw as parse_tennislink_draw
from src.parse.tennislink_players import (
    parse_player_profile as parse_tennislink_player_profile,
)
from src.parse.tennislink_players import (
    parse_player_search_results as parse_tennislink_player_search_results,
)
from src.parse.tennislink_rankings import (
    parse_ranking_list as parse_tennislink_ranking_list,
)
from src.parse.tennislink_tournaments import (
    parse_tournament_detail as parse_tennislink_tournament_detail,
)
from src.parse.tennislink_tournaments import (
    parse_tournament_search_results as parse_tennislink_tournament_search_results,
)

__all__ = [
    "ParseError",
    "SchemaDriftError",
    "parse_tennislink_draw",
    "parse_tennislink_player_profile",
    "parse_tennislink_player_search_results",
    "parse_tennislink_ranking_list",
    "parse_tennislink_tournament_detail",
    "parse_tennislink_tournament_search_results",
]
