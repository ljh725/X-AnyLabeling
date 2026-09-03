"""Application lifecycle controller for the derived dataset index."""

from __future__ import annotations

import logging
import os.path as osp
from dataclasses import replace
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from PyQt6 import QtCore

from .index import (
    DATASET_INDEX_READY,
    DatasetFilterIndex,
    DatasetIndexResult,
    install_staged_database,
    make_db_path,
    remove_database_files,
)
from .types import (
    DatasetIndexAutoRefreshPolicy,
    DatasetIndexContext,
    DatasetIndexState,
    DatasetThumbnailLocation,
    DatasetThumbnailPage,
)
from .worker import DatasetIndexWorker

logger = logging.getLogger(__name__)

START_REJECTED_BUSY = "busy"
START_REJECTED_NO_IMAGES = "no_images"
DEFAULT_AUTO_REFRESH_DELAY_MS = 1500

IndexFactory = Callable[..., DatasetFilterIndex]
WorkerFactory = Callable[..., DatasetIndexWorker]
DbPathFactory = Callable[[str], str]
DatabaseInstaller = Callable[[str, str], None]
DatabaseRemover = Callable[[Optional[str]], None]
PathIsFile = Callable[[str], bool]
TimerFactory = Callable[[QtCore.QObject], QtCore.QTimer]


