"""Qt worker and dialog flow for cross-image object relabeling.

The worker thread only touches pure Python domain objects (immutable
plan, preflight summary, structured result); it never accesses QWidget
or Canvas instances. All UI interaction happens on the GUI thread via
queued signals.
"""

import os.path as osp
import threading

from PyQt6 import QtCore, QtWidgets

from anylabeling.views.labeling.widgets.label_batch import (
    BatchWriteGate,
)
from anylabeling.views.labeling.widgets.object_relabel import (
    ObjectRelabelEngine,
    ObjectRelabelPlan,
    ObjectRelabelResult,
)

_FLOW_OWNER = "object-relabel"


class ObjectRelabelThread(QtCore.QThread):
    """Background preflight/stage/commit driver for one immutable plan."""

    progress = QtCore.pyqtSignal(str, int, int, str)
    preflight_ready = QtCore.pyqtSignal(object)
    committing_started = QtCore.pyqtSignal()
    finished_result = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)

    def __init__(
        self,
        engine: ObjectRelabelEngine,
        plan: ObjectRelabelPlan,
        commit_root: str,
        parent=None,
    ) -> None:
        """Initialize the worker for one plan and commit root."""
        super().__init__(parent)
        self._engine = engine
        self._plan = plan
        self._commit_root = commit_root
        self._confirm = threading.Event()
        self._aborted = False

    def confirm_commit(self) -> None:
        """Let the worker proceed from preflight into staging."""
        self._confirm.set()

    def request_abort(self) -> None:
        """Abort before commit; ignored once committing has started."""
        self._aborted = True
        self._confirm.set()

    def run(self) -> None:
        """Run preflight, wait for confirmation, then stage and commit."""
        try:
            summary = self._engine.preflight(
                self._plan,
                cancel_check=lambda: self._aborted,
                progress=self._emit_progress,
            )
            if self._aborted or summary.cancelled:
                self.finished_result.emit(
                    self._engine.cancelled_result(plan=self._plan)
                )
                return
            self.preflight_ready.emit(summary)
            self._confirm.wait()
            if self._aborted:
                self.finished_result.emit(
                    self._engine.cancelled_result(plan=self._plan)
                )
                return
            staged = self._engine.stage(
                self._plan,
                cancel_check=lambda: self._aborted,
                progress=self._emit_progress,
            )
            if self._aborted or staged.operation.cancelled:
                self.finished_result.emit(
                    self._engine.cancelled_result(staged=staged)
                )
                return
            self.committing_started.emit()
            result = self._engine.commit(staged, self._commit_root)
            self.finished_result.emit(result)
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            self.failed.emit(f"{type(exc).__name__}: {exc}")

    def _emit_progress(
        self, phase: str, index: int, total: int, path: str
    ) -> None:
        """Forward one domain progress callback as a Qt signal."""
        self.progress.emit(phase, index, total, path)


def _preflight_message(summary) -> str:
    """Build the confirmation text for one preflight summary."""

    return QtCore.QCoreApplication.translate(
        "LabelingWidget",
        "Target label: {label}\n"
        "Marked objects: {objects} in {files} file(s)\n"
        "Changeable: {changeable}\n"
        "Already target label: {unchanged}\n"
        "Deleted: {deleted}\n"
        "Identity conflicts: {conflict}\n"
        "Read failures: {failed}\n\n"
        "This operation writes annotation JSON files immediately and is "
        "not added to the normal undo stack. A recovery manifest is created "
        "for committed files.\n\n"
        "Proceed with the commit?",
    ).format(
        label=summary.target_label,
        objects=summary.snapshot_objects,
        files=summary.candidate_files,
        changeable=summary.changeable,
        unchanged=summary.unchanged,
        deleted=summary.deleted,
        conflict=summary.conflict,
        failed=summary.failed,
    )


def _result_message(result: ObjectRelabelResult) -> str:
    """Build the final per-object and per-file report text."""
    counts = result.counts
    file_counts = result.file_counts
    text = QtCore.QCoreApplication.translate(
        "LabelingWidget",
        "Objects — succeeded: {succeeded}, unchanged: {unchanged}, "
        "deleted: {deleted}, conflict: {conflict}, failed: {failed}, "
        "cancelled: {cancelled}\n"
        "Files — succeeded: {fs}, skipped: {fk}, failed: {ff}\n"
        "Recovery manifest: {manifest}",
    ).format(
        succeeded=counts.get("succeeded", 0),
        unchanged=counts.get("unchanged", 0),
        deleted=counts.get("deleted", 0),
        conflict=counts.get("conflict", 0),
        failed=counts.get("failed", 0),
        cancelled=counts.get("cancelled", 0),
        fs=file_counts.get("succeeded", 0),
        fk=file_counts.get("skipped", 0),
        ff=file_counts.get("failed", 0),
        manifest=result.manifest_path
        or QtCore.QCoreApplication.translate("LabelingWidget", "(none)"),
    )
    if result.cancelled:
        text = (
            QtCore.QCoreApplication.translate(
                "LabelingWidget",
                "Relabel cancelled. No files were written; all marks kept.",
            )
            + "\n\n"
            + text
        )
    return text


