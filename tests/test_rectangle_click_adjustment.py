"""Regress rectangle click editing and temporary Shift point fitting."""

from pathlib import Path

import pytest
import yaml
from PyQt6 import QtCore, QtGui, QtTest, QtWidgets

from anylabeling.views.labeling import rect_edge_alignment as rea
from anylabeling.views.labeling.shape import Shape
from tests.test_rect_edge_click_canvas import box, click, send
from tests.test_rect_edge_click_canvas import editor as _editor_fixture

editor = _editor_fixture

SHIFT = QtCore.Qt.KeyboardModifier.ShiftModifier
CONTROL = QtCore.Qt.KeyboardModifier.ControlModifier


def _rectangle(
    left: float,
    top: float,
    right: float,
    bottom: float,
    label: str = "vehicle",
) -> Shape:
    """Build one closed rectangle for interaction tests."""
    shape = Shape(label=label, shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(left, top),
        QtCore.QPointF(right, top),
        QtCore.QPointF(right, bottom),
        QtCore.QPointF(left, bottom),
    ]
    shape.close()
    return shape


@pytest.mark.parametrize(
    "axis,point,expected",
    [
        ("x", (80, 400), (80, 100, 200, 300)),
        ("y", (400, 320), (100, 100, 200, 320)),
        ("x", (150, 200), (150, 100, 200, 300)),
        ("y", (150, 200), (100, 200, 200, 300)),
    ],
)
def test_axis_half_plane_commit_exits_mode_and_keeps_selection(
    editor, axis, point, expected
):
    """A successful axis adjustment exits but keeps its rectangle selected."""
    editor.rectangle_review_refinement_enabled = False
    editor.set_rect_edge_align_enabled(False)
    original = box(editor)
    assert editor.begin_rect_click_axis(axis)
    baseline = len(editor.shapes_backups)

    click(editor, point)

    assert box(editor) == expected
    assert editor.rect_edge_click.axis is None
    assert editor.selected_shapes == [editor.shapes[0]]
    assert len(editor.shapes_backups) == baseline + 1
    editor.restore_shape()
    assert box(editor) == original


@pytest.mark.parametrize("scale", [0.75, 1.5])
def test_rendered_axis_guide_spans_work_area(editor, scale):
    """Check actual guide pixels outside the old rectangle at two zooms."""
    editor.resize(800, 800)
    editor.scale = scale
    editor.rectangle_review_refinement_enabled = False
    editor.show_labels = False
    editor.show_rectangle_pixels = False
    baseline = QtGui.QPixmap(editor.size())
    editor.render(baseline)
    editor.begin_rect_click_axis("x")
    send(editor, QtCore.QEvent.Type.MouseMove, (80, 400))
    output = QtGui.QPixmap(editor.size())
    editor.render(output)
    before, after = baseline.toImage(), output.toImage()
    x = round((80 + editor.offset_to_center().x()) * scale)
    changed = sum(
        any(
            before.pixel(px, y) != after.pixel(px, y)
            for px in range(x - 1, x + 2)
        )
        for y in range(10, 90)
    )
    assert changed > 15
    assert box(editor) == (100, 100, 200, 300)


def test_native_click_switches_selection(editor):
    """A normal click continues through the native hit-test path."""
    other = _rectangle(300, 100, 400, 300)
    editor.shapes.append(other)

    click(editor, (350, 200))

    assert editor.selected_shapes == [other]


def test_native_ctrl_click_adds_to_selection(editor):
    """Ctrl-click retains native multiple-selection behavior."""
    other = _rectangle(300, 100, 400, 300)
    editor.shapes.append(other)

    click(editor, (350, 200), CONTROL)

    assert editor.selected_shapes == [editor.shapes[0], other]


def test_native_corner_drag_remains_available(editor):
    """Removing corner-click mode must not remove native corner dragging."""
    editor.rectangle_review_refinement_enabled = False
    editor.set_rect_edge_align_enabled(False)
    send(editor, QtCore.QEvent.Type.MouseMove, (100, 100))
    send(editor, QtCore.QEvent.Type.MouseButtonPress, (100, 100))
    send(editor, QtCore.QEvent.Type.MouseMove, (80, 80), held=True)
    send(editor, QtCore.QEvent.Type.MouseButtonRelease, (80, 80))

    assert box(editor) == (80, 80, 200, 300)


def test_shift_point_fit_dead_zone_commit_deselect_and_undo(editor):
    """Inside points fit, dead-zone clicks do not, and one undo restores all."""
    editor.set_rect_edge_align_enabled(False)
    original = box(editor)

    send(editor, QtCore.QEvent.Type.MouseMove, (150, 150), SHIFT)
    assert editor.rect_point_fit_pending_box is None
    click(editor, (150, 150), SHIFT)
    assert box(editor) == original
    assert editor.selected_shapes == [editor.shapes[0]]

    send(editor, QtCore.QEvent.Type.MouseMove, (120, 140), SHIFT)
    assert editor.rect_point_fit_pending_box == (120, 140, 200, 300)
    baseline = len(editor.shapes_backups)
    click(editor, (120, 140), SHIFT)

    assert box(editor) == (120, 140, 200, 300)
    assert editor.selected_shapes == []
    assert len(editor.shapes_backups) == baseline + 1
    editor.restore_shape()
    assert box(editor) == original


