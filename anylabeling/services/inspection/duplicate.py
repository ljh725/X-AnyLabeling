"""Shared rectangle duplicate geometry migrated from the beta4 dual-screen core."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, fields
from enum import IntEnum
from typing import (
    Any,
    Callable,
    Iterable,
    Iterator,
    Mapping,
    Optional,
    Sequence,
)

from .models import canonical_relation_key


class DuplicateSeverity(IntEnum):
    """Review priority for a geometric rectangle pair."""

    NONE = 0
    SUSPICIOUS = 1
    HIGH_RISK = 2


@dataclass(frozen=True)
class RectangleSnapshot:
    """Validated immutable rectangle used by detection and reports."""

    shape_id: str
    label: str
    bbox: tuple[float, float, float, float]
    group_id: Optional[int] = None

    @property
    def width(self) -> float:
        return max(0.0, self.bbox[2] - self.bbox[0])

    @property
    def height(self) -> float:
        return max(0.0, self.bbox[3] - self.bbox[1])

    @property
    def area(self) -> float:
        return self.width * self.height

    def to_dict(self) -> dict[str, Any]:
        return {
            "shape_id": self.shape_id,
            "label": self.label,
            "bbox": [round(value, 4) for value in self.bbox],
            "group_id": self.group_id,
        }


@dataclass(frozen=True)
class DuplicateMetrics:
    """Explainable pair metrics; values mirror the beta4 implementation."""

    iou: float
    smaller_coverage: float
    center_distance: float
    area_ratio: float
    aspect_ratio: float
    edge_delta: float

    def to_dict(self) -> dict[str, float]:
        return {
            "iou": round(self.iou, 6),
            "smaller_coverage": round(self.smaller_coverage, 6),
            "center_distance": round(self.center_distance, 6),
            "area_ratio": round(self.area_ratio, 6),
            "aspect_ratio": round(self.aspect_ratio, 6),
            "edge_delta": round(self.edge_delta, 6),
        }


@dataclass(frozen=True)
class DuplicatePair:
    """One classified rectangle pair with stable unordered identity."""

    first_id: str
    second_id: str
    severity: DuplicateSeverity
    metrics: DuplicateMetrics

    @property
    def key(self) -> tuple[str, str]:
        return tuple(sorted((self.first_id, self.second_id)))


@dataclass(frozen=True)
class DetectionResult:
    """Full-scan output that distinguishes cancellation from an empty result."""

    pairs: tuple[DuplicatePair, ...]
    cancelled: bool = False
    complete: bool = True
    invalid_shape_ids: tuple[str, ...] = ()
    truncated: bool = False

    @property
    def red_count(self) -> int:
        return sum(
            pair.severity is DuplicateSeverity.HIGH_RISK for pair in self.pairs
        )

    @property
    def yellow_count(self) -> int:
        return sum(
            pair.severity is DuplicateSeverity.SUSPICIOUS
            for pair in self.pairs
        )


@dataclass(frozen=True)
class DuplicateThresholds:
    """Validated red/yellow thresholds with the original beta4 presets."""

    red_iou: float
    red_containment: float
    red_center: float
    red_area_ratio: float
    yellow_iou: float
    yellow_containment: float
    yellow_center: float
    yellow_area_ratio: float
    yellow_aspect_ratio: float
    yellow_edge_delta: float

    def validate(self) -> "DuplicateThresholds":
        for item in fields(self):
            value = float(getattr(self, item.name))
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(
                    f"{item.name} must be a finite value between 0 and 1"
                )
        if self.red_iou < self.yellow_iou:
            raise ValueError("red_iou must be at least yellow_iou")
        if self.red_containment < self.yellow_containment:
            raise ValueError(
                "red_containment must be at least yellow_containment"
            )
        if self.red_center > self.yellow_center:
            raise ValueError("red_center must not exceed yellow_center")
        if self.red_area_ratio < self.yellow_area_ratio:
            raise ValueError(
                "red_area_ratio must be at least yellow_area_ratio"
            )
        return self

    def to_dict(self) -> dict[str, float]:
        return {
            item.name: float(getattr(self, item.name)) for item in fields(self)
        }


PRESETS = {
    "low": DuplicateThresholds(
        0.93, 0.95, 0.06, 0.82, 0.72, 0.88, 0.18, 0.55, 0.58, 0.20
    ),
    "medium": DuplicateThresholds(
        0.95, 0.97, 0.04, 0.88, 0.80, 0.92, 0.13, 0.65, 0.68, 0.14
    ),
    "high": DuplicateThresholds(
        0.97, 0.985, 0.025, 0.93, 0.87, 0.96, 0.09, 0.76, 0.78, 0.09
    ),
}


def thresholds_from_mapping(values: Mapping[str, Any]) -> DuplicateThresholds:
    """Build validated thresholds from a serialized profile payload."""
    names = {item.name for item in fields(DuplicateThresholds)}
    missing = names.difference(values)
    unknown = set(values).difference(names)
    if missing or unknown:
        raise ValueError(
            "threshold fields do not match schema: "
            f"missing={sorted(missing)} unknown={sorted(unknown)}"
        )
    return DuplicateThresholds(
        **{name: float(values[name]) for name in names}
    ).validate()


def rectangle_snapshot_from_points(
    shape_id: str,
    label: str,
    points: Sequence[Sequence[float]],
    group_id: Optional[int] = None,
) -> RectangleSnapshot:
    """Create a validated snapshot from raw point pairs.

    Raises:
        ValueError: if coordinates are non-finite or the rectangle is
            degenerate. Callers must report this instead of silently
            treating the shape as checked.
    """
    if not shape_id:
        raise ValueError("rectangle requires a non-empty shape_id")
    coordinates: list[tuple[float, float]] = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            raise ValueError("rectangle point must contain two coordinates")
        x_value = float(point[0])
        y_value = float(point[1])
        if not math.isfinite(x_value) or not math.isfinite(y_value):
            raise ValueError("rectangle coordinates must be finite")
        coordinates.append((x_value, y_value))
    if len(coordinates) < 2:
        raise ValueError("rectangle requires at least two points")
    left = min(point[0] for point in coordinates)
    right = max(point[0] for point in coordinates)
    top = min(point[1] for point in coordinates)
    bottom = max(point[1] for point in coordinates)
    if right <= left or bottom <= top:
        raise ValueError("rectangle has zero or negative area")
    return RectangleSnapshot(
        shape_id=shape_id,
        label=str(label),
        bbox=(left, top, right, bottom),
        group_id=group_id,
    )


def rectangle_snapshot_from_shape(shape: Any) -> Optional[RectangleSnapshot]:
    """Adapt a canvas Shape, returning None for non-rectangles or bad input."""
    if getattr(shape, "shape_type", "") != "rectangle":
        return None
    try:
        return rectangle_snapshot_from_points(
            str(getattr(shape, "xanylabeling_shape_id", "") or ""),
            str(getattr(shape, "label", "") or ""),
            getattr(shape, "points", ()) or (),
            getattr(shape, "group_id", None),
        )
    except (TypeError, ValueError):
        return None


def pair_metrics(
    first: RectangleSnapshot, second: RectangleSnapshot
) -> DuplicateMetrics:
    """Compute the original beta4 geometry metrics for one pair."""
    left = max(first.bbox[0], second.bbox[0])
    top = max(first.bbox[1], second.bbox[1])
    right = min(first.bbox[2], second.bbox[2])
    bottom = min(first.bbox[3], second.bbox[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = first.area + second.area - intersection
    smaller = min(first.area, second.area)
    iou_value = intersection / union if union > 0 else 0.0
    coverage = intersection / smaller if smaller > 0 else 0.0
    first_center = (
        (first.bbox[0] + first.bbox[2]) / 2.0,
        (first.bbox[1] + first.bbox[3]) / 2.0,
    )
    second_center = (
        (second.bbox[0] + second.bbox[2]) / 2.0,
        (second.bbox[1] + second.bbox[3]) / 2.0,
    )
    center_scale = max(
        1.0,
        math.hypot(
            min(first.width, second.width),
            min(first.height, second.height),
        ),
    )
    center_distance = (
        math.hypot(
            first_center[0] - second_center[0],
            first_center[1] - second_center[1],
        )
        / center_scale
    )
    area_ratio = smaller / max(first.area, second.area)
    first_aspect = first.width / first.height
    second_aspect = second.width / second.height
    aspect_ratio = min(first_aspect, second_aspect) / max(
        first_aspect, second_aspect
    )
    edge_scale = max(
        1.0,
        first.width,
        first.height,
        second.width,
        second.height,
    )
    edge_delta = (
        max(abs(first.bbox[index] - second.bbox[index]) for index in range(4))
        / edge_scale
    )
    return DuplicateMetrics(
        iou=iou_value,
        smaller_coverage=coverage,
        center_distance=center_distance,
        area_ratio=area_ratio,
        aspect_ratio=aspect_ratio,
        edge_delta=edge_delta,
    )


def classify_metrics(
    metrics: DuplicateMetrics, thresholds: DuplicateThresholds
) -> DuplicateSeverity:
    """Classify metrics using the original explainable combinations."""
    red_iou = (
        metrics.iou >= thresholds.red_iou
        and metrics.area_ratio >= thresholds.red_area_ratio
    )
    red_contained = (
        metrics.smaller_coverage >= thresholds.red_containment
        and metrics.center_distance <= thresholds.red_center
        and metrics.area_ratio >= thresholds.red_area_ratio
    )
    if red_iou or red_contained:
        return DuplicateSeverity.HIGH_RISK
    yellow_overlap = (
        metrics.iou >= thresholds.yellow_iou
        and metrics.area_ratio >= thresholds.yellow_area_ratio
    )
    yellow_contained = (
        metrics.smaller_coverage >= thresholds.yellow_containment
        and metrics.center_distance <= thresholds.yellow_center
        and metrics.area_ratio >= thresholds.yellow_area_ratio
    )
    yellow_aligned = (
        metrics.smaller_coverage > 0
        and metrics.center_distance <= thresholds.yellow_center
        and metrics.area_ratio >= thresholds.yellow_area_ratio
        and metrics.aspect_ratio >= thresholds.yellow_aspect_ratio
        and metrics.edge_delta <= thresholds.yellow_edge_delta
    )
    if yellow_overlap or yellow_contained or yellow_aligned:
        return DuplicateSeverity.SUSPICIOUS
    return DuplicateSeverity.NONE


def evaluate_pair(
    first: RectangleSnapshot,
    second: RectangleSnapshot,
    thresholds: DuplicateThresholds,
) -> Optional[DuplicatePair]:
    """Return a classified pair when its severity is non-zero."""
    metrics = pair_metrics(first, second)
    severity = classify_metrics(metrics, thresholds)
    if severity is DuplicateSeverity.NONE:
        return None
    return DuplicatePair(first.shape_id, second.shape_id, severity, metrics)


class SpatialRectangleIndex:
    """Uniform-grid candidate index, identical in spirit to beta4."""

    def __init__(
        self,
        rectangles: Iterable[RectangleSnapshot],
        cell_size: Optional[float] = None,
    ) -> None:
        self.rectangles = {item.shape_id: item for item in rectangles}
        valid_sizes = [
            math.sqrt(item.area)
            for item in self.rectangles.values()
            if item.area > 0
        ]
        inferred = (
            sorted(valid_sizes)[len(valid_sizes) // 2] if valid_sizes else 64.0
        )
        self.cell_size = max(16.0, float(cell_size or inferred))
        self.cells: dict[tuple[int, int], set[str]] = defaultdict(set)
        for item in self.rectangles.values():
            for cell in self._cells_for(item):
                self.cells[cell].add(item.shape_id)

    def _cells_for(self, item: RectangleSnapshot) -> Iterator[tuple[int, int]]:
        left, top, right, bottom = item.bbox
        start_x = math.floor(left / self.cell_size)
        end_x = math.floor(right / self.cell_size)
        start_y = math.floor(top / self.cell_size)
        end_y = math.floor(bottom / self.cell_size)
        for x_value in range(start_x, end_x + 1):
            for y_value in range(start_y, end_y + 1):
                yield x_value, y_value

    def candidate_pairs(self) -> Iterator[tuple[str, str]]:
        # Per-object neighbours avoid retaining an O(N²) global 'seen' set.
        for first in sorted(self.rectangles):
            for second in sorted(self.candidates_for(self.rectangles[first])):
                if first < second:
                    yield first, second

    def candidates_for(self, item: RectangleSnapshot) -> set[str]:
        result: set[str] = set()
        for cell in self._cells_for(item):
            result.update(self.cells.get(cell, ()))
        result.discard(item.shape_id)
        return result


def full_scan(
    rectangles: Sequence[RectangleSnapshot],
    thresholds: DuplicateThresholds,
    should_cancel: Optional[Callable[[], bool]] = None,
    *,
    max_pairs: Optional[int] = None,
) -> DetectionResult:
    """Evaluate every spatially plausible pair and preserve cancellation."""
    thresholds = thresholds.validate()
    valid = tuple(item for item in rectangles if item.area > 0)
    index = SpatialRectangleIndex(valid)
    by_id = {item.shape_id: item for item in valid}
    pairs: list[DuplicatePair] = []
    for first_id, second_id in index.candidate_pairs():
        if should_cancel is not None and should_cancel():
            return DetectionResult(
                pairs=tuple(sorted(pairs, key=lambda item: item.key)),
                cancelled=True,
                complete=False,
            )
        pair = evaluate_pair(by_id[first_id], by_id[second_id], thresholds)
        if pair is not None:
            if max_pairs is not None and len(pairs) >= max_pairs:
                return DetectionResult(
                    pairs=tuple(sorted(pairs, key=lambda item: item.key)),
                    complete=False,
                    truncated=True,
                )
            pairs.append(pair)
    return DetectionResult(
        pairs=tuple(sorted(pairs, key=lambda item: item.key)),
        cancelled=False,
        complete=True,
    )


class IncrementalDuplicateDetector:
    """Maintain pair adjacency and recompute only changed rectangles."""

    def __init__(
        self, thresholds: DuplicateThresholds, max_pairs: Optional[int] = None
    ) -> None:
        self.thresholds = thresholds.validate()
        self.max_pairs = max_pairs
        self.truncated = False
        self.rectangles: dict[str, RectangleSnapshot] = {}
        self.pairs: dict[tuple[str, str], DuplicatePair] = {}
        self.adjacency: dict[str, set[tuple[str, str]]] = defaultdict(set)

    def replace(
        self,
        result: DetectionResult,
        rectangles: Iterable[RectangleSnapshot],
    ) -> None:
        self.rectangles = {item.shape_id: item for item in rectangles}
        self.pairs = {pair.key: pair for pair in result.pairs}
        self.truncated = result.truncated
        self._rebuild_adjacency()

    def _rebuild_adjacency(self) -> None:
        self.adjacency = defaultdict(set)
        for key in self.pairs:
            self.adjacency[key[0]].add(key)
            self.adjacency[key[1]].add(key)

    def _drop_pairs(self, shape_id: str) -> None:
        for key in tuple(self.adjacency.pop(shape_id, ())):
            self.pairs.pop(key, None)
            other = key[1] if key[0] == shape_id else key[0]
            self.adjacency[other].discard(key)

    def remove(self, shape_id: str) -> None:
        self._drop_pairs(shape_id)
        self.rectangles.pop(shape_id, None)

    def update_geometry(self, item: RectangleSnapshot) -> None:
        self._drop_pairs(item.shape_id)
        self.rectangles[item.shape_id] = item
        for other in self.rectangles.values():
            if other.shape_id == item.shape_id:
                continue
            pair = evaluate_pair(item, other, self.thresholds)
            if pair is None:
                continue
            if (
                self.max_pairs is not None
                and len(self.pairs) >= self.max_pairs
            ):
                self.truncated = True
                break
            key = pair.key
            self.pairs[key] = pair
            self.adjacency[key[0]].add(key)
            self.adjacency[key[1]].add(key)

    def update_many(self, items: Iterable[RectangleSnapshot]) -> None:
        for item in items:
            self.update_geometry(item)

    def relabel(self, shape_id: str, label: str) -> None:
        item = self.rectangles.get(shape_id)
        if item is not None:
            self.rectangles[shape_id] = RectangleSnapshot(
                shape_id=item.shape_id,
                label=str(label),
                bbox=item.bbox,
                group_id=item.group_id,
            )

    def severities(self) -> Mapping[str, DuplicateSeverity]:
        result: dict[str, DuplicateSeverity] = {}
        for pair in self.pairs.values():
            for shape_id in (pair.first_id, pair.second_id):
                result[shape_id] = max(
                    result.get(shape_id, DuplicateSeverity.NONE),
                    pair.severity,
                )
        return result

    def counts(self) -> tuple[int, int]:
        red = sum(
            pair.severity is DuplicateSeverity.HIGH_RISK
            for pair in self.pairs.values()
        )
        yellow = sum(
            pair.severity is DuplicateSeverity.SUSPICIOUS
            for pair in self.pairs.values()
        )
        return red, yellow


def relation_for(
    first: RectangleSnapshot,
    second: RectangleSnapshot,
    relations: Mapping[str, str],
) -> str:
    """Return the configured relation, defaulting to conservative unknown."""
    return str(
        relations.get(
            canonical_relation_key(first.label, second.label), "unknown"
        )
    )


def legacy_same_group_pair(
    first: RectangleSnapshot,
    second: RectangleSnapshot,
    edge_tolerance_px: float = 2.0,
) -> Optional[DuplicateMetrics]:
    """Evaluate the legacy L2-13 same-label/same-group edge rule.

    The old rule compared absolute pixel edge differences inside one
    group. It is kept as an independent evidence source instead of being
    translated into the new geometric severity scale.
    """
    if first.label != second.label:
        return None
    if first.group_id is None or first.group_id != second.group_id:
        return None
    metrics = pair_metrics(first, second)
    edge_scale = max(
        1.0,
        first.width,
        first.height,
        second.width,
        second.height,
    )
    absolute_delta = metrics.edge_delta * edge_scale
    if absolute_delta > float(edge_tolerance_px):
        return None
    return metrics
