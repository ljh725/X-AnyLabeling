"""
Geometry primitives for the L1/L2 quality checker.

All functions are pure (no Qt).  Coordinate conventions match LabelMe /
X-AnyLabeling: ``points`` is a list of ``[x, y]`` pairs in pixel space,
y grows downward.

Provided:
- bbox construction from points, area / center / width / height
- bbox validity (non-degenerate, finite, positive area)
- overlap / intersection / containment ratios
- face/head/person overflow ratio
- bbox expansion (uniform ratio + pixel floor)
- point-in-box and normalized distance from a point to a box edge
- keypoint ``y_rel`` (relative to person height) and body-band violation
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

Point = Tuple[float, float]
BBox = Tuple[float, float, float, float]  # (x1, y1, x2, y2), x1<=x2

_EPS = 1e-9


# ---------------------------------------------------------------------------
# bbox construction
# ---------------------------------------------------------------------------


def bbox_from_points(points: Sequence[Point]) -> Optional[BBox]:
    """Return axis-aligned bbox (x1,y1,x2,y2) or None if no valid points."""
    xs = [p[0] for p in points if _is_finite_pt(p)]
    ys = [p[1] for p in points if _is_finite_pt(p)]
    if not xs or not ys:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def bbox_from_two_corners(points: Sequence[Point]) -> Optional[BBox]:
    """BBox for a rectangle shape defined by exactly two corners."""
    if len(points) < 2:
        return None
    return bbox_from_points(points)


def is_valid_bbox(bbox: Optional[BBox]) -> bool:
    """True iff bbox has positive area and finite coords."""
    if bbox is None:
        return False
    x1, y1, x2, y2 = bbox
    if not all(_is_finite(v) for v in bbox):
        return False
    return (x2 - x1) > _EPS and (y2 - y1) > _EPS


def bbox_area(bbox: BBox) -> float:
    return max(0.0, (bbox[2] - bbox[0])) * max(0.0, (bbox[3] - bbox[1]))


def bbox_width(bbox: BBox) -> float:
    return bbox[2] - bbox[0]


def bbox_height(bbox: BBox) -> float:
    return bbox[3] - bbox[1]


def bbox_center(bbox: BBox) -> Point:
    return (
        (bbox[0] + bbox[2]) / 2.0,
        (bbox[1] + bbox[3]) / 2.0,
    )


def shape_bbox(
    shape_type: str,
    points: Sequence[Point],
) -> Optional[BBox]:
    """Build the bbox appropriate to a shape_type.

    - rectangle → two-corner bbox
    - everything else (point, polygon, linestrip, ...) → extent bbox
    """
    if shape_type == "rectangle":
        return bbox_from_two_corners(points)
    return bbox_from_points(points)


# ---------------------------------------------------------------------------
# overlap / intersection / containment
# ---------------------------------------------------------------------------


def _intersection_raw(a: BBox, b: BBox) -> Optional[BBox]:
    ix1 = max(a[0], b[0])
    iy1 = max(a[1], b[1])
    ix2 = min(a[2], b[2])
    iy2 = min(a[3], b[3])
    if ix2 <= ix1 or iy2 <= iy1:
        return None
    return (ix1, iy1, ix2, iy2)


def intersection_area(a: BBox, b: BBox) -> float:
    inter = _intersection_raw(a, b)
    if inter is None:
        return 0.0
    return bbox_area(inter)


def x_overlap_ratio(a: BBox, b: BBox) -> float:
    """Overlap length along x divided by the *smaller* width.

    Returns 0 if either box has zero width.
    """
    wa = bbox_width(a)
    wb = bbox_width(b)
    if wa <= _EPS or wb <= _EPS:
        return 0.0
    ow = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    return ow / min(wa, wb)


def y_overlap_ratio(a: BBox, b: BBox) -> float:
    ha = bbox_height(a)
    hb = bbox_height(b)
    if ha <= _EPS or hb <= _EPS:
        return 0.0
    oh = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return oh / min(ha, hb)


def iou(a: BBox, b: BBox) -> float:
    inter = intersection_area(a, b)
    if inter <= _EPS:
        return 0.0
    union = bbox_area(a) + bbox_area(b) - inter
    if union <= _EPS:
        return 0.0
    return inter / union


def containment_ratio(inner: BBox, outer: BBox) -> float:
    """Fraction of ``inner`` area that lies inside ``outer`` (0..1)."""
    inner_area = bbox_area(inner)
    if inner_area <= _EPS:
        return 0.0
    return intersection_area(inner, outer) / inner_area


def area_ratio(small: BBox, big: BBox) -> float:
    """area(small) / area(big), guarded against zero."""
    ab = bbox_area(big)
    if ab <= _EPS:
        return float("inf")
    return bbox_area(small) / ab


# ---------------------------------------------------------------------------
# overflow + expansion
# ---------------------------------------------------------------------------


def overflow_ratio(inner: BBox, outer: BBox) -> float:
    """Fraction of ``inner`` area that lies *outside* ``outer`` (0..1).

    ``face_head_overflow_ratio`` in the spec.  0 ⇒ fully contained.
    """
    return 1.0 - containment_ratio(inner, outer)


def expand_bbox(
    bbox: BBox,
    ratio: float,
    min_pixels: float = 0.0,
) -> BBox:
    """Uniformly expand a bbox by ``ratio`` (e.g. 0.15 ⇒ 15%).

    The expansion in each dimension is ``max(ratio * dim, min_pixels)``.
    """
    w = bbox_width(bbox)
    h = bbox_height(bbox)
    dx = max(ratio * w, min_pixels)
    dy = max(ratio * h, min_pixels)
    return (
        bbox[0] - dx,
        bbox[1] - dy,
        bbox[2] + dx,
        bbox[3] + dy,
    )


def point_in_bbox(pt: Point, bbox: BBox) -> bool:
    return (
        bbox[0] - _EPS <= pt[0] <= bbox[2] + _EPS
        and bbox[1] - _EPS <= pt[1] <= bbox[3] + _EPS
    )


def point_bbox_distance(pt: Point, bbox: BBox) -> float:
    """Euclidean distance from point to nearest bbox edge (0 if inside)."""
    cx = max(bbox[0] - pt[0], 0.0, pt[0] - bbox[2])
    cy = max(bbox[1] - pt[1], 0.0, pt[1] - bbox[3])
    return math.hypot(cx, cy)


def normalized_point_distance(
    pt: Point,
    bbox: BBox,
) -> float:
    """Distance from ``pt`` to ``bbox`` normalized by bbox diagonal.

    0 ⇒ inside; >0 ⇒ outside by that fraction of the diagonal.  Used as
    ``keypoint_outside_distance_norm`` / ``head_keypoint_box_distance_norm``.
    """
    diag = math.hypot(bbox_width(bbox), bbox_height(bbox))
    if diag <= _EPS:
        return 0.0
    return point_bbox_distance(pt, bbox) / diag


def center_distance_norm(
    inner: BBox,
    outer: BBox,
) -> float:
    """Center offset normalized by outer half-extents (max component)."""
    ci = bbox_center(inner)
    co = bbox_center(outer)
    dx = abs(ci[0] - co[0])
    dy = abs(ci[1] - co[1])
    half_w = bbox_width(outer) / 2.0
    half_h = bbox_height(outer) / 2.0
    if half_w <= _EPS or half_h <= _EPS:
        return 0.0
    return max(dx / half_w, dy / half_h)


# ---------------------------------------------------------------------------
# keypoint vertical bands (L2-10)
# ---------------------------------------------------------------------------


def keypoint_y_rel(
    pt: Point,
    person_bbox: BBox,
) -> Optional[float]:
    """``y_rel`` of a keypoint relative to person top (0)→bottom (1).

    Returns None if the person has zero height.
    """
    h = bbox_height(person_bbox)
    if h <= _EPS:
        return None
    return (pt[1] - person_bbox[1]) / h


def band_violation_distance(
    y_rel: float,
    y_min: Optional[float],
    y_max: Optional[float],
) -> float:
    """How far ``y_rel`` falls outside the [y_min, y_max] band.

    Returns 0 if inside the band.
    """
    if y_min is not None and y_rel < y_min:
        return y_min - y_rel
    if y_max is not None and y_rel > y_max:
        return y_rel - y_max
    return 0.0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _is_finite(value: float) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def _is_finite_pt(pt: Point) -> bool:
    return (
        isinstance(pt, (list, tuple))
        and len(pt) >= 2
        and _is_finite(pt[0])
        and _is_finite(pt[1])
    )
