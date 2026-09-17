"""Main-window adapters for guarded asynchronous history inverse commands."""

import os.path as osp
import sqlite3

from .history_inverse import build_inverse_plan
from ..object_relabel_dialog import run_object_relabel_flow


def run_history_inverse(
    parent: object, window: object, record: dict, items: list
) -> None:
    """Reuse dirty resolution, the write gate and the existing worker flow."""
    title = parent.tr("Revert selected changes")
    if not parent._prepare_object_relabel(title):
        return
    try:
        for item in items:
            if osp.normcase(osp.abspath(item["json_path"])) != osp.normcase(
                osp.abspath(
                    parent._annotation_path_for_image(item["image_path"])
                )
            ):
                raise ValueError(
                    "Historical annotation path belongs to another output directory"
                )
        plan = build_inverse_plan(
            window._history,
            record,
            items,
            parent._marked_project_id(),
            window.history_view(),
        )
    except (OSError, ValueError, sqlite3.Error) as exc:
        parent.error_message(title, str(exc))
        return
    parent._object_relabel_running = True
    window._pending_history = plan.history_context

    def finished(result: object) -> None:
        """Synchronize authoritative changes before exposing another command."""
        try:
            parent._apply_object_relabel_result(result)
            if not window._closed:
                window.apply_relabel_result(result)
        finally:
            parent._object_relabel_running = False

    def failed(message: str) -> None:
        """Report uncertain worker outcomes without replaying a write."""
        parent._object_relabel_running = False
        parent.error_message(title, message)
        if not window._closed:
            window.operation_history.message.setText(message)

    started = run_object_relabel_flow(
        parent,
        plan,
        parent._batch_write_root(),
        parent._batch_write_root(),
        finished,
        failed,
        show_result_dialog=False,
    )
    if not started:
        parent._object_relabel_running = False
