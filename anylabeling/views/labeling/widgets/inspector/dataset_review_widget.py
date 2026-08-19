"""Inspector controls for the cross-file dataset review queue.

The widget is a pure view: it emits requests (create/open/close/rebuild/
reconcile/backup/cancel/outcomes/filters) and renders controller state
(scan progress, draft exclusions, current page tasks, counters,
warnings, recovery choices).  All strings go through Qt translation
calls with a stable context.
"""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtWidgets

from ...virtual_review import (
    BindingState,
    QueueFilter,
    TaskFreshness,
    TaskOutcome,
)

_FILTER_ITEMS = (
    (QueueFilter.ACTIONABLE, "待处理"),
    (QueueFilter.COMPLETED, "已完成"),
    (QueueFilter.NEEDS_REWORK, "需返工"),
    (QueueFilter.SKIPPED, "已跳过"),
    (QueueFilter.STALE, "已过期"),
    (QueueFilter.UNRESOLVED, "未解析"),
    (QueueFilter.ALL, "全部"),
)

_OUTCOME_LABELS = {
    TaskOutcome.COMPLETED: "已完成",
    TaskOutcome.NEEDS_REWORK: "需返工",
    TaskOutcome.SKIPPED: "已跳过",
    TaskOutcome.PENDING: "待处理",
}

_FRESHNESS_LABELS = {
    TaskFreshness.FRESH: "",
    TaskFreshness.STALE: " · 已过期",
    TaskFreshness.UNRESOLVED: " · 未解析",
}

_BINDING_LABELS = {
    BindingState.READY: "就绪",
    BindingState.CHANGED_RESOLVED: "已变更",
    BindingState.MANUALLY_BOUND: "手动绑定",
    BindingState.ORPHANED: "孤儿",
    BindingState.AMBIGUOUS: "歧义",
    BindingState.MISSING: "缺失",
}


def _tr(text: str) -> str:
    """Translate a dataset-review UI string with a stable context."""

    return QtCore.QCoreApplication.translate("DatasetReviewWidget", text)


