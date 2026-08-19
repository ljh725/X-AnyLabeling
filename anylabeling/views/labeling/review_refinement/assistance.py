"""Pure, request-only helpers for optional rectangle-edge assistance."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Callable, Sequence


@dataclass(frozen=True)
class LoupeROI:
    """Read-only image ROI around an active edge."""

    x: int
    y: int
    width: int
    height: int
    center_x: float
    center_y: float


def build_loupe_roi(
    center: tuple[float, float],
    image_size: tuple[int, int],
    radius_px: int = 16,
) -> LoupeROI:
    """Return a bounded ROI without changing image/canvas coordinates."""
    image_width, image_height = image_size
    radius = max(1, int(radius_px))
    diameter = radius * 2 + 1
    x = max(0, min(int(round(center[0])) - radius, image_width - diameter))
    y = max(0, min(int(round(center[1])) - radius, image_height - diameter))
    return LoupeROI(
        x=x,
        y=y,
        width=min(diameter, image_width),
        height=min(diameter, image_height),
        center_x=float(center[0]),
        center_y=float(center[1]),
    )


@dataclass(frozen=True)
class EdgeCandidate:
    """Non-mutating edge candidate preview."""

    edge: str
    coordinate: float
    offset: float
    confidence: float


class EdgeCandidateService:
    """Compute candidates only when the caller explicitly requests one."""

    def request(
        self,
        edge: str,
        samples: Sequence[float],
        baseline_coordinate: float,
        sample_spacing: float = 1.0,
    ) -> EdgeCandidate | None:
        """Return the strongest adjacent-sample transition, if any."""
        if len(samples) < 2:
            return None
        spacing = max(float(sample_spacing), 1e-6)
        differences = [
            abs(float(right) - float(left))
            for left, right in zip(samples, samples[1:])
        ]
        strongest = max(differences)
        if strongest <= 0:
            return None
        index = differences.index(strongest)
        offset = (index + 0.5) * spacing
        confidence = min(
            1.0, strongest / (sum(differences) / len(differences))
        )
        return EdgeCandidate(
            edge=edge,
            coordinate=float(baseline_coordinate) + offset,
            offset=offset,
            confidence=confidence,
        )


class CandidatePreviewController:
    """Hold a candidate preview until explicit accept/reject/cancel."""

    def __init__(self) -> None:
        """Initialize an empty preview transaction."""
        self.preview: EdgeCandidate | None = None

    def show(self, candidate: EdgeCandidate) -> None:
        """Show a candidate without mutating a shape."""
        self.preview = candidate

    def reject(self) -> None:
        """Discard the current candidate preview."""
        self.preview = None

    def accept(
        self,
        validator: Callable[[EdgeCandidate], bool],
        commit: Callable[[EdgeCandidate], None],
    ) -> bool:
        """Validate and commit once, returning whether the transaction changed."""
        candidate = self.preview
        if candidate is None or not validator(candidate):
            return False
        commit(candidate)
        self.preview = None
        return True


def distance_between(
    first: tuple[float, float], second: tuple[float, float]
) -> float:
    """Return Euclidean distance for overlay placement tests."""
    return hypot(first[0] - second[0], first[1] - second[1])
