"""Qt field editor and transaction flow for marked annotation objects."""

from __future__ import annotations

import json
import os.path as osp
import threading

from PyQt6 import QtCore, QtWidgets

from anylabeling.views.labeling.widgets.label_batch import BatchWriteGate
from anylabeling.views.labeling.widgets.object_field_edit import (
    FieldAssignment,
    ObjectFieldEditEngine,
    ObjectFieldEditPlan,
    ObjectFieldEditPlanError,
    ObjectFieldEditResult,
    ObjectFieldPreflightSummary,
)

_FLOW_OWNER = "object-field-edit"


class _FieldRow(QtWidgets.QWidget):
    """One editable field assignment row."""

    _ROOTS = (
        ("label", "label"),
        ("difficult", "difficult"),
        ("group_id", "group_id"),
        ("description", "description"),
        ("score", "score"),
        ("flags", "flags.<key>"),
        ("attributes", "attributes.<key>"),
    )

    def __init__(self, parent=None) -> None:
        """Create a row with a field selector and typed value editor."""
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.field_combo = QtWidgets.QComboBox(self)
        for value, label in self._ROOTS:
            self.field_combo.addItem(label, value)
        self.key_edit = QtWidgets.QLineEdit(self)
        self.key_edit.setPlaceholderText(self.tr("key"))
        self.value_edit = QtWidgets.QLineEdit(self)
        self.value_edit.setPlaceholderText(self.tr("value"))
        self.bool_edit = QtWidgets.QComboBox(self)
        self.bool_edit.addItem(self.tr("true"), True)
        self.bool_edit.addItem(self.tr("false"), False)
        self.remove_button = QtWidgets.QToolButton(self)
        self.remove_button.setText(self.tr("−"))
        self.remove_button.setToolTip(self.tr("Remove field"))
        layout.addWidget(self.field_combo)
        layout.addWidget(self.key_edit)
        layout.addWidget(self.value_edit)
        layout.addWidget(self.bool_edit)
        layout.addWidget(self.remove_button)
        self.field_combo.currentIndexChanged.connect(self._update_editor)
        self._update_editor()

    @property
    def path(self) -> str:
        """Return the selected dotted path."""
        root = str(self.field_combo.currentData())
        if root in {"flags", "attributes"}:
            return f"{root}.{self.key_edit.text().strip()}"
        return root

    def _update_editor(self) -> None:
        """Show the key and value editor appropriate for this field."""
        root = str(self.field_combo.currentData())
        nested = root in {"flags", "attributes"}
        self.key_edit.setVisible(nested)
        is_bool = root in {"difficult", "flags"}
        self.bool_edit.setVisible(is_bool)
        self.value_edit.setVisible(not is_bool)

    def assignment(self) -> FieldAssignment:
        """Parse and validate this row into an immutable assignment."""
        root = str(self.field_combo.currentData())
        if root in {"difficult", "flags"}:
            value = bool(self.bool_edit.currentData())
        else:
            raw = self.value_edit.text()
            if root in {"group_id", "score"} and not raw.strip():
                value = None
            elif root == "group_id":
                value = int(raw.strip())
            elif root == "score":
                value = float(raw.strip())
            elif root == "attributes":
                try:
                    value = json.loads(raw)
                except json.JSONDecodeError:
                    value = raw
            else:
                value = raw
        return FieldAssignment(self.path, value)


