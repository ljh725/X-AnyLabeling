"""Pure helpers for discrete rectangle-edge refinement commands."""

from __future__ import annotations

from dataclasses import dataclass
from math import copysign
from typing import Hashable


@dataclass(frozen=True)
class NudgeCommand:
    """One accepted edge movement in image-pixel space."""

    edge: str
    direction: int
    pixels: int
    source: str


class WheelAccumulator:
    """Normalize high- and low-resolution wheel input into full notches."""

    def __init__(self, pixels_per_notch: float = 120.0) -> None:
        """Initialize an accumulator with the Qt angleDelta convention."""
        self.pixels_per_notch = max(float(pixels_per_notch), 1.0)
        self._remainder = 0.0

    def add(self, angle_delta: float = 0.0, pixel_delta: float = 0.0) -> int:
        """Return signed complete notches and retain a partial remainder."""
        raw = float(angle_delta) if angle_delta else float(pixel_delta)
        if angle_delta:
            raw /= 120.0
        else:
            raw /= self.pixels_per_notch
        self._remainder += raw
        notches = int(self._remainder)
        self._remainder -= notches
        return notches

    def reset(self) -> None:
        """Discard a partial wheel notch."""
        self._remainder = 0.0


class NudgeBurstTracker:
    """Group compatible nudges into one undo burst."""

    def __init__(self, burst_seconds: float = 0.5) -> None:
        """Initialize an empty tracker."""
        self.burst_seconds = max(float(burst_seconds), 0.0)
        self._key: Hashable | None = None
        self._timestamp: float | None = None

    def begin(self, key: Hashable, timestamp: float) -> bool:
        """Return true when ``key`` starts a new undo burst."""
        now = float(timestamp)
        is_new = (
            self._key != key
            or self._timestamp is None
            or now - self._timestamp > self.burst_seconds
        )
        self._key = key
        self._timestamp = now
        return is_new

    def reset(self) -> None:
        """End the current burst explicitly."""
        self._key = None
        self._timestamp = None


def nudge_delta(edge: str, direction: int, pixels: int) -> tuple[float, float]:
    """Return an axis-aligned image delta for an edge command."""
    signed = copysign(float(abs(int(pixels))), 1 if direction >= 0 else -1)
    if edge in ("left", "right"):
        return signed, 0.0
    if edge in ("top", "bottom"):
        return 0.0, signed
    raise ValueError(f"Unsupported rectangle edge: {edge!r}")


def valid_edge_nudge(
    bbox: tuple[float, float, float, float],
    edge: str,
    direction: int,
    pixels: int,
    image_size: tuple[float, float],
    min_size: float = 1.0,
) -> bool:
    """Check bounds, minimum size and non-flip constraints before applying."""
    x_min, y_min, x_max, y_max = bbox
    width, height = image_size
    dx, dy = nudge_delta(edge, direction, pixels)
    if edge == "left":
        x_min += dx
    elif edge == "right":
        x_max += dx
    elif edge == "top":
        y_min += dy
    else:
        y_max += dy
    return (
        0.0 <= x_min < x_max <= width - 1
        and 0.0 <= y_min < y_max <= height - 1
        and x_max - x_min >= min_size
        and y_max - y_min >= min_size
    )
