"""Non-modal Inspector dialog for inspection runs, review and handoff."""

from __future__ import annotations

import html
import os
import os.path as osp
from dataclasses import replace
from typing import Any, Mapping, Optional

from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.services.inspection.candidates import (
    AcceptIntentStore,
    AlreadyAccepted,
    CandidateStore,
    load_candidates,
)
from anylabeling.services.inspection.handoff import (
    build_status,
    handoff_payload,
)
from anylabeling.services.inspection.importers import (
    export_report,
    import_legacy_report,
)
from anylabeling.services.inspection.models import (
    ActionState,
    Candidate,
    CandidateStatus,
    Decision,
    InspectionIssue,
    InspectionProfile,
    RunReport,
    RunScope,
    RunState,
    VerificationState,
)
from anylabeling.services.inspection.profiles import (
    build_default_catalog,
    copy_builtin,
    default_profiles,
    load_profile,
    save_profile,
    validate_profile,
)
from anylabeling.services.inspection.storage import (
    InspectionStorage,
    RevisionConflict,
    StorageError,
)
from anylabeling.services.inspection.verification import (
    verify_report_context,
)
from anylabeling.views.labeling.shape_identity import new_shape_id
from anylabeling.views.labeling.utils.style import (
    get_dialog_style,
    get_workbench_qss,
)
from anylabeling.views.labeling.utils.theme import get_theme

from .controller import InspectionController

STAGE_LABELS = {
    "pre_label": "预标注清洗",
    "in_progress": "标注中",
    "post_label": "完成后检查",
}

SCOPE_LABELS = {
    RunScope.CURRENT_IMAGE: "当前图片",
    RunScope.SELECTED_FILES: "选定文件",
    RunScope.DATASET: "当前数据集",
    RunScope.CHANGED_FILES: "已变更文件（保守全量）",
}


def _variant_button(text, variant=None, tip=None):
    """Build a button whose emphasis is driven by the scoped QSS."""
    button = QtWidgets.QPushButton(text)
    if variant:
        button.setProperty("variant", variant)
    if tip:
        button.setToolTip(tip)
    return button


_STATUS_WORDS = {
    "available": "可用",
    "passed": "通过",
    "failed": "未通过",
    "unchanged": "未改变",
}


def _state_word(payload) -> str:
    state = str(payload.get("state", ""))
    return _STATUS_WORDS.get(state, str(payload.get("label", state) or "未知"))


DECISION_LABELS = {
    Decision.PENDING: "待处理",
    Decision.CONFIRMED_ERROR: "确认错误",
    Decision.FALSE_POSITIVE: "误报",
    Decision.ACCEPTABLE: "可接受",
    Decision.NEEDS_DISCUSSION: "需讨论",
}

VERIFICATION_LABELS = {
    VerificationState.CURRENT: "当前",
    VerificationState.STALE: "已过期",
    VerificationState.PENDING_RECHECK: "待复查",
    VerificationState.NOT_DETECTED: "成功复查未再检出",
    VerificationState.UNVERIFIABLE: "无法核验",
}

ACTION_LABELS = {
    ActionState.UNCHANGED: "未改",
    ActionState.MODIFIED: "已修改",
    ActionState.DELETED: "已删除",
    ActionState.RELABELED: "已重标",
    ActionState.ADDED: "已新增",
}


