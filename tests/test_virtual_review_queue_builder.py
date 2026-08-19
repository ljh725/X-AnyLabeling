"""Tests for cancellable queue construction and revision publishing.

Covers determinism, cancellation, parse/missing exclusions, staging
failure isolation, publication invariants, and active-revision
preservation on failed rebuilds.  Self-contained file.
"""

import json
import os
import os.path as osp
import sqlite3

import pytest

from anylabeling.views.labeling import virtual_review as vr

CRITERIA = vr.VirtualTaskCriteria(
    labels=frozenset({"person"}),
    shape_types=frozenset({"rectangle"}),
)


def _rect(gid=None, x=100, y=100, w=50, h=60):
    """Return one rectangle shape payload."""

    return {
        "label": "person",
        "shape_type": "rectangle",
        "group_id": gid,
        "points": [[x, y], [x + w, y + h]],
    }


def _write(root, name, shapes):
    """Write one image/annotation pair under ``root``."""

    os.makedirs(root, exist_ok=True)
    image_path = osp.join(root, f"{name}.jpg")
    label_path = osp.join(root, f"{name}.json")
    with open(image_path, "wb") as handle:
        handle.write(b"fake-image")
    _dump(label_path, shapes)
    return image_path, label_path


def _dump(label_path, shapes):
    with open(label_path, "w", encoding="utf-8") as handle:
        json.dump(
            {"imageWidth": 1000, "imageHeight": 800, "shapes": shapes},
            handle,
        )


def _request(root, descriptors, sidecar):
    """Build a standard scan request."""

    return vr.QueueBuildRequest(
        files=descriptors,
        criteria=CRITERIA,
        packing_options=vr.VirtualPackingOptions(mode="single"),
        reference_viewport=(1200.0, 800.0),
        sidecar_path=str(sidecar),
    )


def _published_store(root, descriptors, sidecar):
    """Scan, publish, and open a queue for editing."""

    draft = vr.scan_dataset(_request(root, descriptors, sidecar))
    assert draft.publishable, draft.diagnostics
    vr.publish_new_queue(draft)
    return vr.ReviewStore.open(str(sidecar))


def test_build_is_deterministic_across_runs(tmp_path):
    root = tmp_path / "ds"
    files = [
        ("a", [_rect(gid=1), _rect(x=400, y=300), _rect(x=700, y=500)]),
        ("b", [_rect(gid=2)]),
    ]
    descriptors = vr.descriptors_from_lists(
        str(root),
        *zip(*[_write(root, name, shapes) for name, shapes in files]),
    )
    first = vr.scan_dataset(
        _request(root, descriptors, tmp_path / "one.xreview.sqlite3")
    )
    second = vr.scan_dataset(
        _request(root, descriptors, tmp_path / "two.xreview.sqlite3")
    )
    assert first.stats == second.stats
    store_one = vr.ReviewStore.open(first.staging_path, editable=False)
    store_two = vr.ReviewStore.open(second.staging_path, editable=False)
    try:
        snap_one = store_one.load_snapshot()
        snap_two = store_two.load_snapshot()
        assert [f.label_rel_path for f in snap_one.files] == [
            f.label_rel_path for f in snap_two.files
        ]
        assert [
            [t.locator["bbox"] for t in snap_one.tasks_by_page[p.page_id]]
            for p in snap_one.pages
        ] == [
            [t.locator["bbox"] for t in snap_two.tasks_by_page[p.page_id]]
            for p in snap_two.pages
        ]
        # Task rows themselves are keyed by uuid and may be listed in
        # any order; their content multiset must still be identical.
        assert sorted(
            str(t.locator["bbox"]) for t in snap_one.tasks
        ) == sorted(str(t.locator["bbox"]) for t in snap_two.tasks)
    finally:
        store_one.close()
        store_two.close()


