"""Canvas controls through real windows, editing events and saved files."""

import hashlib
import os
import subprocess
import sys

import numpy as np
import pytest
import yaml
from PIL import Image
from PyQt6 import QtCore, QtGui, QtTest, QtWidgets

from anylabeling import user_config
from anylabeling.views.labeling.shape import Shape
from tests.test_labeling.test_canvas_display_retention import (
    image_path,
    window,
)

Qt = QtCore.Qt


def rectangle(left=100, top=100, right=200, bottom=200):
    shape = Shape(label="object", shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(x, y)
        for x, y in (
            (left, top),
            (right, top),
            (right, bottom),
            (left, bottom),
        )
    ]
    shape.close()
    return shape


def open_rectangles(window, tmp_path, count=1):
    w = window.labeling_widget.view
    w._config["auto_save"] = False
    assert w.load_file(image_path(tmp_path, "edit.png", size=(800, 600)))
    w.set_zoom(100)
    w.load_shapes(
        [
            rectangle(100 + i * 150, 100, 200 + i * 150, 200)
            for i in range(count)
        ],
        update_last_label=False,
    )
    w.canvas.select_shapes(w.canvas.shapes)
    return w


def mouse(canvas, kind, xy, modifiers=Qt.KeyboardModifier.NoModifier):
    pos = (QtCore.QPointF(*xy) + canvas.offset_to_center()) * canvas.scale
    held = kind != QtCore.QEvent.Type.MouseButtonRelease
    button = (
        Qt.MouseButton.NoButton
        if kind == QtCore.QEvent.Type.MouseMove
        else Qt.MouseButton.LeftButton
    )
    event = QtGui.QMouseEvent(
        kind,
        pos,
        pos,
        button,
        Qt.MouseButton.LeftButton if held else Qt.MouseButton.NoButton,
        modifiers,
    )
    QtWidgets.QApplication.sendEvent(canvas, event)


@pytest.mark.parametrize("gesture", ["edge", "fit"])
@pytest.mark.parametrize("cancel", [False, True], ids=["commit", "cancel"])
def test_pending_mode_finishes_real_edit(window, tmp_path, gesture, cancel):
    w = open_rectangles(window, tmp_path)
    canvas = w.canvas
    before = canvas.shapes[0].to_dict()
    if gesture == "edge":
        canvas.set_rectangle_edge_enabled(True)
        modifiers = Qt.KeyboardModifier.NoModifier
        start, end = (100, 150), (90, 150)
        mouse(canvas, QtCore.QEvent.Type.MouseMove, start)
    else:
        modifiers = Qt.KeyboardModifier.ShiftModifier
        start, end = (210, 90), (220, 80)
    mouse(canvas, QtCore.QEvent.Type.MouseButtonPress, start, modifiers)
    assert canvas.interaction_in_progress()
    w.apply_wheel_navigation_mode("traditional")
    w.apply_wheel_navigation_mode("direct")
    w.apply_wheel_navigation_mode("traditional")
    assert canvas.wheel_navigation_mode == "direct"
    if cancel:
        QtTest.QTest.keyClick(canvas, Qt.Key.Key_Escape)
    else:
        mouse(canvas, QtCore.QEvent.Type.MouseMove, end, modifiers)
    mouse(canvas, QtCore.QEvent.Type.MouseButtonRelease, end, modifiers)
    QtWidgets.QApplication.processEvents()
    assert not canvas.interaction_in_progress()
    assert canvas.wheel_navigation_mode == "traditional"
    assert w._pending_wheel_navigation_mode is None
    assert (
        canvas.shapes[0].xanylabeling_shape_id
        == before["xanylabeling_shape_id"]
    )
    if cancel:
        assert canvas.shapes[0].to_dict() == before
    else:
        assert canvas.shapes[0].to_dict()["points"] != before["points"]
        w.undo_shape_edit()
        assert canvas.shapes[0].to_dict() == before


