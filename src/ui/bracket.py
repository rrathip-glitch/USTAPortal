"""SVG bracket renderer for single-elimination draws.

Two pure helpers, no IO and no global state:

* :func:`build_bracket_layout` takes a draw, its entries, the matches we have
  so far, and a name lookup; returns a :class:`BracketLayout` — a 2-D grid of
  :class:`BracketSlot` objects, one column per round.
* :func:`render_bracket_svg` converts a layout into an SVG string ready for
  ``{{ ... | safe }}`` embedding in a Jinja template.

The grid is always padded to the next power of two so the geometry stays
predictable: round 0 has ``size/2`` slots, the round after has ``size/4``, and
so on down to a single final. Empty positions render as italic "TBD" boxes;
positions where a real winner is known propagate forward into the next
round's slot.

Round winners come from the supplied ``matches`` list. The matcher is
intentionally tolerant: a slot is a "winner" when its match has a
``winner_id`` that equals one of the two participants — round labels on
``Match`` (e.g. ``"R1"``, ``"QF"``) are not required, since we already know
the round from the slot's position in the grid. This keeps the renderer
useful for partially-synced draws where ``Match.round`` may be missing.

The user-highlight color picks out the focal player's slot in each round and
records the chain of indices in ``BracketLayout.user_path`` so the template
can render a "your path" legend without re-walking the grid.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from src.models.draw import Draw, DrawEntry
from src.models.match import Match
from src.models.player import Player

# Project palette — keep in sync with the existing CSS variables referenced in
# ``draw_detail.html``. Hard-coded here because SVG fills cannot read CSS
# custom properties reliably across browsers.
COLOR_USER = "#1d4ed8"          # project blue
COLOR_WINNER = "#16a34a"        # project green
COLOR_USER_OUT = "#6b7280"      # muted grey
COLOR_BORDER = "#cbd5e1"        # neutral slate
COLOR_TEXT = "#0f172a"          # near-black
COLOR_MUTED = "#64748b"         # secondary text
COLOR_BG = "#ffffff"

# Geometry constants. Tuned so a 32-player bracket fits a phone in landscape
# without text overlap; ``render_bracket_svg`` scales horizontally to the
# requested width but leaves vertical sizing fixed so the slot boxes stay
# readable on a courtside phone.
SLOT_HEIGHT = 24
SLOT_GAP = 8                    # vertical gap between two slots in a pair
PAIR_GAP = 18                   # vertical gap between match groups in R1
ROUND_LABEL_HEIGHT = 24
PADDING_X = 12
PADDING_Y = 12
NAME_MAX_LEN = 22


@dataclass(frozen=True)
class BracketSlot:
    """One position in the bracket grid.

    ``top_*`` / ``bottom_*`` are the two players paired at this slot. In
    rounds > 0 they are the winners (when known) of the two feeder slots
    below; ``None`` means "TBD".
    """

    round_index: int
    match_index: int
    top_player_id: str | None
    top_player_name: str | None
    top_seed: int | None
    bottom_player_id: str | None
    bottom_player_name: str | None
    bottom_seed: int | None
    winner_id: str | None
    score: str | None
    highlight: bool


@dataclass(frozen=True)
class BracketLayout:
    """Resolved bracket grid.

    ``slot_grid[r][m]`` is the slot at round ``r`` (0 = first round, N-1 =
    final) and match index ``m``. ``user_path`` is the chain of ``match_index``
    values where the focal user appears, truncated at the round they lose in.
    Empty when no user player was supplied or they are not in the field.
    """

    rounds: int
    slot_grid: list[list[BracketSlot]]
    user_path: list[int]


# ---------------------------------------------------------------------------
# Layout construction
# ---------------------------------------------------------------------------


def _round_up_pow2(n: int) -> int:
    """Smallest power of two >= ``n`` (``n >= 1``)."""
    p = 1
    while p < n:
        p <<= 1
    return p


def _bracket_size(draw: Draw, entries: list[DrawEntry]) -> int:
    """Pick a power-of-two bracket size.

    Prefer the count of entries (so a 6-entry draw rounds up to 8 with two
    byes). Fall back to ``draw.size`` when no entries are loaded yet. As a
    last resort, default to 8 — the renderer should still produce a valid SVG
    on a fresh checkout with no synced data.
    """
    n = len(entries)
    if n > 0:
        return max(2, _round_up_pow2(n))
    if draw.size and draw.size > 0:
        return max(2, _round_up_pow2(draw.size))
    return 8


def _player_display_name(player: Player | None, fallback_id: str | None) -> str | None:
    """Resolve a display name. ``None`` -> renders as TBD; ID-as-name is fine
    when the player row hasn't been synced yet."""
    if player is not None and player.full_name:
        return player.full_name
    return fallback_id


