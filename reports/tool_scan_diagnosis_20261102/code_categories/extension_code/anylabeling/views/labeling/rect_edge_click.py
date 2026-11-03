"""Pure geometry for fitting one rectangle corner to a point."""

from __future__ import annotations

import math
from dataclasses import dataclass

Box = tuple[float, float, float, float]
Point = tuple[float, float]

INSIDE_BAND_SCREEN_PX = 1.0
OUTSIDE_BAND_SCREEN_PX = 8.0

OPPOSITE_CORNER = {
    "top_left": "bottom_right",
    "top_right": "bottom_left",
    "bottom_right": "top_left",
    "bottom_left": "top_right",
}


@dataclass(frozen=True)
class ClickDecision:
    """Identify a rectangle corner or explain an ambiguous input."""

    edge: str | None
    reason: str | None = None


def point_fit_decision(
    box: Box, point: Point, scale: float = 1.0
) -> ClickDecision:
    """Determine the corner using an inside/outside screen-pixel band."""
    left, top, right, bottom = box
    if (
        not all(math.isfinite(value) for value in box)
        or right <= left
        or bottom <= top
    ):
        return ClickDecision(None, "invalid_box")
    x, y = point
    if not all(math.isfinite(value) for value in point):
        return ClickDecision(None, "dead_zone")
    if not math.isfinite(scale) or scale <= 0:
        scale = 1.0
    outside = max(left - x, x - right, top - y, y - bottom, 0.0) * scale
    band = min(OUTSIDE_BAND_SCREEN_PX, INSIDE_BAND_SCREEN_PX + outside)
    band_x = min(band, (right - left) * scale / 4) / scale
    band_y = min(band, (bottom - top) * scale / 4) / scale
    cx, cy = (left + right) / 2, (top + bottom) / 2
    if abs(x - cx) <= band_x or abs(y - cy) <= band_y:
        return ClickDecision(None, "dead_zone")
    horizontal = "left" if x < cx else "right"
    vertical = "top" if y < cy else "bottom"
    return ClickDecision(f"{vertical}_{horizontal}")


def corner_point(box: Box, corner: str) -> Point:
    """Return the coordinates of one named corner of a box."""
    left, top, right, bottom = box
    if corner == "top_left":
        return left, top
    if corner == "top_right":
        return right, top
    if corner == "bottom_right":
        return right, bottom
    if corner == "bottom_left":
        return left, bottom
    raise ValueError(f"Unknown point-fit corner: {corner}")


def _span_corner_and_point(box: Box, corner: str, point: Point) -> Box:
    """Return the box spanned by one corner and the point."""
    anchor_x, anchor_y = corner_point(box, corner)
    x, y = point
    return (
        min(anchor_x, x),
        min(anchor_y, y),
        max(anchor_x, x),
        max(anchor_y, y),
    )


def proposed_point_fit_box(box: Box, corner: str, point: Point) -> Box:
    """Move the named corner to the point, keeping its opposite fixed."""
    if corner not in OPPOSITE_CORNER:
        raise ValueError(f"Unknown point-fit corner: {corner}")
    return _span_corner_and_point(box, OPPOSITE_CORNER[corner], point)


def proposed_inward_point_fit_box(box: Box, corner: str, point: Point) -> Box:
    """Keep the named corner fixed and move its opposite onto the point.

    This is the smaller of the two boxes an interior point can define: the
    default proposal keeps the far corner and therefore contains the box
    centre, while this one stays inside the quadrant that was clicked.
    """
    if corner not in OPPOSITE_CORNER:
        raise ValueError(f"Unknown point-fit corner: {corner}")
    return _span_corner_and_point(box, corner, point)
