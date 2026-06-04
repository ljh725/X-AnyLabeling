"""
Inspector Panel — the main dock widget that houses the data inspection UI.

This is the top-level container.  It:
- Holds the FlatIndex, IssueListWidget, EditableTableWidget,
  RuleConfigWidget (with shared label set), and export controls.
- Orchestrates scan → validate → display, rule config, and file export.
- Emits navigation and edit signals that the parent label_widget connects to.

检查器面板 — 用于容纳数据检查用户界面的主停靠窗口部件。

这是顶层容器。它：
- 包含 FlatIndex、IssueListWidget、EditableTableWidget、RuleConfigWidget（带共享标签集）以及导出控件。
- 协调扫描 → 验证 → 显示、规则配置和文件导出。
- 发出导航和编辑信号，由父级 label_widget 连接。

Usage (in label_widget.py)::

    from .widgets.inspector import InspectorPanel

    self.inspector_panel = InspectorPanel()
    self.inspector_panel.issue_navigate_requested.connect(...)
"""

import logging
import os
import os.path as osp
from typing import Any, Dict, List, Optional, Set

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from .flat_index import FlatIndex, FlattenedRecord
from .validation_engine import (
    ValidationEngine,
    ValidationReport,
    ValidationRule,
)
from .issue_list_widget import IssueListWidget
from .editable_table_widget import EditableTableWidget
from .rule_config_widget import RuleConfigWidget
from .export_manager import ExportManager, ExportResult

logger = logging.getLogger(__name__)


