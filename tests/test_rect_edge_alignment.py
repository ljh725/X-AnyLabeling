"""Tests for ``anylabeling.views.labeling.rect_edge_alignment``.

Headless Qt is configured centrally in ``tests/conftest.py`` (sets
``QT_QPA_PLATFORM=offscreen``), so this module does not need to set it.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore  # noqa: E402

from anylabeling.views.labeling.rect_edge_alignment import (  # noqa: E402
    RECT_EDGE_AXIS_X,
    RECT_EDGE_AXIS_Y,
    RECT_EDGE_BOTTOM,
    RECT_EDGE_LEFT,
    RECT_EDGE_NAMES,
    RECT_EDGE_RIGHT,
    RECT_EDGE_TOP,
    apply_edge_coord,
    edge_from_geometry,
    edges_are_compatible,
    geometry_from_shape,
    geometry_with_edge_coord,
    iter_edges,
    nearest_edge,
    points_from_geometry,
    RectGeometry,
)
from anylabeling.views.labeling.shape import Shape  # noqa: E402


def _rect(points):
    """Build a rectangle ``Shape`` from raw ``(x, y)`` tuples."""
    shape = Shape(label="person", shape_type="rectangle")
    shape.points = [QtCore.QPointF(x, y) for x, y in points]
    return shape


class TestGeometryFromShape(unittest.TestCase):
    """B.1 / B.2 — normalization of 2-point and 4-point rectangles."""

    def test_two_point_diagonal_is_normalized(self):
        # B.1: input (20,30),(10,5) -> x_min=10,y_min=5,x_max=20,y_max=30
        shape = _rect([(20, 30), (10, 5)])
        geom = geometry_from_shape(shape)
        self.assertIsNotNone(geom)
        self.assertEqual(geom.x_min, 10)
        self.assertEqual(geom.y_min, 5)
        self.assertEqual(geom.x_max, 20)
        self.assertEqual(geom.y_max, 30)

    def test_four_point_shuffled_uses_min_max(self):
        # B.2: four corners in arbitrary order still collapse to bbox.
        shape = _rect(
            [
                (120, 140),  # bottom-right
                (20, 140),  # bottom-left
                (20, 30),  # top-left
                (120, 30),  # top-right
            ]
        )
        geom = geometry_from_shape(shape)
        self.assertIsNotNone(geom)
        self.assertEqual(geom.x_min, 20)
        self.assertEqual(geom.y_min, 30)
        self.assertEqual(geom.x_max, 120)
        self.assertEqual(geom.y_max, 140)

    def test_non_rectangle_returns_none(self):
        polygon = Shape(label="x", shape_type="polygon")
        polygon.points = [QtCore.QPointF(0, 0), QtCore.QPointF(1, 1)]
        self.assertIsNone(geometry_from_shape(polygon))

    def test_too_few_points_returns_none(self):
        shape = _rect([(5, 5)])
        self.assertIsNone(geometry_from_shape(shape))

    def test_invalid_point_count_returns_none(self):
        shape = _rect([(0, 0), (1, 0), (1, 1)])
        self.assertIsNone(geometry_from_shape(shape))

    def test_width_height_and_is_valid(self):
        geom = RectGeometry(10, 5, 20, 30)
        self.assertEqual(geom.width, 10)
        self.assertEqual(geom.height, 25)
        self.assertTrue(geom.is_valid())
        # Degenerate: zero area.
        self.assertFalse(RectGeometry(10, 5, 10, 5).is_valid())
        # Below the minimum-size contract.
        self.assertFalse(RectGeometry(10, 5, 10.5, 6.0).is_valid(min_width=1))


class TestPointsFromGeometry(unittest.TestCase):
    """Output order must be TL -> TR -> BR -> BL."""

    def test_canonical_four_point_order(self):
        geom = RectGeometry(10, 5, 20, 30)
        pts = points_from_geometry(geom)
        self.assertEqual(len(pts), 4)
        self.assertEqual((pts[0].x(), pts[0].y()), (10, 5))  # top-left
        self.assertEqual((pts[1].x(), pts[1].y()), (20, 5))  # top-right
        self.assertEqual((pts[2].x(), pts[2].y()), (20, 30))  # bottom-right
        self.assertEqual((pts[3].x(), pts[3].y()), (10, 30))  # bottom-left


class TestIterEdges(unittest.TestCase):
    """B.3 — edge enumeration returns the four edges with correct axis/coord."""

    def test_four_edges_with_axis_and_coord(self):
        shape = _rect([(10, 5), (20, 30)])
        edges = {e.edge_name: e for e in iter_edges(shape)}

        self.assertEqual(set(edges.keys()), set(RECT_EDGE_NAMES))

        self.assertEqual(edges[RECT_EDGE_LEFT].axis, RECT_EDGE_AXIS_X)
        self.assertEqual(edges[RECT_EDGE_LEFT].coord, 10)
        self.assertEqual(edges[RECT_EDGE_LEFT].opposite_coord, 20)

        self.assertEqual(edges[RECT_EDGE_RIGHT].axis, RECT_EDGE_AXIS_X)
        self.assertEqual(edges[RECT_EDGE_RIGHT].coord, 20)
        self.assertEqual(edges[RECT_EDGE_RIGHT].opposite_coord, 10)

        self.assertEqual(edges[RECT_EDGE_TOP].axis, RECT_EDGE_AXIS_Y)
        self.assertEqual(edges[RECT_EDGE_TOP].coord, 5)
        self.assertEqual(edges[RECT_EDGE_TOP].opposite_coord, 30)

        self.assertEqual(edges[RECT_EDGE_BOTTOM].axis, RECT_EDGE_AXIS_Y)
        self.assertEqual(edges[RECT_EDGE_BOTTOM].coord, 30)
        self.assertEqual(edges[RECT_EDGE_BOTTOM].opposite_coord, 5)

    def test_edge_endpoints_match_table(self):
        shape = _rect([(10, 5), (20, 30)])
        edges = {e.edge_name: e for e in iter_edges(shape)}

        # left: (x_min,y_min)-(x_min,y_max)
        self.assertEqual((edges["left"].p1.x(), edges["left"].p1.y()), (10, 5))
        self.assertEqual(
            (edges["left"].p2.x(), edges["left"].p2.y()), (10, 30)
        )
        # top: (x_min,y_min)-(x_max,y_min)
        self.assertEqual((edges["top"].p1.x(), edges["top"].p1.y()), (10, 5))
        self.assertEqual((edges["top"].p2.x(), edges["top"].p2.y()), (20, 5))

    def test_non_rectangle_returns_empty(self):
        polygon = Shape(label="x", shape_type="polygon")
        polygon.points = [QtCore.QPointF(0, 0), QtCore.QPointF(1, 1)]
        self.assertEqual(iter_edges(polygon), [])

    def test_invalid_rectangle_returns_empty(self):
        # Two coincident points -> zero area -> not valid.
        shape = _rect([(5, 5), (5, 5)])
        self.assertEqual(iter_edges(shape), [])


class TestNearestEdge(unittest.TestCase):
    """B.4 — nearest edge hit-testing."""

    def test_hit_near_left_edge(self):
        shape = _rect([(10, 5), (20, 30)])  # left at x=10
        result = nearest_edge(shape, QtCore.QPointF(10.3, 17), epsilon=1.0)
        self.assertIsNotNone(result)
        edge, dist = result
        self.assertEqual(edge.edge_name, RECT_EDGE_LEFT)
        self.assertAlmostEqual(dist, 0.3, places=6)

    def test_miss_when_outside_epsilon(self):
        shape = _rect([(10, 5), (20, 30)])
        # Center of the rectangle: far from any edge segment projection? The
        # perpendicular distance to the nearest edge is small, so pick a
        # point clearly outside the epsilon envelope on the diagonal.
        result = nearest_edge(shape, QtCore.QPointF(50, 60), epsilon=2.0)
        self.assertIsNone(result)


class TestEdgesAreCompatible(unittest.TestCase):
    """B.5 — compatibility matrix."""

    def _make_edge(self, edge_name, axis, shape):
        geom = geometry_from_shape(shape)
        return edge_from_geometry(shape, geom, edge_name)

    def test_different_shape_same_axis_is_compatible(self):
        a = self._make_edge(
            RECT_EDGE_LEFT, RECT_EDGE_AXIS_X, _rect([(0, 0), (10, 10)])
        )
        b = self._make_edge(
            RECT_EDGE_RIGHT, RECT_EDGE_AXIS_X, _rect([(20, 0), (30, 10)])
        )
        self.assertTrue(edges_are_compatible(a, b))

    def test_same_shape_is_incompatible(self):
        shape = _rect([(0, 0), (10, 10)])
        a = self._make_edge(RECT_EDGE_LEFT, RECT_EDGE_AXIS_X, shape)
        b = self._make_edge(RECT_EDGE_RIGHT, RECT_EDGE_AXIS_X, shape)
        self.assertFalse(edges_are_compatible(a, b))

    def test_different_axis_is_incompatible(self):
        a = self._make_edge(
            RECT_EDGE_LEFT, RECT_EDGE_AXIS_X, _rect([(0, 0), (10, 10)])
        )
        b = self._make_edge(
            RECT_EDGE_TOP, RECT_EDGE_AXIS_Y, _rect([(20, 0), (30, 10)])
        )
        self.assertFalse(edges_are_compatible(a, b))


class TestGeometryWithEdgeCoord(unittest.TestCase):
    """B.6 / B.7 — edge update and anti-flip clamp."""

    def test_update_left_changes_xmin_only(self):
        geom = RectGeometry(10, 5, 20, 30)
        new = geometry_with_edge_coord(geom, RECT_EDGE_LEFT, 4)
        self.assertEqual(new.x_min, 4)
        self.assertEqual(new.x_max, 20)
        self.assertEqual(new.y_min, 5)
        self.assertEqual(new.y_max, 30)

    def test_clamp_prevents_flip_on_left(self):
        # B.7: moving left past right clamps to x_max - min_size.
        geom = RectGeometry(10, 5, 20, 30)
        new = geometry_with_edge_coord(geom, RECT_EDGE_LEFT, 50, min_size=2.0)
        self.assertEqual(new.x_min, 20 - 2.0)
        self.assertEqual(new.x_max, 20)

    def test_clamp_prevents_flip_on_right(self):
        geom = RectGeometry(10, 5, 20, 30)
        new = geometry_with_edge_coord(
            geom, RECT_EDGE_RIGHT, -100, min_size=2.0
        )
        self.assertEqual(new.x_max, 10 + 2.0)
        self.assertEqual(new.x_min, 10)

    def test_clamp_prevents_flip_on_top_and_bottom(self):
        geom = RectGeometry(10, 5, 20, 30)
        top_clamped = geometry_with_edge_coord(
            geom, RECT_EDGE_TOP, 100, min_size=2.0
        )
        self.assertEqual(top_clamped.y_min, 30 - 2.0)

        bottom_clamped = geometry_with_edge_coord(
            geom, RECT_EDGE_BOTTOM, -100, min_size=2.0
        )
        self.assertEqual(bottom_clamped.y_max, 5 + 2.0)


class TestApplyEdgeCoord(unittest.TestCase):
    """B.8 — apply_edge_coord rewrites the shape to canonical four points."""

    def test_apply_writes_canonical_four_points(self):
        shape = _rect([(10, 5), (20, 30)])  # 2-point diagonal input
        ok = apply_edge_coord(shape, RECT_EDGE_LEFT, 4, min_size=1.0)
        self.assertTrue(ok)
        pts = shape.points
        self.assertEqual(len(pts), 4)
        # Order: TL -> TR -> BR -> BL
        self.assertEqual((pts[0].x(), pts[0].y()), (4, 5))
        self.assertEqual((pts[1].x(), pts[1].y()), (20, 5))
        self.assertEqual((pts[2].x(), pts[2].y()), (20, 30))
        self.assertEqual((pts[3].x(), pts[3].y()), (4, 30))

    def test_apply_returns_false_for_non_rectangle(self):
        polygon = Shape(label="x", shape_type="polygon")
        polygon.points = [QtCore.QPointF(0, 0), QtCore.QPointF(1, 1)]
        self.assertFalse(apply_edge_coord(polygon, RECT_EDGE_LEFT, 5))

    def test_apply_does_not_touch_label_or_group_id(self):
        shape = _rect([(10, 5), (20, 30)])
        shape.label = "car"
        shape.group_id = 7
        apply_edge_coord(shape, RECT_EDGE_RIGHT, 25)
        self.assertEqual(shape.label, "car")
        self.assertEqual(shape.group_id, 7)

    def test_apply_clamps_to_prevent_flip(self):
        shape = _rect([(10, 5), (20, 30)])
        # Move left past right -> clamped, no flip in the resulting geometry.
        ok = apply_edge_coord(shape, RECT_EDGE_LEFT, 100, min_size=2.0)
        self.assertTrue(ok)
        geom = geometry_from_shape(shape)
        self.assertLess(geom.x_min, geom.x_max)


if __name__ == "__main__":
    unittest.main()
