"""
Inspector Panel — the main dock widget that houses the data inspection UI.

This is the top-level container.  It:
- Holds the FlatIndex, ValidationEngine, and IssueListWidget.
- Orchestrates the scan → validate → display pipeline.
- Emits navigation signals that the parent label_widget connects to.

Usage (in label_widget.py)::

    from .widgets.inspector import InspectorPanel

    self.inspector_panel = InspectorPanel(allowed_labels={...})
    self.inspector_panel.issue_navigate_requested.connect(self._on_inspector_navigate)
    self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.inspector_panel)
"""

import logging
import os.path as osp
from typing import Callable, Dict, List, Optional, Set

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

logger = logging.getLogger(__name__)


class InspectorPanel(QtWidgets.QDockWidget):
    """
    Dock panel for annotation data quality inspection.

    Signals:
        issue_navigate_requested(file_path: str, shape_index: int)
            The user clicked an issue → navigate to that file + shape.
        scan_started()
            Emitted when a scan begins.
        scan_finished(report: ValidationReport)
            Emitted when a scan completes.
    """

    issue_navigate_requested = QtCore.pyqtSignal(str, int)    # file_path, shape_index
    scan_started = QtCore.pyqtSignal()
    scan_finished = QtCore.pyqtSignal(object)                  # ValidationReport

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
        self._flat_index = FlatIndex(allowed_labels=self._allowed_labels)
        self._engine = self._build_engine(extra_rules)

        # ── UI ───────────────────────────────────────────────────
        self._issue_list = IssueListWidget()
        self.setWidget(self._issue_list)

        # ── wire signals ─────────────────────────────────────────
        self._issue_list.issue_double_clicked.connect(
            self.issue_navigate_requested.emit
        )
        self._issue_list.issue_clicked.connect(
            self.issue_navigate_requested.emit
        )
        self._issue_list.rescan_requested.connect(self.run_scan)

        # ── state ────────────────────────────────────────────────
        self._last_report: Optional[ValidationReport] = None
        self._file_list: List[str] = []           # current file list (JSON paths)

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

    # ── Public API ───────────────────────────────────────────────

    def set_file_list(self, file_paths: List[str]) -> None:
        """
        Set the list of JSON files to scan.
        Call this when the file list changes (directory opened, files added).
        """
        self._file_list = list(file_paths)
        self._issue_list.clear_results()

    def set_allowed_labels(self, labels: Set[str]) -> None:
        """Update the label allowlist and rebuild the engine."""
        self._allowed_labels = set(labels)
        self._engine = self._build_engine()
        # clear cached results since rules changed
        self._last_report = None
        self._issue_list.clear_results()

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
            # file not in index yet
            return

        self._flat_index.refresh_file(file_path)

        # re-run validation and update display
        if self._last_report:
            report = self._engine.run(self._flat_index)
            self._last_report = report
            self._issue_list.populate(report)

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
