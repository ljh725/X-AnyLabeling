"""Pure geometry and mapping rules for discrete rectangle placement."""

from __future__ import annotations

from math import isfinite
from typing import Any

EDGES = ("top", "right", "bottom", "left")
BOUNDARY_KEYS = tuple(f"rectangle_place_{edge}" for edge in EDGES)
PRESETS = {"QWER": ("Q", "W", "E", "R"), "1234": ("1", "2", "3", "4")}


def drawing_method(mapping: dict[str, Any]) -> str:
    """Resolve a compatible rectangle method, rejecting unknown values."""
    if mapping.get("mode") != "rectangle":
        return "two_points"
    method = mapping.get("drawing_method", "two_points")
    if method not in ("two_points", "four_extremes"):
        raise ValueError("Unknown rectangle drawing method")
    return method


def placement_error(
    bbox: tuple[float, float, float, float],
    point: tuple[float, float],
    size: tuple[int, int],
    edge: str,
) -> str | None:
    """Return the rejection reason, or None for a legal one-edge placement."""
    left, top, right, bottom = bbox
    x, y = point
    width, height = size
    if not all(isfinite(v) for v in (*bbox, *point, *size)):
        return "invalid"
    if not (
        0 <= left < right <= width - 1
        and 0 <= top < bottom <= height - 1
        and right - left >= 1
        and bottom - top >= 1
    ):
        return "invalid"
    if not (0 <= x <= width - 1 and 0 <= y <= height - 1):
        return "pointer"
    allowed = {
        "top": y < (top + bottom) / 2,
        "right": x > (left + right) / 2,
        "bottom": y > (top + bottom) / 2,
        "left": x < (left + right) / 2,
    }
    if not allowed.get(edge, False):
        return "half"
    coords = dict(zip(("left", "top", "right", "bottom"), bbox))
    coords[edge] = y if edge in ("top", "bottom") else x
    if (
        coords["right"] - coords["left"] < 1
        or coords["bottom"] - coords["top"] < 1
    ):
        return "size"
    return None
