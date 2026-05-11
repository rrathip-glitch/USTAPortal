"""SVG line-chart and sparkline helpers for the player briefing UI.

These helpers produce **pure-SVG strings** that templates can embed verbatim
with the Jinja ``|safe`` filter. There is intentionally no JavaScript, no
external charting dependency, and no per-request asset graph — every chart is
self-contained markup the browser renders natively. The follow-up route agent
will compute the snapshot lists (or empty lists in a fresh-DB scenario) and
hand them to :func:`render_wtn_trajectory_svg` /
:func:`render_ranking_trajectory_svg` / :func:`render_win_loss_sparkline`.

Design rules baked in:

- Empty inputs render a stable-sized "No data yet" placeholder so a fresh
  install never collapses the surrounding page layout.
- WTN values and ranking positions are **lower-is-better**, so those charts
  flip the y-axis (highest value at the bottom). Callers signal this with the
  ``y_inverted`` flag on the generic :func:`render_line_chart`.
- Any text drawn from a snapshot's ``label`` (which may include a
  user-supplied player name) is run through :func:`html.escape` before being
  injected into the SVG. ``<title>`` and ``<text>`` nodes parse markup like
  HTML, so an un-escaped ``&`` or ``<`` would break the document.
"""

from __future__ import annotations

import html
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime

from src.models.ranking import RankingSnapshot
from src.models.wtn import WTNSnapshot

# Layout constants — exposed as module-level so tests (and future callers
# wanting consistent paddings across charts) can reference them by name.
PAD_LEFT = 32
PAD_BOTTOM = 24
PAD_RIGHT = 8
PAD_TOP = 8


@dataclass(frozen=True)
class ChartPoint:
    """One datum on a line chart.

    ``x_value`` may be a :class:`date` or :class:`datetime`; both are
    normalised to ordinal-day arithmetic during scaling, so a mix is tolerated
    but homogeneous inputs render most predictably. ``label`` is rendered as
    the ``<title>`` child of the marker circle — the browser surfaces it as
    a native tooltip on hover.
    """

    x_value: date | datetime
    y_value: float
    label: str


@dataclass(frozen=True)
class ChartAnnotation:
    """A vertical-line annotation: e.g. "tournament start"."""

    x_value: date | datetime
    label: str


# ---------------------------------------------------------------------------
# Internal scaling / formatting helpers
# ---------------------------------------------------------------------------


def _to_ordinal(value: date | datetime) -> float:
    """Convert a date/datetime to a float ordinal (days since epoch).

    Using a single numeric axis lets us mix :class:`date` and
    :class:`datetime` callers without branching every time we compute a
    coordinate. Datetimes contribute their time-of-day as a fractional day.
    """
    if isinstance(value, datetime):
        base = value.date().toordinal()
        seconds = (
            value.hour * 3600 + value.minute * 60 + value.second + value.microsecond / 1e6
        )
        return base + seconds / 86400.0
    return float(value.toordinal())


def _scale(value: float, src_min: float, src_max: float, dst_min: float, dst_max: float) -> float:
    """Linearly map ``value`` from the source range into the destination range.

    Degenerate sources (``src_min == src_max``) collapse to the midpoint of
    the destination so a single-point chart still renders sensibly rather
    than dividing by zero.
    """
    if src_max == src_min:
        return (dst_min + dst_max) / 2.0
    return dst_min + (value - src_min) * (dst_max - dst_min) / (src_max - src_min)


def _format_x_tick(value: float) -> str:
    """Format an ordinal x-coordinate as ``MMM 'YY`` (e.g. ``Apr '26``).

    Negative or otherwise-non-resolvable ordinals fall back to an empty
    string — the chart still renders, the tick just goes label-less.
    """
    try:
        d = date.fromordinal(round(value))
    except (ValueError, OverflowError):
        return ""
    return d.strftime("%b '%y")


def _format_y_tick(value: float, *, integer: bool) -> str:
    """Format a y-tick: integer for rank-style axes, one decimal otherwise."""
    if integer:
        return f"{round(value)}"
    return f"{value:.1f}"


