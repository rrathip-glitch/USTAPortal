"""Unit tests for :mod:`src.ui.bracket`.

These tests exercise the two public helpers in isolation — no database, no
TestClient. The :class:`BracketLayout` builder is asserted by inspecting the
``slot_grid`` directly; the SVG renderer is asserted by string-search on its
output (we are not validating XML structurally, only that the well-known
shapes are present).

A tiny ``_player`` / ``_entry`` / ``_match`` triple of factory helpers keeps
each test focused on the field under examination — every other field gets a
sensible default.
"""

from __future__ import annotations

from src.models.draw import Draw, DrawEntry
from src.models.match import Match
from src.models.player import Player
from src.ui.bracket import (
    BracketLayout,
    build_bracket_layout,
    render_bracket_svg,
)

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _draw(size: int | None = 8) -> Draw:
    return Draw(
        usta_id="D-TEST",
        tournament_id="T-TEST",
        name="Test Draw",
        format="single_elimination",
        size=size,
    )


def _player(pid: str, name: str | None = None) -> Player:
    return Player(usta_id=pid, full_name=name or f"Player {pid}")


def _entry(pid: str, position: int, seed: int | None = None) -> DrawEntry:
    return DrawEntry(draw_id="D-TEST", player_id=pid, seed=seed, position=position)


def _match(a: str, b: str, winner: str, *, round_: str | None = None) -> Match:
    return Match(
        usta_id=f"M-{a}-{b}",
        draw_id="D-TEST",
        round=round_,
        player_a_id=a,
        player_b_id=b,
        winner_id=winner,
        score_raw="6-4 6-2",
    )


def _eight_entries() -> list[DrawEntry]:
    return [_entry(f"P{i}", position=i) for i in range(1, 9)]


def _players_for(entries: list[DrawEntry]) -> dict[str, Player]:
    return {e.player_id: _player(e.player_id) for e in entries}


# ---------------------------------------------------------------------------
# build_bracket_layout
# ---------------------------------------------------------------------------


def test_eight_entries_no_matches_populates_r1_only() -> None:
    """R1 has all 4 slots filled; R2 + final exist with no winners yet."""
    entries = _eight_entries()
    layout = build_bracket_layout(
        _draw(8), entries, matches=[], players_by_id=_players_for(entries)
    )

    assert layout.rounds == 3
    assert len(layout.slot_grid) == 3
    assert [len(r) for r in layout.slot_grid] == [4, 2, 1]

    # R1: every slot has both players.
    for slot in layout.slot_grid[0]:
        assert slot.top_player_id is not None
        assert slot.bottom_player_id is not None
        assert slot.winner_id is None

    # R2 and Final: both sides TBD because no R1 winners are known.
    for r in (1, 2):
        for slot in layout.slot_grid[r]:
            assert slot.top_player_id is None
            assert slot.bottom_player_id is None


def test_two_r1_winners_flow_into_r2() -> None:
    """Resolving two R1 matches surfaces those winners as R2 participants."""
    entries = _eight_entries()
    matches = [
        # Slot 0: P1 vs P2 -> P1 wins.
        _match("P1", "P2", "P1", round_="R1"),
        # Slot 1: P3 vs P4 -> P3 wins. Together they meet in R2 slot 0.
        _match("P3", "P4", "P3", round_="R1"),
    ]
    layout = build_bracket_layout(
        _draw(8), entries, matches, players_by_id=_players_for(entries)
    )

    r2_slot0 = layout.slot_grid[1][0]
    assert {r2_slot0.top_player_id, r2_slot0.bottom_player_id} == {"P1", "P3"}
    # The R2 slot itself has no winner (no R2 match supplied).
    assert r2_slot0.winner_id is None

    # The unresolved R2 slot still has both sides TBD.
    r2_slot1 = layout.slot_grid[1][1]
    assert r2_slot1.top_player_id is None
    assert r2_slot1.bottom_player_id is None


def test_user_path_extends_round_by_round() -> None:
    """User in position 1, wins R1 -> user_path covers R1 and R2."""
    entries = _eight_entries()
    matches = [
        _match("P1", "P2", "P1", round_="R1"),  # user wins R1
    ]
    layout = build_bracket_layout(
        _draw(8),
        entries,
        matches,
        players_by_id=_players_for(entries),
        user_player_id="P1",
    )

    # R1 slot 0 holds the user; user_path[0] == 0.
    assert layout.user_path[0] == 0
    # R2 slot 0 carries P1 forward; user_path extends.
    assert len(layout.user_path) >= 2
    assert layout.user_path[1] == 0

    # The R1 slot the user occupies is marked highlight=True.
    assert layout.slot_grid[0][0].highlight is True