def test_cancellation_discards_staging_and_keeps_queue(tmp_path):
    root = tmp_path / "ds"
    descriptors = vr.descriptors_from_lists(
        str(root),
        *zip(
            *[
                _write(root, name, [_rect(gid=index)])
                for index, name in enumerate("abc")
            ]
        ),
    )
    sidecar = tmp_path / "q.xreview.sqlite3"
    store = _published_store(root, descriptors, sidecar)
    try:
        snapshot = store.load_snapshot()
        store.apply_outcomes(
            snapshot.revision,
            [
                vr.OutcomeChange(
                    snapshot.tasks[0].task_id,
                    vr.TaskOutcome.COMPLETED,
                    reviewed_signature=(snapshot.tasks[0].current_signature),
                )
            ],
            store.logical_revision,
        )
        revision = store.active_revision
    finally:
        store.close()

    def cancel_after_first():
        return cancel_after_first.count > 0

    cancel_after_first.count = 0
    progress_calls = []

    def progress(index, total, path):
        progress_calls.append((index, total))
        cancel_after_first.count += 1

    draft = vr.scan_dataset(
        _request(root, descriptors, sidecar),
        progress=progress,
        cancel=cancel_after_first,
    )
    assert draft.cancelled is True
    assert not osp.exists(draft.staging_path)
    assert progress_calls and progress_calls[0][1] == 3

    reopened = vr.ReviewStore.open(str(sidecar))
    try:
        assert reopened.active_revision == revision
        snapshot = reopened.load_snapshot()
        assert snapshot.tasks[0].outcome is vr.TaskOutcome.COMPLETED
    finally:
        reopened.close()


def test_parse_and_missing_files_recorded_as_exclusions(tmp_path):
    root = tmp_path / "ds"
    good = _write(root, "good", [_rect(gid=1)])
    broken = osp.join(root, "broken.json")
    with open(broken, "w", encoding="utf-8") as handle:
        handle.write("{ not json")
    ghost_label = osp.join(root, "ghost.json")
    image_paths = [
        good[0],
        osp.join(root, "broken.jpg"),
        osp.join(root, "ghost.jpg"),
    ]
    label_paths = [good[1], broken, ghost_label]
    descriptors = vr.descriptors_from_lists(
        str(root), image_paths, label_paths
    )
    sidecar = tmp_path / "q.xreview.sqlite3"
    draft = vr.scan_dataset(_request(root, descriptors, sidecar))
    assert draft.publishable, draft.diagnostics
    reasons = sorted(e.reason for e in draft.exclusions)
    assert reasons == ["missing", "parse"]
    store = _published_store(root, descriptors, sidecar)
    try:
        snapshot = store.load_snapshot()
        excluded = [
            f
            for f in snapshot.files
            if f.availability is vr.FileAvailability.EXCLUDED
        ]
        assert len(excluded) == 2
        assert all(f.exclusion_reason for f in excluded)
        assert len(snapshot.pages) == 1
    finally:
        store.close()


def test_zero_match_file_omitted_without_error(tmp_path):
    root = tmp_path / "ds"
    matching = _write(root, "a", [_rect(gid=1)])
    empty = _write(root, "b", [])
    descriptors = vr.descriptors_from_lists(
        str(root), [matching[0], empty[0]], [matching[1], empty[1]]
    )
    sidecar = tmp_path / "q.xreview.sqlite3"
    draft = vr.scan_dataset(_request(root, descriptors, sidecar))
    assert draft.publishable
    assert draft.stats.files_matched == 1
    assert draft.stats.files_total == 2
    store = _published_store(root, descriptors, sidecar)
    try:
        snapshot = store.load_snapshot()
        assert [f.label_rel_path for f in snapshot.files] == ["a.json"]
    finally:
        store.close()


def test_staging_failure_in_missing_directory_is_isolated(tmp_path):
    root = tmp_path / "ds"
    descriptors = vr.descriptors_from_lists(
        str(root), *zip(*[_write(root, "a", [_rect(gid=1)])])
    )
    sidecar = tmp_path / "no-dir" / "q.xreview.sqlite3"
    with pytest.raises(vr.InvalidSidecar):
        vr.scan_dataset(_request(root, descriptors, sidecar))
    assert not osp.exists(str(sidecar))
    assert not osp.exists(str(tmp_path / "no-dir"))


