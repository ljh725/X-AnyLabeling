"""Temporary diagnostic: why is the selected candidate not accepted?"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from anylabeling.services.inspection.candidates import Candidate

from tests.test_inspection.test_inspector_dialog import (  # noqa: F401
    _prepare_image,
    _wait_until,
    window,
)


def test_diag(window, tmp_path):
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
    print("ensure", dialog._ensure_storage())
    print("relative", repr(widget.inspection_current_relative_path()))
    print("dataset", repr(widget.inspection_dataset_root()))
    candidate = Candidate(
        candidate_id="cand-1",
        source="model",
        source_version="1",
        relative_path="other.png",
        image_path="",
        label="person",
        region=(10, 10, 26, 26),
        image_width=64,
        image_height=64,
        score=0.9,
    )
    dialog._candidate_records = {"cand-1": candidate}
    dialog._populate_candidate_table()
    dialog.candidate_table.selectRow(0)
    app.processEvents()
    print("row", dialog.candidate_table.currentRow(), dialog.candidate_table.rowCount())
    print("selected", dialog._selected_candidate())
    print("for_file", dialog._candidate_for_file(candidate))
    ok, payload = widget.inspection_accept_candidate(candidate, "new-id")
    print("host accept", ok, payload)
    from unittest.mock import patch

    with patch.object(dialog, "_show_error") as show_error:
        dialog._accept_candidate()
    print("show_error count", show_error.call_count, show_error.call_args)
    print("storage", dialog.storage is not None)
    print("status", dialog._candidate_records["cand-1"].status)
