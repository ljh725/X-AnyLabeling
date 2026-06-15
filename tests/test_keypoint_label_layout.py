import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6 import QtCore
from anylabeling.views.labeling.widgets.keypoint_label_layout import (
    LabelItem,
    _clamp_to_canvas,
    layout_keypoint_labels,
)


def _make_item(gid, px, py, w=40, h=14):
    rect = QtCore.QRect(int(px + 5), int(py - 15), w, h)
    return LabelItem(
        shape_ref=None, group_id=gid, anchor=QtCore.QPointF(px, py), rect=rect
    )


class TestKeypointLabelLayout(unittest.TestCase):
    def test_single_label_unchanged(self):
        items = [_make_item(gid=1, px=100, py=100)]
        laid, leaders = layout_keypoint_labels(
            items, canvas_size=QtCore.QSize(800, 600), step=14, max_tries=8
        )
        self.assertEqual(len(laid), 1)
        self.assertEqual(laid[0].rect, items[0].rect)
        self.assertEqual(leaders, [])

    def test_two_overlapping_labels_get_separated(self):
        items = [
            _make_item(gid=1, px=100, py=100),
            _make_item(gid=1, px=110, py=100),
        ]
        laid, _ = layout_keypoint_labels(items, QtCore.QSize(800, 600))
        self.assertEqual(len(laid), 2)
        self.assertFalse(
            laid[0]
            .rect.adjusted(-2, -2, 2, 2)
            .intersects(laid[1].rect.adjusted(-2, -2, 2, 2))
        )

    def test_different_groups_still_do_not_overlap(self):
        items = [
            _make_item(gid=1, px=100, py=100),
            _make_item(gid=2, px=105, py=100),
        ]
        laid, _ = layout_keypoint_labels(items, QtCore.QSize(800, 600))
        self.assertFalse(laid[0].rect.intersects(laid[1].rect))

    def test_leader_line_emitted_when_moved_far(self):
        items = [
            _make_item(gid=1, px=100, py=100),
            _make_item(gid=1, px=102, py=100),
            _make_item(gid=1, px=104, py=100),
        ]
        _, leaders = layout_keypoint_labels(items, QtCore.QSize(800, 600))
        self.assertGreaterEqual(len(leaders), 1)
        for anchor_pt, edge_pt in leaders:
            self.assertIsInstance(anchor_pt, QtCore.QPointF)
            self.assertIsInstance(edge_pt, QtCore.QPoint)

    def test_obstacles_are_avoided(self):
        obs = [QtCore.QRect(105, 85, 40, 14)]
        items = [_make_item(gid=1, px=100, py=100)]
        laid, _ = layout_keypoint_labels(
            items, QtCore.QSize(800, 600), obstacles=obs
        )
        self.assertFalse(laid[0].rect.intersects(obs[0]))

    def test_input_order_is_preserved(self):
        items = [
            _make_item(gid=2, px=100, py=100),
            _make_item(gid=1, px=200, py=200),
            _make_item(gid=2, px=110, py=100),
        ]
        laid, _ = layout_keypoint_labels(items, QtCore.QSize(800, 600))
        self.assertEqual([it.group_id for it in laid], [2, 1, 2])
        for orig, new in zip(items, laid):
            self.assertEqual(orig.anchor, new.anchor)
            self.assertEqual(orig.group_id, new.group_id)

    def test_label_stays_inside_canvas_near_edge(self):
        rect = QtCore.QRect(780, 100, 40, 14)
        item = LabelItem(
            shape_ref=None,
            group_id=1,
            anchor=QtCore.QPointF(790, 107),
            rect=rect,
        )
        laid, _ = layout_keypoint_labels([item], QtCore.QSize(800, 600))
        canvas = QtCore.QRect(0, 0, 800, 600)
        self.assertTrue(canvas.contains(laid[0].rect))

    def test_fallback_keeps_original_position(self):
        item = _make_item(gid=1, px=100, py=100)
        obs = [QtCore.QRect(0, 0, 800, 600)]
        laid, _ = layout_keypoint_labels(
            items=[item],
            canvas_size=QtCore.QSize(800, 600),
            obstacles=obs,
        )
        canvas = QtCore.QRect(0, 0, 800, 600)
        self.assertTrue(canvas.contains(laid[0].rect))

    def test_three_close_points_no_mutual_overlap(self):
        items = [
            _make_item(gid=7, px=200, py=200),
            _make_item(gid=7, px=206, py=200),
            _make_item(gid=7, px=212, py=200),
        ]
        laid, _ = layout_keypoint_labels(
            items, QtCore.QSize(1000, 800)
        )
        for i in range(len(laid)):
            for j in range(i + 1, len(laid)):
                a = laid[i].rect.adjusted(-2, -2, 2, 2)
                b = laid[j].rect.adjusted(-2, -2, 2, 2)
                self.assertFalse(
                    a.intersects(b),
                    f"labels {i} and {j} still overlap",
                )

    def test_out_of_bounds_original_gets_clamped(self):
        rect = QtCore.QRect(900, 100, 40, 14)
        item = LabelItem(
            shape_ref=None,
            group_id=1,
            anchor=QtCore.QPointF(920, 107),
            rect=rect,
        )
        laid, _ = layout_keypoint_labels([item], QtCore.QSize(800, 600))
        canvas = QtCore.QRect(0, 0, 800, 600)
        self.assertTrue(canvas.contains(laid[0].rect))

    def test_gap_separation(self):
        items = [
            _make_item(gid=1, px=100, py=100),
            _make_item(gid=1, px=110, py=100),
        ]
        laid, _ = layout_keypoint_labels(items, QtCore.QSize(800, 600), gap=10)
        self.assertFalse(
            laid[0].rect.adjusted(-10, -10, 10, 10).intersects(laid[1].rect)
        )
        self.assertFalse(
            laid[1].rect.adjusted(-10, -10, 10, 10).intersects(laid[0].rect)
        )

    def test_empty_items_returns_empty(self):
        laid, leaders = layout_keypoint_labels([], QtCore.QSize(800, 600))
        self.assertEqual(laid, [])
        self.assertEqual(leaders, [])

    def test_none_group_id(self):
        items = [
            _make_item(gid=None, px=100, py=100),
            _make_item(gid=None, px=110, py=100),
        ]
        laid, _ = layout_keypoint_labels(items, QtCore.QSize(800, 600))
        self.assertEqual(len(laid), 2)
        self.assertFalse(laid[0].rect.intersects(laid[1].rect))

    def test_fallback_with_all_directions_blocked(self):
        # Obstacle covers the whole canvas: no collision-free position
        # exists, so the fallback must return the clamped original rect.
        item = _make_item(gid=1, px=100, py=100)
        canvas = QtCore.QRect(0, 0, 200, 200)
        obs = [QtCore.QRect(0, 0, 200, 200)]
        laid, _ = layout_keypoint_labels(
            items=[item],
            canvas_size=QtCore.QSize(200, 200),
            obstacles=obs,
            step=14,
            max_tries=8,
        )
        expected = _clamp_to_canvas(item.rect, canvas)
        self.assertEqual(laid[0].rect, expected)