class ObjectFieldEditDialog(QtWidgets.QDialog):
    """Collect one or more typed field assignments before preflight."""

    def __init__(
        self, object_count: int, file_count: int, parent=None
    ) -> None:
        """Create the field editor and show the frozen mark summary."""
        super().__init__(parent)
        self.setWindowTitle(self.tr("Batch Edit Marked Objects"))
        self._rows: list[_FieldRow] = []
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(
            QtWidgets.QLabel(
                self.tr("Marked objects: %d in %d file(s)")
                % (object_count, file_count),
                self,
            )
        )
        layout.addWidget(
            QtWidgets.QLabel(
                self.tr(
                    "Missing selected fields will be created; unselected "
                    "fields are not completed. Field completion is not a "
                    "prerequisite."
                ),
                self,
            )
        )
        self.rows_layout = QtWidgets.QVBoxLayout()
        layout.addLayout(self.rows_layout)
        add_button = QtWidgets.QPushButton(self.tr("Add field"), self)
        add_button.clicked.connect(self.add_row)
        layout.addWidget(add_button)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._accept_checked)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.add_row()

    @property
    def rows(self) -> tuple[_FieldRow, ...]:
        """Return the current rows for tests and lightweight integrations."""
        return tuple(self._rows)

    def add_row(self) -> None:
        """Append one field row."""
        row = _FieldRow(self)
        row.remove_button.clicked.connect(lambda: self.remove_row(row))
        self._rows.append(row)
        self.rows_layout.addWidget(row)

    def remove_row(self, row: _FieldRow) -> None:
        """Remove a row, keeping one editable row available."""
        if len(self._rows) <= 1:
            return
        self._rows.remove(row)
        row.deleteLater()

    def assignments(self) -> tuple[FieldAssignment, ...]:
        """Return validated assignments from all rows."""
        assignments = tuple(row.assignment() for row in self._rows)
        paths = [assignment.path for assignment in assignments]
        if len(paths) != len(set(paths)):
            raise ObjectFieldEditPlanError(
                "duplicate field paths are not allowed"
            )
        return assignments

    def _accept_checked(self) -> None:
        """Validate rows and accept only when all values are valid."""
        try:
            self.assignments()
        except (ObjectFieldEditPlanError, TypeError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(
                self, self.tr("Invalid field assignment"), str(exc)
            )
            return
        self.accept()


class ObjectFieldEditThread(QtCore.QThread):
    """Background preflight/stage/commit driver for one field plan."""

    progress = QtCore.pyqtSignal(str, int, int, str)
    preflight_ready = QtCore.pyqtSignal(object)
    committing_started = QtCore.pyqtSignal()
    finished_result = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)

    def __init__(
        self,
        engine: ObjectFieldEditEngine,
        plan: ObjectFieldEditPlan,
        commit_root: str,
        parent=None,
    ) -> None:
        """Initialize the worker with an immutable plan."""
        super().__init__(parent)
        self._engine = engine
        self._plan = plan
        self._commit_root = commit_root
        self._confirm = threading.Event()
        self._aborted = False

    def confirm_commit(self) -> None:
        """Allow the worker to continue after preflight confirmation."""
        self._confirm.set()

    def request_abort(self) -> None:
        """Cancel before the atomic commit boundary."""
        self._aborted = True
        self._confirm.set()

    def run(self) -> None:
        """Execute preflight, staging and commit off the GUI thread."""
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
            self.finished_result.emit(
                self._engine.commit(staged, self._commit_root)
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            self.failed.emit(f"{type(exc).__name__}: {exc}")

    def _emit_progress(
        self, phase: str, index: int, total: int, path: str
    ) -> None:
        """Forward domain progress as a Qt signal."""
        self.progress.emit(phase, index, total, path)


def _preflight_message(summary: ObjectFieldPreflightSummary) -> str:
    """Build the confirmation text for field mutations."""
    counts = summary.field_counts
    warning_text = "\n".join(summary.warnings)
    return QtCore.QCoreApplication.translate(
        "LabelingWidget",
        "Fields: {fields}\n"
        "Objects: {objects} in {files} file(s)\n"
        "Created: {created}\nUpdated: {updated}\n"
        "Unchanged: {unchanged}\nConflicts: {conflict}\n"
        "Deleted: {deleted}\nFailed: {failed}\n\n{warnings}\n"
        "Proceed with the commit?",
    ).format(
        fields=", ".join(item.path_text for item in summary.assignments),
        objects=summary.snapshot_objects,
        files=summary.candidate_files,
        created=counts["created"],
        updated=counts["updated"],
        unchanged=counts["unchanged"],
        conflict=counts["conflict"],
        deleted=summary.deleted,
        failed=summary.failed,
        warnings=warning_text
        or QtCore.QCoreApplication.translate("LabelingWidget", "No warnings."),
    )


def _result_message(result: ObjectFieldEditResult) -> str:
    """Build the final field/object/file report."""
    counts = result.counts
    fields = result.field_counts
    files = result.file_counts
    return QtCore.QCoreApplication.translate(
        "LabelingWidget",
        "Fields — created: {created}, updated: {updated}, "
        "unchanged: {unchanged}, conflict: {conflict}\n"
        "Objects — succeeded: {succeeded}, unchanged: {unchanged_objects}, "
        "deleted: {deleted}, conflict: {object_conflict}, failed: {failed}, "
        "cancelled: {cancelled}\n"
        "Files — succeeded: {fs}, skipped: {skipped}, failed: {ff}\n"
        "Recovery manifest: {manifest}",
    ).format(
        created=fields["created"],
        updated=fields["updated"],
        unchanged=fields["unchanged"],
        conflict=fields["conflict"],
        succeeded=counts.get("succeeded", 0),
        unchanged_objects=counts.get("unchanged", 0),
        deleted=counts.get("deleted", 0),
        object_conflict=counts.get("conflict", 0),
        failed=counts.get("failed", 0),
        cancelled=counts.get("cancelled", 0),
        fs=files.get("succeeded", 0),
        skipped=files.get("skipped", 0),
        ff=files.get("failed", 0),
        manifest=result.manifest_path
        or QtCore.QCoreApplication.translate("LabelingWidget", "(none)"),
    )


def run_object_field_edit_flow(
    parent: QtWidgets.QWidget,
    plan: ObjectFieldEditPlan,
    transaction_root: str,
    commit_root: str,
    on_finished,
    on_flow_failed,
) -> bool:
    """Drive preflight → confirm → stage → commit for field assignments."""
    flow_key = osp.normcase(osp.abspath(commit_root))
    if not BatchWriteGate.try_acquire(flow_key, _FLOW_OWNER):
        QtWidgets.QMessageBox.warning(
            parent,
            parent.tr("Batch Edit Marked Objects"),
            parent.tr(
                "Another batch write is already running for this dataset."
            ),
        )
        return False
    state = {"committing": False, "done": False, "progress_closed": False}
    engine = ObjectFieldEditEngine(transaction_root)
    thread = ObjectFieldEditThread(engine, plan, commit_root, parent=parent)
    dialog = QtWidgets.QProgressDialog(
        parent.tr("Preflighting field assignments..."),
        parent.tr("Cancel"),
        0,
        0,
        parent,
    )
    dialog.setWindowTitle(parent.tr("Batch Edit Marked Objects"))
    dialog.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)

    def release() -> None:
        BatchWriteGate.release(flow_key, _FLOW_OWNER)

    def close_progress() -> None:
        """Close progress UI once."""
        if state["progress_closed"]:
            return
        state["progress_closed"] = True
        dialog.hide()
        dialog.deleteLater()

    def finish(result: ObjectFieldEditResult) -> None:
        if state["done"]:
            return
        state["done"] = True
        release()
        thread.wait()
        parent._object_field_edit_thread = None
        close_progress()
        QtWidgets.QMessageBox.information(
            parent,
            parent.tr("Batch Edit Marked Objects"),
            _result_message(result),
        )
        on_finished(result)

    def on_progress(phase: str, index: int, total: int, path: str) -> None:
        if state["done"]:
            return
        dialog.setRange(0, total if total > 0 else 0)
        if total > 0:
            dialog.setValue(max(0, min(index, total)))
        dialog.setLabelText(
            parent.tr("{phase}: {index}/{total}\n{path}").format(
                phase=phase, index=index, total=total, path=path
            )
        )

    def on_preflight(summary: ObjectFieldPreflightSummary) -> None:
        dialog.hide()
        answer = QtWidgets.QMessageBox.question(
            parent,
            parent.tr("Confirm field edit"),
            _preflight_message(summary),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            dialog.show()
            thread.confirm_commit()
        else:
            thread.request_abort()

    def on_committing() -> None:
        state["committing"] = True
        dialog.setRange(0, 1)
        dialog.setValue(0)
        dialog.setLabelText(
            parent.tr("Committing atomically — cannot cancel.")
        )
        dialog.setCancelButton(None)
        dialog.show()

    def on_worker_failed(message: str) -> None:
        if state["done"]:
            return
        state["done"] = True
        release()
        thread.wait()
        parent._object_field_edit_thread = None
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
    parent._object_field_edit_thread = thread
    dialog.show()
    thread.start()
    return True
