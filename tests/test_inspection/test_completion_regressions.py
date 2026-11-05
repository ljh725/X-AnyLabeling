"""Remaining Inspector tasks: edit commits, immutable reports and recovery."""

import json
from dataclasses import replace
from unittest.mock import patch

import pytest
from PyQt6 import QtCore, QtWidgets

from anylabeling.services.inspection.candidates import AcceptIntentStore
from anylabeling.services.inspection.duplicate import full_scan
from anylabeling.services.inspection.incremental import (
    DuplicateTracker,
    rectangles_from_file,
)
from anylabeling.services.inspection.manifest import (
    build_manifest,
    compare_manifests,
    memory_file_snapshot,
)
from anylabeling.services.inspection.models import Candidate, CandidateStatus
from anylabeling.services.inspection.profiles import default_profiles
from anylabeling.services.inspection.runner import InspectionRunner
from anylabeling.services.inspection.storage import ReportStore, StorageError
from anylabeling.views.labeling.inspector.dialog import (
    CandidateAdjustmentDialog,
)
from tests.test_inspection.test_inspector_dialog import (  # noqa: F401
    _prepare_image,
    _wait_until,
    window as _inspector_window,
)

window = _inspector_window


def _snapshot(tmp_path, ids=("id1", "id2")):
    return memory_file_snapshot(
        str(tmp_path / "image.png"),
        "image.png",
        [
            dict(
                label="person",
                shape_type="rectangle",
                points=[[0, 0], [10, 10]],
                xanylabeling_shape_id=sid,
            )
            for sid in ids
        ],
        image_width=64,
        image_height=64,
    )


def _open(window, tmp_path, *, separated=False):
    widget = window.labeling_widget.view
    image = _prepare_image(tmp_path)
    path = tmp_path / "image.json"
    if separated:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["shapes"][1]["points"] = [[40, 40], [60, 60]]
        path.write_text(json.dumps(payload), encoding="utf-8")
    assert widget.load_file(image)
    widget.open_inspector()
    dialog = widget.inspector_dialog
    dialog.profile_combo.setCurrentIndex(
        dialog.profile_combo.findData("generic")
    )
    dialog._start_run()
    assert _wait_until(
        QtWidgets.QApplication.instance(), lambda: dialog.report is not None
    )
    return widget, dialog


def _candidate():
    return Candidate(
        candidate_id="recovery",
        source="model",
        source_version="1",
        relative_path="image.png",
        image_path="",
        label="person",
        region=(10, 10, 25, 25),
        image_width=64,
        image_height=64,
    )


def test_snapshot_sync_removes_objects_without_scanning_unchanged_pairs(
    tmp_path,
):
    tracker = DuplicateTracker()
    tracker.load_file("image.png", _snapshot(tmp_path))
    with patch(
        "anylabeling.services.inspection.incremental.full_scan",
        side_effect=AssertionError("edit commit must not rescan all pairs"),
    ):
        result = tracker.synchronize_file(
            "image.png", _snapshot(tmp_path, ("id1",))
        )
    assert result.pairs == ()
    assert set(tracker.detectors["image.png"].rectangles) == {"id1"}
    result = tracker.synchronize_file(
        "image.png", _snapshot(tmp_path), verify=True
    )
    rectangles, _ = rectangles_from_file(_snapshot(tmp_path))
    assert result.consistent
    assert result.pairs == full_scan(rectangles, tracker.thresholds).pairs


def test_changed_scope_compares_image_orientation(tmp_path):
    _prepare_image(tmp_path)
    manifest = build_manifest(str(tmp_path))
    assert manifest.files[0].image_orientation == "1"
    modified = replace(
        manifest, files=(replace(manifest.files[0], image_orientation="6"),)
    )
    delta = compare_manifests(manifest, modified)
    assert delta.modified == ("image.png",)
    assert "方向" in delta.reasons["image.png"]


def test_report_identity_cannot_be_overwritten(tmp_path):
    _prepare_image(tmp_path)
    manifest = build_manifest(str(tmp_path))
    report = InspectionRunner().run(manifest, default_profiles()[0])
    store = ReportStore(str(tmp_path / "store"))
    path = store.save(report, manifest)
    original = open(path, "rb").read()
    with pytest.raises(StorageError, match="不可覆盖"):
        store.save(replace(report, issues=()), manifest)
    assert open(path, "rb").read() == original
    assert store.save(report, manifest) == path


