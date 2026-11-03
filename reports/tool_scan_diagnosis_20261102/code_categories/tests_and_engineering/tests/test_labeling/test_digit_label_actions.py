"""Digit key behaviour tests: draw when idle, relabel when selected."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

from anylabeling.views.labeling.label_widget import LabelingWidget
from anylabeling.views.labeling.shape import Shape


def make_shape(label, **fields):
    shape = Shape(label=label, shape_type="polygon")
    shape.points = [
        QtCore.QPointF(10.0, 10.0),
        QtCore.QPointF(30.0, 10.0),
        QtCore.QPointF(30.0, 30.0),
    ]
    shape.close()
    for key, value in fields.items():
        setattr(shape, key, value)
    return shape


class FakeCanvas:
    def __init__(self, shapes=(), selected=()):
        self.shapes = list(shapes)
        self.selected_shapes = list(selected)
        self.current = None
        self.shapes_backups = []
        self.rectangle_size_invalidations = 0

    def store_shapes(self):
        self.shapes_backups.append([shape.copy() for shape in self.shapes])

    def invalidate_rectangle_size_issues(self):
        self.rectangle_size_invalidations += 1

    @property
    def is_shape_restorable(self):
        return len(self.shapes_backups) >= 2


class DigitHost:
    """Build a labeling-widget double exercising the real helpers."""

    def __init__(self, shapes, selected, mapping, draft=None):
        self.canvas = FakeCanvas(shapes, selected)
        self.drawing_digit_shortcuts = mapping
        self.digit_to_label = None
        self.toggle_draw_mode = Mock()
        self.validate_label = Mock(return_value=True)
        self.error_message = Mock()
        self.attributes = {}
        self.label_list = SimpleNamespace(
            find_item_by_shape=Mock(return_value=None)
        )
        self.unique_label_list = SimpleNamespace(
            find_items_by_label=Mock(return_value=True),
            create_item_from_label=Mock(),
            addItem=Mock(),
            set_item_label=Mock(),
        )
        self._update_shape_color = Mock()
        self._get_rgb_by_label = Mock(return_value=(0, 0, 0))
        self.actions = SimpleNamespace(undo=Mock())
        self._config = {"validate_label": None}
        self.set_dirty = Mock()
        self._refresh_shape_filters = Mock()
        self.tr = lambda text: text
        self.rectangle_creation = SimpleNamespace(draft=draft)
        self._resolve_label_attributes = (
            lambda shape, label: LabelingWidget._resolve_label_attributes(
                self, shape, label
            )
        )
        self._apply_field_patch = (
            lambda target, values, touched: LabelingWidget._apply_field_patch(
                self, target, values, touched
            )
        )
        self._relabel_selection = (
            lambda target, label: LabelingWidget._relabel_selection(
                self, target, label
            )
        )


MAPPING = {3: {"label": "car", "mode": "rectangle"}}


class TestDigitDrawOrRelabel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance()
        if cls.app is None:
            cls.app = QtWidgets.QApplication([])

    def test_no_selection_starts_drawing_with_mapped_label(self):
        host = DigitHost([], [], MAPPING)

        LabelingWidget.create_digit_mode(host, 3)

        self.assertEqual(host.digit_to_label, "car")
        host.toggle_draw_mode.assert_called_once_with(
            edit=False, create_mode="rectangle"
        )
        self.assertEqual(host.canvas.shapes_backups, [])

    def test_selection_relabels_instead_of_drawing(self):
        first = make_shape("person", group_id=1, flags={"a": True})
        second = make_shape("dog", group_id=2, description="kept")
        host = DigitHost([first, second], [first, second], MAPPING)

        LabelingWidget.create_digit_mode(host, 3)

        self.assertEqual([first.label, second.label], ["car", "car"])
        self.assertEqual(first.group_id, 1)
        self.assertEqual(second.group_id, 2)
        self.assertEqual(first.flags, {"a": True})
        self.assertEqual(second.description, "kept")
        self.assertIsNone(host.digit_to_label)
        host.toggle_draw_mode.assert_not_called()

    def test_clicking_digit_twice_does_not_draw_after_relabel(self):
        shape = make_shape("person")
        host = DigitHost([shape], [shape], MAPPING)

        LabelingWidget.create_digit_mode(host, 3)
        LabelingWidget.create_digit_mode(host, 3)

        self.assertEqual(shape.label, "car")
        host.toggle_draw_mode.assert_not_called()

    def test_multi_selection_relabel_is_single_undo_step(self):
        shapes = [make_shape("a"), make_shape("b"), make_shape("c")]
        host = DigitHost(shapes, list(shapes), MAPPING)

        LabelingWidget.create_digit_mode(host, 3)

        self.assertEqual([shape.label for shape in shapes], ["car"] * 3)
        self.assertTrue(host.canvas.is_shape_restorable)
        self.assertEqual(len(host.canvas.shapes_backups), 2)
        host.set_dirty.assert_called_once()

    def test_locked_shapes_are_not_relabelled(self):
        locked = make_shape("locked", locked=True)
        unlocked = make_shape("open")
        host = DigitHost([locked, unlocked], [locked, unlocked], MAPPING)

        LabelingWidget.create_digit_mode(host, 3)

        self.assertEqual(locked.label, "locked")
        self.assertEqual(unlocked.label, "car")

    def test_fully_locked_selection_never_starts_drawing(self):
        locked = make_shape("locked", locked=True)
        host = DigitHost([locked], [locked], MAPPING)

        LabelingWidget.create_digit_mode(host, 3)

        self.assertEqual(locked.label, "locked")
        host.toggle_draw_mode.assert_not_called()
        self.assertIsNone(host.digit_to_label)

    def test_drawing_in_progress_ignores_digit(self):
        shape = make_shape("person")
        host = DigitHost([shape], [shape], MAPPING)
        host.canvas.current = make_shape("draft")

        LabelingWidget.create_digit_mode(host, 3)

        self.assertEqual(shape.label, "person")
        host.toggle_draw_mode.assert_not_called()
        self.assertIsNone(host.digit_to_label)

    def test_active_extreme_draft_ignores_digit(self):
        shape = make_shape("person")
        host = DigitHost([shape], [shape], MAPPING, draft=object())

        LabelingWidget.create_digit_mode(host, 3)

        self.assertEqual(shape.label, "person")
        host.toggle_draw_mode.assert_not_called()

    def test_unmapped_digit_is_ignored(self):
        host = DigitHost([], [], MAPPING)

        LabelingWidget.create_digit_mode(host, 7)

        self.assertIsNone(host.digit_to_label)
        host.toggle_draw_mode.assert_not_called()

    def test_unsupported_mode_is_ignored(self):
        host = DigitHost(
            [], [], {1: {"label": "car", "mode": "spiral"}}
        )

        LabelingWidget.create_digit_mode(host, 1)

        self.assertIsNone(host.digit_to_label)
        host.toggle_draw_mode.assert_not_called()

    def test_invalid_label_keeps_selection_untouched(self):
        shape = make_shape("person")
        host = DigitHost([shape], [shape], MAPPING)
        host.validate_label = Mock(return_value=False)

        LabelingWidget.create_digit_mode(host, 3)

        self.assertEqual(shape.label, "person")
        host.error_message.assert_called_once()
        self.assertEqual(host.canvas.shapes_backups, [])
        host.toggle_draw_mode.assert_not_called()

    def test_mapping_uses_digit_index_directly(self):
        shape = make_shape("person")
        mapping = {0: {"label": "background", "mode": "rectangle"}}
        host = DigitHost([shape], [shape], mapping)

        LabelingWidget.create_digit_mode(host, 0)

        self.assertEqual(shape.label, "background")

    def test_missing_mapping_table_is_ignored(self):
        host = DigitHost([], [], None)

        LabelingWidget.create_digit_mode(host, 3)

        self.assertIsNone(host.digit_to_label)
        host.toggle_draw_mode.assert_not_called()


if __name__ == "__main__":
    unittest.main()