@pytest.mark.parametrize("navigation", ["switch", "close"])
def test_pending_mode_resolves_when_navigation_ends_edit(
    window, tmp_path, navigation
):
    w = open_rectangles(window, tmp_path)
    canvas = w.canvas
    canvas.set_rectangle_edge_enabled(True)
    mouse(canvas, QtCore.QEvent.Type.MouseMove, (100, 150))
    mouse(canvas, QtCore.QEvent.Type.MouseButtonPress, (100, 150))
    w.apply_wheel_navigation_mode("traditional")
    if navigation == "switch":
        assert w.load_file(image_path(tmp_path, "next.png", size=(800, 600)))
    else:
        w.close_file()
    QtWidgets.QApplication.processEvents()
    assert not canvas.interaction_in_progress()
    assert canvas.wheel_navigation_mode == "traditional"
    assert w._pending_wheel_navigation_mode is None


def test_latest_mode_request_supersedes_an_earlier_pending_switch(
    window, tmp_path
):
    w = open_rectangles(window, tmp_path)
    w.canvas.set_rectangle_edge_enabled(True)
    mouse(w.canvas, QtCore.QEvent.Type.MouseMove, (100, 150))
    mouse(w.canvas, QtCore.QEvent.Type.MouseButtonPress, (100, 150))
    w.apply_wheel_navigation_mode("traditional")
    w.apply_wheel_navigation_mode("direct")
    mouse(w.canvas, QtCore.QEvent.Type.MouseButtonRelease, (100, 150))
    QtWidgets.QApplication.processEvents()
    assert w.canvas.wheel_navigation_mode == "direct"
    assert w._pending_wheel_navigation_mode is None


def test_grouping_is_one_undoable_edit_without_reloading(window, tmp_path):
    w = open_rectangles(window, tmp_path, 2)
    before = [shape.to_dict() for shape in w.canvas.shapes]
    w.actions.group_selected_shapes.trigger()
    assert len(w.canvas.shapes) == 2
    assert w.canvas.shapes[0].group_id is not None
    assert w.canvas.shapes[0].group_id == w.canvas.shapes[1].group_id
    assert w.dirty
    w.undo_shape_edit()
    assert [shape.to_dict() for shape in w.canvas.shapes] == before
    w.redo_shape_edit()
    grouped = [shape.to_dict() for shape in w.canvas.shapes]
    assert grouped[0]["group_id"] is not None
    assert w.save_labels(w.get_label_file())
    w.set_clean()
    assert w.load_file(w.filename)
    assert [shape.to_dict() for shape in w.canvas.shapes] == grouped
    w.canvas.select_shapes(w.canvas.shapes)
    w.actions.ungroup_selected_shapes.trigger()
    assert all(shape.group_id is None for shape in w.canvas.shapes)
    w.undo_shape_edit()
    assert [shape.to_dict() for shape in w.canvas.shapes] == grouped


def test_locked_group_member_prevents_partial_group_edit(window, tmp_path):
    w = open_rectangles(window, tmp_path, 2)
    for shape in w.canvas.shapes:
        shape.group_id = 7
    w.canvas.shapes[1].locked = True
    w.canvas.select_shapes([w.canvas.shapes[0]])
    before = [shape.to_dict() for shape in w.canvas.shapes]
    history = len(w.canvas.shapes_backups)
    w.ungroup_selected_shapes()
    assert [shape.to_dict() for shape in w.canvas.shapes] == before
    assert len(w.canvas.shapes_backups) == history


def test_merge_groups_keeps_unselected_members_and_unrelated_shapes(
    window, tmp_path
):
    w = open_rectangles(window, tmp_path, 4)
    for shape, group in zip(w.canvas.shapes, [7, 7, 3, 9]):
        shape.group_id = group
    w.canvas.select_shapes([w.canvas.shapes[0], w.canvas.shapes[2]])
    before = [s.to_dict() for s in w.canvas.shapes]
    w.canvas._selected_group_id = 7
    w.group_selected_shapes()
    assert [s.group_id for s in w.canvas.shapes] == [3, 3, 3, 9]
    assert w.canvas._selected_group_id is None
    w.undo_shape_edit()
    assert [s.to_dict() for s in w.canvas.shapes] == before


