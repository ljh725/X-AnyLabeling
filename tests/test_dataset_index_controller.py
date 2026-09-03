"""Tests for dataset-index controller ownership and lifecycle."""

from dataclasses import FrozenInstanceError

import pytest

from anylabeling.views.labeling.dataset_index import (
    DATASET_INDEX_CACHED,
    DATASET_INDEX_FAILED,
    DATASET_INDEX_MISSING,
    DATASET_INDEX_READY,
    DATASET_INDEX_STALE,
    DATASET_INDEX_SYNCING,
    DatasetIndexAutoRefreshPolicy,
    DatasetIndexContext,
    DatasetIndexResult,
    DatasetIndexState,
    DatasetThumbnailLocation,
)
from anylabeling.views.labeling.dataset_index.controller import (
    DatasetIndexController,
)


class FakeSignal:
    """Provide the minimal connect/disconnect/emit signal contract."""

    def __init__(self) -> None:
        """Initialize an empty callback list."""
        self.callbacks = []

    def connect(self, callback) -> None:
        """Register one callback."""
        self.callbacks.append(callback)

    def disconnect(self) -> None:
        """Remove every registered callback."""
        self.callbacks.clear()

    def emit(self, *args) -> None:
        """Invoke a stable snapshot of registered callbacks."""
        for callback in list(self.callbacks):
            callback(*args)


class FakeTimer:
    """Provide a deterministic single-shot timer contract."""

    def __init__(self, _parent) -> None:
        """Initialize an inactive timer."""
        self.timeout = FakeSignal()
        self.active = False
        self.interval = None
        self.single_shot = False

    def setSingleShot(self, enabled: bool) -> None:
        """Record the single-shot setting."""
        self.single_shot = enabled

    def start(self, interval: int) -> None:
        """Record and activate one timer."""
        self.interval = interval
        self.active = True

    def stop(self) -> None:
        """Deactivate the timer."""
        self.active = False

    def isActive(self) -> bool:
        """Return the recorded active state."""
        return self.active


class FakeIndex:
    """Record lifecycle and refresh calls for an injected index."""

    def __init__(
        self,
        db_path: str,
        journal_mode: str = "wal",
        *,
        open_result: bool = True,
    ) -> None:
        """Store requested database settings and default behavior."""
        self.db_path = db_path
        self.journal_mode = journal_mode
        self.open_result = open_result
        self.closed = False
        self.refresh_calls = []
        self.fail_refresh = False
        self.query_result = []
        self.query_shapes_result = {}
        self.query_calls = []
        self.query_shapes_calls = []
        self.thumbnail_location_result = None
        self.thumbnail_location_calls = []

    def open(self) -> bool:
        """Return the configured open result."""
        self.closed = False
        return self.open_result

    def close(self) -> None:
        """Record connection closure."""
        self.closed = True

    def is_ready(self) -> bool:
        """Report an open query connection."""
        return self.open_result and not self.closed

    @staticmethod
    def snapshot_state() -> str:
        """Report a completed cache snapshot."""
        return DATASET_INDEX_READY

    @staticmethod
    def is_compatible(_dataset_root: str, _output_dir: str | None) -> bool:
        """Accept the requested dataset identity."""
        return True

    @staticmethod
    def file_statuses(_image_files: list[str]) -> dict:
        """Return no cached UI statuses for unit tests."""
        return {}

    def refresh_file(self, image_path: str, output_dir: str | None) -> None:
        """Record a refresh or raise the configured cache failure."""
        if self.fail_refresh:
            raise RuntimeError("cache unavailable")
        self.refresh_calls.append((image_path, output_dir))

    def query(self, filter_state) -> list[str]:
        """Record and answer one file-level query."""
        self.query_calls.append(filter_state)
        return list(self.query_result)

    def query_shapes(self, filter_state) -> dict[str, list[int]]:
        """Record and answer one shape-level query."""
        self.query_shapes_calls.append(filter_state)
        return dict(self.query_shapes_result)

    def query_thumbnail_location(self, image_path: str, shape_id: str):
        """Record and answer one object-location query."""
        self.thumbnail_location_calls.append((image_path, shape_id))
        return self.thumbnail_location_result


