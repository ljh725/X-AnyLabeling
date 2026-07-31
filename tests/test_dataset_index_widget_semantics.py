"""Lightweight tests for dataset-index UI lifecycle semantics."""

import inspect
from types import SimpleNamespace

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


def test_three_dataset_index_actions_delegate_to_controller():
    """Refresh, rebuild, and cancel handlers must be pure delegations."""
    refresh_source = inspect.getsource(LabelingWidget.refresh_dataset_index)
    rebuild_source = inspect.getsource(LabelingWidget.rebuild_dataset_index)
    cancel_source = inspect.getsource(
        LabelingWidget.cancel_dataset_index_build
    )

    assert "_dataset_index_controller.refresh()" in refresh_source
    assert "_dataset_index_controller.rebuild()" in rebuild_source
    assert "_dataset_index_controller.cancel()" in cancel_source
    assert "_start_dataset_index_worker" not in refresh_source
    assert "_start_dataset_index_worker" not in rebuild_source


def test_authoritative_save_delegates_index_sync_to_controller():
    """Successful JSON save must invoke the controller label-saved hook."""
    source = inspect.getsource(LabelingWidget.save_labels)

    assert "_dataset_index_controller.label_saved(self.image_path)" in source


def test_filter_navigation_receives_controller_query_contract():
    """Widget must not expose the raw SQLite index to navigation logic."""
    source = inspect.getsource(LabelingWidget.enable_filter_navigation)

    assert "dataset_index=self._dataset_index_controller," in source
    assert "_dataset_index_controller.index" not in source


def test_auto_refresh_policy_is_not_owned_by_labeling_widget():
    """Automatic cache verification must be a controller policy."""
    assert not hasattr(LabelingWidget, "_schedule_dataset_index_refresh")
    assert not hasattr(LabelingWidget, "_auto_refresh_dataset_index")


def test_force_detach_resets_same_dataset_worker_and_index():
    """Changing output directory must delegate a forced controller detach."""
    calls = []

    class Controller:
        """Record directory preparation requests."""

        @staticmethod
        def prepare_for_directory(dataset_root, output_dir, *, force=False):
            """Record one controller lifecycle request."""
            calls.append((dataset_root, output_dir, force))

    widget = SimpleNamespace(
        _dataset_index_controller=Controller(),
        output_dir="labels-b",
        _normalize_dataset_root=lambda root: root,
    )

    LabelingWidget._prepare_dataset_index_for_directory(
        widget, "same-root", force=True
    )

    assert calls == [("same-root", "labels-b", True)]
