"""Verify leaving rectangle creation through the actual edit shortcut."""

import copy
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtTest, QtWidgets

from anylabeling import config as app_config, user_config
from anylabeling.config import normalize_user_config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.mainwindow import MainWindow


def test_ctrl_j_returns_from_rectangle_creation(tmp_path, monkeypatch):
    """The edit action and shortcut return an idle canvas to edit mode."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
    config_file = tmp_path / "config.yaml"
    monkeypatch.setattr(app_config, "current_config_file", str(config_file))
    config = load_template_config()
    user_config.begin_session(
        target_path=str(config_file),
        origin="file",
        template=copy.deepcopy(config),
        effective=copy.deepcopy(config),
        ensure_created=True,
        normalizer=normalize_user_config,
    )
    settings_class = QtCore.QSettings
    monkeypatch.setattr(
        QtCore,
        "QSettings",
        lambda *args: settings_class(
            str(tmp_path / "settings.ini"), settings_class.Format.IniFormat
        ),
    )
    window = MainWindow(app, config=config)
    window.show()
    app.processEvents()
    widget = window.labeling_widget.view
    try:
        widget.toggle_draw_mode(False, create_mode="rectangle")
        assert widget.canvas.drawing()
        assert widget.actions.edit_mode.isEnabled()
        assert widget.actions.edit_mode.shortcut().toString() == "Ctrl+J"
        widget.canvas.setFocus()
        QtTest.QTest.keyClick(
            widget.canvas,
            QtCore.Qt.Key.Key_J,
            QtCore.Qt.KeyboardModifier.ControlModifier,
        )
        app.processEvents()
        assert widget.canvas.editing()
    finally:
        widget.dirty = False
        window.close()
        app.removeEventFilter(widget)
        window.deleteLater()
        app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