def test_report_page_does_not_materialize_or_cache_whole_report(tmp_path):
    _prepare_image(tmp_path)
    report = InspectionRunner().run(
        build_manifest(str(tmp_path)), default_profiles()[0]
    )
    store = ReportStore(str(tmp_path / "store"))
    store.save(report)
    store._cache.clear()
    with patch.object(
        store, "load", side_effect=AssertionError("whole report decoded")
    ):
        page = store.read_issue_page(report.run_id, 0, 1)
    assert len(page) == 1
    assert page[0]["family_key"] == report.issues[0].family_key
    assert not store._cache


def test_first_issue_appears_after_editing_a_clean_image(window, tmp_path):
    widget, dialog = _open(window, tmp_path, separated=True)
    assert not dialog.report.issues
    shape = next(
        s for s in widget.canvas.shapes if s.xanylabeling_shape_id == "id2"
    )
    shape.points = [QtCore.QPointF(4, 4), QtCore.QPointF(30, 30)]
    widget.canvas.shape_moved.emit()
    assert any(
        "duplicate_boxes" in issue.rule_ids for issue in dialog.report.issues
    )
    assert dialog._duplicate_tracker is not None


def test_saved_candidate_undo_redo_tracks_document_not_stale_disk(
    window, tmp_path
):
    widget, dialog = _open(window, tmp_path)
    candidate = _candidate()
    dialog._candidate_records = {candidate.candidate_id: candidate}
    dialog._populate_candidate_table()
    dialog.candidate_table.selectRow(0)
    dialog._accept_candidate()
    assert len(widget.canvas.shapes) == 3
    assert (
        dialog._intent_store.load()[candidate.candidate_id]["status"]
        == "applied"
    )
    assert "尚未保存" in dialog.candidate_table.item(0, 0).toolTip()
    widget.save_file()
    assert not widget.dirty
    assert (
        dialog._intent_store.load()[candidate.candidate_id]["status"]
        == "confirmed"
    )
    widget.undo_shape_edit()
    dialog._on_canvas_edit()
    assert len(widget.canvas.shapes) == 2
    assert (
        dialog._candidate_records[candidate.candidate_id].status
        is CandidateStatus.PENDING
    )
    widget.redo_shape_edit()
    dialog._on_canvas_edit()
    assert len(widget.canvas.shapes) == 3
    assert (
        dialog._candidate_records[candidate.candidate_id].status
        is CandidateStatus.ACCEPTED
    )


def test_failed_acceptance_sidecar_does_not_allow_duplicate_object(
    window, tmp_path
):
    widget, dialog = _open(window, tmp_path)
    candidate = _candidate()
    dialog._candidate_records = {candidate.candidate_id: candidate}
    dialog._populate_candidate_table()
    dialog.candidate_table.selectRow(0)
    with patch.object(
        dialog._intent_store, "applied", side_effect=StorageError("disk full")
    ):
        dialog._accept_candidate()
    assert len(widget.canvas.shapes) == 3
    assert (
        dialog._candidate_records[candidate.candidate_id].status
        is CandidateStatus.ACCEPTED
    )
    with patch.object(dialog, "_show_error"):
        dialog._accept_candidate()
    assert len(widget.canvas.shapes) == 3


def test_corrupt_candidate_intents_are_not_treated_as_empty(tmp_path):
    store = AcceptIntentStore(str(tmp_path))
    (tmp_path / "candidate_intents.json").write_text("{", encoding="utf-8")
    with pytest.raises(StorageError):
        store.load()


def test_adjusted_candidate_cancel_does_not_create_object(window, tmp_path):
    widget, dialog = _open(window, tmp_path)
    candidate = _candidate()
    dialog._candidate_records = {candidate.candidate_id: candidate}
    dialog._populate_candidate_table()
    dialog.candidate_table.selectRow(0)
    before = len(widget.canvas.shapes)
    with patch.object(
        CandidateAdjustmentDialog,
        "exec",
        return_value=QtWidgets.QDialog.DialogCode.Rejected,
    ):
        dialog._accept_candidate_adjusted()
    assert len(widget.canvas.shapes) == before
    assert dialog._candidate_records[candidate.candidate_id] == candidate