def _winners_by_round(
    matches: list[Match], rounds: int
) -> dict[int, dict[tuple[str, str], str]]:
    """Index winner IDs by (round, frozenset-of-participants).

    The bracket grid already knows which round a slot belongs to, and the
    feeder slots tell us the two participants. Looking up "did one of these
    two win their match?" only needs the participant pair — we don't have to
    trust ``Match.round`` strings, which may be missing or formatted
    inconsistently across sources.

    Returned shape: ``index[round_index][(player_a, player_b)] = winner_id``,
    where the participant tuple is canonicalised (sorted) so the lookup is
    symmetric regardless of A/B order on the ``Match`` row.
    """
    # Try to honour Match.round when present — this lets us disambiguate
    # rematches across rounds. When absent, we fall back to "any match between
    # these two" and assign to every round.
    label_to_index = _round_label_index(rounds)
    index: dict[int, dict[tuple[str, str], str]] = {r: {} for r in range(rounds)}
    for m in matches:
        if not m.winner_id or not m.player_a_id or not m.player_b_id:
            continue
        key = tuple(sorted((m.player_a_id, m.player_b_id)))
        # ``tuple(sorted(...))`` widens to ``tuple[str, ...]``; cast back to a
        # fixed-length pair for the dict key.
        pair: tuple[str, str] = (key[0], key[1])
        r_idx = label_to_index.get((m.round or "").upper())
        if r_idx is not None and 0 <= r_idx < rounds:
            index[r_idx][pair] = m.winner_id
        else:
            for r in range(rounds):
                index[r].setdefault(pair, m.winner_id)
    return index


def _round_label_index(rounds: int) -> dict[str, int]:
    """Map round-label strings (``"R1"``, ``"QF"``, ``"F"``) to an index.

    The mapping depends on the bracket depth — a 32-player draw has
    ``R1, R2, R3, QF, SF, F``; an 8-player draw is just ``QF, SF, F``. We
    build it from the back: the final is always the last round.
    """
    if rounds <= 0:
        return {}
    tail = ["F", "SF", "QF"]
    out: dict[str, int] = {}
    for offset, label in enumerate(tail):
        idx = rounds - 1 - offset
        if idx < 0:
            break
        out[label] = idx
    # Earlier rounds: R1, R2, ... counted from the start.
    earliest = rounds - len(tail)
    for r in range(min(earliest, rounds)):
        out[f"R{r + 1}"] = r
    return out


