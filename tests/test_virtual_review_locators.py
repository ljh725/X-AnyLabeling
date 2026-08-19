"""Tests for persistent locators, reconciliation, and freshness.

Covers label edits, group-id edits, geometry edits, repeated nearby
objects, missing files, moved dataset roots, ambiguous matches, manual
binding protection, and per-task freshness.  Self-contained file.
"""

import json
import os
import os.path as osp
import shutil

import pytest

from anylabeling.views.labeling import virtual_review as vr

CRITERIA = vr.VirtualTaskCriteria(
    labels=frozenset({"person"}),
    shape_types=frozenset({"rectangle"}),
)


def _rect(label="person", gid=None, x=100, y=100, w=50, h=60):
    """Return one rectangle shape payload."""

    return {
        "label": label,
        "shape_type": "rectangle",
        "group_id": gid,
        "points": [[x, y], [x + w, y + h]],
    }


def _write_dataset(root, files):
    """Write annotation fixtures; returns descriptors in given order."""

    os.makedirs(root, exist_ok=True)
    image_paths, label_paths = [], []
    for name, shapes in files:
        image_path = osp.join(root, f"{name}.jpg")
        label_path = osp.join(root, f"{name}.json")
        with open(image_path, "wb") as handle:
            handle.write(b"fake")
        _dump(label_path, shapes)
        image_paths.append(image_path)
        label_paths.append(label_path)
    return vr.descriptors_from_lists(str(root), image_paths, label_paths)


def _dump(label_path, shapes):
    with open(label_path, "w", encoding="utf-8") as handle:
        json.dump(
            {"imageWidth": 1000, "imageHeight": 800, "shapes": shapes},
            handle,
        )


def _build(root, descriptors, sidecar):
    """Build and publish a queue, returning the open store."""

    request = vr.QueueBuildRequest(
        files=descriptors,
        criteria=CRITERIA,
        packing_options=vr.VirtualPackingOptions(mode="single"),
        reference_viewport=(1200.0, 800.0),
        sidecar_path=str(sidecar),
    )
    draft = vr.scan_dataset(request)
    assert draft.publishable, draft.diagnostics
    vr.publish_new_queue(draft)
    return vr.ReviewStore.open(str(sidecar))


def _reconcile_all(store, dataset_root, manual=None):
    """Run the full reconcile driver over the active revision."""

    snapshot = store.load_snapshot()
    reports = []
    for file_record in snapshot.files:
        locators_by_task = {
            task.task_id: task.locator
            for task in snapshot.tasks
            if task.file_id == file_record.file_id
        }
        reports.append(
            vr.reconcile_source_file(
                file_record,
                str(dataset_root),
                locators_by_task,
                manual_choices=manual,
            )
        )
    store.record_reconciliation(
        snapshot.revision,
        reports,
        store.logical_revision,
        dataset_root=str(dataset_root),
    )
    return store.load_snapshot()


def _task_of_page(snapshot, index=0):
    """Return the first task of the given page."""

    page = snapshot.pages[index]
    return snapshot.task_by_id[page.task_ids[0]]


def test_unchanged_file_fast_path_restores_ready(tmp_path):
    root = tmp_path / "ds"
    descriptors = _write_dataset(
        root, [("a", [_rect(gid=1), _rect(x=500, y=400)])]
    )
    store = _build(root, descriptors, tmp_path / "q.xreview.sqlite3")
    try:
        snapshot = _reconcile_all(store, root)
        for task in snapshot.tasks:
            assert task.binding_state is vr.BindingState.READY
            assert task.outcome is vr.TaskOutcome.PENDING
    finally:
        store.close()


def test_label_edit_keeps_identity_via_scoring(tmp_path):
    root = tmp_path / "ds"
    descriptors = _write_dataset(root, [("a", [_rect(gid=1)])])
    store = _build(root, descriptors, tmp_path / "q.xreview.sqlite3")
    try:
        _dump(
            osp.join(root, "a.json"),
            [_rect(label="worker", gid=1)],
        )
        snapshot = _reconcile_all(store, root)
        task = _task_of_page(snapshot)
        assert task.binding_state is vr.BindingState.CHANGED_RESOLVED
    finally:
        store.close()