def _empty_chart_svg(width: int, height: int) -> str:
    """Render the "No data yet" placeholder at the caller's requested size."""
    msg = "No data yet"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{msg}">'
        f'<text x="{width // 2}" y="{height // 2}" text-anchor="middle" '
        f'dominant-baseline="middle" fill="#6b7280" '
        f'font-family="system-ui, sans-serif" font-size="14">{msg}</text>'
        f"</svg>"
    )


# ---------------------------------------------------------------------------
# Public renderers
# ---------------------------------------------------------------------------


def render_line_chart(
    points: list[ChartPoint],
    *,
    width: int = 640,
    height: int = 200,
    y_inverted: bool = False,
    title: str | None = None,
    y_label: str | None = None,
    fill_color: str = "#2563eb",
    stroke_color: str = "#1d4ed8",
    annotations: list[ChartAnnotation] | None = None,
    y_integer_ticks: bool = False,
) -> str:
    """Render a list of :class:`ChartPoint` as an SVG line chart.

    Returns the SVG document as a string. The caller is responsible for
    embedding it with ``|safe`` in a Jinja template (or writing it directly
    to a response). ``y_inverted=True`` is the right choice for axes where
    lower numeric values are *better* (WTN, ranking position) — the smaller
    value sits at the top of the plot rather than the bottom.
    """
    if not points:
        return _empty_chart_svg(width, height)

    plot_x0 = PAD_LEFT
    plot_y0 = PAD_TOP
    plot_x1 = width - PAD_RIGHT
    plot_y1 = height - PAD_BOTTOM
    plot_w = max(1, plot_x1 - plot_x0)
    plot_h = max(1, plot_y1 - plot_y0)

    xs = [_to_ordinal(p.x_value) for p in points]
    ys = [p.y_value for p in points]
    x_min, x_max = min(xs), max(xs)
    if x_min == x_max:
        # Single-point series — pad one day each side so the polyline path
        # has a non-zero range to scale into.
        x_min -= 1.0
        x_max += 1.0

    y_lo_raw, y_hi_raw = min(ys), max(ys)
    if y_lo_raw == y_hi_raw:
        # Flat series — bracket the value so we don't collapse to a zero
        # range. Choose +/- 1 unit which works for both WTN (1-40) and rank.
        y_lo = y_lo_raw - 1.0
        y_hi = y_hi_raw + 1.0
    else:
        y_lo = y_lo_raw * 0.95
        y_hi = y_hi_raw * 1.05
        # When the spec says "min*0.95, max*1.05", negative values would
        # invert the bounds. We're not expecting them here, but clamp anyway.
        if y_lo > y_hi:
            y_lo, y_hi = y_hi, y_lo

    def project_x(v: float) -> float:
        return _scale(v, x_min, x_max, plot_x0, plot_x1)

    def project_y(v: float) -> float:
        # When y is inverted ("lower is better"), swap the destination
        # endpoints so the smallest value sits at the top of the plot.
        if y_inverted:
            return _scale(v, y_lo, y_hi, plot_y0, plot_y1)
        return _scale(v, y_lo, y_hi, plot_y1, plot_y0)

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{html.escape(title or y_label or "Line chart")}">'
    )

    if title:
        parts.append(
            f'<title>{html.escape(title)}</title>'
        )

    # Plot border + subtle background — gives the chart visual weight.
    parts.append(
        f'<rect x="{plot_x0}" y="{plot_y0}" width="{plot_w}" height="{plot_h}" '
        f'fill="#f9fafb" stroke="#e5e7eb"/>'
    )

    # Y-axis ticks (4 evenly spaced)
    for i in range(4):
        frac = i / 3.0
        # Tick value: when inverted, top of plot is y_lo (best), bottom is
        # y_hi (worst); display order goes top→bottom so the top label is
        # the smallest value.
        if y_inverted:
            v = y_lo + frac * (y_hi - y_lo)
            ty = plot_y0 + frac * plot_h
        else:
            v = y_hi - frac * (y_hi - y_lo)
            ty = plot_y0 + frac * plot_h
        parts.append(
            f'<line x1="{plot_x0}" y1="{ty:.1f}" x2="{plot_x1}" y2="{ty:.1f}" '
            f'stroke="#e5e7eb" stroke-dasharray="2,3"/>'
        )
        parts.append(
            f'<text x="{plot_x0 - 4}" y="{ty:.1f}" text-anchor="end" '
            f'dominant-baseline="middle" font-family="system-ui, sans-serif" '
            f'font-size="10" fill="#374151">'
            f"{html.escape(_format_y_tick(v, integer=y_integer_ticks))}</text>"
        )

    # X-axis ticks (3 evenly spaced)
    for i in range(3):
        frac = i / 2.0
        v = x_min + frac * (x_max - x_min)
        tx = plot_x0 + frac * plot_w
        parts.append(
            f'<text x="{tx:.1f}" y="{plot_y1 + 14}" text-anchor="middle" '
            f'font-family="system-ui, sans-serif" font-size="10" '
            f'fill="#374151">{html.escape(_format_x_tick(v))}</text>'
        )

    # Y-axis label (rotated)
    if y_label:
        parts.append(
            f'<text x="10" y="{plot_y0 + plot_h / 2:.1f}" text-anchor="middle" '
            f'transform="rotate(-90 10 {plot_y0 + plot_h / 2:.1f})" '
            f'font-family="system-ui, sans-serif" font-size="10" '
            f'fill="#374151">{html.escape(y_label)}</text>'
        )

    # Polyline path
    projected = [(project_x(x), project_y(y)) for x, y in zip(xs, ys, strict=True)]
    points_attr = " ".join(f"{px:.1f},{py:.1f}" for px, py in projected)
    parts.append(
        f'<polyline points="{points_attr}" fill="none" '
        f'stroke="{html.escape(stroke_color)}" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
    )

    # Markers — one circle per point with a <title> child for hover text.
    for (px, py), point in zip(projected, points, strict=True):
        parts.append(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.5" '
            f'fill="{html.escape(fill_color)}" stroke="white" stroke-width="1">'
            f"<title>{html.escape(point.label)}</title>"
            f"</circle>"
        )

    # Annotations: vertical dashed lines with rotated label at top.
    if annotations:
        for ann in annotations:
            ax = project_x(_to_ordinal(ann.x_value))
            # Clamp inside the plot so an out-of-range annotation doesn't
            # leak into the padding.
            if ax < plot_x0 or ax > plot_x1:
                continue
            parts.append(
                f'<line x1="{ax:.1f}" y1="{plot_y0}" x2="{ax:.1f}" y2="{plot_y1}" '
                f'stroke="#dc2626" stroke-width="1" stroke-dasharray="4,3"/>'
            )
            parts.append(
                f'<text x="{ax:.1f}" y="{plot_y0 + 2}" text-anchor="start" '
                f'transform="rotate(-60 {ax:.1f} {plot_y0 + 2})" '
                f'font-family="system-ui, sans-serif" font-size="9" '
                f'fill="#991b1b">{html.escape(ann.label)}</text>'
            )

    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Convenience wrappers for WTN / ranking trajectories
