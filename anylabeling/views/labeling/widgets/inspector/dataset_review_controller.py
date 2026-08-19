"""Dataset review queue controller: lifecycle, lease, safe navigation.

The controller owns the queue state machine, the writer lease and
heartbeat, guarded cross-file transitions, save-first outcome commits,
and persistence-blocked recovery.  Database, matching, and queue
algorithms stay in the pure ``virtual_review`` package; the host
(``LabelWidget`` or a test double) is reached only through the narrow
dataset-review host API.
"""

from __future__ import annotations

import enum
import os.path as osp
import sqlite3
from typing import Any, Optional

from PyQt6 import QtCore

from ...virtual_review import (
    BindingState,
    OutcomeChange,
    QueueBuildRequest,
    QueueFilter,
    QueueSnapshot,
    ReviewStore,
    StoreError,
    TaskOutcome,
    TRUSTED_BINDINGS,
    build_live_candidates,
    find_next_eligible,
    find_resume_target,
    reconcile_file_tasks,
    reconcile_source_file,
    resolve_relative_path,
    summarize_snapshot,
)
from ...virtual_review.models import (
    VirtualPackingOptions,
    VirtualReviewPage,
    VirtualTaskCriteria,
)
from .dataset_review_worker import DatasetQueueBuildWorker

HEARTBEAT_INTERVAL_MS = 30_000


class DatasetReviewState(enum.Enum):
    """Lifecycle states of the dataset queue controller."""

    IDLE = "idle"
    BUILDING = "building"
    DRAFT_CONFIRMATION = "draft_confirmation"
    OPENING = "opening"
    RECONCILING = "reconciling"
    ACTIVE = "active"
    TRANSITIONING = "transitioning"
    REBUILDING = "rebuilding"
    PERSISTENCE_BLOCKED = "persistence_blocked"
    CLOSED = "closed"


DATASET_MODE_STATES = frozenset(
    {
        DatasetReviewState.OPENING,
        DatasetReviewState.RECONCILING,
        DatasetReviewState.ACTIVE,
        DatasetReviewState.TRANSITIONING,
        DatasetReviewState.REBUILDING,
    }
)