def test_user_path_truncates_on_elimination() -> None:
    """User loses R1 -> path has exactly one entry (the round they exited)."""
    entries = _eight_entries()
    matches = [
        _match("P1", "P2", "P2", round_="R1"),  # P2 beats P1
    ]
    layout = build_bracket_layout(
        _draw(8),
        entries,
        matches,
        players_by_id=_players_for(entries),
        user_player_id="P1",
    )

    assert layout.user_path == [0]


# ---------------------------------------------------------------------------
# render_bracket_svg
# ---------------------------------------------------------------------------


def test_render_returns_well_formed_svg_with_key_shapes() -> None:
    """SVG output contains the headline structural markers."""
    entries = _eight_entries()
    layout = build_bracket_layout(
        _draw(8), entries, matches=[], players_by_id=_players_for(entries)
    )
    svg = render_bracket_svg(layout)

    assert svg.startswith("<svg")
    assert "viewBox=" in svg
    assert "<g" in svg
    assert "</svg>" in svg
    assert 'preserveAspectRatio="xMinYMin meet"' in svg


def test_long_names_are_truncated() -> None:
    """A 40-char name is shortened in the rendered text (cap is 22)."""
    long_name = "A" * 40
    entries = [_entry("P1", 1), _entry("P2", 2)]
    players = {
        "P1": _player("P1", long_name),
        "P2": _player("P2", "Short Name"),
    }
    layout = build_bracket_layout(_draw(2), entries, matches=[], players_by_id=players)
    svg = render_bracket_svg(layout)

    # The full 40-char name must not appear verbatim.
    assert long_name not in svg
    # But its truncated prefix should.
    assert "A" * 20 in svg


def test_seed_renders_in_parentheses_after_name() -> None:
    """Entries with ``seed`` produce ``"Name (4)"`` in the SVG text."""
    entries = [_entry("P1", 1, seed=4), _entry("P2", 2)]
    players = {
        "P1": _player("P1", "Janav Thasen"),
        "P2": _player("P2", "Other Player"),
    }
    layout = build_bracket_layout(_draw(2), entries, matches=[], players_by_id=players)
    svg = render_bracket_svg(layout)

    assert "Janav Thasen (4)" in svg


def test_empty_layout_renders_placeholder_svg() -> None:
    """A zero-entry, zero-size layout still returns a valid ``<svg>``."""
    empty = BracketLayout(rounds=0, slot_grid=[], user_path=[])
    svg = render_bracket_svg(empty)

    assert svg.startswith("<svg")
    assert "</svg>" in svg
    assert "viewBox=" in svg
    # Defensive: should not crash, should not be empty.
    assert len(svg) > 0


def test_six_entries_round_up_to_eight_with_byes() -> None:
    """6 entries fill 6 of 8 R1 slot sides; 2 sides remain ``None``."""
    entries = [_entry(f"P{i}", position=i) for i in range(1, 7)]
    layout = build_bracket_layout(
        _draw(None), entries, matches=[], players_by_id=_players_for(entries)
    )

    # Power of two rounding: 6 -> 8 -> 3 rounds.
    assert layout.rounds == 3
    assert len(layout.slot_grid[0]) == 4

    # Count the missing player slots — should be exactly 2 (the byes).
    missing = 0
    for slot in layout.slot_grid[0]:
        if slot.top_player_id is None:
            missing += 1
        if slot.bottom_player_id is None:
            missing += 1
    assert missing == 2


# ---------------------------------------------------------------------------
# Extra coverage — winner stroke + TBD text
# ---------------------------------------------------------------------------


def test_tbd_label_appears_for_missing_player() -> None:
    """A slot with no player on one side renders ``TBD`` in italic."""
    entries = [_entry("P1", 1)]  # position 2 is empty
    players = {"P1": _player("P1", "Solo Player")}
    layout = build_bracket_layout(_draw(2), entries, matches=[], players_by_id=players)
    svg = render_bracket_svg(layout)

    assert "TBD" in svg
    assert 'font-style="italic"' in svg


def test_winner_box_uses_green_stroke() -> None:
    """When a slot has a winner, the winner's box is stroked in project green."""
    entries = [_entry("P1", 1), _entry("P2", 2)]
    matches = [_match("P1", "P2", "P1", round_="F")]
    players = {"P1": _player("P1"), "P2": _player("P2")}
    layout = build_bracket_layout(_draw(2), entries, matches, players_by_id=players)
    svg = render_bracket_svg(layout)

    # Green stroke colour is documented in bracket.py as #16a34a.
    assert "#16a34a" in svg