# ---------------------------------------------------------------------------


def render_wtn_trajectory_svg(
    snapshots: list[WTNSnapshot],
    *,
    width: int = 640,
    height: int = 200,
    annotations: list[ChartAnnotation] | None = None,
) -> str:
    """Render a WTN-over-time chart.

    The y-axis is inverted because a *lower* WTN value indicates a stronger
    player — viewers expect "up = better".
    """
    points = [
        ChartPoint(
            x_value=s.as_of,
            y_value=float(s.value),
            label=f"{s.as_of.isoformat()}: WTN {s.value:.1f}",
        )
        for s in sorted(snapshots, key=lambda s: s.as_of)
    ]
    return render_line_chart(
        points,
        width=width,
        height=height,
        y_inverted=True,
        title="WTN trajectory",
        y_label="WTN",
        fill_color="#16a34a",
        stroke_color="#15803d",
        annotations=annotations,
        y_integer_ticks=False,
    )


def render_ranking_trajectory_svg(
    snapshots: list[RankingSnapshot],
    *,
    width: int = 640,
    height: int = 200,
    annotations: list[ChartAnnotation] | None = None,
) -> str:
    """Render a ranking-position-over-time chart.

    Position (rank) is also inverted: ``#1`` belongs at the top. Snapshots
    whose ``position`` is ``None`` (an unranked listing) are skipped — there
    is no sensible y-value to plot for them.
    """
    filtered = [s for s in snapshots if s.position is not None]
    points = [
        ChartPoint(
            x_value=s.as_of,
            y_value=float(s.position) if s.position is not None else 0.0,
            label=f"{s.as_of.isoformat()}: #{s.position} ({s.category})",
        )
        for s in sorted(filtered, key=lambda s: s.as_of)
    ]
    return render_line_chart(
        points,
        width=width,
        height=height,
        y_inverted=True,
        title="Ranking trajectory",
        y_label="Position",
        fill_color="#7c3aed",
        stroke_color="#5b21b6",
        annotations=annotations,
        y_integer_ticks=True,
    )


