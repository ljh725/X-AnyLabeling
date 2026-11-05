"""Candidate overlay, acceptance paths and Inspector/dense-review handoff."""

import json
import os
from dataclasses import replace
from unittest.mock import patch

import pytest
from PyQt6 import QtCore, QtWidgets
from PIL import Image

from anylabeling.services.inspection.candidates import Candidate
from anylabeling.services.inspection.handoff import (
    HandoffRequest,
    build_handoff_request,
    dense_review_available,
    handoff_payload,
    validate_handoff,
)
from anylabeling.services.inspection.manifest import build_manifest
from anylabeling.services.inspection.models import RunScope
from anylabeling.services.inspection.profiles import default_profiles
from anylabeling.services.inspection.runner import InspectionRunner

from tests.test_inspection.test_inspector_dialog import (  # noqa: F401
    _prepare_image,
    _wait_until,
    window,
)


def _candidate(relative_path="image.png", **overrides):
    payload = dict(
        candidate_id="cand-1",
        source="model",
        source_version="1",
        relative_path=relative_path,
        image_path="",
        label="person",
        region=(10, 10, 26, 26),
        image_width=64,
        image_height=64,
        score=0.9,
    )
    payload.update(overrides)
    return Candidate(**payload)


def _open_inspector(window, tmp_path):
    app = QtWidgets.QApplication.instance()
    widget = window.labeling_widget.view
    image_path = _prepare_image(tmp_path)
    assert widget.load_file(image_path)
    widget.open_inspector()
    dialog = widget.inspector_dialog
    dialog.profile_combo.setCurrentIndex(
        dialog.profile_combo.findData("generic")
    )
    dialog._start_run()
    assert _wait_until(app, lambda: dialog.report is not None)
    return app, widget, dialog


def test_candidate_overlay_is_separate_and_cleared_on_close(window, tmp_path):
    app, widget, dialog = _open_inspector(window, tmp_path)
    assert dialog._ensure_storage()
    dialog._candidate_records = {
        "cand-1": _candidate(status=None) if False else _candidate()
    }
    dialog._candidate_store = None
    dialog._populate_candidate_table()
    app.processEvents()
    dialog.candidate_table.selectRow(0)
    app.processEvents()
    overlay = widget.canvas.inspection_candidates
    assert [item.candidate_id for item in overlay] == ["cand-1"]
    # The overlay never touches formal shapes.
    before = {shape.xanylabeling_shape_id for shape in widget.canvas.shapes}
    assert before == {"id1", "id2"}
    dialog._clear_candidate_overlay()
    assert widget.canvas.inspection_candidates == []
    dialog.close()
    assert widget.canvas.inspection_candidates == []


def test_accept_adjusted_selects_new_object_and_rejects_cross_file(
    window, tmp_path
):
    app, widget, dialog = _open_inspector(window, tmp_path)
    assert dialog._ensure_storage()
    cross = _candidate(candidate_id="cross", relative_path="other.png")
    dialog._candidate_records = {"cross": cross}
    dialog._populate_candidate_table()
    dialog.candidate_table.selectRow(0)
    app.processEvents()
    assert not widget.canvas.inspection_candidates
    with patch.object(dialog, "_show_error") as show_error:
        dialog._accept_candidate()
    show_error.assert_called_once()
    assert "other.png" in show_error.call_args.args[1]
    assert len(widget.canvas.shapes) == 2

    same_file = _candidate(candidate_id="cand-ok")
    dialog._candidate_records = {"cand-ok": same_file}
    dialog._populate_candidate_table()
    dialog.candidate_table.selectRow(0)
    app.processEvents()
    before = len(widget.canvas.shapes)
    with patch(
        "anylabeling.views.labeling.inspector.dialog.CandidateAdjustmentDialog.exec",
        return_value=QtWidgets.QDialog.DialogCode.Accepted,
    ):
        dialog._accept_candidate_adjusted()
    app.processEvents()
    assert len(widget.canvas.shapes) == before + 1
    selected = widget.canvas.selected_shapes
    assert len(selected) == 1
    assert selected[0].label == "person"
    assert dialog._candidate_records["cand-ok"].status.value == "accepted"


def test_batch_accept_previews_exact_set(window, tmp_path):
    app, widget, dialog = _open_inspector(window, tmp_path)
    assert dialog._ensure_storage()
    records = {
        f"cand-{index}": _candidate(
            candidate_id=f"cand-{index}",
            region=(4 + index, 4 + index, 20 + index, 20 + index),
        )
        for index in range(3)
    }
    dialog._candidate_records = dict(records)
    dialog._populate_candidate_table()
    app.processEvents()
    before = len(widget.canvas.shapes)
    with patch.object(
        QtWidgets.QMessageBox,
        "question",
        return_value=QtWidgets.QMessageBox.StandardButton.Yes,
    ) as question:
        dialog._batch_accept_candidates()
    app.processEvents()
    preview = question.call_args.args[2]
    for candidate_id in records:
        assert candidate_id in preview
    assert len(widget.canvas.shapes) == before + 3
    assert all(
        record.status.value == "accepted"
        for record in dialog._candidate_records.values()
    )


