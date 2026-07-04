"""Geometry primitives tests for the L1/L2 quality checker.

Covers bbox construction / area / center, overlap / intersection /
containment, overflow ratio, expansion, point-in-box, normalized
distance, and keypoint ``y_rel`` / body-band violation.

Run: pytest tests/test_quality_geometry.py -v
"""

import math
import os.path as osp
import sys

import pytest

sys.path.insert(0, osp.dirname(osp.dirname(osp.abspath(__file__))))

from anylabeling.views.labeling.widgets.inspector.quality import (
    geometry as G,
)  # noqa: E402

# ---------------------------------------------------------------------------
# bbox construction
# ---------------------------------------------------------------------------


class TestBboxConstruction:
    def test_from_points(self):
        b = G.bbox_from_points([(1, 2), (3, 4), (0, 5)])
        assert b == (0, 2, 3, 5)

    def test_from_points_empty(self):
        assert G.bbox_from_points([]) is None

    def test_from_points_filters_nonfinite(self):
        b = G.bbox_from_points([(1, 2), (float("nan"), 3), (4, 5)])
        assert b == (1, 2, 4, 5)

    def test_rectangle_two_corners(self):
        b = G.bbox_from_two_corners([(10, 20), (30, 40)])
        assert b == (10, 20, 30, 40)

    def test_shape_bbox_rectangle(self):
        b = G.shape_bbox("rectangle", [(0, 0), (5, 5)])
        assert b == (0, 0, 5, 5)

    def test_shape_bbox_polygon(self):
        b = G.shape_bbox("polygon", [(1, 1), (3, 1), (3, 4), (1, 4)])
        assert b == (1, 1, 3, 4)


# ---------------------------------------------------------------------------
# validity / area / center
# ---------------------------------------------------------------------------


class TestBboxBasics:
    def test_is_valid_positive_area(self):
        assert G.is_valid_bbox((0, 0, 5, 5)) is True

    def test_is_valid_degenerate(self):
        assert G.is_valid_bbox((0, 0, 0, 5)) is False

    def test_is_valid_none(self):
        assert G.is_valid_bbox(None) is False

    def test_area(self):
        assert G.bbox_area((0, 0, 4, 5)) == 20.0

    def test_width_height(self):
        assert G.bbox_width((1, 1, 4, 6)) == 3.0
        assert G.bbox_height((1, 1, 4, 6)) == 5.0

    def test_center(self):
        assert G.bbox_center((0, 0, 10, 6)) == (5.0, 3.0)


# ---------------------------------------------------------------------------
# overlap / intersection / containment
# ---------------------------------------------------------------------------


class TestOverlapRelations:
    def test_iou_full_overlap(self):
        assert G.iou((0, 0, 4, 4), (0, 0, 4, 4)) == pytest.approx(1.0)

    def test_iou_half_overlap(self):
        # two 4x4 boxes overlapping in a 2x4 region → iou = 8/24
        assert G.iou((0, 0, 4, 4), (2, 0, 6, 4)) == pytest.approx(8 / 24)

    def test_iou_disjoint(self):
        assert G.iou((0, 0, 1, 1), (5, 5, 6, 6)) == 0.0

    def test_intersection_area_disjoint(self):
        assert G.intersection_area((0, 0, 1, 1), (2, 2, 3, 3)) == 0.0

    def test_containment_full(self):
        inner = (2, 2, 3, 3)
        outer = (0, 0, 5, 5)
        assert G.containment_ratio(inner, outer) == pytest.approx(1.0)

    def test_containment_partial(self):
        inner = (0, 0, 4, 4)  # area 16
        outer = (2, 2, 6, 6)  # intersection is 2x2 = 4
        assert G.containment_ratio(inner, outer) == pytest.approx(0.25)

    def test_x_overlap_ratio(self):
        a = (0, 0, 4, 1)
        b = (2, 0, 6, 1)
        # overlap length 2, min width 4 → 0.5
        assert G.x_overlap_ratio(a, b) == pytest.approx(0.5)

    def test_y_overlap_ratio_zero(self):
        assert G.y_overlap_ratio((0, 0, 1, 1), (0, 5, 1, 6)) == 0.0

    def test_area_ratio(self):
        small = (0, 0, 2, 2)  # 4
        big = (0, 0, 4, 4)  # 16
        assert G.area_ratio(small, big) == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# overflow + expansion
