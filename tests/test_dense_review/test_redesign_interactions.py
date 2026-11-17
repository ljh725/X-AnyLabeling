"""Real keyboard, screen restoration and retry interactions."""

# flake8: noqa: F811
import pytest
from PyQt6 import QtCore, QtGui, QtTest

from .test_workspace_review_fixes import _open, app, open_window


def test_handoff_keeps_cross_batch_objects_and_associated_point_reachable(app, open_window):
    from dataclasses import replace
    from anylabeling.services.inspection.handoff import HandoffRequest
    from .test_workspace_dock_tasks import _rectangle, _point, _open_review
    window, path = open_window([
        _rectangle("person", "rect1", 40, 40, group_id=0),
        _rectangle("vehicle", "rect2", 300, 40, group_id=1),
        _point("nose", "kp1", 80, 80, group_id=0),
    ], batches=(("person", ("person",)), ("vehicle", ("vehicle",))),
       rules=(("person", "visible", ""), ("vehicle", "visible", "")))
    widget, ws = _open_review(app, window, path)
    request = HandoffRequest("issue", "family", widget.inspection_dataset_root(),
                             widget.inspection_output_dir(), widget.inspection_current_relative_path(),
                             object_ids=("rect1", "rect2"))
    assert widget.inspection_handoff_to_dense_review(request)[0]
    ws.refresh_all()
    ws._navigate_child(ws.child_objects.findData("rect2"))
    assert ws.session.current_object().shape_id == "rect2"
    assert ws.session.state.current_batch == ws.session.state.batches[1].batch_id
    assert widget.canvas.selected_shapes[0].xanylabeling_shape_id == "rect2"
    assert widget.inspection_handoff_to_dense_review(replace(request, object_ids=("kp1",)))[0]
    assert ws.session.current_object().shape_id == "kp1"
    assert ws.session.state.current_batch == ws.session.state.batches[0].batch_id
    assert not widget.inspection_handoff_to_dense_review(replace(request, object_ids=("stale",)))[0]
    assert ws.session.current_object().shape_id == "kp1"
    assert not widget.dirty


@pytest.mark.parametrize("floating", [False, True])
def test_one_shortcut_serves_canvas_and_floating_panel(app, open_window, floating):
    window, widget, ws = _open(app, open_window)
    ws.setFloating(floating)
    owner = ws if floating else window
    owner.activateWindow()
    target = ws.card_list if floating else widget.canvas
    target.setFocus()
    app.processEvents()
    shortcut = next(item for item in ws._shortcuts if item.key().toString() == "Ctrl+Return")
    spy = QtTest.QSignalSpy(shortcut.activated)
    QtTest.QTest.keyClick(target, QtCore.Qt.Key.Key_Return, QtCore.Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    assert len(spy) == 1
    assert ws.session.object("rect1").confirmed_both()
    assert ws.session.object("rect2").confirmed_both()


def test_review_shortcut_does_not_steal_spinbox_input(app, open_window):
    window, _, ws = _open(app, open_window)
    window.activateWindow()
    ws.context_spin.setFocus()
    app.processEvents()
    QtTest.QTest.keyClick(ws.context_spin, QtCore.Qt.Key.Key_Return, QtCore.Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    assert not ws.session.object("rect1").confirmed_both()


def test_conflicting_or_empty_bindings_are_not_installed(app, open_window):
    _, widget, ws = _open(app, open_window)
    widget._config["shortcuts"]["dense_review_skip"] = "Ctrl+Z"
    widget._config["shortcuts"]["dense_review_difficult"] = None
    widget._settings_runtime_applier.apply_change("shortcuts.dense_review_skip", "Ctrl+Z")
    sequences = [shortcut.key().toString() for shortcut in ws._shortcuts]
    assert "Ctrl+Z" not in sequences
    assert "Alt+X" not in sequences
    assert ws._shortcut_warnings


def test_ambiguous_observation_owner_preserves_saved_group(app, open_window):
    _, widget, ws = _open(app, open_window)
    rectangle = widget._dense_review_find_shape("rect2")
    rectangle.group_id = 0
    widget._dense_review_sync_from_canvas()
    before = [(shape.xanylabeling_shape_id, shape.group_id) for shape in widget.canvas.shapes]
    assert not ws._card_points(ws.session.object("rect1"))
    ws._refresh_observation()
    ws._choose_observation_owner(ws.association_owner.findData("rect2"))
    assert [point.shape_id for point in ws._card_points(ws.session.object("rect2"))] == ["kp1"]
    assert [(shape.xanylabeling_shape_id, shape.group_id) for shape in widget.canvas.shapes] == before
    assert not widget.dirty


def test_retry_excludes_known_failure_until_current_success(app, open_window, monkeypatch):
    _, _, ws = _open(app, open_window)
    ws._on_thumbnail_failed("rect1", "source unavailable")
    assert "rect1" not in ws._scope().candidate_ids
    monkeypatch.setattr(ws, "_schedule_visible_thumbnails", lambda: None)
    ws._retry_current_crop()
    assert "rect1" not in ws._scope().candidate_ids
    image = QtGui.QImage(10, 10, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor("blue"))
    ws._on_thumbnail_ready("rect1", image)
    assert "rect1" in ws._scope().candidate_ids


def test_disconnected_screen_geometry_returns_to_accessible_screen(app, open_window):
    _, widget, ws = _open(app, open_window)
    ws.setFloating(True)
    ws.move(50000, 50000)
    assert ws._save_review_preferences()
    ws._restore_review_geometry()
    app.processEvents()
    area = QtGui.QGuiApplication.primaryScreen().availableGeometry()
    assert ws.frameGeometry().intersects(area)
    assert area.contains(ws.frameGeometry().topLeft())
    assert not widget.dirty


def test_close_discards_delayed_workspace_results(app, open_window):
    _, _, ws = _open(app, open_window)
    old_generation = ws.thumbnails.generation
    ws.close()
    app.processEvents()
    assert ws.thumbnails.generation > old_generation
    assert not ws._compare_dialogs
    assert not ws.thumbnails._latest_requests


def test_grid_draft_survives_refresh_until_explicit_rebuild(app, open_window):
    _, _, ws = _open(app, open_window)
    ws.set_task(ws.TASK_COVERAGE)
    old_plan = ws.session.state.coverage
    old_columns = old_plan.columns
    ws.columns_spin.setValue(7)
    ws.refresh_all()
    assert ws.columns_spin.value() == 7
    assert ws.session.state.coverage is old_plan
    assert old_plan.columns == old_columns