def run_object_relabel_flow(
    parent: QtWidgets.QWidget,
    plan: ObjectRelabelPlan,
    transaction_root: str,
    commit_root: str,
    on_finished,
    on_flow_failed,
) -> bool:
    """Drive preflight → confirm → stage → commit for one plan.

    Returns False when another relabel flow is already active for the
    same dataset root. ``on_finished(result)`` runs after the result
    dialog is acknowledged; ``on_flow_failed(message)`` covers worker
    errors.
    """

    flow_key = osp.normcase(osp.abspath(commit_root))
    if not BatchWriteGate.try_acquire(flow_key, _FLOW_OWNER):
        QtWidgets.QMessageBox.warning(
            parent,
            QtCore.QCoreApplication.translate(
                "LabelingWidget", "Relabel Marked Objects"
            ),
            QtCore.QCoreApplication.translate(
                "LabelingWidget",
                "Another batch write is already running for this " "dataset.",
            ),
        )
        return False

    state = {"committing": False, "done": False, "progress_closed": False}

    def release() -> None:
        BatchWriteGate.release(flow_key, _FLOW_OWNER)

    engine = ObjectRelabelEngine(transaction_root)
    thread = ObjectRelabelThread(engine, plan, commit_root, parent=parent)
    dialog = QtWidgets.QProgressDialog(
        QtCore.QCoreApplication.translate(
            "LabelingWidget", "Preflighting marked objects..."
        ),
        QtCore.QCoreApplication.translate("LabelingWidget", "Cancel"),
        0,
        0,
        parent,
    )
    dialog.setWindowTitle(
        QtCore.QCoreApplication.translate(
            "LabelingWidget", "Relabel Marked Objects"
        )
    )
    dialog.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)

    def close_progress() -> None:
        """Hide and schedule deletion of the progress dialog exactly once."""
        if state["progress_closed"]:
            return
        state["progress_closed"] = True
        dialog.hide()
        dialog.deleteLater()

    def finish(result: ObjectRelabelResult) -> None:
        if state["done"]:
            return
        state["done"] = True
        release()
        thread.wait()
        parent._object_relabel_thread = None
        close_progress()
        QtWidgets.QMessageBox.information(
            parent,
            QtCore.QCoreApplication.translate(
                "LabelingWidget", "Relabel Marked Objects"
            ),
            _result_message(result),
        )
        on_finished(result)

    def on_progress(phase: str, index: int, total: int, path: str) -> None:
        if state["done"]:
            return
        if total > 0:
            if dialog.minimum() != 0 or dialog.maximum() != total:
                dialog.setRange(0, total)
            dialog.setValue(max(0, min(index, total)))
        else:
            dialog.setRange(0, 0)
        dialog.setLabelText(
            QtCore.QCoreApplication.translate(
                "LabelingWidget", "{phase}: {index}/{total}\n{path}"
            ).format(phase=phase, index=index, total=total, path=path)
        )

    def on_preflight(summary) -> None:
        dialog.hide()
        answer = QtWidgets.QMessageBox.question(
            parent,
            QtCore.QCoreApplication.translate(
                "LabelingWidget", "Confirm object relabel"
            ),
            _preflight_message(summary),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if (
            answer == QtWidgets.QMessageBox.StandardButton.Yes
            and not state["committing"]
        ):
            dialog.setRange(0, 0)
            dialog.setLabelText(
                QtCore.QCoreApplication.translate(
                    "LabelingWidget", "Staging changed files..."
                )
            )
            dialog.show()
            thread.confirm_commit()
        else:
            thread.request_abort()

    def on_committing() -> None:
        state["committing"] = True
        dialog.setRange(0, 1)
        dialog.setValue(0)
        dialog.setLabelText(
            QtCore.QCoreApplication.translate(
                "LabelingWidget",
                "Committing atomically — this stage cannot be cancelled.",
            )
        )
        dialog.setCancelButton(None)
        dialog.show()

    def on_worker_failed(message: str) -> None:
        if state["done"]:
            return
        state["done"] = True
        release()
        thread.wait()
        parent._object_relabel_thread = None
        close_progress()
        on_flow_failed(message)

    thread.progress.connect(on_progress)
    thread.preflight_ready.connect(on_preflight)
    thread.committing_started.connect(on_committing)
    thread.finished_result.connect(finish)
    thread.failed.connect(on_worker_failed)
    dialog.canceled.connect(
        lambda: (
            None
            if state["done"] or state["committing"]
            else thread.request_abort()
        )
    )
    parent._object_relabel_thread = thread
    dialog.show()
    thread.start()
    return True
