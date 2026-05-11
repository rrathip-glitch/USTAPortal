"""Unit tests for :mod:`src.parse.coretennis`.

The CoreTennis parser is exercised against the captured fixtures under
``tests/fixtures/coretennis/`` plus a handful of synthetic HTML snippets
that cover edge cases (no profile, broken rows, multi-year tabs).

Note on the outcome literal: the :class:`Match` model's
:data:`MatchOutcome` is ``Literal["completed", "retired", "walkover",
"default", "unfinished", "unknown"]`` — it does NOT include ``"won"`` or
``"lost"``. The parser therefore emits ``outcome="completed"`` for
finished CoreTennis rows and carries the W/L information in
``winner_id``: ``player_id`` for a W and ``None`` for an L. These tests
assert on that contract, not on the ``"won"``/``"lost"`` strings the
parser charter mentioned (which would violate Pydantic validation).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.parse.coretennis import ParseError, parse_coretennis_player

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "coretennis"

PLAYER_ID = "203938"


@pytest.fixture
def profile_html() -> str:
    return (FIXTURES / "janav_profile.html").read_text(encoding="utf-8")


@pytest.fixture
def results_html() -> str:
    return (FIXTURES / "janav_results.html").read_text(encoding="utf-8")


def test_parse_real_results_html_yields_expected_matches(
    profile_html: str, results_html: str
) -> None:
    """The canonical happy path: load both fixtures, assert match shape."""

    player, matches = parse_coretennis_player(
        profile_html, results_html, player_id=PLAYER_ID
    )

    # 1 match in 2026 + 3 matches in 2025 = 4 total.
    assert len(matches) == 4, [m.score_raw for m in matches]

    # 2026 tournament comes first in DOM order.
    first = matches[0]
    assert first.round == "1/32"
    # Outcome literal is constrained by the model; the L is encoded by
    # winner_id remaining None.
    assert first.outcome == "completed"
    assert first.winner_id is None  # listed player lost
    assert first.player_a_id == PLAYER_ID
    assert first.player_b_id is None
    assert first.score_raw == "75 26 1210"
    assert first.court == "Hard"
    assert first.scheduled_at is not None
    assert first.scheduled_at.year == 2026
    assert first.scheduled_at.month == 1
    assert first.scheduled_at.day == 17

    # Sets: 7-5, 2-6, then a match tiebreak. The third set is the
    # bracketed pseudo-set encoding parse_score uses (games 0-1 or 1-0
    # with both tiebreak_a/tiebreak_b set to the actual MTB points).
    assert len(first.sets) == 3
    assert (first.sets[0].games_a, first.sets[0].games_b) == (7, 5)
    assert (first.sets[1].games_a, first.sets[1].games_b) == (2, 6)
    mtb = first.sets[2]
    assert {mtb.games_a, mtb.games_b} == {0, 1}, "match tiebreak should be 0-1 pseudo-set"
    assert mtb.tiebreak_a is not None and mtb.tiebreak_b is not None
    assert {mtb.tiebreak_a, mtb.tiebreak_b} == {10, 12}

    # Opponent name isn't a model field, but the fixture's first match
    # opponent is Gustavo Lipinski — we verify via score_raw + round
    # combination above and via the draw_id slug below.
    assert "coretennis:" in first.draw_id

    # The 2025 dates roll through correctly.
    years = sorted({m.scheduled_at.year for m in matches if m.scheduled_at})
    assert years == [2025, 2026]


def test_parse_profile_html_extracts_name_and_category(
    profile_html: str, results_html: str
) -> None:
    player, _ = parse_coretennis_player(
        profile_html, results_html, player_id=PLAYER_ID
    )
    assert player.usta_id == PLAYER_ID
    assert player.full_name == "Janav Thasen"
    assert player.first_name == "Janav"
    assert player.last_name == "Thasen"
    assert player.gender == "M"
    assert player.age_category == "Boys 12"


def test_parse_with_missing_profile_returns_player_with_placeholder_name(
    results_html: str,
) -> None:
    player, matches = parse_coretennis_player(
        None, results_html, player_id=PLAYER_ID
    )
    assert player.usta_id == PLAYER_ID
    # Placeholder full_name when we have no profile HTML to crib from.
    assert "coretennis" in player.full_name.lower()
    assert player.gender is None
    assert player.age_category is None
    # Matches still parse fine.
    assert len(matches) == 4


def test_parse_skips_malformed_row() -> None:
    """A pprRow missing the score column is logged and skipped, not fatal."""

    html = """
    <html><body>
      <ul id="plTournTabs"><li><a href="#" rel="yearContent2026">2026</a></li></ul>
      <div id="yearContent2026" class="tabcontent">
        <div class="plTourn plTL901 plSurf2">
          <div class="pprContainer">
            <div class="pprHead">
              <div class="plM1">Mar 03<br>Mar 05</div>
              <div class="plM2">Some Tournament - Venue, City, ST - Boys 12 - Hard</div>
            </div>
            <div class="pprRow">
              <div class="plM1">QF</div>
              <div class="plM4">W</div>
              <div class="plM4">vs</div>
              <div class="plM2">Opponent A</div>
              <!-- score column is missing on purpose -->
            </div>
            <div class="pprRow">
              <div class="plM1">SF</div>
              <div class="plM4">L</div>
              <div class="plM4">vs</div>
              <div class="plM2">Opponent B</div>
              <div class="plM3">63 64</div>
            </div>
          </div>
        </div>
      </div>
    </body></html>
    """

    _, matches = parse_coretennis_player(
        None, html, player_id=PLAYER_ID
    )
    # The first row (no plM3) is skipped; the second row survives.
    assert len(matches) == 1
    survivor = matches[0]
    assert survivor.round == "SF"
    assert survivor.score_raw == "63 64"
    # L means winner_id stays None.
    assert survivor.winner_id is None


def test_parse_year_carries_across_rows() -> None:
    """A synthetic two-year HTML resolves each tournament to its tab year."""

    html = """
    <html><body>
      <ul id="plTournTabs">
        <li><a href="#" rel="yearContent2024">2024</a></li>
        <li><a href="#" rel="yearContent2022">2022</a></li>
      </ul>
      <div id="yearContent2024" class="tabcontent">
        <div class="plTourn">
          <div class="pprContainer">
            <div class="pprHead">
              <div class="plM1">Aug 10<br>Aug 12</div>
              <div class="plM2">Cup A - Venue - Boys 12 - Hard</div>
            </div>
            <div class="pprRow">
              <div class="plM1">F</div>
              <div class="plM4">W</div>
              <div class="plM4">vs</div>
              <div class="plM2">Foe A</div>
              <div class="plM3">62 63</div>
            </div>
          </div>
        </div>
      </div>
      <div id="yearContent2022" class="tabcontent">
        <div class="plTourn">
          <div class="pprContainer">
            <div class="pprHead">
              <div class="plM1">Apr 02<br>Apr 04</div>
              <div class="plM2">Cup B - Venue - Boys 12 - Clay</div>
            </div>
            <div class="pprRow">
              <div class="plM1">QF</div>
              <div class="plM4">L</div>
              <div class="plM4">vs</div>
              <div class="plM2">Foe B</div>
              <div class="plM3">36 46</div>
            </div>
          </div>
        </div>
      </div>
    </body></html>
    """

    _, matches = parse_coretennis_player(None, html, player_id=PLAYER_ID)
    assert len(matches) == 2

    by_year = {m.scheduled_at.year: m for m in matches if m.scheduled_at}
    assert set(by_year.keys()) == {2024, 2022}

    aug_match = by_year[2024]
    assert aug_match.scheduled_at.month == 8
    assert aug_match.scheduled_at.day == 10
    assert aug_match.court == "Hard"
    assert aug_match.winner_id == PLAYER_ID  # W -> winner_id is the player

    apr_match = by_year[2022]
    assert apr_match.scheduled_at.month == 4
    assert apr_match.scheduled_at.day == 2
    assert apr_match.court == "Clay"
    assert apr_match.winner_id is None  # L -> winner_id stays None


def test_parse_empty_results_html_raises_parse_error() -> None:
    with pytest.raises(ParseError):
        parse_coretennis_player(None, "", player_id=PLAYER_ID)


def test_parse_nonsense_results_html_raises_parse_error() -> None:
    """HTML missing every structural anchor is a hard ParseError."""

    with pytest.raises(ParseError):
        parse_coretennis_player(
            None,
            "<html><body><p>this is not a results page</p></body></html>",
            player_id=PLAYER_ID,
        )
