"""Unit tests for the SVG chart helpers in :mod:`src.ui.charts`.

These tests pin the contract that the follow-up route agent depends on:

- A non-empty input renders a real ``<polyline>`` plus one ``<circle>`` per
  point.
- An empty input still renders an SVG (so the surrounding layout doesn't
  collapse), now with a centered "No data yet" label.
- The y-axis is inverted for WTN / ranking — verified by asserting the
  topmost y-tick label corresponds to the *smallest* value.
- ``ChartPoint.label`` text round-trips into a ``<title>`` element verbatim.
- The sparkline always emits 12 cells (one per month) regardless of data.

We avoid asserting on rendered pixel coordinates because the layout maths is
subject to minor padding tweaks; instead we assert on element counts and on
the presence of label text, which is what consumers actually rely on.
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from src.models.ranking import RankingSnapshot
from src.models.wtn import WTNSnapshot
from src.ui.charts import (
    ChartAnnotation,
    ChartPoint,
    render_line_chart,
    render_ranking_trajectory_svg,
    render_win_loss_sparkline,
    render_wtn_trajectory_svg,
)


def _count(svg: str, needle: str) -> int:
    """Count occurrences of ``needle`` in ``svg``.

    Avoids regex precedence surprises by using plain string counting — the
    fragments we look for (e.g. ``"<circle "``) are unambiguous in SVG.
    """
    return svg.count(needle)


# ---------------------------------------------------------------------------
# render_line_chart
# ---------------------------------------------------------------------------


def test_line_chart_five_points_emits_polyline_and_five_circles() -> None:
    points = [
        ChartPoint(x_value=date(2026, 1, 1), y_value=10.0, label="Jan"),
        ChartPoint(x_value=date(2026, 2, 1), y_value=12.0, label="Feb"),
        ChartPoint(x_value=date(2026, 3, 1), y_value=11.0, label="Mar"),
        ChartPoint(x_value=date(2026, 4, 1), y_value=9.0, label="Apr"),
        ChartPoint(x_value=date(2026, 5, 1), y_value=8.5, label="May"),
    ]
    svg = render_line_chart(points)
    assert "<svg" in svg
    assert "<polyline" in svg
    assert _count(svg, "<circle ") == 5


def test_line_chart_empty_renders_no_data_placeholder() -> None:
    svg = render_line_chart([])
    assert "<svg" in svg
    assert "No data yet" in svg
    # Still no polyline or circle markers in the empty state.
    assert "<polyline" not in svg
    assert "<circle " not in svg


def test_line_chart_respects_width_and_height_args() -> None:
    svg = render_line_chart(
        [ChartPoint(x_value=date(2026, 1, 1), y_value=5.0, label="A")],
        width=800,
        height=300,
    )
    assert 'width="800"' in svg
    assert 'height="300"' in svg
    assert 'viewBox="0 0 800 300"' in svg


def test_line_chart_empty_state_respects_width_and_height_args() -> None:
    # Even the empty placeholder must reserve the caller's requested size.
    svg = render_line_chart([], width=400, height=120)
    assert 'width="400"' in svg
    assert 'height="120"' in svg


def test_line_chart_annotations_render_dashed_line_and_label() -> None:
    points = [
        ChartPoint(x_value=date(2026, 1, 1), y_value=10.0, label="A"),
        ChartPoint(x_value=date(2026, 6, 1), y_value=12.0, label="B"),
    ]
    ann = ChartAnnotation(x_value=date(2026, 3, 15), label="Sectional start")
    svg = render_line_chart(points, annotations=[ann])
    assert "stroke-dasharray" in svg
    assert "Sectional start" in svg
    # The dashed annotation must be a <line>, not just the dotted gridlines
    # (the dashed-stroke attribute appears on multiple element types).
    assert re.search(r"<line[^>]*stroke-dasharray=\"4,3\"", svg) is not None


def test_chart_point_label_appears_verbatim_in_title_element() -> None:
    label = "2026-04-11: WTN 8.7"
    svg = render_line_chart(
        [ChartPoint(x_value=date(2026, 4, 11), y_value=8.7, label=label)]
    )
    assert f"<title>{label}</title>" in svg


def test_line_chart_escapes_html_in_labels_and_title() -> None:
    # An adversarial label must not break the SVG document.
    svg = render_line_chart(
        [ChartPoint(x_value=date(2026, 1, 1), y_value=5.0, label="A & <B>")],
        title="Title with <script>",
    )
    assert "A &amp; &lt;B&gt;" in svg
    assert "Title with &lt;script&gt;" in svg
    # And the raw form must NOT appear (the < inside the label would have
    # broken the parser if it had).
    assert "<script>" not in svg


def test_line_chart_long_title_renders_without_breaking_svg() -> None:
    long_title = "X" * 200
    points = [ChartPoint(x_value=date(2026, 1, 1), y_value=1.0, label="a")]
    svg = render_line_chart(points, title=long_title)
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert long_title in svg
    # Sanity check: tag balance — exactly one opening <svg.
    assert _count(svg, "<svg") == 1
    assert _count(svg, "</svg>") == 1


# ---------------------------------------------------------------------------
# WTN / ranking trajectories
# ---------------------------------------------------------------------------


def _y_tick_values(svg: str) -> list[float]:
    """Pull the numeric content of every y-axis tick label.

    The y-axis labels are rendered as ``<text ... text-anchor="end" ...
    dominant-baseline="middle" ...>NUMBER</text>``. We use ``text-anchor="end"``
    as the disambiguating attribute (x-axis ticks use ``"middle"``).
    """
    matches = re.findall(
        r'<text[^>]*text-anchor="end"[^>]*>([-\d.]+)</text>', svg
    )
    return [float(m) for m in matches]


def test_wtn_trajectory_is_y_inverted_so_top_label_is_smallest() -> None:
    # Lower WTN is better, so the top of the chart should display the
    # smallest value. Y-tick labels are emitted top→bottom, so the first
    # one in document order should be the minimum.
    snaps = [
        WTNSnapshot(player_id="P", type="singles", value=10.0, as_of=date(2026, 1, 1)),
        WTNSnapshot(player_id="P", type="singles", value=8.0, as_of=date(2026, 2, 1)),
        WTNSnapshot(player_id="P", type="singles", value=12.0, as_of=date(2026, 3, 1)),
    ]
    svg = render_wtn_trajectory_svg(snaps)
    ticks = _y_tick_values(svg)
    assert len(ticks) == 4
    # Ascending top→bottom == inverted axis (smaller-is-better at top).
    assert ticks == sorted(ticks)


def test_ranking_trajectory_is_y_inverted_and_uses_integer_ticks() -> None:
    snaps = [
        RankingSnapshot(
            player_id="P",
            category="Boys 16 Singles",
            scope="sectional",
            position=10,
            as_of=date(2026, 1, 1),
        ),
        RankingSnapshot(
            player_id="P",
            category="Boys 16 Singles",
            scope="sectional",
            position=5,
            as_of=date(2026, 2, 1),
        ),
        RankingSnapshot(
            player_id="P",
            category="Boys 16 Singles",
            scope="sectional",
            position=20,
            as_of=date(2026, 3, 1),
        ),
    ]
    svg = render_ranking_trajectory_svg(snaps)
    ticks = _y_tick_values(svg)
    assert len(ticks) == 4
    assert ticks == sorted(ticks)
    # Integer formatting — no decimal point in the rendered labels.
    label_matches = re.findall(
        r'<text[^>]*text-anchor="end"[^>]*>([^<]+)</text>', svg
    )
    for lbl in label_matches:
        assert "." not in lbl


def test_wtn_trajectory_empty_renders_placeholder() -> None:
    svg = render_wtn_trajectory_svg([])
    assert "No data yet" in svg


def test_ranking_trajectory_skips_snapshots_with_no_position() -> None:
    snaps = [
        RankingSnapshot(
            player_id="P",
            category="Cat",
            scope="sectional",
            position=None,
            as_of=date(2026, 1, 1),
        ),
        RankingSnapshot(
            player_id="P",
            category="Cat",
            scope="sectional",
            position=None,
            as_of=date(2026, 2, 1),
        ),
    ]
    # All filtered out → empty placeholder rendered.
    svg = render_ranking_trajectory_svg(snaps)
    assert "No data yet" in svg


# ---------------------------------------------------------------------------
# Sparkline
# ---------------------------------------------------------------------------


def test_sparkline_with_12_months_of_data_emits_12_cells_with_titles() -> None:
    today = date(2026, 5, 11)
    data: list[tuple[date, bool]] = []
    # One match per month for the last 12 months: alternate win/loss.
    cursor = today
    for i in range(12):
        # Use day=1 so the test isn't sensitive to month length.
        data.append((date(cursor.year, cursor.month, 1), i % 2 == 0))
        # Step back one month.
        y, m = cursor.year, cursor.month - 1
        if m == 0:
            y -= 1
            m = 12
        cursor = date(y, m, 1)
    svg = render_win_loss_sparkline(data, today=today)
    assert _count(svg, "<rect ") == 12
    assert _count(svg, "<title>") == 12


def test_sparkline_empty_emits_12_grey_cells() -> None:
    today = date(2026, 5, 11)
    svg = render_win_loss_sparkline([], today=today)
    assert _count(svg, "<rect ") == 12
    # Grey neutral color appears on every cell.
    assert svg.count("#e5e7eb") == 12
    # Every cell still carries a tooltip (with "no matches").
    assert svg.count("no matches") == 12


def test_sparkline_respects_width_and_height_args() -> None:
    svg = render_win_loss_sparkline([], width=480, height=48, today=date(2026, 5, 11))
    assert 'width="480"' in svg
    assert 'height="48"' in svg


def test_sparkline_tooltip_format_uses_record_and_percent() -> None:
    today = date(2026, 5, 11)
    # Three wins, one loss in May 2026 → "May 2026: 3-1 (75%)".
    data = [
        (date(2026, 5, 1), True),
        (date(2026, 5, 2), True),
        (date(2026, 5, 3), True),
        (date(2026, 5, 4), False),
    ]
    svg = render_win_loss_sparkline(data, today=today)
    assert "May 2026: 3-1 (75%)" in svg


def test_sparkline_intensity_scales_with_sample_size() -> None:
    today = date(2026, 5, 11)
    # One match in April, five matches in May (all wins). Opacity for the
    # one-match month should be lower than for the five-match month.
    data = [
        (date(2026, 4, 1), True),
        (date(2026, 5, 1), True),
        (date(2026, 5, 2), True),
        (date(2026, 5, 3), True),
        (date(2026, 5, 4), True),
        (date(2026, 5, 5), True),
    ]
    svg = render_win_loss_sparkline(data, today=today)
    # Pull the opacities in document order.
    opacities = [float(m) for m in re.findall(r'fill-opacity="([\d.]+)"', svg)]
    assert len(opacities) == 12
    # One-match April had opacity 0.40; five-match May should be 1.00.
    assert 0.39 < opacities[-2] < 0.41
    assert opacities[-1] == pytest.approx(1.0, abs=0.01)