class FakeIndexFactory:
    """Create inspectable fake indexes with queued open results."""

    def __init__(self, open_results: list[bool] | None = None) -> None:
        """Initialize queued open results."""
        self.open_results = list(open_results or [])
        self.created = []

    def __call__(self, db_path: str, journal_mode: str = "wal") -> FakeIndex:
        """Create and retain one fake index."""
        open_result = self.open_results.pop(0) if self.open_results else True
        index = FakeIndex(
            db_path,
            journal_mode,
            open_result=open_result,
        )
        self.created.append(index)
        return index


class FakeWorker:
    """Provide an inspectable worker with manually emitted terminal signals."""

    def __init__(
        self,
        mode: str,
        db_path: str,
        image_files: list[str],
        output_dir: str | None,
        dataset_root: str | None,
        parent: object,
    ) -> None:
        """Store worker settings and initialize fake signals."""
        self.mode = mode
        self.db_path = db_path
        self.image_files = list(image_files)
        self.output_dir = output_dir
        self.dataset_root = dataset_root
        self.parent = parent
        self.progress_changed = FakeSignal()
        self.finished = FakeSignal()
        self.cancelled = FakeSignal()
        self.failed = FakeSignal()
        self.started = False
        self.cancel_called = False
        self.wait_called = False
        self.delete_called = False

    def start(self) -> None:
        """Record worker start."""
        self.started = True

    def cancel(self) -> None:
        """Record cooperative cancellation."""
        self.cancel_called = True

    def wait(self) -> None:
        """Record synchronous worker join."""
        self.wait_called = True

    def deleteLater(self) -> None:
        """Record deferred QObject deletion."""
        self.delete_called = True


class FakeWorkerFactory:
    """Create and retain inspectable fake workers."""

    def __init__(self) -> None:
        """Initialize the created-worker list."""
        self.created = []

    def __call__(
        self,
        mode: str,
        db_path: str,
        image_files: list[str],
        output_dir: str | None,
        dataset_root: str | None,
        parent: object,
    ) -> FakeWorker:
        """Create and retain one fake worker."""
        worker = FakeWorker(
            mode,
            db_path,
            image_files,
            output_dir,
            dataset_root,
            parent,
        )
        self.created.append(worker)
        return worker


def _controller(
    *,
    index_factory: FakeIndexFactory | None = None,
    worker_factory: FakeWorkerFactory | None = None,
    installer=None,
    remover=None,
    path_is_file=None,
    auto_refresh_policy=DatasetIndexAutoRefreshPolicy.DISABLED,
) -> tuple[DatasetIndexController, FakeIndexFactory, FakeWorkerFactory]:
    """Build a controller with deterministic fake collaborators."""
    indexes = index_factory or FakeIndexFactory()
    workers = worker_factory or FakeWorkerFactory()
    controller = DatasetIndexController(
        index_factory=indexes,
        worker_factory=workers,
        db_path_factory=lambda _root: "cache.db",
        database_installer=installer or (lambda _stage, _target: None),
        database_remover=remover or (lambda _path: None),
        path_is_file=path_is_file or (lambda _path: True),
        auto_refresh_policy=auto_refresh_policy,
        timer_factory=FakeTimer,
    )
    return controller, indexes, workers


def test_state_enum_preserves_legacy_string_values() -> None:
    """Typed states must remain compatible with persisted string constants."""
    assert {
        DATASET_INDEX_MISSING,
        DATASET_INDEX_CACHED,
        DATASET_INDEX_SYNCING,
        DATASET_INDEX_READY,
        DATASET_INDEX_STALE,
        DATASET_INDEX_FAILED,
    } == {state.value for state in DatasetIndexState}


def test_context_captures_an_immutable_file_snapshot() -> None:
    """Context creation must detach from mutable caller-owned file lists."""
    files = ["a.jpg"]

    context = DatasetIndexContext.create("root", "labels", files)
    files.append("b.jpg")

    assert context.image_files == ("a.jpg",)
    with pytest.raises(FrozenInstanceError):
        context.dataset_root = "other"


