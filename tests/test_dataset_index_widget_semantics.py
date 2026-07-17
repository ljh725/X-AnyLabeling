"""Lightweight tests for dataset-index UI lifecycle semantics."""

import inspect
from types import SimpleNamespace

from anylabeling.views.labeling.dataset_filter_index import (
    DATASET_INDEX_STALE,
)
from anylabeling.views.labeling.label_widget import LabelingWidget


def test_dataset_sync_uses_complete_list_not_filtered_ui_list():
    """Filename filtering must never remove hidden files from the index."""
    widget = SimpleNamespace(
        _dataset_all_image_files=["all-a.jpg", "all-b.jpg"],
        image_list=["all-a.jpg"],
    )

    files = LabelingWidget._dataset_index_files(widget)

    assert files == ["all-a.jpg", "all-b.jpg"]


def test_background_label_check_does_not_create_modal_progress_dialog():
    """Dataset opening must not install an application-modal label scan."""
    source = inspect.getsource(LabelingWidget._start_label_check_worker)

    assert "QProgressDialog" not in source
    assert "ApplicationModal" not in source


def test_index_failure_after_json_save_is_queued_not_raised():
    """A derived-cache failure must not escape the post-save sync hook."""

    class BrokenIndex:
        """Index stub that simulates a SQLite write failure."""

        @staticmethod
        def refresh_file(_image_path, _output_dir):
            """Raise a representative cache failure."""
            raise RuntimeError("cache unavailable")

    statuses = []
    messages = []
    widget = SimpleNamespace(
        _dataset_index_worker=None,
        _dataset_filter_index=BrokenIndex(),
        _pending_dataset_index_refresh_files=set(),
        output_dir=None,
        _set_dataset_index_state=statuses.append,
        status=lambda message, _delay: messages.append(message),
        tr=lambda text: text,
    )

    LabelingWidget._sync_dataset_index_after_save(widget, "sample.jpg")

    assert widget._pending_dataset_index_refresh_files == {"sample.jpg"}
    assert statuses == [DATASET_INDEX_STALE]
    assert messages == ["Label saved; dataset index sync pending"]


def test_force_detach_resets_same_dataset_worker_and_index():
    """Changing output directory must detach even when the root is unchanged."""

    class Signal:
        """Minimal Qt signal stand-in."""

        @staticmethod
        def disconnect():
            """Accept disconnection."""

    class Worker:
        """Cancellable worker stand-in."""

        progress_changed = Signal()
        finished = Signal()
        cancelled = Signal()
        failed = Signal()

        def __init__(self):
            self.cancel_called = False
            self.wait_called = False
            self.delete_called = False

        def cancel(self):
            """Record cancellation."""
            self.cancel_called = True

        def wait(self):
            """Record the join."""
            self.wait_called = True

        def deleteLater(self):
            """Record deferred deletion."""
            self.delete_called = True

    class Index:
        """Closable index stand-in."""

        def __init__(self):
            self.closed = False

        def close(self):
            """Record closure."""
            self.closed = True

    class Action:
        """Action enable-state stand-in."""

        def __init__(self):
            self.enabled = None

        def setEnabled(self, enabled):
            """Record the enabled state."""
            self.enabled = enabled

    worker = Worker()
    index = Index()
    actions = SimpleNamespace(
        refresh_dataset_index=Action(),
        rebuild_dataset_index=Action(),
        cancel_dataset_index=Action(),
    )
    widget = SimpleNamespace(
        _dataset_index_timer=None,
        _dataset_index_root="same-root",
        _dataset_index_worker=worker,
        _dataset_filter_index=index,
        _pending_dataset_index_refresh_files={"pending.jpg"},
        _dataset_index_mode="refresh",
        _dataset_index_state=None,
        actions=actions,
        _normalize_dataset_root=lambda root: root,
    )
    widget._finish_dataset_index_worker = lambda: (
        LabelingWidget._finish_dataset_index_worker(widget)
    )
    widget._close_dataset_filter_index = lambda: (
        LabelingWidget._close_dataset_filter_index(widget)
    )
    widget._set_dataset_index_state = lambda state: setattr(
        widget, "_dataset_index_state", state
    )

    LabelingWidget._prepare_dataset_index_for_directory(
        widget, "same-root", force=True
    )

    assert worker.cancel_called
    assert worker.wait_called
    assert worker.delete_called
    assert index.closed
    assert widget._dataset_index_worker is None
    assert widget._dataset_filter_index is None
    assert widget._pending_dataset_index_refresh_files == set()
    assert actions.refresh_dataset_index.enabled is True
    assert actions.rebuild_dataset_index.enabled is True
    assert actions.cancel_dataset_index.enabled is False