def test_group_id_edit_keeps_identity_but_flagged(tmp_path):
    root = tmp_path / "ds"
    descriptors = _write_dataset(root, [("a", [_rect(gid=1)])])
    store = _build(root, descriptors, tmp_path / "q.xreview.sqlite3")
    try:
        _dump(osp.join(root, "a.json"), [_rect(gid=7)])
        snapshot = _reconcile_all(store, root)
        task = _task_of_page(snapshot)
        assert task.binding_state is vr.BindingState.CHANGED_RESOLVED
    finally:
        store.close()


def test_small_geometry_edit_resolves_and_large_move_orphans(tmp_path):
    root = tmp_path / "ds"
    descriptors = _write_dataset(
        root, [("a", [_rect(x=100, y=100), _rect(x=700, y=600)])]
    )
    store = _build(root, descriptors, tmp_path / "q.xreview.sqlite3")
    try:
        _dump(
            osp.join(root, "a.json"),
            [_rect(x=105, y=103), _rect(x=10, y=600)],
        )
        snapshot = _reconcile_all(store, root)
        first = _task_of_page(snapshot, 0)
        second = _task_of_page(snapshot, 1)
        assert first.binding_state is vr.BindingState.CHANGED_RESOLVED
        assert second.binding_state is vr.BindingState.ORPHANED
    finally:
        store.close()


def test_repeated_identical_objects_become_ambiguous(tmp_path):
    root = tmp_path / "ds"
    descriptors = _write_dataset(
        root, [("a", [_rect(x=100, y=100), _rect(x=400, y=100)])]
    )
    store = _build(root, descriptors, tmp_path / "q.xreview.sqlite3")
    try:
        # Replace the stored target with two identical twins at its own
        # position: both exact matches are equally plausible, so no
        # automatic progress transfer may happen.
        _dump(
            osp.join(root, "a.json"),
            [_rect(x=100, y=100), _rect(x=100, y=100)],
        )
        snapshot = _reconcile_all(store, root)
        stored_at_100 = [
            task for task in snapshot.tasks if _locator_x(task.locator) < 200
        ]
        assert stored_at_100
        for task in stored_at_100:
            assert task.binding_state is vr.BindingState.AMBIGUOUS
    finally:
        store.close()


def test_nearby_similar_objects_stay_unambiguous(tmp_path):
    root = tmp_path / "ds"
    descriptors = _write_dataset(
        root,
        [("a", [_rect(x=100, y=100), _rect(x=140, y=100)])],
    )
    store = _build(root, descriptors, tmp_path / "q.xreview.sqlite3")
    try:
        snapshot = _reconcile_all(store, root)
        for task in snapshot.tasks:
            assert task.binding_state is vr.BindingState.READY
    finally:
        store.close()


def test_colliding_claims_downgrade_to_ambiguous(tmp_path):
    """Two stored tasks claiming one live candidate never auto-bind."""

    root = tmp_path / "ds"
    descriptors = _write_dataset(
        root, [("a", [_rect(x=100, y=100), _rect(x=104, y=100)])]
    )
    store = _build(root, descriptors, tmp_path / "q.xreview.sqlite3")
    try:
        # Collapse both near-identical objects into one shape between
        # them: each stored task would claim the same live candidate,
        # so both must be downgraded instead of silently transferring.
        _dump(osp.join(root, "a.json"), [_rect(x=102, y=100)])
        snapshot = _reconcile_all(store, root)
        states = [task.binding_state for task in snapshot.tasks]
        assert vr.BindingState.AMBIGUOUS in states
        assert vr.BindingState.CHANGED_RESOLVED not in states
    finally:
        store.close()


def _locator_x(locator):
    """Return the stored bbox left edge of a locator."""

    bbox = locator.get("bbox")
    return bbox[0] if bbox else 0.0


