"""Classify finite rectangle click regions without depending on Qt."""

import math
from dataclasses import dataclass

Box = tuple[float, float, float, float]
Point = tuple[float, float]

# Trial values: outer width/height multiplier and screen-space band half-width.
EFFECTIVE_RANGE_FACTOR = 2.0
DEAD_BAND_SCREEN_PX = 6.0
DEAD_BAND_SHORT_SIDE_CAP = 0.05
REASON_DEAD_ZONE = "dead_zone"
REASON_OUT_OF_RANGE = "out_of_range"
REASON_INVALID_BOX = "invalid_box"


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
