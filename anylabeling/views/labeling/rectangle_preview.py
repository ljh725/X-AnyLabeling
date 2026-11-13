"""Geometry helpers for rectangle preview outlines.

The helpers in this module only depend on Qt geometry and path types. They
must not import ``Shape`` or ``Canvas``: the canvas owns the preview state and
uses these functions to build a temporary stroke path for the current frame.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from PyQt6 import QtGui

Box = tuple[float, float, float, float]

FIT_CANDIDATE_COLOR = QtGui.QColor(220, 130, 0, 255)
FIT_CANDIDATE_WIDTH = 2.0

COLLINEAR_TOLERANCE = 1e-6
MIN_SEGMENT_LENGTH = 1e-9
ANTIALIAS_MARGIN_PX = 1.0


@dataclass(frozen=True)
class RectangleEdge:
    """One axis-aligned edge in image coordinates."""

    orientation: str
    coordinate: float
    start: float
    end: float

    @property
    def length(self) -> float:
        """Return the edge length."""
        return self.end - self.start


@dataclass(frozen=True)
class PointFitPreview:
    """Immutable per-frame point-fit state shared by every paint entry."""

    target: object | None
    box: Box | None
    candidate_box: Box | None
    outline_path: QtGui.QPainterPath | None
    fixed_point: tuple[float, float] | None = None
    pointer: tuple[float, float] | None = None
    guides: bool = False

    @property
    def valid(self) -> bool:
        """Return whether the candidate geometry is valid for display."""
        return self.box is not None and self.candidate_box is not None

    @property
    def candidate_differs(self) -> bool:
        """Return whether the candidate changed the rectangle geometry."""
        return self.valid and self.candidate_box != self.box

    @property
    def owns_guides(self) -> bool:
        """Return whether this frame draws its own crosshair guides."""
        return self.guides and self.pointer is not None


def normalize_box(box: Iterable[float]) -> Box | None:
    """Return normalized finite bounds, or ``None`` for unusable input."""
    values = tuple(float(value) for value in box)
    if len(values) != 4 or not all(math.isfinite(value) for value in values):
        return None
    left, top, right, bottom = values
    if right < left:
        left, right = right, left
    if bottom < top:
        top, bottom = bottom, top
    if right - left <= 0 or bottom - top <= 0:
        return None
    return left, top, right, bottom


def rectangle_box_from_points(points: Sequence) -> Box | None:
    """Return bounds when points describe an axis-aligned rectangle."""
    if len(points) == 2:
        first, second = points
        return normalize_box((first.x(), first.y(), second.x(), second.y()))
    if len(points) != 4:
        return None
    coordinates = [(point.x(), point.y()) for point in points]
    xs = [point[0] for point in coordinates]
    ys = [point[1] for point in coordinates]
    box = normalize_box((min(xs), min(ys), max(xs), max(ys)))
    if box is None:
        return None
    left, top, right, bottom = box
    corners = (
        (left, top),
        (right, top),
        (right, bottom),
        (left, bottom),
    )
    for x, y in coordinates:
        if not any(
            math.isclose(x, corner_x, abs_tol=COLLINEAR_TOLERANCE)
            and math.isclose(y, corner_y, abs_tol=COLLINEAR_TOLERANCE)
            for corner_x, corner_y in corners
        ):
            return None
    return box


def rectangle_edges(box: Box) -> tuple[RectangleEdge, ...]:
    """Return the four axis-aligned edges of a normalized box."""
    left, top, right, bottom = box
    return (
        RectangleEdge("horizontal", top, left, right),
        RectangleEdge("vertical", right, top, bottom),
        RectangleEdge("horizontal", bottom, left, right),
        RectangleEdge("vertical", left, top, bottom),
    )


def _is_same_line(first: RectangleEdge, second: RectangleEdge) -> bool:
    return first.orientation == second.orientation and math.isclose(
        first.coordinate, second.coordinate, abs_tol=COLLINEAR_TOLERANCE
    )


def _subtract_intervals(
    start: float, end: float, holes: Iterable[tuple[float, float]]
) -> tuple[tuple[float, float], ...]:
    """Return the positive-length parts of a span not covered by holes."""
    cursor = start
    segments = []
    for hole_start, hole_end in sorted(holes):
        if hole_end <= cursor:
            continue
        if hole_start > cursor:
            segments.append((cursor, min(hole_start, end)))
        cursor = max(cursor, hole_end)
        if cursor >= end:
            break
    if cursor < end:
        segments.append((cursor, end))
    return tuple(
        segment
        for segment in segments
        if segment[1] - segment[0] > MIN_SEGMENT_LENGTH
    )


def _stroke_margin(scale: float, line_width: float) -> float:
    """Convert half a preview stroke plus antialiasing to image units."""
    safe_scale = scale if math.isfinite(scale) and scale > 0 else 1.0
    return (max(line_width, 0.0) / 2.0 + ANTIALIAS_MARGIN_PX) / safe_scale


def remaining_edges(
    box: Box,
    other_box: Box,
    *,
    scale: float = 1.0,
    line_width: float = FIT_CANDIDATE_WIDTH,
) -> tuple[RectangleEdge, ...] | None:
    """Return original edges without the parts shared with another box.

    Only same-orientation edges on the same line with a positive-length
    overlap are removed. Near but non-collinear edges and point-only
    intersections are preserved.
    """
    original = normalize_box(box)
    other = normalize_box(other_box)
    if original is None or other is None:
        return None
    margin = _stroke_margin(scale, line_width)
    other_edges = rectangle_edges(other)
    result = []
    for edge in rectangle_edges(original):
        holes = []
        for candidate in other_edges:
            if not _is_same_line(edge, candidate):
                continue
            overlap_start = max(edge.start, candidate.start)
            overlap_end = min(edge.end, candidate.end)
            if overlap_end - overlap_start <= MIN_SEGMENT_LENGTH:
                continue
            holes.append(
                (
                    max(edge.start, overlap_start - margin),
                    min(edge.end, overlap_end + margin),
                )
            )
        for start, end in _subtract_intervals(edge.start, edge.end, holes):
            result.append(
                RectangleEdge(edge.orientation, edge.coordinate, start, end)
            )
    return tuple(result)


def creation_edges(
    box: Box, guide_x: float, guide_y: float
) -> tuple[RectangleEdge, ...] | None:
    """Return draft edges that do not duplicate the crosshair guides."""
    normalized = normalize_box(box)
    if normalized is None:
        return None
    if not (math.isfinite(guide_x) and math.isfinite(guide_y)):
        return None
    result = []
    for edge in rectangle_edges(normalized):
        guide = guide_y if edge.orientation == "horizontal" else guide_x
        if math.isclose(edge.coordinate, guide, abs_tol=COLLINEAR_TOLERANCE):
            continue
        result.append(edge)
    return tuple(result)


def path_from_edges(edges: Iterable[RectangleEdge]) -> QtGui.QPainterPath:
    """Build one open path from independent edge segments."""
    path = QtGui.QPainterPath()
    for edge in edges:
        if edge.length <= MIN_SEGMENT_LENGTH:
            continue
        if edge.orientation == "horizontal":
            path.moveTo(edge.start, edge.coordinate)
            path.lineTo(edge.end, edge.coordinate)
        else:
            path.moveTo(edge.coordinate, edge.start)
            path.lineTo(edge.coordinate, edge.end)
    return path


def build_remaining_outline(
    box: Box,
    other_box: Box,
    *,
    scale: float = 1.0,
    line_width: float = FIT_CANDIDATE_WIDTH,
) -> QtGui.QPainterPath | None:
    """Build the temporary stroke path for a fitted rectangle preview."""
    edges = remaining_edges(box, other_box, scale=scale, line_width=line_width)
    if edges is None:
        return None
    return path_from_edges(edges)


def build_creation_outline(
    box: Box, guide_x: float, guide_y: float
) -> QtGui.QPainterPath | None:
    """Build the temporary stroke path for a two-point rectangle draft."""
    edges = creation_edges(box, guide_x, guide_y)
    if edges is None:
        return None
    return path_from_edges(edges)