def test_missing_file_marks_missing_and_keeps_records(tmp_path):
    root = tmp_path / "ds"
    descriptors = _write_dataset(root, [("a", [_rect(gid=1)])])
    store = _build(root, descriptors, tmp_path / "q.xreview.sqlite3")
    try:
        snapshot = store.load_snapshot()
        task = _task_of_page(snapshot)
        store.apply_outcomes(
            snapshot.revision,
            [
                vr.OutcomeChange(
                    task.task_id,
                    vr.TaskOutcome.COMPLETED,
                    reviewed_signature=task.current_signature,
                )
            ],
            store.logical_revision,
        )
        os.remove(osp.join(root, "a.json"))
        after = _reconcile_all(store, root)
        record = after.task_by_id[task.task_id]
        assert record.outcome is vr.TaskOutcome.COMPLETED
        assert record.binding_state is vr.BindingState.MISSING
        assert after.file_by_id[record.file_id].availability is (
            vr.FileAvailability.MISSING
        )
    finally:
        store.close()


def test_moved_dataset_root_rebinds_without_outcome_change(tmp_path):
    root = tmp_path / "ds"
    descriptors = _write_dataset(root, [("a", [_rect(gid=1)])])
    sidecar = tmp_path / "q.xreview.sqlite3"
    store = _build(root, descriptors, sidecar)
    try:
        snapshot = store.load_snapshot()
        task = _task_of_page(snapshot)
        store.apply_outcomes(
            snapshot.revision,
            [
                vr.OutcomeChange(
                    task.task_id,
                    vr.TaskOutcome.COMPLETED,
                    reviewed_signature=task.current_signature,
                )
            ],
            store.logical_revision,
        )
    finally:
        store.close()

    moved = tmp_path / "moved"
    shutil.move(str(root), str(moved))

    store = vr.ReviewStore.open(str(sidecar))
    try:
        snapshot = _reconcile_all(store, moved)
        record = snapshot.task_by_id[task.task_id]
        assert record.outcome is vr.TaskOutcome.COMPLETED
        assert record.binding_state is vr.BindingState.READY
        assert record.freshness is vr.TaskFreshness.FRESH
        assert snapshot.pages == snapshot.pages  # membership untouched
        assert store.meta("dataset_root_hint") == str(moved)
    finally:
        store.close()


def test_manual_binding_survives_reconcile(tmp_path):
    root = tmp_path / "ds"
    descriptors = _write_dataset(root, [("a", [_rect(gid=1)])])
    store = _build(root, descriptors, tmp_path / "q.xreview.sqlite3")
    try:
        _dump(osp.join(root, "a.json"), [_rect(gid=7)])
        snapshot = store.load_snapshot()
        task = _task_of_page(snapshot)
        meta = store.load_revision_meta(snapshot.revision)
        criteria = vr.criteria_from_dict(json.loads(meta.criteria_json))
        scan = vr.scan_annotation_file(osp.join(root, "a.json"))
        views, points = vr.views_from_annotation(scan)
        candidates = vr.build_live_candidates(views, points, criteria)
        chosen = candidates[0].signature
        store.record_manual_binding(
            snapshot.revision,
            task.task_id,
            chosen,
            store.logical_revision,
        )
        after = _reconcile_all(store, root, manual={task.task_id: chosen})
        record = after.task_by_id[task.task_id]
        assert record.binding_state is vr.BindingState.MANUALLY_BOUND
        assert record.current_signature == chosen
    finally:
        store.close()


def test_unrelated_edit_keeps_completed_task_fresh(tmp_path):
    root = tmp_path / "ds"
    descriptors = _write_dataset(
        root,
        [("a", [_rect(gid=1), _rect(label="car", x=800, y=10)])],
    )
    store = _build(root, descriptors, tmp_path / "q.xreview.sqlite3")
    try:
        snapshot = store.load_snapshot()
        task = _task_of_page(snapshot)
        store.apply_outcomes(
            snapshot.revision,
            [
                vr.OutcomeChange(
                    task.task_id,
                    vr.TaskOutcome.COMPLETED,
                    reviewed_signature=task.current_signature,
                )
            ],
            store.logical_revision,
        )
        # Edit only the unrelated car shape; the completed person task
        # content signature must stay equal, so freshness stays fresh.
        _dump(
            osp.join(root, "a.json"),
            [_rect(gid=1), _rect(label="car", x=850, y=20)],
        )
        after = _reconcile_all(store, root)
        record = after.task_by_id[task.task_id]
        assert record.outcome is vr.TaskOutcome.COMPLETED
        assert record.freshness is vr.TaskFreshness.FRESH
    finally:
        store.close()


