"""Head-to-head computation.

Given two player IDs, walk the matches table for any match where both appear
as player_a/player_b, compute the record, last result, and per-surface split.
Pure SQL + Python; no external calls.
"""

from __future__ import annotations


def head_to_head(_player_a_id: str, _player_b_id: str) -> object:
    raise NotImplementedError("Phase 2.")
