"""Pure geometry for fitting one rectangle corner to a point."""

from __future__ import annotations

import math
from dataclasses import dataclass

Box = tuple[float, float, float, float]
Point = tuple[float, float]

INSIDE_BAND_SCREEN_PX = 1.0
OUTSIDE_BAND_SCREEN_PX = 8.0
HOVER_SWITCH_SCREEN_PX = 3.0

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
    box: Box,
    point: Point,
    scale: float = 1.0,
    *,
    previous_corner: str | None = None,
) -> ClickDecision:
    """Acquire a quadrant, then resist small movements across its centre.

    A fresh gesture still rejects the centre band. Once a corner is known,
    each axis keeps its previous side until the pointer clearly crosses the
    centre. Cap that margin for tiny rectangles so every side stays reachable.
    """
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
    if previous_corner in OPPOSITE_CORNER:
        vertical, horizontal = previous_corner.split("_")
        switch_band = max(band, HOVER_SWITCH_SCREEN_PX)
        switch_x = min(switch_band, (right - left) * scale / 4) / scale
        switch_y = min(switch_band, (bottom - top) * scale / 4) / scale
        if abs(x - cx) > switch_x:
            horizontal = "left" if x < cx else "right"
        if abs(y - cy) > switch_y:
            vertical = "top" if y < cy else "bottom"
        return ClickDecision(f"{vertical}_{horizontal}")
    if abs(x - cx) <= band_x or abs(y - cy) <= band_y:
        return ClickDecision(None, "dead_zone")
    horizontal = "left" if x < cx else "right"
    vertical = "top" if y < cy else "bottom"
    return ClickDecision(f"{vertical}_{horizontal}")


def point_fit_inside_box(box: Box, point: Point) -> bool:
    """Return whether a point is strictly inside a usable rectangle.

    Points on the outline are excluded: a Shift press there enters the
    original point-fit flow instead of locking a corner.
    """
    left, top, right, bottom = box
    if (
        not all(math.isfinite(value) for value in box)
        or right <= left
        or bottom <= top
    ):
        return False
    x, y = point
    if not all(math.isfinite(value) for value in point):
        return False
    return left < x < right and top < y < bottom


def point_fit_lock_decision(
    box: Box,
    point: Point,
    scale: float = 1.0,
) -> ClickDecision:
    """Return the initial moving-corner region, or why it still waits.

    The strict inside test keeps edge and outside presses in the original
    flow; the shared centre buffer then leaves the corner undecided until
    the pointer reaches one clear quadrant.
    """
    if not point_fit_inside_box(box, point):
        return ClickDecision(None, "outside")
    return point_fit_decision(box, point, scale)


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
