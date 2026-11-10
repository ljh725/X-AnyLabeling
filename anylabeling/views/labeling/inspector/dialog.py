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
    FeedbackRecord,
    InspectionIssue,
    InspectionProfile,
    RunReport,
    RunScope,
    RunState,
    VerificationState,
    dataset_identity,
    output_identity,
)
from anylabeling.services.inspection.profiles import (
    build_default_catalog,
    copy_builtin,
    default_profiles,
    load_profile,
    save_profile,
    validate_profile,
)
from anylabeling.services.inspection.review_queue import (
    action_target_problem,
    apply_feedback,
    invalidate_file_edits,
    merge_recheck_report,
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
from anylabeling.views.labeling.utils.qt import themed_icon
from anylabeling.views.labeling.utils.theme import get_theme

from .controller import InspectionController

DIALOG_CONTEXT = "InspectorDialog"


def _translate_label(text: str) -> str:
    """Translate a module-level label through the dialog context."""
    return QtCore.QCoreApplication.translate(DIALOG_CONTEXT, text)


STAGE_LABELS = {
    "pre_label": QtCore.QT_TRANSLATE_NOOP(DIALOG_CONTEXT, "预标注清洗"),
    "in_progress": QtCore.QT_TRANSLATE_NOOP(DIALOG_CONTEXT, "标注中"),
    "post_label": QtCore.QT_TRANSLATE_NOOP(DIALOG_CONTEXT, "完成后检查"),
}

SCOPE_LABELS = {
    RunScope.CURRENT_IMAGE: QtCore.QT_TRANSLATE_NOOP(
        DIALOG_CONTEXT, "当前图片"
    ),
    RunScope.SELECTED_FILES: QtCore.QT_TRANSLATE_NOOP(
        DIALOG_CONTEXT, "选定文件"
    ),
    RunScope.DATASET: QtCore.QT_TRANSLATE_NOOP(DIALOG_CONTEXT, "当前数据集"),
    RunScope.CHANGED_FILES: QtCore.QT_TRANSLATE_NOOP(
        DIALOG_CONTEXT, "已变更文件（保守全量）"
    ),
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
    "available": QtCore.QT_TRANSLATE_NOOP(DIALOG_CONTEXT, "可用"),
    "passed": QtCore.QT_TRANSLATE_NOOP(DIALOG_CONTEXT, "通过"),
    "failed": QtCore.QT_TRANSLATE_NOOP(DIALOG_CONTEXT, "未通过"),
    "unchanged": QtCore.QT_TRANSLATE_NOOP(DIALOG_CONTEXT, "未改变"),
}


def _state_word(payload) -> str:
    state = str(payload.get("state", ""))
    label = _STATUS_WORDS.get(
        state, str(payload.get("label", state) or "未知")
    )
    return _translate_label(label)


DECISION_LABELS = {
    Decision.PENDING: QtCore.QT_TRANSLATE_NOOP(DIALOG_CONTEXT, "待处理"),
    Decision.CONFIRMED_ERROR: QtCore.QT_TRANSLATE_NOOP(
        DIALOG_CONTEXT, "确认错误"
    ),
    Decision.FALSE_POSITIVE: QtCore.QT_TRANSLATE_NOOP(DIALOG_CONTEXT, "误报"),
    Decision.ACCEPTABLE: QtCore.QT_TRANSLATE_NOOP(DIALOG_CONTEXT, "可接受"),
    Decision.NEEDS_DISCUSSION: QtCore.QT_TRANSLATE_NOOP(
        DIALOG_CONTEXT, "需讨论"
    ),
}

VERIFICATION_LABELS = {
    VerificationState.CURRENT: QtCore.QT_TRANSLATE_NOOP(
        DIALOG_CONTEXT, "当前"
    ),
    VerificationState.STALE: QtCore.QT_TRANSLATE_NOOP(
        DIALOG_CONTEXT, "已过期"
    ),
    VerificationState.PENDING_RECHECK: QtCore.QT_TRANSLATE_NOOP(
        DIALOG_CONTEXT, "待复查"
    ),
    VerificationState.NOT_DETECTED: QtCore.QT_TRANSLATE_NOOP(
        DIALOG_CONTEXT, "成功复查未再检出"
    ),
    VerificationState.UNVERIFIABLE: QtCore.QT_TRANSLATE_NOOP(
        DIALOG_CONTEXT, "无法核验"
    ),
}

ACTION_LABELS = {
    ActionState.UNCHANGED: QtCore.QT_TRANSLATE_NOOP(DIALOG_CONTEXT, "未改"),
    ActionState.MODIFIED: QtCore.QT_TRANSLATE_NOOP(DIALOG_CONTEXT, "已修改"),
    ActionState.DELETED: QtCore.QT_TRANSLATE_NOOP(DIALOG_CONTEXT, "已删除"),
    ActionState.RELABELED: QtCore.QT_TRANSLATE_NOOP(DIALOG_CONTEXT, "已重标"),
    ActionState.ADDED: QtCore.QT_TRANSLATE_NOOP(DIALOG_CONTEXT, "已新增"),
}


CANDIDATE_STATUS_LABELS = {
    CandidateStatus.PENDING: QtCore.QT_TRANSLATE_NOOP(
        DIALOG_CONTEXT, "待处理"
    ),
    CandidateStatus.ACCEPTED: QtCore.QT_TRANSLATE_NOOP(
        DIALOG_CONTEXT, "已接受"
    ),
    CandidateStatus.REJECTED: QtCore.QT_TRANSLATE_NOOP(
        DIALOG_CONTEXT, "已拒绝"
    ),
    CandidateStatus.DEFERRED: QtCore.QT_TRANSLATE_NOOP(
        DIALOG_CONTEXT, "已暂存"
    ),
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
        self._frozen_profile_id = ""
        self._recheck_issue: Optional[InspectionIssue] = None
        self._session = None
        self._binding_key: Optional[tuple[str, str]] = None
        self._user_selected_profile = False
        self._verification_reasons: tuple[str, ...] = ()
        self._verification_current = True
        self._notes_visible = False
        self._run_context = None
        self._run_token = ""
        self._edit_serial = 0
        self._run_edit_serial = 0
        self._session_dirty = False
        self._run_notes: tuple[str, ...] = ()
        self._pending_feedback: dict[str, FeedbackRecord] = {}
        self._recheck_relative_path = ""
        self._disabled_profiles: set[str] = set()
        self._duplicate_tracker = None
        self._handoff_family_key = ""
        self._active_issue_key = ""
        self._navigation_order = []
        self._navigating = False
        self._navigation_serial = 0
        self._session_open = False
        self._save_recheck_context = None
        self._click_timer = QtCore.QElapsedTimer()
        self._click_key = ""
        self._issue_page = 0
        self._issue_page_size = 200
        self.setObjectName("annotationInspector")
        self._build_ui()
        self.setStyleSheet(get_dialog_style() + get_workbench_qss())
        self._connect()
        self._install_shortcuts()
        self._apply_icons()
        self._load_builtin_profiles()
        self._set_status(self.tr("请选择方案和范围后开始检查。"))
        self._show_details_placeholder()
        for label, text in (
            (self.execution_label, self.tr("执行 -")),
            (self.issue_handling_label, self.tr("问题 -")),
            (self.object_review_label, self.tr("对象 -")),
            (self.spatial_label, self.tr("空间 -")),
            (self.formal_label, self.tr("正式 -")),
        ):
            label.setText(self.tr(text))
        self.setWindowTitle(self.tr("Annotation Inspector"))
        self.resize(1200, 820)
        # A small window must still show the toolbar and actions instead of
        # clipping Chinese labels; the splitter keeps both panels usable.
        self.setMinimumSize(880, 560)
        self.setWindowModality(QtCore.Qt.WindowModality.NonModal)
        self._restore_window_preferences()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(10)

        toolbar = QtWidgets.QFrame(self)
        toolbar.setObjectName("workbenchToolbar")
        toolbar_rows = QtWidgets.QVBoxLayout(toolbar)
        toolbar_rows.setContentsMargins(10, 8, 10, 8)
        toolbar_rows.setSpacing(6)
        toolbar_layout = QtWidgets.QHBoxLayout()
        toolbar_rows.addLayout(toolbar_layout)
        toolbar_layout.setSpacing(8)

        self.profile_combo = QtWidgets.QComboBox()
        self.profile_combo.setMinimumWidth(190)
        self.profile_combo.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.stage_combo = QtWidgets.QComboBox()
        for value, label in STAGE_LABELS.items():
            self.stage_combo.addItem(_translate_label(label), value)
        self.stage_combo.setMinimumWidth(118)
        self.scope_combo = QtWidgets.QComboBox()
        for value, label in SCOPE_LABELS.items():
            self.scope_combo.addItem(_translate_label(label), value.value)
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
            if combo is self.stage_combo:
                caption.hide()
                combo.hide()

        toolbar_layout = QtWidgets.QHBoxLayout()
        toolbar_layout.setSpacing(8)
        toolbar_rows.addLayout(toolbar_layout)
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
        self.rename_profile_button = _variant_button(self.tr("改名"))
        self.edit_profile_button = _variant_button(self.tr("编辑规则"))
        self.toggle_profile_button = _variant_button(self.tr("停用方案"))
        self.import_profile_button = _variant_button(self.tr("导入方案"))
        self.export_profile_button = _variant_button(self.tr("导出方案"))
        self.import_issues_button = _variant_button(self.tr("导入旧问题"))
        self.export_button = _variant_button(self.tr("导出报告"))
        menu = QtWidgets.QMenu(self.more_button)
        for button in (
            self.resume_button,
            self.copy_profile_button,
            self.rename_profile_button,
            self.edit_profile_button,
            self.toggle_profile_button,
            self.import_profile_button,
            self.export_profile_button,
            self.import_issues_button,
            self.export_button,
        ):
            button.setVisible(False)
            button.setParent(self)
        menu.addAction(self.tr("继续上次处理"), self.resume_button.click)
        menu.addAction(self.tr("复制方案"), self.copy_profile_button.click)
        menu.addAction(self.tr("改名"), self.rename_profile_button.click)
        menu.addAction(self.tr("编辑规则"), self.edit_profile_button.click)
        menu.addAction(
            self.tr("停用/启用方案"), self.toggle_profile_button.click
        )
        menu.addAction(self.tr("导入方案"), self.import_profile_button.click)
        menu.addAction(self.tr("导出方案"), self.export_profile_button.click)
        menu.addSeparator()
        menu.addAction(self.tr("导入旧问题"), self.import_issues_button.click)
        menu.addAction(self.tr("导出报告"), self.export_button.click)
        menu.addAction(self.tr("重试保存检查记录"), self._retry_records)
        stage_action = QtWidgets.QWidgetAction(menu)
        stage_action.setDefaultWidget(self.stage_combo)
        menu.addAction(stage_action)
        self.stage_combo.show()
        history_panel = QtWidgets.QWidget()
        history_layout = QtWidgets.QHBoxLayout(history_panel)
        history_layout.addWidget(self.history_combo)
        history_layout.addWidget(self.load_history_button)
        history_action = QtWidgets.QWidgetAction(menu)
        history_action.setDefaultWidget(history_panel)
        menu.addAction(history_action)
        self.more_button.setMenu(menu)
        toolbar_layout.addWidget(self.more_button)
        toolbar_layout.addStretch(1)

        self.cancel_button = _variant_button(self.tr("取消"))
        self.cancel_button.setEnabled(False)
        self.start_button = _variant_button(self.tr("开始检查"), "primary")
        self.start_button.setToolTip(self.tr("开始检查（F5）"))
        self.shortcut_hint = QtWidgets.QLabel(
            self.tr("F5 开始检查 · Enter 定位选中问题")
        )
        self.shortcut_hint.setObjectName("fieldLabel")
        self.shortcut_hint.setMinimumWidth(0)
        self.shortcut_hint.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        self.shortcut_hint.setToolTip(
            self.tr(
                "这两个快捷键只在 Inspector 窗口内生效，不占用画布编辑键。"
            )
        )
        toolbar_layout.addWidget(self.shortcut_hint)
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
        self.progress.setTextVisible(True)
        self.progress.setFormat("%p%")
        self.progress.setFixedSize(200, 22)
        self.progress.setStyleSheet(
            "QProgressBar { min-height: 22px; max-height: 22px; "
            "text-align: center; }"
        )
        self.status_label = QtWidgets.QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumWidth(0)
        self.status_label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
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
        rule_actions = QtWidgets.QHBoxLayout()
        self.view_rules_button = _variant_button(self.tr("查看规则与参数"))
        self.view_rules_button.clicked.connect(self._view_rules)
        toolbar_layout.insertWidget(1, self.view_rules_button)
        for button in (self.copy_profile_button, self.edit_profile_button):
            rule_actions.addWidget(button)
            button.setVisible(False)
        rule_actions.addStretch(1)
        info_layout.addLayout(rule_actions)
        self.info_frame.setVisible(False)
        layout.addWidget(self.info_frame)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)

        queue_panel = QtWidgets.QWidget()
        queue_layout = QtWidgets.QVBoxLayout(queue_panel)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        queue_layout.setSpacing(6)

        filter_row = QtWidgets.QHBoxLayout()
        filter_row.setSpacing(6)
        self.filter_combo = QtWidgets.QComboBox()
        self.filter_combo.addItem(self.tr("待处理"), "review_pending")
        self.filter_combo.addItem(self.tr("已解决"), "review_resolved")
        self.filter_combo.addItem(self.tr("已忽略"), "review_ignored")
        self.filter_combo.addItem(self.tr("全部"), "all")
        self.filter_combo.addItem(self.tr("待处理"), "pending")
        self.filter_combo.addItem(self.tr("已处理"), "handled")
        self.filter_combo.addItem(self.tr("待复查"), "pending_recheck")
        self.filter_combo.addItem(self.tr("误报"), "false_positive")
        self.filter_combo.addItem(self.tr("可接受"), "acceptable")
        self.filter_combo.addItem(self.tr("需讨论"), "needs_discussion")
        self.filter_combo.addItem(self.tr("确认错误"), "confirmed_error")
        self.filter_combo.addItem(self.tr("未再检出"), "not_detected")
        self.rule_filter_combo = QtWidgets.QComboBox()
        self.rule_filter_combo.addItem(self.tr("全部规则"), "")
        self.rule_filter_combo.setMinimumWidth(120)
        self.source_filter_combo = QtWidgets.QComboBox()
        self.source_filter_combo.addItem(self.tr("全部来源"), "")
        self.source_filter_combo.setMinimumWidth(110)
        self.risk_filter_combo = QtWidgets.QComboBox()
        self.risk_filter_combo.addItem(self.tr("全部风险"), "")
        self.risk_filter_combo.addItem(self.tr("错误"), "error")
        self.risk_filter_combo.addItem(self.tr("疑似"), "warning")
        self.risk_filter_combo.addItem(self.tr("提示"), "info")
        self.issue_count_label = QtWidgets.QLabel()
        self.issue_count_label.setObjectName("fieldLabel")
        self.prev_issue_button = _variant_button(self.tr("上一个"), "quiet")
        self.next_issue_button = _variant_button(self.tr("下一个"), "quiet")
        for widget in (
            self.filter_combo,
            self.rule_filter_combo,
            self.source_filter_combo,
            self.risk_filter_combo,
        ):
            filter_row.addWidget(widget)
        filter_row.addWidget(self.issue_count_label)
        filter_row.addStretch(1)
        queue_layout.addLayout(filter_row)
        page_row = QtWidgets.QHBoxLayout()
        self.prev_page_button = _variant_button(self.tr("上一页"), "quiet")
        self.next_page_button = _variant_button(self.tr("下一页"), "quiet")
        self.page_label = QtWidgets.QLabel()
        page_row.addWidget(self.prev_page_button)
        page_row.addWidget(self.page_label)
        page_row.addWidget(self.next_page_button)
        page_row.addStretch(1)
        self.save_report_button = _variant_button(self.tr("另存检查报告"))
        page_row.addWidget(self.save_report_button)
        self.open_report_location_button = _variant_button(
            self.tr("打开报告保存位置")
        )
        page_row.addWidget(self.open_report_location_button)
        self.save_report_button.hide()
        self.open_report_location_button.hide()
        menu.addAction(self.tr("另存检查报告"), self.save_report_button.click)
        menu.addAction(
            self.tr("打开报告保存位置"), self.open_report_location_button.click
        )
        queue_layout.addLayout(page_row)

        self.issue_stack = QtWidgets.QStackedWidget()
        self.issue_table = QtWidgets.QTableWidget(0, 5)
        self.issue_table.setToolTip(self.tr("双击或按 Enter 定位到画布对象"))
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
        for column in (3, 4):
            self.issue_table.setColumnHidden(column, True)

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
        navigation_row = QtWidgets.QHBoxLayout()
        navigation_row.addWidget(self.prev_issue_button)
        navigation_row.addWidget(self.next_issue_button)
        queue_layout.addLayout(navigation_row)
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
        self.keep_both_button = _variant_button(self.tr("保留两者"))
        self.defer_button = _variant_button(self.tr("疑难暂存"))
        self.recheck_button = _variant_button(self.tr("复查当前图"))
        self.handoff_button = _variant_button(self.tr("交接密集复核"))
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
        self.batch_delete_button = _variant_button(self.tr("批量删除问题框"))
        self.batch_delete_button.setProperty("variant", "danger")
        self.batch_relabel_button = _variant_button(self.tr("按类别批量重标"))
        self.undo_button = _variant_button(self.tr("撤销上次修改"), "quiet")
        actions = (
            self.locate_button,
            self.false_positive_button,
            self.acceptable_button,
            self.discussion_button,
            self.confirmed_button,
            self.modified_button,
            self.keep_both_button,
            self.defer_button,
            self.recheck_button,
            self.handoff_button,
            self.delete_button,
            self.relabel_button,
            self.batch_delete_button,
            self.batch_relabel_button,
            self.undo_button,
        )
        self.acceptable_button.setText(self.tr("忽略此问题"))
        self.save_recheck_button = _variant_button(
            self.tr("保存并复查"), "primary"
        )
        self.save_recheck_button.clicked.connect(self._save_and_recheck)
        self.auto_advance = QtWidgets.QCheckBox(
            self.tr("通过后进入下一个问题")
        )
        self.auto_advance.setChecked(
            bool(self.host._config.get("inspector_auto_advance", True))
        )
        self.auto_advance.toggled.connect(self._save_window_preferences)
        self.object_combo = QtWidgets.QComboBox()
        self.object_combo.activated.connect(self._select_problem_object)
        detail_page_layout.addWidget(self.object_combo)
        action_grid.addWidget(self.acceptable_button, 0, 0)
        action_grid.addWidget(self.save_recheck_button, 0, 1)
        detail_page_layout.addWidget(self.auto_advance)
        self.advanced_actions = QtWidgets.QWidget()
        advanced_layout = QtWidgets.QGridLayout(self.advanced_actions)
        for index, button in enumerate(
            b for b in actions if b is not self.acceptable_button
        ):
            advanced_layout.addWidget(button, index // 3, index % 3)
        self.advanced_actions.hide()
        detail_page_layout.addWidget(self.advanced_actions)
        advanced_action = menu.addAction(self.tr("详细处理操作"))
        advanced_action.setCheckable(True)
        advanced_action.toggled.connect(self.advanced_actions.setVisible)
        advanced_action.toggled.connect(self.info_frame.setVisible)
        for combo in (self.source_filter_combo, self.risk_filter_combo):
            combo.hide()
            advanced_action.toggled.connect(combo.setVisible)
        advanced_action.toggled.connect(
            lambda _: self._show_selected_details()
        )
        advanced_action.toggled.connect(
            lambda shown: self.issue_table.setColumnHidden(3, not shown)
        )
        advanced_action.toggled.connect(
            lambda shown: self.issue_table.setColumnHidden(4, not shown)
        )
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
        self.accept_adjusted_button = _variant_button(self.tr("调整后接受"))
        self.batch_accept_button = _variant_button(self.tr("批量接受"))
        self.reject_candidate_button = _variant_button(self.tr("拒绝"))
        self.defer_candidate_button = _variant_button(self.tr("暂存"))
        candidate_buttons.addWidget(self.import_candidates_button)
        candidate_buttons.addWidget(self.accept_candidate_button)
        candidate_buttons.addWidget(self.accept_adjusted_button)
        candidate_buttons.addWidget(self.batch_accept_button)
        candidate_buttons.addWidget(self.reject_candidate_button)
        candidate_buttons.addWidget(self.defer_candidate_button)
        candidate_buttons.addStretch(1)
        candidate_layout.addWidget(self.candidate_table, 1)
        candidate_layout.addLayout(candidate_buttons)
        self.detail_tabs.addTab(candidate_panel, self.tr("外部候选"))
        self.detail_tabs.setTabVisible(1, False)
        candidate_action = menu.addAction(self.tr("外部候选"))
        candidate_action.setCheckable(True)
        candidate_action.toggled.connect(
            lambda shown: self.detail_tabs.setTabVisible(1, shown)
        )

        detail_layout.addWidget(self.detail_tabs, 1)
        splitter.addWidget(detail_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([400, 180])
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
        for chip in (
            self.execution_label,
            self.issue_handling_label,
            self.object_review_label,
            self.spatial_label,
            self.formal_label,
        ):
            chip.hide()
            advanced_action.toggled.connect(chip.setVisible)
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
        self.rename_profile_button.clicked.connect(self._rename_profile)
        self.edit_profile_button.clicked.connect(self._edit_profile)
        self.toggle_profile_button.clicked.connect(self._toggle_profile)
        self.import_profile_button.clicked.connect(self._import_profile)
        self.export_profile_button.clicked.connect(self._export_profile)
        self.load_history_button.clicked.connect(self._load_selected_history)
        self.prev_issue_button.clicked.connect(lambda: self._select_issue(-1))
        self.next_issue_button.clicked.connect(lambda: self._select_issue(1))
        self.prev_page_button.clicked.connect(
            lambda: self._change_issue_page(-1)
        )
        self.next_page_button.clicked.connect(
            lambda: self._change_issue_page(1)
        )
        self.save_report_button.clicked.connect(self._save_report_elsewhere)
        self.open_report_location_button.clicked.connect(
            self._open_report_location
        )
        self.host.canvas.shape_moved.connect(self._on_canvas_edit)
        self.host.canvas.shape_rotated.connect(self._on_canvas_edit)
        self.host.canvas.shapes_deleted.connect(self._on_canvas_edit)
        self.host.canvas.selection_changed.connect(self._update_action_buttons)
        self.host.actions.undo.triggered.connect(self._on_canvas_edit)
        self.filter_combo.currentIndexChanged.connect(self._populate_table)
        self.rule_filter_combo.currentIndexChanged.connect(
            self._populate_table
        )
        self.source_filter_combo.currentIndexChanged.connect(
            self._populate_table
        )
        self.risk_filter_combo.currentIndexChanged.connect(
            self._populate_table
        )
        self.profile_combo.currentIndexChanged.connect(
            self._update_profile_details
        )
        self.profile_combo.activated.connect(self._mark_profile_selected)
        self.issue_table.itemSelectionChanged.connect(
            self._show_selected_details
        )
        self.issue_table.installEventFilter(self)
        self.issue_table.cellClicked.connect(self._click_issue)
        self.issue_table.cellDoubleClicked.connect(self._double_click_issue)

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
        self.keep_both_button.clicked.connect(self._keep_both)
        self.defer_button.clicked.connect(self._defer_issue)
        self.recheck_button.clicked.connect(self._recheck_selected)
        self.handoff_button.clicked.connect(self._handoff_selected)
        self.delete_button.clicked.connect(self._delete_selected)
        self.relabel_button.clicked.connect(self._relabel_selected)
        self.batch_delete_button.clicked.connect(self._batch_delete)
        self.batch_relabel_button.clicked.connect(self._batch_relabel)
        self.undo_button.clicked.connect(self._undo_last_edit)
        self.import_issues_button.clicked.connect(self._import_issues)
        self.export_button.clicked.connect(self._export_report)
        self.note_toggle_button.clicked.connect(self._toggle_notes)
        self.import_candidates_button.clicked.connect(self._import_candidates)
        self.candidate_table.itemSelectionChanged.connect(
            self._sync_candidate_overlay
        )
        self.accept_candidate_button.clicked.connect(self._accept_candidate)
        self.accept_adjusted_button.clicked.connect(
            self._accept_candidate_adjusted
        )
        self.batch_accept_button.clicked.connect(self._batch_accept_candidates)
        self.reject_candidate_button.clicked.connect(
            lambda: self._set_candidate_status(CandidateStatus.REJECTED)
        )
        self.defer_candidate_button.clicked.connect(
            lambda: self._set_candidate_status(CandidateStatus.DEFERRED)
        )
        self.close_button.clicked.connect(self.close)
        self.controller.progress.connect(self._on_progress)
        self.controller.scan_progress.connect(self._on_scan_progress)
        self.controller.stage_changed.connect(self._on_stage_changed)
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
            if profile_id in self._disabled_profiles:
                suffix += self.tr("（已停用）")
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
            f"{_translate_label(STAGE_LABELS.get(profile.stage, profile.stage))}；"
            f"版本：{profile.version}"
        )
        names = []
        for rule in profile.enabled_rules:
            meta = self.catalog.meta(rule.rule_id)
            names.append(meta.name if meta else rule.rule_id)
        self.rule_summary.setText(
            "、".join(names) if names else self.tr("无启用规则")
        )

    def _require_editable_profile(self) -> Optional[InspectionProfile]:
        """Return the selected profile when it may be edited in place."""
        profile = self._selected_profile()
        if profile is None:
            return None
        if profile.builtin:
            self._show_error(
                self.tr("内置模板只读"),
                self.tr(
                    "内置检查模板不能直接修改。请先「复制方案」，"
                    "再编辑副本；历史报告仍保留原有效配置。"
                ),
            )
            return None
        path = self._custom_profile_paths.get(profile.profile_id)
        if not path:
            self._show_error(
                self.tr("方案不可编辑"),
                self.tr("该方案没有可写的本地文件，请重新复制或导入。"),
            )
            return None
        return profile

    def _view_rules(self) -> None:
        profile = self._selected_profile()
        if profile is not None:
            profile = replace(profile, stage=self.stage_combo.currentData())
            ProfileRuleEditor(
                profile, self.catalog, self, read_only=True
            ).exec()

    def _persist_profile(self, profile: InspectionProfile) -> bool:
        if self.storage is None:
            return False
        path = self._custom_profile_paths.get(profile.profile_id) or osp.join(
            self.storage.profiles_dir, f"{profile.profile_id}.json"
        )
        try:
            save_profile(path, profile)
        except OSError as error:
            self._show_error(self.tr("保存方案失败"), str(error))
            return False
        self._profiles[profile.profile_id] = profile
        self._custom_profile_paths[profile.profile_id] = path
        try:
            self.storage.profile_state.bump_revision(profile.profile_id)
        except (OSError, StorageError):
            pass
        self._refresh_profile_combo(profile.profile_id)
        return True

    def _rename_profile(self) -> None:
        if not self._ensure_storage():
            return
        profile = self._require_editable_profile()
        if profile is None:
            return
        name, ok = QtWidgets.QInputDialog.getText(
            self,
            self.tr("方案改名"),
            self.tr("新名称："),
            text=profile.name,
        )
        if not ok or not name.strip() or name.strip() == profile.name:
            return
        updated = replace(
            profile, name=name.strip(), version=profile.version + 1
        )
        if self._persist_profile(updated):
            self._set_status(
                f"方案已改名为 {updated.name}（v{updated.version}）。"
            )

    def _toggle_profile(self) -> None:
        if not self._ensure_storage() or self.storage is None:
            return
        profile = self._selected_profile()
        if profile is None:
            return
        disabled = profile.profile_id not in self._disabled_profiles
        try:
            self.storage.profile_state.set_disabled(
                profile.profile_id, disabled
            )
        except (OSError, StorageError) as error:
            self._show_error(self.tr("方案状态保存失败"), str(error))
            return
        if disabled:
            self._disabled_profiles.add(profile.profile_id)
        else:
            self._disabled_profiles.discard(profile.profile_id)
        self._refresh_profile_combo(profile.profile_id)
        self._set_status(
            self.tr("方案 {name} 已{state}；历史报告不受影响。").format(
                name=profile.name,
                state=self.tr("停用") if disabled else self.tr("启用"),
            )
        )

    def _edit_profile(self) -> None:
        if not self._ensure_storage():
            return
        profile = self._require_editable_profile()
        if profile is None:
            return
        dialog = ProfileRuleEditor(profile, self.catalog, self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        updated = dialog.result_profile()
        if updated is None:
            return
        validation = validate_profile(updated, self.catalog)
        if validation.errors:
            self._show_error(
                self.tr("方案无法保存"), "\n".join(validation.errors)
            )
            return
        if self._persist_profile(updated):
            self._set_status(
                f"方案 {updated.name} 已保存为 v{updated.version}；"
                "历史报告保留原配置。"
            )

    def _copy_profile(self) -> None:
        if not self._ensure_storage() or self.storage is None:
            return
        profile = self._selected_profile()
        if profile is None:
            return
        name, ok = QtWidgets.QInputDialog.getText(
            self,
            self.tr("复制检查方案"),
            self.tr("新方案名称："),
            text=f"{profile.name} 副本",
        )
        if not ok or not name.strip():
            return
        new_id = "custom-" + new_shape_id()[:8]
        copied = copy_builtin(profile, new_id, name.strip())
        path = osp.join(self.storage.profiles_dir, f"{new_id}.json")
        try:
            save_profile(path, copied)
        except OSError as error:
            self._show_error(self.tr("复制方案失败"), str(error))
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
            self.tr("导入检查方案"),
            self.storage.root,
            self.tr("JSON (*.json);;所有文件 (*)"),
        )
        if not path:
            return
        try:
            profile = load_profile(path)
        except (OSError, ValueError) as error:
            self._show_error(self.tr("导入方案失败"), str(error))
            return
        validation = validate_profile(profile, self.catalog)
        if validation.errors:
            self._show_error(self.tr("方案无效"), "\n".join(validation.errors))
            return
        if profile.builtin or profile.profile_id in self._profiles:
            profile = copy_builtin(
                profile, "imported-" + new_shape_id(), profile.name
            )
        target = osp.join(
            self.storage.profiles_dir, f"{profile.profile_id}.json"
        )
        try:
            save_profile(target, profile)
        except OSError as error:
            self._show_error(self.tr("保存方案失败"), str(error))
            return
        self._profiles[profile.profile_id] = profile
        self._custom_profile_paths[profile.profile_id] = target
        self._refresh_profile_combo(profile.profile_id)
        if validation.missing_rule_ids:
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("方案含缺失规则"),
                self.tr("本机未登记：\n")
                + "\n".join(validation.missing_rule_ids)
                + self.tr("\n\n运行时可选择仅执行可用子集。"),
            )
        else:
            self._set_status(f"已导入方案 {profile.name}。")

    def _export_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            self.tr("导出检查方案"),
            f"{profile.profile_id}.json",
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            save_profile(path, profile)
        except OSError as error:
            self._show_error(self.tr("导出方案失败"), str(error))
            return
        self._set_status(f"已导出方案 {path}。")

    def _navigation_allowed(self):
        if QtWidgets.QApplication.activeWindow() not in (self, self.host.window()):
            return False
        if (
            not self._session_open
            or self._navigating
            or self.controller.is_running()
            or QtWidgets.QApplication.activeModalWidget() is not None
            or self.host.canvas.interaction_in_progress()
        ):
            return False
        if self.report is None:
            return False
        return output_identity(self.report.dataset_root) == output_identity(
            self.host.inspection_dataset_root()
        ) and output_identity(self.report.output_root) == output_identity(
            self.host.inspection_output_dir()
        )

    def _neighbor(self, offset):
        queue = self._filtered_issues()
        keys = [issue.family_key for issue in queue]
        if not keys:
            return None
        if self._active_issue_key in keys:
            index = keys.index(self._active_issue_key) + offset
            return queue[index] if 0 <= index < len(queue) else None
        if self._active_issue_key in self._navigation_order:
            index = self._navigation_order.index(self._active_issue_key)
            candidates = (
                self._navigation_order[index + 1 :]
                if offset > 0
                else reversed(self._navigation_order[:index])
            )
            for key in candidates:
                if key in keys:
                    return queue[keys.index(key)]
            return None
        return queue[0 if offset > 0 else -1]

    def _select_issue(self, offset: int) -> None:
        issue = self._neighbor(offset)
        if issue is not None:
            self._navigate_issue(issue)

    def _restore_issue_cursor(self):
        queue = self._filtered_issues()
        keys = [issue.family_key for issue in queue]
        if self._active_issue_key in keys:
            index = keys.index(self._active_issue_key)
            self._issue_page = index // self._issue_page_size
            self._populate_table()
            self.issue_table.selectRow(index % self._issue_page_size)
        else:
            self.issue_table.clearSelection()
            self.issue_table.setCurrentCell(-1, -1)

    def _navigate_issue(self, issue, object_ids=None):
        if not self._navigation_allowed():
            self._restore_issue_cursor()
            return False
        ids = tuple(
            object_ids
            if object_ids is not None
            else issue.location.object_ids[:1]
        )
        if (
            issue.family_key == self._active_issue_key
            and object_ids is None
            and self.host.inspection_current_relative_path()
            == issue.location.relative_path
            and not self._target_guard_reason(issue)
        ):
            return True
        self._navigating = True
        try:
            ok = self.host.inspection_navigate_to(
                issue.location.relative_path,
                ids,
                issue.location.region,
                image_path=issue.location.image_path,
            )
            if ok:
                self._active_issue_key = issue.family_key
                self._navigation_order = [
                    item.family_key for item in self._filtered_issues()
                ]
                self._navigation_serial += 1
                self._restore_issue_cursor()
                self.object_combo.clear()
                self.object_combo.addItems(list(issue.location.object_ids))
                self._set_status(issue.message)
            else:
                self._restore_issue_cursor()
                self._set_status(
                    self.tr(
                        "无法定位：切换被取消、文件或对象身份失效，请复查。"
                    )
                )
            return ok
        finally:
            self._navigating = False
            self._update_navigation_buttons()
            self._update_action_buttons()

    def _select_problem_object(self, index):
        issue = (
            next(
                (
                    item
                    for item in self.report.issues
                    if item.family_key == self._active_issue_key
                ),
                None,
            )
            if self.report
            else None
        )
        if issue and 0 <= index < len(issue.location.object_ids):
            self._navigate_issue(issue, (issue.location.object_ids[index],))

    def _update_navigation_buttons(self):
        self.prev_issue_button.setEnabled(self._neighbor(-1) is not None)
        self.next_issue_button.setEnabled(self._neighbor(1) is not None)
        keys = [issue.family_key for issue in self._filtered_issues()]
        position = (
            str(keys.index(self._active_issue_key) + 1)
            if self._active_issue_key in keys
            else "–"
        )
        self.page_label.setText(f"{position} / {len(keys)}")

    def _click_issue(self, *args):
        issue = self._selected_issue()
        self._click_key = issue.family_key if issue else ""
        self._click_timer.start()
        self._locate_selected()

    def _double_click_issue(self, *args):
        issue = self._selected_issue()
        if (
            issue
            and self._click_key == issue.family_key
            and self._click_timer.isValid()
            and self._click_timer.elapsed()
            <= QtWidgets.QApplication.doubleClickInterval()
        ):
            return
        self._locate_selected()

    def eventFilter(self, watched, event):
        if (
            watched is self.issue_table
            and event.type() == QtCore.QEvent.Type.KeyRelease
        ):
            if event.key() in (
                QtCore.Qt.Key.Key_Up,
                QtCore.Qt.Key.Key_Down,
                QtCore.Qt.Key.Key_Home,
                QtCore.Qt.Key.Key_End,
                QtCore.Qt.Key.Key_PageUp,
                QtCore.Qt.Key.Key_PageDown,
            ):
                self._locate_selected()
        return super().eventFilter(watched, event)

    def _on_canvas_edit(self, *args) -> None:
        self._edit_serial += 1
        try:
            self._handle_canvas_edit()
        except (RuntimeError, AttributeError):
            # A closing window can emit edit signals after its widgets are
            # gone; the queue is rebuilt on the next run instead of crashing.
            return

    def _handle_canvas_edit(self) -> None:
        if self._candidate_records:
            self._reconcile_candidate_intents()
            self._populate_candidate_table()
        if self.report is None:
            return
        relative = self.host.inspection_current_relative_path()
        if not relative:
            return
        if dataset_identity(self.report.dataset_root) != dataset_identity(
            self.host.inspection_dataset_root()
        ) or output_identity(self.report.output_root) != output_identity(
            self.host.inspection_output_dir()
        ):
            return
        updated, _ = invalidate_file_edits(self.report, relative)
        self.report = updated
        self._refresh_duplicate_issues_incrementally(relative)
        self._populate_table()
        self._update_status()
        self._set_status(self.tr("画布已修改，相关问题标记为待复查。"))

    def _refresh_duplicate_issues_incrementally(
        self, relative_path: str
    ) -> None:
        """Recompute this file's duplicate pairs without a full re-run.

        Only the edited file is touched; the tracker refuses to publish a
        result that differs from a full scan of the same snapshot.
        """
        if self.report is None or self._active_profile is None:
            return
        rule_ids = {
            rule.rule_id
            for rule in self._active_profile.enabled_rules
            if rule.rule_id
            in ("duplicate_boxes", "legacy_same_group_duplicate")
        }
        if not rule_ids:
            return
        current_manifest = self.host.inspection_current_manifest()
        if current_manifest is None or not current_manifest.files:
            return
        file = current_manifest.files[0]
        if file.relative_path != relative_path:
            return
        from anylabeling.services.inspection.incremental import (
            tracker_from_profile,
        )
        from anylabeling.services.inspection.rules import (
            RuleContext,
            run_duplicate_boxes,
            run_legacy_same_group_duplicate,
        )
        from anylabeling.services.inspection.runner import _merge_issues

        tracker = self._duplicate_tracker
        configured = tracker_from_profile(self._active_profile)
        if (
            tracker is None
            or tracker.thresholds != configured.thresholds
            or tracker.max_pairs != configured.max_pairs
        ):
            tracker = configured
            self._duplicate_tracker = tracker
        pair_state = tracker.synchronize_file(relative_path, file)
        context = RuleContext(
            profile=self._active_profile,
            file=file,
            duplicate_pairs=pair_state.pairs,
        )
        outcomes = []
        for rule_id, executor in (
            ("duplicate_boxes", run_duplicate_boxes),
            ("legacy_same_group_duplicate", run_legacy_same_group_duplicate),
        ):
            if rule_id in rule_ids:
                rule = self._active_profile.rule_config(rule_id)
                outcomes.append(executor(context, dict(rule.parameters)))
        new_issues = _merge_issues(
            issue for outcome in outcomes for issue in outcome.issues
        )
        new_keys = {issue.family_key for issue in new_issues}
        existing = {
            issue.family_key: issue
            for issue in self.report.issues
            if issue.location.relative_path == relative_path
        }
        kept = []
        for issue in self.report.issues:
            if issue.location.relative_path != relative_path:
                kept.append(issue)
                continue
            if not set(issue.rule_ids).issubset(
                {"duplicate_boxes", "legacy_same_group_duplicate"}
            ):
                kept.append(issue)
                continue
            if issue.family_key in new_keys:
                continue
            kept.append(issue)
        for issue in new_issues:
            previous = existing.get(issue.family_key)
            issue = replace(
                issue,
                decision=(
                    previous.decision
                    if previous is not None
                    and previous.location.snapshot_digest
                    == issue.location.snapshot_digest
                    else Decision.PENDING
                ),
                action=(
                    previous.action
                    if previous is not None
                    else ActionState.UNCHANGED
                ),
                verification=VerificationState.PENDING_RECHECK,
            )
            kept.append(issue)
        kept.sort(
            key=lambda item: (
                item.location.relative_path,
                item.location.object_ids,
                item.title,
            )
        )
        self.report = replace(
            self.report,
            issues=tuple(kept),
            state=(
                RunState.PARTIAL
                if pair_state.truncated or any(o.truncated for o in outcomes)
                else self.report.state
            ),
            truncated=self.report.truncated
            or pair_state.truncated
            or any(o.truncated for o in outcomes),
        )

    def _ask_dirty_batch(self) -> str:
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(self.tr("存在未保存修改"))
        box.setText(
            self.tr(
                "批量检查范围包含当前未保存文档。请选择保存后运行、"
                "明确排除该图片，或取消。"
            )
        )
        save_button = box.addButton(
            self.tr("保存后运行"), QtWidgets.QMessageBox.ButtonRole.AcceptRole
        )
        exclude_button = box.addButton(
            self.tr("排除未保存图片"),
            QtWidgets.QMessageBox.ButtonRole.DestructiveRole,
        )
        box.addButton(
            self.tr("取消"), QtWidgets.QMessageBox.ButtonRole.RejectRole
        )
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
            self._set_status(self.tr("无法确定数据集目录。"))
            return False
        try:
            storage = InspectionStorage.open(dataset_root, output_dir)
        except OSError as error:
            self._show_error(self.tr("无法建立检查存储"), str(error))
            return False
        if self.storage is None or self.storage.root != storage.root:
            self.storage = storage
            self._load_feedback()
            self._load_custom_profiles()
            self._load_candidates()
            self._load_session()
            self._refresh_history_combo()
            if storage.migration_notes:
                self._run_notes = tuple(storage.migration_notes)
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
        directory = self.storage.profiles_dir
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
        try:
            self._disabled_profiles = set(
                self.storage.profile_state.disabled()
            )
        except (OSError, StorageError):
            self._disabled_profiles = set()
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
        self._candidate_store = CandidateStore(
            self.storage.root, dataset_key=self.storage.dataset_key
        )
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
        self._reconcile_candidate_intents()
        self._populate_candidate_table()

    def _reconcile_candidate_intents(self) -> None:
        """Do not replay an acceptance whose formal object disappeared.

        A saved intent only proves the click happened; the shape itself is
        the evidence.  If the object is no longer in the file the candidate
        returns to pending so the user decides, and nothing is re-created.
        """
        from anylabeling.services.inspection.manifest import (
            load_file_snapshot,
        )

        if self._intent_store is None:
            return
        try:
            intents = self._intent_store.load()
        except (OSError, StorageError) as error:
            self._set_status(str(error))
            return
        changed = False
        dataset_root = self.host.inspection_dataset_root()
        memory = {}
        memory_manifest = self.host.inspection_current_manifest()
        if memory_manifest is not None:
            for file in memory_manifest.files:
                memory[file.relative_path] = file
        disk_files = {}
        for candidate in list(self._candidate_records.values()):
            intent = intents.get(candidate.candidate_id, {})
            if (
                not intent
                and candidate.status is not CandidateStatus.ACCEPTED
                and not candidate.accepted_shape_id
            ):
                continue
            path = candidate.relative_path
            if path not in disk_files:
                image_path = candidate.image_path or osp.join(
                    dataset_root, path
                )
                try:
                    disk_files[path] = load_file_snapshot(
                        image_path,
                        dataset_root,
                        self.host.inspection_output_dir(),
                        relative_path=path,
                        hash_images=False,
                    )
                except (OSError, TypeError, ValueError):
                    disk_files[path] = None
            disk = disk_files[path]
            snapshot = memory.get(path, disk)
            if snapshot is None or snapshot.annotation_state == "error":
                # An unreadable document is not proof of a deleted object.
                continue
            expected_id = candidate.accepted_shape_id or str(
                intent.get("preallocated_shape_id", "")
            )
            shape = next(
                (
                    shape
                    for shape in snapshot.shapes
                    if (
                        expected_id
                        and shape.shape_id == expected_id
                        and shape.attributes.get(
                            "inspection_candidate_id", candidate.candidate_id
                        )
                        == candidate.candidate_id
                    )
                ),
                None,
            )
            if shape is not None:
                saved = bool(
                    disk is not None
                    and any(
                        item.shape_id == shape.shape_id for item in disk.shapes
                    )
                )
                updated = replace(
                    candidate,
                    status=CandidateStatus.ACCEPTED,
                    accepted_shape_id=shape.shape_id,
                    reason="" if saved else "已接受，标注尚未保存",
                )
                if intent:
                    desired = "confirmed" if saved else "applied"
                    if intent.get("status") != desired:
                        try:
                            if saved:
                                self._intent_store.confirm(
                                    candidate.candidate_id
                                )
                            else:
                                self._intent_store.applied(
                                    candidate.candidate_id
                                )
                        except (OSError, StorageError) as error:
                            self._set_status(str(error))
            else:
                updated = replace(
                    candidate,
                    status=CandidateStatus.PENDING,
                    accepted_shape_id="",
                    reason="正式对象已不存在，需重新确认（不会重复画框）",
                )
                if intent and intent.get("status") != "abandoned":
                    try:
                        self._intent_store.abandon(candidate.candidate_id)
                    except (OSError, StorageError) as error:
                        self._set_status(str(error))
            if updated != candidate:
                self._candidate_records[candidate.candidate_id] = updated
                changed = True
        if changed and self._candidate_store is not None:
            try:
                self._candidate_revision = self._candidate_store.save(
                    self._candidate_records, self._candidate_revision
                )
            except (OSError, StorageError) as error:
                # Keep the reconciled in-memory state, including formal IDs.
                self._set_status(self.tr("候选状态保存失败") + f": {error}")

    def _prepare_run_profile(self):
        profile = self._selected_profile()
        if profile is None:
            self._show_error(self.tr("检查"), self.tr("请选择检查方案。"))
            return None
        stage = str(self.stage_combo.currentData())
        if stage != profile.stage:
            profile = replace(profile, stage=stage)
        if profile.profile_id in self._disabled_profiles:
            answer = QtWidgets.QMessageBox.question(
                self,
                self.tr("方案已停用"),
                self.tr(
                    "方案 {} 已停用；历史报告仍保留。本次仍要运行吗？"
                ).format(profile.name),
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
            )
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                return None
        validation = validate_profile(profile, self.catalog)
        if validation.errors:
            self._show_error(
                self.tr("方案无法运行"), "\n".join(validation.errors)
            )
            return None
        allow_partial = False
        if validation.missing_rule_ids:
            answer = QtWidgets.QMessageBox.question(
                self,
                self.tr("规则缺失"),
                self.tr("方案引用本机未登记规则：\n")
                + "\n".join(validation.missing_rule_ids)
                + self.tr("\n\n仅运行可用子集？"),
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
                self._show_error(
                    self.tr("检查"), self.tr("当前没有可检查的图片。")
                )
                return None, None, False
        elif scope is RunScope.SELECTED_FILES:
            paths = self.host.inspection_selected_image_paths()
            if not paths:
                self._show_error(
                    self.tr("检查"), self.tr("请先在文件列表选择文件。")
                )
                return None, None, False
        else:
            if dataset_root:
                paths = None
            else:
                paths = self.host.inspection_image_paths()
            if not paths and not dataset_root:
                self._show_error(
                    self.tr("检查"), self.tr("当前数据集没有可检查文件。")
                )
                return None, None, False
            if scope is RunScope.CHANGED_FILES:
                self._set_status(
                    self.tr(
                        "正在核验上一份清单；无可信清单时按保守范围全量检查。"
                    )
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
                    self.tr("保存失败"),
                    self.tr("未保存修改仍然存在，已取消检查。"),
                )
                return paths, excluded, False
            return paths, excluded, True
        if paths is None:
            return paths, {self.host.filename}, True
        remaining = [path for path in paths if path != self.host.filename]
        if not remaining:
            self._show_error(
                self.tr("检查"), self.tr("排除未保存图片后范围为空。")
            )
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
        previous_report = None
        if scope is RunScope.CHANGED_FILES and self.storage is not None:
            entries = self.storage.reports.list_reports()
            if entries:
                try:
                    previous_report = self.storage.reports.load(
                        str(entries[0].get("run_id", ""))
                    )
                    previous_manifest = self.storage.reports.load_manifest(
                        previous_report.run_id
                    )
                except (OSError, StorageError):
                    previous_report = None
                    previous_manifest = None
        self._active_profile = profile
        self._duplicate_tracker = None
        self._generation += 1
        self._run_edit_serial = self._edit_serial
        self._run_token = ""
        self._run_notes = ()
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setRange(0, 0)
        self._set_status(self.tr("扫描文件"))
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
                previous_report=previous_report,
                allow_partial=allow_partial,
                generation=self._generation,
            )
        except RuntimeError as error:
            self.start_button.setEnabled(True)
            self.cancel_button.setEnabled(False)
            self._show_error(self.tr("检查"), str(error))
            return
        context = self.controller.active_context
        self._run_context = context
        self._run_token = context.token if context else ""

    def _on_stage_changed(self, token: str, message: str) -> None:
        if self._run_token and token and token != self._run_token:
            return
        self._set_status(message)

    def _on_progress(
        self, token: str, index: int, total: int, path: str
    ) -> None:
        if self._run_token and token and token != self._run_token:
            return
        self.progress.setRange(0, max(1, total))
        self.progress.setFormat("%v/%m (%p%)")
        self.progress.setValue(index)
        self._set_status(f"检查 {index}/{total}: {path}")

    def _on_scan_progress(
        self, token: str, index: int, total: int, path: str
    ) -> None:
        if self._run_token and token and token != self._run_token:
            return
        if total:
            self.progress.setRange(0, total)
            self.progress.setFormat("%v/%m (%p%)")
            self.progress.setValue(index)
            self._set_status(
                self.tr("扫描文件 {done}/{total}: {path}").format(
                    done=index, total=total, path=path
                )
            )
        else:
            self.progress.setRange(0, 0)
            self._set_status(
                self.tr("正在查找图片，已找到 {count} 个: {path}").format(
                    count=index, path=path
                )
            )

    def _on_failed(self, token: str, message: str) -> None:
        if self._run_token and token and token != self._run_token:
            return
        self._recheck_issue = None
        self._save_recheck_context = None
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self._set_status(f"检查失败: {message}")
        self._show_error(self.tr("检查失败"), message)

    def _run_result_is_current(self, report: RunReport, token: str) -> str:
        """Return "" when a finished run still describes the live context."""
        if self._run_token and token and token != self._run_token:
            return "运行令牌不匹配，旧运行结果不覆盖当前队列"
        if int(report.generation) != int(self._generation):
            return "运行代际不匹配，旧运行结果不覆盖当前队列"
        saved_context = self._save_recheck_context
        if saved_context is not None:
            serial, edits, key, path = saved_context
            if (
                serial != self._navigation_serial
                or edits != self._edit_serial
                or key != self._active_issue_key
                or path != self.host.inspection_current_relative_path()
            ):
                return self.tr("保存复查期间文档或问题已变化，结果仅作历史")
        context = self._run_context
        if context is not None:
            current_dataset = self.host.inspection_dataset_root()
            current_output = self.host.inspection_output_dir()
            if output_identity(context.dataset_root) != output_identity(
                report.dataset_root
            ):
                return "报告数据集与运行上下文不一致"
            if output_identity(context.output_dir) != output_identity(
                report.output_root
            ):
                return "报告输出目录与运行上下文不一致"
            if context.profile_fingerprint:
                snapshot_profile = report.profile_snapshot.get(
                    "profile_fingerprint", ""
                )
                if context.config_digest and report.config_digest:
                    if report.config_digest != context.config_digest:
                        return "报告方案与运行上下文不一致"
                elif (
                    snapshot_profile
                    and snapshot_profile != context.profile_fingerprint
                ):
                    return "报告方案与运行上下文不一致"
            if output_identity(current_dataset) != output_identity(
                context.dataset_root
            ) or output_identity(current_output) != output_identity(
                context.output_dir
            ):
                return "运行期间数据集或输出目录已切换，结果仅作历史"
        return ""

    def _on_finished(
        self, report: RunReport, manifest, token: str = ""
    ) -> None:
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        total = report.requested_files
        self.progress.setRange(0, max(1, total))
        self.progress.setFormat("%v/%m (%p%)" if total else "0/0")
        self.progress.setValue(
            min(total, report.completed_files + report.failed_files)
        )
        stale_reason = self._run_result_is_current(report, token)
        if stale_reason:
            self._archive_stale_run(report, manifest, stale_reason)
            return
        self._verification_reasons = ()
        self._verification_current = True
        if self._recheck_issue is not None:
            self._finish_recheck(report, manifest)
            return
        if self._edit_serial != self._run_edit_serial:
            # Inputs were edited while the run was in flight: compare the
            # report against the current canvas before trusting it.
            self.report = report
            self.manifest = manifest
            self._load_feedback()
            self.report = self._apply_feedback_to_report(report)
            self.report = self._apply_report_verification(self.report)
            self._run_notes = self._run_notes + (
                "运行期间画布发生编辑，结果已复核并标记变化范围",
            )
        else:
            self.report = report
            self.manifest = manifest
            self._load_feedback()
            self.report = self._apply_feedback_to_report(report)
        self._active_issue_key = ""
        self._navigation_order = []
        self._navigation_serial += 1
        self._save_run(self.report, self.manifest)
        self._populate_table()
        self._update_status()
        summary = self.report.summary()
        self._set_status(
            "检查结束：{}；{} 个问题，{} 张图片；{}".format(
                self.report.state.value,
                summary["issue_count"],
                summary["image_count"],
                "；".join(self._run_notes) or "无附加范围说明",
            )
        )

    def _archive_stale_run(
        self, report: RunReport, manifest, reason: str
    ) -> None:
        """Keep a late run in its original history without touching the queue."""
        if self._recheck_issue is not None:
            self._recheck_issue = None
            reason = reason + "；复查结果未应用，原队列保持不变"
        self._save_recheck_context = None
        self._run_notes = self._run_notes + (reason,)
        try:
            archive = InspectionStorage.open(
                report.dataset_root, report.output_root
            )
            archive.reports.save(report, manifest)
            saved = "报告已归档到原数据集历史 {}。".format(archive.root)
        except (OSError, StorageError) as error:
            saved = f"旧报告未能归档: {error}。"
        self._set_status(f"{reason}；{saved}")

    def _save_run(self, report=None, manifest=None) -> bool:
        report = report if report is not None else self.report
        manifest = manifest if manifest is not None else self.manifest
        if report is None:
            return False
        try:
            store = self.storage
            if store is None or output_identity(
                store.dataset_root
            ) != output_identity(report.dataset_root):
                store = InspectionStorage.open(
                    report.dataset_root, report.output_root
                )
                if self.storage is None:
                    self.storage = store
            store.reports.save(report, manifest)
            if store is self.storage:
                self._refresh_history_combo()
                frozen_profile = report.profile_snapshot.get("profile", {})
                if not isinstance(frozen_profile, Mapping):
                    frozen_profile = {}
                self.storage.bindings.save(
                    report.dataset_root,
                    report.output_root,
                    str(frozen_profile.get("profile_id", "")),
                    int(frozen_profile.get("profile_version", 1) or 1),
                    str(
                        report.profile_snapshot.get("profile_fingerprint", "")
                    ),
                )
                self._save_session()
            return True
        except (OSError, StorageError) as error:
            self._show_error(
                self.tr("报告保存失败"),
                f"{error}\n结果仍保留在当前窗口中，可选择导出。",
            )

            return False

    def _apply_feedback_to_report(self, report: RunReport) -> RunReport:
        dataset_key = self.storage.dataset_key if self.storage else ""
        return apply_feedback(report, self.feedback, dataset_key=dataset_key)

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

    def _refresh_filter_options(self) -> None:
        """Populate rule/source filters from the current report."""
        issues = self.report.issues if self.report is not None else ()
        rule_names = {}
        sources = set()
        for issue in issues:
            for evidence in issue.evidence:
                if evidence.rule_id:
                    rule_names[evidence.rule_id] = evidence.rule_name
                if evidence.source:
                    sources.add(evidence.source)
        combos = (
            (
                self.rule_filter_combo,
                self.tr("全部规则"),
                [
                    (rule_id, rule_names.get(rule_id, rule_id))
                    for rule_id in sorted(rule_names)
                ],
            ),
            (
                self.source_filter_combo,
                self.tr("全部来源"),
                [(source, source) for source in sorted(sources)],
            ),
        )
        for combo, empty_label, options in combos:
            current = str(combo.currentData() or "")
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(empty_label, "")
            for value, label in options:
                combo.addItem(label, value)
            index = combo.findData(current)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

    def _populate_table(self) -> None:
        if self.report is None:
            self.issue_table.setRowCount(0)
            self._row_issues = []
            self.issue_stack.setCurrentIndex(1)
            self.issue_count_label.setText("")
            return
        self._refresh_filter_options()
        selected = self._selected_issue()
        selected_key = selected.family_key if selected else ""
        filter_value = str(self.filter_combo.currentData())
        rule_value = str(self.rule_filter_combo.currentData() or "")
        source_value = str(self.source_filter_combo.currentData() or "")
        risk_value = str(self.risk_filter_combo.currentData() or "")
        filtered = self._filtered_issues()
        page_count = max(
            1,
            (len(filtered) + self._issue_page_size - 1)
            // self._issue_page_size,
        )
        self._issue_page = min(self._issue_page, page_count - 1)
        self.prev_page_button.setEnabled(self._issue_page > 0)
        self.next_page_button.setEnabled(self._issue_page + 1 < page_count)
        self.page_label.setText(f"{self._issue_page + 1} / {page_count}")
        start = self._issue_page * self._issue_page_size
        self.issue_table.setRowCount(0)
        self._row_issues = []
        for issue in filtered[start : start + self._issue_page_size]:
            if not self._matches_filter(issue, filter_value):
                continue
            if rule_value and rule_value not in issue.rule_ids:
                continue
            if source_value and not any(
                item.source == source_value for item in issue.evidence
            ):
                continue
            if risk_value and issue.severity.value != risk_value:
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
                    self.tr("区域 ")
                    + ", ".join(
                        f"{value:.1f}" for value in issue.location.region
                    )
                    if issue.location.region
                    else self.tr("图片")
                )
            )
            values = (
                self._severity_text(issue),
                rule_names,
                f"{issue.location.relative_path} · {object_text}",
                _translate_label(
                    VERIFICATION_LABELS.get(
                        issue.verification, issue.verification.value
                    )
                ),
                _translate_label(
                    DECISION_LABELS.get(issue.decision, issue.decision.value)
                ),
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
            self._show_selected_details()
        elif self.issue_table.currentRow() < 0 and not self._active_issue_key:
            self.issue_table.selectRow(0)
        self.issue_stack.setCurrentIndex(0 if self._row_issues else 1)
        total = len(self.report.issues) if self.report is not None else 0
        if total:
            counts = self.report.summary()["verification_counts"]
            self.issue_count_label.setText(
                self.tr(
                    "{shown} / {total} 条 · 当前 {current} · 待复查 "
                    "{pending} · 未再检出 {history} · 过期 {stale}"
                ).format(
                    shown=len(self._row_issues),
                    total=total,
                    current=counts.get("current", 0),
                    pending=counts.get("pending_recheck", 0),
                    history=counts.get(
                        "not_detected_on_successful_recheck", 0
                    ),
                    stale=counts.get("stale", 0)
                    + counts.get("unverifiable", 0),
                )
            )
        else:
            self.issue_count_label.setText(self.tr("0 条"))
        self.issue_count_label.setToolTip(
            self.tr(
                "请求图片 {requested}；问题图片 {images}；对象 {objects}；"
                "截断 {truncated}"
            ).format(
                requested=self.report.summary()["requested_files"],
                images=self.report.summary()["image_count"],
                objects=self.report.summary()["object_count"],
                truncated=(
                    self.tr("是") if self.report.truncated else self.tr("否")
                ),
            )
        )
        self._update_action_buttons()
        counts = {
            state: sum(
                self._review_state(item) == state
                for item in self.report.issues
            )
            for state in ("pending", "resolved", "ignored")
        }
        self.issue_count_label.setText(
            self.tr(
                "待处理 {pending} · 已解决 {resolved} · 已忽略 {ignored}"
            ).format(**counts)
        )
        self._update_navigation_buttons()

    def _change_issue_page(self, offset: int) -> None:
        self._issue_page = max(0, self._issue_page + offset)
        self._populate_table()

    def _filtered_issues(self) -> list[InspectionIssue]:
        if self.report is None:
            return []
        rule = str(self.rule_filter_combo.currentData() or "")
        source = str(self.source_filter_combo.currentData() or "")
        risk = str(self.risk_filter_combo.currentData() or "")
        return [
            issue
            for issue in self.report.issues
            if self._matches_filter(
                issue, str(self.filter_combo.currentData())
            )
            and (not rule or rule in issue.rule_ids)
            and (not source or any(e.source == source for e in issue.evidence))
            and (not risk or issue.severity.value == risk)
        ]

    def _save_report_elsewhere(self) -> None:
        if self.report is None:
            return
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self, self.tr("另存检查报告"), self.host.inspection_dataset_root()
        )
        if not directory:
            return
        try:
            alternate = InspectionStorage.open(
                self.report.dataset_root,
                self.report.output_root,
                preferred=directory,
            )
            alternate.reports.save(self.report, self.manifest)
        except (OSError, StorageError) as error:
            self._show_error(self.tr("报告保存失败"), str(error))
            return
        self._set_status(alternate.root)

    def _open_report_location(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            self.tr("打开报告保存位置"),
            self.host.inspection_dataset_root(),
        )
        if not directory:
            return
        root = self.host.inspection_dataset_root()
        candidate = osp.join(directory, dataset_identity(root), "reports")
        if not osp.isdir(candidate):
            self._show_error(
                self.tr("恢复失败"), self.tr("没有可恢复的检查报告。")
            )
            return
        try:
            alternate = InspectionStorage.open(
                root, self.host.inspection_output_dir(), preferred=directory
            )
            entries = alternate.reports.list_reports()
            if not entries:
                raise StorageError(self.tr("没有可恢复的检查报告。"))
        except (OSError, StorageError) as error:
            self._show_error(self.tr("恢复失败"), str(error))
            return
        self.storage = alternate
        self._refresh_history_combo()
        self._load_report(str(entries[0]["run_id"]))

    @staticmethod
    def _review_state(issue):
        if issue.verification in (
            VerificationState.STALE,
            VerificationState.PENDING_RECHECK,
            VerificationState.UNVERIFIABLE,
        ):
            return "pending"
        if issue.verification is VerificationState.NOT_DETECTED:
            return "resolved"
        if issue.decision in (Decision.ACCEPTABLE, Decision.FALSE_POSITIVE):
            return "ignored"
        return "pending"

    def _matches_filter(self, issue: InspectionIssue, value: str) -> bool:
        if value.startswith("review_"):
            return self._review_state(issue) == value[7:]
        if value == "all":
            return True
        if value == "pending":
            return issue.decision is Decision.PENDING
        if value == "handled":
            return issue.decision is not Decision.PENDING
        if value == "pending_recheck":
            return issue.verification is VerificationState.PENDING_RECHECK
        if value == "not_detected":
            return issue.verification is VerificationState.NOT_DETECTED
        return issue.decision.value == value

    def _severity_text(self, issue: InspectionIssue) -> str:
        if issue.severity.value == "error":
            return self.tr("错误")
        if issue.severity.value == "warning":
            return self.tr("疑似")
        return self.tr("提示")

    def _selected_issue(self) -> Optional[InspectionIssue]:
        row = self.issue_table.currentRow()
        if row < 0 or row >= len(self._row_issues):
            return None
        return self._row_issues[row]

    def _target_guard_reason(self, issue: Optional[InspectionIssue]) -> str:
        return action_target_problem(
            self.report,
            issue,
            dataset_root=self.host.inspection_dataset_root(),
            output_dir=self.host.inspection_output_dir(),
            current_relative_path=(
                self.host.inspection_current_relative_path()
            ),
        )

    def _selected_target_ids(
        self, issue: Optional[InspectionIssue]
    ) -> list[str]:
        if issue is None or self._target_guard_reason(issue):
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
        bound = (
            next(
                (
                    item
                    for item in self.report.issues
                    if item.family_key == self._active_issue_key
                ),
                None,
            )
            if self.report
            else None
        )
        self.save_recheck_button.setEnabled(
            bool(
                bound
                and self._navigation_allowed()
                and bound.location.relative_path
                == self.host.inspection_current_relative_path()
            )
        )
        issue = self._selected_issue()
        target_ids = self._selected_target_ids(issue)
        guard = self._target_guard_reason(issue) if issue is not None else ""
        self.delete_button.setEnabled(bool(target_ids))
        self.relabel_button.setEnabled(bool(target_ids))
        self.handoff_button.setEnabled(issue is not None and not guard)
        self.keep_both_button.setEnabled(issue is not None and not guard)
        self.defer_button.setEnabled(issue is not None and not guard)
        self.batch_delete_button.setEnabled(
            bool(issue is not None and not guard)
        )
        self.batch_relabel_button.setEnabled(
            bool(issue is not None and not guard)
        )
        if guard:
            tooltip = guard
        elif target_ids:
            tooltip = self.tr(
                "仅修改当前画布「{file}」中选中的问题对象：{ids}"
            ).format(
                file=issue.location.relative_path,
                ids=", ".join(target_ids),
            )
        else:
            tooltip = self.tr("请先在画布中选中要删除/重标的问题对象")
        self.delete_button.setToolTip(tooltip)
        self.relabel_button.setToolTip(tooltip)

    def _selected_candidate(self) -> Optional[Candidate]:
        row = self.candidate_table.currentRow()
        if row < 0:
            return None
        item = self.candidate_table.item(row, 0)
        if item is None:
            return None
        candidate_id = str(item.data(QtCore.Qt.ItemDataRole.UserRole))
        return self._candidate_records.get(candidate_id)

    def _section(self, title: str, body: str) -> str:
        """Render one labelled block of the issue detail page."""
        theme = get_theme()
        return (
            '<div style="margin:0 0 16px 0;">'
            '<div style="color:{};font-size:11px;margin:0 0 6px 0;">'
            "{}</div>"
            '<div style="color:{};font-size:13px;line-height:1.7;">{}</div>'
            "</div>"
        ).format(
            theme["text_secondary"],
            html.escape(title),
            theme["text"],
            body,
        )

    def _kv_table(self, rows) -> str:
        theme = get_theme()
        cells = []
        for label, value in rows:
            cells.append(
                '<tr><td style="color:{};font-size:11px;padding:1px 14px '
                '1px 0;white-space:nowrap;vertical-align:top;">{}</td>'
                '<td style="color:{};font-size:12px;padding:1px 0;">'
                "{}</td></tr>".format(
                    theme["text_secondary"],
                    html.escape(label),
                    theme["text"],
                    value,
                )
            )
        return (
            '<table cellspacing="0" cellpadding="0" '
            'style="border-collapse:collapse;">{}</table>'.format(
                "".join(cells)
            )
        )

    @staticmethod
    def _format_metric(value) -> str:
        if isinstance(value, float):
            return f"{value:.4f}"
        return html.escape(str(value))

    def _show_details_placeholder(self) -> None:
        theme = get_theme()
        self.details.setHtml(
            '<div style="color:{};font-size:13px;line-height:1.7;'
            'padding:16px 4px;">{}<br/>{}</div>'.format(
                theme["text_secondary"],
                self.tr("选择左侧问题查看规则、证据与建议。"),
                self.tr("双击问题行或按 Enter 可定位到画布对象。"),
            )
        )

    def _show_selected_details(self) -> None:
        issue = self._selected_issue()
        if issue is None and self.report is not None:
            issue = next(
                (
                    item
                    for item in self.report.issues
                    if item.family_key == self._active_issue_key
                ),
                None,
            )
        if issue is None:
            self._show_details_placeholder()
            self._update_action_buttons()
            return
        theme = get_theme()
        evidence_blocks = []
        for evidence in issue.evidence:
            metrics = self._kv_table(
                [
                    (str(key), self._format_metric(value))
                    for key, value in evidence.metrics.items()
                ]
            )
            if not evidence.metrics:
                metrics = ""
            evidence_blocks.append(
                '<div style="margin:0 0 10px 0;">'
                '<div style="font-size:13px;font-weight:600;">{}</div>'
                '<div style="color:{};font-size:12px;margin:2px 0 4px 0;">'
                "{}</div>{}</div>".format(
                    html.escape(evidence.rule_name),
                    theme["text_secondary"],
                    html.escape(evidence.message),
                    metrics,
                )
            )
        if not evidence_blocks:
            evidence_blocks.append(
                '<div style="color:{};font-size:12px;">{}</div>'.format(
                    theme["text_secondary"],
                    self.tr("本轮没有规则证据。"),
                )
            )
        payload = handoff_payload(issue)
        notes = [
            self.tr("检查只读；定位/导航不会修改标签或审核状态。"),
            self.tr("问题队列清空不能替代独立空间查漏。"),
        ]
        if payload.get("available"):
            notes.append(self.tr("可交接至密集复核工作区。"))
        else:
            notes.append(self.tr("密集复核不可用，请在普通画布处理。"))
        region = (
            ", ".join(f"{value:.1f}" for value in issue.location.region)
            if issue.location.region
            else self.tr("无")
        )
        objects = ", ".join(issue.location.object_ids) or self.tr("无")
        suggestion = issue.suggested_action or self.tr("无建议动作。")
        status_rows = self._kv_table(
            [
                (
                    self.tr("人工判断"),
                    html.escape(
                        _translate_label(
                            DECISION_LABELS.get(
                                issue.decision, issue.decision.value
                            )
                        )
                    ),
                ),
                (
                    self.tr("动作"),
                    html.escape(
                        _translate_label(
                            ACTION_LABELS.get(issue.action, issue.action.value)
                        )
                    ),
                ),
                (
                    self.tr("机器状态"),
                    html.escape(
                        _translate_label(
                            VERIFICATION_LABELS.get(
                                issue.verification,
                                issue.verification.value,
                            )
                        )
                    ),
                ),
            ]
        )
        sections = [
            self._section(self.tr("规则命中"), "".join(evidence_blocks)),
            self._section(
                self.tr("位置"),
                self._kv_table(
                    [
                        (
                            self.tr("文件"),
                            html.escape(issue.location.relative_path),
                        ),
                        (self.tr("对象"), html.escape(objects)),
                        (self.tr("区域"), html.escape(region)),
                    ]
                ),
            ),
            self._section(self.tr("建议"), html.escape(suggestion)),
            self._section(self.tr("状态"), status_rows),
            self._section(
                self.tr("备注"),
                '<div style="color:{};font-size:12px;line-height:1.7;">'
                "{}</div>".format(
                    theme["text_secondary"],
                    "<br/>".join(html.escape(note) for note in notes),
                ),
            ),
        ]
        body = (
            '<div style="font-size:13px;">'
            '<div style="font-size:16px;font-weight:600;color:{};'
            'margin:0 0 4px 0;">{}</div>'
            '<div style="color:{};font-size:12px;line-height:1.6;'
            'margin:0 0 16px 0;">{}</div>'
            "{}</div>"
        ).format(
            theme["text"],
            html.escape(issue.title),
            theme["text_secondary"],
            html.escape(issue.message),
            "".join(sections),
        )
        self._detail_body = body
        if not self.advanced_actions.isVisible():
            body = "<h3>{}</h3><p>{}</p>".format(
                html.escape(issue.title), html.escape(issue.message)
            )
        self.details.setHtml(body)
        self._update_action_buttons()

    def _install_shortcuts(self) -> None:
        self.start_shortcut = QtGui.QShortcut(QtGui.QKeySequence("F5"), self)
        self.start_shortcut.setContext(
            QtCore.Qt.ShortcutContext.WindowShortcut
        )
        self.start_shortcut.activated.connect(self._start_run_shortcut)
        self.locate_shortcut = QtGui.QShortcut(
            QtGui.QKeySequence(QtCore.Qt.Key.Key_Return),
            self.issue_table,
        )
        self.locate_shortcut.setContext(
            QtCore.Qt.ShortcutContext.WidgetShortcut
        )
        self.locate_shortcut.activated.connect(self._locate_selected)
        self._issue_shortcuts = []
        for owner in (self, self.host):
            for key, default, offset, button in (
                ("inspector_previous_issue", "F1", -1, self.prev_issue_button),
                ("inspector_next_issue", "F2", 1, self.next_issue_button),
            ):
                shortcut = QtGui.QShortcut(owner)
                shortcut.setContext(QtCore.Qt.ShortcutContext.WindowShortcut)
                shortcut.setAutoRepeat(False)
                shortcut.activated.connect(
                    lambda step=offset: self._select_issue(step)
                )
                self._issue_shortcuts.append((key, default, shortcut, button))
        self._refresh_shortcuts()

    def _refresh_shortcuts(self) -> None:
        config = self.host._config.get("shortcuts", {})
        existing = {
            QtGui.QKeySequence(s).toString()
            for s in self.host.existing_shortcut_sequences()
        }
        assigned = set()
        labels = []
        for key, default, shortcut in (
            ("inspector_run", "F5", self.start_shortcut),
            ("inspector_locate", "Return", self.locate_shortcut),
        ):
            value = config.get(key, default)
            if isinstance(value, (list, tuple)):
                value = value[0] if value else ""
            sequence = QtGui.QKeySequence(value or "")
            text = sequence.toString()
            allowed = bool(
                text and text not in existing and text not in assigned
            )
            shortcut.setKey(sequence)
            shortcut.setEnabled(allowed)
            if allowed:
                assigned.add(text)
            labels.append(text if allowed else self.tr("未绑定"))
        if labels == ["F5", "Return"]:
            hint = self.tr("F5 开始检查 · Enter 定位选中问题")
        else:
            hint = self.tr("{run} 开始检查 · {locate} 定位选中问题").format(
                run=labels[0], locate=labels[1]
            )
        self.shortcut_hint.setText(hint)
        self.start_button.setToolTip(hint)
        for key, default, shortcut, button in self._issue_shortcuts:
            value = config.get(key, default)
            if isinstance(value, (list, tuple)):
                value = value[0] if value else ""
            sequence = QtGui.QKeySequence(value or "")
            text = sequence.toString()
            other_key = (
                "inspector_next_issue"
                if key == "inspector_previous_issue"
                else "inspector_previous_issue"
            )
            other_default = (
                "F2" if other_key == "inspector_next_issue" else "F1"
            )
            other_value = config.get(other_key, other_default)
            if isinstance(other_value, (list, tuple)):
                other_value = other_value[0] if other_value else ""
            other_text = QtGui.QKeySequence(other_value or "").toString()
            allowed = bool(
                text
                and text not in existing
                and text not in assigned
                and text != other_text
            )
            shortcut.setKey(sequence)
            shortcut.setEnabled(allowed and self._session_open)
            label = (
                self.tr("上一个问题")
                if key == "inspector_previous_issue"
                else self.tr("下一个问题")
            )
            button.setText(label + (" (" + text + ")" if allowed else ""))
            button.setToolTip(label + (" (" + text + ")" if allowed else ""))
        self.shortcut_hint.setToolTip(
            self.tr("问题导航在主窗口和 Inspector 内生效。")
        )

    def showEvent(self, event) -> None:
        self._session_open = True
        self._refresh_shortcuts()
        super().showEvent(event)

    def _start_run_shortcut(self) -> None:
        if self.start_button.isEnabled():
            self._start_run()

    def _apply_icons(self) -> None:
        theme = get_theme()
        icons = (
            (self.start_button, "play", theme["selection_text"]),
            (self.locate_button, "scan-search", theme["text_secondary"]),
            (self.recheck_button, "rotate-cw", theme["text_secondary"]),
        )
        for button, name, color in icons:
            button.setIcon(themed_icon(name, color))
            button.setIconSize(QtCore.QSize(15, 15))

    def _locate_selected(self) -> None:
        issue = self._selected_issue()
        if issue is not None:
            self._navigate_issue(issue)

    def _set_decision(self, decision: Decision) -> None:
        issue = self._selected_issue()
        if issue is None or self.storage is None:
            return
        if issue.verification in (
            VerificationState.STALE,
            VerificationState.UNVERIFIABLE,
        ):
            self._show_error(
                self.tr("问题已过期"),
                self.tr(
                    "当前输入或配置已变化，请先复查当前图或重新运行检查，"
                    "再记录人工结论。"
                ),
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
        record = replace(
            record,
            dataset_key=self.storage.dataset_key,
            dataset_root=self.storage.dataset_root,
            output_root=self.storage.output_root,
            profile_fingerprint=(
                self.report.config_digest
                if self.report is not None
                else record.profile_fingerprint
            ),
            rule_versions=(
                self._report_rule_versions(self.report)
                if self.report is not None
                else dict(record.rule_versions)
            ),
        )
        if self._pending_feedback:
            pending = dict(self._pending_feedback)
            pending[record.family_key] = record
            if self._save_feedback_records(pending):
                self._pending_feedback = {}
                self.feedback[record.family_key] = record
                return True
            return False
        try:
            self.feedback_revision = self.storage.feedback.upsert(
                record, self.feedback_revision
            )
        except RevisionConflict as error:
            self._pending_feedback[record.family_key] = record
            self._show_error(
                self.tr("反馈冲突"),
                f"{error}\n冲突版本已保留：{error.conflict_path}",
            )
            self._load_feedback()
            self._set_status(
                self.tr(
                    "反馈未保存：另一窗口已更新。当前判断已保留在内存中，"
                    "可稍后重试保存。"
                )
            )
            return False
        except (OSError, StorageError) as error:
            self._pending_feedback[record.family_key] = record
            self._set_status(
                f"反馈尚未保存（保留在内存中，可稍后重试）: {error}"
            )
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

    def _retry_records(self):
        feedback_saved = (
            not self._pending_feedback
            or self._save_feedback_records(self._pending_feedback)
        )
        if feedback_saved and self._save_run():
            self._set_status(self.tr("检查记录已保存。"))

    def _save_and_recheck(self):
        if not self._navigation_allowed():
            return
        issue = next(
            (
                item
                for item in self.report.issues
                if item.family_key == self._active_issue_key
            ),
            None,
        )
        if (
            issue is None
            or issue.location.relative_path
            != self.host.inspection_current_relative_path()
        ):
            self._set_status(self.tr("请先定位当前问题，再保存并复查。"))
            return
        context = (
            self._navigation_serial,
            self._edit_serial,
            issue.family_key,
            issue.location.relative_path,
        )
        self._navigating = True
        try:
            # Use the same guarded save transaction as ordinary saving;
            # its Boolean result includes cancellation and write failure.
            if not self.host._save_file(self.host.get_label_file()):
                self._set_status(self.tr("保存未成功，未执行复查。"))
                return
        finally:
            self._navigating = False
        if context[:2] != (self._navigation_serial, self._edit_serial):
            return
        self._save_recheck_context = context
        self._recheck_selected(issue)

    def _recheck_selected(self, issue=None) -> None:
        issue = (
            issue
            if isinstance(issue, InspectionIssue)
            else self._selected_issue()
        )
        if issue is None:
            return
        if self.controller.is_running():
            return
        if (
            self.report is None
            or issue.location.relative_path
            != self.host.inspection_current_relative_path()
            or output_identity(self.report.output_root)
            != output_identity(self.host.inspection_output_dir())
        ):
            self._set_status(self.tr("请先定位当前问题，再保存并复查。"))
            self._save_recheck_context = None
            return
        manifest = self.host.inspection_current_manifest()
        if manifest is None:
            self._show_error(
                self.tr("复查"), self.tr("当前没有可复查的图片。")
            )
            return
        if self._active_profile is None:
            self._restore_profile_from_report(self.report)
        if self._active_profile is None:
            self._show_error(
                self.tr("复查"),
                self.tr(
                    "报告缺少可恢复的方案快照，无法安全复查；"
                    "请重新选择方案后运行检查。"
                ),
            )
            return
        profile = self._active_profile
        notes = []
        selected = self._selected_profile()
        if (
            selected is not None
            and selected.fingerprint() != profile.fingerprint()
        ):
            notes.append(
                "使用报告冻结方案 {} v{} 复查（与当前选择不同）".format(
                    profile.profile_id, profile.version
                )
            )
        if (
            self.report is not None
            and self.report.dataset_root
            and output_identity(self.report.dataset_root)
            != output_identity(self.host.inspection_dataset_root())
        ):
            self._show_error(
                self.tr("复查"),
                self.tr("报告数据集与当前数据集不一致，请重新检查。"),
            )
            return
        self._run_edit_serial = self._edit_serial
        self._recheck_issue = issue
        self._recheck_relative_path = issue.location.relative_path
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setRange(0, 0)
        self._set_status(self.tr("复查当前图片"))
        self.controller.start(
            profile,
            RunScope.CURRENT_IMAGE,
            dataset_root=self.host.inspection_dataset_root(),
            output_dir=self.host.inspection_output_dir(),
            manifest=manifest,
            allow_partial=False,
            generation=self._generation,
            scope_notes=notes,
        )
        context = self.controller.active_context
        self._run_context = context
        self._run_token = context.token if context else ""

    def _finish_recheck(self, report: RunReport, manifest) -> None:
        previous = self._recheck_issue
        self._recheck_issue = None
        if previous is None:
            return
        if self.report is None:
            self.report = report
            self.manifest = manifest
            self._populate_table()
            self._update_status()
            return
        self._load_feedback()
        relative_path = previous.location.relative_path
        result = merge_recheck_report(
            self.report,
            report,
            relative_path,
            selected_family_key=previous.family_key,
        )
        feedback_saved = self._persist_recheck_feedback(
            result, report, relative_path
        )
        self.report = result.report
        if manifest is not None:
            if (
                self.manifest is not None
                and dataset_identity(self.manifest.dataset_root)
                == dataset_identity(manifest.dataset_root)
                and output_identity(self.manifest.output_root)
                == output_identity(manifest.output_root)
            ):
                files = {
                    file.relative_path: file for file in self.manifest.files
                }
                files.update(
                    {file.relative_path: file for file in manifest.files}
                )
                replaced_paths = {
                    file.relative_path for file in manifest.files
                }
                self.manifest = replace(
                    self.manifest,
                    files=tuple(files[path] for path in sorted(files)),
                    errors=tuple(
                        e
                        for e in self.manifest.errors
                        if e.get("relative_path") not in replaced_paths
                    )
                    + manifest.errors,
                    complete=self.manifest.complete and manifest.complete,
                )
            else:
                self.manifest = manifest
            self.report = replace(
                self.report, manifest_fingerprint=self.manifest.fingerprint()
            )
        report_saved = self._save_run(self.report, self.manifest)
        self._populate_table()
        self._update_status()
        outcome_labels = {
            "re_detected": self.tr("重新检出，已回到待处理"),
            "not_detected": self.tr("成功复查，未再检出"),
            "unverifiable": self.tr("无法核验，保留原问题"),
            "not_selected": self.tr("未找到原问题，已保留队列"),
        }
        self._set_status(
            self.tr(
                "复查完成：{outcome}；来源 {sources} 个；保留其他图片问题 "
                "{preserved} 项。"
            ).format(
                outcome=outcome_labels.get(result.outcome, result.outcome),
                sources=len(result.sources),
                preserved=result.preserved_other_files,
            )
        )

        context = self._save_recheck_context
        self._save_recheck_context = None
        if (
            context is not None
            and context[0] == self._navigation_serial
            and context[1] == self._edit_serial
            and feedback_saved
            and report_saved
            and self.auto_advance.isChecked()
            and result.outcome == "not_detected"
        ):
            self._select_issue(1)

    def _persist_recheck_feedback(
        self, result, report: RunReport, relative_path: str
    ) -> bool:
        """Persist per-source verification outcomes for the rechecked file."""
        if self.storage is None:
            return False
        updates: dict[str, FeedbackRecord] = {}
        for issue in result.report.issues:
            if issue.location.relative_path != relative_path:
                continue
            old = self.feedback.get(issue.family_key)
            if old is None and issue.verification is VerificationState.CURRENT:
                continue
            history = list(old.history) if old else []
            if (
                old is not None
                and old.verification is issue.verification
                and old.decision is issue.decision
                and old.action is issue.action
            ):
                continue
            history.append(
                {
                    "at": QtCore.QDateTime.currentDateTime().toString(
                        QtCore.Qt.DateFormat.ISODate
                    ),
                    "decision": old.decision.value if old else "pending",
                    "action": old.action.value if old else "unchanged",
                    "verification": (
                        old.verification.value if old else "current"
                    ),
                    "event": "recheck_recorded",
                }
            )
            updates[issue.family_key] = FeedbackRecord(
                family_key=issue.family_key,
                issue_id=issue.issue_id,
                decision=issue.decision,
                action=issue.action,
                verification=issue.verification,
                note=old.note if old else "",
                evidence_digest=issue.location.snapshot_digest,
                updated_at=QtCore.QDateTime.currentDateTime().toString(
                    QtCore.Qt.DateFormat.ISODate
                ),
                history=tuple(history),
                dataset_key=self.storage.dataset_key,
                dataset_root=self.storage.dataset_root,
                output_root=self.storage.output_root,
                profile_fingerprint=result.report.config_digest,
                rule_versions=self._report_rule_versions(result.report),
            )
        if updates:
            return self._save_feedback_records(updates)
        return True

    @staticmethod
    def _report_rule_versions(report: RunReport) -> dict[str, str]:
        versions: dict[str, str] = {}
        for rule in report.profile_snapshot.get("rules", []) or []:
            if not isinstance(rule, Mapping):
                continue
            if not rule.get("enabled", True):
                continue
            versions[str(rule.get("rule_id", ""))] = str(
                rule.get("implementation_version", "")
            )
        return versions

    def _save_feedback_records(
        self, records: Mapping[str, FeedbackRecord]
    ) -> bool:
        if self.storage is None:
            return False
        merged = dict(self._pending_feedback)
        merged.update(self.feedback)
        merged.update(records)
        try:
            self.feedback_revision = self.storage.feedback.save(
                merged, self.feedback_revision
            )
        except RevisionConflict as error:
            self._pending_feedback.update(records)
            self._show_error(
                self.tr("反馈冲突"),
                f"{error}\n冲突版本已保留：{error.conflict_path}",
            )
            self._load_feedback()
            self._set_status(
                self.tr(
                    "反馈未保存：另一窗口已更新。当前判断已保留在内存中，"
                    "可稍后重试保存。"
                )
            )
            return False
        except (OSError, StorageError) as error:
            self._pending_feedback.update(records)
            self._set_status(
                f"反馈尚未保存（保留在内存中，可稍后重试）: {error}"
            )
            return False
        self._pending_feedback = {}
        self.feedback = merged
        return True

    def _delete_selected(self) -> None:
        issue = self._selected_issue()
        guard = self._target_guard_reason(issue) if issue is not None else ""
        if guard:
            self._show_error(self.tr("删除"), guard)
            return
        target_ids = self._selected_target_ids(issue)
        if issue is None or not target_ids:
            self._show_error(
                self.tr("删除"),
                self.tr(
                    "请先在画布中选中要删除的未锁定问题对象；"
                    "不会自动删除整对对象。"
                ),
            )
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            self.tr("删除确认"),
            self.tr(
                "文件：{file}\n仅删除以下画布选中对象（共 {count} 个）：\n"
                "{ids}\n\n未选中的对象会保留；此操作可通过撤销恢复。"
            ).format(
                file=issue.location.relative_path,
                count=len(target_ids),
                ids="\n".join(target_ids),
            ),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        if self._target_guard_reason(issue):
            return
        ok, reason = self.host.inspection_delete_shapes(
            target_ids,
            relative_path=issue.location.relative_path,
            dataset_root=self.host.inspection_dataset_root(),
            output_dir=self.host.inspection_output_dir(),
        )
        if not ok:
            self._show_error(self.tr("删除失败"), reason)
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
        guard = self._target_guard_reason(issue) if issue is not None else ""
        if guard:
            self._show_error(self.tr("重标"), guard)
            return
        target_ids = self._selected_target_ids(issue)
        if issue is None or not target_ids:
            self._show_error(
                self.tr("重标"),
                self.tr("请先在画布中选中要重标的未锁定问题对象。"),
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
                self.tr("重标选中框"),
                self.tr("目标类别："),
                labels,
                0,
                False,
            )
        else:
            label, ok = QtWidgets.QInputDialog.getText(
                self, self.tr("重标选中框"), self.tr("目标类别：")
            )
        if not ok or not label:
            return
        if self._target_guard_reason(issue):
            return
        success, reason = self.host.inspection_relabel_shapes(
            target_ids,
            label,
            relative_path=issue.location.relative_path,
            dataset_root=self.host.inspection_dataset_root(),
            output_dir=self.host.inspection_output_dir(),
        )
        if not success:
            self._show_error(self.tr("重标失败"), reason)
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

    def _keep_both(self) -> None:
        """Record that both boxes are legitimate without deleting either."""
        issue = self._selected_issue()
        if issue is None:
            return
        self._set_decision(Decision.ACCEPTABLE)
        self._update_issue(issue.family_key, action=ActionState.UNCHANGED)
        self._set_status(
            self.tr(
                "已记录「两者保留」：不会自动删除任何框；复查前仍显示该问题。"
            )
        )

    def _defer_issue(self) -> None:
        """Park a hard case for later discussion without changing shapes."""
        issue = self._selected_issue()
        if issue is None:
            return
        self._set_decision(Decision.NEEDS_DISCUSSION)
        self._set_status(
            self.tr("已暂存为疑难问题；可在筛选「需讨论」中继续处理。")
        )

    def _undo_last_edit(self) -> None:
        try:
            undo = self.host.actions.undo
        except AttributeError:
            return
        if not undo.isEnabled():
            self._set_status(self.tr("没有可撤销的编辑。"))
            return
        undo.trigger()
        self._on_canvas_edit()
        self._set_status(self.tr("已撤销上一次画布修改。"))

    def _current_file_issues(self) -> list[InspectionIssue]:
        if self.report is None:
            return []
        relative = self.host.inspection_current_relative_path()
        if not relative:
            return []
        return [
            issue
            for issue in self.report.issues
            if issue.location.relative_path == relative
            and issue.verification
            in (
                VerificationState.CURRENT,
                VerificationState.PENDING_RECHECK,
            )
        ]

    def _batch_target_shapes(
        self, issues: list[InspectionIssue], label: str = ""
    ) -> list:
        wanted_ids = {
            object_id
            for issue in issues
            for object_id in issue.location.object_ids
        }
        shapes = []
        for shape in self.host.canvas.shapes:
            if shape.locked:
                continue
            shape_id = str(getattr(shape, "xanylabeling_shape_id", "") or "")
            if shape_id and shape_id in wanted_ids:
                if label and shape.label != label:
                    continue
                shapes.append(shape)
        return shapes

    def _batch_delete(self) -> None:
        issue = self._selected_issue()
        guard = self._target_guard_reason(issue) if issue is not None else ""
        if guard:
            self._show_error(self.tr("批量删除"), guard)
            return
        issues = self._current_file_issues()
        shapes = self._batch_target_shapes(issues)
        deletable = [shape for shape in shapes if not shape.locked]
        if not deletable:
            self._show_error(
                self.tr("批量删除"),
                self.tr("当前图片没有可删除的问题对象。"),
            )
            return
        ids = sorted({str(shape.xanylabeling_shape_id) for shape in deletable})
        answer = QtWidgets.QMessageBox.question(
            self,
            self.tr("批量删除预览"),
            self.tr(
                "文件：{file}\n将删除 {count} 个未锁定对象（精确集合）：\n"
                "{ids}\n\n不会删除未列出的对象；可撤销。"
            ).format(
                file=self.host.inspection_current_relative_path(),
                count=len(ids),
                ids="\n".join(ids),
            ),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        ok, reason = self.host.inspection_delete_shapes(
            ids,
            relative_path=self.host.inspection_current_relative_path(),
            dataset_root=self.host.inspection_dataset_root(),
            output_dir=self.host.inspection_output_dir(),
        )
        if not ok:
            self._show_error(self.tr("批量删除失败"), reason)
            return
        for item in issues:
            old = self.feedback.get(item.family_key)
            record = (
                replace(
                    old,
                    action=ActionState.DELETED,
                    verification=VerificationState.PENDING_RECHECK,
                )
                if old
                else replace(
                    _new_feedback(item, Decision.CONFIRMED_ERROR),
                    action=ActionState.DELETED,
                    verification=VerificationState.PENDING_RECHECK,
                )
            )
            self._save_feedback(record)
        self._on_canvas_edit()
        self._set_status(
            self.tr("已批量删除 {count} 个问题对象；可撤销。").format(
                count=len(ids)
            )
        )

    def _batch_relabel(self) -> None:
        issue = self._selected_issue()
        guard = self._target_guard_reason(issue) if issue is not None else ""
        if guard:
            self._show_error(self.tr("批量重标"), guard)
            return
        issues = self._current_file_issues()
        shapes = [
            shape
            for shape in self._batch_target_shapes(issues)
            if not shape.locked
        ]
        if not shapes:
            self._show_error(
                self.tr("批量重标"),
                self.tr("当前图片没有可重标的问题对象。"),
            )
            return
        labels = sorted({shape.label for shape in shapes})
        source, ok = QtWidgets.QInputDialog.getItem(
            self,
            self.tr("批量重标预览"),
            self.tr("源类别（仅当前图片问题对象）："),
            labels,
            0,
            False,
        )
        if not ok or not source:
            return
        targets = [shape for shape in shapes if shape.label == source]
        target_labels = []
        try:
            for index in range(self.host.unique_label_list.count()):
                target_labels.append(
                    self.host.unique_label_list.item(index).label()
                )
        except (AttributeError, RuntimeError):
            target_labels = []
        if target_labels:
            target, ok = QtWidgets.QInputDialog.getItem(
                self,
                self.tr("批量重标预览"),
                self.tr("目标类别："),
                target_labels,
                0,
                False,
            )
        else:
            target, ok = QtWidgets.QInputDialog.getText(
                self, self.tr("批量重标预览"), self.tr("目标类别：")
            )
        if not ok or not target or target == source:
            return
        ids = sorted(
            {
                str(shape.xanylabeling_shape_id)
                for shape in targets
                if getattr(shape, "xanylabeling_shape_id", "")
            }
        )
        answer = QtWidgets.QMessageBox.question(
            self,
            self.tr("批量重标预览"),
            self.tr(
                "文件：{file}\n将把 {count} 个「{source}」对象改为"
                "「{target}」：\n{ids}\n\n其他类别、点、多边形与属性不变；"
                "可撤销。"
            ).format(
                file=self.host.inspection_current_relative_path(),
                count=len(ids),
                source=source,
                target=target,
                ids="\n".join(ids),
            ),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        success, reason = self.host.inspection_relabel_shapes(
            ids,
            target,
            relative_path=self.host.inspection_current_relative_path(),
            dataset_root=self.host.inspection_dataset_root(),
            output_dir=self.host.inspection_output_dir(),
        )
        if not success:
            self._show_error(self.tr("批量重标失败"), reason)
            return
        for item in issues:
            old = self.feedback.get(item.family_key)
            record = (
                replace(
                    old,
                    action=ActionState.RELABELED,
                    verification=VerificationState.PENDING_RECHECK,
                )
                if old
                else replace(
                    _new_feedback(item, item.decision),
                    action=ActionState.RELABELED,
                    verification=VerificationState.PENDING_RECHECK,
                )
            )
            self._save_feedback(record)
        self._on_canvas_edit()
        self._set_status(
            self.tr("已批量重标 {count} 个对象；可撤销。").format(
                count=len(ids)
            )
        )

    def _handoff_selected(self) -> None:
        """Hand one issue to the dense-review workspace, or say why not."""
        issue = self._selected_issue()
        if issue is None:
            return
        from anylabeling.services.inspection.handoff import (
            build_handoff_request,
            dense_review_available,
            handoff_unavailable_status,
            validate_handoff,
        )

        available = bool(
            getattr(self.host, "inspection_dense_review_available", None)
            and self.host.inspection_dense_review_available()
        )
        if not available:
            status = handoff_unavailable_status(
                "密集复核工作区不可用（未加载图片或模块不可导入）"
            )
            self._set_status(status["message"])
            QtWidgets.QMessageBox.information(
                self, self.tr("密集复核不可用"), status["message"]
            )
            return
        request = build_handoff_request(
            issue,
            dataset_root=self.host.inspection_dataset_root(),
            output_root=self.host.inspection_output_dir(),
        )
        reason = validate_handoff(
            request,
            dataset_root=self.host.inspection_dataset_root(),
            output_root=self.host.inspection_output_dir(),
            current_relative_path=(
                self.host.inspection_current_relative_path()
            ),
        )
        if reason:
            self._show_error(self.tr("交接密集复核"), reason)
            return
        handler = getattr(
            self.host, "inspection_handoff_to_dense_review", None
        )
        if handler is None:
            self._set_status(self.tr("当前窗口不支持密集复核交接。"))
            return
        ok, message = handler(request)
        if not ok:
            self._show_error(self.tr("交接密集复核"), message)
            return
        self._handoff_family_key = issue.family_key
        self._set_status(
            self.tr("已交接问题 {issue}；返回后仍定位原队列位置。").format(
                issue=issue.family_key[:12]
            )
        )

    def focus_family(self, family_key: str) -> bool:
        """Select the issue row for a family key after returning."""
        filtered = self._filtered_issues()
        if not any(issue.family_key == family_key for issue in filtered):
            self._apply_filter_state({})
            filtered = self._filtered_issues()
        if self.report is not None:
            for index, issue in enumerate(filtered):
                if issue.family_key == family_key:
                    self._issue_page = index // self._issue_page_size
                    self._populate_table()
                    break
        for row, issue in enumerate(self._row_issues):
            if issue.family_key == family_key:
                self.issue_table.selectRow(row)
                item = self.issue_table.item(row, 0)
                if item is not None:
                    self.issue_table.scrollToItem(item)
                self._set_status(self.tr("已回到原问题队列位置。"))
                return True
        self._populate_table()
        for row, issue in enumerate(self._row_issues):
            if issue.family_key == family_key:
                self.issue_table.selectRow(row)
                return True
        self._set_status(
            self.tr("原问题已不在当前队列；请查看运行记录后再决定。")
        )
        return False

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
                    self.tr("内存")
                    if self.report.source_kind == "memory"
                    else self.tr("磁盘")
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
                "对象 {objects}；问题图片 {images}/{files}；未处理 {pending}；"
                "已处理 {handled}；过期/不可核验 {stale}"
            ).format(
                objects=summary.get("object_count", 0),
                images=summary.get("image_count", 0),
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
                self.tr("历史报告核验：")
                + "；".join(self._verification_reasons[:5])
            )
        if self.report.scope_notes:
            notes.append(
                self.tr("范围说明：") + "；".join(self.report.scope_notes[:5])
            )
        if self._run_notes:
            notes.append(
                self.tr("运行说明：") + "；".join(self._run_notes[:5])
            )
        self.note_label.setText(" ".join(notes))

    def _toggle_notes(self) -> None:
        self._notes_visible = not self._notes_visible
        self.note_label.setVisible(self._notes_visible)
        self.note_toggle_button.setText(
            self.tr("收起说明") if self._notes_visible else self.tr("说明")
        )

    def _import_issues(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.tr("导入旧问题"),
            self.host.inspection_dataset_root(),
            self.tr("问题文件 (*.tsv *.csv *.json);;所有文件 (*)"),
        )
        if not path:
            return
        try:
            result = import_legacy_report(path, manifest=self.manifest)
        except (OSError, ValueError) as error:
            self._show_error(self.tr("导入失败"), str(error))
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
            f"导入 {len(result.issues)} 条（{result.format}）",
            f"错误 {len(result.errors)} 条",
            f"歧义 {len(result.ambiguous)} 条",
        ]
        summary.extend(result.warnings)
        if result.context:
            summary.append(
                "报告上下文：{} {} / {}".format(
                    result.context.get("run_id", ""),
                    result.context.get("dataset_root", ""),
                    result.context.get("profile_id", ""),
                )
            )
        QtWidgets.QMessageBox.information(
            self, self.tr("导入旧问题"), "\n".join(summary)
        )

    def _export_report(self) -> None:
        if self.report is None:
            self._show_error(
                self.tr("导出"), self.tr("当前没有可导出的报告。")
            )
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            self.tr("导出检查报告"),
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
            self._show_error(self.tr("导出失败"), str(error))
            return
        self._set_status(f"已导出：{path} 与 {tsv_path}（TSV 为简化格式）")

    def _import_candidates(self) -> None:
        if not self._ensure_storage() or self.storage is None:
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.tr("导入外部候选"),
            self.host.inspection_dataset_root(),
            self.tr("JSON (*.json);;所有文件 (*)"),
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
            self._show_error(self.tr("候选导入失败"), str(error))
            return
        self._load_candidates()
        records = dict(self._candidate_records)
        for candidate in result.candidates:
            records[candidate.candidate_id] = replace(
                candidate, dataset_key=self.storage.dataset_key
            )
        try:
            self._candidate_revision = self._candidate_store.save(
                records, self._candidate_revision
            )
        except (OSError, StorageError) as error:
            self._show_error(self.tr("候选保存失败"), str(error))
            return
        self._candidate_records = records
        self._populate_candidate_table()
        QtWidgets.QMessageBox.information(
            self,
            self.tr("候选导入"),
            self.tr("导入 {} 条，拒绝 {} 条，歧义 {} 条。").format(
                len(result.candidates),
                len(result.errors),
                len(result.ambiguous),
            ),
        )

    def _populate_candidate_table(self) -> None:
        self.candidate_table.blockSignals(True)
        try:
            self._fill_candidate_table()
        finally:
            self.candidate_table.blockSignals(False)
        self._sync_candidate_overlay()

    def _fill_candidate_table(self) -> None:
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
                _translate_label(
                    CANDIDATE_STATUS_LABELS.get(
                        candidate.status, candidate.status.value
                    )
                ),
                candidate.label,
                f"{candidate.relative_path} · {region_text}",
                f"{candidate.source} {score_text}".strip(),
            )
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(str(value))
                item.setToolTip(
                    "{}\n{}\n{}\n{}".format(
                        candidate.relative_path,
                        region_text,
                        candidate.candidate_id,
                        candidate.reason,
                    )
                )
                if column == 0:
                    item.setData(
                        QtCore.Qt.ItemDataRole.UserRole,
                        candidate.candidate_id,
                    )
                self.candidate_table.setItem(row, column, item)
        self._sync_candidate_overlay()

    def _sync_candidate_overlay(self) -> None:
        """Show only the selected candidate on the read-only overlay."""
        try:
            show = getattr(self.host, "show_inspection_candidates", None)
            clear = getattr(self.host, "clear_inspection_candidates", None)
            candidate = self._selected_candidate()
            if (
                candidate is None
                or candidate.status is CandidateStatus.ACCEPTED
                or not self._candidate_for_file(candidate)
            ):
                if clear is not None:
                    clear()
                return
            if show is not None:
                show([candidate])
        except (RuntimeError, AttributeError):
            # The window/canvas may already be closing; the overlay is not
            # worth aborting the GUI event loop over.
            return

    def _candidate_for_file(self, candidate) -> bool:
        return (
            candidate.relative_path
            == self.host.inspection_current_relative_path()
        )

    def _accept_candidate(self) -> None:
        candidate = self._selected_candidate()
        if candidate is None or self.storage is None:
            return
        if candidate.status is CandidateStatus.ACCEPTED:
            self._show_error(
                self.tr("候选"), self.tr("该候选已接受，不能重复新增。")
            )
            return
        if not self._candidate_for_file(candidate):
            self._show_error(
                self.tr("候选"),
                self.tr("候选属于 {path}，请先定位到该图片再接受。").format(
                    path=candidate.relative_path
                ),
            )
            return
        if self._candidate_store is None or self._intent_store is None:
            self._load_candidates()
        if self._candidate_store is None or self._intent_store is None:
            self._show_error(self.tr("候选"), self.tr("候选存储不可用。"))
            return
        self._accept_candidate_record(candidate)
        self._populate_candidate_table()
        self._clear_candidate_overlay()

    def _accept_candidate_record(self, candidate) -> bool:
        """Reserve an identity, apply once, and keep unsaved linkage on error."""
        if not self._candidate_for_file(candidate):
            return False
        self._reconcile_candidate_intents()
        current = self._candidate_records.get(
            candidate.candidate_id, candidate
        )
        if current.status is CandidateStatus.ACCEPTED:
            return False
        try:
            self._candidate_records[candidate.candidate_id] = current
            self._candidate_revision = self._candidate_store.save(
                self._candidate_records, self._candidate_revision
            )
            intent = self._intent_store.create(
                candidate.candidate_id,
                candidate.relative_path,
                new_shape_id(),
            )
        except (OSError, StorageError) as error:
            self._show_error(self.tr("候选"), str(error))
            return False
        shape_id = str(intent["preallocated_shape_id"])
        ok, payload = self.host.inspection_accept_candidate(
            candidate, shape_id
        )
        if not ok:
            try:
                self._intent_store.abandon(candidate.candidate_id)
            except (OSError, StorageError) as error:
                self._set_status(str(error))
            self._show_error(self.tr("接受候选失败"), str(payload))
            return False
        self._candidate_records[candidate.candidate_id] = replace(
            candidate,
            status=CandidateStatus.ACCEPTED,
            accepted_shape_id=str(payload),
            reason="已接受，标注尚未保存",
        )
        try:
            self._intent_store.applied(candidate.candidate_id)
            self._candidate_revision = self._candidate_store.save(
                self._candidate_records, self._candidate_revision
            )
        except (OSError, StorageError) as error:
            # The object already exists. Retain its ID and the durable intent
            # so retries/reopen reconcile instead of creating another object.
            self._set_status(self.tr("候选状态保存失败") + f": {error}")
        self._on_canvas_edit()
        return True

    def _on_annotation_saved(self) -> None:
        self._reconcile_candidate_intents()
        self._populate_candidate_table()

    def _accept_candidate_adjusted(self) -> None:
        """Preview coordinates/category before creating any formal object."""
        candidate = self._selected_candidate()
        if candidate is None:
            return
        editor = CandidateAdjustmentDialog(candidate, self)
        if editor.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        self._candidate_records[candidate.candidate_id] = editor.candidate()
        self._accept_candidate()
        selected = self._candidate_records.get(candidate.candidate_id)
        if selected is None or selected.status is not CandidateStatus.ACCEPTED:
            return
        shapes = {
            str(getattr(shape, "xanylabeling_shape_id", "") or ""): shape
            for shape in self.host.canvas.shapes
        }
        shape = shapes.get(selected.accepted_shape_id)
        if shape is not None:
            self.host.canvas.select_shapes([shape])
            self.host.canvas.update()
        self._set_status(
            self.tr(
                "已接受候选；画布中已选中新对象，可直接调整后按普通流程保存。"
            )
        )

    def _batch_accept_candidates(self) -> None:
        if self.storage is None or self._candidate_store is None:
            self._load_candidates()
        if self.storage is None or self._candidate_store is None:
            return
        relative = self.host.inspection_current_relative_path()
        pending = [
            candidate
            for candidate in self._candidate_records.values()
            if candidate.status is CandidateStatus.PENDING
            and candidate.relative_path == relative
        ]
        if not pending:
            self._show_error(
                self.tr("批量接受"),
                self.tr("当前图片没有待处理的候选。"),
            )
            return
        ids = sorted(candidate.candidate_id for candidate in pending)
        answer = QtWidgets.QMessageBox.question(
            self,
            self.tr("批量接受预览"),
            self.tr(
                "文件：{file}\n将接受 {count} 个候选（精确集合）：\n{ids}\n\n"
                "每个候选都会新增一个正式对象，均可撤销。"
            ).format(file=relative, count=len(ids), ids="\n".join(ids)),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        accepted = 0
        failed = []
        for candidate in sorted(pending, key=lambda item: item.candidate_id):
            if not self._accept_candidate_record(candidate):
                failed.append(candidate.candidate_id)
                continue
            accepted += 1
        self._populate_candidate_table()
        self._clear_candidate_overlay()
        if accepted:
            self._on_canvas_edit()
        self._set_status(
            self.tr("批量接受 {accepted} 个候选；失败 {failed} 个。").format(
                accepted=accepted, failed=len(failed)
            )
        )

    def _clear_candidate_overlay(self) -> None:
        clear = getattr(self.host, "clear_inspection_candidates", None)
        if clear is not None:
            clear()

    def _set_candidate_status(self, status: CandidateStatus) -> None:
        candidate = self._selected_candidate()
        if candidate is None or self._candidate_store is None:
            return
        try:
            self._candidate_store.mark(candidate, status)
        except (OSError, StorageError) as error:
            self._show_error(self.tr("候选状态保存失败"), str(error))
            return
        self._load_candidates()
        self._clear_candidate_overlay()

    def _save_session(self) -> None:
        if self.storage is None or self.report is None:
            return
        from anylabeling.services.inspection.models import ReviewSession

        issue = self._selected_issue()
        session = self._session
        if session is None or session.report_id != self.report.run_id:
            session = ReviewSession(
                report_id=self.report.run_id,
                dataset_root=self.storage.dataset_root,
                output_root=self.storage.output_root,
                dataset_key=self.storage.dataset_key,
            )
        cursor = {
            "issue_id": issue.issue_id if issue else "",
            "family_key": issue.family_key if issue else "",
            "relative_path": issue.location.relative_path if issue else "",
        }
        filters = {
            "queue": str(self.filter_combo.currentData()),
            "rule": str(self.rule_filter_combo.currentData() or ""),
            "source": str(self.source_filter_combo.currentData() or ""),
            "risk": str(self.risk_filter_combo.currentData() or ""),
        }
        try:
            self._session = self.storage.sessions.save(
                replace(
                    session,
                    dataset_root=self.storage.dataset_root,
                    output_root=self.storage.output_root,
                    dataset_key=self.storage.dataset_key,
                    cursor=cursor,
                    filters=filters,
                ),
                session.revision,
            )
            self._session_dirty = False
        except RevisionConflict as error:
            self._session_dirty = True
            self._load_session()
            self._set_status(
                "会话已被其他窗口修改；双方版本均已保留（{}），"
                "当前游标未保存。".format(error.conflict_path or "冲突文件")
            )
        except (OSError, StorageError) as error:
            self._session_dirty = True
            self._set_status(f"会话尚未保存（保留在内存中）: {error}")

    def _load_session(self) -> None:
        if self.storage is None:
            return
        try:
            session = self.storage.sessions.load()
        except (OSError, StorageError) as error:
            self._session = None
            self._set_status(f"会话读取失败: {error}")
            return
        if (
            session is not None
            and session.dataset_key
            and (session.dataset_key != self.storage.dataset_key)
        ):
            self._session = None
            self._set_status("会话属于另一数据集，未恢复队列位置")
            return
        self._session = session

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
            self._show_error(
                self.tr("继续处理"), self.tr("没有可恢复的检查报告。")
            )
            return
        self._load_report(str(entries[0].get("run_id", "")))

    def _load_report(self, run_id: str) -> None:
        if not run_id or self.storage is None:
            return
        try:
            report = self.storage.reports.load(run_id)
        except (
            OSError,
            StorageError,
            ValueError,
            UnicodeDecodeError,
        ) as error:
            self._show_error(
                self.tr("恢复失败"),
                self.tr(
                    "报告 {run_id} 无法恢复：{error}\n原文件保持未修改；"
                    "该报告范围内的人工结论不能作为当前结论。"
                ).format(run_id=run_id, error=error),
            )
            return
        missing_manifest = False
        try:
            self.manifest = self.storage.reports.load_manifest(run_id)
        except (OSError, StorageError):
            self.manifest = None
            missing_manifest = True
        self._load_feedback()
        self._load_candidates()
        self._load_session()
        self._duplicate_tracker = None
        self.report = self._apply_feedback_to_report(report)
        restored = self._show_report_profile(report)
        self._active_profile = (
            restored if restored is not None else self._active_profile
        )
        self._verification_reasons = ()
        self.report = self._apply_report_verification(self.report)
        if restored is None:
            self._verification_reasons = tuple(self._verification_reasons) + (
                "报告方案快照不可恢复，复查前请重新选择方案",
            )
        filters = {}
        if self._session is not None:
            if self._session.report_id not in ("", run_id):
                self._verification_reasons = tuple(
                    self._verification_reasons
                ) + ("会话游标属于另一份报告，未恢复问题位置",)
                self._session = None
            else:
                filters = dict(self._session.filters or {})
        self._apply_filter_state(filters)
        self._populate_table()
        if self._session is not None:
            family_key = str(
                (self._session.cursor or {}).get("family_key", "")
            )
            if family_key:
                self.focus_family(family_key)
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
        notes = []
        if missing_manifest:
            notes.append("缺少历史文件清单，无法核验当前输入")
        if stale:
            notes.append(f"{stale} 项因数据或配置变化过期，需重新检查")
        if restored is None:
            notes.append("报告方案快照损坏，不能直接复查")
        if self.report.profile_snapshot:
            current = self._selected_profile()
            frozen = self._profile_from_snapshot(report)
            if (
                current is not None
                and frozen is not None
                and current.fingerprint() != frozen.fingerprint()
            ):
                notes.append("当前选择与报告冻结方案不同；复查将使用冻结方案")
        self._set_status(
            "已恢复报告 {}。{}".format(
                run_id, "；".join(notes) if notes else ""
            )
        )

    def _apply_filter_state(self, filters: Mapping[str, Any]) -> None:
        for combo, key in (
            (self.filter_combo, "queue"),
            (self.rule_filter_combo, "rule"),
            (self.source_filter_combo, "source"),
            (self.risk_filter_combo, "risk"),
        ):
            value = str(filters.get(key, "") or "")
            index = combo.findData(value)
            if index >= 0:
                combo.blockSignals(True)
                combo.setCurrentIndex(index)
                combo.blockSignals(False)

    def _profile_from_snapshot(
        self, report: RunReport
    ) -> Optional[InspectionProfile]:
        snapshot = report.profile_snapshot.get("profile", {})
        if not isinstance(snapshot, Mapping) or not snapshot:
            return None
        try:
            return InspectionProfile.from_dict(dict(snapshot))
        except (TypeError, ValueError, KeyError):
            return None

    def _restore_profile_from_report(
        self, report: Optional[RunReport]
    ) -> Optional[InspectionProfile]:
        if report is None:
            return None
        frozen = self._profile_from_snapshot(report)
        if frozen is None:
            return None
        self._active_profile = frozen
        self._frozen_profile_id = frozen.profile_id
        return frozen

    def _show_report_profile(
        self, report: RunReport
    ) -> Optional[InspectionProfile]:
        profile = report.profile_snapshot.get("profile", {})
        if not isinstance(profile, Mapping):
            return None
        profile_id = str(profile.get("profile_id", ""))
        frozen = self._restore_profile_from_report(report)
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
        digest = report.profile_snapshot.get("snapshot_digest", "")
        self.profile_summary.setText(
            self.tr("历史方案：{} v{}；配置摘要 {}").format(
                profile.get("name", profile_id),
                profile.get("profile_version", "?"),
                digest[:12],
            )
        )
        self.rule_summary.setText("、".join(names))
        return frozen

    def _show_error(self, title: str, message: str) -> None:
        QtWidgets.QMessageBox.critical(self, title, message)

    def _set_status(self, message: str) -> None:
        self.status_label.setText(str(message))
        self.status_label.setToolTip(str(message))

    @staticmethod
    def _visible_geometry(rect, screens):
        if not screens:
            return rect
        screen = max(
            screens,
            key=lambda area: area.intersected(rect).width()
            * area.intersected(rect).height(),
        )
        width, height = min(rect.width(), screen.width()), min(
            rect.height(), screen.height()
        )
        return QtCore.QRect(
            max(screen.left(), min(rect.left(), screen.right() - width + 1)),
            max(screen.top(), min(rect.top(), screen.bottom() - height + 1)),
            width,
            height,
        )

    def _restore_window_preferences(self):
        value = self.host._config.get("inspector_window_geometry")
        if isinstance(value, (list, tuple)) and len(value) == 4:
            rect = QtCore.QRect(*map(int, value))
        else:
            rect = self.geometry()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        areas = [
            screen.availableGeometry()
            for screen in QtWidgets.QApplication.screens()
        ]
        rect = self._visible_geometry(rect, areas)
        self.setMinimumSize(min(880, rect.width()), min(560, rect.height()))
        self.setGeometry(rect)

    def _save_window_preferences(self, *args):
        rect = (
            self.normalGeometry()
            if self.isMaximized() or self.isMinimized()
            else self.geometry()
        )
        self.host.persist_user_preferences(
            {
                "inspector_window_geometry": [
                    rect.x(),
                    rect.y(),
                    rect.width(),
                    rect.height(),
                ],
                "inspector_auto_advance": self.auto_advance.isChecked(),
            }
        )

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        try:
            self.host.clear_inspection_candidates()
        except (AttributeError, RuntimeError):
            pass
        if self.controller.is_running():
            answer = QtWidgets.QMessageBox.question(
                self,
                self.tr("检查仍在运行"),
                self.tr("取消当前检查并关闭 Inspector？"),
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
            )
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.controller.cancel()
        self._save_window_preferences()
        self._session_open = False
        self._navigation_serial += 1
        self._refresh_shortcuts()
        super().closeEvent(event)


class CandidateAdjustmentDialog(QtWidgets.QDialog):
    """Edit a candidate draft; rejecting never changes the annotation."""

    def __init__(self, candidate: Candidate, parent=None):
        super().__init__(parent)
        self._candidate = candidate
        self.setWindowTitle(self.tr("调整后接受"))
        layout = QtWidgets.QFormLayout(self)
        self.label_edit = QtWidgets.QLineEdit(candidate.label)
        layout.addRow(self.tr("类别"), self.label_edit)
        self.coordinates = []
        for name, value, maximum in zip(
            ("X1", "Y1", "X2", "Y2"),
            candidate.region,
            (candidate.image_width, candidate.image_height) * 2,
        ):
            spin = QtWidgets.QDoubleSpinBox()
            spin.setRange(0, maximum)
            spin.setDecimals(6)
            spin.setValue(value)
            layout.addRow(name, spin)
            self.coordinates.append(spin)
        self.error_label = QtWidgets.QLabel()
        layout.addRow(self.error_label)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_draft)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def candidate(self) -> Candidate:
        return replace(
            self._candidate,
            label=self.label_edit.text().strip(),
            region=tuple(spin.value() for spin in self.coordinates),
        )

    def _accept_draft(self) -> None:
        candidate = self.candidate()
        x1, y1, x2, y2 = candidate.region
        if not candidate.label or x1 >= x2 or y1 >= y2:
            self.error_label.setText(self.tr("请输入类别和有效矩形坐标。"))
            return
        self.accept()


