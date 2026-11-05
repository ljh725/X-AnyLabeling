"""Real window integration for settings, digit drawing and canvas retention."""

import json
import os
import shutil
import uuid

import pytest
import yaml
from PIL import Image
from PyQt6 import QtCore, QtTest, QtWidgets

from anylabeling import config as app_config, user_config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.views.mainwindow import MainWindow
from anylabeling.views.labeling.widgets.label_dialog import DigitShortcutDialog


@pytest.fixture
def workspace():
    root = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        ".tmp",
        "settings-window-integration",
        uuid.uuid4().hex,
    )
    os.makedirs(root, exist_ok=True)
    target = os.path.join(root, "config.yaml")
    with open(target, "w", encoding="utf-8") as stream:
        stream.write("{}")
    app = QtWidgets.QApplication.instance()
    windows = []

    def close(window):
        view = window.labeling_widget.view
        view.dirty = False
        if view._settings_dialog is not None:
            view._settings_dialog.close()
        window.close()
        for _attempt in range(100):
            if not window.isVisible():
                break
            QtTest.QTest.qWait(10)
        assert (
            not window.isVisible()
        ), "window did not complete its close lifecycle"
        app.removeEventFilter(view)
        window.deleteLater()
        app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        windows.remove(window)
        user_config.end_session()

    def open_window():
        app_config.set_work_directory(root)
        config = app_config.get_config(
            target, {"auto_save": False, "labels": ["车辆"]}
        )
        window = MainWindow(app, config=config)
        windows.append(window)
        window.resize(1400, 900)
        window.show()
        app.processEvents()
        return window

    yield root, target, open_window, close
    for window in list(windows):
        close(window)
    shutil.rmtree(root, ignore_errors=True)


def save_digit_through_the_main_window(view, before_retry=None):
    errors = []

    def fill_dialog():
        dialog = QtWidgets.QApplication.activeModalWidget()
        try:
            assert isinstance(dialog, DigitShortcutDialog)
            combo = dialog._get_combo(1)
            combo.setCurrentIndex(combo.findData("rectangle"))
            dialog._get_label_edit(1).setText("车辆")
            dialog.save_settings()
            if before_retry is not None:
                assert dialog.isVisible()
                assert dialog._get_label_edit(1).text() == "车辆"
                before_retry()
                dialog.save_settings()
            assert dialog.result() == QtWidgets.QDialog.DialogCode.Accepted
        except Exception as error:
            errors.append(error)
            if dialog is not None:
                dialog.reject()

    QtCore.QTimer.singleShot(0, fill_dialog)
    view.digit_shortcut_manager()
    if errors:
        raise errors[0]


def test_real_entries_interleave_restart_and_keep_drawing_bindings(
    workspace, monkeypatch
):
    root, target, open_window, close = workspace
    first_image = os.path.join(root, "first.png")
    next_image = os.path.join(root, "next.png")
    Image.new("RGB", (200, 160), "white").save(first_image)
    Image.new("RGB", (200, 160), "blue").save(next_image)
    window = open_window()
    view = window.labeling_widget.view
    assert view.load_file(first_image)
    view.open_settings_dialog()
    controller = view._settings_controller
    # Leave a draft open while the digit manager and canvas controls save.
    controller.update_field("canvas.epsilon", 9.5, schedule_save=False)
    save_digit_through_the_main_window(view)
    view.actions.keep_prev_brightness.trigger()
    view.canvas_adjustment.contrast_pin.click()
    assert view.canvas_adjustment.brightness_pin.isChecked()
    assert view.actions.keep_prev_contrast.isChecked()
    wanted = "Ctrl+Alt+Shift+F12"
    controller.update_field("shortcuts.open", wanted, schedule_save=False)
    controller.update_field(
        "canvas.wheel_navigation_mode", "traditional", schedule_save=False
    )
    controller.save_now()
    assert controller.last_error is None
    assert not controller.has_pending_apply()
    assert view.actions.open.shortcut().toString() == wanted
    assert view.canvas.wheel_navigation_mode == "traditional"
    view._on_inline_brightness_contrast(70, 80)
    view.canvas_adjustment.set_brightness_contrast(70, 80)
    assert view.load_file(next_image)
    assert view.canvas_adjustment.brightness_slider.value() == 70
    assert view.canvas_adjustment.contrast_slider.value() == 80

    model_file = os.path.join(root, "model.yaml")
    model = {
        "type": "yolov8",
        "name": "settings-review-model",
        "display_name": "Settings review model",
        "config_file": model_file,
        "classes": ["车辆"],
    }
    with open(model_file, "w", encoding="utf-8") as stream:
        yaml.safe_dump(model, stream, allow_unicode=True)
    manager = view.auto_labeling_widget.model_manager
    assert manager.save_custom_models([model])
    manager.load_model_configs()
    assert any(
        item["config_file"] == model_file
        for item in manager.get_model_configs()
    )
    close(window)

    window = open_window()
    view = window.labeling_widget.view
    assert view.actions.open.shortcut().toString() == wanted
    assert view._config["canvas"]["epsilon"] == 9.5
    assert view.canvas.wheel_navigation_mode == "traditional"
    assert view.actions.keep_prev_brightness.isChecked()
    assert view.canvas_adjustment.contrast_pin.isChecked()
    assert view.drawing_digit_shortcuts[1] == {
        "mode": "rectangle",
        "label": "车辆",
    }
    assert any(
        item["config_file"] == model_file
        for item in view.auto_labeling_widget.model_manager.get_model_configs()
    )
    assert view.load_file(first_image)
    canvas = view.canvas
    canvas.setFocus()
    QtTest.QTest.keyClick(canvas, QtCore.Qt.Key.Key_1)
    assert canvas.drawing() and canvas.create_mode == "rectangle"
    assert view.digit_to_label == "车辆"
    for x, y in ((20, 30), (100, 110)):
        point = (
            QtCore.QPointF(x, y) + canvas.offset_to_center()
        ) * canvas.scale
        QtTest.QTest.mouseClick(
            canvas, QtCore.Qt.MouseButton.LeftButton, pos=point.toPoint()
        )
    assert len(canvas.shapes) == 1
    annotation = os.path.join(root, "first.json")
    monkeypatch.setattr(view, "save_file_dialog", lambda: annotation)
    view.save_file()
    with open(annotation, encoding="utf-8") as stream:
        saved = json.load(stream)
    assert saved["shapes"][0]["label"] == "车辆"
    assert saved["shapes"][0]["shape_type"] == "rectangle"
    with open(target, encoding="utf-8") as stream:
        persisted = yaml.safe_load(stream)
    assert persisted["digit_shortcuts"][1]["label"] == "车辆"
    assert persisted["shortcuts"]["open"] == wanted
    assert (
        persisted["keep_prev_brightness"] and persisted["keep_prev_contrast"]
    )


def test_main_window_digit_failure_preserves_input_for_retry(
    workspace, monkeypatch
):
    root, target, open_window, close = workspace
    view = open_window().labeling_widget.view
    real_save = user_config.save_patch
    warnings = []

    def fail_save(patch):
        raise user_config.ConfigWriteError("simulated disk failure")

    monkeypatch.setattr(user_config, "save_patch", fail_save)
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "warning", lambda *args: warnings.append(args)
    )
    save_digit_through_the_main_window(
        view,
        before_retry=lambda: monkeypatch.setattr(
            user_config, "save_patch", real_save
        ),
    )
    assert warnings
    assert view.drawing_digit_shortcuts[1]["label"] == "车辆"