def build_bracket_layout(
    draw: Draw,
    entries: list[DrawEntry],
    matches: list[Match],
    players_by_id: dict[str, Player],
    *,
    user_player_id: str | None = None,
) -> BracketLayout:
    """Resolve the draw + matches into a renderable grid.

    Bracket size rounds up to the next power of two; missing positions render
    as TBD; winners from ``matches`` propagate forward one round at a time.

    The user-path computation walks the grid from R1 forward: each round we
    locate the slot the user occupies (top or bottom), record its
    ``match_index``, and stop the moment they lose or disappear (knocked out,
    withdrew, never had a position).
    """
    size = _bracket_size(draw, entries)
    if size < 2:
        return BracketLayout(rounds=0, slot_grid=[], user_path=[])

    rounds = max(1, size.bit_length() - 1)  # 8 -> 3, 16 -> 4, 32 -> 5

    # Position -> entry, restricted to positions in [1, size].
    by_position: dict[int, DrawEntry] = {}
    for e in entries:
        if e.position is None or e.position < 1 or e.position > size:
            continue
        by_position[e.position] = e

    winners_index = _winners_by_round(matches, rounds)

    # Build R1 slots: slot k pairs positions 2k+1 and 2k+2.
    grid: list[list[BracketSlot]] = []
    r1_slots: list[BracketSlot] = []
    r1_size = size // 2
    for k in range(r1_size):
        top_entry = by_position.get(2 * k + 1)
        bot_entry = by_position.get(2 * k + 2)
        top_id = top_entry.player_id if top_entry else None
        bot_id = bot_entry.player_id if bot_entry else None
        winner = None
        score = None
        if top_id and bot_id:
            pair: tuple[str, str] = tuple(sorted((top_id, bot_id)))  # type: ignore[assignment]
            winner = winners_index.get(0, {}).get(pair)
            score = _match_score(matches, top_id, bot_id)
        r1_slots.append(
            BracketSlot(
                round_index=0,
                match_index=k,
                top_player_id=top_id,
                top_player_name=_player_display_name(
                    players_by_id.get(top_id) if top_id else None, top_id
                ),
                top_seed=top_entry.seed if top_entry else None,
                bottom_player_id=bot_id,
                bottom_player_name=_player_display_name(
                    players_by_id.get(bot_id) if bot_id else None, bot_id
                ),
                bottom_seed=bot_entry.seed if bot_entry else None,
                winner_id=winner,
                score=score,
                highlight=False,
            )
        )
    grid.append(r1_slots)

    # Higher rounds: each slot's top/bottom comes from the winner of the two
    # feeder slots in the previous round.
    for r in range(1, rounds):
        prev = grid[r - 1]
        this_round: list[BracketSlot] = []
        for k in range(len(prev) // 2):
            feeder_top = prev[2 * k]
            feeder_bot = prev[2 * k + 1]
            top_id = feeder_top.winner_id
            bot_id = feeder_bot.winner_id
            top_seed = _seed_for(feeder_top, top_id)
            bot_seed = _seed_for(feeder_bot, bot_id)
            winner = None
            score = None
            if top_id and bot_id:
                pair_r: tuple[str, str] = tuple(sorted((top_id, bot_id)))  # type: ignore[assignment]
                winner = winners_index.get(r, {}).get(pair_r)
                score = _match_score(matches, top_id, bot_id)
            this_round.append(
                BracketSlot(
                    round_index=r,
                    match_index=k,
                    top_player_id=top_id,
                    top_player_name=_player_display_name(
                        players_by_id.get(top_id) if top_id else None, top_id
                    ),
                    top_seed=top_seed,
                    bottom_player_id=bot_id,
                    bottom_player_name=_player_display_name(
                        players_by_id.get(bot_id) if bot_id else None, bot_id
                    ),
                    bottom_seed=bot_seed,
                    winner_id=winner,
                    score=score,
                    highlight=False,
                )
            )
        grid.append(this_round)

    # User path: walk forward, marking the slot the user is in. Stop the
    # moment they don't appear (knocked out or withdrew before this round).
    user_path: list[int] = []
    if user_player_id:
        for slots in grid:
            hit_index: int | None = None
            for slot in slots:
                if (
                    slot.top_player_id == user_player_id
                    or slot.bottom_player_id == user_player_id
                ):
                    hit_index = slot.match_index
                    break
            if hit_index is None:
                break
            user_path.append(hit_index)

    # Re-emit highlighted copies of the slots on the path. Frozen dataclasses
    # can't be mutated in place, so we rebuild the affected rows.
    if user_path:
        for r, m_idx in enumerate(user_path):
            row = grid[r]
            slot = row[m_idx]
            row[m_idx] = BracketSlot(
                round_index=slot.round_index,
                match_index=slot.match_index,
                top_player_id=slot.top_player_id,
                top_player_name=slot.top_player_name,
                top_seed=slot.top_seed,
                bottom_player_id=slot.bottom_player_id,
                bottom_player_name=slot.bottom_player_name,
                bottom_seed=slot.bottom_seed,
                winner_id=slot.winner_id,
                score=slot.score,
                highlight=True,
            )

    return BracketLayout(rounds=rounds, slot_grid=grid, user_path=user_path)


def _seed_for(feeder: BracketSlot, winner_id: str | None) -> int | None:
    """Pick the seed corresponding to a feeder slot's winner side."""
    if winner_id is None:
        return None
    if feeder.top_player_id == winner_id:
        return feeder.top_seed
    if feeder.bottom_player_id == winner_id:
        return feeder.bottom_seed
    return None


def _match_score(matches: list[Match], a: str, b: str) -> str | None:
    """Best-effort score lookup for a pair, regardless of A/B order."""
    pair = {a, b}
    for m in matches:
        if not m.player_a_id or not m.player_b_id:
            continue
        if {m.player_a_id, m.player_b_id} == pair:
            return m.score_raw
    return None


# ---------------------------------------------------------------------------
# SVG rendering
# ---------------------------------------------------------------------------


def _truncate(name: str) -> str:
    """Cap a name at :data:`NAME_MAX_LEN` characters with an ellipsis."""
    if len(name) <= NAME_MAX_LEN:
        return name
    return name[: NAME_MAX_LEN - 1].rstrip() + "…"


def _label_for(
    name: str | None,
    seed: int | None,
) -> tuple[str, bool]:
    """Return the display text + a flag for whether it should render italic.

    Italic == "TBD" — we want a visual cue distinct from a real player whose
    name happens to be short.
    """
    if not name:
        return "TBD", True
    text = _truncate(name)
    if seed is not None:
        text = f"{text} ({seed})"
    return text, False


def _round_title(round_index: int, total_rounds: int) -> str:
    """Human label for a round column."""
    remaining = total_rounds - round_index
    if remaining == 1:
        return "Final"
    if remaining == 2:
        return "Semifinal"
    if remaining == 3:
        return "Quarterfinal"
    return f"Round {round_index + 1}"


def _slot_color(slot: BracketSlot, player_side_id: str | None) -> str:
    """Pick the stroke colour for one player box in a slot."""
    if slot.highlight:
        if slot.winner_id and slot.winner_id != player_side_id:
            # User lost this match — muted grey on the loser side.
            return COLOR_USER_OUT
        return COLOR_USER
    if slot.winner_id and slot.winner_id == player_side_id:
        return COLOR_WINNER
    return COLOR_BORDER


def render_bracket_svg(layout: BracketLayout, *, width: int = 1100) -> str:
    """Render a layout to an SVG string.

    Returns a minimal but well-formed ``<svg>`` document. Width is requested
    by the caller; height is derived from the R1 slot count so the geometry
    stays consistent across draw sizes. Empty layouts return a tiny
    placeholder SVG rather than the empty string, so the template can embed
    the result without an extra ``if`` guard.
    """
    if layout.rounds == 0 or not layout.slot_grid:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'viewBox="0 0 100 40" preserveAspectRatio="xMinYMin meet" '
            'role="img" aria-label="Empty bracket">'
            '<text x="10" y="24" font-family="system-ui, sans-serif" '
            f'font-size="14" fill="{COLOR_MUTED}" font-style="italic">'
            "No bracket data yet</text></svg>"
        )

    r1_count = len(layout.slot_grid[0])
    # Vertical span of one R1 match group (two slots + inner gap).
    group_height = SLOT_HEIGHT * 2 + SLOT_GAP
    body_height = r1_count * group_height + (r1_count - 1) * PAIR_GAP
    height = body_height + ROUND_LABEL_HEIGHT + 2 * PADDING_Y

    col_count = layout.rounds
    inner_width = max(1, width - 2 * PADDING_X)
    col_width = inner_width / col_count
    box_width = max(80.0, col_width - 28)  # leave room for connector lines

    parts: list[str] = []
    parts.append(
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width} {int(height)}" '
        'preserveAspectRatio="xMinYMin meet" '
        'role="img" aria-label="Tournament bracket">'
    )
    parts.append(f'<rect width="{width}" height="{int(height)}" fill="{COLOR_BG}"/>')

    # Pre-compute slot vertical centres per round. Round 0 spaces matches
    # evenly; subsequent rounds centre each slot between its two feeders.
    centres: list[list[float]] = []
    for r in range(layout.rounds):
        if r == 0:
            ys = [
                PADDING_Y
                + ROUND_LABEL_HEIGHT
                + i * (group_height + PAIR_GAP)
                + group_height / 2
                for i in range(r1_count)
            ]
        else:
            prev = centres[r - 1]
            ys = [(prev[2 * i] + prev[2 * i + 1]) / 2 for i in range(len(prev) // 2)]
        centres.append(ys)

    # Round headers.
    for r in range(layout.rounds):
        cx = PADDING_X + r * col_width + box_width / 2
        parts.append(
            f'<text x="{cx:.1f}" y="{PADDING_Y + 14}" '
            'font-family="system-ui, sans-serif" font-size="12" '
            f'fill="{COLOR_MUTED}" text-anchor="middle">'
            f"{escape(_round_title(r, layout.rounds))}</text>"
        )

    # Connector lines from each slot to the next round's slot.
    for r in range(layout.rounds - 1):
        next_centres = centres[r + 1]
        for k, cy in enumerate(centres[r]):
            x_right = PADDING_X + r * col_width + box_width
            x_next = PADDING_X + (r + 1) * col_width
            mid_x = (x_right + x_next) / 2
            target_y = next_centres[k // 2]
            parts.append(
                f'<line x1="{x_right:.1f}" y1="{cy:.1f}" '
                f'x2="{mid_x:.1f}" y2="{cy:.1f}" '
                f'stroke="{COLOR_BORDER}" stroke-width="1"/>'
            )
            parts.append(
                f'<line x1="{mid_x:.1f}" y1="{cy:.1f}" '
                f'x2="{mid_x:.1f}" y2="{target_y:.1f}" '
                f'stroke="{COLOR_BORDER}" stroke-width="1"/>'
            )
            parts.append(
                f'<line x1="{mid_x:.1f}" y1="{target_y:.1f}" '
                f'x2="{x_next:.1f}" y2="{target_y:.1f}" '
                f'stroke="{COLOR_BORDER}" stroke-width="1"/>'
            )

    # Slot groups.
    for r, slots in enumerate(layout.slot_grid):
        x = PADDING_X + r * col_width
        for slot in slots:
            cy = centres[r][slot.match_index]
            y_top = cy - SLOT_HEIGHT - SLOT_GAP / 2
            y_bot = cy + SLOT_GAP / 2
            parts.append(
                f'<g class="bracket-slot" data-round="{slot.round_index}" '
                f'data-match="{slot.match_index}">'
            )
            parts.append(
                _render_player_box(
                    x,
                    y_top,
                    box_width,
                    slot.top_player_name,
                    slot.top_seed,
                    _slot_color(slot, slot.top_player_id),
                    is_winner=(
                        slot.winner_id is not None
                        and slot.winner_id == slot.top_player_id
                    ),
                )
            )
            parts.append(
                _render_player_box(
                    x,
                    y_bot,
                    box_width,
                    slot.bottom_player_name,
                    slot.bottom_seed,
                    _slot_color(slot, slot.bottom_player_id),
                    is_winner=(
                        slot.winner_id is not None
                        and slot.winner_id == slot.bottom_player_id
                    ),
                )
            )
            parts.append("</g>")

    parts.append("</svg>")
    return "".join(parts)


def _render_player_box(
    x: float,
    y: float,
    box_width: float,
    name: str | None,
    seed: int | None,
    stroke: str,
    *,
    is_winner: bool,
) -> str:
    """Render one ``<rect>`` + ``<text>`` for a single player slot."""
    text, italic = _label_for(name, seed)
    safe_text = escape(text)
    font_weight = "600" if is_winner else "400"
    font_style = "italic" if italic else "normal"
    text_fill = COLOR_MUTED if italic else COLOR_TEXT
    stroke_width = 2 if stroke != COLOR_BORDER else 1
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{box_width:.1f}" '
        f'height="{SLOT_HEIGHT}" rx="4" ry="4" '
        f'fill="{COLOR_BG}" stroke="{stroke}" stroke-width="{stroke_width}"/>'
        f'<text x="{x + 8:.1f}" y="{y + SLOT_HEIGHT / 2 + 4:.1f}" '
        'font-family="system-ui, sans-serif" font-size="12" '
        f'font-weight="{font_weight}" font-style="{font_style}" '
        f'fill="{text_fill}">{safe_text}</text>'
    )


__all__ = [
    "BracketLayout",
    "BracketSlot",
    "build_bracket_layout",
    "render_bracket_svg",
]
