"""Regression checks for UI density and four-boundary rectangles."""

import copy
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtGui, QtTest, QtWidgets

import anylabeling.resources.resources  # noqa: F401
from anylabeling import config as app_config
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.mainwindow import MainWindow


@pytest.fixture
def window(tmp_path, monkeypatch):
    """Create a main window with isolated settings."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
    config_file = tmp_path / "config.yaml"
    config_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(app_config, "current_config_file", str(config_file))
    settings = QtCore.QSettings
    monkeypatch.setattr(
        QtCore, "QSettings", lambda *args: settings(
            str(tmp_path / "settings.ini"), settings.Format.IniFormat
        )
    )
    win = MainWindow(app, config=copy.deepcopy(load_template_config()))
    win.resize(2200, 1300)
    win.show()
    app.processEvents()
    yield win
    win.labeling_widget.view.dirty = False
    win.close()
    app.removeEventFilter(win.labeling_widget.view)
    win.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def test_density_uses_outer_window_size(window, monkeypatch):
    """Child layout changes must not change the computed density."""
    widget = window.labeling_widget.view
    monkeypatch.setattr(widget, "width", lambda: 100)
    monkeypatch.setattr(widget, "height", lambda: 100)
    widget._update_ui_density()
    expected = round(min(1.5, max(1.0, min(
        window.width() / 1920, window.height() / 1000
    ))) * 8) / 8
    assert widget._ui_scale == expected


def test_four_extremes_commit_and_cancel(window, tmp_path):
    """Load an image and commit one rectangle through the normal pipeline."""
    widget = window.labeling_widget.view
    image = QtGui.QImage(100, 100, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtCore.Qt.GlobalColor.white)
    path = tmp_path / "image.png"
    assert image.save(str(path))
    assert widget.load_file(str(path))
    creation = widget.rectangle_creation
    assert creation.commands["rectangle_extreme"].isEnabled()
    creation.start_extreme()
    widget.digit_to_label = "person"
    canvas = widget.canvas
    for x, y in [(50, 10), (80, 40), (40, 70), (20, 40)]:
        position = (QtCore.QPointF(x, y) + canvas.offset_to_center()) * canvas.scale
        QtTest.QTest.mouseClick(canvas, QtCore.Qt.MouseButton.LeftButton,
                                pos=position.toPoint())
    assert len(widget.canvas.shapes) == 1
    shape = widget.canvas.shapes[0]
    assert shape.label == "person"
    for point, (x, y) in zip(
        shape.points, [(20, 10), (80, 10), (80, 70), (20, 70)]
    ):
        assert point.x() == pytest.approx(x, abs=0.5)
        assert point.y() == pytest.approx(y, abs=0.5)
    creation.start_extreme()
    creation.cancel()
    assert len(widget.canvas.shapes) == 1
    widget.undo_shape_edit()
    assert len(widget.canvas.shapes) == 0
