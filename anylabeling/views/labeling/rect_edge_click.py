"""Classify finite rectangle click regions without depending on Qt."""

from __future__ import annotations

import math
from dataclasses import dataclass

Box = tuple[float, float, float, float]
Point = tuple[float, float]

# Trial values: outer width/height multiplier and screen-space band half-width.
EFFECTIVE_RANGE_FACTOR = 3.0
DEAD_BAND_SCREEN_PX = 6.0
DEAD_BAND_SHORT_SIDE_CAP = 0.05
POINT_FIT_DEAD_BAND_SCREEN_PX = 8.0
REASON_DEAD_ZONE = "dead_zone"
REASON_OUT_OF_RANGE = "out_of_range"
REASON_INVALID_BOX = "invalid_box"


def classify_axis(box: Box, point: Point, axis: str) -> ClickDecision:
    """Classify a click by the selected axis and the box center half.

    The axis shortcut deliberately removes the old edge hit area and center
    dead-zone: X selects left/right from the committed center, while Y selects
    top/bottom.  The caller still validates image bounds and minimum size.
    """
    left, top, right, bottom = box
    if (
        axis not in {"x", "y"}
        or not all(math.isfinite(value) for value in box)
        or right <= left
        or bottom <= top
    ):
        return ClickDecision(None, REASON_INVALID_BOX)
    x, y = point
    if axis == "x":
        return ClickDecision("left" if x <= (left + right) / 2 else "right")
    return ClickDecision("top" if y <= (top + bottom) / 2 else "bottom")


@dataclass(frozen=True)
class ClickDecision:
    """Identify one edge, or explain why the point cannot select an edge."""

    edge: str | None
    reason: str | None = None


def effective_box(box: Box) -> Box:
    """Return the concentric outer box with the original aspect ratio."""
    left, top, right, bottom = box
    cx, cy = (left + right) / 2, (top + bottom) / 2
    dx = (right - left) * EFFECTIVE_RANGE_FACTOR / 2
    dy = (bottom - top) * EFFECTIVE_RANGE_FACTOR / 2
    return cx - dx, cy - dy, cx + dx, cy + dy


def dead_band_half_width(box: Box, scale: float) -> float:
    """Convert the screen band to image units, capped for small rectangles."""
    left, top, right, bottom = box
    if not math.isfinite(scale) or scale <= 0:
        scale = 1.0
    return min(
        DEAD_BAND_SCREEN_PX / scale,
        DEAD_BAND_SHORT_SIDE_CAP * min(right - left, bottom - top),
    )


def classify(box: Box, point: Point, scale: float = 1.0) -> ClickDecision:
    """Select a side using normalized offsets and finite diagonal bands.

    Args:
        box: Original left, top, right and bottom image coordinates.
        point: Click position in image coordinates.
        scale: Display pixels per image pixel.

    Returns:
        One edge name, or an invalid-box, out-of-range or dead-zone reason.
    """
    left, top, right, bottom = box
    if (
        not all(math.isfinite(value) for value in box)
        or right <= left
        or bottom <= top
    ):
        return ClickDecision(None, REASON_INVALID_BOX)
    x, y = point
    outer = effective_box(box)
    if not (outer[0] <= x <= outer[2] and outer[1] <= y <= outer[3]):
        return ClickDecision(None, REASON_OUT_OF_RANGE)
    a, b = (right - left) / 2, (bottom - top) / 2
    px, py = x - (left + right) / 2, y - (top + bottom) / 2
    distance = min(abs(px * b - py * a), abs(px * b + py * a))
    if distance / math.hypot(a, b) <= dead_band_half_width(box, scale):
        return ClickDecision(None, REASON_DEAD_ZONE)
    u, v = px / a, py / b
    if abs(u) > abs(v):
        return ClickDecision("right" if u > 0 else "left")
    return ClickDecision("bottom" if v > 0 else "top")


def proposed_box(box: Box, edge: str, point: Point) -> Box:
    """Replace exactly one coordinate without rounding or clamping."""
    index = ("left", "top", "right", "bottom").index(edge)
    coordinates = list(box)
    coordinates[index] = point[index % 2]
    return tuple(coordinates)


def proposed_corner_box(box: Box, corner: int, point: Point) -> Box:
    """Move the explicitly selected canonical corner without flipping it."""
    horizontal, vertical = (
        ("left", "top"),
        ("right", "top"),
        ("right", "bottom"),
        ("left", "bottom"),
    )[corner]
    return proposed_box(proposed_box(box, horizontal, point), vertical, point)


def point_fit_decision(
    box: Box, point: Point, scale: float = 1.0
) -> ClickDecision:
    """Infer a corner from a point relative to the rectangle center.

    The center horizontal and vertical bands are intentionally ambiguous: a
    point in either band does not provide enough information to infer a unique
    corner, so the caller should show a preview but reject the commit.

    Args:
        box: Original left, top, right and bottom image coordinates.
        point: Candidate point in image coordinates.
        scale: Display pixels per image pixel.

    Returns:
        A canonical corner name (``top_left`` etc.), or a reason when the
        point cannot determine one safely.
    """
    left, top, right, bottom = box
    if (
        not all(math.isfinite(value) for value in box)
        or right <= left
        or bottom <= top
    ):
        return ClickDecision(None, REASON_INVALID_BOX)
    x, y = point
    if not all(math.isfinite(value) for value in point):
        return ClickDecision(None, REASON_DEAD_ZONE)
    if not math.isfinite(scale) or scale <= 0:
        scale = 1.0
    # Keep this tolerance in screen pixels so zooming does not change the
    # interaction feel.  Very small rectangles may therefore be entirely
    # ambiguous, which is safer than silently selecting the wrong corner.
    half_band = POINT_FIT_DEAD_BAND_SCREEN_PX / scale
    cx, cy = (left + right) / 2, (top + bottom) / 2
    if abs(x - cx) <= half_band or abs(y - cy) <= half_band:
        return ClickDecision(None, REASON_DEAD_ZONE)
    horizontal = "left" if x < cx else "right"
    vertical = "top" if y < cy else "bottom"
    return ClickDecision(f"{vertical}_{horizontal}")


def proposed_point_fit_box(box: Box, corner: str, point: Point) -> Box:
    """Move the inferred corner to a point while fixing the opposite corner."""
    corners = {
        "top_left": 0,
        "top_right": 1,
        "bottom_right": 2,
        "bottom_left": 3,
    }
    if corner not in corners:
        raise ValueError(f"Unknown point-fit corner: {corner}")
    return proposed_corner_box(box, corners[corner], point)
