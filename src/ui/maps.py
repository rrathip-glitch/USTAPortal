"""Pure-SVG map renderers for the tournament-locations view.

Two helpers in this module:

* :func:`render_florida_map_svg` — outline of Florida with markers.
* :func:`render_us_map_svg` — bounding-box rectangle of the continental US
  with markers.

Both use an equirectangular projection (lon → x, lat → y, y flipped so
north sits at the top of the canvas) and pure SVG primitives — no external
libraries, no JavaScript. The Florida outline is approximated by a
hand-picked polyline of ~17 points; rough but recognizable.

User-supplied label strings are HTML-escaped before being written into
``<text>`` or ``<title>`` nodes so an adversarial label cannot break the
SVG document.
"""

from __future__ import annotations

import html
from dataclasses import dataclass


@dataclass(frozen=True)
class MapMarker:
    """One pin on the map.

    ``lat`` / ``lon`` are projected via the active map's bounding box.
    ``color`` accepts any valid CSS color string; the project's default is
    blue (``#1d4ed8``).
    """

    lat: float
    lon: float
    label: str
    color: str = "#1d4ed8"


# Approximate bounding boxes used by the equirectangular projection. The
# Florida box was chosen wide enough to fit the panhandle without
# squashing the peninsula vertically; the US box is the conventional
# "continental 48" frame.
FL_BBOX_SOUTH = 24.396308
FL_BBOX_NORTH = 31.000968
FL_BBOX_WEST = -87.634938
FL_BBOX_EAST = -79.974307

US_BBOX_SOUTH = 24.0
US_BBOX_NORTH = 50.0
US_BBOX_WEST = -125.0
US_BBOX_EAST = -66.0


# Hand-picked polyline of Florida's outline, panhandle → east coast → keys
# → west coast → panhandle. Coarse but recognizable; closes back on the
# starting point so the resulting SVG path can be Z-closed.
_FLORIDA_OUTLINE: list[tuple[float, float]] = [
    (31.00, -87.50),
    (31.00, -85.00),
    (30.80, -82.00),
    (30.40, -81.45),
    (29.10, -80.90),
    (27.50, -80.05),
    (25.80, -80.10),
    (25.30, -80.50),
    (25.10, -81.10),
    (26.10, -81.80),
    (27.60, -82.65),
    (29.10, -83.10),
    (29.90, -84.30),
    (30.20, -85.00),
    (30.40, -86.50),
    (30.80, -87.40),
    (31.00, -87.50),
]


def _project(
    lat: float,
    lon: float,
    *,
    bbox_south: float,
    bbox_north: float,
    bbox_west: float,
    bbox_east: float,
    width: int,
    height: int,
) -> tuple[float, float]:
    """Map (lat, lon) → (x, y) using an equirectangular projection.

    Latitude is flipped so the northernmost value lands at ``y=0``. The
    function does no clipping; markers outside the bounding box render at
    negative or out-of-canvas coordinates and the caller decides whether
    to keep them.
    """
    x = (lon - bbox_west) / (bbox_east - bbox_west) * width
    y = (bbox_north - lat) / (bbox_north - bbox_south) * height
    return x, y


def _outline_path(
    points: list[tuple[float, float]],
    *,
    bbox_south: float,
    bbox_north: float,
    bbox_west: float,
    bbox_east: float,
    width: int,
    height: int,
) -> str:
    """Build an SVG ``d`` attribute from projected (lat, lon) vertices."""
    segments: list[str] = []
    for i, (lat, lon) in enumerate(points):
        x, y = _project(
            lat,
            lon,
            bbox_south=bbox_south,
            bbox_north=bbox_north,
            bbox_west=bbox_west,
            bbox_east=bbox_east,
            width=width,
            height=height,
        )
        cmd = "M" if i == 0 else "L"
        segments.append(f"{cmd}{x:.1f},{y:.1f}")
    segments.append("Z")
    return " ".join(segments)


