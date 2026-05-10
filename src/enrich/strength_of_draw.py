"""Strength-of-draw computation.

For a given draw and the user's seed line, compute average opponent rating,
hardest projected opponent on the path to the final, and easiest path. Uses
WTN as the rating axis where available, sectional ranking as fallback.
"""

from __future__ import annotations


def strength_of_draw(_draw_id: str, _player_id: str) -> object:
    raise NotImplementedError("Phase 2.")
