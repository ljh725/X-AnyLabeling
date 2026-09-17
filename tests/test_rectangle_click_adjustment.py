"""Regress the explicit axis/corner workflow through real Qt input."""

from pathlib import Path

import pytest
import yaml
from PyQt6 import QtCore, QtGui, QtTest, QtWidgets

from tests.test_rect_edge_click_canvas import box, click, send
from tests.test_rect_edge_click_canvas import editor as _editor_fixture

editor = _editor_fixture


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
    """A successful shortcut adjustment exits but keeps its rectangle selected."""
    editor.rectangle_review_refinement_enabled = False
    editor.set_rect_edge_align_enabled(False)
    original = box(editor)
    assert editor.begin_rect_click_axis(axis)
    assert editor.rect_edge_click.message
    baseline = len(editor.shapes_backups)
    click(editor, point)
    assert box(editor) == expected
    assert editor.rect_edge_click.axis is None
    assert editor.selected_shapes == [editor.shapes[0]]
    assert editor.shapes[0].selected is True
    assert len(editor.shapes_backups) == baseline + 1
    editor.restore_shape()
    assert box(editor) == original


@pytest.mark.parametrize("scale", [0.75, 1.5])
def test_rendered_axis_guide_spans_work_area(editor, scale):
    """Check actual painted pixels outside the old rectangle at two zooms."""
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
    assert changed > 15, "No reference line painted above the old rectangle"
    assert box(editor) == (100, 100, 200, 300)
    if scale == 0.75:
        output_path = (
            Path(__file__).parents[1]
            / "artifacts/rectangle-click-adjustment/axis-preview.png"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        assert output.save(str(output_path))


def test_corner_two_clicks_reject_flip_and_keep_corner(editor):
    """Corner choice is explicit; each valid target is one undo item."""
    editor.set_rect_edge_align_enabled(False)
    editor.set_rect_angle_click_enabled(True)
    baseline = len(editor.shapes_backups)
    click(editor, (100, 100))
    assert len(editor.shapes_backups) == baseline
    click(
        editor, (160, 220)
    )  # Cross center, but remain above/left of opposite.
    assert box(editor) == (160, 220, 200, 300)
    assert editor.rect_angle_click_corner == 0
    assert len(editor.shapes_backups) == baseline + 1
    click(editor, (210, 310))  # Flipping the specified corner is invalid.
    assert box(editor) == (160, 220, 200, 300)
    assert len(editor.shapes_backups) == baseline + 1
    click(editor, (140, 180))
    assert box(editor) == (140, 180, 200, 300)
    assert len(editor.shapes_backups) == baseline + 2
    QtTest.QTest.keyClick(editor, QtCore.Qt.Key.Key_Escape)
    assert not editor.rect_angle_click_enabled
    assert editor.selected_shapes == [editor.shapes[0]]
    editor.restore_shape()
    assert box(editor) == (160, 220, 200, 300)


@pytest.mark.parametrize("mode", ["axis", "corner"])
def test_guides_and_commit_in_scrolled_viewport(editor, qapp, mode):
    """Render both guide directions after real scroll-area pan and zoom."""
    scroll = QtWidgets.QScrollArea()
    scroll.resize(400, 400)
    editor.scale = 2
    editor.resize(1000, 1000)
    editor.show_labels = False
    editor.show_rectangle_pixels = False
    scroll.setWidget(editor)
    try:
        scroll.show()
        scroll.activateWindow()
        scroll.horizontalScrollBar().setValue(100)
        scroll.verticalScrollBar().setValue(100)
        editor.setFocus()
        qapp.processEvents()
        if mode == "axis":
            editor.begin_rect_click_axis("x")
        else:
            editor.set_rect_angle_click_enabled(True)
            click(editor, (100, 100))
        send(editor, QtCore.QEvent.Type.MouseMove, (130, 220))
        qapp.processEvents()
        rendered = scroll.viewport().grab().toImage()
        x = 260 - scroll.horizontalScrollBar().value()
        y = 440 - scroll.verticalScrollBar().value()

        def guide_pixel(px, py):
            """Identify cyan guide pixels independently of the old frame."""
            color = rendered.pixelColor(px, py)
            return color.blue() > 180 and color.red() < 100

        assert (
            sum(
                any(guide_pixel(px, py) for px in range(x - 1, x + 2))
                for py in range(10, 80)
            )
            > 15
        )
        if mode == "corner":
            assert (
                sum(
                    any(guide_pixel(px, py) for py in range(y - 1, y + 2))
                    for px in range(10, 80)
                )
                > 15
            )
            output_path = (
                Path(__file__).parents[1]
                / "artifacts/rectangle-click-adjustment/corner-preview.png"
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            assert rendered.save(str(output_path))
        assert box(editor) == (100, 100, 200, 300)
        click(editor, (130, 220))
        assert box(editor) == (130, 220 if mode == "corner" else 100, 200, 300)
    finally:
        scroll.takeWidget()
        editor.setParent(None)
        scroll.close()
        scroll.deleteLater()


@pytest.mark.parametrize("mode", ["axis", "corner"])
@pytest.mark.parametrize(
    "interrupt", ["focus", "selection", "image", "escape", "hidden"]
)
def test_modes_cancel_even_before_pointer_moves(editor, mode, interrupt):
    """No-preview states must also be canceled on context changes."""
    if mode == "axis":
        editor.begin_rect_click_axis("x")
    else:
        editor.set_rect_angle_click_enabled(True)
    baseline = len(editor.shapes_backups)
    if interrupt == "focus":
        editor.focusOutEvent(QtGui.QFocusEvent(QtCore.QEvent.Type.FocusOut))
    elif interrupt == "selection":
        editor.select_shapes([])
    elif interrupt == "image":
        editor.load_pixmap(QtGui.QPixmap(500, 500))
    elif interrupt == "hidden":
        editor.set_shape_visible(editor.shapes[0], False)
    else:
        QtTest.QTest.keyClick(editor, QtCore.Qt.Key.Key_Escape)
    assert editor.rect_edge_click.axis is None
    assert not editor.rect_angle_click_enabled
    assert editor.rect_angle_click_preview is None
    if interrupt != "image":
        assert len(editor.shapes_backups) == baseline


def test_axis_and_corner_switch_exclusively(editor):
    """Switching methods cancels previews without creating history."""
    baseline = len(editor.shapes_backups)
    editor.begin_rect_click_axis("x")
    editor.set_rect_angle_click_enabled(True)
    assert editor.rect_edge_click.axis is None
    click(editor, (100, 100))
    editor.begin_rect_click_axis("y")
    assert not editor.rect_angle_click_enabled
    assert editor.rect_angle_click_preview is None
    assert len(editor.shapes_backups) == baseline


def test_real_window_shortcuts_settings_and_text_focus(
    qapp, monkeypatch, tmp_path
):
    """Use production actions with actual key events, not action.trigger()."""
    from anylabeling.views.labeling import label_widget as module
    from anylabeling.services.auto_labeling import model_manager
    from anylabeling.views.labeling.shape import Shape
    import sys
    import traceback

    slot_errors = []
    monkeypatch.setattr(
        sys,
        "excepthook",
        lambda *args: slot_errors.append(
            "".join(traceback.format_exception(*args))
        ),
    )

    config = yaml.safe_load(
        (
            Path(__file__).parents[1]
            / "anylabeling/configs/xanylabeling_config.yaml"
        ).read_text(encoding="utf-8")
    )
    config["auto_save"] = False
    config["rectangle_workflow"]["enabled"] = True
    config["rectangle_review_refinement"]["enabled"] = True
    config["shortcuts"]["rectangle_refine"] = "F8"
    config["shortcuts"]["rectangle_keyboard_fit"] = "F8"
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
        window.activateWindow()
        canvas = widget.canvas
        pixmap = QtGui.QPixmap(500, 500)
        pixmap.fill(QtGui.QColor("white"))
        canvas.load_pixmap(pixmap)
        shape = Shape(label="person", shape_type="rectangle")
        shape.points = [
            QtCore.QPointF(100, 100),
            QtCore.QPointF(200, 100),
            QtCore.QPointF(200, 300),
            QtCore.QPointF(100, 300),
        ]
        shape.close()
        canvas.load_shapes([shape])
        canvas.set_editing(True)
        canvas.select_shapes([shape])
        canvas.setFocus()
        QtTest.QTest.qWait(50)
        assert canvas.hasFocus()
        assert not widget.actions.toggle_rect_angle_click.isChecked()
        canvas.select_shapes([])
        assert not widget.actions.toggle_rect_angle_click.isEnabled()
        canvas.select_shapes([shape])
        assert widget.actions.toggle_rect_angle_click.isEnabled()
        assert not hasattr(widget, "rectangle_workflow")
        assert not hasattr(widget.actions, "rectangle_refine")
        assert not hasattr(widget.actions, "rectangle_keyboard_fit")
        assert not canvas.rectangle_review_refinement_enabled
        QtTest.QTest.keyClick(canvas, QtCore.Qt.Key.Key_F8)
        assert canvas.rect_edge_click.axis is None
        QtTest.QTest.keyClick(canvas, QtCore.Qt.Key.Key_X)
        assert canvas.rect_edge_click.axis == "x"
        click(canvas, (80, 400))
        assert box(canvas) == (80, 100, 200, 300)
        assert canvas.rect_edge_click.axis is None
        assert canvas.selected_shapes == [shape]
        QtTest.QTest.keyClick(canvas, QtCore.Qt.Key.Key_Y)
        assert canvas.rect_edge_click.axis == "y"
        QtTest.QTest.keyClick(canvas, QtCore.Qt.Key.Key_Escape)
        applier = widget._settings_runtime_applier
        applier.apply_shortcuts("shortcuts.rectangle_click_adjust_x", "F8")
        QtTest.QTest.keyClick(canvas, QtCore.Qt.Key.Key_X)
        assert canvas.rect_edge_click.axis is None
        QtTest.QTest.keyClick(canvas, QtCore.Qt.Key.Key_F8)
        assert canvas.rect_edge_click.axis == "x"
        QtTest.QTest.keyClick(canvas, QtCore.Qt.Key.Key_Escape)
        applier.apply_shortcuts("shortcuts.rectangle_click_adjust_x", None)
        QtTest.QTest.keyClick(canvas, QtCore.Qt.Key.Key_F8)
        assert canvas.rect_edge_click.axis is None
        widget.actions.toggle_rect_angle_click.trigger()
        assert canvas.rect_angle_click_enabled
        QtTest.QTest.keyClick(canvas, QtCore.Qt.Key.Key_Y)
        assert not widget.actions.toggle_rect_angle_click.isChecked()
        assert canvas.rect_edge_click.axis == "y"
        edit = QtWidgets.QLineEdit(widget)
        edit.show()
        edit.setFocus()
        qapp.processEvents()
        QtTest.QTest.keyClicks(edit, "xy")
        assert edit.text() == "xy"
        assert canvas.rect_edge_click.axis is None
        assert not slot_errors, "\n".join(slot_errors)
    finally:
        widget.dirty = False
        window.hide()
        widget.deleteLater()
        wrapper.deleteLater()
        window.deleteLater()
        qapp.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def test_corner_legacy_two_points_noop_and_invalid_bounds(editor):
    """Legacy two-point rectangles support all four canonical corners."""
    shape = editor.shapes[0]
    shape.points = [QtCore.QPointF(100, 100), QtCore.QPointF(200, 300)]
    editor.set_rect_angle_click_enabled(True)
    baseline = len(editor.shapes_backups)
    click(editor, (200, 100))
    assert editor.rect_angle_click_corner == 1
    click(editor, (550, 80))
    assert box(editor) == (100, 100, 200, 300)
    assert len(editor.shapes_backups) == baseline
    click(editor, (230, 80))
    assert box(editor) == (100, 80, 230, 300)
    assert len(editor.shapes_backups) == baseline + 1


def test_normal_corner_drag_after_click_mode_exit(editor):
    """Esc returns the same selected shape to the native drag handler."""
    editor.rectangle_review_refinement_enabled = False
    editor.set_rect_angle_click_enabled(True)
    QtTest.QTest.keyClick(editor, QtCore.Qt.Key.Key_Escape)
    send(editor, QtCore.QEvent.Type.MouseMove, (100, 100))
    send(editor, QtCore.QEvent.Type.MouseButtonPress, (100, 100))
    send(editor, QtCore.QEvent.Type.MouseMove, (80, 80), held=True)
    send(editor, QtCore.QEvent.Type.MouseButtonRelease, (80, 80))
    assert box(editor) == (80, 80, 200, 300)


def test_axis_recomputes_center_after_new_activation(editor):
    """A new one-shot activation uses the previously committed center."""
    editor.begin_rect_click_axis("x")
    baseline = len(editor.shapes_backups)
    send(editor, QtCore.QEvent.Type.MouseMove, (80, 400))
    send(editor, QtCore.QEvent.Type.MouseMove, (145, 400))
    assert editor.rect_edge_hover_edge.edge_name == "left"
    click(editor, (80, 400))
    assert editor.selected_shapes == [editor.shapes[0]]
    editor.begin_rect_click_axis("x")
    click(editor, (145, 400))
    assert box(editor) == (80, 100, 145, 300)
    assert editor.rect_edge_click.axis is None
    assert editor.selected_shapes == [editor.shapes[0]]
    assert len(editor.shapes_backups) == baseline + 2


def test_new_click_strings_are_in_compiled_translations(qapp):
    """The shipped resources contain the new menu and status translations."""
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
        assert translator.translate(
            "RectangleEdgeClick",
            "Modify {axis}: click a boundary; Esc to exit.",
        )


def test_axis_settings_conflict_clear_defaults_and_reload(
    qapp, tmp_path, monkeypatch
):
    """Save both new bindings via settings and reload an isolated YAML."""
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
    assert (
        yaml.safe_load(path.read_text(encoding="utf-8"))["shortcuts"][
            "rectangle_click_adjust_x"
        ]
        == "F8"
    )
    reloaded = config_module.get_config(str(path))
    assert (
        reloaded["shortcuts"]["rectangle_click_adjust_y"]
        == "Ctrl+Alt+Shift+F8"
    )
    controller.update_field(x, None, schedule_save=False)
    controller.save_now()
    assert (
        config_module.get_config(str(path))["shortcuts"][
            "rectangle_click_adjust_x"
        ]
        is None
    )
    controller.update_field(
        x, controller.get_default_value(x), schedule_save=False
    )
    controller.save_now()
    assert (
        config_module.get_config(str(path))["shortcuts"][
            "rectangle_click_adjust_x"
        ]
        == "X"
    )
