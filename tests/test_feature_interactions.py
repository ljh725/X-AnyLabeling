"""Regression tests for feature interactions after the Pose View
filter-driven refactor.

Removed (obsolete): H1/H2/H3/H5 (hidden_by_filter system deleted),
all pose-focus tests (_apply_group_focus / _pose_focus_on_selection
deleted), Alt+H tests (auto-aggregation deleted).
"""

import os
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.conftest import MockShape


def _make_widget(canvas, **extra):
    """Build a minimal LabelingWidget stand-in for bound-method tests."""
    w = types.SimpleNamespace()
    w.canvas = canvas
    w.filename = extra.get("filename", "test.json")
    w.set_dirty = lambda: None
    w.status = lambda *a, **k: None
    w.tr = lambda x: x
    return w


def test_h6_inspector_edit_records_undo_backup(canvas):
    """H6: inspector table edits must call ``store_shapes()``."""
    from anylabeling.views.labeling.label_widget import LabelingWidget

    shape = MockShape()
    shape.label = "old"
    canvas.shapes = [shape]

    store_calls = []
    canvas.store_shapes = lambda: store_calls.append(1)
    canvas.update = lambda: None

    w = _make_widget(canvas, filename="test.json")
    LabelingWidget._on_inspector_shape_edit(w, "test.json", 0, "label", "new")

    assert shape.label == "new"
    assert len(store_calls) > 0, "inspector edit must record undo backup"


def test_pose_click_sets_gid_filter(canvas):
    """Pose View click-to-focus: clicking a shape sets the gid filter
    (native filter engine drives visibility), NOT mass-selection."""
    from anylabeling.views.labeling.label_widget import LabelingWidget

    shape = MockShape(group_id=3)
    canvas.visible[shape] = True
    canvas.shapes = [shape]

    calls = []
    w = _make_widget(canvas)
    w.set_gid_filter_value = lambda gid: calls.append(gid)

    LabelingWidget._pose_focus_by_filter(w, [shape])

    assert calls == ["3"], "click should set gid filter to the group"


def test_pose_click_no_group_id_does_not_filter(canvas):
    """Clicking a shape without group_id does not set a filter."""
    from anylabeling.views.labeling.label_widget import LabelingWidget

    shape = MockShape(group_id=None)
    canvas.visible[shape] = True
    canvas.shapes = [shape]

    calls = []
    w = _make_widget(canvas)
    w.set_gid_filter_value = lambda gid: calls.append(gid)

    LabelingWidget._pose_focus_by_filter(w, [shape])

    assert calls == [], "no group_id should not trigger filter"


def test_gid_dropdown_natural_sort(qapp):
    """gid filter dropdown must sort numerically with '-1' first."""
    from anylabeling.views.labeling.label_widget import LabelingWidget

    captured = []
    widget = types.SimpleNamespace()
    widget._filter_state = types.SimpleNamespace(gid="-1")
    widget.gid_filter_combobox = types.SimpleNamespace(
        gid_box=types.SimpleNamespace(currentText=lambda: ""),
        update_items=lambda items: captured.append(list(items)),
    )
    widget.set_gid_filter_value = lambda *a, **k: None

    LabelingWidget.update_gid_box(widget, precomputed=["2", "10", "1"])

    assert captured and captured[0] == ["-1", "1", "2", "10"]
