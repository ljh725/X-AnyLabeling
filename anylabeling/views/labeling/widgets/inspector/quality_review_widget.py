"""
Quality Review Widget — L1/L2 issue review queue UI (PyQt6).

Displays the quality review queue grouped by rule, lets the user filter
(status / severity / rule / current file), navigate to the offending
file+shape, and record review decisions.  Review decisions are written
through to ``review_feedback.tsv`` by the owning InspectorPanel.

This widget stays a view only — all queue logic lives in the pure-Python
``QualityReviewQueue`` so it remains unit-testable without Qt.

Signals (consumed by InspectorPanel):
    issue_clicked(file_path: str, shape_index: int)
        Navigate to the issue's file + shape.  Matches the existing
        ``issue_navigate_requested`` contract so the panel re-emits it.
    import_requested()
        User clicked the import button (panel shows the file dialog).
    rescan_current_requested()
        User clicked "复扫当前" (panel runs the quality scan worker).
    generate_suggestion_requested()
        User clicked "生成建议" (panel calls threshold suggestion).
    review_changed()
        A review decision was recorded (panel flushes feedback.tsv).
"""

from __future__ import annotations

import logging
import os.path as osp
from typing import List, Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from .quality.quality_review_queue import (
    DEFAULT_FIXED_ACTION,
    QualityReviewItem,
    QualityReviewQueue,
    VALID_STATUSES,
)

logger = logging.getLogger(__name__)


# reuse the severity visual language from IssueListWidget
SEVERITY_COLORS = {
    "error": QtGui.QColor(220, 53, 69),
    "warning": QtGui.QColor(255, 193, 7),
    "info": QtGui.QColor(13, 110, 253),
}
SEVERITY_ICONS = {"error": "✗", "warning": "⚠", "info": "ℹ"}

# status visual language
STATUS_ICONS = {
    "pending": "○",
    "viewed": "◑",
    "fixed": "✓",
    "confirmed_error": "✗",
    "false_positive": "⊘",
    "acceptable": "◐",
    "needs_discussion": "?",
    "resolved_after_rescan": "—",
}
STATUS_LABELS = {
    "pending": "待复核",
    "viewed": "已查看",
    "fixed": "已修复",
    "confirmed_error": "确认错误",
    "false_positive": "误报",
    "acceptable": "可接受",
    "needs_discussion": "需讨论",
    "resolved_after_rescan": "复扫后消失",
}

_TREE_ROLE = Qt.ItemDataRole.UserRole