def test_adjusted_candidate_is_edited_before_acceptance(window, tmp_path):
    widget, dialog = _open(window, tmp_path)
    candidate = _candidate()
    dialog._candidate_records = {candidate.candidate_id: candidate}
    dialog._populate_candidate_table()
    dialog.candidate_table.selectRow(0)

    def accept_draft(editor):
        editor.coordinates[0].setValue(12)
        editor.coordinates[2].setValue(35)
        editor._accept_draft()
        return editor.result()

    with patch.object(CandidateAdjustmentDialog, "exec", accept_draft):
        dialog._accept_candidate_adjusted()
    shape = next(
        s
        for s in widget.canvas.shapes
        if s.attributes.get("inspection_candidate_id")
        == candidate.candidate_id
    )
    assert min(p.x() for p in shape.points) == 12
    assert max(p.x() for p in shape.points) == 35


def test_imported_builtin_cannot_replace_shipped_template(window, tmp_path):
    widget, dialog = _open(window, tmp_path)
    original = dialog._profiles["generic"]
    path = tmp_path / "imported.json"
    path.write_text(
        json.dumps(replace(original, name="changed").to_dict()),
        encoding="utf-8",
    )
    with patch.object(
        QtWidgets.QFileDialog,
        "getOpenFileName",
        return_value=(str(path), "JSON"),
    ):
        dialog._import_profile()
    assert dialog._profiles["generic"] == original
    custom = [p for p in dialog._profiles.values() if p.name == "changed"]
    assert len(custom) == 1 and not custom[0].builtin


def test_gui_pages_bound_rows_and_restore_a_distant_issue(window, tmp_path):
    widget, dialog = _open(window, tmp_path)
    issue = dialog.report.issues[0]
    dialog.report = replace(
        dialog.report,
        issues=tuple(
            replace(issue, family_key=f"row-{index}", issue_id=f"row-{index}")
            for index in range(450)
        ),
    )
    dialog._populate_table()
    assert dialog.issue_table.rowCount() == 200
    assert dialog.next_page_button.isEnabled()
    assert dialog.focus_family("row-410")
    assert dialog._issue_page == 2
    assert dialog.issue_table.rowCount() == 50
    assert dialog._selected_issue().family_key == "row-410"


def test_alternative_report_save_preserves_recoverable_manifest(
    window, tmp_path
):
    widget, dialog = _open(window, tmp_path)
    destination = tmp_path / "alternate"
    destination.mkdir()
    with patch.object(
        QtWidgets.QFileDialog,
        "getExistingDirectory",
        return_value=str(destination),
    ):
        dialog._save_report_elsewhere()
    from anylabeling.services.inspection.storage import InspectionStorage

    alternate = InspectionStorage.open(
        str(tmp_path), "", preferred=str(destination)
    )
    assert (
        alternate.reports.load(dialog.report.run_id).issues
        == dialog.report.issues
    )
    assert alternate.reports.load_manifest(dialog.report.run_id).files


def test_inspector_shortcuts_are_configurable_and_do_not_steal_canvas_keys(
    window, tmp_path
):
    widget, dialog = _open(window, tmp_path)
    widget._config["shortcuts"]["inspector_run"] = "F8"
    widget._config["shortcuts"]["inspector_locate"] = None
    dialog._refresh_shortcuts()
    assert dialog.start_shortcut.key().toString() == "F8"
    assert dialog.start_shortcut.isEnabled()
    assert not dialog.locate_shortcut.isEnabled()
    widget._config["shortcuts"]["inspector_run"] = widget._config["shortcuts"][
        "open"
    ]
    dialog._refresh_shortcuts()
    assert not dialog.start_shortcut.isEnabled()


def test_candidate_rejects_same_size_image_replaced_since_import(
    window, tmp_path
):
    widget, dialog = _open(window, tmp_path)
    from PIL import Image
    from anylabeling.services.inspection.manifest import file_digest

    candidate = replace(
        _candidate(),
        image_digest=file_digest(widget.filename),
        image_digest_kind="content",
    )
    Image.new("RGB", (64, 64), "red").save(widget.filename)
    ok, _ = widget.inspection_accept_candidate(candidate)
    assert not ok
    assert len(widget.canvas.shapes) == 2


