"""Immutable data contracts for rectangle-size validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable, Literal, Optional, Tuple

BBox = Tuple[float, float, float, float]
CandidateId = Hashable
DimensionName = Literal["width", "height"]
TriggerMode = Literal["any", "all"]


@dataclass(frozen=True)
class RectangleSizeRule:
    """Minimum-size requirements for one rectangle label.

    Attributes:
        label: Exact, case-sensitive shape label matched by the rule.
        min_width_px: Optional width boundary in image pixels. Values less
            than or equal to it are abnormal.
        min_height_px: Optional height boundary in image pixels. Values less
            than or equal to it are abnormal.
        trigger_mode: Whether any or all configured dimensions must fail.
        enabled: Whether the rule participates in evaluation.
    """

    label: str
    min_width_px: Optional[float] = None
    min_height_px: Optional[float] = None
    trigger_mode: TriggerMode = "any"
    enabled: bool = True


@dataclass(frozen=True)
class RectangleCandidate:
    """Pure snapshot of one live shape considered for size validation.

    Attributes:
        candidate_id: Hashable identity used to reconnect results to a shape.
        shape_index: Stable ordering index within the current shape snapshot.
        label: Shape label used for exact rule matching.
        shape_type: Shape type; only rectangles are evaluated later.
        bbox: Normalized ``(x_min, y_min, x_max, y_max)`` in image pixels.
        interactive: Whether the shape is currently visible and interactive.
    """

    candidate_id: CandidateId
    shape_index: int
    label: str
    shape_type: str
    bbox: BBox
    interactive: bool = True


@dataclass(frozen=True)
class DimensionViolation:
    """One failed width or height threshold comparison.

    Attributes:
        dimension: The failed rectangle dimension.
        actual_px: Raw measured value in image pixels.
        threshold_px: Configured minimum threshold in image pixels.
    """

    dimension: DimensionName
    actual_px: float
    threshold_px: float


@dataclass(frozen=True)
class RectangleSizeIssue:
    """Aggregated dimension failures for one rectangle candidate.

    Attributes:
        candidate_id: Identity copied from the evaluated candidate.
        shape_index: Ordering index copied from the evaluated candidate.
        label: Candidate label displayed by downstream UI adapters.
        bbox: Candidate bounding box in image pixels.
        width: Raw rectangle width in image pixels.
        height: Raw rectangle height in image pixels.
        violations: All failed configured dimensions for this candidate.
    """

    candidate_id: CandidateId
    shape_index: int
    label: str
    bbox: BBox
    width: float
    height: float
    violations: Tuple[DimensionViolation, ...]


__all__ = [
    "BBox",
    "CandidateId",
    "DimensionName",
    "DimensionViolation",
    "RectangleCandidate",
    "RectangleSizeIssue",
    "RectangleSizeRule",
    "TriggerMode",
]
