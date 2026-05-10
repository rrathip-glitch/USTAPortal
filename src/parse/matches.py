"""Match parser. Pending recon.

Score parsing follows Jeff Sackmann's match-charting conventions where they
apply: sets separated by spaces, set scores like "6-4" or "7-6(3)" for tiebreaks,
"RET" for retirements, "W/O" for walkovers. See RESEARCH.md for the canonical
reference.
"""

from __future__ import annotations


def parse_match(_raw: object) -> object:
    raise NotImplementedError("Pending recon and ADR-001.")


def parse_score(_score: str) -> object:
    raise NotImplementedError("Score parser pending — see TESTING.md property tests.")