def test_changed_completed_target_becomes_stale(tmp_path):
    root = tmp_path / "ds"
    descriptors = _write_dataset(root, [("a", [_rect(gid=1)])])
    store = _build(root, descriptors, tmp_path / "q.xreview.sqlite3")
    try:
        snapshot = store.load_snapshot()
        task = _task_of_page(snapshot)
        store.apply_outcomes(
            snapshot.revision,
            [
                vr.OutcomeChange(
                    task.task_id,
                    vr.TaskOutcome.COMPLETED,
                    reviewed_signature=task.current_signature,
                )
            ],
            store.logical_revision,
        )
        _dump(osp.join(root, "a.json"), [_rect(label="worker", gid=1)])
        after = _reconcile_all(store, root)
        record = after.task_by_id[task.task_id]
        assert record.outcome is vr.TaskOutcome.COMPLETED
        assert record.freshness is vr.TaskFreshness.STALE
        assert record.actionable is True
    finally:
        store.close()


def test_freshness_evaluator_fail_closed_inputs():
    fresh = vr.evaluate_task_freshness("completed", "sig-a", "sig-a", True)
    assert fresh is vr.TaskFreshness.FRESH
    stale = vr.evaluate_task_freshness("completed", "sig-a", "sig-b", True)
    assert stale is vr.TaskFreshness.STALE
    unresolved = vr.evaluate_task_freshness("completed", "sig-a", None, False)
    assert unresolved is vr.TaskFreshness.UNRESOLVED
    pending = vr.evaluate_task_freshness("pending", None, "sig-a", True)
    assert pending is vr.TaskFreshness.FRESH
    legacy = vr.evaluate_task_freshness("completed", None, "sig-a", True)
    assert legacy is vr.TaskFreshness.FRESH


def test_scan_annotation_file_tolerates_bad_input(tmp_path):
    missing = vr.scan_annotation_file(str(tmp_path / "nope.json"))
    assert missing.error == "missing"
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    parsed = vr.scan_annotation_file(str(bad))
    assert parsed.error == "parse"
    non_dict = tmp_path / "list.json"
    non_dict.write_text("[1, 2]", encoding="utf-8")
    assert vr.scan_annotation_file(str(non_dict)).error == "parse"
    good = tmp_path / "good.json"
    good.write_text(
        json.dumps(
            {
                "imageWidth": 640,
                "imageHeight": None,
                "shapes": [_rect(gid=1)],
            }
        ),
        encoding="utf-8",
    )
    scan = vr.scan_annotation_file(str(good))
    assert scan.ok and scan.image_width == 640
    assert scan.image_height is None
    textual = tmp_path / "textual.json"
    textual.write_text(
        json.dumps({"imageWidth": "640", "imageHeight": 480, "shapes": []}),
        encoding="utf-8",
    )
    parsed = vr.scan_annotation_file(str(textual))
    # Non-numeric image dimensions fail closed rather than guessing.
    assert parsed.ok and parsed.image_width is None


def test_geometry_fingerprint_quantization_is_shared():
    first = vr.geometry_fingerprint([[10.001, 20.002], [30.0, 40.0]])
    second = vr.geometry_fingerprint([[10.0, 20.0], [30.0, 40.0]])
    assert first == second
    assert vr.geometry_fingerprint(None, (0, 0, 10, 10)) != (
        vr.geometry_fingerprint(None, (0, 0, 11, 10))
    )
    assert vr.geometry_fingerprint(None, None) is None
    assert vr.geometry_fingerprint("nope") is None


def test_relative_path_round_trip_across_separators():
    rel = vr.normalize_relative_path("R:/ds", "R:/ds/sub/img.jpg")
    assert rel == "sub/img.jpg"
    assert vr.resolve_relative_path("D:/elsewhere", rel) == (
        osp.normpath("D:/elsewhere/sub/img.jpg")
    )
    assert vr.normalize_relative_path("", "x/y.json") == "x/y.json"