def test_reopen_recovery_does_not_replay_accepted_candidate(window, tmp_path):
    app, widget, dialog = _open_inspector(window, tmp_path)
    assert dialog._ensure_storage()
    candidate = _candidate(candidate_id="cand-recover")
    dialog._candidate_records = {"cand-recover": candidate}
    dialog._populate_candidate_table()
    dialog.candidate_table.selectRow(0)
    app.processEvents()
    dialog._accept_candidate()
    app.processEvents()
    accepted = dialog._candidate_records["cand-recover"]
    assert accepted.status.value == "accepted"
    shape_id = accepted.accepted_shape_id
    assert shape_id
    # The formal object disappears (deleted externally / not saved).
    annotation = tmp_path / "image.json"
    payload = json.loads(annotation.read_text(encoding="utf-8"))
    payload["shapes"] = [
        item
        for item in payload["shapes"]
        if item.get("xanylabeling_shape_id") != shape_id
    ]
    annotation.write_text(json.dumps(payload), encoding="utf-8")
    assert widget.load_file(str(tmp_path / "image.png"))
    before = len(widget.canvas.shapes)
    dialog._load_candidates()
    app.processEvents()
    recovered = dialog._candidate_records["cand-recover"]
    assert recovered.status.value == "pending"
    assert recovered.accepted_shape_id == ""
    assert "不会重复画框" in recovered.reason
    assert len(widget.canvas.shapes) == before


def _report_and_issue(window, tmp_path):
    app, widget, dialog = _open_inspector(window, tmp_path)
    dialog.issue_table.selectRow(0)
    app.processEvents()
    return widget, dialog, dialog.report.issues[0]


def test_handoff_request_rejects_other_file_and_missing_snapshot(tmp_path):
    report_issue = None

    class _Location:
        relative_path = "a.png"
        image_path = ""
        object_ids = ("id1",)
        region = None
        snapshot_digest = "digest"

    class _Issue:
        issue_id = "i1"
        family_key = "f1"
        location = _Location()

    request = build_handoff_request(
        _Issue(), dataset_root=str(tmp_path), output_root=""
    )
    assert (
        validate_handoff(
            request,
            dataset_root=str(tmp_path),
            output_root="",
            current_relative_path="a.png",
        )
        == ""
    )
    other_file = validate_handoff(
        request,
        dataset_root=str(tmp_path),
        output_root="",
        current_relative_path="b.png",
    )
    assert other_file
    assert "定位" in other_file or "不一致" in other_file
    empty = replace(request, snapshot_digest="")
    assert "快照" in validate_handoff(
        empty,
        dataset_root=str(tmp_path),
        output_root="",
        current_relative_path="a.png",
    )


def test_handoff_unavailable_reports_honest_status():
    payload = handoff_payload(
        type(
            "_Issue",
            (),
            {
                "issue_id": "i1",
                "family_key": "f",
                "title": "t",
                "message": "m",
                "severity": type("S", (), {"value": "warning"})(),
                "location": type(
                    "L",
                    (),
                    {
                        "relative_path": "a.png",
                        "image_path": "",
                        "object_ids": (),
                        "shape_indices": (),
                        "group_id": None,
                        "region": None,
                    },
                )(),
                "evidence": (),
                "suggested_action": "",
            },
        )(),
        available=False,
    )
    assert payload["available"] is False
    assert payload["fallback"] == "ordinary_canvas"
    assert "未开展" in payload["message"]
    assert dense_review_available(None) is True


def test_handoff_button_uses_workspace_and_returns_to_queue(window, tmp_path):
    widget, dialog, issue = _report_and_issue(window, tmp_path)
    request_seen = {}

    def handler(request: HandoffRequest):
        request_seen["request"] = request
        return True, ""

    with (
        patch.object(
            widget, "inspection_dense_review_available", return_value=True
        ),
        patch.object(
            widget, "inspection_handoff_to_dense_review", side_effect=handler
        ),
    ):
        dialog._handoff_selected()
    assert "request" in request_seen
    assert request_seen["request"].family_key == issue.family_key
    assert dialog._handoff_family_key == issue.family_key
    # Returning to the queue selects the original row.
    dialog.issue_table.clearSelection()
    assert widget.inspection_handoff_return_context(issue.family_key) is True
    row_issue = dialog._row_issues[dialog.issue_table.currentRow()]
    assert row_issue.family_key == issue.family_key


def test_handoff_unavailable_shows_fallback_and_does_not_call_window(
    window, tmp_path
):
    widget, dialog, _ = _report_and_issue(window, tmp_path)
    with (
        patch.object(
            widget, "inspection_dense_review_available", return_value=False
        ),
        patch.object(widget, "inspection_handoff_to_dense_review") as handler,
        patch.object(QtWidgets.QMessageBox, "information") as information,
    ):
        dialog._handoff_selected()
    handler.assert_not_called()
    information.assert_called_once()
    assert "未开展" in information.call_args.args[2]