def test_tiny_geometry_change_does_not_keep_a_report_current(tmp_path):
    from anylabeling.services.inspection.manifest import (
        shape_collection_digest,
    )

    before = _snapshot(tmp_path)
    moved = replace(
        before.shapes[0],
        points=((0.0000001, 0), (10, 0), (10, 10), (0.0000001, 10)),
    )
    assert shape_collection_digest((moved,)) != shape_collection_digest(
        (before.shapes[0],)
    )


def test_committed_field_edit_updates_inspector_without_canvas_move(
    window, tmp_path
):
    widget, dialog = _open(window, tmp_path)
    widget._apply_field_patch(
        [widget.canvas.shapes[0]], {"label": "changed"}, {"label"}
    )
    assert any(
        issue.verification.value == "pending_recheck"
        for issue in dialog.report.issues
    )
    assert any("changed" in issue.message for issue in dialog.report.issues)


def test_real_dense_review_handoff_and_return_keep_queue_context(
    window, tmp_path
):
    widget, dialog = _open(window, tmp_path)
    issue = dialog.report.issues[0]
    dialog.issue_table.selectRow(0)
    try:
        dialog._handoff_selected()
        workspace = widget.dense_review_workspace
        assert workspace is not None and workspace.isVisible()
        assert widget.dense_review_session is not None
        assert widget.inspection_handoff_return_context(issue.family_key)
        assert dialog._selected_issue().family_key == issue.family_key
        widget._apply_field_patch(
            [widget.canvas.shapes[0]], {"label": "changed"}, {"label"}
        )
        assert any(
            i.verification.value == "pending_recheck"
            for i in dialog.report.issues
        )
    finally:
        if widget.dense_review_workspace is not None:
            widget.dense_review_workspace.close()
            widget.dense_review_workspace.shutdown()


def test_dense_scan_stops_collecting_at_its_explicit_limit():
    from anylabeling.services.inspection.duplicate import (
        PRESETS,
        RectangleSnapshot,
    )

    rectangles = [
        RectangleSnapshot(str(i), "person", (0, 0, 10, 10)) for i in range(150)
    ]
    result = full_scan(rectangles, PRESETS["medium"], max_pairs=5)
    assert len(result.pairs) == 5
    assert result.truncated and not result.complete


def test_candidate_overlay_clears_on_image_change(window, tmp_path):
    widget, dialog = _open(window, tmp_path)
    widget.show_inspection_candidates([_candidate()])
    assert widget.canvas.inspection_candidates
    widget.canvas.reset_state()
    assert not widget.canvas.inspection_candidates


def test_candidate_import_allows_a_valid_image_without_annotation(tmp_path):
    from anylabeling.services.inspection.candidates import load_candidates

    _prepare_image(tmp_path)
    (tmp_path / "image.json").unlink()
    path = tmp_path / "external.json"
    path.write_text(
        json.dumps({"candidates": [_candidate().to_dict()]}), encoding="utf-8"
    )
    result = load_candidates(str(path), manifest=build_manifest(str(tmp_path)))
    assert len(result.candidates) == 1
    assert result.candidates[0].image_digest


def test_new_ui_strings_are_shipped_in_all_compiled_languages():
    from PyQt6 import QtCore

    for language in ("zh_CN", "en_US", "ja_JP", "ko_KR"):
        translator = QtCore.QTranslator()
        assert translator.load(f":/languages/translations/{language}.qm")
        for context, source in (
            ("InspectorDialog", "上一页"),
            ("InspectorDialog", "打开报告保存位置"),
            ("CandidateAdjustmentDialog", "调整后接受"),
            ("ProfileRuleEditor", "启用"),
        ):
            # QTranslator's raw char* API accepts UTF-8 bytes; QObject.tr
            # handles this conversion internally for the product UI.
            assert translator.translate(context, source.encode("utf-8"))


def test_alternative_report_location_can_be_reopened(window, tmp_path):
    widget, dialog = _open(window, tmp_path)
    run_id = dialog.report.run_id
    destination = tmp_path / "alternate-reopen"
    destination.mkdir()
    with patch.object(
        QtWidgets.QFileDialog,
        "getExistingDirectory",
        return_value=str(destination),
    ):
        dialog._save_report_elsewhere()
        dialog.report = None
        dialog._open_report_location()
    assert dialog.report.run_id == run_id
    assert dialog.manifest.files


