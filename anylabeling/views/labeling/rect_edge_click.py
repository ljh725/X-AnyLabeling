"""Pure geometry for fitting one rectangle corner to a point."""

from __future__ import annotations

import math
from dataclasses import dataclass

Box = tuple[float, float, float, float]
Point = tuple[float, float]

INSIDE_BAND_SCREEN_PX = 1.0
OUTSIDE_BAND_SCREEN_PX = 8.0


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
    inside = left <= x <= right and top <= y <= bottom
    band = INSIDE_BAND_SCREEN_PX if inside else OUTSIDE_BAND_SCREEN_PX
    cx, cy = (left + right) / 2, (top + bottom) / 2
    if abs(x - cx) <= band / scale or abs(y - cy) <= band / scale:
        return ClickDecision(None, "dead_zone")
    horizontal = "left" if x < cx else "right"
    vertical = "top" if y < cy else "bottom"
    return ClickDecision(f"{vertical}_{horizontal}")


def proposed_point_fit_box(box: Box, corner: str, point: Point) -> Box:
    """Move the named corner to the point, keeping its opposite fixed."""
    left, top, right, bottom = box
    x, y = point
    if corner == "top_left":
        return x, y, right, bottom
    if corner == "top_right":
        return left, y, x, bottom
    if corner == "bottom_right":
        return left, top, x, y
    if corner == "bottom_left":
        return x, top, right, y
    raise ValueError(f"Unknown point-fit corner: {corner}")
