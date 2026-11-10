"""Wiring tests for the labeling-menu entry point.

``metrics_available()`` only becomes true once controller/panel/report_dialog
all exist, so these tests exercise the whole adapter layer offscreen: the menu
call must create the controller, open the round, build the panel and the report
dialog, and stay inert when disabled.
"""

from __future__ import annotations

import types

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from anylabeling.views.labeling.correction_metrics import (  # noqa: E402
    controller as controller_module,
)
from anylabeling.views.labeling.correction_metrics.controller import (  # noqa: E402
    CorrectionMetricsController,
)
from anylabeling.views.labeling.correction_metrics.hooks import (  # noqa: E402
    metrics_available,
)
from anylabeling.views.labeling.correction_metrics.panel import (  # noqa: E402
    CorrectionMetricsPanel,
)
from anylabeling.views.labeling.correction_metrics.report_dialog import (  # noqa: E402
    ReportDialog,
)

from .test_controller import rect  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def make_host(tmp_path, language="zh_CN"):
    from PyQt6.QtWidgets import QWidget

    image = tmp_path / "images" / "scene.jpg"
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"wiring-image")
    labels = tmp_path / "labels"
    labels.mkdir(exist_ok=True)
    host = QWidget()
    host.filename = str(image)
    host.output_dir = str(labels)
    host.canvas = types.SimpleNamespace(shapes=[rect("r1"), rect("r2")])
    host._config = {"language": language}
    host.correction_metrics = None
    return host


def test_workspace_is_available_now_that_all_three_modules_exist():
    """三个模块齐备后入口不再显示“开发中”。"""
    assert metrics_available() is True


def test_start_metrics_creates_the_session_and_the_panel(qt_app, tmp_path):
    """菜单入口应当建立会话、冻结起点并创建面板。"""
    host = make_host(tmp_path)

    controller = controller_module.start_metrics(host)

    try:
        assert isinstance(controller, CorrectionMetricsController)
        assert host.correction_metrics is controller
        assert controller.enabled is True
        assert isinstance(controller.panel, CorrectionMetricsPanel)
        row = controller.current_row()
        assert row is not None and row["baseline_count"] == 2
    finally:
        controller.stop()
        host.deleteLater()


def test_start_metrics_is_idempotent(qt_app, tmp_path):
    """重复点击菜单复用同一个 controller，不重复开会话。"""
    host = make_host(tmp_path)
    first = controller_module.start_metrics(host)
    try:
        second = controller_module.start_metrics(host)
        assert second is first
        assert host.correction_metrics is first
    finally:
        first.stop()
        host.deleteLater()


def test_panel_and_summary_survive_a_degraded_controller(qt_app, tmp_path):
    """界面刷新与汇总打开在降级后仍不抛异常。"""
    host = make_host(tmp_path)
    controller = controller_module.start_metrics(host)
    try:
        controller.degrade("edit", RuntimeError("boom"))
        assert controller.refresh_panel() is True
        assert controller.show_summary() is True
        assert isinstance(controller.report_dialog, ReportDialog)
    finally:
        controller.stop()
        host.deleteLater()


def test_disabled_controller_reports_no_row_and_no_panel(qt_app, tmp_path):
    """未启用时查询返回空；面板仍可打开但只会显示"开发中/未启用"状态。"""
    host = make_host(tmp_path)
    controller = CorrectionMetricsController(host, language="zh_CN")
    try:
        assert controller.enabled is False
        assert controller.current_row() is None
        assert controller.refresh_panel() is False
        assert controller.show_panel() is True
        assert controller.panel is not None
        assert controller.rows() == [] and controller.count() == 0
    finally:
        controller.stop()
        host.deleteLater()
