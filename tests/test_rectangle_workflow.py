"""Real-widget regression tests for rectangle creation and refinement."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import anylabeling.config as config_module  # noqa: E402

config_module.current_config_file = str(
    Path(__file__).parents[1] / "anylabeling/configs/xanylabeling_config.yaml"
)

from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402
from anylabeling.views.labeling.label_wrapper import (
    LabelingWrapper,
)  # noqa: E402
from anylabeling.views.labeling.shape import Shape  # noqa: E402
from anylabeling.views.labeling import rect_edge_alignment as rea  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> Iterator[QtWidgets.QApplication]:
    """Provide the offscreen application."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def widget(qapp: Any, tmp_path: Path) -> Iterator[Any]:
    """Load a real image and enable the opt-in workbench."""
    image = QtGui.QImage(300, 300, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor("white"))
    path = tmp_path / "image.png"
    assert image.save(str(path))
    main = QtWidgets.QMainWindow()
    wrapper = LabelingWrapper(main)
    main.setCentralWidget(wrapper)
    w = wrapper.view
    assert w.load_file(str(path))
    w.rectangle_workflow.enabled_box.setChecked(True)
    w._config["display_label_popup"] = True
    w._config["auto_use_last_label"] = False
    w._config["auto_use_last_gid"] = False
    w._config["auto_save"] = False
    main.resize(1400, 900)
    main.show()
    qapp.processEvents()
    yield w
    # Dispose each complete Qt tree before the next fixture creates a window.
    # Relying on cyclic Python GC can destroy live Qt timers out of order.
    for timer in w.findChildren(QtCore.QTimer):
        timer.stop()
    main.hide()
    main.deleteLater()
    QtWidgets.QApplication.sendPostedEvents(
        None, QtCore.QEvent.Type.DeferredDelete
    )
    qapp.processEvents()


def _rect(widget: Any) -> Shape:
    """Load and select a rectangle with a known undo baseline."""
    shape = Shape(label="person", shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(20, 30),
        QtCore.QPointF(100, 30),
        QtCore.QPointF(100, 120),
        QtCore.QPointF(20, 120),
    ]
    shape.close()
    widget.load_shapes([shape], replace=True)
    widget.canvas.select_shapes([shape])
    return shape


def _key(canvas: Any, key: Any, modifiers: Any = None) -> None:
    """Deliver a real Qt key event through the installed event filter."""
    if modifiers is None:
        modifiers = QtCore.Qt.KeyboardModifier.NoModifier
    event = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, key, modifiers)
    QtWidgets.QApplication.sendEvent(canvas, event)


