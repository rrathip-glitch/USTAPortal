"""Unit tests for the SVG map renderers in :mod:`src.ui.maps`."""

from __future__ import annotations

import re

from src.ui.maps import MapMarker, render_florida_map_svg, render_us_map_svg


def test_florida_map_with_no_markers_contains_svg_and_outline_path() -> None:
    svg = render_florida_map_svg([])
    assert "<svg" in svg
    # The Florida outline is rendered as a <path>.
    assert "<path" in svg
    # No marker circles when no markers were supplied.
    assert "<circle" not in svg


def test_florida_map_one_marker_inside_canvas() -> None:
    # (27.66, -81.52) is roughly central Florida and should project inside
    # the default 640x480 canvas.
    width, height = 640, 480
    svg = render_florida_map_svg(
        [MapMarker(lat=27.66, lon=-81.52, label="Central FL")],
        width=width,
        height=height,
    )
    match = re.search(r'<circle\s+cx="([\d.]+)"\s+cy="([\d.]+)"', svg)
    assert match is not None
    cx = float(match.group(1))
    cy = float(match.group(2))
    assert 0 <= cx <= width
    assert 0 <= cy <= height


def test_florida_map_label_appears_in_text_and_title() -> None:
    svg = render_florida_map_svg(
        [MapMarker(lat=27.66, lon=-81.52, label="Central FL")]
    )
    # The label must appear inside a <text> element (sibling of the circle).
    assert re.search(r"<text[^>]*>Central FL</text>", svg) is not None
    # And inside a <title> element (child of the circle, for native
    # tooltip support).
    assert "<title>Central FL</title>" in svg


def test_us_map_renders_markers_in_different_states() -> None:
    markers = [
        MapMarker(lat=27.66, lon=-81.52, label="Florida"),  # FL
        MapMarker(lat=40.71, lon=-74.00, label="New York"),  # NY
        MapMarker(lat=34.05, lon=-118.24, label="Los Angeles"),  # CA
    ]
    svg = render_us_map_svg(markers)
    assert svg.count("<circle") == 3
    for label in ("Florida", "New York", "Los Angeles"):
        assert label in svg


def test_map_escapes_html_in_label() -> None:
    adversarial = "<script>alert(1)</script>"
    svg = render_florida_map_svg(
        [MapMarker(lat=27.66, lon=-81.52, label=adversarial)]
    )
    # The raw script tag must NOT appear (it would break the SVG).
    assert "<script>" not in svg
    # The escaped form must appear.
    assert "&lt;script&gt;" in svg
