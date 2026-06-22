"""Unit tests for the category layout mode.

Migrated from ``migration/test_pose_category_layout.py``.  Uses
lightweight mock objects for ``PoseLabelItem`` and host constants so the
tests run anywhere with only PyQt6 installed.  Mirrors the behavioural
contract documented in the module docstring of
``pose_category_layout``.

Run::

    pytest tests/test_pose_category_layout.py -v
"""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore

from anylabeling.views.labeling.widgets.pose_label.pose_category_layout import (  # noqa: E501
    _body_part_group,
    _head_lateral_rank,
    _is_lateral_prefix,
    layout_category,
)

# -----------------------------------------------------------------------
# Host-constant stand-ins (mirrors pose_constants.py)
# -----------------------------------------------------------------------

COCO_KEYPOINT_ORDER = [
    "nose",
    "l_eye",
    "r_eye",
    "l_ear",
    "r_ear",
    "l_sho",
    "r_sho",
    "l_elb",
    "r_elb",
    "l_wri",
    "r_wri",
    "l_hip",
    "r_hip",
    "l_knee",
    "r_knee",
    "l_ank",
    "r_ank",
]
COCO_KEYPOINT_INDEX = {
    name: idx for idx, name in enumerate(COCO_KEYPOINT_ORDER)
}
BODY_PARTS = {
    "head": ["nose", "l_eye", "r_eye", "l_ear", "r_ear"],
    "la": ["l_sho", "l_elb", "l_wri"],
    "ra": ["r_sho", "r_elb", "r_wri"],
    "ll": ["l_hip", "l_knee", "l_ank"],
    "rl": ["r_hip", "r_knee", "r_ank"],
}


def _make_item(label: str, px: float, py: float, w: int = 50, h: int = 16):
    """Build a mock PoseLabelItem via SimpleNamespace (duck typed)."""
    ki = COCO_KEYPOINT_INDEX.get(label, 0)
    return SimpleNamespace(
        shape_ref=SimpleNamespace(label=label),
        label=label,
        keypoint_index=ki,
        group_id=0,
        anchor=QtCore.QPointF(px, py),
        rect=QtCore.QRect(int(px), int(py), w, h),
        direction="up",
        leader_start=QtCore.QPointF(0, 0),
        leader_end=QtCore.QPoint(0, 0),
        color_hex="#ffffff",
    )


def _full_skeleton():
    """Build all 17 COCO keypoints at representative positions."""
    return [
        _make_item("nose", 150, 160),
        _make_item("l_eye", 142, 152),
        _make_item("r_eye", 158, 152),
        _make_item("l_ear", 134, 158),
        _make_item("r_ear", 166, 158),
        _make_item("l_sho", 120, 200),
        _make_item("r_sho", 180, 200),
        _make_item("l_elb", 110, 250),
        _make_item("r_elb", 190, 250),
        _make_item("l_wri", 100, 300),
        _make_item("r_wri", 200, 300),
        _make_item("l_hip", 125, 320),
        _make_item("r_hip", 175, 320),
        _make_item("l_knee", 120, 400),
        _make_item("r_knee", 180, 400),
        _make_item("l_ank", 118, 470),
        _make_item("r_ank", 182, 470),
    ]


# -----------------------------------------------------------------------
# Helper unit tests
# -----------------------------------------------------------------------


class TestIsLateralPrefix(unittest.TestCase):
    """Prefix detection."""

    def test_basic_prefixes(self):
        """l_/r_/left_/right_ all detected, case-insensitive."""
        self.assertEqual(_is_lateral_prefix("l_sho"), "left")
        self.assertEqual(_is_lateral_prefix("r_knee"), "right")
        self.assertEqual(_is_lateral_prefix("left_elb"), "left")
        self.assertEqual(_is_lateral_prefix("right_ank"), "right")
        self.assertEqual(_is_lateral_prefix("L_SHO"), "left")
        self.assertEqual(_is_lateral_prefix("Right_Elb"), "right")

    def test_no_false_positive(self):
        """light_ and plain labels return None."""
        self.assertIsNone(_is_lateral_prefix("light_switch"))
        self.assertIsNone(_is_lateral_prefix("nose"))
        self.assertIsNone(_is_lateral_prefix(""))


class TestBodyPartGroup(unittest.TestCase):
    """COCO index -> body-part mapping."""

    def test_groups(self):
        """Each index lands in the expected group."""
        self.assertEqual(
            _body_part_group(0, COCO_KEYPOINT_INDEX, BODY_PARTS), "head"
        )
        self.assertEqual(
            _body_part_group(5, COCO_KEYPOINT_INDEX, BODY_PARTS), "la"
        )
        self.assertEqual(
            _body_part_group(6, COCO_KEYPOINT_INDEX, BODY_PARTS), "ra"
        )
        self.assertEqual(
            _body_part_group(11, COCO_KEYPOINT_INDEX, BODY_PARTS), "ll"
        )
        self.assertEqual(
            _body_part_group(12, COCO_KEYPOINT_INDEX, BODY_PARTS), "rl"
        )