def test_query_facade_hides_index_and_preserves_stale_cache_reads() -> None:
    """Consumers must query through the controller while a cache is readable."""
    controller, indexes, _workers = _controller()
    state = object()

    assert controller.query(state) == []
    assert controller.query_shapes(state) == {}
    assert not controller.is_query_ready
    assert controller.attach_existing("root", "labels", ["a.jpg"])

    index = indexes.created[-1]
    index.query_result = ["a.jpg"]
    index.query_shapes_result = {"a.jpg": [1, 3]}
    controller.set_state(DatasetIndexState.STALE)

    assert controller.is_query_ready
    assert controller.query(state) == ["a.jpg"]
    assert controller.query_shapes(state) == {"a.jpg": [1, 3]}
    assert index.query_calls == [state]
    assert index.query_shapes_calls == [state]


def test_thumbnail_location_facade_is_gated_by_query_readiness() -> None:
    """Object navigation reads only a verified READY index."""
    controller, indexes, _workers = _controller()

    assert controller.query_thumbnail_location("a.jpg", "shape") is None
    assert controller.attach_existing("root", "labels", ["a.jpg"])
    index = indexes.created[-1]
    location = DatasetThumbnailLocation(
        "a.jpg", "a.json", 0, 2, "shape", "person", 7
    )
    index.thumbnail_location_result = location
    controller.set_state(DatasetIndexState.STALE)
    assert controller.query_thumbnail_location("a.jpg", "shape") is None

    controller.set_state(DatasetIndexState.READY)
    assert controller.query_thumbnail_location("a.jpg", "shape") == location
    assert index.thumbnail_location_calls == [("a.jpg", "shape")]


def test_rebuild_creates_connects_and_starts_worker() -> None:
    """Controller must own worker creation, signals, and syncing state."""
    controller, _indexes, workers = _controller()
    started = []
    busy = []
    progress = []
    controller.task_started.connect(started.append)
    controller.busy_changed.connect(busy.append)
    controller.progress_changed.connect(
        lambda current, total, name: progress.append((current, total, name))
    )
    controller.set_context("root", "labels", ["a.jpg"])

    assert controller.rebuild()

    worker = workers.created[0]
    assert worker.started
    assert worker.parent is controller
    assert worker.image_files == ["a.jpg"]
    assert controller.worker is worker
    assert controller.mode == "rebuild"
    assert controller.state is DatasetIndexState.SYNCING
    assert started == ["rebuild"]
    assert busy == [True]

    worker.progress_changed.emit(1, 1, "a.json")
    assert progress == [(1, 1, "a.json")]


def test_finished_rebuild_installs_stage_and_replays_saved_files() -> None:
    """Successful installation must reopen the index and replay pending saves."""
    installs = []
    controller, indexes, workers = _controller(
        installer=lambda stage, target: installs.append((stage, target))
    )
    completed = []
    statuses = []
    busy = []
    controller.task_finished.connect(completed.append)
    controller.statuses_refresh_requested.connect(
        lambda: statuses.append(True)
    )
    controller.busy_changed.connect(busy.append)
    controller.set_context("root", "labels", ["a.jpg"])
    controller.rebuild()
    worker = workers.created[0]
    controller.label_saved("a.jpg")

    result = DatasetIndexResult(
        target_db_path="cache.db",
        staged_db_path="stage.db",
    )
    worker.finished.emit(result)

    assert installs == [("stage.db", "cache.db")]
    assert indexes.created[-1].refresh_calls == [("a.jpg", "labels")]
    assert controller.state is DatasetIndexState.READY
    assert controller.worker is None
    assert controller.pending_refresh_files == frozenset()
    assert completed == [result]
    assert statuses == [True]
    assert busy == [True, False]
    assert worker.delete_called


def test_label_saved_failure_is_deferred_without_raising() -> None:
    """A derived-cache failure must remain isolated from authoritative save."""
    controller, indexes, _workers = _controller()
    deferred = []
    controller.label_sync_deferred.connect(
        lambda image_path, message: deferred.append((image_path, message))
    )
    assert controller.attach_existing("root", None, ["a.jpg"])
    indexes.created[-1].fail_refresh = True

    controller.label_saved("a.jpg")

    assert controller.state is DatasetIndexState.STALE
    assert controller.pending_refresh_files == frozenset({"a.jpg"})
    assert deferred == [("a.jpg", "cache unavailable")]


