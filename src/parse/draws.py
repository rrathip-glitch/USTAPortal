"""Draw / bracket parser. Pending recon.

The example URL `/Competitions/<comp>/Tournaments/draws/<GUID>` suggests draws
are addressed by GUID; recon must confirm whether the GUID is the tournament
ID, draw ID, or a composite, and what the JSON shape looks like.
"""

from __future__ import annotations


def parse_draw(_raw: object) -> object:
    raise NotImplementedError("Pending recon and ADR-001.")