# ---------------------------------------------------------------------------
# Win/loss monthly sparkline
# ---------------------------------------------------------------------------


def _month_key(d: date) -> tuple[int, int]:
    """Return a ``(year, month)`` tuple suitable for grouping/sorting."""
    return (d.year, d.month)


def _month_label(year: int, month: int) -> str:
    """Render a month tuple as ``Mon YYYY`` for the sparkline tooltip."""
    return date(year, month, 1).strftime("%b %Y")


def _prev_month(year: int, month: int) -> tuple[int, int]:
    """Step one calendar month backward, handling the January→December wrap."""
    if month == 1:
        return year - 1, 12
    return year, month - 1


def render_win_loss_sparkline(
    matches_chronological: list[tuple[date, bool]],
    *,
    width: int = 320,
    height: int = 32,
    today: date | None = None,
) -> str:
    """Render a 12-cell monthly win/loss sparkline.

    Each cell represents one calendar month, with the **rightmost cell** the
    current month. Cells with no recorded matches render as light grey; cells
    with matches render green (>=50% win rate) or red (<50%), with opacity
    scaling from 0.4 (one match) up to 1.0 (five or more) so a busy month
    visually dominates a one-off.

    ``today`` is injectable for deterministic testing.
    """
    today = today or date.today()
    # Build the list of 12 month tuples, oldest first → newest last.
    months: list[tuple[int, int]] = []
    cursor = (today.year, today.month)
    for _ in range(12):
        months.append(cursor)
        cursor = _prev_month(*cursor)
    months.reverse()  # oldest → newest

    # Bucket matches by month. Counter keys on (year, month, won?) and
    # produces fast totals without re-walking the list per month.
    bucket: Counter[tuple[int, int, bool]] = Counter()
    for d, won in matches_chronological:
        bucket[(d.year, d.month, won)] += 1

    n = 12
    cell_w = width / n
    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Monthly win-loss sparkline">'
    )

    for i, (yr, mo) in enumerate(months):
        wins = bucket[(yr, mo, True)]
        losses = bucket[(yr, mo, False)]
        total = wins + losses
        x = i * cell_w
        if total == 0:
            color = "#e5e7eb"
            opacity = 1.0
            tooltip = f"{_month_label(yr, mo)}: no matches"
        else:
            rate = wins / total
            color = "#16a34a" if rate >= 0.5 else "#dc2626"
            # 1 match → 0.4, 5+ matches → 1.0, linear in between.
            opacity = min(1.0, 0.4 + (total - 1) * 0.15)
            pct = round(rate * 100)
            tooltip = f"{_month_label(yr, mo)}: {wins}-{losses} ({pct}%)"
        # Tiny inset to draw visible inter-cell gutters.
        rx = max(0, x + 1)
        rw = max(0, cell_w - 2)
        parts.append(
            f'<rect x="{rx:.2f}" y="2" width="{rw:.2f}" height="{height - 4}" '
            f'fill="{color}" fill-opacity="{opacity:.2f}" rx="2" ry="2">'
            f"<title>{html.escape(tooltip)}</title>"
            f"</rect>"
        )

    parts.append("</svg>")
    return "".join(parts)


__all__ = [
    "ChartAnnotation",
    "ChartPoint",
    "render_line_chart",
    "render_ranking_trajectory_svg",
    "render_win_loss_sparkline",
    "render_wtn_trajectory_svg",
]
