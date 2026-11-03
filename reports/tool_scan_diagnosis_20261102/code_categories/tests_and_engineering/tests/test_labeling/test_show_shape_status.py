"""Pointer status feedback for CUSTOM-003.

``show_shape`` runs for every mouse move while a rectangle is dragged.  It used
to rebuild the whole file list twice per move and then throw the result away,
so the cost grew with the dataset.  These tests replace ``image_list`` with a
property that fails on access: the expected text must still be produced for
every list state, which proves the high-frequency slot no longer depends on it.
"""

import copy
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtWidgets

from anylabeling import config as app_config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.mainwindow import MainWindow
from PIL import Image


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
    config_file = tmp_path / "config.yaml"
    config_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(app_config, "current_config_file", str(config_file))
    settings_class = QtCore.QSettings
    monkeypatch.setattr(
        QtCore,
        "QSettings",
        lambda *args: settings_class(
            str(tmp_path / "settings.ini"), settings_class.Format.IniFormat
        ),
    )
    window = MainWindow(app, config=copy.deepcopy(load_template_config()))
    window.resize(1200, 800)
    window.show()
    app.processEvents()
    yield window
    window.labeling_widget.view.dirty = False
    window.close()
    app.removeEventFilter(window.labeling_widget.view)
    window.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


@pytest.fixture
def widget(window, tmp_path, monkeypatch):
    """A loaded image whose ``image_list`` raises when it is read."""
    view = window.labeling_widget.view
    image_path = str(tmp_path / "image.png")
    Image.new("RGB", (64, 64)).save(image_path)
    assert view.load_file(image_path)
    assert view.image_path

    def forbidden_image_list(self):
        raise AssertionError(
            "show_shape must not read the full image list on the pointer path"
        )

    monkeypatch.setattr(
        type(view), "image_list", property(forbidden_image_list)
    )
    return view


def status_text(view) -> str:
    return view.statusBar().currentMessage()


@pytest.mark.parametrize("list_state", ["empty", "current-missing", "current-present"])
def test_text_does_not_depend_on_list_membership(widget, list_state) -> None:
    """All former branches produced the same text, for every list state."""
    items = {
        "empty": [],
        "current-missing": [f"/data/other_{i:03d}.jpg" for i in range(3)],
        "current-present": [widget.filename]
        + [f"/data/other_{i:03d}.jpg" for i in range(500)],
    }[list_state]
    with QtCore.QSignalBlocker(widget.file_list_widget):
        widget.file_list_widget.clear()
        widget.file_list_widget.addItems(items)

    widget.show_shape(30, 40, QtCore.QPointF(10, 20))
    assert status_text(widget) == "X: 10, Y: 20 | H: 30, W: 40"

    widget.show_shape(-1, -1, QtCore.QPointF(11, 21))
    assert status_text(widget) == "X: 11, Y: 21"


def test_large_dataset_slot_never_builds_the_list(widget) -> None:
    """11792 entries are visible but never read by the pointer slot."""
    with QtCore.QSignalBlocker(widget.file_list_widget):
        widget.file_list_widget.clear()
        widget.file_list_widget.addItems(
            [widget.filename]
            + [f"/data/prw_{i:05d}.jpg" for i in range(11791)]
        )
    assert widget.file_list_widget.count() == 11792

    for step in range(20):
        widget.show_shape(50 + step, 60 + step, QtCore.QPointF(200 + step, 300))
    assert status_text(widget) == "X: 219, Y: 300 | H: 69, W: 79"


def test_fractional_values_keep_integer_formatting(widget) -> None:
    """Widths that arrive as floats are still shown truncated, as before."""
    widget.show_shape(30.9, 40.9, QtCore.QPointF(10.9, 20.9))
    assert status_text(widget) == "X: 10, Y: 20 | H: 30, W: 40"


def test_no_image_keeps_the_previous_status(widget) -> None:
    """Without an image the slot stays silent, matching the old behaviour."""
    widget.status("keep me", 10000)
    widget.image_path = None
    widget.show_shape(-1, -1, QtCore.QPointF(5, 6))
    assert status_text(widget) == "keep me"


def test_status_follows_repeated_reporting(widget) -> None:
    """Repeated updates keep overwriting the same single message."""
    positions = [(1, 2), (3, 4), (5, 6)]
    for index, (x, y) in enumerate(positions):
        widget.show_shape(10 + index, 20 + index, QtCore.QPointF(x, y))
        assert status_text(widget) == (
            f"X: {x}, Y: {y} | H: {10 + index}, W: {20 + index}"
        )