def _marker_svg(
    marker: MapMarker,
    *,
    bbox_south: float,
    bbox_north: float,
    bbox_west: float,
    bbox_east: float,
    width: int,
    height: int,
) -> str:
    """Render one marker as an ``<g>`` containing a ``<circle>`` and a label.

    The circle carries a ``<title>`` child (SVG's native tooltip) and a
    sibling ``<text>`` shows the label to the right of the dot. Both
    label strings are HTML-escaped.
    """
    cx, cy = _project(
        marker.lat,
        marker.lon,
        bbox_south=bbox_south,
        bbox_north=bbox_north,
        bbox_west=bbox_west,
        bbox_east=bbox_east,
        width=width,
        height=height,
    )
    safe_label = html.escape(marker.label)
    safe_color = html.escape(marker.color)
    return (
        f'<g class="map-marker">'
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5" '
        f'fill="{safe_color}" stroke="white" stroke-width="1.5">'
        f"<title>{safe_label}</title>"
        f"</circle>"
        f'<text x="{cx + 8:.1f}" y="{cy + 4:.1f}" '
        f'font-family="system-ui, sans-serif" font-size="12" '
        f'fill="#0f172a">{safe_label}</text>'
        f"</g>"
    )


def render_florida_map_svg(
    markers: list[MapMarker], *, width: int = 640, height: int = 480
) -> str:
    """Render Florida's outline plus markers as an SVG string.

    The outline is a single hand-picked polyline (see
    ``_FLORIDA_OUTLINE``). Markers are projected with an equirectangular
    transform using the Florida bounding box from the module constants.
    """
    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Florida tournament map">'
    )
    parts.append(
        f'<rect x="0" y="0" width="{width}" height="{height}" '
        f'fill="#f0f9ff"/>'
    )
    path_d = _outline_path(
        _FLORIDA_OUTLINE,
        bbox_south=FL_BBOX_SOUTH,
        bbox_north=FL_BBOX_NORTH,
        bbox_west=FL_BBOX_WEST,
        bbox_east=FL_BBOX_EAST,
        width=width,
        height=height,
    )
    parts.append(
        f'<path d="{path_d}" fill="#bae6fd" stroke="#0369a1" stroke-width="1.5"/>'
    )
    for marker in markers:
        parts.append(
            _marker_svg(
                marker,
                bbox_south=FL_BBOX_SOUTH,
                bbox_north=FL_BBOX_NORTH,
                bbox_west=FL_BBOX_WEST,
                bbox_east=FL_BBOX_EAST,
                width=width,
                height=height,
            )
        )
    parts.append("</svg>")
    return "".join(parts)


def render_us_map_svg(
    markers: list[MapMarker], *, width: int = 640, height: int = 360
) -> str:
    """Render a continental-US bounding-box rectangle plus markers as SVG.

    The outline is a plain rectangle (no state borders) — recognisable
    enough for a low-detail overview and trivially cheap to draw. Markers
    are projected with an equirectangular transform using the
    ``US_BBOX_*`` constants.
    """
    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="US tournament map">'
    )
    parts.append(
        f'<rect x="0" y="0" width="{width}" height="{height}" '
        f'fill="#f0f9ff"/>'
    )
    # Outline rectangle covers the entire canvas because the bounding box
    # *is* the canvas — a margin would mean the projection should also be
    # padded, which adds complexity for a low-detail map.
    parts.append(
        f'<rect x="0" y="0" width="{width}" height="{height}" '
        f'fill="#bae6fd" stroke="#0369a1" stroke-width="1.5"/>'
    )
    for marker in markers:
        parts.append(
            _marker_svg(
                marker,
                bbox_south=US_BBOX_SOUTH,
                bbox_north=US_BBOX_NORTH,
                bbox_west=US_BBOX_WEST,
                bbox_east=US_BBOX_EAST,
                width=width,
                height=height,
            )
        )
    parts.append("</svg>")
    return "".join(parts)


__all__ = ["MapMarker", "render_florida_map_svg", "render_us_map_svg"]
