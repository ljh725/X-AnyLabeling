"""The unfinished statistics entry must be safe in a saved project baseline."""

import copy
from types import SimpleNamespace
from unittest.mock import Mock

from PyQt6 import QtCore, QtWidgets

from anylabeling import config as app_config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.views.labeling.label_widget import LabelingWidget
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.mainwindow import MainWindow


def test_direct_entry_reports_pending_instead_of_missing_import(monkeypatch):
    monkeypatch.setattr(
        "anylabeling.views.labeling.label_widget.metrics_available",
        lambda: False,
    )
    host = SimpleNamespace(_config={"language": "zh_CN"}, status=Mock())
    LabelingWidget.open_correction_metrics(host)
    assert "开发中" in host.status.call_args.args[0]


def test_actual_workflow_menu_disables_unfinished_statistics(
    tmp_path, monkeypatch
):
    app = QtWidgets.QApplication.instance()
    monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
    config_file = tmp_path / "config.yaml"
    config_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(app_config, "current_config_file", str(config_file))
    settings = QtCore.QSettings
    monkeypatch.setattr(
        QtCore,
        "QSettings",
        lambda *args: settings(
            str(tmp_path / "settings.ini"), settings.Format.IniFormat
        ),
    )
    monkeypatch.setattr(
        "anylabeling.views.labeling.label_widget.metrics_available",
        lambda: False,
    )
    config = copy.deepcopy(load_template_config())
    config["language"] = "zh_CN"
    window = MainWindow(app, config=config)
    view = window.labeling_widget.view
    try:
        action = view.actions.open_correction_metrics
        assert action in view.menus.workflow.actions()
        assert not action.isEnabled()
        assert "开发中" in action.toolTip()
        assert view.actions.open_inspector.isEnabled()
        assert view.actions.open_dense_review.isEnabled()
    finally:
        view.dirty = False
        window.close()
        app.removeEventFilter(view)
        window.deleteLater()
        app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
