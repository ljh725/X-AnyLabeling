"""Exercise statistics through the actual labeling workflow menu."""

import copy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling import config as app_config, user_config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.views.labeling.correction_metrics.controller import (
    CorrectionMetricsController,
)
from anylabeling.views.labeling.label_widget import LabelingWidget
from anylabeling.views.labeling.settings.runtime_applier import (
    SettingsRuntimeApplier,
)
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.mainwindow import MainWindow


def test_direct_entry_reports_pending_instead_of_missing_import(monkeypatch):
    monkeypatch.setattr(
        "anylabeling.views.labeling.label_widget.metrics_available",
        lambda: False,
    )
    host = SimpleNamespace(_config={"language": "zh_CN"}, error_message=Mock())
    LabelingWidget.open_correction_metrics(host)
    assert "开发中" in host.error_message.call_args.args[1]


@pytest.fixture
def view(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance()
    monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
    config_file = tmp_path / "config.yaml"
    monkeypatch.setattr(app_config, "current_config_file", str(config_file))
    monkeypatch.setenv("XANYLABELING_METRICS_DIR", str(tmp_path / "metrics"))
    config = copy.deepcopy(load_template_config())
    config["language"] = "zh_CN"
    user_config.begin_session(
        target_path=str(config_file),
        origin="file",
        template=copy.deepcopy(config),
        effective=config,
        ensure_created=True,
        normalizer=app_config.normalize_user_config,
    )
    window = MainWindow(app, config=config)
    window.resize(1280, 800)
    window.show()
    view = window.labeling_widget.view
    try:
        yield view
    finally:
        if view._settings_dialog is not None:
            view._settings_dialog.close()
        view.dirty = False
        window.close()
        app.removeEventFilter(view)
        window.deleteLater()
        app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def test_workflow_action_opens_the_opt_in_setting(view, tmp_path):
    action = view.actions.open_correction_metrics
    assert action in view.menus.workflow.actions()
    assert action.isEnabled()
    action.trigger()

    dialog = view._settings_dialog
    assert dialog.isVisible()
    setting = dialog._field_rows["correction_metrics_enabled"]
    checkbox = setting.findChild(QtWidgets.QCheckBox)
    assert not checkbox.isChecked()
    checkbox.click()
    dialog.shortcuts_save_button.click()

    assert view._config["correction_metrics_enabled"] is True
    assert view.correction_metrics is None
    assert not (tmp_path / "metrics").exists()


@pytest.fixture
def loaded_view(view, tmp_path):
    image_path = tmp_path / "scene.png"
    image = QtGui.QImage(64, 64, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtCore.Qt.GlobalColor.white)
    assert image.save(str(image_path))
    view.load_file(str(image_path))
    assert view.filename == str(image_path)
    return view


def test_enabled_workflow_action_shows_panel_in_the_sidebar(loaded_view):
    view = loaded_view
    view._config["correction_metrics_enabled"] = True
    view.toggle_right_sidebar()
    assert view.right_sidebar.isHidden()

    action = view.actions.open_correction_metrics
    action.trigger()
    QtWidgets.QApplication.processEvents()

    controller = view.correction_metrics
    assert controller.enabled
    panel = controller.panel
    assert view.right_sidebar.layout().indexOf(panel) >= 0
    assert panel.isVisible()
    scroll = panel.findChild(QtWidgets.QScrollArea)
    assert scroll.verticalScrollBar().maximum() > 0
    panel.set_collapsed(True)
    action.trigger()
    assert view.correction_metrics is controller
    assert panel.body.isVisible()

    SettingsRuntimeApplier(view).apply_correction_metrics(False)
    assert view.correction_metrics is None
    assert panel.isHidden()


def test_failed_panel_open_is_visible_and_starts_no_session(
    loaded_view, tmp_path, monkeypatch
):
    view = loaded_view
    view._config["correction_metrics_enabled"] = True
    monkeypatch.setattr(
        CorrectionMetricsController, "_build_panel", lambda _: None
    )
    error = Mock()
    monkeypatch.setattr(view, "error_message", error)

    view.actions.open_correction_metrics.trigger()

    assert "无法打开统计面板" in error.call_args.args[1]
    assert view.correction_metrics is None
    assert not (tmp_path / "metrics").exists()
