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
from .external_result_importer import ExternalResultImporter
from .quality_scan_worker import QualityScanThread
from .quality_review_widget import QualityReviewWidget
from .quality.quality_issue import QualityReport
from .quality.quality_review_queue import (
    QualityReviewItem,
    QualityReviewQueue,
)
from .quality.threshold_profile import (
    ThresholdProfile,
    load_threshold_profile,
)
from .quality.threshold_suggestion import (
    SuggestionContext,
    generate_threshold_suggestion,
)
from .virtual_review_widget import VirtualReviewWidget
from .dataset_review_widget import DatasetReviewWidget

logger = logging.getLogger(__name__)


def _format_export_diagnostics(result: ExportResult, limit: int = 20) -> str:
    """Return compact export diagnostics for the status tooltip."""
    lines: List[str] = []
    entries = [("ERROR", result.errors), ("WARN", result.warnings)]
    for level, diagnostics in entries:
        for path, message in diagnostics[:limit]:
            lines.append(f"{level}: {path}: {message}")
        if len(diagnostics) > limit:
            lines.append(
                f"{level}: ... {len(diagnostics) - limit} more omitted"
            )
    return "\n".join(lines)


class InspectorScanThread(QtCore.QThread):
    """Background worker for inspector scan and validation."""

    progress = QtCore.pyqtSignal(int, int, str, str)
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
            progress_step = max(file_total // 100, 1)

            self.status_changed.emit("正在扫描标注文件...")

            def on_file_progress(
                current: int, _total: int, filename: str
            ) -> None:
                if current == file_total or current % progress_step == 0:
                    self.progress.emit(
                        current,
                        max(file_total, 1),
                        filename,
                        "scan",
                    )

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
                    current,
                    max(rule_total, 1),
                    rule_name,
                    "validate",
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


class InspectorExportThread(QtCore.QThread):
    """Background worker for Inspector file export."""

    progress = QtCore.pyqtSignal(int, int, str)
    finished_with_result = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(str)

    def __init__(
        self,
        report: ValidationReport,
        output_dir: str,
        parent: Optional[QtCore.QObject] = None,
    ):
        """Initialize the export worker."""
        super().__init__(parent)
        self._report = report
        self._output_dir = output_dir
        self._cancelled = False

    def cancel(self) -> None:
        """Request cancellation before the next file copy starts."""
        self._cancelled = True

    def run(self) -> None:  # noqa: D401 — QThread override
        """Run export off the UI thread and emit a result."""
        try:
            manager = ExportManager()

            def on_progress(current: int, total: int, name: str) -> None:
                self.progress.emit(current, total, name)

            result = manager.export(
                report=self._report,
                output_dir=self._output_dir,
                progress_callback=on_progress,
                cancel_callback=lambda: self._cancelled,
            )
            self.finished_with_result.emit(result)
        except Exception as exc:  # noqa: BLE001 — isolate worker crashes
            logger.exception("Inspector export worker failed")
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
    virtual_review_start_requested = QtCore.pyqtSignal(object)
    virtual_review_stop_requested = QtCore.pyqtSignal()
    virtual_review_previous_requested = QtCore.pyqtSignal()
    virtual_review_next_requested = QtCore.pyqtSignal()
    virtual_review_overview_requested = QtCore.pyqtSignal()

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

        # L1/L2 quality review queue tab (inserted at index 1, right
        # after 数据检查, leaving the existing IssueListWidget untouched).
        self._quality_review = QualityReviewWidget()
        self._tab_widget.insertTab(
            1, self._quality_review, self.tr("质检复核")
        )

        self._virtual_review = VirtualReviewWidget()
        self._tab_widget.insertTab(
            2, self._virtual_review, self.tr("目标复核")
        )

        # Dataset queue section lives inside the same target-review
        # tab, clearly separated below the image-local review controls.
        self._dataset_review = DatasetReviewWidget()
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        separator.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        virtual_layout = self._virtual_review.layout()
        insert_at = max(0, virtual_layout.count() - 1)
        virtual_layout.insertWidget(insert_at, separator)
        virtual_layout.insertWidget(insert_at + 1, self._dataset_review)

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
        self._issue_list.scan_current_requested.connect(self.run_scan_current)
        self._issue_list.import_requested.connect(
            self._on_import_external_results
        )

        self._table_widget.shape_clicked.connect(
            self.issue_navigate_requested.emit
        )
        self._table_widget.shape_double_clicked.connect(
            self.issue_navigate_requested.emit
        )
        self._table_widget.set_edit_callback(self._on_table_edit)

        self._rule_config.config_changed.connect(self._on_rule_config_changed)

        # ── wire quality review signals ─────────────────────────
        # navigation reuses the existing issue_navigate_requested path so
        # the parent label_widget needs no changes.
        self._quality_review.issue_clicked.connect(
            self.issue_navigate_requested.emit
        )
        self._quality_review.import_requested.connect(
            self._on_import_quality_report
        )
        self._quality_review.rescan_current_requested.connect(
            self._on_rescan_current_quality
        )
        self._quality_review.generate_suggestion_requested.connect(
            self._on_generate_quality_suggestion
        )
        self._quality_review.review_changed.connect(
            self._on_quality_review_changed
        )

        self._virtual_review.start_requested.connect(
            self.virtual_review_start_requested.emit
        )
        self._virtual_review.stop_requested.connect(
            self.virtual_review_stop_requested.emit
        )
        self._virtual_review.previous_requested.connect(
            self.virtual_review_previous_requested.emit
        )
        self._virtual_review.next_requested.connect(
            self.virtual_review_next_requested.emit
        )
        self._virtual_review.overview_requested.connect(
            self.virtual_review_overview_requested.emit
        )

        # ── state ────────────────────────────────────────────────
        self._last_report: Optional[ValidationReport] = None
        self._file_list: List[str] = []
        self._scan_thread: Optional[InspectorScanThread] = None
        self._export_thread: Optional[InspectorExportThread] = None
        self._current_file_path: Optional[str] = None
        # L1/L2 quality review state
        self._quality_thread: Optional[QualityScanThread] = None
        self._quality_scan_target_path: Optional[str] = None
        self._quality_profile: Optional[ThresholdProfile] = None
        self._quality_feedback_path: Optional[str] = None
        self._quality_feedback_dirty = False
        self._quality_feedback_save_timer = QtCore.QTimer(self)
        self._quality_feedback_save_timer.setSingleShot(True)
        self._quality_feedback_save_timer.setInterval(1500)
        self._quality_feedback_save_timer.timeout.connect(
            self._flush_quality_feedback
        )

        # Populate rule config UI from initial engine
        self._rule_config.populate(self._engine.rules)

        logger.debug("InspectorPanel initialized")

    @property
    def virtual_review_widget(self) -> VirtualReviewWidget:
        """Return the virtual review criteria/navigation widget."""
        return self._virtual_review

    @property
    def dataset_review_widget(self) -> DatasetReviewWidget:
        """Return the dataset review queue controls."""
        return self._dataset_review

    def set_virtual_review_labels(self, labels: Set[str]) -> None:
        """Update virtual-review label choices from the active label set."""
        self._virtual_review.set_labels(labels)

    # ── Rule config handler ──────────────────────────────────────

    def _on_rule_config_changed(self) -> None:
        """Rebuild the engine when user changes rule configuration."""
        if self._scan_thread is not None or self._export_thread is not None:
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

        if self._export_thread is not None:
            return

        self._export_btn.setEnabled(False)
        self._export_status.setToolTip("")
        self._export_status.setText(self.tr("正在准备导出..."))
        self._export_status.setStyleSheet("color: #888; font-size: 9pt;")

        self._export_thread = InspectorExportThread(
            self._last_report,
            output_dir,
            self,
        )
        self._export_thread.progress.connect(self._on_export_progress)
        self._export_thread.finished_with_result.connect(
            self._on_export_finished
        )
        self._export_thread.error.connect(self._on_export_error)
        self._export_thread.finished.connect(self._on_export_thread_finished)
        self._export_thread.start()

    def _on_export_progress(
        self, current: int, total: int, filename: str
    ) -> None:
        """Show background export progress in the export tab."""
        safe_total = max(total, 1)
        percent = int((max(current, 0) / safe_total) * 100)
        if filename:
            self._export_status.setText(
                self.tr("正在导出: %d/%d (%d%%) %s")
                % (current, safe_total, percent, filename)
            )
        else:
            self._export_status.setText(
                self.tr("正在导出: %d/%d (%d%%)")
                % (current, safe_total, percent)
            )

    def _on_export_finished(self, result: ExportResult) -> None:
        """Show completed export counts and diagnostics."""
        self._show_export_result(result)

    def _on_export_error(self, message: str) -> None:
        """Show unrecoverable export worker failures."""
        self._export_status.setText(self.tr("导出失败: %s") % message)
        self._export_status.setStyleSheet("color: #b71c1c; font-size: 9pt;")
        self._export_status.setToolTip(message)

    def _on_export_thread_finished(self) -> None:
        """Clear the worker thread reference and restore export controls."""
        self._export_thread = None
        self._update_export_button()

    def _show_export_result(self, result: ExportResult) -> None:
        """Render export result counts, warnings, and errors."""
        warning_count = len(result.warnings)
        error_count = len(result.errors)
        if result.errors:
            self._export_status.setText(
                self.tr("导出完成。复制 %d JSON + %d 图片，%d 错误，%d 警告。")
                % (
                    result.copied_files,
                    result.copied_images,
                    error_count,
                    warning_count,
                )
            )
            self._export_status.setStyleSheet(
                "color: #e65100; font-size: 9pt;"
            )
        elif result.cancelled:
            self._export_status.setText(
                self.tr("导出已取消。已复制 %d JSON + %d 图片，%d 警告。")
                % (
                    result.copied_files,
                    result.copied_images,
                    warning_count,
                )
            )
            self._export_status.setStyleSheet(
                "color: #e65100; font-size: 9pt;"
            )
        elif result.warnings:
            self._export_status.setText(
                self.tr(
                    "导出完成。复制 %d JSON + %d 图片到 %d 子目录，%d 警告。"
                )
                % (
                    result.copied_files,
                    result.copied_images,
                    len(result.rules_exported),
                    warning_count,
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

        self._export_status.setToolTip(_format_export_diagnostics(result))

    def _update_export_button(self) -> None:
        has_dir = bool(self._export_dir_edit.text().strip())
        has_report = (
            self._last_report is not None and self._last_report.issue_count > 0
        )
        idle = self._scan_thread is None and self._export_thread is None
        self._export_btn.setEnabled(has_dir and has_report and idle)

    def _on_import_external_results(self) -> None:
        """Import external validation issues and replace current results."""
        if self._scan_thread is not None:
            return

        start_dir = (
            osp.dirname(self._file_list[0])
            if self._file_list
            else os.path.expanduser("~")
        )
        file_path, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.tr("导入外部检测结果"),
            start_dir,
            self.tr("Result Files (*.txt *.tsv *.csv *.json);;All Files (*)"),
        )
        if not file_path:
            return

        try:
            importer = ExternalResultImporter(self._file_list)
            result = importer.import_file(file_path)
        except Exception as exc:
            logger.exception("Failed to import external inspector results")
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("导入失败"),
                self.tr("无法导入外部检测结果: %s") % str(exc),
            )
            return

        self._flat_index.clear()
        self._last_report = result.report
        self._issue_list.populate(result.report)
        self.scan_finished.emit(result.report)
        self._update_export_button()

        skipped = len(result.errors)
        if result.report.issue_count:
            summary = self.tr("导入 %d 个问题") % result.report.issue_count
        else:
            summary = self.tr("导入完成，未发现问题")
        if skipped:
            self._issue_list.summary_label.setToolTip("\n".join(result.errors))
            self._issue_list.summary_label.setText(
                self.tr("%s，跳过 %d 行") % (summary, skipped)
            )
        else:
            self._issue_list.summary_label.setToolTip("")
            self._issue_list.summary_label.setText(summary)

    # ── L1/L2 quality review handlers ────────────────────────────

    def _ensure_quality_profile(self) -> ThresholdProfile:
        """Lazily load the bundled v0 threshold profile on first use."""
        if self._quality_profile is None:
            try:
                self._quality_profile = load_threshold_profile()
            except Exception:  # noqa: BLE001
                logger.exception("Failed to load quality threshold profile")
                raise
        return self._quality_profile

    def _on_import_quality_report(self) -> None:
        """Import a CLI-generated report.json / review.tsv into the queue."""
        if self._quality_thread is not None:
            return
        start_dir = (
            osp.dirname(self._file_list[0])
            if self._file_list
            else os.path.expanduser("~")
        )
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.tr("导入 L1/L2 质检结果"),
            start_dir,
            self.tr("Quality Report (*.json *.tsv);;All Files (*)"),
        )
        if not file_path:
            return

        queue: QualityReviewQueue = self._quality_review.queue
        queue.clear()
        self._quality_feedback_path = None
        self._quality_feedback_dirty = False
        self._quality_feedback_save_timer.stop()
        try:
            if file_path.lower().endswith(".json"):
                queue.load_report(file_path)
            else:
                queue.load_review_tsv(file_path)
            # overlay existing feedback if a sidecar review_feedback.tsv
            # sits next to the imported file
            sidecar = osp.join(osp.dirname(file_path), "review_feedback.tsv")
            if osp.isfile(sidecar):
                queue.merge_feedback(sidecar)
                self._quality_feedback_path = sidecar
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to import quality report")
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("导入失败"),
                self.tr("无法导入质检结果: %s") % str(exc),
            )
            return

        self._quality_review.populate()
        self._tab_widget.setCurrentWidget(self._quality_review)

    def _on_quality_review_changed(self) -> None:
        """Schedule review_feedback.tsv writing without blocking each click."""
        self._quality_feedback_dirty = True
        self._quality_feedback_save_timer.start()

    def _flush_quality_feedback(self) -> None:
        """Flush the current review state to review_feedback.tsv."""
        if not self._quality_feedback_dirty:
            return
        path = self._choose_quality_feedback_path()
        if path is None:
            return
        try:
            self._quality_review.queue.write_feedback(path)
            self._quality_feedback_dirty = False
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to write review_feedback.tsv")
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("写反馈失败"),
                self.tr("无法写入 review_feedback.tsv: %s") % str(exc),
            )

    def _choose_quality_feedback_path(self) -> Optional[str]:
        """Resolve where to write review_feedback.tsv.

        Defaults to a sidecar next to the imported report; otherwise asks.
        """
        if self._quality_feedback_path:
            return self._quality_feedback_path
        queue = self._quality_review.queue
        base = queue.report_path
        if base:
            self._quality_feedback_path = osp.join(
                osp.dirname(base), "review_feedback.tsv"
            )
            return self._quality_feedback_path
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            self.tr("保存复核反馈"),
            "review_feedback.tsv",
            self.tr("TSV (*.tsv)"),
        )
        if path:
            self._quality_feedback_path = path
        return self._quality_feedback_path or None

    def _on_rescan_current_quality(self) -> None:
        """Re-scan the current file's L1/L2 issues in the background."""
        if self._quality_thread is not None:
            return
        json_path = (
            self._quality_review.current_rescan_file()
            or self._resolve_current_json_path()
        )
        if not json_path or not osp.isfile(json_path):
            QtWidgets.QMessageBox.information(
                self,
                self.tr("复扫当前"),
                self.tr("没有可复扫的当前文件。"),
            )
            return
        try:
            profile = self._ensure_quality_profile()
        except Exception:
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("复扫当前"),
                self.tr("无法加载阈值配置，复扫中止。"),
            )
            return

        self._quality_thread = QualityScanThread(
            json_paths=[json_path],
            profile=profile,
            input_root=osp.dirname(json_path),
            parent=self,
        )
        self._quality_scan_target_path = json_path
        self._quality_thread.scan_finished.connect(
            self._on_quality_scan_finished
        )
        self._quality_thread.error.connect(self._on_quality_scan_error)
        self._quality_review.rescan_btn.setEnabled(False)
        self._quality_thread.start()

    def _on_quality_scan_finished(self, report: QualityReport) -> None:
        """Merge a single-file re-scan into the queue without losing
        prior feedback (disappeared issues tagged resolved_after_rescan)."""
        self._quality_thread = None
        json_path = self._quality_scan_target_path
        self._quality_scan_target_path = None
        self._quality_review.rescan_btn.setEnabled(
            self._quality_review.current_rescan_file() is not None
        )
        if json_path is None:
            return
        # convert the freshly-scanned QualityReport issues into
        # QualityReviewItems for the same file
        new_items: List[QualityReviewItem] = []
        for issue in report.issues:
            pm = issue.primary_metric
            new_items.append(
                QualityReviewItem(
                    issue_id=issue.issue_id(),
                    run_id=report.run_id,
                    file_path=issue.file_path,
                    shape_index=issue.shape_index,
                    rule_id=issue.rule_id,
                    rule_name=issue.rule_name,
                    severity=issue.severity,
                    message=issue.message,
                    label=issue.label,
                    group_id=issue.group_id,
                    primary_metric_name=(pm.name if pm is not None else ""),
                    primary_metric_value=(pm.value if pm is not None else 0.0),
                    primary_metric_direction=(
                        pm.direction if pm is not None else "higher_is_worse"
                    ),
                    original_severity=issue.severity,
                )
            )
        result = self._quality_review.queue.rescan_file(json_path, new_items)
        self._quality_review.populate()
        logger.info(
            "quality rescan merged: added=%d resolved=%d total=%d",
            result["added"],
            result["resolved"],
            result["total"],
        )

    def _on_quality_scan_error(self, message: str) -> None:
        self._quality_thread = None
        self._quality_scan_target_path = None
        self._quality_review.rescan_btn.setEnabled(
            self._quality_review.current_rescan_file() is not None
        )
        QtWidgets.QMessageBox.warning(self, self.tr("复扫失败"), message)

    def _on_generate_quality_suggestion(self) -> None:
        """Generate threshold_suggestion.json (always pending, non-binding)."""
        queue = self._quality_review.queue
        report_path = queue.report_path
        if (
            not queue.has_report
            or not report_path
            or not osp.isfile(report_path)
        ):
            QtWidgets.QMessageBox.information(
                self,
                self.tr("生成建议"),
                self.tr("请先导入 report.json 质检结果。"),
            )
            return
        # ensure feedback is written first so the suggestion reflects
        # the latest review decisions
        feedback_path = self._choose_quality_feedback_path()
        if feedback_path:
            try:
                self._flush_quality_feedback()
            except Exception:  # noqa: BLE001
                logger.exception("Failed to write feedback before suggestion")

        out_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            self.tr("保存阈值建议"),
            osp.join(osp.dirname(report_path), "threshold_suggestion.json"),
            self.tr("JSON (*.json)"),
        )
        if not out_path:
            return
        try:
            ctx = SuggestionContext(
                report_path=report_path,
                feedback_path=feedback_path or "",
                base_threshold_profile=(
                    self._quality_profile.profile_id
                    if self._quality_profile
                    else "v0_default"
                ),
            )
            generate_threshold_suggestion(ctx, out_path)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to generate threshold suggestion")
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("生成建议失败"),
                self.tr("无法生成阈值建议: %s") % str(exc),
            )
            return
        # emphasize the suggestion is non-binding
        QtWidgets.QMessageBox.information(
            self,
            self.tr("阈值建议已生成"),
            self.tr(
                "建议已写入：\n%1\n\n"
                "approval.status = pending，建议未生效，"
                "不会自动修改阈值 YAML。"
            ).arg(out_path),
        )

    # ── Scan progress helpers ────────────────────────────────────

    def _set_scan_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable controls while a background scan is running."""
        self._issue_list.scan_btn.setEnabled(enabled)
        self._issue_list.scan_current_btn.setEnabled(
            enabled and self._can_scan_current()
        )
        self._rule_config.setEnabled(enabled)
        if enabled:
            self._update_export_button()
        else:
            self._export_btn.setEnabled(False)

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
        self, current: int, total: int, current_name: str, stage: str
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
            if stage == "validate":
                self._scan_status_label.setText(
                    self.tr("正在检查规则: %s") % current_name
                )
            else:
                self._scan_status_label.setText(
                    self.tr("正在扫描: %s") % current_name
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
        self._issue_list.scan_current_btn.setEnabled(self._can_scan_current())

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

    def _resolve_current_json_path(self) -> Optional[str]:
        """Return the JSON annotation path for the current file.

        Matches by basename to handle cases where images and JSON
        files reside in different directories (e.g. ``images/`` vs
        ``jsons/``) or use different path separators.
        """
        if self._current_file_path is None:
            return None
        if self._current_file_path in self._flat_index._by_file:
            return self._current_file_path

        # Fast path: same directory, just different extension
        base, _ = osp.splitext(self._current_file_path)
        json_path = base + ".json"
        if json_path in self._flat_index._by_file:
            return json_path

        # Slow path: match by basename (handles different dirs)
        target_base = osp.splitext(osp.basename(self._current_file_path))[0]
        for key in self._flat_index._by_file:
            key_base = osp.splitext(osp.basename(key))[0]
            if key_base == target_base and key.endswith(".json"):
                return key
        return None

    def _can_scan_current(self) -> bool:
        """Return True if the current file can be scanned incrementally."""
        return self._resolve_current_json_path() is not None

    def set_current_file(self, file_path: Optional[str]) -> None:
        """Update the path of the currently viewed file.

        Called by label_widget whenever the active image changes.
        Enables or disables the "scan current" button accordingly.
        """
        self._current_file_path = file_path
        self._issue_list.scan_current_btn.setEnabled(self._can_scan_current())
        # keep the quality review widget in sync (drives 复扫当前 + filter)
        self._quality_review.set_current_file(file_path)

    def run_scan_current(self) -> None:
        """Re-scan and re-validate only the currently viewed file.

        Requires that a full scan has been run first so the file exists
        in the flat index.  Uses FlatIndex.refresh_file() to avoid
        re-reading all other files, then runs all rules on the updated
        in-memory index.
        """
        if self._scan_thread is not None or self._export_thread is not None:
            return

        json_path = self._resolve_current_json_path()
        if json_path is None:
            logger.warning(
                "Cannot scan current file: not in index (%s)",
                self._current_file_path,
            )
            return

        self._engine = ValidationEngine(self._rule_config.build_rules())

        self._flat_index.refresh_file(json_path)

        report = self._engine.run(self._flat_index)
        self._last_report = report
        self._issue_list.populate(report)
        self.scan_finished.emit(report)
        self._update_export_button()

        logger.info(
            "Inspector single-file scan finished: %d issues "
            "(%d errors, %d warnings)",
            report.issue_count,
            report.error_count,
            report.warning_count,
        )

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
        if self._scan_thread is not None or self._export_thread is not None:
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
        self._show_scan_progress(len(paths))

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
        if self._quality_thread is not None:
            self._quality_thread.cancel()
        if self._export_thread is not None:
            self._export_thread.cancel()
        self._flush_quality_feedback()
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