class DatasetReviewController(QtCore.QObject):
    """Coordinate one dataset review queue session end to end."""

    status_changed = QtCore.pyqtSignal(str)
    state_changed = QtCore.pyqtSignal(str)
    scan_progress = QtCore.pyqtSignal(int, int, str)
    draft_ready = QtCore.pyqtSignal(object)
    takeover_prompt = QtCore.pyqtSignal(dict)
    error_reported = QtCore.pyqtSignal(str, str)
    session_changed = QtCore.pyqtSignal()

    def __init__(self, label_widget, local_controller) -> None:
        """Bind the controller to its host and local review controller."""

        super().__init__(label_widget)
        self._host = label_widget
        self._local = local_controller
        self._state = DatasetReviewState.IDLE
        self._store: Optional[ReviewStore] = None
        self._snapshot: Optional[QueueSnapshot] = None
        self._logical_revision = 0
        self._filter = QueueFilter.ACTIONABLE
        self._current_page_id: Optional[str] = None
        self._dataset_root = ""
        self._worker: Optional[DatasetQueueBuildWorker] = None
        self._draft = None
        self._rebuild_mode = False
        self._pending_direction = 0
        self._load_token = 0
        self._pending_open_path = ""
        self._pending_target_page_id: Optional[str] = None
        self._blocked_reason = ""
        self._manual_choices: dict[str, str] = {}
        self._runtime_bindings: dict[str, Any] = {}
        self._file_candidates: dict[str, tuple] = {}
        self._heartbeat = QtCore.QTimer(self)
        self._heartbeat.setInterval(HEARTBEAT_INTERVAL_MS)
        self._heartbeat.timeout.connect(self._on_heartbeat)
        finished = getattr(self._host, "dataset_review_load_finished", None)
        if finished is not None:
            finished.connect(self._on_load_finished)

    # ── state ────────────────────────────────────────────────

    @property
    def state(self) -> DatasetReviewState:
        """Return the current lifecycle state."""

        return self._state

    @property
    def session_active(self) -> bool:
        """Return whether a queue session owns the review focus."""

        return self._state in DATASET_MODE_STATES or (
            self._state is DatasetReviewState.PERSISTENCE_BLOCKED
        )

    @property
    def snapshot(self) -> Optional[QueueSnapshot]:
        """Return the active frozen snapshot, when loaded."""

        return self._snapshot

    @property
    def current_page_id(self) -> Optional[str]:
        """Return the last successfully activated page id."""

        return self._current_page_id

    @property
    def dataset_root(self) -> str:
        """Return the active dataset root hint."""

        return self._dataset_root

    @property
    def current_filter(self) -> QueueFilter:
        """Return the active navigation filter."""

        return self._filter

    @property
    def editable_session(self) -> bool:
        """Return whether the session accepts outcome mutations."""

        if self._store is None:
            return False
        return self._store.editable

    def runtime_bindings(self) -> dict:
        """Return a copy of the live runtime bindings."""

        return dict(self._runtime_bindings)

    def record_pending_open(self, path: str) -> None:
        """Remember the path of the most recent open attempt."""

        self._pending_open_path = str(path)

    @property
    def pending_open_path(self) -> str:
        """Return the most recently attempted sidecar path."""

        return self._pending_open_path

    def _set_state(self, state: DatasetReviewState) -> None:
        """Switch state and notify observers."""

        if state is self._state:
            return
        self._state = state
        self.state_changed.emit(state.value)
        self.session_changed.emit()

    def _status(self, message: str) -> None:
        """Publish a status line to the host and queue widget."""

        self.status_changed.emit(str(message))

    # ── creation and opening ─────────────────────────────────

    def create_queue(
        self,
        sidecar_path: str,
        criteria: VirtualTaskCriteria,
        packing_options: VirtualPackingOptions,
        reference_viewport: tuple,
    ) -> None:
        """Start building a new queue from the loaded dataset."""

        if self._state is not DatasetReviewState.IDLE:
            self._status("已有队列会话：请先关闭当前队列")
            return
        descriptors = self._host.dataset_review_descriptors()
        if not descriptors:
            self._status("未加载可扫描的数据集")
            return
        request = self._assemble_request(
            descriptors,
            criteria,
            packing_options,
            reference_viewport,
            sidecar_path,
        )
        self._rebuild_mode = False
        self._start_scan(request)

    def open_queue(self, path: str, takeover: bool = False) -> None:
        """Open an existing sidecar and resume at the durable cursor."""

        self.record_pending_open(str(path))
        if self.session_active:
            self._status("已有队列会话：请先关闭当前队列")
            return
        self._set_state(DatasetReviewState.OPENING)
        try:
            store = ReviewStore.open(str(path), takeover=takeover)
        except StoreError as exc:
            self._handle_open_failure(exc, path)
            return
        self._activate_store(store)
        self._resume_from_cursor()

    def open_readonly(self, path: str) -> None:
        """Open a sidecar read-only for diagnostics and summaries."""

        if self.session_active:
            self._status("已有队列会话：请先关闭当前队列")
            return
        self._set_state(DatasetReviewState.OPENING)
        try:
            store = ReviewStore.open(str(path), editable=False)
        except StoreError as exc:
            self._set_state(DatasetReviewState.IDLE)
            self.error_reported.emit("open_failed", str(exc))
            self._status(f"只读打开失败：{exc}")
            return
        self._activate_store(store)
        summary = summarize_snapshot(self._snapshot)
        self._set_state(DatasetReviewState.ACTIVE)
        self._status(
            "只读诊断模式：队列共 %d 个任务（可操作 %d）"
            % (summary.total_tasks, summary.actionable_tasks)
        )

    def _handle_open_failure(self, exc: StoreError, path: str) -> None:
        """Classify an open failure into recovery options for the UI."""

        self._set_state(DatasetReviewState.IDLE)
        from ...virtual_review import (
            IntegrityFailure,
            LeaseHeld,
            SchemaVersionTooNew,
        )

        if isinstance(exc, LeaseHeld):
            if exc.stale:
                self.takeover_prompt.emit(exc.holder)
                self._status(
                    "写入租约疑似过期（持有者 %s）：需显式确认接管"
                    % exc.holder.get("instance_id", "?")
                )
            else:
                self.error_reported.emit("lease_held", str(exc.holder))
                self._status("队列正被其他实例编辑：可选择只读诊断或另存副本")
            return
        if isinstance(exc, SchemaVersionTooNew):
            self.error_reported.emit(
                "schema_too_new",
                f"sidecar schema v{exc.version} 高于当前支持版本",
            )
            self._status("队列文件由更新版本创建：可只读诊断，不会修改")
            return
        if isinstance(exc, IntegrityFailure):
            self.error_reported.emit("integrity", "; ".join(exc.diagnostics))
            self._status("队列数据库完整性校验失败：可另存恢复副本")
            return
        self.error_reported.emit("open_failed", str(exc))
        self._status(f"打开队列失败：{exc}")

    def _activate_store(self, store: ReviewStore) -> None:
        """Adopt an opened store and load its active snapshot."""

        self._store = store
        self._logical_revision = store.logical_revision
        self._snapshot = store.load_snapshot()
        self._dataset_root = str(store.meta("dataset_root_hint") or "")
        cursor = store.load_cursor()
        if cursor is not None:
            self._filter = cursor.filter_name
        self._local.enter_dataset_mode()
        self._heartbeat.start()
        self._status(
            "队列已打开：修订 %d，%d 个页面"
            % (self._snapshot.revision, len(self._snapshot.pages))
        )

    def _resume_from_cursor(self) -> None:
        """Resolve the resume target and drive the first activation."""

        cursor = self._store.load_cursor()
        saved = cursor.page_id if cursor is not None else None
        plan = find_resume_target(self._snapshot, saved, self._filter)
        if plan.target is None:
            self._set_state(DatasetReviewState.ACTIVE)
            self._status(
                "默认过滤条件下没有可继续的工作：可切换过滤器查看全部"
            )
            return
        self._transition_to_page(plan.target)

    # ── scan / rebuild flow ──────────────────────────────────

    def _assemble_request(
        self,
        descriptors,
        criteria,
        packing_options,
        reference_viewport,
        sidecar_path,
    ) -> QueueBuildRequest:
        """Build the frozen scan request, failing closed on input."""

        return QueueBuildRequest(
            files=descriptors,
            criteria=criteria,
            packing_options=packing_options,
            reference_viewport=reference_viewport,
            sidecar_path=str(sidecar_path),
            app_version=self._app_version(),
        )

    def _app_version(self) -> str:
        """Return the application version string when available."""

        try:
            import anylabeling.app_info as app_info

            return str(app_info.__version__)
        except Exception:  # noqa: BLE001 - version is cosmetic here
            return ""

    def _start_scan(self, request: QueueBuildRequest) -> None:
        """Launch the build worker for a new queue or a rebuild."""

        self._set_state(
            DatasetReviewState.REBUILDING
            if self._rebuild_mode
            else DatasetReviewState.BUILDING
        )
        self._worker = DatasetQueueBuildWorker(request, self)
        self._worker.progress_reported.connect(self.scan_progress.emit)
        self._worker.draft_ready.connect(self._on_draft_ready)
        self._worker.scan_failed.connect(self._on_scan_failed)
        self._worker.start()
        self._status("正在扫描数据集…")

    def cancel_scan(self) -> None:
        """Request cancellation of the running scan."""

        if self._worker is not None:
            self._worker.request_cancel()
            self._status("正在取消扫描…")

    def _on_scan_failed(self, message: str) -> None:
        """Handle a scan failure without touching active state."""

        self._worker = None
        if self._rebuild_mode:
            self._set_state(DatasetReviewState.ACTIVE)
            self._rebuild_mode = False
        else:
            self._set_state(DatasetReviewState.IDLE)
        self.error_reported.emit("scan_failed", message)
        self._status(f"扫描失败：{message}")

    def _on_draft_ready(self, draft) -> None:
        """Stage the finished draft; confirm exclusions before publish."""

        self._worker = None
        self._draft = draft
        if draft.cancelled:
            self._draft = None
            if self._rebuild_mode:
                self._set_state(DatasetReviewState.ACTIVE)
                self._rebuild_mode = False
            else:
                self._set_state(DatasetReviewState.IDLE)
            self._status("已取消扫描：未修改当前队列")
            return
        if draft.diagnostics:
            self._discard_draft()
            message = "; ".join(draft.diagnostics)
            self._on_scan_failed(f"staging validation failed: {message}")
            return
        if draft.exclusions:
            self._set_state(DatasetReviewState.DRAFT_CONFIRMATION)
            self.draft_ready.emit(draft)
            return
        self.confirm_draft()

    def confirm_draft(self) -> None:
        """Publish the confirmed draft as new queue or new revision."""

        draft = self._draft
        if draft is None:
            return
        self._draft = None
        try:
            if self._rebuild_mode:
                result = self._publish_rebuild(draft)
                self._rebuild_mode = False
                self._reload_after_rebuild(result)
                return
            path = self._publish_new(draft)
        except (StoreError, ValueError, OSError) as exc:
            self._set_state(
                DatasetReviewState.ACTIVE
                if self._store is not None
                else DatasetReviewState.IDLE
            )
            self._rebuild_mode = False
            self.error_reported.emit("publish_failed", str(exc))
            self._status(f"发布队列失败：{exc}")
            return
        store = ReviewStore.open(path)
        self._activate_store(store)
        plan = find_resume_target(self._snapshot, None, self._filter)
        if plan.target is None:
            self._set_state(DatasetReviewState.ACTIVE)
            self._status("队列已创建：没有符合条件的页面")
            return
        self._transition_to_page(plan.target)

    def cancel_draft(self) -> None:
        """Discard the staged draft and keep the current queue."""

        self._discard_draft()
        if self._rebuild_mode:
            self._set_state(DatasetReviewState.ACTIVE)
            self._rebuild_mode = False
        else:
            self._set_state(DatasetReviewState.IDLE)
        self._status("已取消：当前队列保持不变")

    def _discard_draft(self) -> None:
        """Drop the draft reference and its staging database."""

        draft, self._draft = self._draft, None
        if draft is not None and draft.staging_path:
            import os

            for suffix in ("", "-wal", "-shm"):
                candidate = draft.staging_path + suffix
                if osp.exists(candidate):
                    try:
                        os.remove(candidate)
                    except OSError:
                        pass

    def _publish_new(self, draft) -> str:
        """Install a validated staging database as a new sidecar."""

        from ...virtual_review import publish_new_queue

        return publish_new_queue(draft)

    def _publish_rebuild(self, draft):
        """Import a validated staging revision into the open queue."""

        from ...virtual_review import publish_rebuild

        return publish_rebuild(draft, self._store, self._logical_revision)

    def _reload_after_rebuild(self, result) -> None:
        """Refresh state after a rebuild import and resume work."""

        self._logical_revision = result.logical_revision
        self._snapshot = self._store.load_snapshot()
        self._runtime_bindings = {}
        self._file_candidates = {}
        self._manual_choices = {}
        self._current_page_id = None
        plan = find_resume_target(self._snapshot, None, self._filter)
        if plan.target is None:
            self._set_state(DatasetReviewState.ACTIVE)
            self._status(
                "重建完成（携带 %d 项进度）：没有可继续页面"
                % result.detail.get("carried", 0)
            )
            return
        self._transition_to_page(plan.target)

    def rebuild_queue(
        self,
        criteria: VirtualTaskCriteria,
        packing_options: VirtualPackingOptions,
        reference_viewport: tuple,
    ) -> None:
        """Rescan the dataset and publish a new frozen revision."""

        if self._state is not DatasetReviewState.ACTIVE:
            self._status("仅活跃队列可以重建")
            return
        descriptors = self._host.dataset_review_descriptors()
        if not descriptors:
            self._status("未加载可扫描的数据集")
            return
        request = self._assemble_request(
            descriptors,
            criteria,
            packing_options,
            reference_viewport,
            self._store.path,
        )
        self._rebuild_mode = True
        self._start_scan(request)

    # ── navigation ───────────────────────────────────────────

    def next_page(self) -> None:
        """Navigate to the next eligible page (F2 across files)."""

        self._navigate(1)

    def previous_page(self) -> None:
        """Navigate to the previous eligible page (Shift+F2)."""

        self._navigate(-1)

    def _navigate(self, direction: int) -> None:
        """Run one guarded navigation step in the active filter."""

        if self._state is DatasetReviewState.TRANSITIONING:
            self._pending_direction = direction
            return
        if self._state is not DatasetReviewState.ACTIVE:
            return
        if self._host.dataset_review_edit_guard_active():
            self._status("请先完成或取消当前绘制/拖动/编辑操作")
            return
        plan = find_next_eligible(
            self._snapshot, self._current_page_id, self._filter, direction
        )
        if plan.target is None:
            if plan.message == "no_eligible_pages":
                self._status("当前过滤器下没有可导航页面")
            else:
                self._status(
                    "已经是最后一页" if direction > 0 else "已经是第一页"
                )
            return
        self._transition_to_page(plan.target)

    def _transition_to_page(self, page) -> None:
        """Resolve dirty state, load, rehydrate, and commit cursor."""

        if self._store is None or self._snapshot is None:
            return
        self._set_state(DatasetReviewState.TRANSITIONING)
        file_record = self._snapshot.file_by_id[page.file_id]
        target_image = resolve_relative_path(
            self._dataset_root, file_record.image_rel_path
        )
        current_image = self._host.dataset_review_current_image()
        if osp.normcase(str(current_image or "")) == osp.normcase(
            target_image
        ):
            if self._activate_page(page):
                self._finish_transition(page)
            else:
                self._reject_transition(page, "目标页面无法绑定到当前图片")
            return
        decision = self._host.dataset_review_resolve_dirty()
        if decision == "cancel":
            self._abort_transition("已取消：页面与进度保持不变")
            return
        if decision == "save_failed":
            self._abort_transition("保存失败：未切换文件，编辑内容仍在")
            return
        self._load_token += 1
        self._pending_target_page_id = page.page_id
        self._host.dataset_review_request_load(target_image, self._load_token)

    def _on_load_finished(
        self, path: str, ok: bool, token: int, cancelled: bool
    ) -> None:
        """Continue or roll back the pending cross-file transition."""

        if self._state is not DatasetReviewState.TRANSITIONING:
            return
        if int(token) != self._load_token:
            return
        page_id = self._pending_target_page_id
        self._pending_target_page_id = None
        page = self._snapshot.page_by_id.get(page_id)
        if page is None or cancelled or not ok:
            self._reject_transition(
                page,
                (
                    "目标文件加载失败：游标与进度保持不变"
                    if page is not None
                    else "目标页面已不存在"
                ),
            )
            return
        if self._activate_page(page):
            self._finish_transition(page)
        else:
            self._reject_transition(page, "目标页面无法重新绑定")

    def _activate_page(self, page) -> bool:
        """Rehydrate the page's file and install its runtime focus."""

        self._rehydrate_file(page.file_id)
        runtime_page = self._runtime_page(page)
        if runtime_page is None:
            return False
        index = next(
            (
                position
                for position, candidate in enumerate(self._snapshot.pages)
                if candidate.page_id == page.page_id
            ),
            page.order,
        )
        return self._local.install_dataset_page(
            runtime_page,
            (index, len(self._snapshot.pages), len(runtime_page.task_ids)),
        )

    def _finish_transition(self, page) -> None:
        """Commit the durable cursor and return to active state."""

        try:
            result = self._store.commit_cursor(
                self._snapshot.revision,
                page.page_id,
                self._filter,
                self._logical_revision,
            )
        except (StoreError, sqlite3.Error, OSError) as exc:
            self._enter_blocked(f"游标提交失败：{exc}")
            return
        self._logical_revision = result.logical_revision
        self._current_page_id = page.page_id
        self._set_state(DatasetReviewState.ACTIVE)
        if self._pending_direction:
            direction = self._pending_direction
            self._pending_direction = 0
            self._navigate(direction)

    def _abort_transition(self, message: str) -> None:
        """Return to active without changing cursor or outcomes."""

        self._pending_direction = 0
        self._pending_target_page_id = None
        self._set_state(DatasetReviewState.ACTIVE)
        self._status(message)

    def _reject_transition(self, page, message: str) -> None:
        """Keep the prior cursor and record an availability warning."""

        self._abort_transition(message)
        if page is not None:
            from ...virtual_review import FileReconcileReport

            report = FileReconcileReport(
                file_id=page.file_id, availability="missing"
            )
            try:
                result = self._store.record_reconciliation(
                    self._snapshot.revision,
                    [report],
                    self._logical_revision,
                )
                self._logical_revision = result.logical_revision
                self._snapshot = self._store.load_snapshot()
            except (StoreError, sqlite3.Error, OSError) as exc:
                self._enter_blocked(f"可用性记录失败：{exc}")

    # ── runtime rehydration ──────────────────────────────────

    def _rehydrate_file(self, file_id: str) -> None:
        """Rebuild runtime bindings for one file's stored tasks."""

        locators = {
            task.task_id: task.locator
            for task in self._snapshot.tasks
            if task.file_id == file_id
        }
        (
            views,
            points_by_id,
            _shape_map,
        ) = self._local.dataset_shape_payloads()
        candidates = build_live_candidates(
            views, points_by_id, VirtualTaskCriteria()
        )
        self._file_candidates[file_id] = candidates
        bindings = reconcile_file_tasks(
            locators, candidates, file_unchanged=False
        )
        self._runtime_bindings.update(bindings)

    def _runtime_page(self, page):
        """Build the image-local page carrying runtime shape ids."""

        member_ids: list[str] = []
        anchor_ids: list[str] = []
        live_tasks: list[str] = []
        for task_id in page.task_ids:
            binding = self._runtime_bindings.get(task_id)
            if binding is None or not binding.member_ids:
                continue
            member_ids.extend(binding.member_ids)
            anchor = getattr(binding, "anchor_id", None)
            anchor_ids.append(anchor or binding.member_ids[0])
            live_tasks.append(task_id)
        if not member_ids:
            return None
        return VirtualReviewPage(
            page_id=f"queue:{page.page_id}",
            task_ids=tuple(live_tasks),
            member_ids=tuple(member_ids),
            anchor_ids=tuple(anchor_ids),
            bbox=page.bbox,
            projected_scale=page.projected_scale,
        )

    # ── outcomes ─────────────────────────────────────────────

    def apply_outcome(self, outcome: str, task_ids=None) -> None:
        """Apply one explicit outcome, saving annotations first."""

        if self._state is not DatasetReviewState.ACTIVE:
            self._status("当前状态不允许修改复核结果")
            return
        if self._store is not None and not self._store.editable:
            self._status("只读诊断模式：无法修改复核结果")
            return
        if self._host.dataset_review_edit_guard_active():
            self._status("请先完成或取消当前编辑操作")
            return
        target_ids = self._resolve_outcome_targets(task_ids)
        if not target_ids:
            self._status("没有可应用该操作的已绑定任务")
            return
        untrusted = [
            task_id
            for task_id in target_ids
            if not self._binding_trusted(task_id)
        ]
        if untrusted:
            self._status("所选任务缺少可靠绑定：请先手动绑定或重新调和")
            return
        if not self._host.dataset_review_save_current():
            self._status("标注保存失败：复核结果未记录")
            return
        changes = []
        for task_id in target_ids:
            binding = self._runtime_bindings.get(task_id)
            signature = getattr(binding, "current_signature", None)
            changes.append(
                OutcomeChange(
                    task_id=task_id,
                    outcome=TaskOutcome(outcome),
                    reviewed_signature=signature,
                )
            )
        try:
            result = self._store.apply_outcomes(
                self._snapshot.revision,
                changes,
                self._logical_revision,
            )
        except (StoreError, sqlite3.Error, OSError) as exc:
            self._enter_blocked(f"进度写入失败：{exc}")
            self._status("进度写入失败：请重试或另存副本（标注已保存）")
            return
        self._logical_revision = result.logical_revision
        self._snapshot = self._store.load_snapshot()
        self._status("已记录复核结果")
        self.session_changed.emit()

    def complete_and_next(self) -> None:
        """Commit completion first, then perform an ordinary next."""

        self.apply_outcome(TaskOutcome.COMPLETED.value)
        if self._state is DatasetReviewState.ACTIVE:
            self.next_page()

    def _resolve_outcome_targets(self, task_ids) -> list:
        """Return explicit targets or the page's live-bound tasks."""

        if task_ids:
            return [
                str(task_id)
                for task_id in task_ids
                if task_id in self._runtime_bindings
            ]
        if self._current_page_id is None:
            return []
        page = self._snapshot.page_by_id.get(self._current_page_id)
        if page is None:
            return []
        return [
            task_id
            for task_id in page.task_ids
            if self._binding_trusted(task_id)
        ]

    def _binding_trusted(self, task_id: str) -> bool:
        """Return whether a task currently holds a trusted binding."""

        binding = self._runtime_bindings.get(task_id)
        if binding is None:
            return False
        return binding.state in TRUSTED_BINDINGS

    # ── reconcile and manual binding ─────────────────────────

    def reconcile(self, new_root: Optional[str] = None) -> None:
        """Refresh bindings and availability without repacking."""

        if self._state is not DatasetReviewState.ACTIVE:
            self._status("仅活跃队列可以调和")
            return
        self._set_state(DatasetReviewState.RECONCILING)
        root = str(new_root) if new_root else self._dataset_root
        reports = []
        for file_record in self._snapshot.files:
            locators = {
                task.task_id: task.locator
                for task in self._snapshot.tasks
                if task.file_id == file_record.file_id
            }
            reports.append(
                reconcile_source_file(
                    file_record,
                    root,
                    locators,
                    manual_choices=self._manual_choices,
                )
            )
        try:
            result = self._store.record_reconciliation(
                self._snapshot.revision,
                reports,
                self._logical_revision,
                dataset_root=root,
            )
        except (StoreError, sqlite3.Error, OSError) as exc:
            self._enter_blocked(f"调和写入失败：{exc}")
            return
        self._logical_revision = result.logical_revision
        self._dataset_root = root
        self._snapshot = self._store.load_snapshot()
        self._runtime_bindings = {}
        self._file_candidates = {}
        new_candidates = result.detail.get("new_candidates", 0)
        self._set_state(DatasetReviewState.ACTIVE)
        self._status(
            "调和完成：缺失文件 %d，重新绑定 %d，过期 %d，新候选 %d"
            % (
                result.detail.get("missing_files", 0),
                result.detail.get("rebound_tasks", 0),
                result.detail.get("stale", 0),
                new_candidates,
            )
        )
        if self._current_page_id is not None:
            page = self._snapshot.page_by_id.get(self._current_page_id)
            if page is not None:
                self._activate_page(page)

    def manual_bind_selected(self, task_id: str) -> None:
        """Bind one ambiguous task to its best remaining candidate."""

        if self._state is not DatasetReviewState.ACTIVE:
            return
        task = self._snapshot.task_by_id.get(str(task_id))
        if task is None:
            return
        candidates = self._file_candidates.get(task.file_id, ())
        claimed = {
            "|".join(binding.member_ids)
            for binding in self._runtime_bindings.values()
            if getattr(binding, "member_ids", None)
            and binding.state
            in (BindingState.READY, BindingState.CHANGED_RESOLVED)
        }
        chosen = next(
            (
                candidate
                for candidate in candidates
                if "|".join(candidate.task.member_ids) not in claimed
            ),
            None,
        )
        if chosen is None or not chosen.signature:
            self._status("没有可用于手动绑定的候选目标")
            return
        try:
            result = self._store.record_manual_binding(
                self._snapshot.revision,
                task.task_id,
                chosen.signature,
                self._logical_revision,
            )
        except (StoreError, sqlite3.Error, OSError) as exc:
            self._enter_blocked(f"手动绑定写入失败：{exc}")
            return
        self._logical_revision = result.logical_revision
        self._snapshot = self._store.load_snapshot()
        self._manual_choices[task.task_id] = chosen.signature
        self._rehydrate_file(task.file_id)
        if self._current_page_id is not None:
            page = self._snapshot.page_by_id.get(self._current_page_id)
            if page is not None:
                self._activate_page(page)
        self._status("已手动绑定所选任务")

    # ── filters and summaries ────────────────────────────────

    def set_filter(self, filter_name: str) -> None:
        """Switch the navigation filter (durable with next cursor)."""

        try:
            self._filter = QueueFilter(str(filter_name))
        except ValueError:
            return
        self._status("过滤器已切换：%s" % self._filter.value)

    # ── persistence-blocked recovery ─────────────────────────

    def _enter_blocked(self, reason: str) -> None:
        """Block further mutations while keeping state visible."""

        self._pending_direction = 0
        self._pending_target_page_id = None
        self._blocked_reason = reason
        self._set_state(DatasetReviewState.PERSISTENCE_BLOCKED)
        self.error_reported.emit("persistence_blocked", reason)

    @property
    def blocked_reason(self) -> str:
        """Return why persistence is blocked, when applicable."""

        return self._blocked_reason

    def retry_persistence(self) -> None:
        """Verify lease and revision, returning to active on success."""

        if self._state is not DatasetReviewState.PERSISTENCE_BLOCKED:
            return
        try:
            self._store.heartbeat()
            self._logical_revision = self._store.logical_revision
            self._snapshot = self._store.load_snapshot()
        except StoreError as exc:
            self._blocked_reason = str(exc)
            self._status(f"重试失败：{exc}")
            return
        self._blocked_reason = ""
        self._set_state(DatasetReviewState.ACTIVE)
        self._status("持久化已恢复")

    def save_as(self, new_path: str) -> None:
        """Write a separate copy and continue on the copy."""

        if self._store is None:
            return
        try:
            self._store.backup_to(str(new_path))
        except (StoreError, OSError) as exc:
            self.error_reported.emit("save_as_failed", str(exc))
            self._status(f"另存失败：{exc}")
            return
        self.close_queue(claim_saved=False)
        self.open_queue(str(new_path))

    def backup_to(self, destination: str) -> None:
        """Write a validated backup of the active queue."""

        if self._store is None:
            return
        try:
            self._store.backup_to(str(destination))
        except (StoreError, OSError) as exc:
            self.error_reported.emit("backup_failed", str(exc))
            self._status(f"备份失败：{exc}")
            return
        self._status("备份已写入：%s" % destination)

    # ── lifecycle ────────────────────────────────────────────

    def close_queue(self, claim_saved: bool = True) -> None:
        """Close the session, release the lease, and restore focus."""

        if self._worker is not None:
            self._worker.request_cancel()
            self._worker = None
        self._heartbeat.stop()
        unsaved_reason = self._blocked_reason
        if self._store is not None:
            try:
                self._store.close()
            except (StoreError, sqlite3.Error, OSError):
                pass
            self._store = None
        self._snapshot = None
        self._current_page_id = None
        self._runtime_bindings = {}
        self._file_candidates = {}
        self._manual_choices = {}
        self._pending_direction = 0
        self._pending_target_page_id = None
        self._blocked_reason = ""
        self._local.exit_dataset_mode()
        self._set_state(DatasetReviewState.CLOSED)
        if not claim_saved and unsaved_reason:
            self._status("已关闭：存在未保存的复核进度（%s）" % unsaved_reason)
        else:
            self._status("数据集复核队列已关闭")

    def shutdown(self) -> None:
        """Tear down without claiming progress; used on app close."""

        if self._store is not None or self._worker is not None:
            self.close_queue()
        elif self._state is not DatasetReviewState.IDLE:
            self._set_state(DatasetReviewState.IDLE)

    def _on_heartbeat(self) -> None:
        """Refresh the lease heartbeat or enter the blocked state."""

        if self._store is None:
            return
        try:
            self._store.heartbeat()
        except StoreError as exc:
            self._enter_blocked(f"写入租约失效：{exc}")

    def runtime_binding(self, task_id: str):
        """Return the runtime binding of one task for UI display."""

        return self._runtime_bindings.get(str(task_id))

    def current_page_tasks(self) -> list:
        """Return the current page's task records in slot order."""

        if self._snapshot is None or self._current_page_id is None:
            return []
        page = self._snapshot.page_by_id.get(self._current_page_id)
        if page is None:
            return []
        return [
            self._snapshot.task_by_id[task_id]
            for task_id in page.task_ids
            if task_id in self._snapshot.task_by_id
        ]

    def queue_summary(self):
        """Return the current summary of the active snapshot."""

        if self._snapshot is None:
            return None
        return summarize_snapshot(self._snapshot)


__all__ = ["DatasetReviewController", "DatasetReviewState"]
