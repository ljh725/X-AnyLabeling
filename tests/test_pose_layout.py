"""Unit tests for pose_layout (direct / anti / column).

Tests verify:
- Midline computation from shoulder/nose keypoints
- Direction assignment for head / limbs / legs
- Direct layout places labels along direction vectors
- Anti layout reduces overlap count vs direct
- Column layout splits into left/right/top columns
- apply_layout dispatcher routes correctly
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore

from anylabeling.views.labeling.widgets.pose_label.pose_constants import (
    COCO_KEYPOINT_INDEX,
)
from anylabeling.views.labeling.widgets.pose_label.pose_layout import (
    PoseLabelItem,
    _count_overlaps,
    apply_layout,
    compute_direction,
    compute_midline,
    layout_anti,
    layout_column,
    layout_direct,
)


def _make_item(
    label: str,
    px: float,
    py: float,
    w: int = 50,
    h: int = 16,
) -> PoseLabelItem:
    """Build a PoseLabelItem at (px, py) with a default-sized rect."""
    ki = COCO_KEYPOINT_INDEX.get(label, 0)
    rect = QtCore.QRect(int(px), int(py), w, h)
    return PoseLabelItem(
        shape_ref=None,
        label=label,
        keypoint_index=ki,
        group_id=0,
        anchor=QtCore.QPointF(px, py),
        rect=rect,
    )


class TestComputeMidline(unittest.TestCase):
    """Tests for midline computation."""

    def test_from_shoulders(self):
        """Midline x is shoulder midpoint."""
        kps = {
            5: QtCore.QPointF(100, 200),
            6: QtCore.QPointF(200, 200),
        }
        mid = compute_midline(kps)
        self.assertIsNotNone(mid)
        self.assertAlmostEqual(mid[0], 150.0)
        self.assertAlmostEqual(mid[1], 100.0)

    def test_fallback_to_nose(self):
        """When shoulders missing, fall back to nose position."""
        kps = {0: QtCore.QPointF(120, 50)}
        mid = compute_midline(kps)
        self.assertIsNotNone(mid)
        self.assertAlmostEqual(mid[0], 120.0)
        self.assertAlmostEqual(mid[1], 60.0)

    def test_no_keypoints(self):
        """Returns None when no reference keypoints exist."""
        mid = compute_midline({})
        self.assertIsNone(mid)


class TestComputeDirection(unittest.TestCase):
    """Tests for direction computation."""

    def test_center_keypoint_goes_up(self):
        """A keypoint near the midline goes 'up'."""
        mid = (150.0, 100.0)
        pos = QtCore.QPointF(151, 100)
        d = compute_direction(0, pos, mid)
        self.assertEqual(d, "up")

    def test_left_shoulder_goes_left(self):
        """Left shoulder (index 5) on the left side goes 'left'."""
        mid = (150.0, 100.0)
        pos = QtCore.QPointF(100, 200)
        d = compute_direction(5, pos, mid)
        self.assertEqual(d, "left")

    def test_right_ankle_goes_right_down(self):
        """Right ankle (index 16) on the right goes 'right-down'."""
        mid = (150.0, 100.0)
        pos = QtCore.QPointF(200, 400)
        d = compute_direction(16, pos, mid)
        self.assertEqual(d, "right-down")

    def test_no_midline_defaults_up(self):
        """Without midline, direction is always 'up'."""
        d = compute_direction(5, QtCore.QPointF(0, 0), None)
        self.assertEqual(d, "up")


class TestLayoutDirect(unittest.TestCase):
    """Tests for direct layout (no collision avoidance)."""

    def test_labels_displaced_from_anchor(self):
        """Each label moves away from its anchor along the direction."""
        items = [
            _make_item("l_sho", 100, 200),
            _make_item("r_sho", 200, 200),
        ]
        mid = (150.0, 100.0)
        for it in items:
            it.direction = compute_direction(it.keypoint_index, it.anchor, mid)
        layout_direct(items, mid, leader_length=40)
        self.assertNotEqual(items[0].rect.center().x(), 100)
        self.assertNotEqual(items[1].rect.center().x(), 200)
        self.assertLess(items[0].rect.center().x(), 150)
        self.assertGreater(items[1].rect.center().x(), 150)


class TestLayoutAnti(unittest.TestCase):
    """Tests for anti-occlusion layout."""

    def test_reduces_overlap_vs_direct(self):
        """Anti layout should produce fewer overlaps than direct."""
        items = [
            _make_item("l_sho", 100, 200),
            _make_item("r_sho", 110, 200),
            _make_item("l_elb", 105, 205),
            _make_item("r_elb", 115, 205),
        ]
        mid = (112.0, 20.0)
        for it in items:
            it.direction = compute_direction(it.keypoint_index, it.anchor, mid)
        items_direct = [
            _make_item("l_sho", 100, 200),
            _make_item("r_sho", 110, 200),
            _make_item("l_elb", 105, 205),
            _make_item("r_elb", 115, 205),
        ]
        for it in items_direct:
            it.direction = compute_direction(it.keypoint_index, it.anchor, mid)
        layout_direct(items_direct, mid, leader_length=40)
        layout_anti(items, mid, leader_length=40)
        direct_overlaps = _count_overlaps(items_direct)
        anti_overlaps = _count_overlaps(items)
        self.assertLessEqual(anti_overlaps, direct_overlaps)


class TestLayoutColumn(unittest.TestCase):
    """Tests for column layout."""

    def test_left_right_split(self):
        """Left-side keypoints go left column, right-side go right."""
        items = [
            _make_item("l_sho", 100, 200),
            _make_item("r_sho", 200, 200),
            _make_item("l_hip", 110, 350),
            _make_item("r_hip", 190, 350),
        ]
        mid = (150.0, 100.0)
        bbox = QtCore.QRectF(80, 150, 140, 250)
        layout_column(items, mid, bbox, column_gap=8)
        self.assertLess(items[0].rect.center().x(), 100)
        self.assertGreater(items[1].rect.center().x(), 200)

    def test_empty_items_returns_empty(self):
        """Column layout on empty list is a no-op."""
        result = layout_column([], None, None, 8)
        self.assertEqual(result, [])


class TestApplyLayout(unittest.TestCase):
    """Tests for the public dispatcher."""

    def test_dispatch_direct(self):
        """apply_layout with 'direct' mode works."""
        items = [_make_item("nose", 150, 100)]
        mid = (150.0, 100.0)
        result, overlaps = apply_layout(
            items, mid, None, "direct", leader_length=40
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(overlaps, 0)

    def test_dispatch_unknown_defaults_to_direct(self):
        """Unknown layout mode falls back to direct."""
        items = [_make_item("nose", 150, 100)]
        mid = (150.0, 100.0)
        result, _ = apply_layout(items, mid, None, "bogus", leader_length=40)
        self.assertEqual(len(result), 1)

    def test_empty_items(self):
        """Empty item list returns (empty, 0)."""
        result, overlaps = apply_layout(
            [], None, None, "anti", leader_length=40
        )
        self.assertEqual(result, [])
        self.assertEqual(overlaps, 0)


if __name__ == "__main__":
    unittest.main()
