"""Smoke test for PoseRenderer.

Verifies that the renderer can draw a full pose scene (bbox, skeleton,
keypoints, labels) without crashing and returns a valid overlap count.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.views.labeling.widgets.pose_label import (
    PoseDisplayConfig,
    PoseRenderer,
)


class _FakeShape:
    """Minimal shape stand-in for renderer testing."""

    def __init__(self, shape_type, label, x, y, group_id, points=None):
        self.shape_type = shape_type
        self.label = label
        self.group_id = group_id
        self.points = points or [QtCore.QPointF(x, y)]
        self.selected = False
        self.visible = True
        self.hidden_by_filter = False
        self.line_color = QtGui.QColor(0, 255, 0)


def _build_person(gid, ox, oy):
    """Build a person rectangle + 17 COCO keypoints."""
    shapes = []
    shapes.append(
        _FakeShape(
            "rectangle",
            "person",
            ox,
            oy,
            gid,
            [
                QtCore.QPointF(ox - 30, oy - 20),
                QtCore.QPointF(ox + 130, oy + 400),
            ],
        )
    )
    offsets = [
        ("nose", 50, 20),
        ("l_eye", 40, 10),
        ("r_eye", 60, 10),
        ("l_ear", 30, 15),
        ("r_ear", 70, 15),
        ("l_sho", 0, 80),
        ("r_sho", 100, 80),
        ("l_elb", -10, 170),
        ("r_elb", 110, 160),
        ("l_wri", -20, 250),
        ("r_wri", 120, 240),
        ("l_hip", 20, 230),
        ("r_hip", 80, 230),
        ("l_knee", 15, 300),
        ("r_knee", 85, 300),
        ("l_ank", 10, 360),
        ("r_ank", 90, 360),
    ]
    for label, dx, dy in offsets:
        shapes.append(_FakeShape("point", label, ox + dx, oy + dy, gid))
    return shapes


class TestPoseRendererSmoke(unittest.TestCase):
    """Verify renderer runs without exceptions."""

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or (
            QtWidgets.QApplication([])
        )

    def test_render_single_person(self):
        """Render one person and check overlap count >= 0."""
        shapes = _build_person(gid=0, ox=200, oy=100)
        img = QtGui.QImage(800, 600, QtGui.QImage.Format.Format_ARGB32)
        img.fill(QtCore.Qt.GlobalColor.black)
        p = QtGui.QPainter(img)
        cfg = PoseDisplayConfig(enabled=True)
        r = PoseRenderer(cfg)
        count = r.render(p, shapes, img.size(), 1.0)
        p.end()
        self.assertGreaterEqual(count, 0)

    def test_render_two_persons(self):
        """Render two persons and verify no crash."""
        shapes = _build_person(gid=0, ox=150, oy=100)
        shapes += _build_person(gid=1, ox=450, oy=100)
        img = QtGui.QImage(800, 600, QtGui.QImage.Format.Format_ARGB32)
        img.fill(QtCore.Qt.GlobalColor.black)
        p = QtGui.QPainter(img)
        cfg = PoseDisplayConfig(enabled=True, layout_mode="anti")
        r = PoseRenderer(cfg)
        count = r.render(p, shapes, img.size(), 1.0)
        p.end()
        self.assertGreaterEqual(count, 0)

    def test_render_with_scale(self):
        """Render at scale=2.0 to verify /scale compensation."""
        shapes = _build_person(gid=0, ox=200, oy=100)
        img = QtGui.QImage(1600, 1200, QtGui.QImage.Format.Format_ARGB32)
        img.fill(QtCore.Qt.GlobalColor.black)
        p = QtGui.QPainter(img)
        p.scale(2.0, 2.0)
        cfg = PoseDisplayConfig(enabled=True)
        r = PoseRenderer(cfg)
        count = r.render(p, shapes, img.size(), 2.0)
        p.end()
        self.assertGreaterEqual(count, 0)

    def test_render_all_layout_modes(self):
        """Render with each layout mode."""
        shapes = _build_person(gid=0, ox=200, oy=100)
        for mode in ("direct", "anti", "column"):
            img = QtGui.QImage(800, 600, QtGui.QImage.Format.Format_ARGB32)
            img.fill(QtCore.Qt.GlobalColor.black)
            p = QtGui.QPainter(img)
            cfg = PoseDisplayConfig(enabled=True, layout_mode=mode)
            r = PoseRenderer(cfg)
            count = r.render(p, shapes, img.size(), 1.0)
            p.end()
            self.assertGreaterEqual(count, 0)

    def test_render_person_color_mode(self):
        """Render with person coloring mode."""
        shapes = _build_person(gid=0, ox=200, oy=100)
        img = QtGui.QImage(800, 600, QtGui.QImage.Format.Format_ARGB32)
        img.fill(QtCore.Qt.GlobalColor.black)
        p = QtGui.QPainter(img)
        cfg = PoseDisplayConfig(enabled=True, color_mode="person")
        r = PoseRenderer(cfg)
        count = r.render(p, shapes, img.size(), 1.0)
        p.end()
        self.assertGreaterEqual(count, 0)

    def test_render_empty_shapes(self):
        """Empty shapes list returns 0 overlap."""
        img = QtGui.QImage(800, 600, QtGui.QImage.Format.Format_ARGB32)
        p = QtGui.QPainter(img)
        cfg = PoseDisplayConfig(enabled=True)
        r = PoseRenderer(cfg)
        count = r.render(p, [], img.size(), 1.0)
        p.end()
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
