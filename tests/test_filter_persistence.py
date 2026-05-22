import os
import types
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6 import QtWidgets

    from anylabeling.views.labeling.filter_state import FilterState
    from anylabeling.views.labeling.label_widget import LabelingWidget

    PYQT_AVAILABLE = True
except Exception:
    PYQT_AVAILABLE = False


class _FakeModel:
    def __init__(self, row_count):
        self._row_count = row_count

    def rowCount(self):
        return self._row_count


class _FakeLabelList(list):
    def model(self):
        return _FakeModel(len(self))


class _FakeCanvas:
    def __init__(self):
        self.update_calls = 0

    def update(self):
        self.update_calls += 1


class _FakeNavigatorDialog:
    def __init__(self, visible=True):
        self._visible = visible

    def isVisible(self):
        return self._visible


class _FakeFilterEngine:
    def __init__(self, changed=True):
        self.apply_calls = 0
        self.changed = changed

    def apply_label_visibility(self):
        self.apply_calls += 1
        return self.changed

    def compute_matches(self, *_args, **_kwargs):
        raise AssertionError("Should not compute matches without active filter")

    def sync_label_list_visibility(self, *_args, **_kwargs):
        raise AssertionError("Should not sync filtered visibility without active filter")


@unittest.skipUnless(
    PYQT_AVAILABLE, "PyQt6 is required for filter persistence tests"
)
class TestFilterPersistence(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance()
        if cls.app is None:
            cls.app = QtWidgets.QApplication([])

    def test_set_gid_and_type_values_update_state_when_blocked(self):
        widget = types.SimpleNamespace()
        widget._filter_state = FilterState()

        gid_box = QtWidgets.QComboBox()
        gid_box.addItems(["-1", "7"])
        gid_signals = []
        gid_box.currentIndexChanged.connect(lambda idx: gid_signals.append(idx))
        widget.gid_filter_combobox = types.SimpleNamespace(gid_box=gid_box)

        type_box = QtWidgets.QComboBox()
        type_box.addItems(["", "polygon"])
        type_signals = []
        type_box.currentIndexChanged.connect(
            lambda idx: type_signals.append(idx)
        )
        widget.shape_type_filter_combobox = types.SimpleNamespace(
            type_box=type_box
        )

        LabelingWidget.set_gid_filter_value(widget, "7", block_signal=True)
        LabelingWidget.set_shape_type_filter_value(
            widget, "polygon", block_signal=True
        )

        self.assertEqual(widget._filter_state.gid, "7")
        self.assertEqual(widget.gid_filter_combobox.gid_box.currentText(), "7")
        self.assertEqual(gid_signals, [])
        self.assertEqual(widget._filter_state.shape_type, "polygon")
        self.assertEqual(
            widget.shape_type_filter_combobox.type_box.currentText(),
            "polygon",
        )
        self.assertEqual(type_signals, [])

    def test_refresh_shape_filters_normalizes_pending_restore(self):
        widget = types.SimpleNamespace()
        widget._pending_filter_restore = types.SimpleNamespace(
            labels={"car"}, gid="", shape_type=None
        )
        widget._filter_state = FilterState(labels={"old"}, gid="9", shape_type="point")
        widget.label_list = _FakeLabelList()
        widget._filter_index = object()

        calls = []
        widget._rebuild_filter_index = lambda: calls.append("rebuild")
        widget._collect_filter_options = lambda: ({"car"}, set(), set())
        widget.update_combo_box = (
            lambda **kwargs: calls.append(("labels", kwargs))
        )
        widget.update_gid_box = lambda **kwargs: calls.append(("gid", kwargs))
        widget.update_shape_type_box = (
            lambda **kwargs: calls.append(("type", kwargs))
        )
        widget._apply_combined_shape_filters = (
            lambda: calls.append("apply")
        )

        LabelingWidget._refresh_shape_filters(widget)

        self.assertIsNone(widget._pending_filter_restore)
        self.assertEqual(widget._filter_state.labels, {"car"})
        self.assertEqual(widget._filter_state.gid, FilterState.DEFAULT_GID)
        self.assertEqual(
            widget._filter_state.shape_type, FilterState.DEFAULT_TYPE
        )
        self.assertEqual(widget._filter_index, None)
        self.assertIn("rebuild", calls)
        self.assertIn("apply", calls)

    def test_apply_combined_shape_filters_restores_visibility_without_filter(self):
        status_messages = []
        widget = types.SimpleNamespace()
        widget._filter_state = FilterState()
        widget._filter_navigation_active = False
        widget.label_list = _FakeLabelList()
        widget._filter_engine = _FakeFilterEngine(changed=True)
        widget.canvas = _FakeCanvas()
        widget.navigator_dialog = _FakeNavigatorDialog(visible=True)
        widget.status = lambda message: status_messages.append(message)
        widget.update_navigator_shapes_calls = 0
        widget.update_navigator_shapes = lambda: setattr(
            widget,
            "update_navigator_shapes_calls",
            widget.update_navigator_shapes_calls + 1,
        )

        LabelingWidget._apply_combined_shape_filters(widget)

        self.assertEqual(widget._filter_engine.apply_calls, 1)
        self.assertEqual(widget.canvas.update_calls, 1)
        self.assertEqual(widget.update_navigator_shapes_calls, 1)
        self.assertEqual(status_messages[-1], "")

    def test_apply_combined_shape_filters_clears_navigation_without_filter(self):
        status_messages = []
        widget = types.SimpleNamespace()
        widget._filter_state = FilterState()
        widget._filter_navigation_active = True
        widget._filter_navigation_files = ["a.jpg"]
        widget._filter_navigation_initial_count = 1
        widget._filter_navigation_state = FilterState(labels={"person"})
        widget.label_list = _FakeLabelList()
        widget._filter_engine = _FakeFilterEngine(changed=False)
        widget.canvas = _FakeCanvas()
        widget.navigator_dialog = _FakeNavigatorDialog(visible=True)
        widget.status = lambda message, *_args: status_messages.append(message)
        widget.update_navigator_shapes_calls = 0
        widget.update_navigator_shapes = lambda: setattr(
            widget,
            "update_navigator_shapes_calls",
            widget.update_navigator_shapes_calls + 1,
        )
        widget._set_filter_navigation_action_checked = lambda _checked: None

        LabelingWidget._apply_combined_shape_filters(widget)

        self.assertFalse(widget._filter_navigation_active)
        self.assertEqual(widget._filter_navigation_files, [])
        self.assertEqual(widget._filter_navigation_initial_count, 0)
        self.assertIsNone(widget._filter_navigation_state)
        self.assertEqual(status_messages[-1], "")

    def test_multi_label_summary_does_not_clear_filter_state(self):
        widget = types.SimpleNamespace()
        widget._filter_state = FilterState(labels={"cat", "dog"})
        widget.apply_calls = 0
        widget._apply_combined_shape_filters = lambda: setattr(
            widget, "apply_calls", widget.apply_calls + 1
        )

        text_box = QtWidgets.QComboBox()
        text_box.addItems(["", "cat", "dog"])
        widget.label_filter_combobox = types.SimpleNamespace(text_box=text_box)

        callback_calls = []

        def _on_change(index):
            callback_calls.append(index)
            LabelingWidget.text_selection_changed(widget, index)

        text_box.currentIndexChanged.connect(_on_change)

        LabelingWidget._update_combo_box_label_summary(widget)

        self.assertEqual(widget._filter_state.labels, {"cat", "dog"})
        self.assertEqual(callback_calls, [])
        self.assertEqual(widget.apply_calls, 0)


if __name__ == "__main__":
    unittest.main()
