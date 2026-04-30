"""
Issue List Widget — read-only, grouped display of validation issues.

Features:
- Issues grouped by rule (e.g. "标签名错误 (3)", "group_id重复 (1)")
- Color-coded by severity: error=red, warning=orange, info=blue
- Click to navigate: emits issue_clicked(file_path, shape_index)
"""

import logging
from typing import Dict, List, Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from .validation_engine import Issue, ValidationReport

logger = logging.getLogger(__name__)

# ── color constants ──────────────────────────────────────────────
SEVERITY_COLORS = {
    "error": QtGui.QColor(220, 53, 69),      # red
    "warning": QtGui.QColor(255, 193, 7),    # amber
    "info": QtGui.QColor(13, 110, 253),      # blue
}

SEVERITY_ICONS = {
    "error": "✗",
    "warning": "⚠",
    "info": "ℹ",
}


class IssueListWidget(QtWidgets.QWidget):
    """
    A tree widget that displays validation issues grouped by rule.

    Signals:
        issue_clicked(file_path: str, shape_index: int):
            Emitted when the user clicks a specific issue row.
        issue_double_clicked(file_path: str, shape_index: int):
            Emitted on double-click (→ navigate + activate edit mode).
        rescan_requested():
            Emitted when the user clicks the "Re-scan" button.
    """

    issue_clicked = QtCore.pyqtSignal(str, int)          # file_path, shape_index
    issue_double_clicked = QtCore.pyqtSignal(str, int)   # file_path, shape_index
    rescan_requested = QtCore.pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self._report: Optional[ValidationReport] = None
        self._setup_ui()
        self._connect_signals()

    # ── UI Setup ─────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ── header bar ───────────────────────────────────────────
        header_layout = QtWidgets.QHBoxLayout()

        self.title_label = QtWidgets.QLabel("数据检查")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 11pt;")
        header_layout.addWidget(self.title_label)

        header_layout.addStretch()

        self.scan_btn = QtWidgets.QPushButton("扫描")
        self.scan_btn.setFixedHeight(24)
        self.scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        header_layout.addWidget(self.scan_btn)

        layout.addLayout(header_layout)

        # ── summary bar ──────────────────────────────────────────
        self.summary_label = QtWidgets.QLabel("就绪")
        self.summary_label.setStyleSheet("color: #888; font-size: 9pt;")
        layout.addWidget(self.summary_label)

        # ── tree widget ──────────────────────────────────────────
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["问题", "文件", "详情"])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.tree.setIndentation(16)
        self.tree.setAnimated(True)

        # column widths
        header = self.tree.header()
        header.setStretchLastSection(True)
        header.resizeSection(0, 220)   # 问题
        header.resizeSection(1, 180)   # 文件

        layout.addWidget(self.tree)

    def _connect_signals(self) -> None:
        self.scan_btn.clicked.connect(self.rescan_requested.emit)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)

    # ── Populate ─────────────────────────────────────────────────

    def populate(self, report: ValidationReport) -> None:
        """Clear and repopulate the tree from a ValidationReport."""
        self._report = report
        self.tree.clear()

        if report.issue_count == 0:
            self.summary_label.setText(
                f"✓ 扫描 {report.total_files} 文件，{report.total_records} 条记录，未发现问题"
            )
            self.summary_label.setStyleSheet("color: #2e7d32; font-size: 9pt;")
            self.title_label.setText("数据检查 ✓")
            return

        # summary
        self.summary_label.setText(
            f"扫描 {report.total_files} 文件 | "
            f"✗ {report.error_count} 错误 | "
            f"⚠ {report.warning_count} 警告"
        )
        self.summary_label.setStyleSheet("color: #b71c1c; font-size: 9pt;")
        self.title_label.setText(
            f"数据检查 ({report.issue_count} 个问题)"
        )

        # group by rule
        grouped = report.issues_by_rule()

        for rule_name, issues in grouped.items():
            severity = issues[0].severity if issues else "info"
            color = SEVERITY_COLORS.get(severity, SEVERITY_COLORS["info"])
            icon = SEVERITY_ICONS.get(severity, "?")

            # ── group header item ────────────────────────────────
            group_item = QtWidgets.QTreeWidgetItem()
            group_item.setText(0, f"{icon} {rule_name}")
            group_item.setText(1, f"{len(issues)} 项")
            group_item.setForeground(0, color)
            font = group_item.font(0)
            font.setBold(True)
            group_item.setFont(0, font)
            group_item.setData(0, Qt.ItemDataRole.UserRole, {
                "type": "group",
                "rule_name": rule_name,
            })
            self.tree.addTopLevelItem(group_item)

            # ── leaf items ───────────────────────────────────────
            for issue in issues:
                leaf = QtWidgets.QTreeWidgetItem()
                leaf.setText(0, issue.message)
                leaf.setText(1, self._shorten_path(issue.file_path))
                leaf.setText(2, self._detail_text(issue))
                leaf.setToolTip(0, issue.message)
                leaf.setToolTip(1, issue.file_path)
                leaf.setData(0, Qt.ItemDataRole.UserRole, {
                    "type": "issue",
                    "file_path": issue.file_path,
                    "shape_index": issue.shape_index,
                    "group_id": issue.group_id,
                })
                group_item.addChild(leaf)

        self.tree.expandAll()

    def clear_results(self) -> None:
        """Reset to empty state."""
        self._report = None
        self.tree.clear()
        self.summary_label.setText("就绪")
        self.summary_label.setStyleSheet("color: #888; font-size: 9pt;")
        self.title_label.setText("数据检查")

    # ── Event handlers ───────────────────────────────────────────

    def _on_item_clicked(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "issue":
            file_path = data["file_path"]
            shape_index = data["shape_index"]
            self.issue_clicked.emit(file_path, shape_index)

    def _on_item_double_clicked(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "issue":
            file_path = data["file_path"]
            shape_index = data["shape_index"]
            self.issue_double_clicked.emit(file_path, shape_index)

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _shorten_path(path: str, max_len: int = 40) -> str:
        """Show just the filename + parent dir if path is too long."""
        import os.path as osp
        if len(path) <= max_len:
            return path
        parent = osp.basename(osp.dirname(path))
        filename = osp.basename(path)
        return f".../{parent}/{filename}"

    @staticmethod
    def _detail_text(issue: Issue) -> str:
        parts = []
        if issue.label:
            parts.append(f"label={issue.label}")
        if issue.group_id is not None:
            parts.append(f"gid={issue.group_id}")
        if issue.shape_index >= 0:
            parts.append(f"idx={issue.shape_index}")
        return ", ".join(parts)

    # ── Public helpers ───────────────────────────────────────────

    @property
    def has_results(self) -> bool:
        return self._report is not None and self._report.issue_count > 0
