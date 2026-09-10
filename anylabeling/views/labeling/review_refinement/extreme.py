"""Image-coordinate models for extreme-point creation and observation."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite

EDGES = ("top", "right", "bottom", "left")


@dataclass
class ExtremeDraft:
    """Collect four axis-specific boundaries without creating Shapes."""

    width: float
    height: float
    points: list[tuple[float, float]] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """Return whether all four boundaries were accepted."""
        return len(self.points) == 4

    @property
    def edge(self) -> str | None:
        """Return the next boundary name."""
        return None if self.complete else EDGES[len(self.points)]

    def accept(self, x: float, y: float) -> bool:
        """Accept a valid point, leaving the draft intact on rejection."""
        if self.complete or not all(isfinite(v) for v in (x, y)):
            return False
        if not (0 <= x <= self.width - 1 and 0 <= y <= self.height - 1):
            return False
        if len(self.points) == 2 and y - self.points[0][1] < 1:
            return False
        if len(self.points) == 3 and self.points[1][0] - x < 1:
            return False
        self.points.append((float(x), float(y)))
        return True

    def back(self) -> None:
        """Remove the most recently confirmed boundary, if any."""
        if self.points:
            self.points.pop()

    def bbox(self) -> tuple[float, float, float, float]:
        """Return the completed rectangle without rounding coordinates."""
        if not self.complete:
            raise ValueError("Four boundaries are required")
        return (
            self.points[3][0],
            self.points[0][1],
            self.points[1][0],
            self.points[2][1],
        )


def observation_view(
    bbox: tuple[float, float, float, float],
    image_size: tuple[float, float],
    viewport_size: tuple[float, float],
    target_pixels: float = 400,
    max_scale: float = 8,
) -> tuple[int, float, float]:
    """Return zoom percent and center while fitting surrounding context."""
    left, top, right, bottom = bbox
    width, height = image_size
    view_w, view_h = viewport_size
    values = (*bbox, *image_size, *viewport_size, target_pixels, max_scale)
    if not all(isfinite(v) for v in values):
        raise ValueError("Observation coordinates must be finite")
    if not (
        0 <= left < right <= width - 1
        and 0 <= top < bottom <= height - 1
        and min(view_w, view_h, target_pixels, max_scale) > 0
    ):
        raise ValueError("Invalid observation geometry")
    pad_x = max((right - left) * 0.25, 16)
    pad_y = max((bottom - top) * 0.25, 16)
    x1, x2 = max(0, left - pad_x), min(width, right + pad_x)
    y1, y2 = max(0, top - pad_y), min(height, bottom + pad_y)
    scale = min(
        target_pixels / max(right - left, bottom - top),
        max_scale,
        view_w / (x2 - x1),
        view_h / (y2 - y1),
    )
    return max(1, int(scale * 100)), (x1 + x2) / 2, (y1 + y2) / 2