class InspectorScanThread(QtCore.QThread):
    """Background worker for inspector scan and validation."""

    progress = QtCore.pyqtSignal(int, int, str)
    status_changed = QtCore.pyqtSignal(str)
    finished_with_result = QtCore.pyqtSignal(object, object)
    error = QtCore.pyqtSignal(str)

    def __init__(
        self,
        json_paths: List[str],
        rules: List[ValidationRule],
        parent: Optional[QtCore.QObject] = None,
    ):
        """Initialize the worker.

        Args:
            json_paths: JSON annotation files to scan.
            rules: Validation rules captured from the current UI state.
            parent: Optional QObject parent.
        """
        super().__init__(parent)
        self._json_paths = list(json_paths)
        self._rules = list(rules)
        self._cancelled = False

    def cancel(self) -> None:
        """Request cancellation before the next scan stage continues."""
        self._cancelled = True

    def run(self) -> None:
        """Build the flat index and run validation rules in the background."""
        try:
            index = FlatIndex()
            file_total = len(self._json_paths)
            rule_total = len(self._rules)
            total_units = max(file_total + rule_total, 1)
            progress_step = max(file_total // 100, 1)

            self.status_changed.emit("正在扫描标注文件...")

            def on_file_progress(
                current: int, _total: int, filename: str
            ) -> None:
                if current == file_total or current % progress_step == 0:
                    self.progress.emit(current, total_units, filename)

            index.scan_files(
                self._json_paths,
                progress_callback=on_file_progress,
                cancel_check=lambda: self._cancelled,
            )
            if self._cancelled:
                return

            self.status_changed.emit("正在检查规则...")
            engine = ValidationEngine(self._rules)

            def on_rule_progress(
                current: int, _total: int, rule_name: str
            ) -> None:
                self.progress.emit(
                    file_total + current,
                    total_units,
                    rule_name,
                )

            report = engine.run(
                index,
                progress_callback=on_rule_progress,
            )
            if not self._cancelled:
                self.finished_with_result.emit(index, report)
        except Exception as exc:
            logger.exception("Inspector scan worker failed")
            self.error.emit(str(exc))


class InspectorPanel(QtWidgets.QDockWidget):
    """Dock panel for annotation data quality inspection.

    Signals:
        issue_navigate_requested(file_path: str, shape_index: int)
        shape_edit_requested(file_path: str, shape_index: int, field: str, value)
        scan_started()
        scan_finished(report: ValidationReport)
    """

    issue_navigate_requested = QtCore.pyqtSignal(str, int)
    shape_edit_requested = QtCore.pyqtSignal(str, int, str, object)
    scan_started = QtCore.pyqtSignal()
    scan_finished = QtCore.pyqtSignal(object)

    COCO_KEYPOINTS: Set[str] = {
        "nose",
        "l_eye",
        "r_eye",
        "l_ear",
        "r_ear",
        "l_sho",
        "r_sho",
        "l_elb",
        "r_elb",
        "l_wri",
        "r_wri",
        "l_hip",
        "r_hip",
        "l_knee",
        "r_knee",
        "l_ank",
        "r_ank",
    }

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
    ):
        super().__init__(parent)
        self.setObjectName("Inspector")
        self.setWindowTitle(self.tr("数据检查 (Inspector)"))
        self.setMinimumWidth(320)

        # ── core components ──────────────────────────────────────
        self._flat_index = FlatIndex()
        self._export_manager = ExportManager()
        self._rule_config = RuleConfigWidget()
        self._engine = ValidationEngine(self._rule_config.build_rules())

        # ── UI: tab widget ───────────────────────────────────────
        self._tab_widget = QtWidgets.QTabWidget()

        self._issue_list = IssueListWidget()
        self._tab_widget.addTab(self._issue_list, self.tr("数据检查"))

        self._table_widget = EditableTableWidget()
        self._tab_widget.addTab(self._table_widget, self.tr("数据表格"))

        self._tab_widget.addTab(self._rule_config, self.tr("规则配置"))

        self._export_widget = self._build_export_widget()
        self._tab_widget.addTab(self._export_widget, self.tr("导出"))

        self._progress_widget = self._build_progress_widget()
        self.setWidget(self._build_main_widget())

        # ── wire signals ─────────────────────────────────────────
        self._issue_list.issue_double_clicked.connect(
            self.issue_navigate_requested.emit
        )
        self._issue_list.issue_clicked.connect(
            self.issue_navigate_requested.emit
        )
        self._issue_list.rescan_requested.connect(self.run_scan)

        self._table_widget.shape_clicked.connect(
            self.issue_navigate_requested.emit
        )
        self._table_widget.shape_double_clicked.connect(
            self.issue_navigate_requested.emit
        )
        self._table_widget.set_edit_callback(self._on_table_edit)

        self._rule_config.config_changed.connect(self._on_rule_config_changed)

        # ── state ────────────────────────────────────────────────
        self._last_report: Optional[ValidationReport] = None
        self._file_list: List[str] = []
        self._scan_thread: Optional[InspectorScanThread] = None

        # Populate rule config UI from initial engine
        self._rule_config.populate(self._engine.rules)

        logger.debug("InspectorPanel initialized")

    # ── Rule config handler ──────────────────────────────────────

    def _on_rule_config_changed(self) -> None:
        """Rebuild the engine when user changes rule configuration."""
        if self._scan_thread is not None:
            return
        self._engine = ValidationEngine(self._rule_config.build_rules())
        self._last_report = None
        self._issue_list.clear_results()
        self._export_btn.setEnabled(False)

    # ── Table edit callback ──────────────────────────────────────

    def _on_table_edit(
        self, file_path: str, shape_index: int, field: str, value
    ) -> None:
        self.shape_edit_requested.emit(file_path, shape_index, field, value)

    # ── Export UI builder ────────────────────────────────────────

    def _build_main_widget(self) -> QtWidgets.QWidget:
        """Build the dock body around scan progress and tabs."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._progress_widget)
        layout.addWidget(self._tab_widget)
        return widget

    def _build_progress_widget(self) -> QtWidgets.QWidget:
        """Build the hidden scan progress row."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 2)
        layout.setSpacing(3)

        self._scan_status_label = QtWidgets.QLabel(
            self.tr("正在扫描标注文件...")
        )
        self._scan_status_label.setStyleSheet("color: #666; font-size: 9pt;")
        layout.addWidget(self._scan_status_label)

        self._scan_progress_bar = QtWidgets.QProgressBar()
        self._scan_progress_bar.setTextVisible(True)
        self._scan_progress_bar.setRange(0, 1)
        self._scan_progress_bar.setValue(0)
        layout.addWidget(self._scan_progress_bar)

        widget.hide()
        return widget

    def _build_export_widget(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        header = QtWidgets.QLabel(self.tr("导出 / 拆分文件"))
        header.setStyleSheet("font-weight: bold; font-size: 11pt;")
        layout.addWidget(header)

        desc = QtWidgets.QLabel(
            self.tr("将扫描结果按规则拆分到子目录中。操作类型为复制。")
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #888; font-size: 9pt;")
        layout.addWidget(desc)

        layout.addSpacing(4)

        dir_layout = QtWidgets.QHBoxLayout()
        dir_layout.addWidget(QtWidgets.QLabel(self.tr("输出目录:")))
        self._export_dir_edit = QtWidgets.QLineEdit()
        self._export_dir_edit.setPlaceholderText(self.tr("选择导出目录..."))
        self._export_dir_edit.setReadOnly(True)
        dir_layout.addWidget(self._export_dir_edit)

        browse_btn = QtWidgets.QPushButton("...")
        browse_btn.setFixedWidth(28)
        browse_btn.clicked.connect(self._on_export_browse)
        dir_layout.addWidget(browse_btn)
        layout.addLayout(dir_layout)

        self._export_btn = QtWidgets.QPushButton(self.tr("开始导出"))
        self._export_btn.setFixedHeight(28)
        self._export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._export_btn.clicked.connect(self._on_export)
        self._export_btn.setEnabled(False)
        layout.addWidget(self._export_btn)

        self._export_status = QtWidgets.QLabel("")
        self._export_status.setWordWrap(True)
        self._export_status.setStyleSheet("color: #666; font-size: 9pt;")
        layout.addWidget(self._export_status)

        layout.addStretch()
        return widget

    def _on_export_browse(self) -> None:
        start_dir = self._export_dir_edit.text() or os.path.expanduser("~")
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            self.tr("选择导出目录"),
            start_dir,
        )
        if directory:
            self._export_dir_edit.setText(osp.normpath(directory))
            self._update_export_button()

    def _on_export(self) -> None:
        if self._last_report is None or not self._last_report.issues:
            self._export_status.setText(self.tr("没有可导出的问题。"))
            self._export_status.setStyleSheet(
                "color: #b71c1c; font-size: 9pt;"
            )
            return

        output_dir = self._export_dir_edit.text().strip()
        if not output_dir:
            self._export_status.setText(self.tr("请先选择输出目录。"))
            self._export_status.setStyleSheet(
                "color: #b71c1c; font-size: 9pt;"
            )
            return

        self._export_btn.setEnabled(False)
        self._export_status.setText(self.tr("正在导出..."))
        self._export_status.setStyleSheet("color: #888; font-size: 9pt;")

        result = self._export_manager.export(
            report=self._last_report,
            output_dir=output_dir,
        )

        if result.errors:
            self._export_status.setText(
                self.tr("导出完成。复制 %d JSON + %d 图片，%d 错误。")
                % (
                    result.copied_files,
                    result.copied_images,
                    len(result.errors),
                )
            )
            self._export_status.setStyleSheet(
                "color: #e65100; font-size: 9pt;"
            )
        else:
            self._export_status.setText(
                self.tr("✓ 导出完成。复制 %d JSON + %d 图片到 %d 子目录。")
                % (
                    result.copied_files,
                    result.copied_images,
                    len(result.rules_exported),
                )
            )
            self._export_status.setStyleSheet(
                "color: #2e7d32; font-size: 9pt;"
            )

        self._export_btn.setEnabled(True)

    def _update_export_button(self) -> None:
        has_dir = bool(self._export_dir_edit.text().strip())
        has_report = (
            self._last_report is not None and self._last_report.issue_count > 0
        )
        self._export_btn.setEnabled(has_dir and has_report)

    # ── Scan progress helpers ────────────────────────────────────

    def _set_scan_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable controls while a background scan is running."""
        self._issue_list.scan_btn.setEnabled(enabled)
        self._rule_config.setEnabled(enabled)
        export_enabled = enabled and self._export_btn.isEnabled()
        self._export_btn.setEnabled(export_enabled)

    def _show_scan_progress(self, total: int) -> None:
        """Reset and show scan progress UI."""
        self._progress_widget.show()
        self._scan_status_label.setStyleSheet("color: #666; font-size: 9pt;")
        self._scan_status_label.setText(self.tr("正在扫描标注文件..."))
        self._scan_progress_bar.setRange(0, max(total, 1))
        self._scan_progress_bar.setValue(0)
        self._scan_progress_bar.setFormat(
            self.tr("0/%d (0%%)") % max(total, 1)
        )

    def _hide_scan_progress(self) -> None:
        """Hide scan progress UI after the current task has ended."""
        self._progress_widget.hide()

    def _on_scan_progress(
        self, current: int, total: int, current_name: str
    ) -> None:
        """Update the scan progress bar and status label."""
        safe_total = max(total, 1)
        safe_current = min(max(current, 0), safe_total)
        percent = int(safe_current * 100 / safe_total)
        self._scan_progress_bar.setRange(0, safe_total)
        self._scan_progress_bar.setValue(safe_current)
        self._scan_progress_bar.setFormat(
            self.tr("%d/%d (%d%%)") % (safe_current, safe_total, percent)
        )
        if current_name:
            self._scan_status_label.setText(
                self.tr("正在处理: %s") % current_name
            )

    def _on_scan_status_changed(self, message: str) -> None:
        """Show the current background scan stage."""
        self._scan_status_label.setText(message)

    def _on_scan_error(self, message: str) -> None:
        """Show scan errors and restore the panel controls."""
        self._last_report = None
        self._issue_list.clear_results()
        self._table_widget.clear_results()
        self._scan_status_label.setText(self.tr("扫描失败: %s") % message)
        self._scan_status_label.setStyleSheet(
            "color: #b71c1c; font-size: 9pt;"
        )
        self._issue_list.summary_label.setText(
            self.tr("扫描失败: %s") % message
        )
        self._issue_list.summary_label.setStyleSheet(
            "color: #b71c1c; font-size: 9pt;"
        )

    def _on_scan_finished_with_result(
        self, index: FlatIndex, report: ValidationReport
    ) -> None:
        """Apply completed background scan results to the UI."""
        self._flat_index = index
        self._last_report = report
        self._issue_list.populate(report)
        self.scan_finished.emit(report)
        self._update_export_button()

        logger.info(
            "Inspector scan finished: %d issues (%d errors, %d warnings)",
            report.issue_count,
            report.error_count,
            report.warning_count,
        )

    def _on_scan_thread_finished(self) -> None:
        """Clear the worker thread reference and restore controls."""
        self._scan_thread = None
        self._hide_scan_progress()
        self._scan_status_label.setStyleSheet("color: #666; font-size: 9pt;")
        self._set_scan_controls_enabled(True)
        self._update_export_button()

    # ── Public API ───────────────────────────────────────────────

    def set_file_list(self, file_paths: List[str]) -> None:
        """Set the list of JSON files to scan."""
        self._file_list = list(file_paths)
        self._issue_list.clear_results()
        self._table_widget.clear_results()

    def set_allowed_labels(self, labels: Set[str]) -> None:
        """Update the shared label set in the rule config widget."""
        self._rule_config.set_shared_labels(labels)
        self._engine = ValidationEngine(self._rule_config.build_rules())
        self._last_report = None
        self._issue_list.clear_results()
        self._table_widget.clear_results()
        self._rule_config.populate(self._engine.rules, shared_labels=labels)

    def run_scan(self, json_paths: Optional[List[str]] = None) -> None:
        """
        Run a full scan → validate → display pipeline.

        If json_paths is None, uses the file list set via set_file_list().
        """
        if self._scan_thread is not None:
            logger.info("Inspector scan already running")
            return

        paths = json_paths or self._file_list
        if not paths:
            logger.warning("No files to scan")
            return

        self.scan_started.emit()

        # Always rebuild engine from current rule config state
        self._engine = ValidationEngine(self._rule_config.build_rules())

        self._last_report = None
        self._issue_list.clear_results()
        self._table_widget.clear_results()
        self._export_btn.setEnabled(False)
        self._set_scan_controls_enabled(False)
        self._show_scan_progress(len(paths) + len(self._engine.rules))

        self._scan_thread = InspectorScanThread(
            paths,
            self._engine.rules,
            self,
        )
        self._scan_thread.progress.connect(self._on_scan_progress)
        self._scan_thread.status_changed.connect(self._on_scan_status_changed)
        self._scan_thread.finished_with_result.connect(
            self._on_scan_finished_with_result
        )
        self._scan_thread.error.connect(self._on_scan_error)
        self._scan_thread.finished.connect(self._on_scan_thread_finished)
        self._scan_thread.start()

    def refresh_file(self, file_path: str) -> None:
        """Re-scan a single file after modification."""
        if self._scan_thread is not None:
            return
        if file_path not in self._flat_index._by_file:
            return
        self._flat_index.refresh_file(file_path)
        if self._last_report:
            report = self._engine.run(self._flat_index)
            self._last_report = report
            self._issue_list.populate(report)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Cancel an active background scan when the dock is closed."""
        if self._scan_thread is not None:
            self._scan_thread.cancel()
        super().closeEvent(event)

    # ── Editable table API ───────────────────────────────────────

    def populate_table(self, records: List[FlattenedRecord]) -> None:
        self._table_widget.populate(records)

    def refresh_table_from_shapes(
        self,
        file_path: str,
        shapes: list,
        image_path: str = "",
    ) -> None:
        records = self._shapes_to_records(file_path, shapes, image_path)
        self._table_widget.populate(records)

    @staticmethod
    def _shapes_to_records(
        file_path: str,
        shapes: list,
        image_path: str = "",
    ) -> List[FlattenedRecord]:
        records: List[FlattenedRecord] = []
        for i, shape in enumerate(shapes):
            rec = FlattenedRecord(
                file_path=file_path,
                image_path=image_path,
                shape_index=i,
                label=getattr(shape, "label", ""),
                shape_type=getattr(shape, "shape_type", ""),
                group_id=getattr(shape, "group_id", None),
                flags=dict(getattr(shape, "flags", {}) or {}),
                attributes=dict(getattr(shape, "attributes", {}) or {}),
                description=getattr(shape, "description", "") or "",
                points_count=len(getattr(shape, "points", []) or []),
                difficulty=bool(getattr(shape, "difficult", False)),
            )
            records.append(rec)
        return records

    # ── Properties ───────────────────────────────────────────────

    @property
    def flat_index(self) -> FlatIndex:
        return self._flat_index

    @property
    def engine(self) -> ValidationEngine:
        return self._engine

    @property
    def last_report(self) -> Optional[ValidationReport]:
        return self._last_report

    @property
    def issue_list_widget(self) -> IssueListWidget:
        return self._issue_list

    @property
    def table_widget(self) -> EditableTableWidget:
        return self._table_widget

    @property
    def rule_config_widget(self) -> RuleConfigWidget:
        return self._rule_config
