"""
Inspector Panel — the main dock widget that houses the data inspection UI.

This is the top-level container.  It:
- Holds the FlatIndex, ValidationEngine, IssueListWidget, and EditableTableWidget.
- Orchestrates the scan → validate → display pipeline.
- Emits navigation signals that the parent label_widget connects to.
- Emits edit signals for bidirectional table ↔ canvas sync.

Usage (in label_widget.py)::

    from .widgets.inspector import InspectorPanel

    self.inspector_panel = InspectorPanel(allowed_labels={...})
    self.inspector_panel.issue_navigate_requested.connect(self._on_inspector_navigate)
    self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.inspector_panel)
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Set

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from .flat_index import FlatIndex, FlattenedRecord
from .validation_engine import (
    ValidationEngine,
    ValidationReport,
    ValidationRule,
    LabelInAllowlist,
    GroupIdUniqueness,
    GroupIdKeypointIntegrity,
    RequiredFieldNotEmpty,
    AttributeConsistency,
)
from .issue_list_widget import IssueListWidget
from .editable_table_widget import EditableTableWidget

logger = logging.getLogger(__name__)


class InspectorPanel(QtWidgets.QDockWidget):
    """
    Dock panel for annotation data quality inspection.

    Signals:
        issue_navigate_requested(file_path: str, shape_index: int)
            The user clicked an issue/table row → navigate to that file + shape.
        shape_edit_requested(file_path: str, shape_index: int, field: str, value)
            The user edited a cell in the editable table → modify the Shape object.
        scan_started()
            Emitted when a scan begins.
        scan_finished(report: ValidationReport)
            Emitted when a scan completes.
    """

    issue_navigate_requested = QtCore.pyqtSignal(str, int)
    shape_edit_requested = QtCore.pyqtSignal(str, int, str, object)
    scan_started = QtCore.pyqtSignal()
    scan_finished = QtCore.pyqtSignal(object)

    # ── COCO keypoints (same as KeypointFillMode) ──────────────
    COCO_KEYPOINTS: Set[str] = {
        "nose", "l_eye", "r_eye", "l_ear", "r_ear",
        "l_sho", "r_sho", "l_elb", "r_elb", "l_wri",
        "r_wri", "l_hip", "r_hip", "l_knee", "r_knee",
        "l_ank", "r_ank",
    }

    def __init__(
        self,
        allowed_labels: Optional[Set[str]] = None,
        extra_rules: Optional[List[ValidationRule]] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ):
        super().__init__(parent)
        self.setObjectName("Inspector")
        self.setWindowTitle(self.tr("数据检查 (Inspector)"))
        self.setMinimumWidth(320)

        # ── core components ──────────────────────────────────────
        self._allowed_labels: Set[str] = allowed_labels or set()
        self._extra_rules: List[ValidationRule] = extra_rules or []
        self._flat_index = FlatIndex()
        self._engine = self._build_engine(self._extra_rules)

        # ── UI: tab widget ───────────────────────────────────────
        self._tab_widget = QtWidgets.QTabWidget()

        self._issue_list = IssueListWidget()
        self._tab_widget.addTab(self._issue_list, self.tr("数据检查"))

        self._table_widget = EditableTableWidget()
        self._tab_widget.addTab(self._table_widget, self.tr("数据表格"))

        self.setWidget(self._tab_widget)

        # ── wire signals ─────────────────────────────────────────
        # issue list → translate
        self._issue_list.issue_double_clicked.connect(
            self.issue_navigate_requested.emit
        )
        self._issue_list.issue_clicked.connect(
            self.issue_navigate_requested.emit
        )
        self._issue_list.rescan_requested.connect(self.run_scan)

        # table → translate
        self._table_widget.shape_clicked.connect(
            self.issue_navigate_requested.emit
        )
        self._table_widget.shape_double_clicked.connect(
            self.issue_navigate_requested.emit
        )

        # table edit → forward to label_widget
        self._table_widget.set_edit_callback(self._on_table_edit)

        # ── state ────────────────────────────────────────────────
        self._last_report: Optional[ValidationReport] = None
        self._file_list: List[str] = []

        logger.debug("InspectorPanel initialized")

    # ── Engine factory ───────────────────────────────────────────

    def _build_engine(
        self,
        extra_rules: Optional[List[ValidationRule]] = None,
    ) -> ValidationEngine:
        rules: List[ValidationRule] = []

        if self._allowed_labels:
            rules.append(LabelInAllowlist(self._allowed_labels))

        rules.extend([
            GroupIdUniqueness(),
            GroupIdKeypointIntegrity(),
            RequiredFieldNotEmpty(),
            AttributeConsistency(),
        ])

        if extra_rules:
            rules.extend(extra_rules)

        return ValidationEngine(rules)

    # ── Table edit callback ──────────────────────────────────────

    def _on_table_edit(
        self, file_path: str, shape_index: int, field: str, value
    ) -> None:
        """Forward table edit to label_widget via signal."""
        self.shape_edit_requested.emit(file_path, shape_index, field, value)

    # ── Public API ───────────────────────────────────────────────

    def set_file_list(self, file_paths: List[str]) -> None:
        """
        Set the list of JSON files to scan.
        Call this when the file list changes (directory opened, files added).
        """
        self._file_list = list(file_paths)
        self._issue_list.clear_results()
        self._table_widget.clear_results()

    def set_allowed_labels(self, labels: Set[str]) -> None:
        """Update the label allowlist and rebuild the engine."""
        self._allowed_labels = set(labels)
        self._engine = self._build_engine(self._extra_rules)
        self._last_report = None
        self._issue_list.clear_results()
        self._table_widget.clear_results()

    def run_scan(self, json_paths: Optional[List[str]] = None) -> None:
        """
        Run a full scan → validate → display pipeline.

        If json_paths is None, uses the file list set via set_file_list().
        """
        paths = json_paths or self._file_list
        if not paths:
            logger.warning("No files to scan")
            return

        self.scan_started.emit()

        # ── Phase 1: index ───────────────────────────────────────
        self._flat_index.clear()
        self._flat_index.scan_files(paths)

        # ── Phase 2: validate ────────────────────────────────────
        report = self._engine.run(self._flat_index)
        self._last_report = report

        # ── Phase 3: display ─────────────────────────────────────
        self._issue_list.populate(report)

        self.scan_finished.emit(report)
        logger.info(
            f"Inspector scan finished: {report.issue_count} issues "
            f"({report.error_count} errors, {report.warning_count} warnings)"
        )

    def refresh_file(self, file_path: str) -> None:
        """
        Re-scan a single file after it's been modified.
        Updates the index and re-runs validation for affected records.
        """
        if file_path not in self._flat_index._by_file:
            return

        self._flat_index.refresh_file(file_path)

        if self._last_report:
            report = self._engine.run(self._flat_index)
            self._last_report = report
            self._issue_list.populate(report)

    # ── Editable table API ───────────────────────────────────────

    def populate_table(
        self, records: List[FlattenedRecord]
    ) -> None:
        """Populate the editable table with records (e.g. for current file)."""
        self._table_widget.populate(records)

    def refresh_table_from_shapes(
        self,
        file_path: str,
        shapes: list,
        image_path: str = "",
    ) -> None:
        """Refresh the editable table directly from canvas shapes (fast path).

        Args:
            file_path: Current file path (used as record key).
            shapes: List of Shape objects from canvas.
            image_path: The imagePath field (optional, for record completeness).
        """
        records = self._shapes_to_records(file_path, shapes, image_path)
        self._table_widget.populate(records)

    @staticmethod
    def _shapes_to_records(
        file_path: str,
        shapes: list,
        image_path: str = "",
    ) -> List[FlattenedRecord]:
        """Convert Shape objects to FlattenedRecords without JSON I/O."""
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
