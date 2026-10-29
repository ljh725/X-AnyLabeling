"""Tests for combined label/group filtering with invert and manual hides."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.views.labeling.label_widget import LabelingWidget
from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.shape_filter import (
    desired_visibility,
    has_active_filter,
    matches_filter,
)


def make_item(shape, checked=True):
    """Wrap a shape the way LabelListWidgetItem exposes it."""
    state = (
        QtCore.Qt.CheckState.Checked
        if checked
        else QtCore.Qt.CheckState.Unchecked
    )
    return SimpleNamespace(shape=lambda: shape, checkState=Mock(return_value=state))


def make_shape(label, group_id=None):
    shape = Shape(label=label, shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(0, 0),
        QtCore.QPointF(10, 0),
        QtCore.QPointF(10, 10),
    ]
    shape.close()
    shape.group_id = group_id
    return shape


class TestFilterRules(unittest.TestCase):
    def test_no_filter_keeps_everything_visible(self):
        shape = make_shape("cat")
        self.assertFalse(has_active_filter("", "-1"))
        self.assertTrue(desired_visibility(shape))
        self.assertTrue(desired_visibility(shape, invert=True))
        self.assertTrue(desired_visibility(shape, label="", gid=""))

    def test_label_filter_matches_and_hides_the_rest(self):
        cat = make_shape("cat")
        dog = make_shape("dog")
        self.assertTrue(desired_visibility(cat, label="cat"))
        self.assertFalse(desired_visibility(dog, label="cat"))

    def test_group_filter_matches_numeric_and_string_ids(self):
        first = make_shape("cat", group_id=3)
        second = make_shape("dog", group_id=None)
        self.assertTrue(desired_visibility(first, gid="3"))
        self.assertFalse(desired_visibility(second, gid="3"))
        self.assertFalse(desired_visibility(second, gid=3))

    def test_label_and_group_filters_combine(self):
        match = make_shape("cat", group_id=2)
        wrong_label = make_shape("dog", group_id=2)
        wrong_group = make_shape("cat", group_id=5)

        self.assertTrue(matches_filter(match, "cat", "2"))
        self.assertFalse(matches_filter(wrong_label, "cat", "2"))
        self.assertFalse(matches_filter(wrong_group, "cat", "2"))

    def test_invert_flips_only_while_a_filter_is_active(self):
        cat = make_shape("cat")
        dog = make_shape("dog")
        self.assertFalse(desired_visibility(cat, label="cat", invert=True))
        self.assertTrue(desired_visibility(dog, label="cat", invert=True))
        self.assertTrue(desired_visibility(cat, invert=True))

    def test_manual_hide_wins_over_filter_and_invert(self):
        cat = make_shape("cat")
        self.assertFalse(
            desired_visibility(cat, label="cat", manually_hidden=True)
        )
        self.assertFalse(
            desired_visibility(cat, label="other", invert=True,
                               manually_hidden=True)
        )

    def test_label_visibility_wins_over_filter(self):
        cat = make_shape("cat")
        self.assertFalse(
            desired_visibility(cat, label="cat", label_visible=False)
        )


class TestFilterApplication(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance()
        if cls.app is None:
            cls.app = QtWidgets.QApplication([])

    def make_host(self, label="", gid="-1", invert=False, manual=()):
        host = SimpleNamespace(
            label_filter_combobox=SimpleNamespace(
                text_box=SimpleNamespace(currentText=lambda: label)
            ),
            gid_filter_combobox=SimpleNamespace(
                gid_box=SimpleNamespace(currentText=lambda: gid)
            ),
            label_info={},
            _manually_hidden_shapes=set(manual),
            _invert_shape_filter=invert,
            _invert_filter_actions=[],
            canvas=SimpleNamespace(shapes=[]),
        )
        host._sync_invert_filter_actions = Mock()
        host.sync_calls = []
        host._sync_label_list_visibility = (
            lambda predicate: host.sync_calls.append(predicate)
        )
        return host

    def predicate_for(self, host):
        LabelingWidget._apply_shape_filter_visibility(host)
        self.assertEqual(len(host.sync_calls), 1)
        return host.sync_calls[0]

    def test_combined_filter_drives_visibility(self):
        host = self.make_host(label="cat", gid="2")
        predicate = self.predicate_for(host)

        match = make_item(make_shape("cat", group_id=2))
        wrong_label = make_item(make_shape("dog", group_id=2))
        wrong_group = make_item(make_shape("cat", group_id=5))

        self.assertTrue(predicate(match))
        self.assertFalse(predicate(wrong_label))
        self.assertFalse(predicate(wrong_group))

    def test_invert_flag_is_forwarded(self):
        host = self.make_host(label="cat", invert=True)
        predicate = self.predicate_for(host)

        self.assertFalse(predicate(make_item(make_shape("cat"))))
        self.assertTrue(predicate(make_item(make_shape("dog"))))

    def test_manual_hidden_shapes_stay_hidden(self):
        cat = make_shape("cat")
        host = self.make_host(label="cat", manual={cat})
        predicate = self.predicate_for(host)

        self.assertFalse(predicate(make_item(cat)))

    def test_manual_hide_is_recorded_from_the_item_checkbox(self):
        shape = make_shape("cat")
        item = make_item(shape, checked=False)
        host = SimpleNamespace(
            canvas=SimpleNamespace(set_shape_visible=Mock()),
            _manually_hidden_shapes=set(),
            _update_select_toggle_button_tooltip=Mock(),
        )

        LabelingWidget.label_item_changed(host, item)

        self.assertIn(shape, host._manually_hidden_shapes)
        host.canvas.set_shape_visible.assert_called_once_with(shape, False)

        item = make_item(shape, checked=True)
        LabelingWidget.label_item_changed(host, item)
        self.assertNotIn(shape, host._manually_hidden_shapes)

    def test_bulk_visibility_resets_manual_memory(self):
        hidden = make_shape("cat")
        host = SimpleNamespace(
            label_list=[],
            label_info={},
            _manually_hidden_shapes={hidden},
            _sync_label_list_visibility=Mock(),
        )

        LabelingWidget._set_all_objects_visibility(host, True)

        self.assertEqual(host._manually_hidden_shapes, set())
        host._sync_label_list_visibility.assert_called_once()

    def test_invert_action_is_disabled_and_cleared_without_filter(self):
        action = QtGui.QAction("invert")
        action.setCheckable(True)
        action.setChecked(True)
        host = SimpleNamespace(
            _invert_shape_filter=True,
            _invert_filter_actions=[action],
            _has_active_shape_filter=Mock(return_value=False),
        )

        LabelingWidget._sync_invert_filter_actions(host)

        self.assertFalse(action.isChecked())
        self.assertFalse(action.isEnabled())
        self.assertFalse(host._invert_shape_filter)

    def test_invert_action_tracks_filter_state(self):
        action = QtGui.QAction("invert")
        action.setCheckable(True)
        host = SimpleNamespace(
            _invert_shape_filter=True,
            _invert_filter_actions=[action],
            _has_active_shape_filter=Mock(return_value=True),
        )

        LabelingWidget._sync_invert_filter_actions(host)

        self.assertTrue(action.isChecked())
        self.assertTrue(action.isEnabled())


if __name__ == "__main__":
    unittest.main()