@pytest.mark.parametrize(
    "field",
    [
        "show_masks",
        "show_texts",
        "show_labels",
        "show_scores",
        "show_degrees",
        "show_attributes",
        "show_linking",
        "show_groups",
    ],
)
def test_display_action_uses_same_menu_toolbar_state_without_annotation_write(
    window, tmp_path, field
):
    w = open_rectangles(window, tmp_path)
    assert w.save_labels(w.get_label_file())
    w.set_clean()
    path = tmp_path / "edit.json"
    before = path.read_bytes()
    history = len(w.canvas.shapes_backups)
    action = getattr(w.actions, field)
    button = next(
        b
        for b in w.tools.findChildren(QtWidgets.QToolButton)
        if b.defaultAction() is action
    )
    initial = action.isChecked()
    button.click()
    assert getattr(w.canvas, field) is (not initial)
    assert w._config[field] is (not initial)
    assert action in w.menus.view.actions()
    action.trigger()
    assert getattr(w.canvas, field) is initial
    assert path.read_bytes() == before
    assert not w.dirty
    assert len(w.canvas.shapes_backups) == history


@pytest.mark.parametrize("mode", ["direct", "traditional"])
def test_sixteen_bit_switch_retains_latest_values_and_original_pixels(
    window, tmp_path, mode
):
    w = window.labeling_widget.view
    paths = [tmp_path / f"gray-{i}.png" for i in range(2)]
    pixels = np.arange(256 * 256, dtype=np.uint16).reshape(256, 256)
    for path in paths:
        Image.fromarray(pixels).save(path)
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    assert w.load_file(str(paths[0]))
    w.apply_wheel_navigation_mode(mode)
    w.set_zoom(150)
    w.actions.keep_prev_brightness.trigger()
    w.canvas_adjustment.brightness_slider.setValue(80)
    assert w.canvas_adjustment._bc_update_timer.isActive()
    assert w.load_file(str(paths[1]))
    QtTest.QTest.qWait(w.canvas_adjustment.BC_UPDATE_INTERVAL_MS + 20)
    assert w.canvas_adjustment.brightness_slider.value() == 80
    assert w.brightness_contrast_values[str(paths[1])][0] == 80
    assert w.brightness_contrast_processor._grayscale16_data is not None
    assert w.canvas.scale == pytest.approx(1.5)
    assert hashes == [
        hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    ]


def test_settings_mode_apply_failure_cancel_and_interleaved_keep(
    window, tmp_path, monkeypatch
):
    w = open_rectangles(window, tmp_path)
    w.open_settings_dialog(field_key="canvas.wheel_navigation_mode")
    controller = w._settings_controller
    dialog = w._settings_dialog
    controller.update_field(
        "canvas.wheel_navigation_mode", "traditional", schedule_save=False
    )
    with monkeypatch.context() as m:

        def fail(*args, **kwargs):
            raise user_config.ConfigWriteError("injected failure")

        m.setattr(user_config, "save_patch", fail)
        controller.save_now()
    assert controller.last_error is not None
    assert w.canvas.wheel_navigation_mode == "direct"
    w.canvas_adjustment.brightness_pin.click()
    user_config.save_values(
        {("digit_shortcuts", 1): {"mode": "rectangle", "label": "car"}}
    )
    controller.save_now()
    assert controller.last_error is None
    assert w.canvas.wheel_navigation_mode == "traditional"
    controller.update_field(
        "canvas.wheel_navigation_mode", "direct", schedule_save=False
    )
    dialog.close()
    assert w.canvas.wheel_navigation_mode == "traditional"
    w.open_settings_dialog(field_key="canvas.wheel_navigation_mode")
    assert (
        controller.get_value("canvas.wheel_navigation_mode") == "traditional"
    )
    assert w._config["keep_prev_brightness"]
    with open(
        user_config.current_session().target_path, encoding="utf-8"
    ) as stream:
        saved = yaml.safe_load(stream)
    assert saved["digit_shortcuts"][1]["label"] == "car"