class InspectorDialog(QtWidgets.QDialog):
    """Daily entry point: choose profile/range, run, review and recheck."""

    def __init__(
        self,
        host: Any,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent or host)
        self.host = host
        self.catalog = build_default_catalog()
        self.controller = InspectionController(self, self.catalog)
        self.storage: Optional[InspectionStorage] = None
        self.report: Optional[RunReport] = None
        self.manifest = None
        self.feedback: dict[str, Any] = {}
        self.feedback_revision = 0
        self._profiles: dict[str, InspectionProfile] = {}
        self._custom_profile_paths: dict[str, str] = {}
        self._row_issues: list[InspectionIssue] = []
        self._candidate_records: dict[str, Candidate] = {}
        self._candidate_revision = 0
        self._candidate_store: Optional[CandidateStore] = None
        self._intent_store: Optional[AcceptIntentStore] = None
        self._generation = 0
        self._active_profile: Optional[InspectionProfile] = None
        self._recheck_issue: Optional[InspectionIssue] = None
        self._session = None
        self._binding_key: Optional[tuple[str, str]] = None
        self._user_selected_profile = False
        self._verification_reasons: tuple[str, ...] = ()
        self._verification_current = True
        self._notes_visible = False
        self.setObjectName("annotationInspector")
        self._build_ui()
        self.setStyleSheet(get_dialog_style() + get_workbench_qss())
        self._connect()
        self._load_builtin_profiles()
        self._set_status("请选择方案和范围后开始检查。")
        self._show_details_placeholder()
        for label, text in (
            (self.execution_label, "执行 -"),
            (self.issue_handling_label, "问题 -"),
            (self.object_review_label, "对象 -"),
            (self.spatial_label, "空间 -"),
            (self.formal_label, "正式 -"),
        ):
            label.setText(self.tr(text))
        self.setWindowTitle(self.tr("Annotation Inspector"))
        self.resize(1200, 820)
        self.setWindowModality(QtCore.Qt.WindowModality.NonModal)

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(10)

        toolbar = QtWidgets.QFrame(self)
        toolbar.setObjectName("workbenchToolbar")
        toolbar_layout = QtWidgets.QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 8, 10, 8)
        toolbar_layout.setSpacing(8)

        self.profile_combo = QtWidgets.QComboBox()
        self.profile_combo.setMinimumWidth(190)
        self.profile_combo.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.stage_combo = QtWidgets.QComboBox()
        for value, label in STAGE_LABELS.items():
            self.stage_combo.addItem(label, value)
        self.stage_combo.setMinimumWidth(118)
        self.scope_combo = QtWidgets.QComboBox()
        for value, label in SCOPE_LABELS.items():
            self.scope_combo.addItem(label, value.value)
        self.scope_combo.setMinimumWidth(150)
        self.scope_combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.scope_combo.setMinimumContentsLength(9)

        for label, combo in (
            (self.tr("方案"), self.profile_combo),
            (self.tr("阶段"), self.stage_combo),
            (self.tr("范围"), self.scope_combo),
        ):
            caption = QtWidgets.QLabel(label)
            caption.setObjectName("fieldLabel")
            toolbar_layout.addWidget(caption)
            toolbar_layout.addWidget(combo)

        self.history_combo = QtWidgets.QComboBox()
        self.history_combo.setMinimumWidth(150)
        self.history_combo.setMaximumWidth(170)
        toolbar_layout.addWidget(self.history_combo)
        self.load_history_button = _variant_button(self.tr("加载"), "quiet")
        self.load_history_button.setToolTip(self.tr("加载选中的运行记录"))
        toolbar_layout.addWidget(self.load_history_button)

        self.more_button = _variant_button(self.tr("更多"), "quiet")
        self.more_button.setObjectName("moreButton")
        self.more_button.setToolTip(self.tr("方案与报告操作"))
        self.more_button.setFixedWidth(76)
        self.resume_button = _variant_button(self.tr("继续上次处理"))
        self.copy_profile_button = _variant_button(self.tr("复制方案"))
        self.import_profile_button = _variant_button(self.tr("导入方案"))
        self.export_profile_button = _variant_button(self.tr("导出方案"))
        self.import_issues_button = _variant_button(self.tr("导入旧问题"))
        self.export_button = _variant_button(self.tr("导出报告"))
        menu = QtWidgets.QMenu(self.more_button)
        for button in (
            self.resume_button,
            self.copy_profile_button,
            self.import_profile_button,
            self.export_profile_button,
            self.import_issues_button,
            self.export_button,
        ):
            button.setVisible(False)
            button.setParent(self)
        menu.addAction(self.tr("继续上次处理"), self.resume_button.click)
        menu.addAction(self.tr("复制方案"), self.copy_profile_button.click)
        menu.addAction(self.tr("导入方案"), self.import_profile_button.click)
        menu.addAction(self.tr("导出方案"), self.export_profile_button.click)
        menu.addSeparator()
        menu.addAction(self.tr("导入旧问题"), self.import_issues_button.click)
        menu.addAction(self.tr("导出报告"), self.export_button.click)
        self.more_button.setMenu(menu)
        toolbar_layout.addWidget(self.more_button)
        toolbar_layout.addStretch(1)

        self.cancel_button = _variant_button(self.tr("取消"))
        self.cancel_button.setEnabled(False)
        self.start_button = _variant_button(self.tr("开始检查"), "primary")
        toolbar_layout.addWidget(self.cancel_button)
        toolbar_layout.addWidget(self.start_button)
        layout.addWidget(toolbar)

        statusline = QtWidgets.QFrame(self)
        statusline.setObjectName("workbenchStatus")
        status_row = QtWidgets.QHBoxLayout(statusline)
        status_row.setContentsMargins(10, 6, 10, 6)
        status_row.setSpacing(10)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedSize(140, 6)
        self.status_label = QtWidgets.QLabel()
        self.status_label.setWordWrap(False)
        status_row.addWidget(self.progress)
        status_row.addWidget(self.status_label, 1)
        layout.addWidget(statusline)

        self.info_frame = QtWidgets.QFrame(self)
        info_layout = QtWidgets.QVBoxLayout(self.info_frame)
        info_layout.setContentsMargins(10, 8, 10, 8)
        info_layout.setSpacing(4)
        self.profile_summary = QtWidgets.QLabel()
        self.profile_summary.setWordWrap(True)
        self.rule_summary = QtWidgets.QLabel()
        self.rule_summary.setWordWrap(True)
        info_layout.addWidget(self.profile_summary)
        info_layout.addWidget(self.rule_summary)
        self.info_frame.setVisible(False)
        layout.addWidget(self.info_frame)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        queue_panel = QtWidgets.QWidget()
        queue_layout = QtWidgets.QVBoxLayout(queue_panel)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        queue_layout.setSpacing(6)

        filter_row = QtWidgets.QHBoxLayout()
        filter_row.setSpacing(6)
        self.filter_combo = QtWidgets.QComboBox()
        self.filter_combo.addItem("全部", "all")
        self.filter_combo.addItem("待处理", "pending")
        self.filter_combo.addItem("已处理", "handled")
        self.filter_combo.addItem("待复查", "pending_recheck")
        self.filter_combo.addItem("误报", "false_positive")
        self.filter_combo.addItem("可接受", "acceptable")
        self.filter_combo.addItem("需讨论", "needs_discussion")
        self.filter_combo.addItem("确认错误", "confirmed_error")
        self.issue_count_label = QtWidgets.QLabel()
        self.issue_count_label.setObjectName("fieldLabel")
        self.prev_issue_button = _variant_button(self.tr("上一个"), "quiet")
        self.next_issue_button = _variant_button(self.tr("下一个"), "quiet")
        filter_row.addWidget(self.filter_combo)
        filter_row.addWidget(self.issue_count_label)
        filter_row.addStretch(1)
        filter_row.addWidget(self.prev_issue_button)
        filter_row.addWidget(self.next_issue_button)
        queue_layout.addLayout(filter_row)

        self.issue_stack = QtWidgets.QStackedWidget()
        self.issue_table = QtWidgets.QTableWidget(0, 5)
        self.issue_table.setHorizontalHeaderLabels(
            [
                self.tr("风险"),
                self.tr("规则"),
                self.tr("文件 · 对象"),
                self.tr("机器状态"),
                self.tr("人工判断"),
            ]
        )
        self.issue_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.issue_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.issue_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.issue_table.setShowGrid(False)
        self.issue_table.setWordWrap(False)
        self.issue_table.setTextElideMode(QtCore.Qt.TextElideMode.ElideRight)
        self.issue_table.verticalHeader().setVisible(False)
        self.issue_table.verticalHeader().setDefaultSectionSize(34)
        table_palette = self.issue_table.palette()
        table_palette.setColor(
            QtGui.QPalette.ColorRole.HighlightedText,
            QtGui.QColor(get_theme()["text"]),
        )
        self.issue_table.setPalette(table_palette)
        header = self.issue_table.horizontalHeader()
        header.setHighlightSections(False)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeMode.Fixed)
        for column, width in enumerate((62, 128, 0, 88, 78)):
            if width:
                self.issue_table.setColumnWidth(column, width)
        self.issue_stack.addWidget(self.issue_table)

        empty_page = QtWidgets.QWidget()
        empty_layout = QtWidgets.QVBoxLayout(empty_page)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        self.empty_state_label = QtWidgets.QLabel(
            self.tr(
                "选择方案与范围后点击「开始检查」。\n问题会按风险列在这里。"
            )
        )
        self.empty_state_label.setObjectName("emptyState")
        self.empty_state_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignCenter
        )
        self.empty_state_label.setWordWrap(True)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.empty_state_label)
        empty_layout.addStretch(1)
        self.issue_stack.addWidget(empty_page)
        self.issue_stack.setCurrentIndex(1)
        queue_layout.addWidget(self.issue_stack, 1)
        splitter.addWidget(queue_panel)

        detail_panel = QtWidgets.QWidget()
        detail_panel.setMinimumWidth(380)
        detail_layout = QtWidgets.QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_tabs = QtWidgets.QTabWidget()
        self.tabs = self.detail_tabs

        detail_page = QtWidgets.QWidget()
        detail_page_layout = QtWidgets.QVBoxLayout(detail_page)
        detail_page_layout.setContentsMargins(10, 10, 10, 10)
        detail_page_layout.setSpacing(8)
        self.details = QtWidgets.QTextBrowser()
        self.details.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.details.setOpenExternalLinks(False)
        detail_page_layout.addWidget(self.details, 1)

        action_grid = QtWidgets.QGridLayout()
        action_grid.setSpacing(6)
        self.locate_button = _variant_button(self.tr("定位"))
        self.false_positive_button = _variant_button(self.tr("标记误报"))
        self.acceptable_button = _variant_button(self.tr("标记可接受"))
        self.discussion_button = _variant_button(self.tr("需讨论"))
        self.confirmed_button = _variant_button(self.tr("确认错误"))
        self.modified_button = _variant_button(self.tr("标记已修改"))
        self.recheck_button = _variant_button(self.tr("复查当前图"))
        self.delete_button = _variant_button(self.tr("删除画布选中框"))
        self.delete_button.setProperty("variant", "danger")
        self.delete_button.setEnabled(False)
        self.delete_button.setToolTip(
            self.tr("请先在画布中选中要删除的问题对象")
        )
        self.relabel_button = _variant_button(self.tr("重标画布选中框"))
        self.relabel_button.setProperty("variant", "danger")
        self.relabel_button.setEnabled(False)
        self.relabel_button.setToolTip(
            self.tr("请先在画布中选中要重标的问题对象")
        )
        actions = (
            self.locate_button,
            self.false_positive_button,
            self.acceptable_button,
            self.discussion_button,
            self.confirmed_button,
            self.modified_button,
            self.recheck_button,
            self.delete_button,
            self.relabel_button,
        )
        for index, button in enumerate(actions):
            action_grid.addWidget(button, index // 3, index % 3)
        detail_page_layout.addLayout(action_grid)
        self.detail_tabs.addTab(detail_page, self.tr("详情"))

        candidate_panel = QtWidgets.QWidget()
        candidate_layout = QtWidgets.QVBoxLayout(candidate_panel)
        candidate_layout.setContentsMargins(10, 10, 10, 10)
        candidate_layout.setSpacing(8)
        self.candidate_table = QtWidgets.QTableWidget(0, 4)
        self.candidate_table.setHorizontalHeaderLabels(
            [
                self.tr("状态"),
                self.tr("类别"),
                self.tr("文件 · 区域"),
                self.tr("来源 / 分数"),
            ]
        )
        self.candidate_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.candidate_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.candidate_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.candidate_table.setShowGrid(False)
        self.candidate_table.setWordWrap(False)
        self.candidate_table.verticalHeader().setVisible(False)
        self.candidate_table.verticalHeader().setDefaultSectionSize(30)
        candidate_header = self.candidate_table.horizontalHeader()
        candidate_header.setHighlightSections(False)
        candidate_header.setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.Fixed
        )
        candidate_header.setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeMode.Fixed
        )
        candidate_header.setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        candidate_header.setSectionResizeMode(
            3, QtWidgets.QHeaderView.ResizeMode.Fixed
        )
        self.candidate_table.setColumnWidth(0, 64)
        self.candidate_table.setColumnWidth(1, 64)
        self.candidate_table.setColumnWidth(3, 86)
        candidate_buttons = QtWidgets.QHBoxLayout()
        candidate_buttons.setSpacing(6)
        self.import_candidates_button = _variant_button(self.tr("导入候选"))
        self.accept_candidate_button = _variant_button(self.tr("接受候选"))
        self.reject_candidate_button = _variant_button(self.tr("拒绝"))
        self.defer_candidate_button = _variant_button(self.tr("暂存"))
        candidate_buttons.addWidget(self.import_candidates_button)
        candidate_buttons.addWidget(self.accept_candidate_button)
        candidate_buttons.addWidget(self.reject_candidate_button)
        candidate_buttons.addWidget(self.defer_candidate_button)
        candidate_buttons.addStretch(1)
        candidate_layout.addWidget(self.candidate_table, 1)
        candidate_layout.addLayout(candidate_buttons)
        self.detail_tabs.addTab(candidate_panel, self.tr("外部候选"))

        detail_layout.addWidget(self.detail_tabs, 1)
        splitter.addWidget(detail_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([740, 380])
        layout.addWidget(splitter, 1)

        self.note_label = QtWidgets.QLabel()
        self.note_label.setWordWrap(True)
        self.note_label.setObjectName("fieldLabel")
        self.note_label.setVisible(False)
        layout.addWidget(self.note_label)

        self.execution_label = QtWidgets.QLabel()
        self.issue_handling_label = QtWidgets.QLabel()
        self.object_review_label = QtWidgets.QLabel()
        self.spatial_label = QtWidgets.QLabel()
        self.formal_label = QtWidgets.QLabel()
        for label in (
            self.execution_label,
            self.issue_handling_label,
            self.object_review_label,
            self.spatial_label,
            self.formal_label,
        ):
            label.setObjectName("statusChip")

        footer = QtWidgets.QFrame(self)
        footer.setObjectName("workbenchStatus")
        footer_layout = QtWidgets.QHBoxLayout(footer)
        footer_layout.setContentsMargins(10, 6, 10, 6)
        footer_layout.setSpacing(14)
        for label in (
            self.execution_label,
            self.issue_handling_label,
            self.object_review_label,
            self.spatial_label,
            self.formal_label,
        ):
            footer_layout.addWidget(label)
        footer_layout.addStretch(1)
        self.note_toggle_button = _variant_button(self.tr("说明"), "quiet")
        self.close_button = _variant_button(self.tr("关闭"), "quiet")
        footer_layout.addWidget(self.note_toggle_button)
        footer_layout.addWidget(self.close_button)
        layout.addWidget(footer)
        for button in self.findChildren(QtWidgets.QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)

    def _connect(self) -> None:
        self.start_button.clicked.connect(self._start_run)
        self.cancel_button.clicked.connect(self.controller.cancel)
        self.resume_button.clicked.connect(self._resume_last)
        self.copy_profile_button.clicked.connect(self._copy_profile)
        self.import_profile_button.clicked.connect(self._import_profile)
        self.export_profile_button.clicked.connect(self._export_profile)
        self.load_history_button.clicked.connect(self._load_selected_history)
        self.prev_issue_button.clicked.connect(lambda: self._select_issue(-1))
        self.next_issue_button.clicked.connect(lambda: self._select_issue(1))
        self.host.canvas.shape_moved.connect(self._on_canvas_edit)
        self.host.canvas.shape_rotated.connect(self._on_canvas_edit)
        self.host.canvas.shapes_deleted.connect(self._on_canvas_edit)
        self.host.canvas.selection_changed.connect(self._update_action_buttons)
        self.host.actions.undo.triggered.connect(self._on_canvas_edit)
        self.filter_combo.currentIndexChanged.connect(self._populate_table)
        self.profile_combo.currentIndexChanged.connect(
            self._update_profile_details
        )
        self.profile_combo.activated.connect(self._mark_profile_selected)
        self.issue_table.itemSelectionChanged.connect(
            self._show_selected_details
        )
        self.issue_table.cellDoubleClicked.connect(
            lambda *_: self._locate_selected()
        )
        self.locate_button.clicked.connect(self._locate_selected)
        self.false_positive_button.clicked.connect(
            lambda: self._set_decision(Decision.FALSE_POSITIVE)
        )
        self.acceptable_button.clicked.connect(
            lambda: self._set_decision(Decision.ACCEPTABLE)
        )
        self.discussion_button.clicked.connect(
            lambda: self._set_decision(Decision.NEEDS_DISCUSSION)
        )
        self.confirmed_button.clicked.connect(
            lambda: self._set_decision(Decision.CONFIRMED_ERROR)
        )
        self.modified_button.clicked.connect(self._mark_modified)
        self.recheck_button.clicked.connect(self._recheck_selected)
        self.delete_button.clicked.connect(self._delete_selected)
        self.relabel_button.clicked.connect(self._relabel_selected)
        self.import_issues_button.clicked.connect(self._import_issues)
        self.export_button.clicked.connect(self._export_report)
        self.note_toggle_button.clicked.connect(self._toggle_notes)
        self.import_candidates_button.clicked.connect(self._import_candidates)
        self.accept_candidate_button.clicked.connect(self._accept_candidate)
        self.reject_candidate_button.clicked.connect(
            lambda: self._set_candidate_status(CandidateStatus.REJECTED)
        )
        self.defer_candidate_button.clicked.connect(
            lambda: self._set_candidate_status(CandidateStatus.DEFERRED)
        )
        self.close_button.clicked.connect(self.close)
        self.controller.progress.connect(self._on_progress)
        self.controller.stage_changed.connect(self._set_status)
        self.controller.finished.connect(self._on_finished)
        self.controller.failed.connect(self._on_failed)

    def _load_builtin_profiles(self) -> None:
        self._profiles = {
            profile.profile_id: profile for profile in default_profiles()
        }
        self._refresh_profile_combo()

    def _refresh_profile_combo(self, selected_id: str = "") -> None:
        current = selected_id or self.profile_combo.currentData()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for profile_id in sorted(
            self._profiles, key=lambda item: self._profiles[item].name
        ):
            profile = self._profiles[profile_id]
            suffix = "" if profile.builtin else self.tr("（自定义）")
            self.profile_combo.addItem(profile.name + suffix, profile_id)
        if current:
            index = self.profile_combo.findData(current)
            if index >= 0:
                self.profile_combo.setCurrentIndex(index)
        self.profile_combo.blockSignals(False)
        self._update_profile_details()

    def _selected_profile(self) -> Optional[InspectionProfile]:
        profile_id = self.profile_combo.currentData()
        return self._profiles.get(str(profile_id))

    def _mark_profile_selected(self, *args) -> None:
        self._user_selected_profile = True

    def _update_profile_details(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            self.profile_summary.clear()
            self.rule_summary.clear()
            return
        index = self.stage_combo.findData(profile.stage)
        if index >= 0:
            self.stage_combo.blockSignals(True)
            self.stage_combo.setCurrentIndex(index)
            self.stage_combo.blockSignals(False)
        self.profile_summary.setText(
            f"{profile.description}\n适用阶段："
            f"{STAGE_LABELS.get(profile.stage, profile.stage)}；"
            f"版本：{profile.version}"
        )
        names = []
        for rule in profile.enabled_rules:
            meta = self.catalog.meta(rule.rule_id)
            names.append(meta.name if meta else rule.rule_id)
        self.rule_summary.setText("、".join(names) if names else "无启用规则")

    def _copy_profile(self) -> None:
        if not self._ensure_storage() or self.storage is None:
            return
        profile = self._selected_profile()
        if profile is None:
            return
        name, ok = QtWidgets.QInputDialog.getText(
            self,
            "复制检查方案",
            "新方案名称：",
            text=f"{profile.name} 副本",
        )
        if not ok or not name.strip():
            return
        new_id = "custom-" + new_shape_id()[:8]
        copied = copy_builtin(profile, new_id, name.strip())
        path = osp.join(self.storage.root, "profiles", f"{new_id}.json")
        try:
            save_profile(path, copied)
        except OSError as error:
            self._show_error("复制方案失败", str(error))
            return
        self._profiles[new_id] = copied
        self._custom_profile_paths[new_id] = path
        self._refresh_profile_combo(new_id)
        self._set_status(f"已创建自定义方案 {copied.name}。")

    def _import_profile(self) -> None:
        if not self._ensure_storage() or self.storage is None:
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "导入检查方案",
            self.storage.root,
            "JSON (*.json);;所有文件 (*)",
        )
        if not path:
            return
        try:
            profile = load_profile(path)
        except (OSError, ValueError) as error:
            self._show_error("导入方案失败", str(error))
            return
        validation = validate_profile(profile, self.catalog)
        if validation.errors:
            self._show_error("方案无效", "\n".join(validation.errors))
            return
        target = osp.join(
            self.storage.root, "profiles", f"{profile.profile_id}.json"
        )
        try:
            save_profile(target, profile)
        except OSError as error:
            self._show_error("保存方案失败", str(error))
            return
        self._profiles[profile.profile_id] = profile
        self._custom_profile_paths[profile.profile_id] = target
        self._refresh_profile_combo(profile.profile_id)
        if validation.missing_rule_ids:
            QtWidgets.QMessageBox.warning(
                self,
                "方案含缺失规则",
                "本机未登记：\n"
                + "\n".join(validation.missing_rule_ids)
                + "\n\n运行时可选择仅执行可用子集。",
            )
        else:
            self._set_status(f"已导入方案 {profile.name}。")

    def _export_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "导出检查方案",
            f"{profile.profile_id}.json",
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            save_profile(path, profile)
        except OSError as error:
            self._show_error("导出方案失败", str(error))
            return
        self._set_status(f"已导出方案 {path}。")

    def _select_issue(self, offset: int) -> None:
        if not self._row_issues:
            return
        row = self.issue_table.currentRow()
        if row < 0:
            row = 0 if offset > 0 else len(self._row_issues) - 1
        else:
            row = max(0, min(len(self._row_issues) - 1, row + offset))
        self.issue_table.selectRow(row)
        item = self.issue_table.item(row, 0)
        if item is not None:
            self.issue_table.scrollToItem(item)

    def _on_canvas_edit(self, *args) -> None:
        if self.report is None:
            return
        relative = self.host.inspection_current_relative_path()
        changed = False
        issues = []
        for issue in self.report.issues:
            if (
                issue.location.relative_path == relative
                and issue.verification is VerificationState.CURRENT
            ):
                issues.append(
                    replace(
                        issue,
                        verification=VerificationState.PENDING_RECHECK,
                    )
                )
                changed = True
            else:
                issues.append(issue)
        if not changed:
            return
        self.report = replace(self.report, issues=tuple(issues))
        self._populate_table()
        self._update_status()
        self._set_status("画布已修改，相关问题标记为待复查。")

    def _ask_dirty_batch(self) -> str:
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("存在未保存修改")
        box.setText(
            "批量检查范围包含当前未保存文档。请选择保存后运行、"
            "明确排除该图片，或取消。"
        )
        save_button = box.addButton(
            "保存后运行", QtWidgets.QMessageBox.ButtonRole.AcceptRole
        )
        exclude_button = box.addButton(
            "排除未保存图片", QtWidgets.QMessageBox.ButtonRole.DestructiveRole
        )
        box.addButton("取消", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save_button:
            return "save"
        if clicked is exclude_button:
            return "exclude"
        return "cancel"

    def _ensure_storage(self) -> bool:
        dataset_root = self.host.inspection_dataset_root()
        output_dir = self.host.inspection_output_dir()
        if not dataset_root:
            self._set_status("无法确定数据集目录。")
            return False
        try:
            storage = InspectionStorage.open(dataset_root, output_dir)
        except OSError as error:
            self._show_error("无法建立检查存储", str(error))
            return False
        if self.storage is None or self.storage.root != storage.root:
            self.storage = storage
            self._load_feedback()
            self._load_custom_profiles()
            self._load_candidates()
            self._load_session()
            self._refresh_history_combo()
        binding_key = (
            osp.abspath(dataset_root),
            osp.abspath(output_dir or dataset_root),
        )
        if self._binding_key != binding_key:
            self._binding_key = binding_key
            if not self._user_selected_profile:
                binding = None
                try:
                    binding = self.storage.bindings.load(
                        dataset_root, output_dir
                    )
                except (OSError, StorageError):
                    binding = None
                if binding and binding.get("profile_id") in self._profiles:
                    index = self.profile_combo.findData(binding["profile_id"])
                    if index >= 0:
                        self.profile_combo.setCurrentIndex(index)
            self._user_selected_profile = False
        return True

    def _load_custom_profiles(self) -> None:
        if self.storage is None:
            return
        directory = osp.join(self.storage.root, "profiles")
        if not osp.isdir(directory):
            return
        for name in sorted(os.listdir(directory)):
            if not name.lower().endswith(".json"):
                continue
            path = osp.join(directory, name)
            try:
                profile = load_profile(path)
            except (OSError, ValueError) as error:
                self._set_status(f"自定义方案读取失败 {name}: {error}")
                continue
            if (
                profile.profile_id in self._profiles
                and self._profiles[profile.profile_id].builtin
            ):
                continue
            self._profiles[profile.profile_id] = profile
            self._custom_profile_paths[profile.profile_id] = path
        self._refresh_profile_combo()

    def _load_feedback(self) -> None:
        if self.storage is None:
            return
        try:
            snapshot = self.storage.feedback.load()
        except (OSError, StorageError) as error:
            self.feedback = {}
            self.feedback_revision = 0
            self._set_status(f"反馈读取失败: {error}")
            return
        self.feedback = dict(snapshot.records)
        self.feedback_revision = snapshot.revision

    def _load_candidates(self) -> None:
        if self.storage is None:
            return
        self._candidate_store = CandidateStore(self.storage.root)
        self._intent_store = AcceptIntentStore(self.storage.root)
        try:
            revision, records = self._candidate_store.load()
        except (OSError, StorageError) as error:
            self._candidate_records = {}
            self._candidate_revision = 0
            self._set_status(f"候选状态读取失败: {error}")
        else:
            self._candidate_records = dict(records)
            self._candidate_revision = revision
        self._populate_candidate_table()

    def _prepare_run_profile(self):
        profile = self._selected_profile()
        if profile is None:
            self._show_error("检查", "请选择检查方案。")
            return None
        stage = str(self.stage_combo.currentData())
        if stage != profile.stage:
            profile = replace(profile, stage=stage)
        validation = validate_profile(profile, self.catalog)
        if validation.errors:
            self._show_error("方案无法运行", "\n".join(validation.errors))
            return None
        allow_partial = False
        if validation.missing_rule_ids:
            answer = QtWidgets.QMessageBox.question(
                self,
                "规则缺失",
                "方案引用本机未登记规则：\n"
                + "\n".join(validation.missing_rule_ids)
                + "\n\n仅运行可用子集？",
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
            )
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                return None
            allow_partial = True
        return profile, allow_partial

    def _prepare_scope(self, scope, dataset_root):
        manifest = None
        paths = None
        if scope is RunScope.CURRENT_IMAGE:
            manifest = self.host.inspection_current_manifest()
            if manifest is None:
                self._show_error("检查", "当前没有可检查的图片。")
                return None, None, False
        elif scope is RunScope.SELECTED_FILES:
            paths = self.host.inspection_selected_image_paths()
            if not paths:
                self._show_error("检查", "请先在文件列表选择文件。")
                return None, None, False
        else:
            if dataset_root:
                paths = None
            else:
                paths = self.host.inspection_image_paths()
            if not paths and not dataset_root:
                self._show_error("检查", "当前数据集没有可检查文件。")
                return None, None, False
            if scope is RunScope.CHANGED_FILES:
                self._set_status(
                    "正在核验上一份清单；无可信清单时按保守范围全量检查。"
                )
        return manifest, paths, True

    def _prepare_batch_dirty(self, scope, paths):
        excluded = set()
        if scope is RunScope.CURRENT_IMAGE or not getattr(
            self.host, "dirty", False
        ):
            return paths, excluded, True
        if paths is not None and self.host.filename not in paths:
            return paths, excluded, True
        choice = self._ask_dirty_batch()
        if choice == "cancel":
            return paths, excluded, False
        if choice == "save":
            self.host.save_file()
            if getattr(self.host, "dirty", False):
                self._show_error(
                    "保存失败", "未保存修改仍然存在，已取消检查。"
                )
                return paths, excluded, False
            return paths, excluded, True
        if paths is None:
            return paths, {self.host.filename}, True
        remaining = [path for path in paths if path != self.host.filename]
        if not remaining:
            self._show_error("检查", "排除未保存图片后范围为空。")
            return paths, excluded, False
        return remaining, excluded, True

    def _start_run(self) -> None:
        if self.controller.is_running():
            return
        if not self._ensure_storage():
            return
        prepared = self._prepare_run_profile()
        if prepared is None:
            return
        profile, allow_partial = prepared
        scope = RunScope(str(self.scope_combo.currentData()))
        dataset_root = self.host.inspection_dataset_root()
        output_dir = self.host.inspection_output_dir()
        manifest, paths, proceed = self._prepare_scope(scope, dataset_root)
        if not proceed:
            return
        paths, excluded, proceed = self._prepare_batch_dirty(scope, paths)
        if not proceed:
            return
        previous_manifest = None
        if scope is RunScope.CHANGED_FILES and self.storage is not None:
            entries = self.storage.reports.list_reports()
            if entries:
                try:
                    previous_manifest = self.storage.reports.load_manifest(
                        str(entries[0].get("run_id", ""))
                    )
                except (OSError, StorageError):
                    previous_manifest = None
        self._active_profile = profile
        self._generation += 1
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setRange(0, 0)
        self._set_status("扫描文件")
        try:
            self.controller.start(
                profile,
                scope,
                dataset_root=dataset_root,
                output_dir=output_dir,
                image_paths=paths,
                manifest=manifest,
                excluded_paths=excluded,
                previous_manifest=previous_manifest,
                allow_partial=allow_partial,
                generation=self._generation,
            )
        except RuntimeError as error:
            self.start_button.setEnabled(True)
            self.cancel_button.setEnabled(False)
            self._show_error("检查", str(error))

    def _on_progress(self, index: int, total: int, path: str) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(index)
        self._set_status(f"检查 {index}/{total}: {path}")

    def _on_failed(self, message: str) -> None:
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self._set_status(f"检查失败: {message}")
        self._show_error("检查失败", message)

    def _on_finished(self, report: RunReport, manifest) -> None:
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self._verification_reasons = ()
        self._verification_current = True
        if self._recheck_issue is not None:
            self._finish_recheck(report, manifest)
            return
        self.report = report
        self.manifest = manifest
        self._load_feedback()
        self.report = self._apply_feedback_to_report(report)
        self._save_run()
        self._populate_table()
        self._update_status()
        self._set_status(
            f"检查结束：{report.state.value}；"
            f"{report.summary()['issue_count']} 个问题。"
        )

    def _save_run(self) -> None:
        if self.storage is None or self.report is None:
            return
        try:
            self.storage.reports.save(self.report, self.manifest)
        except (OSError, StorageError) as error:
            self._show_error(
                "报告保存失败",
                f"{error}\n结果仍保留在当前窗口中，可选择导出。",
            )
            return
        self._refresh_history_combo()
        dataset_root = self.host.inspection_dataset_root()
        output_dir = self.host.inspection_output_dir()
        profile = self._active_profile
        try:
            if profile is not None:
                self.storage.bindings.save(
                    dataset_root,
                    output_dir,
                    profile.profile_id,
                    profile.version,
                    profile.fingerprint(),
                )
            self._save_session()
        except (OSError, StorageError) as error:
            self._set_status(f"会话保存失败: {error}")

    def _apply_feedback_to_report(self, report: RunReport) -> RunReport:
        issues = []
        for issue in report.issues:
            record = self.feedback.get(issue.family_key)
            if record is None:
                issues.append(issue)
                continue
            if (
                record.evidence_digest
                and issue.location.snapshot_digest
                and record.evidence_digest != issue.location.snapshot_digest
            ):
                issues.append(
                    replace(
                        issue,
                        decision=record.decision,
                        action=record.action,
                        verification=VerificationState.STALE,
                    )
                )
            else:
                issues.append(
                    replace(
                        issue,
                        decision=record.decision,
                        action=record.action,
                        verification=record.verification,
                    )
                )
        return replace(report, issues=tuple(issues))

    def _apply_report_verification(self, report: RunReport) -> RunReport:
        current_profile = self._selected_profile()
        snapshot_profile = report.profile_snapshot.get("profile", {})
        if (
            current_profile is not None
            and isinstance(snapshot_profile, Mapping)
            and current_profile.profile_id
            == snapshot_profile.get("profile_id")
            and snapshot_profile.get("stage")
            and snapshot_profile.get("stage") != current_profile.stage
        ):
            current_profile = replace(
                current_profile, stage=snapshot_profile["stage"]
            )
        memory_files = {}
        memory_manifest = self.host.inspection_current_manifest()
        if memory_manifest is not None and memory_manifest.files:
            memory_file = memory_manifest.files[0]
            memory_files[memory_file.relative_path] = memory_file
        verification = verify_report_context(
            report,
            self.manifest,
            self.catalog,
            self.host.inspection_dataset_root(),
            self.host.inspection_output_dir(),
            current_profile,
            memory_files=memory_files,
        )
        self._verification_reasons = verification.reasons
        self._verification_current = verification.current
        stale_files = set(verification.stale_files)
        pending_files = set(verification.pending_files)
        global_stale = (
            verification.missing_manifest
            or verification.dataset_changed
            or verification.output_changed
            or verification.config_changed
        )
        issues = []
        for issue in report.issues:
            relative = issue.location.relative_path
            if global_stale or relative in stale_files:
                issues.append(
                    replace(
                        issue,
                        verification=VerificationState.STALE,
                    )
                )
            elif relative in pending_files:
                issues.append(
                    replace(
                        issue,
                        verification=VerificationState.PENDING_RECHECK,
                    )
                )
            else:
                issues.append(issue)
        return replace(report, issues=tuple(issues))

    def _populate_table(self) -> None:
        if self.report is None:
            self.issue_table.setRowCount(0)
            self._row_issues = []
            self.issue_stack.setCurrentIndex(1)
            self.issue_count_label.setText("")
            return
        selected = self._selected_issue()
        selected_key = selected.family_key if selected else ""
        filter_value = str(self.filter_combo.currentData())
        self.issue_table.setRowCount(0)
        self._row_issues = []
        for issue in self.report.issues:
            if not self._matches_filter(issue, filter_value):
                continue
            row = self.issue_table.rowCount()
            self.issue_table.insertRow(row)
            rule_names = "、".join(
                sorted({item.rule_name for item in issue.evidence})
            )
            object_text = (
                ", ".join(issue.location.object_ids)
                if issue.location.object_ids
                else (
                    "区域 "
                    + ", ".join(
                        f"{value:.1f}" for value in issue.location.region
                    )
                    if issue.location.region
                    else "图片"
                )
            )
            values = (
                self._severity_text(issue),
                rule_names,
                f"{issue.location.relative_path} · {object_text}",
                VERIFICATION_LABELS.get(
                    issue.verification, issue.verification.value
                ),
                DECISION_LABELS.get(issue.decision, issue.decision.value),
            )
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(str(value))
                if column == 2:
                    item.setToolTip(
                        "{}\n{}\n{}".format(
                            issue.location.relative_path,
                            object_text,
                            issue.message,
                        )
                    )
                else:
                    item.setToolTip(issue.message)
                if column == 0:
                    if issue.severity.value == "error":
                        item.setForeground(
                            QtGui.QBrush(QtGui.QColor(get_theme()["error"]))
                        )
                    elif issue.severity.value == "warning":
                        item.setForeground(
                            QtGui.QBrush(QtGui.QColor(get_theme()["warning"]))
                        )
                self.issue_table.setItem(row, column, item)
            self._row_issues.append(issue)
            if issue.family_key == selected_key:
                self.issue_table.selectRow(row)
        if not self._row_issues:
            self._show_details_placeholder()
        elif self.issue_table.currentRow() < 0:
            self.issue_table.selectRow(0)
        self.issue_stack.setCurrentIndex(0 if self._row_issues else 1)
        total = len(self.report.issues) if self.report is not None else 0
        self.issue_count_label.setText(
            self.tr("{shown} / {total} 条").format(
                shown=len(self._row_issues), total=total
            )
            if total
            else ""
        )
        self._update_action_buttons()

    def _matches_filter(self, issue: InspectionIssue, value: str) -> bool:
        if value == "all":
            return True
        if value == "pending":
            return issue.decision is Decision.PENDING
        if value == "handled":
            return issue.decision is not Decision.PENDING
        if value == "pending_recheck":
            return issue.verification is VerificationState.PENDING_RECHECK
        return issue.decision.value == value

    def _severity_text(self, issue: InspectionIssue) -> str:
        if issue.severity.value == "error":
            return "错误"
        if issue.severity.value == "warning":
            return "疑似"
        return "提示"

    def _selected_issue(self) -> Optional[InspectionIssue]:
        row = self.issue_table.currentRow()
        if row < 0 or row >= len(self._row_issues):
            return None
        return self._row_issues[row]

    def _selected_target_ids(
        self, issue: Optional[InspectionIssue]
    ) -> list[str]:
        if issue is None:
            return []
        selected_ids = {
            str(shape.xanylabeling_shape_id)
            for shape in self.host.canvas.selected_shapes
            if getattr(shape, "xanylabeling_shape_id", "") and not shape.locked
        }
        return [
            object_id
            for object_id in issue.location.object_ids
            if object_id in selected_ids
        ]

    def _update_action_buttons(self, *args) -> None:
        issue = self._selected_issue()
        target_ids = self._selected_target_ids(issue)
        self.delete_button.setEnabled(bool(target_ids))
        self.relabel_button.setEnabled(bool(target_ids))
        if target_ids:
            self.delete_button.setToolTip(
                "仅删除当前画布中选中的问题对象：" + ", ".join(target_ids)
            )
        else:
            self.delete_button.setToolTip("请先在画布中选中要删除的问题对象")

    def _selected_candidate(self) -> Optional[Candidate]:
        row = self.candidate_table.currentRow()
        if row < 0:
            return None
        item = self.candidate_table.item(row, 0)
        if item is None:
            return None
        candidate_id = str(item.data(QtCore.Qt.ItemDataRole.UserRole))
        return self._candidate_records.get(candidate_id)

    def _show_details_placeholder(self) -> None:
        self.details.setHtml(
            '<div style="color:#86868b;font-size:13px;'
            'line-height:1.7;padding:16px 4px;">'
            "选择左侧问题查看规则、证据与建议。<br/>"
            "双击问题行可直接定位到画布对象。</div>"
        )

    def _show_selected_details(self) -> None:
        issue = self._selected_issue()
        if issue is None:
            self._show_details_placeholder()
            self._update_action_buttons()
            return
        evidence_blocks = []
        for evidence in issue.evidence:
            metrics = " · ".join(
                f"{key}={value:.4f}" for key, value in evidence.metrics.items()
            )
            evidence_blocks.append(
                '<p style="margin:0 0 2px 0;"><b>{}</b></p>'
                '<p style="color:#86868b; margin:0 0 4px 0;">{}</p>'
                '<p style="color:#86868b; font-size:11px; '
                'margin:0 0 10px 0;">{}</p>'.format(
                    html.escape(evidence.rule_name),
                    html.escape(evidence.message),
                    html.escape(metrics),
                )
            )
        payload = handoff_payload(issue)
        notes = [
            "检查只读；定位/导航不会修改标签或审核状态。",
            "问题队列清空不能替代独立空间查漏。",
        ]
        if payload.get("available"):
            notes.append("可交接至密集复核工作区。")
        else:
            notes.append("密集复核不可用，请在普通画布处理。")
        region = (
            ", ".join(f"{value:.1f}" for value in issue.location.region)
            if issue.location.region
            else "无"
        )
        body = f"""
        <div style="font-size:13px; line-height:1.75;">
        <h3 style="margin:0 0 4px 0;">{html.escape(issue.title)}</h3>
        <p style="color:#86868b; margin:0 0 10px 0;">
        {html.escape(issue.message)}</p>
        <p style="margin:0 0 10px 0;">
        <b>文件</b> {html.escape(issue.location.relative_path)}<br/>
        <b>对象</b> {html.escape(", ".join(issue.location.object_ids) or "无")}<br/>
        <b>区域</b> {html.escape(region)}<br/>
        <b>建议</b> {html.escape(issue.suggested_action)}</p>
        <hr/>
        {''.join(evidence_blocks)}
        <hr/>
        <p style="margin:0 0 6px 0;">
        <b>人工判断</b> {DECISION_LABELS.get(issue.decision, issue.decision.value)}
        &nbsp; <b>动作</b> {ACTION_LABELS.get(issue.action, issue.action.value)}
        &nbsp; <b>机器</b> {VERIFICATION_LABELS.get(issue.verification, issue.verification.value)}</p>
        <p style="color:#86868b; margin:0;">{'<br/>'.join(html.escape(note) for note in notes)}</p>
        </div>
        """
        self.details.setHtml(body)
        self._update_action_buttons()

    def _locate_selected(self) -> None:
        issue = self._selected_issue()
        if issue is None:
            return
        ok = self.host.inspection_navigate_to(
            issue.location.relative_path,
            issue.location.object_ids,
            issue.location.region,
        )
        if not ok:
            self._set_status("无法定位对象；对象可能已删除或身份待重检。")

    def _set_decision(self, decision: Decision) -> None:
        issue = self._selected_issue()
        if issue is None or self.storage is None:
            return
        if issue.verification in (
            VerificationState.STALE,
            VerificationState.UNVERIFIABLE,
        ):
            self._show_error(
                "问题已过期",
                "当前输入或配置已变化，请先复查当前图或重新运行检查，"
                "再记录人工结论。",
            )
            return
        verification_state = (
            VerificationState.PENDING_RECHECK
            if issue.verification is VerificationState.PENDING_RECHECK
            else VerificationState.CURRENT
        )
        old = self.feedback.get(issue.family_key)
        history = list(old.history) if old else []
        history.append(
            {
                "at": QtCore.QDateTime.currentDateTime().toString(
                    QtCore.Qt.DateFormat.ISODate
                ),
                "decision": old.decision.value if old else "pending",
                "action": old.action.value if old else "unchanged",
                "verification": (old.verification.value if old else "current"),
            }
        )
        record = (
            replace(
                old,
                issue_id=issue.issue_id,
                decision=decision,
                verification=verification_state,
                evidence_digest=issue.location.snapshot_digest,
                updated_at=QtCore.QDateTime.currentDateTime().toString(
                    QtCore.Qt.DateFormat.ISODate
                ),
                history=tuple(history),
            )
            if old
            else replace(
                _new_feedback(issue, decision),
                verification=verification_state,
            )
        )
        if not self._save_feedback(record):
            return
        self._update_issue(issue.family_key, decision=decision)

    def _mark_modified(self) -> None:
        issue = self._selected_issue()
        if issue is None or self.storage is None:
            return
        old = self.feedback.get(issue.family_key)
        record = (
            replace(
                old,
                action=ActionState.MODIFIED,
                verification=VerificationState.PENDING_RECHECK,
                evidence_digest=issue.location.snapshot_digest,
            )
            if old
            else replace(
                _new_feedback(issue, issue.decision),
                action=ActionState.MODIFIED,
                verification=VerificationState.PENDING_RECHECK,
            )
        )
        if not self._save_feedback(record):
            return
        self._update_issue(
            issue.family_key,
            action=ActionState.MODIFIED,
            verification=VerificationState.PENDING_RECHECK,
        )

    def _save_feedback(self, record) -> bool:
        if self.storage is None:
            return False
        try:
            self.feedback_revision = self.storage.feedback.upsert(
                record, self.feedback_revision
            )
        except RevisionConflict as error:
            self._show_error(
                "反馈冲突",
                f"{error}\n冲突版本已保留：{error.conflict_path}",
            )
            self._load_feedback()
            return False
        except (OSError, StorageError) as error:
            self._show_error("反馈保存失败", str(error))
            return False
        self.feedback[record.family_key] = record
        return True

    def _update_issue(self, family_key: str, **changes) -> None:
        if self.report is None:
            return
        issues = []
        for issue in self.report.issues:
            if issue.family_key == family_key:
                issues.append(replace(issue, **changes))
            else:
                issues.append(issue)
        self.report = replace(self.report, issues=tuple(issues))
        self._populate_table()
        self._show_selected_details()
        self._update_status()
        self._save_session()

    def _recheck_selected(self) -> None:
        issue = self._selected_issue()
        if issue is None:
            return
        if self.controller.is_running():
            return
        manifest = self.host.inspection_current_manifest()
        if manifest is None:
            self._show_error("复查", "当前没有可复查的图片。")
            return
        if self._active_profile is None:
            self._show_error("复查", "没有可用的检查方案。")
            return
        self._recheck_issue = issue
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setRange(0, 0)
        self._set_status("复查当前图片")
        self.controller.start(
            self._active_profile,
            RunScope.CURRENT_IMAGE,
            dataset_root=self.host.inspection_dataset_root(),
            output_dir=self.host.inspection_output_dir(),
            manifest=manifest,
            allow_partial=False,
            generation=self._generation,
        )

    def _finish_recheck(self, report: RunReport, manifest) -> None:
        previous = self._recheck_issue
        self._recheck_issue = None
        if previous is None:
            return
        self._load_feedback()
        successful = self._coverage_successful(report, previous)
        current = next(
            (
                issue
                for issue in report.issues
                if issue.family_key == previous.family_key
            ),
            None,
        )
        old_record = self.feedback.get(previous.family_key)
        if current is None and successful:
            record = (
                replace(
                    old_record,
                    verification=VerificationState.NOT_DETECTED,
                )
                if old_record
                else replace(
                    _new_feedback(previous, previous.decision),
                    verification=VerificationState.NOT_DETECTED,
                )
            )
            self._save_feedback(record)
            appended = replace(
                previous,
                verification=VerificationState.NOT_DETECTED,
            )
            report = replace(report, issues=tuple(report.issues) + (appended,))
        elif current is not None:
            record = (
                replace(
                    old_record,
                    verification=VerificationState.CURRENT,
                    decision=Decision.PENDING,
                    evidence_digest=current.location.snapshot_digest,
                )
                if old_record
                else _new_feedback(current, Decision.PENDING)
            )
            self._save_feedback(record)
            report = replace(
                report,
                issues=tuple(
                    (
                        replace(
                            issue,
                            decision=Decision.PENDING,
                            verification=VerificationState.CURRENT,
                        )
                        if issue.family_key == current.family_key
                        else issue
                    )
                    for issue in report.issues
                ),
            )
        self.report = report
        self.manifest = manifest
        self._load_feedback()
        self.report = self._apply_feedback_to_report(report)
        self._save_run()
        self._populate_table()
        self._update_status()
        self._set_status("复查完成。")

    def _coverage_successful(
        self, report: RunReport, issue: InspectionIssue
    ) -> bool:
        if report.state not in (RunState.COMPLETED, RunState.PARTIAL):
            return False
        entries = [
            entry
            for entry in report.coverage
            if entry.relative_path == issue.location.relative_path
        ]
        if not entries:
            return False
        return all(
            entry.state.value in ("completed", "not_applicable")
            for entry in entries
        ) and not any(
            entry.state.value in ("failed", "cancelled", "not_run")
            for entry in entries
        )

    def _delete_selected(self) -> None:
        issue = self._selected_issue()
        target_ids = self._selected_target_ids(issue)
        if issue is None or not target_ids:
            self._show_error(
                "删除",
                "请先在画布中选中要删除的未锁定问题对象；"
                "不会自动删除整对对象。",
            )
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            "删除确认",
            "仅删除以下画布选中对象（共 {} 个）：\n{}\n\n"
            "未选中的对象会保留；此操作可通过撤销恢复。".format(
                len(target_ids), "\n".join(target_ids)
            ),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        ok, reason = self.host.inspection_delete_shapes(target_ids)
        if not ok:
            self._show_error("删除失败", reason)
            return
        old = self.feedback.get(issue.family_key)
        record = (
            replace(
                old,
                action=ActionState.DELETED,
                verification=VerificationState.PENDING_RECHECK,
            )
            if old
            else replace(
                _new_feedback(issue, Decision.CONFIRMED_ERROR),
                action=ActionState.DELETED,
                verification=VerificationState.PENDING_RECHECK,
            )
        )
        self._save_feedback(record)
        self._update_issue(
            issue.family_key,
            action=ActionState.DELETED,
            verification=VerificationState.PENDING_RECHECK,
        )

    def _relabel_selected(self) -> None:
        issue = self._selected_issue()
        target_ids = self._selected_target_ids(issue)
        if issue is None or not target_ids:
            self._show_error(
                "重标",
                "请先在画布中选中要重标的未锁定问题对象。",
            )
            return
        labels = []
        try:
            for index in range(self.host.unique_label_list.count()):
                labels.append(self.host.unique_label_list.item(index).label())
        except (AttributeError, RuntimeError):
            labels = []
        if labels:
            label, ok = QtWidgets.QInputDialog.getItem(
                self,
                "重标选中框",
                "目标类别：",
                labels,
                0,
                False,
            )
        else:
            label, ok = QtWidgets.QInputDialog.getText(
                self, "重标选中框", "目标类别："
            )
        if not ok or not label:
            return
        success, reason = self.host.inspection_relabel_shapes(
            target_ids, label
        )
        if not success:
            self._show_error("重标失败", reason)
            return
        old = self.feedback.get(issue.family_key)
        record = (
            replace(
                old,
                action=ActionState.RELABELED,
                verification=VerificationState.PENDING_RECHECK,
            )
            if old
            else replace(
                _new_feedback(issue, issue.decision),
                action=ActionState.RELABELED,
                verification=VerificationState.PENDING_RECHECK,
            )
        )
        self._save_feedback(record)
        self._update_issue(
            issue.family_key,
            action=ActionState.RELABELED,
            verification=VerificationState.PENDING_RECHECK,
        )

    def _update_status(self) -> None:
        if self.report is None:
            return
        checked = None
        try:
            checked = self.host._annotation_checked()
        except (AttributeError, RuntimeError):
            checked = None
        feedback = {
            key: value.to_dict() for key, value in self.feedback.items()
        }
        status = build_status(self.report, feedback, checked=checked)
        execution = status.execution
        self.execution_label.setText(
            self.tr("执行 {done}/{total}").format(
                done=execution.get("completed", 0),
                total=execution.get("requested", 0),
            )
        )
        self.execution_label.setToolTip(
            self.tr(
                "状态 {state}；失败 {failed}；未执行 {not_run}；来源 {source}"
            ).format(
                state=execution.get("state", ""),
                failed=execution.get("failed", 0),
                not_run=execution.get("not_run", 0),
                source=(
                    "内存" if self.report.source_kind == "memory" else "磁盘"
                ),
            )
        )
        handling = status.issue_handling
        summary = self.report.summary()
        self.issue_handling_label.setText(
            self.tr("问题 {done}/{total}").format(
                done=handling.get("handled", 0),
                total=handling.get("total", 0),
            )
        )
        self.issue_handling_label.setToolTip(
            self.tr(
                "对象 {objects}；图片 {files}；未处理 {pending}；已处理 "
                "{handled}；过期 {stale}"
            ).format(
                objects=summary.get("object_count", 0),
                files=summary.get("requested_files", 0),
                pending=handling.get("pending", 0),
                handled=handling.get("handled", 0),
                stale=handling.get("stale", 0),
            )
        )
        self.object_review_label.setText(
            self.tr("对象 {word}").format(
                word=_state_word(status.object_review)
            )
        )
        self.object_review_label.setToolTip(
            str(status.object_review.get("label", ""))
        )
        self.spatial_label.setText(
            self.tr("空间 {word}").format(
                word=_state_word(status.spatial_omission)
            )
        )
        self.spatial_label.setToolTip(
            str(status.spatial_omission.get("label", ""))
        )
        self.formal_label.setText(
            self.tr("正式 {word}").format(
                word=_state_word(status.formal_acceptance)
            )
        )
        self.formal_label.setToolTip(
            str(status.formal_acceptance.get("label", ""))
        )
        notes = list(status.notes)
        if self._verification_reasons:
            notes.append(
                "历史报告核验：" + "；".join(self._verification_reasons[:5])
            )
        self.note_label.setText(" ".join(notes))

    def _toggle_notes(self) -> None:
        self._notes_visible = not self._notes_visible
        self.note_label.setVisible(self._notes_visible)
        self.info_frame.setVisible(self._notes_visible)
        self.note_toggle_button.setText(
            self.tr("收起说明") if self._notes_visible else self.tr("说明")
        )

    def _import_issues(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "导入旧问题",
            self.host.inspection_dataset_root(),
            "问题文件 (*.tsv *.csv *.json);;所有文件 (*)",
        )
        if not path:
            return
        try:
            result = import_legacy_report(path, manifest=self.manifest)
        except (OSError, ValueError) as error:
            self._show_error("导入失败", str(error))
            return
        if self.report is not None and result.issues:
            known = {issue.issue_id for issue in self.report.issues}
            additions = tuple(
                issue for issue in result.issues if issue.issue_id not in known
            )
            self.report = replace(
                self.report, issues=tuple(self.report.issues) + additions
            )
            self._populate_table()
            self._update_status()
        summary = [
            f"导入 {len(result.issues)} 条",
            f"错误 {len(result.errors)} 条",
            f"歧义 {len(result.ambiguous)} 条",
        ]
        QtWidgets.QMessageBox.information(
            self, "导入旧问题", "\n".join(summary)
        )

    def _export_report(self) -> None:
        if self.report is None:
            self._show_error("导出", "当前没有可导出的报告。")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "导出检查报告",
            osp.join(
                self.host.inspection_output_dir()
                or self.host.inspection_dataset_root(),
                f"inspection-{self.report.run_id}.json",
            ),
            "JSON (*.json)",
        )
        if not path:
            return
        tsv_path = osp.splitext(path)[0] + ".tsv"
        try:
            export_report(self.report, path, tsv_path)
        except OSError as error:
            self._show_error("导出失败", str(error))
            return
        self._set_status(f"已导出：{path} 与 {tsv_path}（TSV 为简化格式）")

    def _import_candidates(self) -> None:
        if not self._ensure_storage() or self.storage is None:
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "导入外部候选",
            self.host.inspection_dataset_root(),
            "JSON (*.json);;所有文件 (*)",
        )
        if not path:
            return
        try:
            allowed = set(self.host.label_info.keys())
            result = load_candidates(
                path,
                manifest=self.manifest,
                allowed_labels=allowed or None,
            )
        except (OSError, ValueError) as error:
            self._show_error("候选导入失败", str(error))
            return
        self._load_candidates()
        records = dict(self._candidate_records)
        for candidate in result.candidates:
            records[candidate.candidate_id] = candidate
        try:
            self._candidate_revision = self._candidate_store.save(
                records, self._candidate_revision
            )
        except (OSError, StorageError) as error:
            self._show_error("候选保存失败", str(error))
            return
        self._candidate_records = records
        self._populate_candidate_table()
        QtWidgets.QMessageBox.information(
            self,
            "候选导入",
            "导入 {} 条，拒绝 {} 条，歧义 {} 条。".format(
                len(result.candidates),
                len(result.errors),
                len(result.ambiguous),
            ),
        )

    def _populate_candidate_table(self) -> None:
        self.candidate_table.setRowCount(0)
        for candidate in sorted(
            self._candidate_records.values(),
            key=lambda item: (item.relative_path, item.candidate_id),
        ):
            row = self.candidate_table.rowCount()
            self.candidate_table.insertRow(row)
            region_text = (
                ", ".join(f"{value:.1f}" for value in candidate.region) or "-"
            )
            score_text = (
                "" if candidate.score is None else f"{candidate.score:.3f}"
            )
            values = (
                candidate.status.value,
                candidate.label,
                f"{candidate.relative_path} · {region_text}",
                f"{candidate.source} {score_text}".strip(),
            )
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(str(value))
                item.setToolTip(
                    "{}\n{}\n{}".format(
                        candidate.relative_path,
                        region_text,
                        candidate.candidate_id,
                    )
                )
                if column == 0:
                    item.setData(
                        QtCore.Qt.ItemDataRole.UserRole,
                        candidate.candidate_id,
                    )
                self.candidate_table.setItem(row, column, item)

    def _accept_candidate(self) -> None:
        candidate = self._selected_candidate()
        if candidate is None or self.storage is None:
            return
        if candidate.status is CandidateStatus.ACCEPTED:
            self._show_error("候选", "该候选已接受，不能重复新增。")
            return
        if self._candidate_store is None or self._intent_store is None:
            self._load_candidates()
        if self._candidate_store is None or self._intent_store is None:
            self._show_error("候选", "候选存储不可用。")
            return
        shape_id = new_shape_id()
        try:
            self._intent_store.create(
                candidate.candidate_id,
                candidate.relative_path,
                shape_id,
            )
        except AlreadyAccepted as error:
            self._show_error("候选", str(error))
            return
        ok, payload = self.host.inspection_accept_candidate(
            candidate, shape_id
        )
        if not ok:
            self._intent_store.abandon(candidate.candidate_id)
            self._show_error("接受候选失败", str(payload))
            return
        self._intent_store.confirm(candidate.candidate_id)
        self._candidate_store.mark(
            candidate,
            CandidateStatus.ACCEPTED,
            accepted_shape_id=payload,
        )
        self._load_candidates()
        self._set_status(f"已接受候选并新增对象 {payload}。")

    def _set_candidate_status(self, status: CandidateStatus) -> None:
        candidate = self._selected_candidate()
        if candidate is None or self._candidate_store is None:
            return
        try:
            self._candidate_store.mark(candidate, status)
        except (OSError, StorageError) as error:
            self._show_error("候选状态保存失败", str(error))
            return
        self._load_candidates()

    def _save_session(self) -> None:
        if self.storage is None or self.report is None:
            return
        issue = self._selected_issue()
        session = self._session
        if session is None or session.report_id != self.report.run_id:
            from anylabeling.services.inspection.models import ReviewSession

            session = ReviewSession(
                report_id=self.report.run_id,
                dataset_root=self.host.inspection_dataset_root(),
                output_root=self.host.inspection_output_dir(),
            )
        cursor = {
            "issue_id": issue.issue_id if issue else "",
            "family_key": issue.family_key if issue else "",
        }
        try:
            self._session = self.storage.sessions.save(
                replace(
                    session,
                    dataset_root=self.host.inspection_dataset_root(),
                    output_root=self.host.inspection_output_dir(),
                    cursor=cursor,
                    filters={"queue": str(self.filter_combo.currentData())},
                ),
                session.revision,
            )
        except RevisionConflict:
            self._load_session()
        except (OSError, StorageError) as error:
            self._set_status(f"会话保存失败: {error}")

    def _load_session(self) -> None:
        if self.storage is None:
            return
        try:
            self._session = self.storage.sessions.load()
        except (OSError, StorageError):
            self._session = None

    def _refresh_history_combo(self) -> None:
        if self.storage is None:
            return
        current = self.history_combo.currentData()
        entries = self.storage.reports.list_reports()
        self.history_combo.blockSignals(True)
        self.history_combo.clear()
        self.history_combo.setEnabled(bool(entries))
        self.load_history_button.setEnabled(bool(entries))
        if not entries:
            self.history_combo.addItem(self.tr("暂无运行记录"), "")
            self.history_combo.blockSignals(False)
            return
        for entry in entries[:20]:
            started = str(entry.get("started_at", ""))
            stamp = started.replace("T", " ")[5:16] or started
            label = self.tr("{stamp} · {count} 问题").format(
                stamp=stamp, count=entry.get("issue_count", 0)
            )
            self.history_combo.addItem(label, entry.get("run_id", ""))
            index = self.history_combo.count() - 1
            self.history_combo.setItemData(
                index,
                "{} · {}".format(started, entry.get("state", "")),
                QtCore.Qt.ItemDataRole.ToolTipRole,
            )
        if current:
            index = self.history_combo.findData(current)
            if index >= 0:
                self.history_combo.setCurrentIndex(index)
        self.history_combo.blockSignals(False)

    def _load_selected_history(self) -> None:
        run_id = str(self.history_combo.currentData() or "")
        if not run_id:
            return
        self._load_report(run_id)

    def _resume_last(self) -> None:
        if not self._ensure_storage() or self.storage is None:
            return
        entries = self.storage.reports.list_reports()
        if not entries:
            self._show_error("继续处理", "没有可恢复的检查报告。")
            return
        self._load_report(str(entries[0].get("run_id", "")))

    def _load_report(self, run_id: str) -> None:
        if not run_id or self.storage is None:
            return
        try:
            report = self.storage.reports.load(run_id)
        except (OSError, StorageError) as error:
            self._show_error("恢复失败", str(error))
            return
        try:
            self.manifest = self.storage.reports.load_manifest(run_id)
        except (OSError, StorageError):
            self.manifest = None
        self._load_feedback()
        self._load_candidates()
        self._load_session()
        self.report = self._apply_feedback_to_report(report)
        self._show_report_profile(report)
        self.report = self._apply_report_verification(self.report)
        if self._session is not None:
            queue_filter = str(
                (self._session.filters or {}).get("queue", "all")
            )
            index = self.filter_combo.findData(queue_filter)
            if index >= 0:
                self.filter_combo.setCurrentIndex(index)
        self._populate_table()
        if self._session is not None:
            family_key = str(
                (self._session.cursor or {}).get("family_key", "")
            )
            for row, issue in enumerate(self._row_issues):
                if issue.family_key == family_key:
                    self.issue_table.selectRow(row)
                    break
        self._update_status()
        stale = sum(
            1
            for issue in self.report.issues
            if issue.verification is VerificationState.STALE
        )
        if stale:
            self._set_status(
                f"已恢复报告 {run_id}；{stale} 项因数据或配置变化过期，"
                "需重新检查。"
            )
        else:
            self._set_status(f"已恢复报告 {run_id}。")

    def _show_report_profile(self, report: RunReport) -> None:
        profile = report.profile_snapshot.get("profile", {})
        if not isinstance(profile, Mapping):
            return
        profile_id = str(profile.get("profile_id", ""))
        if profile_id in self._profiles:
            index = self.profile_combo.findData(profile_id)
            if index >= 0:
                self.profile_combo.setCurrentIndex(index)
        snapshot_rules = report.profile_snapshot.get("rules", [])
        names = [
            str(rule.get("rule_name", rule.get("rule_id", "")))
            for rule in snapshot_rules
            if isinstance(rule, Mapping) and rule.get("enabled", True)
        ]
        self.profile_summary.setText(
            "历史方案：{} v{}；配置摘要 {}".format(
                profile.get("name", profile_id),
                profile.get("profile_version", "?"),
                report.profile_snapshot.get("snapshot_digest", "")[:12],
            )
        )
        self.rule_summary.setText("、".join(names))

    def _show_error(self, title: str, message: str) -> None:
        QtWidgets.QMessageBox.critical(self, title, message)

    def _set_status(self, message: str) -> None:
        self.status_label.setText(str(message))

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self.controller.is_running():
            answer = QtWidgets.QMessageBox.question(
                self,
                "检查仍在运行",
                "取消当前检查并关闭 Inspector？",
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
            )
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.controller.cancel()
        super().closeEvent(event)


def _new_feedback(issue: InspectionIssue, decision: Decision):
    from anylabeling.services.inspection.models import FeedbackRecord

    return FeedbackRecord(
        family_key=issue.family_key,
        issue_id=issue.issue_id,
        decision=decision,
        verification=VerificationState.CURRENT,
        evidence_digest=issue.location.snapshot_digest,
        updated_at=QtCore.QDateTime.currentDateTime().toString(
            QtCore.Qt.DateFormat.ISODate
        ),
    )