class ProfileRuleEditor(QtWidgets.QDialog):
    """Edit rule enablement and parameters of a custom profile copy.

    Built-in templates never reach this dialog: the Inspector requires a
    copy first, so a template file is never rewritten.
    """

    def __init__(
        self, profile, catalog, parent=None, *, read_only=False
    ) -> None:
        super().__init__(parent)
        self._profile = profile
        self._catalog = catalog
        self._result = None
        self._read_only = read_only
        self.setWindowTitle(self.tr("编辑检查方案：%s") % profile.name)
        self.resize(720, 520)
        layout = QtWidgets.QVBoxLayout(self)
        hint = QtWidgets.QLabel(
            self.tr(
                "勾选启用规则；参数为 JSON 对象。保存后生成新版本，"
                "历史报告保留原有效配置。"
            )
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [self.tr("启用"), self.tr("规则"), self.tr("参数（JSON）")]
        )
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.table.setColumnWidth(0, 56)
        self.table.setColumnWidth(1, 200)
        layout.addWidget(self.table, 1)
        self.error_label = QtWidgets.QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setObjectName("fieldLabel")
        layout.addWidget(self.error_label)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Save).setText(
            self.tr("保存")
        )
        buttons.button(
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        ).setText(self.tr("取消"))
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._populate()
        if read_only:
            hint.setText(
                self.tr(
                    "当前为只读查看；修改内置模板请先复制方案，再编辑副本。"
                )
            )
            for row in range(self.table.rowCount()):
                for column in range(self.table.columnCount()):
                    item = self.table.item(row, column)
                    item.setFlags(
                        item.flags()
                        & ~QtCore.Qt.ItemFlag.ItemIsEditable
                        & ~QtCore.Qt.ItemFlag.ItemIsUserCheckable
                    )
            buttons.button(
                QtWidgets.QDialogButtonBox.StandardButton.Save
            ).hide()

    def _known_rule_ids(self) -> list:
        known = [rule.rule_id for rule in self._profile.rules]
        for rule_id in self._catalog.rule_ids():
            if rule_id not in known:
                known.append(rule_id)
        return known

    def _populate(self) -> None:
        import json as _json

        configured = {rule.rule_id: rule for rule in self._profile.rules}
        self._rows = []
        for rule_id in self._known_rule_ids():
            meta = self._catalog.meta(rule_id)
            rule = configured.get(rule_id)
            row = self.table.rowCount()
            self.table.insertRow(row)
            check = QtWidgets.QTableWidgetItem()
            check.setFlags(
                QtCore.Qt.ItemFlag.ItemIsUserCheckable
                | QtCore.Qt.ItemFlag.ItemIsEnabled
            )
            enabled = bool(rule.enabled) if rule is not None else False
            check.setCheckState(
                QtCore.Qt.CheckState.Checked
                if enabled
                else QtCore.Qt.CheckState.Unchecked
            )
            self.table.setItem(row, 0, check)
            name = meta.name if meta else self.tr("%s（本机未登记）") % rule_id
            name_item = QtWidgets.QTableWidgetItem(name)
            name_item.setToolTip(
                (meta.description if meta else "") + f"\nrule_id: {rule_id}"
            )
            name_item.setData(QtCore.Qt.ItemDataRole.UserRole, rule_id)
            self.table.setItem(row, 1, name_item)
            parameters = dict(rule.parameters) if rule is not None else {}
            parameter_item = QtWidgets.QTableWidgetItem(
                _json.dumps(parameters, ensure_ascii=False)
            )
            if meta is not None:
                parameter_item.setToolTip(
                    "\n".join(
                        f"{item['name']}: {item.get('description', '')}"
                        for item in self._catalog.describe_parameters(rule_id)
                    )
                )
            self.table.setItem(row, 2, parameter_item)
            self._rows.append((rule_id, check, parameter_item))

    def _save(self) -> None:
        if self._read_only:
            return
        import json as _json

        from anylabeling.services.inspection.models import RuleConfig

        rules = []
        problems = []
        for rule_id, check, parameter_item in self._rows:
            enabled = check.checkState() == QtCore.Qt.CheckState.Checked
            raw = (parameter_item.text() or "").strip() or "{}"
            try:
                parameters = _json.loads(raw)
            except ValueError as error:
                problems.append(f"{rule_id}: 参数不是合法 JSON ({error})")
                continue
            if not isinstance(parameters, dict):
                problems.append(f"{rule_id}: 参数必须是 JSON 对象")
                continue
            rules.append(
                RuleConfig(
                    rule_id=rule_id,
                    enabled=enabled,
                    parameters=parameters,
                )
            )
        if problems:
            self.error_label.setText("\n".join(problems))
            return
        from dataclasses import replace as _replace

        self._result = _replace(
            self._profile,
            rules=tuple(rules),
            version=self._profile.version + 1,
        )
        self.accept()

    def result_profile(self):
        return self._result


def _new_feedback(issue: InspectionIssue, decision: Decision):
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
