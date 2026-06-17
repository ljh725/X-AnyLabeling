"""Phase B regression tests for feature-interaction conflicts.

Each test maps to a hotspot (Hn) documented in
``docs/feature_interaction_test_matrix.md``.

* Tests whose docstring starts with ``Hn (RED)`` encode the *desired*
  contract that the current code violates; they are expected to FAIL until
  Phase C fixes the underlying defect. A red result here is the objective
  evidence that the bug exists.
* Tests marked ``Hn (characterization)`` capture current behaviour as a
  guard so unintended changes are caught.

Covered: H1, H2, H3, H5, H6.
Manual-only (no automated test yet): H4 (needs product decision + paint),
H7 (key event dispatch), H8 (paint-pipeline consistency).
"""

import os
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.conftest import MockShape


def _make_widget(canvas, **extra):
    """Build a minimal LabelingWidget stand-in for bound-method tests.

    Provides just enough attributes for ``show_all_instances`` /
    ``_auto_focus_on_selection`` / ``_on_inspector_shape_edit`` to run,
    without instantiating the 6.6k-line widget.
    """
    w = types.SimpleNamespace()
    w.canvas = canvas
    w.auto_focus_instance = extra.get("auto_focus_instance", True)
    w.auto_focus_group_id = extra.get("auto_focus_group_id", None)
    w.filename = extra.get("filename", "test.json")
    w.set_dirty = lambda: None
    w._sync_label_list_hidden_by_filter = lambda: None
    w.status = lambda *a, **k: None
    w.tr = lambda x: x
    return w


def test_h1_copy_does_not_propagate_hidden_by_filter():
    """H1 (RED): hidden_by_filter is a runtime-only flag and must NOT
    survive copy()/deepcopy, which ``Canvas.store_shapes`` uses for Undo
    backups. Today deepcopy preserves it, so Undo resurrects hidden state.
    """
    from PyQt6.QtCore import QPointF

    from anylabeling.views.labeling.shape import Shape

    s = Shape(shape_type="rectangle")
    s.add_point(QPointF(0, 0))
    s.add_point(QPointF(10, 10))
    s.hidden_by_filter = True

    cp = s.copy()

    assert cp.hidden_by_filter is False, (
        "H1: deepcopy preserved hidden_by_filter; Undo would resurrect "
        "the hidden state from the backup snapshot"
    )


def test_h2_show_all_instances_restores_native_hidden_shape(canvas):
    """H2 (RED): F3 ``show_all_instances`` only clears ``hidden_by_filter``
    but not the native ``shape.visible`` flag, so a shape hidden by both
    systems stays hidden after "show all". A unified restore should make
    the shape interactive again regardless of which system hid it.
    """
    from anylabeling.views.labeling.label_widget import LabelingWidget

    shape = MockShape(visible=False, hidden_by_filter=True)
    canvas.visible[shape] = True
    canvas.shapes = [shape]
    assert not canvas.is_shape_interactive(shape)

    w = _make_widget(canvas)
    LabelingWidget.show_all_instances(w)

    assert canvas.is_shape_interactive(shape), (
        "H2: show_all_instances cleared hidden_by_filter but native "
        "shape.visible=False still hides the shape — no unified restore"
    )


def test_h3_autofocus_broadcasts_selection_via_signal(canvas):
    """H3 (RED): auto-focus must communicate the new selection through the
    ``selection_changed`` signal so the label list / attributes panel stay
    in sync. Today it directly mutates ``canvas.selected_shapes`` instead.
    """
    from anylabeling.views.labeling.label_widget import LabelingWidget

    a1 = MockShape(group_id=1)
    a2 = MockShape(group_id=1)
    b1 = MockShape(group_id=2)
    for s in (a1, a2, b1):
        canvas.visible[s] = True
    canvas.shapes = [a1, a2, b1]
    canvas.selected_shapes = [a1]

    emitted = []
    canvas.selection_changed.connect(
        lambda shapes: emitted.append(list(shapes))
    )

    w = _make_widget(canvas, auto_focus_instance=True)
    LabelingWidget._auto_focus_on_selection(w, [a1])

    assert len(emitted) > 0, (
        "H3: auto-focus changed the selection without emitting "
        "selection_changed; dependent panels are out of sync"
    )


def test_h5_select_shapes_filters_out_hidden_by_filter(canvas):
    """H5 (characterization): ``select_shapes`` filters out shapes hidden
    by auto-focus (``hidden_by_filter``). This is why inspector navigation
    silently no-ops on aggregated-hidden targets. Captured as a guard; the
    Phase C fix will add an explicit "force" path and update this test.
    """
    shape = MockShape(hidden_by_filter=True)
    canvas.visible[shape] = True
    canvas.shapes = [shape]

    emitted = []
    canvas.selection_changed.connect(lambda sh: emitted.append(list(sh)))

    canvas.select_shapes([shape])

    assert emitted, "select_shapes must emit selection_changed"
    assert (
        shape not in emitted[0]
    ), "hidden-by-filter shape must not enter programmatic selection"