class DatasetIndexController(QtCore.QObject):
    """Own dataset-index state, collaborators, and lifecycle transitions."""

    state_changed = QtCore.pyqtSignal(object, object)
    context_changed = QtCore.pyqtSignal(object)
    busy_changed = QtCore.pyqtSignal(bool)
    task_started = QtCore.pyqtSignal(str)
    start_rejected = QtCore.pyqtSignal(str)
    cancellation_requested = QtCore.pyqtSignal()
    progress_changed = QtCore.pyqtSignal(int, int, str)
    task_finished = QtCore.pyqtSignal(object)
    task_cancelled = QtCore.pyqtSignal(object)
    task_failed = QtCore.pyqtSignal(str)
    install_failed = QtCore.pyqtSignal(object, str)
    statuses_refresh_requested = QtCore.pyqtSignal()
    cache_attached = QtCore.pyqtSignal()
    label_sync_deferred = QtCore.pyqtSignal(str, str)
    file_refresh_finished = QtCore.pyqtSignal(str, bool, str)

    def __init__(
        self,
        *,
        index_factory: IndexFactory = DatasetFilterIndex,
        worker_factory: WorkerFactory = DatasetIndexWorker,
        db_path_factory: DbPathFactory = make_db_path,
        database_installer: DatabaseInstaller = install_staged_database,
        database_remover: DatabaseRemover = remove_database_files,
        path_is_file: PathIsFile = osp.isfile,
        auto_refresh_policy: (
            DatasetIndexAutoRefreshPolicy | str
        ) = DatasetIndexAutoRefreshPolicy.ON_CACHE_ATTACH,
        auto_refresh_delay_ms: int = DEFAULT_AUTO_REFRESH_DELAY_MS,
        timer_factory: TimerFactory = QtCore.QTimer,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        """Initialize the dataset-index lifecycle controller.

        Args:
            index_factory: Factory for main-thread query indexes.
            worker_factory: Factory for background index workers.
            db_path_factory: Factory for a dataset-owned cache path.
            database_installer: Atomic staging-database installer.
            database_remover: Cleanup callback for staging databases.
            path_is_file: Cache existence predicate.
            auto_refresh_policy: Policy controlling persisted-cache
                verification.
            auto_refresh_delay_ms: Delay before automatic cache verification.
            timer_factory: Factory for the controller-owned single-shot timer.
            parent: Optional Qt object owner.
        """
        super().__init__(parent)
        self._index_factory = index_factory
        self._worker_factory = worker_factory
        self._db_path_factory = db_path_factory
        self._database_installer = database_installer
        self._database_remover = database_remover
        self._path_is_file = path_is_file
        self._auto_refresh_policy = DatasetIndexAutoRefreshPolicy(
            auto_refresh_policy
        )
        self._auto_refresh_delay_ms = max(0, auto_refresh_delay_ms)
        self._state = DatasetIndexState.MISSING
        self._context = DatasetIndexContext()
        self._index: Optional[DatasetFilterIndex] = None
        self._worker: Optional[DatasetIndexWorker] = None
        self._retired_workers: set[DatasetIndexWorker] = set()
        self._mode: Optional[str] = None
        self._pending_refresh_files: set[str] = set()
        self._auto_refresh_root: Optional[str] = None
        self._auto_refresh_timer = timer_factory(self)
        self._auto_refresh_timer.setSingleShot(True)
        self._auto_refresh_timer.timeout.connect(self._on_auto_refresh_timeout)

    @property
    def state(self) -> DatasetIndexState:
        """Return the current typed lifecycle state."""
        return self._state

    @property
    def state_value(self) -> str:
        """Return the legacy string representation of the current state."""
        return self._state.value

    @property
    def is_busy(self) -> bool:
        """Return whether a background index task is active."""
        return self._worker is not None

    @property
    def auto_refresh_policy(self) -> DatasetIndexAutoRefreshPolicy:
        """Return the explicit automatic-refresh policy."""
        return self._auto_refresh_policy

    @property
    def retired_worker_count(self) -> int:
        """Return the number of asynchronously draining old workers."""
        return len(self._retired_workers)

    @property
    def is_query_ready(self) -> bool:
        """Return whether the active index connection can serve queries."""
        return self._index is not None and self._index.is_ready()

    @property
    def context(self) -> DatasetIndexContext:
        """Return the current immutable dataset context."""
        return self._context

    @property
    def index(self) -> Optional[DatasetFilterIndex]:
        """Return the active main-thread query index."""
        return self._index

    @property
    def worker(self) -> Optional[DatasetIndexWorker]:
        """Return the active background worker."""
        return self._worker

    @property
    def mode(self) -> Optional[str]:
        """Return the active operation mode."""
        return self._mode

    @property
    def pending_refresh_files(self) -> frozenset[str]:
        """Return an immutable view of deferred post-save refreshes."""
        return frozenset(self._pending_refresh_files)

    def set_auto_refresh_policy(
        self, policy: DatasetIndexAutoRefreshPolicy | str
    ) -> bool:
        """Replace the automatic-refresh policy.

        Args:
            policy: Typed policy or its persisted string value.

        Returns:
            True when the policy changed.
        """
        normalized = DatasetIndexAutoRefreshPolicy(policy)
        if normalized is self._auto_refresh_policy:
            return False
        self._auto_refresh_policy = normalized
        if normalized is DatasetIndexAutoRefreshPolicy.DISABLED:
            self._cancel_auto_refresh()
        else:
            self.schedule_auto_refresh()
        return True

    def set_state(self, state: DatasetIndexState | str) -> bool:
        """Set the lifecycle state and emit a typed transition.

        Args:
            state: Typed state or a compatible persisted string.

        Returns:
            True when the state changed, otherwise False.

        Raises:
            ValueError: If ``state`` is not a supported lifecycle value.
        """
        normalized = DatasetIndexState(state)
        if normalized == self._state:
            return False
        previous = self._state
        self._state = normalized
        self.state_changed.emit(previous, normalized)
        return True

    def set_context(
        self,
        dataset_root: Optional[str],
        output_dir: Optional[str],
        image_files: Sequence[str],
    ) -> bool:
        """Replace the complete dataset context.

        Args:
            dataset_root: Normalized root that owns the cache.
            output_dir: Optional directory containing annotation JSON files.
            image_files: Complete dataset image list in navigation order.

        Returns:
            True when the context changed, otherwise False.
        """
        context = DatasetIndexContext.create(
            dataset_root,
            output_dir,
            image_files,
        )
        return self._replace_context(context)

    def update_context(
        self,
        *,
        dataset_root: Optional[str] = None,
        output_dir: Optional[str] = None,
        image_files: Optional[Sequence[str]] = None,
        replace_dataset_root: bool = False,
        replace_output_dir: bool = False,
    ) -> bool:
        """Update selected context fields while keeping an immutable value.

        Args:
            dataset_root: Replacement dataset root.
            output_dir: Replacement annotation output directory.
            image_files: Optional replacement image-file snapshot.
            replace_dataset_root: Whether to replace ``dataset_root``.
            replace_output_dir: Whether to replace ``output_dir``.

        Returns:
            True when the context changed, otherwise False.
        """
        changes = {}
        if replace_dataset_root:
            changes["dataset_root"] = dataset_root
        if replace_output_dir:
            changes["output_dir"] = output_dir
        if image_files is not None:
            changes["image_files"] = tuple(image_files)
        if not changes:
            return False
        return self._replace_context(replace(self._context, **changes))

    def prepare_for_directory(
        self,
        dataset_root: str,
        output_dir: Optional[str],
        *,
        force: bool = False,
    ) -> bool:
        """Detach lifecycle state before switching dataset identity.

        Active work is cancelled cooperatively and retired without blocking the
        UI thread. Its eventual terminal signal can only clean temporary state;
        it cannot install results into the new dataset context.

        Args:
            dataset_root: Normalized root for the next dataset.
            output_dir: Current annotation output directory.
            force: Detach even if the dataset root is unchanged.

        Returns:
            True when a detach occurred, otherwise False.
        """
        if not force and self._context.dataset_root == dataset_root:
            return False
        self._cancel_auto_refresh()
        if self._worker is not None:
            self._retire_worker(self._worker)
        self.close_index()
        self._pending_refresh_files.clear()
        self.set_context(dataset_root, output_dir, ())
        self.set_state(DatasetIndexState.MISSING)
        return True

    def attach_existing(
        self,
        dataset_root: str,
        output_dir: Optional[str],
        image_files: Sequence[str],
    ) -> bool:
        """Attach a compatible cache without scanning annotation JSON files.

        Args:
            dataset_root: Normalized root that owns the cache.
            output_dir: Optional annotation output directory.
            image_files: Complete dataset image list.

        Returns:
            True when a compatible cache is attached.
        """
        if (
            self._index is not None
            and self._context.dataset_root == dataset_root
            and self._index.is_ready()
        ):
            if (
                self._index.snapshot_state() == DATASET_INDEX_READY
                and self._index.is_compatible(dataset_root, output_dir)
            ):
                self.set_context(dataset_root, output_dir, image_files)
                self.statuses_refresh_requested.emit()
                self.schedule_auto_refresh()
                return True
            self.close_index()

        self.set_context(dataset_root, output_dir, image_files)
        db_path = self._db_path_factory(dataset_root)
        if not self._path_is_file(db_path):
            self.set_state(DatasetIndexState.MISSING)
            return False

        index = self.create_index(db_path)
        if not index.open():
            self.set_state(DatasetIndexState.FAILED)
            return False
        if index.snapshot_state() != DATASET_INDEX_READY:
            index.close()
            self.set_state(DatasetIndexState.STALE)
            return False
        if not index.is_compatible(dataset_root, output_dir):
            index.close()
            self.set_state(DatasetIndexState.STALE)
            return False

        self.close_index()
        self._index = index
        self.set_state(DatasetIndexState.CACHED_UNVERIFIED)
        self.statuses_refresh_requested.emit()
        self.cache_attached.emit()
        self.schedule_auto_refresh()
        return True

    def schedule_auto_refresh(self) -> bool:
        """Schedule verification according to the configured policy.

        Returns:
            True when a refresh timer was scheduled.
        """
        if (
            self._auto_refresh_policy is DatasetIndexAutoRefreshPolicy.DISABLED
            or self._state is not DatasetIndexState.CACHED_UNVERIFIED
            or not self._context.dataset_root
        ):
            return False
        self._auto_refresh_root = self._context.dataset_root
        self._auto_refresh_timer.start(self._auto_refresh_delay_ms)
        return True

    def pause_pending_auto_refresh(self) -> bool:
        """Pause a scheduled verification without changing its policy.

        Returns:
            True when a pending timer was paused. Running workers are never
            cancelled by this method.
        """
        if not self._auto_refresh_timer.isActive():
            return False
        self._cancel_auto_refresh()
        return True

    def resume_pending_auto_refresh(self, was_paused: bool) -> bool:
        """Resume a caller-owned pause when verification is still relevant.

        Args:
            was_paused: Token returned by :meth:`pause_pending_auto_refresh`.

        Returns:
            True when verification was scheduled again.
        """
        if not was_paused:
            return False
        return self.schedule_auto_refresh()

    def refresh(self) -> bool:
        """Start an incremental index refresh for the current context."""
        return self._start("refresh")

    def rebuild(self) -> bool:
        """Start a full staged rebuild for the current context."""
        return self._start("rebuild")

    def cancel(self) -> None:
        """Request cooperative cancellation of the active worker."""
        if self._worker is None:
            return
        self._worker.cancel()
        self.cancellation_requested.emit()

    def label_saved(self, image_path: str) -> None:
        """Refresh one saved file or defer it until the worker finishes.

        Args:
            image_path: Image whose authoritative annotation JSON was saved.
        """
        if self._worker is not None:
            self._pending_refresh_files.add(image_path)
            return
        if self._index is None:
            return
        try:
            self._index.refresh_file(image_path, self._context.output_dir)
            self.file_refresh_finished.emit(image_path, True, "")
        except Exception as exc:  # noqa: BLE001
            self._pending_refresh_files.add(image_path)
            self.set_state(DatasetIndexState.STALE)
            logger.warning(
                "JSON saved but dataset index refresh failed for %s: %s",
                image_path,
                exc,
            )
            self.label_sync_deferred.emit(image_path, str(exc))
            self.file_refresh_finished.emit(image_path, False, str(exc))

    def file_statuses(
        self, image_files: Sequence[str]
    ) -> Dict[str, Tuple[str, str]]:
        """Return cached file statuses through the active query index.

        Args:
            image_files: Image paths whose cached status is requested.

        Returns:
            Mapping from image path to index status and JSON path.
        """
        if self._index is None:
            return {}
        return self._index.file_statuses(list(image_files))

    def query(self, filter_state: Any) -> List[str]:
        """Return image paths matching a filter-state snapshot.

        Args:
            filter_state: Immutable or caller-owned filter criteria snapshot.

        Returns:
            Matching image paths, or an empty list when no index is queryable.
        """
        if not self.is_query_ready:
            return []
        return self._index.query(filter_state)

    def query_shapes(self, filter_state: Any) -> Dict[str, List[int]]:
        """Return matching shape indexes grouped by image path.

        Args:
            filter_state: Immutable or caller-owned filter criteria snapshot.

        Returns:
            Shape indexes by image path, or an empty mapping when unavailable.
        """
        if not self.is_query_ready:
            return {}
        return self._index.query_shapes(filter_state)

    def query_label_counts(self) -> List[tuple[str, int]]:
        """Return indexed labels and counts when the cache is queryable."""
        if not self.is_query_ready:
            return []
        return self._index.query_label_counts()

    def query_thumbnail_objects(
        self, label: str, limit: int = 100, offset: int = 0
    ) -> DatasetThumbnailPage:
        """Return one bounded page of thumbnail references."""
        page_limit = max(1, min(int(limit), 100))
        page_offset = max(0, int(offset))
        if not self.is_query_ready:
            return DatasetThumbnailPage(
                label if isinstance(label, str) else "",
                0,
                page_limit,
                page_offset,
            )
        return self._index.query_thumbnail_objects(
            label, page_limit, page_offset
        )

    def query_thumbnail_location(
        self, image_path: str, shape_id: str
    ) -> Optional[DatasetThumbnailLocation]:
        """Return one object's label-relative position when queryable."""
        if (
            self.state is not DatasetIndexState.READY
            or not self.is_query_ready
        ):
            return None
        return self._index.query_thumbnail_location(image_path, shape_id)

    def close_index(self) -> None:
        """Close and release the active query connection."""
        if self._index is None:
            return
        self._index.close()
        self._index = None

    def create_index(
        self,
        db_path: str,
        *,
        journal_mode: Optional[str] = None,
    ) -> DatasetFilterIndex:
        """Create an index through the injected factory.

        Args:
            db_path: SQLite database path.
            journal_mode: Optional SQLite journal mode override.

        Returns:
            A new dataset filter index.
        """
        if journal_mode is None:
            return self._index_factory(db_path)
        return self._index_factory(db_path, journal_mode=journal_mode)

    def create_worker(
        self,
        mode: str,
        db_path: str,
        image_files: List[str],
        output_dir: Optional[str] = None,
        dataset_root: Optional[str] = None,
        parent: Optional[QtCore.QObject] = None,
    ) -> DatasetIndexWorker:
        """Create a worker through the injected factory.

        Args:
            mode: Operation mode, either ``refresh`` or ``rebuild``.
            db_path: Target SQLite database path.
            image_files: Complete dataset image list.
            output_dir: Optional annotation output directory.
            dataset_root: Root used to identify the cache snapshot.
            parent: Optional Qt object owner.

        Returns:
            A new dataset index worker.
        """
        return self._worker_factory(
            mode,
            db_path,
            image_files,
            output_dir,
            dataset_root,
            parent,
        )

    def _replace_context(self, context: DatasetIndexContext) -> bool:
        """Store and publish one immutable context snapshot."""
        if context == self._context:
            return False
        self._context = context
        self.context_changed.emit(context)
        return True

    def _start(self, mode: str) -> bool:
        """Create, connect, and start one worker for the current context."""
        if self._worker is not None:
            self.start_rejected.emit(START_REJECTED_BUSY)
            return False
        if not self._context.image_files:
            self.start_rejected.emit(START_REJECTED_NO_IMAGES)
            return False

        dataset_root = str(self._context.dataset_root or "")
        db_path = self._db_path_factory(dataset_root)
        if any(
            getattr(worker, "db_path", None) == db_path
            for worker in self._retired_workers
        ):
            self.start_rejected.emit(START_REJECTED_BUSY)
            return False

        self._cancel_auto_refresh()
        worker = self.create_worker(
            mode,
            db_path,
            list(self._context.image_files),
            self._context.output_dir,
            dataset_root,
            self,
        )
        self._worker = worker
        self._mode = mode
        self._connect_worker(worker)
        self.set_state(DatasetIndexState.SYNCING)
        self.busy_changed.emit(True)
        self.task_started.emit(mode)
        worker.start()
        return True

    def _connect_worker(self, worker: DatasetIndexWorker) -> None:
        """Connect worker terminal and progress signals to controller slots."""
        worker.progress_changed.connect(
            lambda current, total, filename, current_worker=worker: (
                self._on_worker_progress(
                    current_worker,
                    current,
                    total,
                    filename,
                )
            )
        )
        worker.finished.connect(
            lambda result, current_worker=worker: self._on_worker_finished(
                current_worker, result
            )
        )
        worker.cancelled.connect(
            lambda result, current_worker=worker: self._on_worker_cancelled(
                current_worker, result
            )
        )
        worker.failed.connect(
            lambda message, current_worker=worker: self._on_worker_failed(
                current_worker, message
            )
        )

    def _disconnect_worker(self, worker: DatasetIndexWorker) -> None:
        """Disconnect all controller-owned worker signal connections."""
        for signal in (
            worker.progress_changed,
            worker.finished,
            worker.cancelled,
            worker.failed,
        ):
            try:
                signal.disconnect()
            except TypeError:
                pass

    def _retire_worker(self, worker: DatasetIndexWorker) -> None:
        """Cancel an active worker and let it drain asynchronously."""
        if worker is not self._worker:
            return
        self._worker = None
        self._mode = None
        self._retired_workers.add(worker)
        worker.cancel()
        self.busy_changed.emit(False)

    def _finish_worker(self, worker: DatasetIndexWorker) -> None:
        """Release one active or retired worker after its terminal signal."""
        was_active = worker is self._worker
        self._disconnect_worker(worker)
        self._retired_workers.discard(worker)
        worker.deleteLater()
        if was_active:
            self._worker = None
            self._mode = None
            self.busy_changed.emit(False)

    def _on_worker_progress(
        self,
        worker: DatasetIndexWorker,
        current: int,
        total: int,
        filename: str,
    ) -> None:
        """Forward progress only for the active dataset generation."""
        if worker is self._worker:
            self.progress_changed.emit(current, total, filename)

    def _on_worker_finished(
        self,
        worker: DatasetIndexWorker,
        result: DatasetIndexResult,
    ) -> None:
        """Install a completed snapshot and reopen the query index."""
        worker_root = str(getattr(worker, "dataset_root", "") or "")
        current_root = str(self._context.dataset_root or "")
        if worker is not self._worker or (
            worker_root and worker_root != current_root
        ):
            self._database_remover(result.staged_db_path)
            self._finish_worker(worker)
            return

        db_path = result.target_db_path or self._db_path_factory(current_root)
        if result.staged_db_path:
            self.close_index()
            try:
                self._database_installer(result.staged_db_path, db_path)
            except OSError as exc:
                self._database_remover(result.staged_db_path)
                self._index = self.create_index(db_path)
                old_index_available = self._index.open()
                self.set_state(
                    DatasetIndexState.STALE
                    if old_index_available
                    else DatasetIndexState.FAILED
                )
                if old_index_available:
                    self.statuses_refresh_requested.emit()
                self.install_failed.emit(result, str(exc))
                self._finish_worker(worker)
                return
        else:
            self.close_index()

        self._index = self.create_index(db_path)
        if self._index.open():
            self._refresh_pending_files()
            self.set_state(DatasetIndexState.READY)
            self.statuses_refresh_requested.emit()
        else:
            self.set_state(DatasetIndexState.FAILED)
        self.task_finished.emit(result)
        self._finish_worker(worker)

    def _on_worker_cancelled(
        self,
        worker: DatasetIndexWorker,
        result: DatasetIndexResult,
    ) -> None:
        """Restore the previous query index after cancellation."""
        if worker is not self._worker:
            self._database_remover(result.staged_db_path)
            self._finish_worker(worker)
            return
        if self._index is not None:
            self._refresh_pending_files()
            self.set_state(DatasetIndexState.CACHED_UNVERIFIED)
        else:
            self.set_state(DatasetIndexState.MISSING)
        self.task_cancelled.emit(result)
        self._finish_worker(worker)

    def _on_worker_failed(
        self,
        worker: DatasetIndexWorker,
        message: str,
    ) -> None:
        """Preserve any old query index after a worker failure."""
        if worker is not self._worker:
            self._finish_worker(worker)
            return
        if self._index is not None:
            self._refresh_pending_files()
            self.set_state(DatasetIndexState.STALE)
        else:
            self.set_state(DatasetIndexState.FAILED)
        self.task_failed.emit(message)
        self._finish_worker(worker)

    def _cancel_auto_refresh(self) -> None:
        """Cancel any pending automatic cache verification."""
        self._auto_refresh_timer.stop()
        self._auto_refresh_root = None

    def _on_auto_refresh_timeout(self) -> None:
        """Start delayed verification if its dataset context is still active."""
        expected_root = self._auto_refresh_root
        self._auto_refresh_root = None
        if (
            self._auto_refresh_policy
            is not DatasetIndexAutoRefreshPolicy.ON_CACHE_ATTACH
            or self._state is not DatasetIndexState.CACHED_UNVERIFIED
            or self._context.dataset_root != expected_root
            or self._worker is not None
        ):
            return
        db_path = self._db_path_factory(str(expected_root or ""))
        if any(
            getattr(worker, "db_path", None) == db_path
            for worker in self._retired_workers
        ):
            self._auto_refresh_root = expected_root
            self._auto_refresh_timer.start(self._auto_refresh_delay_ms)
            return
        self.refresh()

    def _refresh_pending_files(self) -> None:
        """Apply saves made while a worker was running."""
        if self._index is None:
            return
        pending = sorted(self._pending_refresh_files)
        self._pending_refresh_files.clear()
        for image_path in pending:
            try:
                self._index.refresh_file(
                    image_path,
                    self._context.output_dir,
                )
                self.file_refresh_finished.emit(image_path, True, "")
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Deferred dataset index refresh failed for %s: %s",
                    image_path,
                    exc,
                )
                self._pending_refresh_files.add(image_path)
                self.set_state(DatasetIndexState.STALE)
                self.file_refresh_finished.emit(image_path, False, str(exc))


__all__ = [
    "DEFAULT_AUTO_REFRESH_DELAY_MS",
    "DatasetIndexController",
    "START_REJECTED_BUSY",
    "START_REJECTED_NO_IMAGES",
]