def test_shift_point_fit_overlapping_shape_keeps_current_target(editor):
    """An overlapping object cannot steal an explicit Shift fit gesture."""
    editor.set_rect_edge_align_enabled(False)
    target = editor.selected_shapes[0]
    other = _rectangle(110, 110, 350, 350)
    editor.shapes.append(other)

    click(editor, (120, 140), SHIFT)

    assert box(editor) == (120, 140, 200, 300)
    assert editor.selected_shapes == []
    assert target.selected is False
    assert other.selected is False


def test_shift_dead_zone_does_not_select_overlapping_shape(editor):
    """The ambiguous band remains owned by the active Shift gesture."""
    target = editor.selected_shapes[0]
    other = _rectangle(110, 110, 350, 350)
    editor.shapes.append(other)

    click(editor, (150, 150), SHIFT)

    assert editor.selected_shapes == [target]
    assert other.selected is False
    assert box(editor) == (100, 100, 200, 300)


def test_shift_click_without_valid_target_falls_back_to_native_selection(
    editor,
):
    """Shift does not swallow selection when no valid fit target exists."""
    other = _rectangle(300, 100, 400, 300)
    editor.shapes.append(other)
    editor.deselect_shape()

    click(editor, (350, 200), SHIFT)

    assert editor.selected_shapes == [other]


def test_releasing_shift_before_mouse_release_cancels_and_consumes(editor):
    """The modifier must remain held through the left-button release."""
    original = box(editor)
    baseline = len(editor.shapes_backups)
    send(editor, QtCore.QEvent.Type.MouseButtonPress, (120, 140), SHIFT)
    assert editor.rect_point_fit_consume_release

    QtTest.QTest.keyRelease(editor, QtCore.Qt.Key.Key_Shift)
    send(editor, QtCore.QEvent.Type.MouseButtonRelease, (120, 140))

    assert box(editor) == original
    assert editor.selected_shapes == [editor.shapes[0]]
    assert len(editor.shapes_backups) == baseline
    assert not editor.rect_point_fit_consume_release


def test_shift_release_clears_hover_preview(editor):
    """A preview disappears as soon as Shift is released."""
    send(editor, QtCore.QEvent.Type.MouseMove, (120, 140), SHIFT)
    assert editor.rect_point_fit_preview is not None

    QtTest.QTest.keyRelease(editor, QtCore.Qt.Key.Key_Shift)

    assert editor.rect_point_fit_preview is None
    assert editor.rect_point_fit_pending_box is None


@pytest.mark.parametrize("interrupt", ["page", "window", "hidden"])
def test_point_fit_context_change_cancels_pending_gesture(editor, interrupt):
    """Page, focus, and target lifecycle changes cannot leak a gesture."""
    target = editor.selected_shapes[0]
    original = box(editor)
    send(editor, QtCore.QEvent.Type.MouseButtonPress, (120, 140), SHIFT)
    assert editor.rect_point_fit_consume_release

    if interrupt == "page":
        editor.load_pixmap(QtGui.QPixmap(500, 500), clear_shapes=False)
    elif interrupt == "window":
        QtWidgets.QApplication.sendEvent(
            editor, QtCore.QEvent(QtCore.QEvent.Type.WindowDeactivate)
        )
    else:
        editor.set_shape_visible(target, False)

    assert not editor.rect_point_fit_consume_release
    assert editor.rect_point_fit_preview is None
    assert (
        editor.rect_edge_click.box(rea.geometry_from_shape(target)) == original
    )


def test_axis_recomputes_center_after_new_activation(editor):
    """A new one-shot axis activation uses the committed rectangle center."""
    editor.begin_rect_click_axis("x")
    baseline = len(editor.shapes_backups)
    click(editor, (80, 400))
    editor.begin_rect_click_axis("x")
    click(editor, (145, 400))

    assert box(editor) == (80, 100, 145, 300)
    assert editor.rect_edge_click.axis is None
    assert editor.selected_shapes == [editor.shapes[0]]
    assert len(editor.shapes_backups) == baseline + 2


