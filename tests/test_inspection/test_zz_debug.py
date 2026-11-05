"""Single-step undo semantics for the Inspector batch operations."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from PyQt6 import QtWidgets

from tests.test_inspection.test_inspector_dialog import (  # noqa: F401
    _prepare_image,
    _wait_until,
    window,
)


def test_batch_delete_records_one_undo_step(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    assert widget.load_file(_prepare_image(tmp_path))
    widget.open_inspector()
    dialog = widget.inspector_dialog
    dialog.profile_combo.setCurrentIndex(
        dialog.profile_combo.findData("generic")
    )
    dialog._start_run()
    assert _wait_until(app, lambda: dialog.report is not None)
    dialog.issue_table.selectRow(0)
    app.processEvents()
    before_steps = len(widget.canvas.shapes_backups)
    with patch.object(
        QtWidgets.QMessageBox,
        "question",
        return_value=QtWidgets.QMessageBox.StandardButton.Yes,
    ):
        dialog._batch_delete()
    app.processEvents()
    # Two objects were deleted but the history grew by exactly one step.
    assert len(widget.canvas.shapes_backups) == before_steps + 1
    assert widget.canvas.shapes == []
    dialog._undo_last_edit()
    app.processEvents()
    restored = {
        shape.xanylabeling_shape_id for shape in widget.canvas.shapes
    }
    assert restored == {"id1", "id2"}
    redo_available = widget.canvas.is_shape_redo_available
    widget.redo_shape_edit()
    app.processEvents()
    assert widget.canvas.shapes == []
    assert redo_available is True