def _click(widget: Any, x: float, y: float) -> None:
    """Send one press/release pair at an original-image coordinate."""
    canvas = widget.canvas
    point = (QtCore.QPointF(x, y) + canvas.offset_to_center()) * canvas.scale
    move = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseMove,
        point,
        point,
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    QtWidgets.QApplication.sendEvent(canvas, move)
    for event_type, buttons in (
        (
            QtCore.QEvent.Type.MouseButtonPress,
            QtCore.Qt.MouseButton.LeftButton,
        ),
        (
            QtCore.QEvent.Type.MouseButtonRelease,
            QtCore.Qt.MouseButton.NoButton,
        ),
    ):
        event = QtGui.QMouseEvent(
            event_type,
            point,
            point,
            QtCore.Qt.MouseButton.LeftButton,
            buttons,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        QtWidgets.QApplication.sendEvent(canvas, event)


def _draw(widget: Any) -> Shape:
    """Create a rectangle using four input events and digit prefill."""
    widget.digit_to_label = "person"
    widget.rectangle_workflow.start_extreme()
    for x, y in [(50, 10), (80, 40), (60, 90), (20, 45)]:
        _click(widget, x, y)
    assert len(widget.canvas.shapes) == 1
    return widget.canvas.shapes[0]


def test_region_click_dirty_feedback_and_undo(widget: Any) -> None:
    """A region click updates real workbench state and undoes as one unit."""
    shape = _rect(widget)
    workflow = widget.rectangle_workflow
    workflow.start_refinement()
    widget.set_clean()
    identity = shape.xanylabeling_shape_id
    baseline = len(widget.canvas.shapes_backups)
    _click(widget, 96, 70)
    assert rea.geometry_from_shape(shape).x_max == pytest.approx(96)
    assert widget.dirty
    assert len(widget.canvas.shapes_backups) == baseline + 1
    assert shape.xanylabeling_shape_id == identity
    assert not any(
        button.isChecked() for button in workflow.edge_buttons.values()
    )
    assert widget.canvas.rect_edge_active_edge is None
    widget.undo_shape_edit()
    restored = widget.canvas.selected_shapes[0]
    assert restored.xanylabeling_shape_id == identity
    assert rea.geometry_from_shape(restored).x_max == 100


def test_region_click_resets_nudge_burst(widget: Any) -> None:
    """Nudges before and after a click cannot merge across that click."""
    _rect(widget)
    workflow = widget.rectangle_workflow
    workflow.start_refinement()
    workflow.select_edge("right")
    _key(widget.canvas, QtCore.Qt.Key.Key_Left)
    _click(widget, 96, 70)
    workflow.select_edge("right")
    _key(widget.canvas, QtCore.Qt.Key.Key_Left)
    for expected in (96, 99, 100):
        widget.undo_shape_edit()
        assert rea.geometry_from_shape(
            widget.canvas.selected_shapes[0]
        ).x_max == pytest.approx(expected)


def test_region_click_scaled_noop(widget: Any) -> None:
    """Coordinate conversion noise cannot create a phantom undo entry."""
    _rect(widget)
    widget.rectangle_workflow.start_refinement()
    widget.canvas.scale = 1.7
    baseline = len(widget.canvas.shapes_backups)
    _click(widget, 100, 70)
    assert len(widget.canvas.shapes_backups) == baseline


def test_region_click_save_reload(widget: Any, tmp_path: Path) -> None:
    """Persist only the edited rectangle and preserve its business identity."""
    shape = _rect(widget)
    shape.group_id = 8
    identity = shape.xanylabeling_shape_id
    widget.rectangle_workflow.start_refinement()
    _click(widget, 96, 70)
    path = tmp_path / "image.json"
    assert widget.save_labels(str(path))
    saved = json.loads(path.read_text(encoding="utf-8"))["shapes"]
    assert len(saved) == 1 and saved[0]["shape_type"] == "rectangle"
    assert saved[0]["group_id"] == 8
    assert saved[0]["xanylabeling_shape_id"] == identity
    assert max(point[0] for point in saved[0]["points"]) == pytest.approx(96)
    widget.set_clean()
    assert widget.load_file(str(tmp_path / "image.png"))
    assert rea.geometry_from_shape(
        widget.canvas.shapes[0]
    ).x_max == pytest.approx(96)
    assert widget.canvas.shapes[0].xanylabeling_shape_id == identity


def test_four_clicks_commit_one_rectangle(widget: Any) -> None:
    """Each click advances once and commits one compatible selected shape."""
    shape = _draw(widget)
    assert shape.label == "person"
    assert shape.shape_type == "rectangle"
    assert [v for p in shape.points for v in (p.x(), p.y())] == pytest.approx(
        [20, 10, 80, 10, 80, 90, 20, 90]
    )
    assert widget.canvas.selected_shapes == [shape]
    assert widget.rectangle_workflow.draft is None
    assert widget.canvas.rect_edge_active_edge is None
    widget.undo_shape_edit()
    assert widget.canvas.shapes == []


def test_draft_back_and_cancel_do_not_touch_history(widget: Any) -> None:
    """Draft shortcuts cannot undo previously committed annotations."""
    original = _rect(widget)
    wf = widget.rectangle_workflow
    before = len(widget.canvas.shapes_backups)
    wf.start_extreme()
    _click(widget, 50, 10)
    _click(widget, 80, 40)
    widget.undo_shape_edit()
    assert len(wf.draft.points) == 1
    _key(widget.canvas, QtCore.Qt.Key.Key_Escape)
    assert wf.draft is None
    assert widget.canvas.shapes == [original]
    assert len(widget.canvas.shapes_backups) == before


def test_label_cancel_retains_draft(
    widget: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancelled label dialog leaves no unlabeled shape or undo record."""
    wf = widget.rectangle_workflow
    widget.digit_to_label = None
    widget.unique_label_list.clearSelection()
    monkeypatch.setattr(
        widget.label_dialog,
        "pop_up",
        lambda *_a, **_k: (None, {}, None, "", False, []),
    )
    wf.start_extreme()
    before = len(widget.canvas.shapes_backups)
    for x, y in [(50, 10), (80, 40), (60, 90), (20, 45)]:
        _click(widget, x, y)
    assert wf.draft.complete
    assert widget.canvas.shapes == []
    assert len(widget.canvas.shapes_backups) == before
    assert not widget.dirty
    widget.digit_to_label = "person"
    wf.submit_draft()
    assert len(widget.canvas.shapes) == 1


@pytest.mark.parametrize("scale", [0.5, 1.0, 4.0])
def test_nudge_axis_scale_and_escape(widget: Any, scale: float) -> None:
    """Input uses original pixels and Escape does not revert committed nudges."""
    shape = _rect(widget)
    canvas = widget.canvas
    wf = widget.rectangle_workflow
    wf.start_refinement()
    canvas.scale = scale
    wf.select_edge("right")
    assert not canvas.rect_edge_dragging
    _key(canvas, QtCore.Qt.Key.Key_Up)
    assert rea.geometry_from_shape(shape).x_max == 100
    _key(canvas, QtCore.Qt.Key.Key_Left)
    _key(
        canvas,
        QtCore.Qt.Key.Key_Left,
        QtCore.Qt.KeyboardModifier.ShiftModifier,
    )
    assert rea.geometry_from_shape(shape).x_max == 94
    assert rea.geometry_from_shape(shape).x_min == 20
    _key(canvas, QtCore.Qt.Key.Key_Escape)
    assert rea.geometry_from_shape(shape).x_max == 94
    assert canvas.rect_edge_active_edge is None


def test_hover_and_no_edge_do_not_move_box(widget: Any) -> None:
    """Hover is not keyboard authorization and empty selection is harmless."""
    shape = _rect(widget)
    wf = widget.rectangle_workflow
    wf.start_refinement()
    widget.canvas.rect_edge_hover_edge = rea.iter_edges(shape)[0]
    points = [(p.x(), p.y()) for p in shape.points]
    _key(widget.canvas, QtCore.Qt.Key.Key_Right)
    assert [(p.x(), p.y()) for p in shape.points] == points
    assert widget.canvas.rect_edge_active_edge is None


def test_nudge_burst_and_direction_change_undo(widget: Any) -> None:
    """The undo baseline includes all steps of the preceding burst."""
    _rect(widget)
    wf = widget.rectangle_workflow
    wf.start_refinement()
    wf.select_edge("right")
    for _ in range(3):
        _key(widget.canvas, QtCore.Qt.Key.Key_Left)
    _key(widget.canvas, QtCore.Qt.Key.Key_Right)
    widget.undo_shape_edit()
    shape = widget.canvas.selected_shapes[0]
    assert rea.geometry_from_shape(shape).x_max == 97
    widget.undo_shape_edit()
    shape = widget.canvas.selected_shapes[0]
    assert rea.geometry_from_shape(shape).x_max == 100


def test_focus_loss_keeps_committed_geometry(widget: Any) -> None:
    """Leaving canvas focus never rolls back a completed keyboard edit."""
    shape = _rect(widget)
    wf = widget.rectangle_workflow
    wf.start_refinement()
    wf.select_edge("right")
    _key(widget.canvas, QtCore.Qt.Key.Key_Left)
    widget.canvas.focusOutEvent(QtGui.QFocusEvent(QtCore.QEvent.Type.FocusOut))
    assert rea.geometry_from_shape(shape).x_max == 99


def test_tab_order_and_finish(widget: Any) -> None:
    """Reverse Tab starts at left and Enter ends the explicit mode."""
    _rect(widget)
    wf = widget.rectangle_workflow
    wf.start_refinement()
    _key(widget.canvas, QtCore.Qt.Key.Key_Backtab)
    assert widget.canvas.rect_edge_active_edge.edge_name == "left"
    _key(widget.canvas, QtCore.Qt.Key.Key_Tab)
    assert widget.canvas.rect_edge_active_edge.edge_name == "top"
    _key(widget.canvas, QtCore.Qt.Key.Key_Return)
    assert not wf.refining
    assert widget.canvas.rect_edge_active_edge is None


def test_observation_preserves_geometry_and_dirty(widget: Any) -> None:
    """Viewport adjustment and restore are observational operations."""
    shape = _rect(widget)
    wf = widget.rectangle_workflow
    widget.set_clean()
    before = [(p.x(), p.y()) for p in shape.points]
    old_scale = widget.canvas.scale
    wf.auto_zoom.setChecked(True)
    wf.start_refinement()
    assert wf._view_snapshot is not None
    scale = widget.canvas.scale
    wf.select_edge("top")
    _key(widget.canvas, QtCore.Qt.Key.Key_Tab)
    assert widget.canvas.scale == scale
    assert [(p.x(), p.y()) for p in shape.points] == before
    assert not widget.dirty
    wf.restore_view()
    assert widget.canvas.scale == pytest.approx(old_scale, abs=0.01)


def test_draft_zoom_preserves_original_coordinates(widget: Any) -> None:
    """Pointer-local zoom preserves accepted boundary coordinates."""
    wf = widget.rectangle_workflow
    wf.start_extreme()
    _click(widget, 50, 10)
    _click(widget, 80, 40)
    points = list(wf.draft.points)
    wf.local_focus()
    assert wf.draft.points == points
    assert not widget.dirty


def test_continue_draw_uses_same_label(widget: Any) -> None:
    """A new draft is explicit and reuses the last successful label."""
    _draw(widget)
    wf = widget.rectangle_workflow
    wf.continue_drawing()
    assert wf.draft is not None and not wf.draft.points
    assert widget.digit_to_label == "person"
    assert len(widget.canvas.shapes) == 1


def test_next_object_preserves_identity_and_clears_edge(widget: Any) -> None:
    """Switching targets cannot carry an active edge to another shape."""
    first = _rect(widget)
    second = first.copy()
    second.xanylabeling_shape_id = Shape.new_shape_id()
    widget.load_shapes([first, second], replace=True)
    widget.canvas.select_shapes([first])
    wf = widget.rectangle_workflow
    wf.start_refinement()
    wf.select_edge("right")
    wf.next_object()
    assert widget.canvas.selected_shapes == [second]
    assert widget.canvas.rect_edge_active_edge is None


def test_save_reload_ordinary_rectangle(widget: Any, tmp_path: Path) -> None:
    """Saved output contains the final rectangle and no temporary points."""
    shape = _draw(widget)
    shape_id = shape.xanylabeling_shape_id
    wf = widget.rectangle_workflow
    wf.select_edge("right")
    _key(widget.canvas, QtCore.Qt.Key.Key_Left)
    path = tmp_path / "image.json"
    assert widget.save_labels(str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["shapes"]) == 1
    saved = data["shapes"][0]
    assert saved["shape_type"] == "rectangle"
    assert saved["xanylabeling_shape_id"] == shape_id
    assert max(p[0] for p in saved["points"]) == 79
    assert widget.load_file(str(tmp_path / "image.png"))
    assert len(widget.canvas.shapes) == 1
    assert widget.canvas.shapes[0].xanylabeling_shape_id == shape_id


def test_disabling_workbench_preserves_normal_creation(widget: Any) -> None:
    """Turning the feature off leaves ordinary two-point drawing available."""
    wf = widget.rectangle_workflow
    wf.enabled_box.setChecked(False)
    widget.digit_to_label = "person"
    widget.toggle_draw_mode(edit=False, create_mode="rectangle")
    _click(widget, 20, 10)
    _click(widget, 80, 90)
    assert len(widget.canvas.shapes) == 1
    assert widget.canvas.shapes[0].label == "person"


def test_failed_navigation_restores_unsaved_geometry(
    widget: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed loader cannot destroy the current unsaved rectangle."""
    shape = _rect(widget)
    wf = widget.rectangle_workflow
    wf.start_refinement()
    wf.select_edge("right")
    _key(widget.canvas, QtCore.Qt.Key.Key_Left)
    filename = widget.filename

    def fail() -> None:
        """Simulate the existing loader clearing state before failing."""
        widget.reset_state()

    monkeypatch.setattr(widget, "open_next_image", fail)
    wf.next_object()
    assert widget.filename == filename
    assert widget.canvas.selected_shapes == [shape]
    assert rea.geometry_from_shape(shape).x_max == 99
    assert widget.dirty


def test_cancelled_navigation_keeps_draft(
    widget: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The normal save cancellation happens before any draft reset."""
    _rect(widget)
    widget.rectangle_workflow.start_extreme()
    _click(widget, 50, 10)
    monkeypatch.setattr(widget, "may_continue", lambda: False)
    widget.open_next_image()
    assert len(widget.rectangle_workflow.draft.points) == 1


def test_wheel_accumulates_and_zoom_modifier_does_not_nudge(
    widget: Any,
) -> None:
    """Small wheel deltas accumulate once, while Ctrl stays a view operation."""
    shape = _rect(widget)
    wf = widget.rectangle_workflow
    wf.start_refinement()
    wf.select_edge("right")

    def wheel(delta: int, modifiers: Any) -> None:
        """Deliver a wheel event on the canvas."""
        event = QtGui.QWheelEvent(
            QtCore.QPointF(50, 50),
            QtCore.QPointF(50, 50),
            QtCore.QPoint(),
            QtCore.QPoint(0, delta),
            QtCore.Qt.MouseButton.NoButton,
            modifiers,
            QtCore.Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QtWidgets.QApplication.sendEvent(widget.canvas, event)

    none = QtCore.Qt.KeyboardModifier.NoModifier
    wheel(60, none)
    assert rea.geometry_from_shape(shape).x_max == 100
    wheel(60, none)
    assert rea.geometry_from_shape(shape).x_max == 101
    wheel(120, QtCore.Qt.KeyboardModifier.ControlModifier)
    assert rea.geometry_from_shape(shape).x_max == 101


def test_settings_live_apply(widget: Any) -> None:
    """Settings and canvas-scoped shortcuts can be changed without restarting."""
    wf = widget.rectangle_workflow
    widget._config["rectangle_workflow"]["auto_zoom"] = True
    wf.apply_preferences()
    assert wf.auto_zoom.isChecked()
    applier = widget._settings_runtime_applier
    applier.apply_shortcuts("shortcuts.rectangle_extreme", "Ctrl+Alt+9")
    assert (
        wf.commands["rectangle_extreme"].shortcut().toString() == "Ctrl+Alt+9"
    )
    wf.commands["rectangle_extreme"].setShortcut(QtGui.QKeySequence())
    widget._config["rectangle_workflow"]["enabled"] = False
    wf.apply_preferences()
    assert not wf.enabled_box.isChecked()


def test_other_control_keys_never_edit_canvas(widget: Any) -> None:
    """Arrow and Tab events directed to a text control cannot move shapes."""
    shape = _rect(widget)
    wf = widget.rectangle_workflow
    wf.start_refinement()
    wf.select_edge("right")
    edit = widget.label_dialog.edit
    edit.setText("reading")
    _key(edit, QtCore.Qt.Key.Key_Left)
    _key(edit, QtCore.Qt.Key.Key_Tab)
    assert rea.geometry_from_shape(shape).x_max == 100


def test_invalid_draft_and_shift_nudge_are_rejected(widget: Any) -> None:
    """Rejected geometric candidates leave the original transaction intact."""
    wf = widget.rectangle_workflow
    wf.start_extreme()
    _click(widget, 50, 30)
    _click(widget, 80, 40)
    _click(widget, 50, 20)
    assert len(wf.draft.points) == 2
    wf.reset()
    shape = _rect(widget)
    wf.start_refinement()
    wf.select_edge("left")
    for _ in range(4):
        _key(
            widget.canvas,
            QtCore.Qt.Key.Key_Left,
            QtCore.Qt.KeyboardModifier.ShiftModifier,
        )
    assert rea.geometry_from_shape(shape).x_min == 0
    _key(
        widget.canvas,
        QtCore.Qt.Key.Key_Left,
        QtCore.Qt.KeyboardModifier.ShiftModifier,
    )
    assert rea.geometry_from_shape(shape).x_min == 0


def test_drag_cancel_and_release_to_nudge(widget: Any) -> None:
    """Dragging can be cancelled, or committed and followed by keyboard input."""
    shape = _rect(widget)
    wf = widget.rectangle_workflow
    wf.start_refinement()
    wf.select_edge("right")
    edge = widget.canvas.rect_edge_active_edge
    widget.canvas._start_rect_edge_drag(edge, QtCore.QPointF(100, 60))
    widget.canvas._rect_edge_drag_update(QtCore.QPointF(103, 60))
    _key(widget.canvas, QtCore.Qt.Key.Key_Escape)
    assert rea.geometry_from_shape(shape).x_max == 100
    wf.select_edge("right")
    edge = widget.canvas.rect_edge_active_edge
    widget.canvas._start_rect_edge_drag(edge, QtCore.QPointF(100, 60))
    widget.canvas._rect_edge_drag_update(QtCore.QPointF(103, 60))
    point = (
        QtCore.QPointF(103, 60) + widget.canvas.offset_to_center()
    ) * widget.canvas.scale
    event = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonRelease,
        point,
        point,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    QtWidgets.QApplication.sendEvent(widget.canvas, event)
    assert not widget.canvas.rect_edge_dragging
    assert widget.canvas.rect_edge_active_edge.edge_name == "right"
    _key(widget.canvas, QtCore.Qt.Key.Key_Left)
    assert rea.geometry_from_shape(shape).x_max == 102


def test_next_object_skips_out_of_image_rectangles(widget: Any) -> None:
    """Invalid source rectangles do not strand a running refinement queue."""
    first = _rect(widget)
    invalid = first.copy()
    invalid.xanylabeling_shape_id = Shape.new_shape_id()
    invalid.points[0].setX(-5)
    invalid.points[3].setX(-5)
    last = first.copy()
    last.xanylabeling_shape_id = Shape.new_shape_id()
    widget.load_shapes([first, invalid, last], replace=True)
    widget.canvas.select_shapes([first])
    wf = widget.rectangle_workflow
    wf.start_refinement()
    wf.next_object()
    assert widget.canvas.selected_shapes == [last]
    assert invalid.points[0].x() == -5