def test_h6_inspector_edit_records_undo_backup(canvas):
    """H6 (RED): inspector table edits must call ``store_shapes()`` so they
    are individually undoable. Today they only set_dirty + redraw, so
    Ctrl+Z cannot revert an inspector edit.
    """
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
    assert (
        len(store_calls) > 0
    ), "H6: inspector edit did not record an Undo backup (store_shapes)"


# -- Pose View selection-driven focus (req3/req5/req1) ---------------------


def _pose_widget(canvas, **extra):
    """A widget stub with Pose View enabled for focus tests."""
    from anylabeling.views.labeling.label_widget import LabelingWidget

    w = _make_widget(canvas, **extra)
    canvas.pose_config.enabled = True
    # The bound-method pattern requires self.* callees to exist on the
    # stub; delegate the ones used by _pose_focus_on_selection.
    w._apply_group_focus = lambda gid: LabelingWidget._apply_group_focus(
        w, gid
    )
    w.show_all_instances = lambda: LabelingWidget.show_all_instances(w)
    return w


def test_pose_focus_hides_other_groups(canvas):
    """req5: selecting a shape in Pose View hides other groups via
    hidden_by_filter and keeps the selected group visible."""
    from anylabeling.views.labeling.label_widget import LabelingWidget

    a1 = MockShape(group_id=1)
    a2 = MockShape(group_id=1)
    b1 = MockShape(group_id=2)
    for s in (a1, a2, b1):
        canvas.visible[s] = True
    canvas.shapes = [a1, a2, b1]

    w = _pose_widget(canvas)
    LabelingWidget._pose_focus_on_selection(w, [a1])

    assert a1.hidden_by_filter is False
    assert a2.hidden_by_filter is False
    assert b1.hidden_by_filter is True


def test_pose_focus_blank_exits(canvas):
    """req5: an empty selection (clicked blank) exits focus and restores
    every shape's visibility."""
    from anylabeling.views.labeling.label_widget import LabelingWidget

    a1 = MockShape(group_id=1)
    b1 = MockShape(group_id=2)
    canvas.visible[a1] = True
    canvas.visible[b1] = True
    canvas.shapes = [a1, b1]

    w = _pose_widget(canvas)
    LabelingWidget._pose_focus_on_selection(w, [a1])
    assert b1.hidden_by_filter is True

    LabelingWidget._pose_focus_on_selection(w, [])
    assert a1.hidden_by_filter is False
    assert b1.hidden_by_filter is False


def test_pose_focus_no_group_id_hinted_not_hidden(canvas):
    """req5: selecting a shape without group_id must NOT hide anything
    (a status hint is shown instead)."""
    from anylabeling.views.labeling.label_widget import LabelingWidget

    no_gid = MockShape(group_id=None)
    a1 = MockShape(group_id=1)
    canvas.visible[no_gid] = True
    canvas.visible[a1] = True
    canvas.shapes = [no_gid, a1]

    w = _pose_widget(canvas)
    LabelingWidget._pose_focus_on_selection(w, [no_gid])

    assert no_gid.hidden_by_filter is False
    assert a1.hidden_by_filter is False


def test_alt_h_noop_in_pose_view(canvas):
    """req1: Alt+H (toggle_auto_focus_instance) must not engage while
    Pose View is active."""
    from anylabeling.views.labeling.label_widget import LabelingWidget

    w = _pose_widget(canvas, auto_focus_instance=False)
    LabelingWidget.toggle_auto_focus_instance(w)
    assert w.auto_focus_instance is False


def test_gid_dropdown_natural_sort(qapp):
    """req2: gid filter dropdown must sort numerically with the '-1'
    sentinel first (was a string sort: '1','10','2')."""
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


# -- List / focus decoupling (adjustments) ---------------------------------


def test_pose_focus_keeps_label_list_rows_visible(canvas):
    """Adjustment: Pose View focus hides other groups on the canvas but
    must NOT hide label-list rows (the list always shows all names)."""
    from anylabeling.views.labeling.label_widget import LabelingWidget

    a1 = MockShape(group_id=1)
    b1 = MockShape(group_id=2)
    canvas.visible[a1] = True
    canvas.visible[b1] = True
    canvas.shapes = [a1, b1]

    w = _pose_widget(canvas)
    sync_calls = []
    w._sync_label_list_hidden_by_filter = lambda: sync_calls.append(1)

    LabelingWidget._apply_group_focus(w, 1)

    assert b1.hidden_by_filter is True  # canvas still hides other group
    assert sync_calls == [], (
        "focus must not call _sync_label_list_hidden_by_filter (rows stay"
        " visible)"
    )


def test_list_selection_does_not_trigger_pose_focus(canvas):
    """Adjustment: selecting from the label list acts on the object
    itself and must not trigger Pose View focus-hide (guarded by
    ``_list_selecting``)."""
    from anylabeling.views.labeling.label_widget import LabelingWidget

    a1 = MockShape(group_id=1)
    b1 = MockShape(group_id=2)
    canvas.visible[a1] = True
    canvas.visible[b1] = True
    canvas.shapes = [a1, b1]

    w = _pose_widget(canvas)
    w._list_selecting = True  # set by label_selection_changed

    LabelingWidget._pose_focus_on_selection(w, [b1])

    assert a1.hidden_by_filter is False
    assert b1.hidden_by_filter is False