# ---------------------------------------------------------------------------


class TestOverflowAndExpand:
    def test_overflow_zero_when_contained(self):
        face = (1, 1, 2, 2)
        head = (0, 0, 5, 5)
        assert G.overflow_ratio(face, head) == pytest.approx(0.0)

    def test_overflow_half_outside(self):
        # face area 4, half outside head → 0.5
        face = (0, 0, 4, 1)
        head = (2, 0, 6, 1)
        assert G.overflow_ratio(face, head) == pytest.approx(0.5)

    def test_expand_grows_uniformly(self):
        expanded = G.expand_bbox((10, 10, 20, 20), 0.10)
        # dx = 0.10 * 10 = 1
        assert expanded == (9, 9, 21, 21)

    def test_expand_respects_min_pixels(self):
        # tiny box: ratio expansion would be 0.05*1=0.05, min_pixels 8 wins
        expanded = G.expand_bbox((0, 0, 1, 1), 0.05, min_pixels=8.0)
        assert expanded == (-8, -8, 9, 9)


# ---------------------------------------------------------------------------
# point / distance
# ---------------------------------------------------------------------------


class TestPointDistance:
    def test_point_in_bbox_inside(self):
        assert G.point_in_bbox((2, 2), (0, 0, 5, 5)) is True

    def test_point_in_bbox_outside(self):
        assert G.point_in_bbox((6, 6), (0, 0, 5, 5)) is False

    def test_point_bbox_distance_inside_is_zero(self):
        assert G.point_bbox_distance((2, 2), (0, 0, 5, 5)) == 0.0

    def test_point_bbox_distance_outside(self):
        # point to right of box: dx=3, dy=0
        assert G.point_bbox_distance((8, 2), (0, 0, 5, 5)) == pytest.approx(
            3.0
        )

    def test_normalized_point_distance_inside_zero(self):
        assert G.normalized_point_distance((2, 2), (0, 0, 5, 5)) == 0.0

    def test_normalized_point_distance_outside_positive(self):
        d = G.normalized_point_distance((8, 2), (0, 0, 5, 5))
        assert d > 0.0

    def test_center_distance_norm_zero(self):
        # concentric → 0
        assert G.center_distance_norm((2, 2, 4, 4), (0, 0, 6, 6)) == 0.0

    def test_center_distance_norm_max_component(self):
        # inner center at (4,3), outer center at (3,3), half_w=3, half_h=3
        # dx=1, dy=0 → max(1/3, 0)=0.333
        d = G.center_distance_norm((3, 2, 5, 4), (0, 0, 6, 6))
        assert d == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# keypoint y_rel + body band
# ---------------------------------------------------------------------------


class TestKeypointBands:
    def test_y_rel_top(self):
        assert G.keypoint_y_rel((5, 0), (0, 0, 10, 10)) == pytest.approx(0.0)

    def test_y_rel_bottom(self):
        assert G.keypoint_y_rel((5, 10), (0, 0, 10, 10)) == pytest.approx(1.0)

    def test_y_rel_zero_height_returns_none(self):
        assert G.keypoint_y_rel((5, 0), (0, 0, 10, 0)) is None

    def test_band_violation_inside_is_zero(self):
        assert G.band_violation_distance(0.20, 0.10, 0.50) == 0.0

    def test_band_violation_above(self):
        # y_rel=0.60, band max 0.50 → violation 0.10
        assert G.band_violation_distance(0.60, 0.10, 0.50) == pytest.approx(
            0.10
        )

    def test_band_violation_below(self):
        # y_rel=0.05, band min 0.10 → violation 0.05
        assert G.band_violation_distance(0.05, 0.10, 0.50) == pytest.approx(
            0.05
        )