class QualityReviewWidget(QtWidgets.QWidget):
    """L1/L2 quality review queue UI."""

    issue_clicked = QtCore.pyqtSignal(str, int)
    related_issue_clicked = QtCore.pyqtSignal(str, int)
    import_requested = QtCore.pyqtSignal()
    rescan_current_requested = QtCore.pyqtSignal()
    generate_suggestion_requested = QtCore.pyqtSignal()
    review_changed = QtCore.pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self._queue = QualityReviewQueue()
        self._current_file: Optional[str] = None
        self._reviewer: str = ""
        self._setup_ui()
        self._connect_signals()
        self._refresh_filter_controls()
        self._update_action_state()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ── header bar ──────────────────────────────────────────
        header = QtWidgets.QHBoxLayout()
        self.title_label = QtWidgets.QLabel(self.tr("质检复核"))
        self.title_label.setStyleSheet("font-weight: bold; font-size: 11pt;")
        header.addWidget(self.title_label)
        header.addStretch()

        self.import_btn = self._mk_btn(self.tr("导入"))
        self.import_btn.setToolTip(self.tr("导入 report.json / review.tsv"))
        self.rescan_btn = self._mk_btn(self.tr("复扫当前"))
        self.rescan_btn.setEnabled(False)
        self.rescan_btn.setToolTip(self.tr("重新扫描当前文件的 L1/L2 issue"))
        self.suggest_btn = self._mk_btn(self.tr("生成建议"))
        self.suggest_btn.setToolTip(
            self.tr("基于 report.json + review_feedback.tsv 生成阈值建议")
        )
        for b in (self.import_btn, self.rescan_btn, self.suggest_btn):
            header.addWidget(b)
        layout.addLayout(header)

        # ── summary bar ─────────────────────────────────────────
        self.summary_label = QtWidgets.QLabel(self.tr("未导入质检结果"))
        self.summary_label.setStyleSheet("color: #888; font-size: 9pt;")
        layout.addWidget(self.summary_label)

        # ── filter bar ──────────────────────────────────────────
        filter_row = QtWidgets.QHBoxLayout()
        self.status_filter = QtWidgets.QComboBox()
        self.status_filter.addItem(self.tr("全部状态"), "")
        for st in [
            "pending",
            "viewed",
            "fixed",
            "confirmed_error",
            "false_positive",
            "acceptable",
            "needs_discussion",
            "resolved_after_rescan",
        ]:
            self.status_filter.addItem(
                f"{STATUS_ICONS.get(st, '')} {STATUS_LABELS.get(st, st)}", st
            )
        self.severity_filter = QtWidgets.QComboBox()
        self.severity_filter.addItem(self.tr("全部级别"), "")
        for sev in ("error", "warning", "info"):
            self.severity_filter.addItem(
                f"{SEVERITY_ICONS.get(sev, '')} {sev}", sev
            )
        self.rule_filter = QtWidgets.QComboBox()
        self.rule_filter.addItem(self.tr("全部规则"), "")
        self.current_file_chk = QtWidgets.QCheckBox(self.tr("仅当前文件"))
        for w in (
            self.status_filter,
            self.severity_filter,
            self.rule_filter,
            self.current_file_chk,
        ):
            filter_row.addWidget(w)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        # ── tree widget ─────────────────────────────────────────
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(
            [self.tr("问题"), self.tr("文件"), self.tr("详情")]
        )
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.tree.setIndentation(16)
        self.tree.setAnimated(True)
        hdr = self.tree.header()
        hdr.setStretchLastSection(True)
        hdr.resizeSection(0, 240)
        hdr.resizeSection(1, 160)
        layout.addWidget(self.tree)

        # ── action bar ──────────────────────────────────────────
        action_row = QtWidgets.QHBoxLayout()
        self.prev_btn = self._mk_btn(self.tr("上一条未处理"))
        self.next_btn = self._mk_btn(self.tr("下一条未处理"))
        self.related_btn = self._mk_btn(self.tr("定位另一对象"))
        self.related_btn.setEnabled(False)
        action_row.addWidget(self.prev_btn)
        action_row.addWidget(self.next_btn)
        action_row.addWidget(self.related_btn)
        action_row.addStretch()
        layout.addLayout(action_row)

        decision_row = QtWidgets.QHBoxLayout()
        self.fixed_btn = self._mk_btn(self.tr("已修复"))
        self.fixed_action_combo = QtWidgets.QComboBox()
        self.fixed_action_combo.setToolTip(self.tr("选择实际修复类型"))
        for action, label in [
            ("fixed_box", self.tr("框")),
            ("fixed_label", self.tr("标签")),
            ("fixed_group_id", self.tr("组ID")),
            ("fixed_points", self.tr("点")),
        ]:
            self.fixed_action_combo.addItem(label, action)
        self.confirm_btn = self._mk_btn(self.tr("确认错误"))
        self.fp_btn = self._mk_btn(self.tr("误报"))
        self.accept_btn = self._mk_btn(self.tr("可接受"))
        self.discuss_btn = self._mk_btn(self.tr("需讨论"))
        self.clear_btn = self._mk_btn(self.tr("清除"))
        for b in (
            self.fixed_btn,
            self.confirm_btn,
            self.fp_btn,
            self.accept_btn,
            self.discuss_btn,
            self.clear_btn,
        ):
            decision_row.addWidget(b)
        decision_row.insertWidget(1, self.fixed_action_combo)
        layout.addLayout(decision_row)

        # ── note row ────────────────────────────────────────────
        note_row = QtWidgets.QHBoxLayout()
        note_row.addWidget(QtWidgets.QLabel(self.tr("备注")))
        self.note_edit = QtWidgets.QLineEdit()
        self.note_edit.setPlaceholderText(self.tr("可选：边界样本或仲裁说明"))
        note_row.addWidget(self.note_edit)
        layout.addLayout(note_row)

    def _mk_btn(self, text: str) -> QtWidgets.QPushButton:
        btn = QtWidgets.QPushButton(text)
        btn.setFixedHeight(24)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def _connect_signals(self) -> None:
        self.import_btn.clicked.connect(self.import_requested.emit)
        self.rescan_btn.clicked.connect(self.rescan_current_requested.emit)
        self.suggest_btn.clicked.connect(
            self.generate_suggestion_requested.emit
        )
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.currentItemChanged.connect(self._on_current_changed)
        for w in (
            self.status_filter,
            self.severity_filter,
            self.rule_filter,
        ):
            w.currentIndexChanged.connect(self._repopulate)
        self.current_file_chk.toggled.connect(self._repopulate)

        self.prev_btn.clicked.connect(lambda: self._jump_unreviewed(-1))
        self.next_btn.clicked.connect(lambda: self._jump_unreviewed(+1))
        self.fixed_btn.clicked.connect(lambda: self._apply_status("fixed"))
        self.confirm_btn.clicked.connect(
            lambda: self._apply_status("confirmed_error")
        )
        self.fp_btn.clicked.connect(
            lambda: self._apply_status("false_positive")
        )
        self.accept_btn.clicked.connect(
            lambda: self._apply_status("acceptable")
        )
        self.discuss_btn.clicked.connect(
            lambda: self._apply_status("needs_discussion")
        )
        self.clear_btn.clicked.connect(lambda: self._apply_status("pending"))
        self.note_edit.editingFinished.connect(self._on_note_committed)
        self.related_btn.clicked.connect(self._navigate_related)

    # ------------------------------------------------------------------
    # Public API (called by InspectorPanel)
    # ------------------------------------------------------------------

    @property
    def queue(self) -> QualityReviewQueue:
        return self._queue

    def set_current_file(self, file_path: Optional[str]) -> None:
        """Track the currently-open file (drives '复扫当前' + filter)."""
        self._current_file = file_path
        self.rescan_btn.setEnabled(self.current_rescan_file() is not None)

    def set_reviewer(self, reviewer: str) -> None:
        self._reviewer = reviewer or ""

    def populate(self) -> None:
        """Rebuild the tree from the queue applying current filters."""
        self._refresh_filter_controls()
        self._repopulate()

    def has_results(self) -> bool:
        return self._queue.total > 0

    def current_rescan_file(self) -> Optional[str]:
        """Return the best JSON path for a current quality re-scan."""
        selected = self.get_selected_item()
        if selected is not None and osp.isfile(selected.file_path):
            return selected.file_path
        matched = self._queue.find_matching_file(self._current_file)
        if matched and osp.isfile(matched):
            return matched
        if (
            self._current_file
            and self._current_file.lower().endswith(".json")
            and osp.isfile(self._current_file)
        ):
            return self._current_file
        return None

    def get_selected_item(self) -> Optional[QualityReviewItem]:
        item = self.tree.currentItem()
        if item is None:
            return None
        data = item.data(0, _TREE_ROLE) or {}
        issue_id = data.get("issue_id")
        if not issue_id:
            return None
        return self._queue.get(issue_id)

    # ------------------------------------------------------------------
    # Filter controls
    # ------------------------------------------------------------------

    def _refresh_filter_controls(self) -> None:
        # rebuild rule filter from current queue
        cur = self.rule_filter.currentData()
        self.rule_filter.blockSignals(True)
        self.rule_filter.clear()
        self.rule_filter.addItem(self.tr("全部规则"), "")
        for rule_id in self._queue.unique_rule_ids():
            self.rule_filter.addItem(rule_id, rule_id)
        if cur:
            idx = self.rule_filter.findData(cur)
            if idx >= 0:
                self.rule_filter.setCurrentIndex(idx)
        self.rule_filter.blockSignals(False)

    def _current_filters(self):
        status = self.status_filter.currentData() or None
        severity = self.severity_filter.currentData() or None
        rule_id = self.rule_filter.currentData() or None
        file_path = (
            self._current_file if self.current_file_chk.isChecked() else None
        )
        return status, severity, rule_id, file_path

    # ------------------------------------------------------------------
    # Tree population
    # ------------------------------------------------------------------

    def _repopulate(self) -> None:
        self.tree.clear()
        status, severity, rule_id, file_path = self._current_filters()
        items = self._queue.sorted_items(
            status=status,
            severity=severity,
            rule_id=rule_id,
            file_path=file_path,
        )

        # group by rule_name, preserving sort order
        groups: dict = {}
        for it in items:
            groups.setdefault(it.rule_name or it.rule_id or "?", []).append(it)

        for rule_name, group in groups.items():
            top = QtWidgets.QTreeWidgetItem([rule_name, "", ""])
            top.setData(0, _TREE_ROLE, {"type": "group", "rule": rule_name})
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            sev = group[0].severity
            color = SEVERITY_COLORS.get(sev)
            if color is not None:
                for c in range(3):
                    top.setForeground(c, QtGui.QBrush(color))
            top.setText(1, f"{len(group)} 项")
            for it in group:
                child = self._build_leaf(it)
                top.addChild(child)
            self.tree.addTopLevelItem(top)
            top.setExpanded(True)

        self._update_summary(len(items))
        self._update_action_state()

    def _build_leaf(
        self, item: QualityReviewItem
    ) -> QtWidgets.QTreeWidgetItem:
        leaf = QtWidgets.QTreeWidgetItem()
        self._refresh_leaf(leaf, item)
        return leaf

    def _refresh_leaf(
        self, leaf: QtWidgets.QTreeWidgetItem, item: QualityReviewItem
    ) -> None:
        """Update one tree leaf from an item without rebuilding the tree."""
        icon = SEVERITY_ICONS.get(item.severity, "")
        status_icon = STATUS_ICONS.get(item.status, "")
        text = f"{icon} {status_icon} {item.message}"
        leaf.setText(0, text)
        leaf.setText(1, self._shorten_path(item.file_path))
        leaf.setText(2, self._detail(item))
        leaf.setData(
            0,
            _TREE_ROLE,
            {
                "type": "issue",
                "issue_id": item.issue_id,
                "file_path": item.file_path,
                "shape_index": item.shape_index,
            },
        )
        leaf.setToolTip(0, item.message)
        leaf.setToolTip(1, item.file_path)
        default_brush = QtGui.QBrush()
        for c in range(3):
            leaf.setForeground(c, default_brush)
        color = SEVERITY_COLORS.get(item.severity)
        if color is not None and item.status in (
            "pending",
            "viewed",
            "resolved_after_rescan",
        ):
            leaf.setForeground(0, QtGui.QBrush(color))
        if item.status == "resolved_after_rescan":
            # dim resolved items
            dim = QtGui.QColor(150, 150, 150)
            for c in range(3):
                leaf.setForeground(c, QtGui.QBrush(dim))

    @staticmethod
    def _shorten_path(path: str, max_len: int = 40) -> str:
        if len(path) <= max_len:
            return osp.basename(path)
        parent = osp.basename(osp.dirname(path))
        return f".../{parent}/{osp.basename(path)}"

    @staticmethod
    def _detail(item: QualityReviewItem) -> str:
        parts = []
        if item.label:
            parts.append(f"label={item.label}")
        if item.group_id is not None:
            parts.append(f"gid={item.group_id}")
        if item.shape_index >= 0:
            parts.append(f"idx={item.shape_index}")
        if item.primary_metric_name:
            parts.append(
                f"{item.primary_metric_name}={item.primary_metric_value:.2f}"
            )
        if item.duplicate_shape_index is not None:
            parts.append(f"other_idx={item.duplicate_shape_index}")
        if item.duplicate_iou is not None:
            parts.append(f"IoU={item.duplicate_iou:.4f}")
        return ", ".join(parts)

    # ------------------------------------------------------------------
    # Selection / navigation
    # ------------------------------------------------------------------

    def _on_item_clicked(
        self, item: QtWidgets.QTreeWidgetItem, _column: int
    ) -> None:
        data = item.data(0, _TREE_ROLE) or {}
        if data.get("type") != "issue":
            return
        issue_id = data.get("issue_id")
        if issue_id:
            self._queue.mark_viewed(issue_id)
        self.issue_clicked.emit(
            str(data.get("file_path", "")),
            int(data.get("shape_index", -1)),
        )

    def _on_item_double_clicked(
        self, item: QtWidgets.QTreeWidgetItem, _column: int
    ) -> None:
        # double-click also navigates (same contract as IssueListWidget)
        self._on_item_clicked(item, _column)

    def _on_current_changed(
        self,
        current: Optional[QtWidgets.QTreeWidgetItem],
        _previous,
    ) -> None:
        item = self.get_selected_item()
        if item is not None:
            self.note_edit.blockSignals(True)
            self.note_edit.setText(item.note)
            self.note_edit.blockSignals(False)
        self._update_action_state()

    def _update_action_state(self) -> None:
        item = self.get_selected_item()
        has_sel = item is not None
        self.rescan_btn.setEnabled(self.current_rescan_file() is not None)
        self.related_btn.setEnabled(
            item is not None and item.duplicate_shape_index is not None
        )
        self.suggest_btn.setEnabled(self._queue.has_report)
        for btn in (
            self.fixed_btn,
            self.fixed_action_combo,
            self.confirm_btn,
            self.fp_btn,
            self.accept_btn,
            self.discuss_btn,
            self.clear_btn,
            self.prev_btn,
            self.next_btn,
        ):
            btn.setEnabled(has_sel)

    def _navigate_related(self) -> None:
        """Navigate to the secondary shape of a duplicate-rectangle issue."""
        item = self.get_selected_item()
        if item is None or item.duplicate_shape_index is None:
            return
        self.related_issue_clicked.emit(
            item.file_path, int(item.duplicate_shape_index)
        )

    def _jump_unreviewed(
        self,
        direction: int,
        rule_id: Optional[str] = None,
        start_issue_id: Optional[str] = None,
    ) -> bool:
        """Select the next/prev unreviewed issue.

        When ``rule_id`` is provided, navigation stays inside the current
        issue category.  This keeps fast review from jumping into another
        top-level group after every decision.
        """
        status, severity, current_rule_id, file_path = self._current_filters()
        items = self._queue.sorted_items(
            status=status,
            severity=severity,
            rule_id=rule_id or current_rule_id,
            file_path=file_path,
        )
        issue_ids = [i.issue_id for i in items]
        cur = self.get_selected_item()
        start_idx = (
            issue_ids.index(start_issue_id)
            if start_issue_id and start_issue_id in issue_ids
            else (
                issue_ids.index(cur.issue_id)
                if cur and cur.issue_id in issue_ids
                else -1
            )
        )
        rng = (
            range(start_idx + 1, len(issue_ids))
            if direction > 0
            else range(start_idx - 1, -1, -1)
        )
        for idx in rng:
            it = items[idx]
            if it.status in ("pending", "viewed"):
                self._select_issue(it.issue_id)
                return True
        if start_issue_id:
            for it in items:
                if it.status in ("pending", "viewed"):
                    self._select_issue(it.issue_id)
                    return True
        return False

    def _select_issue(self, issue_id: str) -> None:
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                child = top.child(j)
                data = child.data(0, _TREE_ROLE) or {}
                if data.get("issue_id") == issue_id:
                    self.tree.setCurrentItem(child)
                    return

    def _jump_unreviewed_in_current_group(
        self, start_child: QtWidgets.QTreeWidgetItem
    ) -> bool:
        """Select the next unreviewed leaf inside the same top-level group."""
        top = start_child.parent()
        if top is None:
            return False
        start_idx = top.indexOfChild(start_child)
        for idx in list(range(start_idx + 1, top.childCount())) + list(
            range(0, start_idx)
        ):
            child = top.child(idx)
            data = child.data(0, _TREE_ROLE) or {}
            issue_id = data.get("issue_id")
            if not issue_id:
                continue
            item = self._queue.get(issue_id)
            if item is not None and item.status in ("pending", "viewed"):
                self.tree.setCurrentItem(child)
                return True
        return False

    # ------------------------------------------------------------------
    # Review actions
    # ------------------------------------------------------------------

    def _apply_status(self, status: str) -> None:
        item = self.get_selected_item()
        if item is None or status not in VALID_STATUSES:
            return
        current_leaf = self.tree.currentItem()
        final_action = None
        if status == "fixed":
            final_action = (
                self.fixed_action_combo.currentData() or DEFAULT_FIXED_ACTION
            )
        try:
            self._queue.update_review(
                item.issue_id,
                status=status,
                final_action=final_action,
                note=self.note_edit.text().strip() or item.note,
                reviewer=self._reviewer,
            )
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, self.tr("复核"), str(exc))
            return
        self.review_changed.emit()
        if (
            current_leaf is None
            or (self.status_filter.currentData() or None) is not None
        ):
            self._repopulate()
            self._select_issue(item.issue_id)
            return
        self._refresh_leaf(current_leaf, item)
        self._update_summary(self._visible_issue_count())
        if not self._jump_unreviewed_in_current_group(current_leaf):
            self.tree.setCurrentItem(current_leaf)
            self._update_action_state()

    def _on_note_committed(self) -> None:
        item = self.get_selected_item()
        if item is None:
            return
        note = self.note_edit.text().strip()
        if note == item.note:
            return
        item.note = note
        self.review_changed.emit()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _visible_issue_count(self) -> int:
        total = 0
        for i in range(self.tree.topLevelItemCount()):
            total += self.tree.topLevelItem(i).childCount()
        return total

    def _update_summary(self, shown: int) -> None:
        s = self._queue.stats()
        self.title_label.setText(
            self.tr("质检复核 ({0} 项)").format(s["total"])
        )
        self.summary_label.setText(
            self.tr(
                "已处理 {reviewed} / 总 {total} | "
                "误报 {fp} | 已修复 {fixed} | 当前显示 {shown}"
            ).format(
                reviewed=s["reviewed"],
                total=s["total"],
                fp=s["false_positive"],
                fixed=s["fixed"],
                shown=shown,
            )
        )