def test_publish_rejects_existing_sidecar_and_invalid_draft(tmp_path):
    root = tmp_path / "ds"
    descriptors = vr.descriptors_from_lists(
        str(root), *zip(*[_write(root, "a", [_rect(gid=1)])])
    )
    sidecar = tmp_path / "q.xreview.sqlite3"
    draft = vr.scan_dataset(_request(root, descriptors, sidecar))
    vr.publish_new_queue(draft)
    with pytest.raises(ValueError):
        vr.publish_new_queue(draft)
    invalid = vr.QueueDraft(
        request=draft.request,
        staging_path=draft.staging_path,
        stats=draft.stats,
        diagnostics=("synthetic failure",),
    )
    with pytest.raises(ValueError):
        vr.publish_new_queue(invalid)
    with pytest.raises(ValueError):
        vr.publish_rebuild(invalid, None, 1)


def test_each_page_belongs_to_exactly_one_source_file(tmp_path):
    root = tmp_path / "ds"
    descriptors = vr.descriptors_from_lists(
        str(root),
        *zip(
            *[
                _write(
                    root,
                    name,
                    [_rect(x=10 + index * 400, y=10)],
                )
                for index, name in enumerate("abcd")
            ]
        ),
    )
    sidecar = tmp_path / "q.xreview.sqlite3"
    request = vr.QueueBuildRequest(
        files=descriptors,
        criteria=CRITERIA,
        packing_options=vr.VirtualPackingOptions(mode="balanced"),
        reference_viewport=(1200.0, 800.0),
        sidecar_path=str(sidecar),
    )
    draft = vr.scan_dataset(request)
    assert draft.publishable, draft.diagnostics
    store = _published_store(root, descriptors, sidecar)
    try:
        snapshot = store.load_snapshot()
        assert snapshot.pages
        for page in snapshot.pages:
            member_files = {
                snapshot.task_by_id[task_id].file_id
                for task_id in page.task_ids
            }
            assert len(member_files) == 1
            assert member_files == {page.file_id}
    finally:
        store.close()


def test_failed_rebuild_keeps_active_revision_and_outcomes(tmp_path):
    root = tmp_path / "ds"
    descriptors = vr.descriptors_from_lists(
        str(root),
        *zip(
            *[
                _write(root, name, [_rect(gid=index)])
                for index, name in enumerate("ab")
            ]
        ),
    )
    sidecar = tmp_path / "q.xreview.sqlite3"
    store = _published_store(root, descriptors, sidecar)
    try:
        snapshot = store.load_snapshot()
        task = snapshot.tasks[0]
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
        revision = store.active_revision
        invalid = vr.QueueDraft(
            request=draft_request(descriptors, sidecar),
            staging_path="unused",
            diagnostics=("broken staging",),
        )
        with pytest.raises(ValueError):
            vr.publish_rebuild(invalid, store, store.logical_revision)
        assert store.active_revision == revision
        final = store.load_snapshot()
        assert (
            final.task_by_id[task.task_id].outcome is vr.TaskOutcome.COMPLETED
        )
    finally:
        store.close()


def draft_request(descriptors, sidecar):
    """Rebuild a scan request for existing descriptors."""

    return vr.QueueBuildRequest(
        files=descriptors,
        criteria=CRITERIA,
        packing_options=vr.VirtualPackingOptions(mode="single"),
        reference_viewport=(1200.0, 800.0),
        sidecar_path=str(sidecar),
    )


def test_corrupt_staging_fails_validation(tmp_path):
    root = tmp_path / "ds"
    descriptors = vr.descriptors_from_lists(
        str(root), *zip(*[_write(root, "a", [_rect(gid=1)])])
    )
    sidecar = tmp_path / "q.xreview.sqlite3"
    draft = vr.scan_dataset(_request(root, descriptors, sidecar))
    # Corrupt the staging database after the scan validated it.
    conn = sqlite3.connect(draft.staging_path)
    conn.execute("DELETE FROM page_task")
    conn.commit()
    conn.close()
    diagnostics = vr.validate_staging(draft.staging_path, draft.stats)
    assert diagnostics
    with pytest.raises(ValueError):
        vr.publish_new_queue(
            vr.QueueDraft(
                request=draft.request,
                staging_path=draft.staging_path,
                stats=draft.stats,
                diagnostics=tuple(diagnostics),
            )
        )