class DatasetReviewWidget(QtWidgets.QWidget):
    """Dataset queue section embedded in the target-review tab."""

    create_requested = QtCore.pyqtSignal(str, object, object, object)
    open_requested = QtCore.pyqtSignal(str)
    open_readonly_requested = QtCore.pyqtSignal(str)
    close_requested = QtCore.pyqtSignal()
    rebuild_requested = QtCore.pyqtSignal()
    reconcile_requested = QtCore.pyqtSignal(object)
    backup_requested = QtCore.pyqtSignal(str)
    cancel_scan_requested = QtCore.pyqtSignal()
    outcome_requested = QtCore.pyqtSignal(str, object)
    complete_next_requested = QtCore.pyqtSignal()
    filter_changed = QtCore.pyqtSignal(str)
    manual_bind_requested = QtCore.pyqtSignal(str)
    takeover_confirmed = QtCore.pyqtSignal(str)
    takeover_declined = QtCore.pyqtSignal()
    retry_persistence_requested = QtCore.pyqtSignal()
    save_as_requested = QtCore.pyqtSignal(str)

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
        path_providers: Optional[dict] = None,
    ) -> None:
        """Build the dataset queue controls.

        ``path_providers`` injects file-dialog callables for tests:
        ``sidecar_save``, ``sidecar_open``, ``backup``, ``root``,
        ``save_as``.  Each returns a path string (empty cancels).
        """

        super().__init__(parent)
        self._takeover_path = ""
        self._task_ids: list[str] = []
        self._readonly = False
        self._confirm_handler = None
        self._cancel_handler = None
        providers = path_providers or {}
        self._provider_sidecar_save = providers.get(
            "sidecar_save", self._default_sidecar_save
        )
        self._provider_sidecar_open = providers.get(
            "sidecar_open", self._default_sidecar_open
        )
        self._provider_backup = providers.get("backup", self._default_backup)
        self._provider_root = providers.get("root", self._default_root)
        self._provider_save_as = providers.get(
            "save_as", self._default_save_as
        )
        self._build_ui()
        self.set_state("idle")

    # ── UI construction ──────────────────────────────────────

    def _build_ui(self) -> None:
        """Lay out the queue controls in one compact column."""

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QtWidgets.QLabel(_tr("数据集复核队列"))
        header.setStyleSheet("font-weight: bold;")
        layout.addWidget(header)

        lifecycle_row = QtWidgets.QHBoxLayout()
        self.create_button = QtWidgets.QPushButton(_tr("创建队列"))
        self.open_button = QtWidgets.QPushButton(_tr("打开队列"))
        self.close_button = QtWidgets.QPushButton(_tr("关闭队列"))
        self.cancel_scan_button = QtWidgets.QPushButton(_tr("取消扫描"))
        self.create_button.clicked.connect(self._emit_create)
        self.open_button.clicked.connect(self._emit_open)
        self.close_button.clicked.connect(self.close_requested.emit)
        self.cancel_scan_button.clicked.connect(
            self.cancel_scan_requested.emit
        )
        for widget in (
            self.create_button,
            self.open_button,
            self.close_button,
            self.cancel_scan_button,
        ):
            lifecycle_row.addWidget(widget)
        layout.addLayout(lifecycle_row)

        maintenance_row = QtWidgets.QHBoxLayout()
        self.rebuild_button = QtWidgets.QPushButton(_tr("重建队列"))
        self.reconcile_button = QtWidgets.QPushButton(_tr("调和队列"))
        self.backup_button = QtWidgets.QPushButton(_tr("备份"))
        self.rebuild_button.clicked.connect(self.rebuild_requested.emit)
        self.reconcile_button.clicked.connect(self._emit_reconcile)
        self.backup_button.clicked.connect(self._emit_backup)
        maintenance_row.addWidget(self.rebuild_button)
        maintenance_row.addWidget(self.reconcile_button)
        maintenance_row.addWidget(self.backup_button)
        layout.addLayout(maintenance_row)

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        self.progress_label = QtWidgets.QLabel("")
        self.progress_label.setWordWrap(True)
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)

        self.draft_label = QtWidgets.QLabel("")
        self.draft_label.setWordWrap(True)
        self.draft_label.setVisible(False)
        self.draft_confirm_button = QtWidgets.QPushButton(_tr("排除并发布"))
        self.draft_cancel_button = QtWidgets.QPushButton(_tr("取消"))
        self.draft_confirm_button.clicked.connect(self._confirm_draft_clicked)
        self.draft_cancel_button.clicked.connect(self._cancel_draft_clicked)
        self.draft_row_widget = QtWidgets.QWidget()
        draft_layout = QtWidgets.QHBoxLayout(self.draft_row_widget)
        draft_layout.setContentsMargins(0, 0, 0, 0)
        draft_layout.addWidget(self.draft_confirm_button)
        draft_layout.addWidget(self.draft_cancel_button)
        self.draft_row_widget.setVisible(False)
        layout.addWidget(self.draft_label)
        layout.addWidget(self.draft_row_widget)

        self.info_label = QtWidgets.QLabel(_tr("未打开队列"))
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        self.task_list = QtWidgets.QListWidget()
        self.task_list.setMaximumHeight(72)
        self.task_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        layout.addWidget(self.task_list)

        outcome_row = QtWidgets.QHBoxLayout()
        self.complete_button = QtWidgets.QPushButton(_tr("完成"))
        self.rework_button = QtWidgets.QPushButton(_tr("返工"))
        self.skip_button = QtWidgets.QPushButton(_tr("跳过"))
        self.reset_button = QtWidgets.QPushButton(_tr("重置"))
        self.complete_next_button = QtWidgets.QPushButton(_tr("完成并下一页"))
        self.bind_button = QtWidgets.QPushButton(_tr("手动绑定所选"))
        self.complete_button.clicked.connect(
            lambda: self._emit_outcome(TaskOutcome.COMPLETED)
        )
        self.rework_button.clicked.connect(
            lambda: self._emit_outcome(TaskOutcome.NEEDS_REWORK)
        )
        self.skip_button.clicked.connect(
            lambda: self._emit_outcome(TaskOutcome.SKIPPED)
        )
        self.reset_button.clicked.connect(
            lambda: self._emit_outcome(TaskOutcome.PENDING)
        )
        self.complete_next_button.clicked.connect(
            self.complete_next_requested.emit
        )
        self.bind_button.clicked.connect(self._emit_manual_bind)
        for widget in (
            self.complete_button,
            self.rework_button,
            self.skip_button,
            self.reset_button,
        ):
            outcome_row.addWidget(widget)
        layout.addLayout(outcome_row)
        action_row = QtWidgets.QHBoxLayout()
        action_row.addWidget(self.complete_next_button)
        action_row.addWidget(self.bind_button)
        layout.addLayout(action_row)

        filter_row = QtWidgets.QHBoxLayout()
        filter_row.addWidget(QtWidgets.QLabel(_tr("过滤")))
        self.filter_box = QtWidgets.QComboBox()
        for flt, label in _FILTER_ITEMS:
            self.filter_box.addItem(_tr(label), flt.value)
        self.filter_box.currentIndexChanged.connect(self._emit_filter)
        filter_row.addWidget(self.filter_box, stretch=1)
        layout.addLayout(filter_row)

        self.summary_label = QtWidgets.QLabel("")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.warning_label = QtWidgets.QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet("color: #b45309;")
        self.warning_label.setVisible(False)
        layout.addWidget(self.warning_label)

        recovery_row = QtWidgets.QHBoxLayout()
        self.takeover_button = QtWidgets.QPushButton(_tr("确认接管租约"))
        self.readonly_button = QtWidgets.QPushButton(_tr("只读诊断"))
        self.retry_button = QtWidgets.QPushButton(_tr("重试写入"))
        self.save_as_button = QtWidgets.QPushButton(_tr("另存副本"))
        self.takeover_button.clicked.connect(self._confirm_takeover)
        self.readonly_button.clicked.connect(self._emit_open_readonly)
        self.retry_button.clicked.connect(
            self.retry_persistence_requested.emit
        )
        self.save_as_button.clicked.connect(self._emit_save_as)
        self.rebind_root_button = QtWidgets.QPushButton(_tr("重选根目录调和"))
        self.rebind_root_button.clicked.connect(
            self.request_reconcile_with_root
        )
        recovery_row.addWidget(self.rebind_root_button)
        for widget in (
            self.takeover_button,
            self.readonly_button,
            self.retry_button,
            self.save_as_button,
        ):
            recovery_row.addWidget(widget)
        layout.addLayout(recovery_row)

    # ── default path providers (file dialogs) ────────────────

    def _default_sidecar_save(self) -> str:
        """Ask the reviewer for a new sidecar path."""

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            _tr("选择队列文件"),
            "",
            _tr("XReview 队列 (*.xreview.sqlite3)"),
        )
        return str(path)

    def _default_sidecar_open(self) -> str:
        """Ask the reviewer for an existing sidecar path."""

        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            _tr("打开队列文件"),
            "",
            _tr("XReview 队列 (*.xreview.sqlite3)"),
        )
        return str(path)

    def _default_backup(self) -> str:
        """Ask for a backup destination path."""

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            _tr("备份队列"),
            "",
            _tr("XReview 队列 (*.xreview.sqlite3)"),
        )
        return str(path)

    def _default_root(self) -> str:
        """Ask for a moved dataset root directory."""

        return str(
            QtWidgets.QFileDialog.getExistingDirectory(
                self, _tr("选择新的数据集根目录")
            )
        )

    def _default_save_as(self) -> str:
        """Ask for a save-as destination path."""

        return self._default_sidecar_save()

    # ── request emitters ─────────────────────────────────────

    def _emit_create(self) -> None:
        """Request queue creation with an empty criteria marker.

        The host glue resolves criteria/packing from the shared review
        form and the current viewport before calling the controller.
        """

        sidecar = self._provider_sidecar_save()
        if not sidecar:
            return
        self.create_requested.emit(sidecar, None, None, None)

    def _emit_open(self) -> None:
        """Request opening an existing queue."""

        path = self._provider_sidecar_open()
        if not path:
            return
        self.open_requested.emit(path)

    def _emit_open_readonly(self) -> None:
        """Request a read-only diagnostic open."""

        path = self._takeover_path or self._provider_sidecar_open()
        if not path:
            return
        self.open_readonly_requested.emit(path)

    def _emit_reconcile(self) -> None:
        """Request an in-place reconcile under the current root."""

        self.reconcile_requested.emit(None)

    def request_reconcile_with_root(self) -> None:
        """Request reconcile after choosing a new dataset root."""

        root = self._provider_root()
        if not root:
            return
        self.reconcile_requested.emit(root)

    def _emit_backup(self) -> None:
        """Request a validated backup copy."""

        destination = self._provider_backup()
        if not destination:
            return
        self.backup_requested.emit(destination)

    def _emit_save_as(self) -> None:
        """Request saving a separate copy and switching to it."""

        destination = self._provider_save_as()
        if not destination:
            return
        self.save_as_requested.emit(destination)

    def selected_task_ids(self) -> tuple:
        """Return the explicitly selected task ids in row order."""

        return tuple(self._task_ids)

    def _emit_outcome(self, outcome: TaskOutcome) -> None:
        """Emit an outcome for selected rows or the whole page."""

        selected = [
            self._task_ids[index.row()]
            for index in self.task_list.selectedIndexes()
        ]
        self.outcome_requested.emit(
            outcome.value, tuple(selected) if selected else None
        )

    def _emit_manual_bind(self) -> None:
        """Request manual binding for the first selected task."""

        selected = [
            self._task_ids[index.row()]
            for index in self.task_list.selectedIndexes()
        ]
        if not selected:
            self.set_warning(_tr("请先选择一个任务再手动绑定"))
            return
        self.manual_bind_requested.emit(selected[0])

    def _emit_filter(self) -> None:
        """Emit the newly selected filter name."""

        self.filter_changed.emit(str(self.filter_box.currentData()))

    # ── draft confirmation ───────────────────────────────────

    def set_draft_handlers(self, confirm, cancel) -> None:
        """Install draft confirmation callbacks (controller glue)."""

        self._confirm_handler = confirm
        self._cancel_handler = cancel

    def _confirm_draft_clicked(self) -> None:
        """Forward draft confirmation."""

        if self._confirm_handler is not None:
            self._confirm_handler()
        self.show_draft(None)

    def _cancel_draft_clicked(self) -> None:
        """Forward draft cancellation."""

        if self._cancel_handler is not None:
            self._cancel_handler()
        self.show_draft(None)

    # ── takeover prompt ──────────────────────────────────────

    def show_takeover_prompt(self, holder: dict, path: str) -> None:
        """Show the stale-lease takeover choice."""

        self._takeover_path = str(path)
        self.set_warning(
            _tr("写入租约疑似过期（实例 %s，PID %s）：请确认接管或只读打开")
            % (
                str(holder.get("instance_id", "?")),
                str(holder.get("pid", "?")),
            )
        )
        self.takeover_button.setVisible(True)
        self.readonly_button.setVisible(True)

    def _confirm_takeover(self) -> None:
        """Confirm the explicit lease takeover."""

        if self._takeover_path:
            self.takeover_confirmed.emit(self._takeover_path)
        self._takeover_path = ""
        self.clear_warning()

    def _decline_takeover(self) -> None:
        """Decline the takeover and keep the session closed."""

        self._takeover_path = ""
        self.takeover_declined.emit()

    # ── state rendering ──────────────────────────────────────

    def set_state(self, state_name: str) -> None:
        """Enable and disable controls for one controller state."""

        name = str(state_name)
        building = name in ("building", "rebuilding")
        session = name in (
            "opening",
            "reconciling",
            "active",
            "transitioning",
            "rebuilding",
            "persistence_blocked",
        )
        active = name == "active"
        mutation_allowed = active and not self._readonly
        for control in (
            self.complete_button,
            self.rework_button,
            self.skip_button,
            self.reset_button,
            self.complete_next_button,
            self.bind_button,
        ):
            control.setEnabled(mutation_allowed)
        self.create_button.setEnabled(name == "idle")
        self.open_button.setEnabled(name == "idle")
        self.close_button.setEnabled(session)
        self.cancel_scan_button.setEnabled(building)
        self.progress_bar.setVisible(building)
        self.progress_label.setVisible(building)
        self.rebuild_button.setEnabled(active)
        self.reconcile_button.setEnabled(active)
        self.rebind_root_button.setEnabled(active)
        self.backup_button.setEnabled(active)
        self.draft_label.setVisible(name == "draft_confirmation")
        self.draft_row_widget.setVisible(name == "draft_confirmation")
        self.retry_button.setVisible(name == "persistence_blocked")
        self.save_as_button.setVisible(name == "persistence_blocked")
        self.takeover_button.setVisible(False)
        self.readonly_button.setVisible(False)
        if not session:
            self.info_label.setText(_tr("未打开队列"))
            self.task_list.clear()
            self._task_ids = []
            self.summary_label.setText("")

    def set_readonly(self, readonly: bool) -> None:
        """Disable outcome mutations in read-only diagnostic mode."""

        self._readonly = bool(readonly)
        mutations = (
            self.complete_button,
            self.rework_button,
            self.skip_button,
            self.reset_button,
            self.complete_next_button,
            self.bind_button,
        )
        for widget in mutations:
            widget.setEnabled(not self._readonly)

    @property
    def readonly(self) -> bool:
        """Return whether the widget renders a read-only session."""

        return self._readonly

    def set_scan_progress(self, done: int, total: int, path: str) -> None:
        """Render scan progress for multi-file queues."""

        self.progress_bar.setRange(0, max(1, int(total)))
        self.progress_bar.setValue(int(done))
        self.progress_label.setText(
            _tr("扫描 %d/%d：%s") % (int(done), int(total), str(path))
        )

    def show_draft(self, draft) -> None:
        """Render draft exclusions requiring explicit confirmation."""

        if draft is None:
            self.draft_label.setVisible(False)
            self.draft_row_widget.setVisible(False)
            self.draft_label.setText("")
            return
        lines = [
            _tr("扫描完成：%d 文件，%d 任务，%d 页面")
            % (
                draft.stats.files_total,
                draft.stats.tasks,
                draft.stats.pages,
            )
        ]
        if draft.exclusions:
            reasons = ", ".join(
                f"{item.label_rel_path}({item.reason})"
                for item in draft.exclusions[:5]
            )
            lines.append(_tr("以下文件将被排除：%s") % reasons)
        self.draft_label.setText("\n".join(lines))
        self.draft_label.setVisible(True)
        self.draft_row_widget.setVisible(True)

    def set_current_page(
        self,
        source_label: str,
        page_index: int,
        page_total: int,
        tasks,
        runtime_bindings,
    ) -> None:
        """Render the current source file, page position, and tasks."""

        self.info_label.setText(
            _tr("来源：%s · 页面 %d/%d")
            % (str(source_label), int(page_index) + 1, int(page_total))
        )
        self._task_ids = []
        self.task_list.clear()
        for task in list(tasks)[:3]:
            binding = (runtime_bindings or {}).get(task.task_id)
            binding_state = getattr(binding, "state", task.binding_state)
            label = (
                task.locator.get("members")[0].get("label")
                if task.locator.get("members")
                else "?"
            )
            gid = task.locator.get("gid")
            summary = f"{label}" + (f"(gid {gid})" if gid else "")
            text = "%s · %s%s · %s" % (
                summary,
                _OUTCOME_LABELS.get(task.outcome, task.outcome.value),
                _FRESHNESS_LABELS.get(task.freshness, ""),
                _BINDING_LABELS.get(
                    binding_state,
                    getattr(binding_state, "value", str(binding_state)),
                ),
            )
            self.task_list.addItem(text)
            self._task_ids.append(task.task_id)

    def set_summary(self, summary, filter_name: str) -> None:
        """Render task/page counters and reduction statistics."""

        if summary is None:
            self.summary_label.setText("")
            return
        if summary.total_tasks == 0:
            self.summary_label.setText(_tr("队列为空"))
            return
        text = _tr("任务 %d · 待处理 %d · 完成 %d · 返工 %d · 跳过 %d") % (
            summary.total_tasks,
            summary.tasks_by_outcome.get("pending", 0),
            summary.tasks_by_outcome.get("completed", 0),
            summary.tasks_by_outcome.get("needs_rework", 0),
            summary.tasks_by_outcome.get("skipped", 0),
        )
        text += "\n" + _tr("页面 %d · 可操作 %d · 过期 %d · 未解析 %d") % (
            summary.total_pages,
            summary.actionable_pages,
            summary.stale_tasks,
            summary.unresolved_tasks,
        )
        if (
            filter_name == QueueFilter.ACTIONABLE.value
            and summary.actionable_tasks == 0
        ):
            text += "\n" + _tr("默认视图下没有剩余可处理工作")
        self.summary_label.setText(text)

    def set_warning(self, message: str) -> None:
        """Show a persistent warning line."""

        self.warning_label.setText(str(message))
        self.warning_label.setVisible(bool(message))

    def clear_warning(self) -> None:
        """Hide the warning line."""

        self.warning_label.setText("")
        self.warning_label.setVisible(False)


__all__ = ["DatasetReviewWidget"]