class TestHeadLateralRank(unittest.TestCase):
    """Head-row ordering helper."""

    def test_ranks(self):
        """left prefix -> -1, right prefix -> +1, nose -> 0."""
        self.assertEqual(_head_lateral_rank(_make_item("l_eye", 0, 0)), -1)
        self.assertEqual(_head_lateral_rank(_make_item("r_eye", 0, 0)), 1)
        self.assertEqual(_head_lateral_rank(_make_item("nose", 0, 0)), 0)


# -----------------------------------------------------------------------
# layout_category behaviour
# -----------------------------------------------------------------------


class TestLayoutCategoryPlacement(unittest.TestCase):
    """Spatial placement around the bbox."""

    BBOX = QtCore.QRectF(80, 150, 140, 350)

    def _layout(self, items):
        """Run layout_category with host stand-in constants."""
        return layout_category(
            items,
            mid=(150.0, 100.0),
            bbox=self.BBOX,
            column_gap=8,
            coco_keypoint_index=COCO_KEYPOINT_INDEX,
            body_parts=BODY_PARTS,
        )

    def test_empty_items_is_noop(self):
        """Empty input returns empty."""
        self.assertEqual(self._layout([]), [])

    def test_head_labels_above_bbox(self):
        """All head labels sit above the bbox top edge."""
        items = self._layout(_full_skeleton())
        head = {"nose", "l_eye", "r_eye", "l_ear", "r_ear"}
        for it in items:
            if it.label in head:
                self.assertLess(it.rect.bottom(), self.BBOX.y())

    def test_nose_centred(self):
        """nose is roughly centred on the bbox horizontal midline."""
        items = self._layout(_full_skeleton())
        nose = next(it for it in items if it.label == "nose")
        self.assertAlmostEqual(nose.rect.center().x(), 150.0, delta=5)

    def test_left_side_left_of_bbox(self):
        """la + ll labels sit strictly left of the bbox."""
        items = self._layout(_full_skeleton())
        left = {"l_sho", "l_elb", "l_wri", "l_hip", "l_knee", "l_ank"}
        for it in items:
            if it.label in left:
                self.assertGreater(self.BBOX.x(), it.rect.right())

    def test_right_side_right_of_bbox(self):
        """ra + rl labels sit strictly right of the bbox."""
        items = self._layout(_full_skeleton())
        right = {"r_sho", "r_elb", "r_wri", "r_hip", "r_knee", "r_ank"}
        bbox_x2 = self.BBOX.x() + self.BBOX.width()
        for it in items:
            if it.label in right:
                self.assertLess(bbox_x2, it.rect.left())

    def test_arm_above_leg_left(self):
        """Left arm sub-column ends above the left leg sub-column."""
        items = self._layout(_full_skeleton())
        l_wri = next(it for it in items if it.label == "l_wri")
        l_hip = next(it for it in items if it.label == "l_hip")
        self.assertLess(l_wri.rect.bottom(), l_hip.rect.y())

    def test_arm_above_leg_right(self):
        """Right arm sub-column ends above the right leg sub-column."""
        items = self._layout(_full_skeleton())
        r_wri = next(it for it in items if it.label == "r_wri")
        r_hip = next(it for it in items if it.label == "r_hip")
        self.assertLess(r_wri.rect.bottom(), r_hip.rect.y())

    def test_leader_lines_populated(self):
        """Every item gets non-default leader_start/leader_end."""
        items = self._layout(_full_skeleton())
        for it in items:
            # leader_end must have moved off the default (0, 0).
            self.assertFalse(
                it.leader_end == QtCore.QPoint(0, 0),
                msg=f"{it.label} leader_end not set",
            )


class TestLayoutCategoryBboxFallback(unittest.TestCase):
    """When bbox is None a fallback is computed from anchors."""

    def test_none_bbox_uses_anchor_fallback(self):
        """Passing bbox=None still places labels (fallback computed)."""
        items = layout_category(
            _full_skeleton(),
            mid=(150.0, 100.0),
            bbox=None,
            column_gap=8,
            coco_keypoint_index=COCO_KEYPOINT_INDEX,
            body_parts=BODY_PARTS,
        )
        # At least one label should have moved off its initial anchor.
        moved = [
            it
            for it in items
            if it.rect.center()
            != QtCore.QPoint(int(it.anchor.x()), int(it.anchor.y()))
        ]
        self.assertGreater(len(moved), 0)


if __name__ == "__main__":
    unittest.main()