def test_closing_settings_cancels_deferred_field_scroll(window, monkeypatch):
    """Closing before the next event tick must not access deleted rows."""
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *error: errors.append(error))
    w = window.labeling_widget.view
    w.open_settings_dialog(field_key="canvas.wheel_navigation_mode")
    dialog = w._settings_dialog
    dialog.close()
    dialog.deleteLater()
    w._settings_dialog = None
    QtWidgets.QApplication.sendPostedEvents(
        None, QtCore.QEvent.Type.DeferredDelete
    )
    QtWidgets.QApplication.processEvents()
    assert errors == []


@pytest.mark.parametrize("selection", ["locked", "multiple", "outside"])
def test_alt_wheel_geometry_history_and_saved_identity(
    window, tmp_path, selection
):
    w = open_rectangles(window, tmp_path, 2 if selection == "multiple" else 1)
    c = w.canvas
    c.enable_wheel_rectangle_editing = True
    c.auto_highlight_shape = False
    if selection == "locked":
        c.shapes[0].locked = True
    before = [s.to_dict() for s in c.shapes]
    history = len(c.shapes_backups)
    pos = (QtCore.QPointF(210, 150) + c.offset_to_center()) * c.scale
    event = QtGui.QWheelEvent(
        pos,
        pos,
        QtCore.QPoint(),
        QtCore.QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.AltModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QtWidgets.QApplication.sendEvent(c, event)
    if selection != "outside":
        assert [s.to_dict() for s in c.shapes] == before
        assert len(c.shapes_backups) == history
        return
    assert c.shapes[0].to_dict()["points"] != before[0]["points"]
    changed = [s.to_dict() for s in c.shapes]
    w.undo_shape_edit()
    assert [s.to_dict() for s in c.shapes] == before
    w.redo_shape_edit()
    assert [s.to_dict() for s in c.shapes] == changed
    assert w.save_labels(w.get_label_file())
    w.set_clean()
    assert w.load_file(w.filename)
    assert [s.to_dict() for s in c.shapes] == changed


@pytest.mark.parametrize("size", [(1, 1), (8192, 256), (256, 4096)])
@pytest.mark.parametrize("mode", ["direct", "traditional"])
def test_view_boundaries_fit_navigator_and_reset_preserve_annotation(
    window, tmp_path, size, mode
):
    w = window.labeling_widget.view
    assert w.load_file(image_path(tmp_path, "boundary.png", size=size))
    w.apply_wheel_navigation_mode(mode)
    w.load_shapes(
        [rectangle(0, 0, min(100, size[0]), min(100, size[1]))],
        update_last_label=False,
    )
    before = [s.to_dict() for s in w.canvas.shapes]
    history = len(w.canvas.shapes_backups)
    w.set_zoom(175)
    w.pan_canvas(QtCore.QPointF(120, -50))
    w.on_navigator_request(0.75, 0.25)
    QtWidgets.QApplication.processEvents()
    w.set_fit_width(True)
    QtWidgets.QApplication.processEvents()
    w.set_fit_window(True)
    QtWidgets.QApplication.processEvents()
    w.reset_shared_view()
    assert [s.to_dict() for s in w.canvas.shapes] == before
    assert len(w.canvas.shapes_backups) == history
    assert not w.dirty
    if mode == "traditional":
        assert w.canvas.pan_offset.isNull()


@pytest.mark.parametrize("mode", ["direct", "traditional"])
@pytest.mark.parametrize("pan", ["space", "right"])
def test_pan_gestures_and_mode_roundtrip_keep_shapes_and_history(
    window, tmp_path, mode, pan
):
    w = open_rectangles(window, tmp_path)
    c = w.canvas
    w.set_zoom(200)
    w.apply_wheel_navigation_mode(mode)
    before = [s.to_dict() for s in c.shapes]
    history = len(c.shapes_backups)
    start = (QtCore.QPointF(300, 250) + c.offset_to_center()) * c.scale
    end = start + QtCore.QPointF(-30, -20)
    button = (
        Qt.MouseButton.RightButton
        if pan == "right"
        else Qt.MouseButton.LeftButton
    )
    if pan == "space":
        QtTest.QTest.keyPress(c, Qt.Key.Key_Space)
    for kind, pos in [
        (QtCore.QEvent.Type.MouseButtonPress, start),
        (QtCore.QEvent.Type.MouseMove, end),
        (QtCore.QEvent.Type.MouseButtonRelease, end),
    ]:
        event = QtGui.QMouseEvent(
            kind,
            pos,
            QtCore.QPointF(c.mapToGlobal(pos.toPoint())),
            (
                Qt.MouseButton.NoButton
                if kind == QtCore.QEvent.Type.MouseMove
                else button
            ),
            (
                Qt.MouseButton.NoButton
                if kind == QtCore.QEvent.Type.MouseButtonRelease
                else button
            ),
            Qt.KeyboardModifier.NoModifier,
        )
        QtWidgets.QApplication.sendEvent(c, event)
    if pan == "space":
        QtTest.QTest.keyRelease(c, Qt.Key.Key_Space)
    QtWidgets.QApplication.processEvents()
    w.apply_wheel_navigation_mode(
        "direct" if mode == "traditional" else "traditional"
    )
    w.apply_wheel_navigation_mode(mode)
    QtWidgets.QApplication.processEvents()
    assert [s.to_dict() for s in c.shapes] == before
    assert len(c.shapes_backups) == history
    assert not w.dirty
    assert not c.interaction_in_progress()


def test_saved_controls_survive_a_real_process_restart(tmp_path):
    """Two independent application processes exercise close and fresh startup."""
    script = r"""
import sys
from PyQt6 import QtWidgets
from anylabeling.resources import resources
from anylabeling import user_config
from anylabeling.views.mainwindow import MainWindow
from scripts.dev_isolation import IsolatedConfig
app = QtWidgets.QApplication([])
with IsolatedConfig(sys.argv[1]) as isolated:
    window = MainWindow(app, config=isolated.config)
    w = window.labeling_widget.view
    if sys.argv[2] == "write":
        controller = w._settings_controller
        controller.update_field("canvas.wheel_navigation_mode", "traditional", schedule_save=False)
        assert w.update_user_preference("keep_prev_brightness", True)
        user_config.save_values({("digit_shortcuts", 1): {"mode": "rectangle", "label": "car"}})
        controller.update_field("shortcuts.open", "Ctrl+Alt+O", schedule_save=False)
        controller.save_now()
        assert controller.last_error is None
        w.canvas_adjustment.opacity_pin.setChecked(False)
        w.canvas_adjustment.opacity_slider.setValue(25)
    else:
        assert w.canvas.wheel_navigation_mode == "traditional"
        assert w.canvas_adjustment.brightness_pin.isChecked()
        assert w._config["digit_shortcuts"][1]["label"] == "car"
        assert w.actions.open.shortcut().toString() == "Ctrl+Alt+O"
        assert w.canvas_adjustment.opacity_pin.isChecked()
        assert w.canvas_adjustment.opacity_slider.value() == 100
    w.dirty = False
    window.close()
print("PROCESS-OK")
"""
    for phase in ("write", "read"):
        result = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path / "restart"), phase],
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            env=dict(
                os.environ,
                QT_QPA_PLATFORM="offscreen",
                PYTHONDONTWRITEBYTECODE="1",
            ),
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "PROCESS-OK" in result.stdout