def test_damaged_candidate_record_is_reported_without_overwrite(tmp_path):
    from anylabeling.services.inspection.candidates import CandidateStore
    from anylabeling.services.inspection.models import CANDIDATE_SCHEMA_VERSION

    path = tmp_path / "candidate_state.json"
    content = json.dumps(
        {
            "schema_version": CANDIDATE_SCHEMA_VERSION,
            "candidates": {"bad": {"region": [0]}},
        }
    )
    path.write_text(content, encoding="utf-8")
    with pytest.raises(StorageError):
        CandidateStore(str(tmp_path)).load()
    assert path.read_text(encoding="utf-8") == content


def test_incremental_pair_budget_is_explicit_and_recovers_after_delete(
    tmp_path,
):
    tracker = DuplicateTracker(max_pairs=5)
    tracker.load_file("image.png", _snapshot(tmp_path))
    dense = _snapshot(tmp_path, tuple(str(i) for i in range(150)))
    partial = tracker.synchronize_file("image.png", dense)
    assert partial.truncated and len(partial.pairs) == 5
    assert len(tracker.detectors["image.png"].pairs) == 5
    cleared = tracker.synchronize_file(
        "image.png", _snapshot(tmp_path, ("one",))
    )
    assert not cleared.truncated and not cleared.pairs


def test_one_file_recheck_keeps_manifest_for_other_queue_files(
    window, tmp_path
):
    widget, dialog = _open(window, tmp_path)
    from PIL import Image
    from anylabeling.services.inspection.models import RunScope

    Image.new("RGB", (64, 64)).save(tmp_path / "second.png")
    (tmp_path / "second.json").write_bytes(
        (tmp_path / "image.json").read_bytes()
    )
    manifest = build_manifest(str(tmp_path))
    full = InspectionRunner().run(manifest, default_profiles()[0])
    dialog.report, dialog.manifest = full, manifest
    dialog._recheck_issue = next(
        i for i in full.issues if i.location.relative_path == "image.png"
    )
    current = widget.inspection_current_manifest()
    checked = InspectionRunner().run(
        current, default_profiles()[0], RunScope.CURRENT_IMAGE
    )
    dialog._finish_recheck(checked, current)
    saved = dialog.storage.reports.load_manifest(dialog.report.run_id)
    assert {f.relative_path for f in saved.files} == {
        "image.png",
        "second.png",
    }
    assert dialog.report.manifest_fingerprint == saved.fingerprint()


def test_feedback_conflict_preserves_both_processes(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    from anylabeling.services.inspection.models import FeedbackRecord
    from anylabeling.services.inspection.storage import FeedbackStore

    store = FeedbackStore(str(tmp_path))
    store.upsert(FeedbackRecord(family_key="parent", issue_id="parent"), 0)
    script = """
import json, sys
from anylabeling.services.inspection.models import FeedbackRecord
from anylabeling.services.inspection.storage import FeedbackStore, RevisionConflict
try:
    FeedbackStore(sys.argv[1]).upsert(FeedbackRecord(family_key='child', issue_id='child'), 0)
except RevisionConflict as error:
    print(json.dumps({'conflict': error.conflict_path}))
else:
    raise AssertionError('another process overwrote the first writer')
"""
    child = subprocess.run(
        [sys.executable, "-B", "-c", script, str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    conflict = Path(json.loads(child.stdout)["conflict"])
    payload = json.loads(conflict.read_text(encoding="utf-8"))
    assert "parent" in payload["current"]["records"]
    assert "child" in payload["attempted"]["records"]
    assert set(store.load().records) == {"parent"}


def test_global_issue_budget_marks_unpublished_source_coverage(tmp_path):
    from anylabeling.services.inspection.models import (
        Manifest,
        RuleConfig,
        RunState,
    )

    first = _snapshot(tmp_path)
    files = tuple(replace(first, relative_path=f"{i}.png") for i in range(5))
    profile = replace(
        default_profiles()[0], rules=(RuleConfig("duplicate_boxes"),)
    )
    report = InspectionRunner(max_issues=2).run(
        Manifest(str(tmp_path), "", files), profile
    )
    assert len(report.issues) == 2
    assert report.truncated and report.state is RunState.PARTIAL
    tail = [
        entry for entry in report.coverage if entry.relative_path == "4.png"
    ]
    assert tail and all(entry.truncated for entry in tail)