def test_real_window_has_no_retired_actions_or_shortcuts(
    qapp, monkeypatch, tmp_path
):
    """Production UI keeps axis actions but exposes no F11/F12 modes."""
    from anylabeling.services.auto_labeling import model_manager
    from anylabeling.views.labeling import label_widget as module

    config = yaml.safe_load(
        (
            Path(__file__).parents[1]
            / "anylabeling/configs/xanylabeling_config.yaml"
        ).read_text(encoding="utf-8")
    )
    config["auto_save"] = False
    monkeypatch.setattr(module, "save_config", lambda _config: True)
    monkeypatch.setattr(model_manager, "get_config", lambda: config)
    window = QtWidgets.QMainWindow()
    wrapper = QtWidgets.QWidget()
    wrapper.parent = window
    widget = module.LabelingWidget(parent=wrapper, config=config)
    window.setCentralWidget(widget)
    widget.settings = QtCore.QSettings(
        str(tmp_path / "ui.ini"), QtCore.QSettings.Format.IniFormat
    )
    try:
        window.resize(1000, 800)
        window.show()
        canvas = widget.canvas
        pixmap = QtGui.QPixmap(500, 500)
        pixmap.fill(QtGui.QColor("white"))
        canvas.load_pixmap(pixmap)
        shape = _rectangle(100, 100, 200, 300, label="person")
        canvas.load_shapes([shape])
        canvas.set_editing(True)
        canvas.select_shapes([shape])
        canvas.setFocus()
        qapp.processEvents()

        assert not hasattr(widget.actions, "toggle_rect_angle_click")
        assert not hasattr(widget.actions, "toggle_rect_point_fit")
        assert not hasattr(canvas, "rect_angle_click_enabled")
        assert not hasattr(canvas, "rect_point_fit_enabled")
        QtTest.QTest.keyClick(canvas, QtCore.Qt.Key.Key_F11)
        QtTest.QTest.keyClick(canvas, QtCore.Qt.Key.Key_F12)
        assert canvas.selected_shapes == [shape]

        QtTest.QTest.keyClick(canvas, QtCore.Qt.Key.Key_X)
        assert canvas.rect_edge_click.axis == "x"
        QtTest.QTest.keyClick(canvas, QtCore.Qt.Key.Key_Escape)
        edit = QtWidgets.QLineEdit(widget)
        edit.show()
        edit.setFocus()
        qapp.processEvents()
        QtTest.QTest.keyClicks(edit, "xy")
        assert edit.text() == "xy"
        assert canvas.rect_edge_click.axis is None
    finally:
        widget.dirty = False
        window.hide()
        widget.deleteLater()
        wrapper.deleteLater()
        window.deleteLater()
        qapp.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def test_click_strings_are_in_compiled_translations(qapp):
    """Shipped resources retain the axis-click menu translation."""
    import anylabeling.resources.resources  # noqa: F401

    for language, expected in (
        ("zh_CN", "矩形点击调整"),
        ("en_US", "Rectangle click adjustment"),
    ):
        translator = QtCore.QTranslator()
        assert translator.load(f":/languages/translations/{language}.qm")
        qapp.installTranslator(translator)
        try:
            assert (
                QtCore.QCoreApplication.translate(
                    "LabelingWidget", "矩形点击调整"
                )
                == expected
            )
        finally:
            qapp.removeTranslator(translator)


def test_retired_shortcut_keys_are_tolerated_in_legacy_config(
    tmp_path, monkeypatch
):
    """Unknown retired keys do not reset unrelated user configuration."""
    from anylabeling import config as config_module

    legacy = yaml.safe_load(
        (
            Path(__file__).parents[1]
            / "anylabeling/configs/xanylabeling_config.yaml"
        ).read_text(encoding="utf-8")
    )
    legacy["shortcuts"]["toggle_rect_angle_click"] = "F11"
    legacy["shortcuts"]["toggle_rect_point_fit"] = "F12"
    legacy["shortcuts"]["rectangle_click_adjust_x"] = "F8"
    path = tmp_path / "legacy.yaml"
    path.write_text(yaml.safe_dump(legacy), encoding="utf-8")
    monkeypatch.setattr(config_module, "current_config_file", str(path))

    loaded = config_module.get_config(str(path))

    assert loaded["shortcuts"]["rectangle_click_adjust_x"] == "F8"


def test_axis_settings_conflict_and_reload(qapp, tmp_path, monkeypatch):
    """Save both axis bindings via settings and reload an isolated YAML."""
    from anylabeling import config as config_module
    from anylabeling.views.labeling.settings.controller import (
        SettingsController,
        SettingsValidationError,
    )

    config = yaml.safe_load(
        (
            Path(__file__).parents[1]
            / "anylabeling/configs/xanylabeling_config.yaml"
        ).read_text(encoding="utf-8")
    )
    path = tmp_path / "settings.yaml"
    monkeypatch.setattr(config_module, "current_config_file", str(path))
    controller = SettingsController(config, defer_runtime_apply=True)
    x, y = (
        "shortcuts.rectangle_click_adjust_x",
        "shortcuts.rectangle_click_adjust_y",
    )
    with pytest.raises(SettingsValidationError):
        controller.update_field(x, "Ctrl+S", schedule_save=False)
    assert controller.get_value(x) == "X"
    controller.update_field(x, "F8", schedule_save=False)
    controller.update_field(y, "Ctrl+Alt+Shift+F8", schedule_save=False)
    controller.save_now()
    reloaded = config_module.get_config(str(path))
    assert reloaded["shortcuts"]["rectangle_click_adjust_x"] == "F8"
    assert reloaded["shortcuts"]["rectangle_click_adjust_y"] == (
        "Ctrl+Alt+Shift+F8"
    )
