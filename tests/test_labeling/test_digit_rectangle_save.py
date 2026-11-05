"""Exercise digit shortcuts through mouse completion and JSON reload."""

import copy
import json
from unittest.mock import Mock

import pytest
from PIL import Image
from PyQt6 import QtCore, QtTest, QtWidgets

from anylabeling import config as app_config, user_config
from anylabeling.config import normalize_user_config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.mainwindow import MainWindow


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance()
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
    monkeypatch.setattr(app_config, "current_config_file", str(config_path))
    settings_class = QtCore.QSettings
    monkeypatch.setattr(
        QtCore, "QSettings",
        lambda *args: settings_class(
            str(tmp_path / "settings.ini"), settings_class.Format.IniFormat
        ),
    )
    config = copy.deepcopy(load_template_config())
    user_config.begin_session(
        target_path=str(config_path), origin="file",
        template=copy.deepcopy(config), effective=copy.deepcopy(config),
        ensure_created=True, normalizer=normalize_user_config,
    )
    result = MainWindow(app, config=config)
    result.resize(1400, 900)
    result.show()
    result.activateWindow()
    app.processEvents()
    widget = result.labeling_widget.view
    widget.error_message = Mock()
    # A digit binding must avoid the label popup entirely.
    widget.label_dialog.pop_up = Mock(side_effect=AssertionError("Unexpected popup"))
    yield result
    widget.dirty = False
    result.close()
    app.removeEventFilter(widget)
    result.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def draw_rectangle(widget, digit, first=(20, 30), second=(100, 110)):
    canvas = widget.canvas
    canvas.setFocus()
    QtWidgets.QApplication.processEvents()
    QtTest.QTest.keyClick(canvas, getattr(QtCore.Qt.Key, f"Key_{digit}"))
    assert canvas.drawing()
    assert canvas.create_mode == "rectangle"
    assert widget.digit_to_label == "车辆"

    for x, y in (first, second):
        point = (QtCore.QPointF(x, y) + canvas.offset_to_center()) * canvas.scale
        QtTest.QTest.mouseClick(
            canvas, QtCore.Qt.MouseButton.LeftButton, pos=point.toPoint()
        )
    QtWidgets.QApplication.processEvents()
    assert canvas.current is None
    assert len(canvas.shapes) == 1
    assert len(widget.label_list) == 1
    widget.error_message.assert_not_called()


@pytest.mark.parametrize("auto_save", [True, False])
@pytest.mark.parametrize("use_output_dir", [False, True])
@pytest.mark.parametrize("popup", [True, False])
@pytest.mark.parametrize("selected_label", [False, True])
def test_digit_rectangle_save_roundtrip(
    window, tmp_path, monkeypatch, request,
    auto_save, use_output_dir, popup, selected_label
):
    if selected_label and not popup:
        request.applymarker(pytest.mark.xfail(
            strict=True,
            reason="new_shape bypasses the digit label when a class is selected and the label popup is disabled",
        ))
    widget = window.labeling_widget.view
    widget._config.update(auto_save=auto_save, display_label_popup=popup)
    widget.drawing_digit_shortcuts = {3: {"label": "车辆", "mode": "rectangle"}}
    image_path = tmp_path / "image.png"
    Image.new("RGB", (200, 160), "white").save(image_path)
    if use_output_dir:
        widget.output_dir = str(tmp_path / "labels")
    assert widget.load_file(str(image_path))
    if selected_label:
        item = widget.unique_label_list.create_item_from_label("其他类别")
        widget.unique_label_list.addItem(item)
        item.setSelected(True)

    target = (tmp_path / "labels" if use_output_dir else tmp_path) / "image.json"
    draw_rectangle(widget, 3)
    if not auto_save:
        assert widget.dirty
        assert widget.actions.save.isEnabled()
        assert not target.exists()
        monkeypatch.setattr(widget, "save_file_dialog", lambda: str(target))
        QtTest.QTest.keyClick(
            widget.canvas, QtCore.Qt.Key.Key_S,
            QtCore.Qt.KeyboardModifier.ControlModifier,
        )
        QtWidgets.QApplication.processEvents()

    assert target.exists()
    assert not widget.dirty
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert len(saved["shapes"]) == 1
    shape = saved["shapes"][0]
    assert shape["label"] == "车辆"
    assert shape["shape_type"] == "rectangle"
    assert len(shape["points"]) == 4
    for actual, expected in zip(shape["points"], [(20, 30), (100, 30), (100, 110), (20, 110)]):
        assert actual == pytest.approx(expected, abs=0.6)
    assert saved["imageWidth"] == 200
    assert saved["imageHeight"] == 160
    assert widget.load_file(str(image_path))
    assert len(widget.canvas.shapes) == 1
    restored = widget.canvas.shapes[0].to_dict()
    assert restored["label"] == "车辆"
    assert [list(point) for point in restored["points"]] == shape["points"]
    widget.error_message.assert_not_called()


@pytest.mark.parametrize("digit", range(10))
def test_every_digit_can_save_a_rectangle(window, tmp_path, digit):
    widget = window.labeling_widget.view
    widget._config.update(auto_save=True, display_label_popup=True)
    widget.drawing_digit_shortcuts = {digit: {"label": "车辆", "mode": "rectangle"}}
    image_path = tmp_path / "image.png"
    Image.new("RGB", (200, 160), "white").save(image_path)
    assert widget.load_file(str(image_path))
    draw_rectangle(widget, digit)
    saved = json.loads(image_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert saved["shapes"][0]["label"] == "车辆"
    assert saved["shapes"][0]["shape_type"] == "rectangle"