def test_force_prepare_retires_worker_without_waiting_or_installing() -> None:
    """Directory switches must not wait or accept a retired worker result."""
    removed = []
    installs = []
    controller, indexes, workers = _controller(
        installer=lambda stage, target: installs.append((stage, target)),
        remover=removed.append,
    )
    assert controller.attach_existing("same-root", "labels-a", ["a.jpg"])
    controller.refresh()
    worker = workers.created[0]
    index = indexes.created[0]
    controller.label_saved("a.jpg")

    detached = controller.prepare_for_directory(
        "same-root",
        "labels-b",
        force=True,
    )

    assert detached
    assert worker.cancel_called
    assert not worker.wait_called
    assert not worker.delete_called
    assert index.closed
    assert controller.worker is None
    assert controller.retired_worker_count == 1
    assert controller.index is None
    assert controller.pending_refresh_files == frozenset()
    assert controller.context == DatasetIndexContext(
        dataset_root="same-root",
        output_dir="labels-b",
        image_files=(),
    )
    assert controller.state is DatasetIndexState.MISSING

    result = DatasetIndexResult(
        target_db_path="cache.db",
        staged_db_path="retired-stage.db",
    )
    worker.finished.emit(result)

    assert installs == []
    assert removed == ["retired-stage.db"]
    assert worker.delete_called
    assert controller.retired_worker_count == 0
    assert controller.context.output_dir == "labels-b"
    assert controller.state is DatasetIndexState.MISSING


def test_same_cache_cannot_restart_until_retired_worker_drains() -> None:
    """Non-blocking cancellation must not permit concurrent SQLite writers."""
    controller, _indexes, workers = _controller()
    controller.set_context("same-root", "labels-a", ["a.jpg"])
    assert controller.refresh()
    old_worker = workers.created[0]

    controller.prepare_for_directory(
        "same-root",
        "labels-b",
        force=True,
    )
    controller.set_context("same-root", "labels-b", ["a.jpg"])

    assert not controller.refresh()
    assert len(workers.created) == 1

    old_worker.cancelled.emit(DatasetIndexResult(cancelled=True))

    assert controller.refresh()
    assert len(workers.created) == 2


def test_auto_refresh_policy_is_explicit_and_controller_owned() -> None:
    """Only the enabled policy may schedule cache verification."""
    disabled, _disabled_indexes, _disabled_workers = _controller()
    assert disabled.attach_existing("disabled-root", None, ["a.jpg"])
    assert not disabled._auto_refresh_timer.isActive()

    controller, _indexes, workers = _controller(
        auto_refresh_policy=DatasetIndexAutoRefreshPolicy.ON_CACHE_ATTACH
    )

    assert controller.attach_existing("root", "labels", ["a.jpg"])
    assert controller.auto_refresh_policy is (
        DatasetIndexAutoRefreshPolicy.ON_CACHE_ATTACH
    )
    assert controller._auto_refresh_timer.isActive()

    controller._auto_refresh_timer.stop()
    controller._on_auto_refresh_timeout()

    assert len(workers.created) == 1
    assert workers.created[0].mode == "refresh"


def test_install_failure_restores_old_index_as_stale() -> None:
    """Atomic install failure must reopen the old cache and report stale."""

    def fail_install(_stage: str, _target: str) -> None:
        """Simulate an operating-system replacement failure."""
        raise OSError("locked")

    controller, indexes, workers = _controller(installer=fail_install)
    failures = []
    controller.install_failed.connect(
        lambda result, message: failures.append((result, message))
    )
    controller.set_context("root", None, ["a.jpg"])
    controller.rebuild()
    worker = workers.created[0]
    result = DatasetIndexResult(
        target_db_path="cache.db",
        staged_db_path="stage.db",
    )

    worker.finished.emit(result)

    assert len(indexes.created) == 1
    assert controller.index is indexes.created[0]
    assert controller.state is DatasetIndexState.STALE
    assert failures == [(result, "locked")]
    assert controller.worker is None


def test_partial_context_update_preserves_other_fields() -> None:
    """Selected context updates must preserve all other immutable fields."""
    controller, _indexes, _workers = _controller()
    controller.set_context("root-a", "labels-a", ["a.jpg"])

    changed = controller.update_context(
        output_dir=None,
        image_files=["b.jpg"],
        replace_output_dir=True,
    )

    assert changed
    assert controller.context == DatasetIndexContext(
        dataset_root="root-a",
        output_dir=None,
        image_files=("b.jpg",),
    )
