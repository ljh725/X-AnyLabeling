"""Undo/redo, rule disable, partial recheck, external edits and sessions."""

import json
import os
from unittest.mock import patch

from PyQt6 import QtWidgets

from anylabeling.services.inspection.manifest import (
    build_manifest,
    load_file_snapshot,
    memory_file_snapshot,
)
from anylabeling.services.inspection.models import (
    CoverageEntry,
    CoverageState,
    RunReport,
    RunScope,
    RunState,
)
from anylabeling.services.inspection.review_queue import merge_recheck_report
from anylabeling.services.inspection.storage import (
    InspectionStorage,
    RevisionConflict,
)

from tests.test_inspection.test_inspector_dialog import (  # noqa: F401
    _prepare_image,
    _wait_until,
    window,
)


def _report_for(tmp_path, issues=(), coverage=()):
    return RunReport(
        run_id="manual-run",
        state=RunState.CANCELLED,
        scope=RunScope.CURRENT_IMAGE,
        dataset_root=str(tmp_path),
        output_root="",
        manifest_fingerprint="fp",
        profile_snapshot={
            "profile": {"profile_id": "generic", "profile_version": 1},
            "snapshot_digest": "cfg",
            "rules": [
                {
                    "rule_id": "duplicate_boxes",
                    "enabled": True,
                    "implementation_version": "1.0.0",
                }
            ],
        },
        coverage=coverage,
        issues=issues,
        requested_files=1,
        completed_files=0,
    )


def test_cancelled_partial_recheck_keeps_previous_queue(window, tmp_path):
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
    previous = dialog.report.issues[0]
    dialog._recheck_issue = previous
    part = _report_for(
        tmp_path,
        coverage=(
            CoverageEntry(
                previous.location.relative_path,
                "duplicate_boxes",
                CoverageState.CANCELLED,
                "运行已取消",
            ),
        ),
    )
    dialog._finish_recheck(part, dialog.manifest)
    app.processEvents()
    kept = [
        issue
        for issue in dialog.report.issues
        if issue.family_key == previous.family_key
    ]
    assert kept
    assert kept[0].verification.value == "unverifiable"
    assert dialog.report.state.value in ("partial", "cancelled")


def test_rule_disabled_recheck_does_not_clear_issue(tmp_path):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"img")
    (tmp_path / "a.json").write_text(
        json.dumps(
            {
                "version": "4.2.1",
                "imageWidth": 100,
                "imageHeight": 100,
                "shapes": [
                    {
                        "label": "person",
                        "shape_type": "rectangle",
                        "points": [[0, 0], [10, 10]],
                        "xanylabeling_shape_id": "id1",
                    },
                    {
                        "label": "person",
                        "shape_type": "rectangle",
                        "points": [[0, 0], [10, 10]],
                        "xanylabeling_shape_id": "id2",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    from anylabeling.services.inspection.profiles import default_profiles
    from anylabeling.services.inspection.runner import InspectionRunner

    manifest = build_manifest(str(tmp_path))
    report = InspectionRunner().run(
        manifest, default_profiles()[0], RunScope.DATASET
    )
    assert report.issues
    issue = report.issues[0]
    # A later run without the rule must not be read as "no longer detected".
    recheck = _report_for(
        tmp_path,
        coverage=(),
    )
    from dataclasses import replace as dataclass_replace

    recheck = dataclass_replace(
        recheck,
        profile_snapshot={**recheck.profile_snapshot, "rules": []},
    )
    result = merge_recheck_report(
        report, recheck, issue.location.relative_path,
        selected_family_key=issue.family_key,
    )
    assert result.outcome == "unverifiable"
    assert result.selected_issue.verification.value == "unverifiable"


def test_undo_redo_marks_queue_pending_not_current(window, tmp_path):
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
    shapes = {
        shape.xanylabeling_shape_id: shape for shape in widget.canvas.shapes
    }
    widget.canvas.select_shapes([shapes["id2"]])
    with patch.object(
        QtWidgets.QMessageBox,
        "question",
        return_value=QtWidgets.QMessageBox.StandardButton.Yes,
    ):
        dialog._delete_selected()
    app.processEvents()
    assert all(
        issue.verification.value == "pending_recheck"
        for issue in dialog.report.issues
        if issue.location.relative_path == "image.png"
    )
    dialog._undo_last_edit()
    app.processEvents()
    assert {shape.xanylabeling_shape_id for shape in widget.canvas.shapes} == {
        "id1",
        "id2",
    }
    assert all(
        issue.verification.value == "pending_recheck"
        for issue in dialog.report.issues
        if issue.location.relative_path == "image.png"
    )
    assert dialog._edit_serial > 0


def test_external_file_change_invalidates_restored_report(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_inspector()
    dialog = widget.inspector_dialog
    dialog.profile_combo.setCurrentIndex(
        dialog.profile_combo.findData("generic")
    )
    dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData("dataset"))
    dialog._start_run()
    assert _wait_until(app, lambda: dialog.report is not None)
    annotation = tmp_path / "image.json"
    payload = json.loads(annotation.read_text(encoding="utf-8"))
    payload["shapes"][1]["points"] = [[40, 40], [55, 55]]
    annotation.write_text(json.dumps(payload), encoding="utf-8")
    dialog._resume_last()
    app.processEvents()
    assert dialog._verification_current is False
    assert any(
        issue.verification.value in ("stale", "pending_recheck")
        for issue in dialog.report.issues
    )


def test_cross_window_feedback_conflict_keeps_draft(window, tmp_path):
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
    assert dialog.storage is not None
    dialog.issue_table.selectRow(0)
    app.processEvents()
    from anylabeling.services.inspection.models import (
        Decision,
        FeedbackRecord,
    )

    # Another window writes feedback first, bumping the revision.
    other = InspectionStorage.open(
        widget.inspection_dataset_root(), widget.inspection_output_dir()
    )
    issue = dialog.report.issues[0]
    other.feedback.upsert(
        FeedbackRecord(family_key=issue.family_key, issue_id=issue.issue_id),
        other.feedback.load().revision,
    )
    with patch.object(dialog, "_show_error") as show_error:
        dialog._set_decision(Decision.ACCEPTABLE)
    app.processEvents()
    show_error.assert_called_once()
    assert "冲突" in show_error.call_args.args[0]
    # Nothing is lost: the pending record stays in memory for a retry.
    assert dialog._pending_feedback
    assert (
        dialog._pending_feedback[issue.family_key].decision
        is Decision.ACCEPTABLE
    )
