"""Tests for outcomes, page states, filters, resume, and rebuilds.

Covers mixed smart pages, selected-task actions, page-wide completion
of live-bound tasks only, stale completions, resets, filter boundaries
without wrapping, resume behavior, reconcile invariance, and
conservative rebuild carry-forward.  Self-contained file.
"""

import json
import os
import os.path as osp

import pytest

from anylabeling.views.labeling import virtual_review as vr

CRITERIA = vr.VirtualTaskCriteria(
    labels=frozenset({"person"}),
    shape_types=frozenset({"rectangle"}),
)


def _rect(gid=None, x=100, y=100, w=50, h=60, label="person"):
    """Return one rectangle shape payload."""

    return {
        "label": label,
        "shape_type": "rectangle",
        "group_id": gid,
        "points": [[x, y], [x + w, y + h]],
    }


def _dump(label_path, shapes):
    with open(label_path, "w", encoding="utf-8") as handle:
        json.dump(
            {"imageWidth": 1000, "imageHeight": 800, "shapes": shapes},
            handle,
        )


@pytest.fixture()
def queue(tmp_path):
    """Publish a three-file, single-task-per-page queue."""

    root = tmp_path / "ds"
    image_paths, label_paths = [], []
    for index, name in enumerate("abc"):
        image_path = osp.join(root, f"{name}.jpg")
        label_path = osp.join(root, f"{name}.json")
        os.makedirs(root, exist_ok=True)
        with open(image_path, "wb") as handle:
            handle.write(b"img")
        _dump(label_path, [_rect(gid=index + 1)])
        image_paths.append(image_path)
        label_paths.append(label_path)
    descriptors = vr.descriptors_from_lists(
        str(root), image_paths, label_paths
    )
    sidecar = tmp_path / "q.xreview.sqlite3"
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
    store = vr.ReviewStore.open(str(sidecar))
    yield store, root, request
    store.close()


def _complete(store, task):
    """Complete one task and return the mutation result."""

    return store.apply_outcomes(
        store.active_revision,
        [
            vr.OutcomeChange(
                task.task_id,
                vr.TaskOutcome.COMPLETED,
                reviewed_signature=task.current_signature,
            )
        ],
        store.logical_revision,
    )


def _reconcile(store, root, manual=None):
    """Run the reconcile driver and reload the snapshot."""

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
                str(root),
                locators_by_task,
                manual_choices=manual,
            )
        )
    store.record_reconciliation(
        snapshot.revision,
        reports,
        store.logical_revision,
        dataset_root=str(root),
    )
    return store.load_snapshot()


def test_mixed_page_selected_task_and_page_states(tmp_path):
    root = tmp_path / "ds"
    os.makedirs(root, exist_ok=True)
    image_path = osp.join(root, "m.jpg")
    label_path = osp.join(root, "m.json")
    with open(image_path, "wb") as handle:
        handle.write(b"img")
    # Two large distant targets pass the balanced projected-size and
    # gap gates and pack onto one shared page.
    _dump(
        label_path,
        [
            _rect(x=10, y=10, w=300, h=300),
            _rect(x=800, y=600, w=300, h=300),
        ],
    )
    sidecar = tmp_path / "mixed.xreview.sqlite3"
    request = vr.QueueBuildRequest(
        files=vr.descriptors_from_lists(str(root), [image_path], [label_path]),
        criteria=CRITERIA,
        packing_options=vr.VirtualPackingOptions(mode="balanced"),
        reference_viewport=(1200.0, 800.0),
        sidecar_path=str(sidecar),
    )
    draft = vr.scan_dataset(request)
    assert draft.publishable, draft.diagnostics
    vr.publish_new_queue(draft)
    store = vr.ReviewStore.open(str(sidecar))
    try:
        snapshot = store.load_snapshot()
        assert len(snapshot.pages) == 1
        page = snapshot.pages[0]
        assert len(page.task_ids) == 2
        first, second = snapshot.tasks_by_page[page.page_id]
        assert (
            vr.derive_page_state(snapshot.tasks_by_page[page.page_id])
            is vr.PageState.ACTIONABLE
        )
        _complete(store, first)
        snapshot = store.load_snapshot()
        members = snapshot.tasks_by_page[page.page_id]
        assert members[0].outcome is vr.TaskOutcome.COMPLETED
        assert members[1].outcome is vr.TaskOutcome.PENDING
        assert vr.derive_page_state(members) is vr.PageState.ACTIONABLE
        assert vr.page_matches_filter(members, vr.QueueFilter.ACTIONABLE)
        assert vr.page_matches_filter(members, vr.QueueFilter.COMPLETED)
    finally:
        store.close()


def test_page_wide_completion_applies_to_live_tasks_only(queue):
    store, root, _ = queue
    snapshot = store.load_snapshot()
    target = snapshot.tasks[0]
    report = vr.FileReconcileReport(
        file_id=target.file_id,
        task_bindings={
            target.task_id: vr.TaskBinding(vr.BindingState.AMBIGUOUS)
        },
    )
    store.record_reconciliation(
        snapshot.revision, [report], store.logical_revision
    )
    snapshot = store.load_snapshot()
    live = [task for task in snapshot.tasks if task.trusted_binding]
    assert len(live) == len(snapshot.tasks) - 1
    changes = [
        vr.OutcomeChange(
            task.task_id,
            vr.TaskOutcome.COMPLETED,
            reviewed_signature=task.current_signature,
        )
        for task in live
    ]
    store.apply_outcomes(snapshot.revision, changes, store.logical_revision)
    final = store.load_snapshot()
    ambiguous = final.task_by_id[target.task_id]
    assert ambiguous.outcome is vr.TaskOutcome.PENDING
    assert all(
        final.task_by_id[task.task_id].outcome is vr.TaskOutcome.COMPLETED
        for task in live
    )
    assert ambiguous.trusted_binding is False


def test_stale_completion_rejoins_actionable_view(queue):
    store, root, _ = queue
    snapshot = store.load_snapshot()
    task = snapshot.task_by_id[snapshot.pages[0].task_ids[0]]
    _complete(store, task)
    # Rename the completed target's label: geometry stays identical so
    # reconciliation still binds it, but its content signature changes.
    label_path = osp.join(root, "a.json")
    _dump(label_path, [_rect(gid=1, label="worker")])
    snapshot = _reconcile(store, root)
    record = snapshot.task_by_id[task.task_id]
    assert record.outcome is vr.TaskOutcome.COMPLETED
    assert record.freshness is vr.TaskFreshness.STALE
    assert record.actionable is True
    members = snapshot.tasks_by_page[snapshot.pages[0].page_id]
    assert vr.page_matches_filter(members, vr.QueueFilter.ACTIONABLE)
    assert vr.page_matches_filter(members, vr.QueueFilter.STALE)


def test_reset_returns_pending_with_event(queue):
    store, _, _ = queue
    snapshot = store.load_snapshot()
    task = snapshot.tasks[0]
    _complete(store, task)
    store.apply_outcomes(
        snapshot.revision,
        [vr.OutcomeChange(task.task_id, vr.TaskOutcome.PENDING)],
        store.logical_revision,
    )
    final = store.load_snapshot()
    record = final.task_by_id[task.task_id]
    assert record.outcome is vr.TaskOutcome.PENDING
    assert record.freshness is vr.TaskFreshness.FRESH
    conn = store.raw_connection()
    events = conn.execute(
        "SELECT outcome FROM outcome_event WHERE task_id = ? "
        "ORDER BY event_id",
        (task.task_id,),
    ).fetchall()
    assert [event[0] for event in events] == [
        "completed",
        "pending",
    ]


def test_filter_boundaries_never_wrap(queue):
    store, _, _ = queue
    snapshot = store.load_snapshot()
    first, last = snapshot.pages[0], snapshot.pages[-1]
    forward = vr.find_next_eligible(
        snapshot, last.page_id, vr.QueueFilter.ACTIONABLE, 1
    )
    assert forward.boundary and forward.message == "last_page"
    backward = vr.find_next_eligible(
        snapshot, first.page_id, vr.QueueFilter.ACTIONABLE, -1
    )
    assert backward.boundary and backward.message == "first_page"
    with pytest.raises(ValueError):
        (
            vr.find_next_eligible(snapshot, first.page_id, None, 0)
            if (False)
            else vr.find_next_eligible(
                snapshot, first.page_id, vr.QueueFilter.ALL, 0
            )
        )


def test_resume_prefers_saved_page_then_nearest_next(queue):
    store, _, _ = queue
    snapshot = store.load_snapshot()
    pages = snapshot.pages
    store.commit_cursor(
        snapshot.revision,
        pages[1].page_id,
        vr.QueueFilter.ACTIONABLE,
        store.logical_revision,
    )
    # Freshly complete every task of the saved page: it leaves the
    # default view, so resume must pick the nearest next page.
    for task_id in pages[1].task_ids:
        task = snapshot.task_by_id[task_id]
        _complete(store, task)
        snapshot = store.load_snapshot()
    plan = vr.find_resume_target(
        snapshot, pages[1].page_id, vr.QueueFilter.ACTIONABLE
    )
    assert plan.target.page_id == pages[2].page_id
    assert plan.message == "saved_not_eligible"


def test_resume_skips_unavailable_saved_page(queue):
    store, root, _ = queue
    snapshot = store.load_snapshot()
    pages = snapshot.pages
    store.commit_cursor(
        snapshot.revision,
        pages[0].page_id,
        vr.QueueFilter.ACTIONABLE,
        store.logical_revision,
    )
    os.remove(osp.join(root, "a.json"))
    snapshot = _reconcile(store, root)
    plan = vr.find_resume_target(
        snapshot, pages[0].page_id, vr.QueueFilter.ACTIONABLE
    )
    assert plan.target.page_id == pages[1].page_id


def test_reconcile_keeps_frozen_membership_and_order(queue):
    store, root, _ = queue
    snapshot = store.load_snapshot()
    second_task = snapshot.task_by_id[snapshot.pages[1].task_ids[0]]
    third_task = snapshot.task_by_id[snapshot.pages[2].task_ids[0]]
    _complete(store, second_task)
    _dump(
        osp.join(root, "c.json"),
        [_rect(gid=3, label="worker", x=100)],
    )
    after = _reconcile(store, root)
    assert [p.page_id for p in after.pages] == [
        p.page_id for p in snapshot.pages
    ]
    assert [f.file_id for f in after.files] == [
        f.file_id for f in snapshot.files
    ]
    assert sorted(t.task_id for t in after.tasks) == sorted(
        t.task_id for t in snapshot.tasks
    )
    assert (
        after.task_by_id[second_task.task_id].outcome
        is vr.TaskOutcome.COMPLETED
    )
    changed = after.task_by_id[third_task.task_id]
    assert changed.binding_state is vr.BindingState.CHANGED_RESOLVED


def test_rebuild_carries_exact_matches_and_archives_old(queue):
    store, root, request = queue
    snapshot = store.load_snapshot()
    completed = snapshot.task_by_id[snapshot.pages[0].task_ids[0]]
    _complete(store, completed)
    # Add a brand new target to file b before rebuilding.
    _dump(
        osp.join(root, "b.json"),
        [_rect(gid=2), _rect(gid=99, x=900, y=700)],
    )
    draft = vr.scan_dataset(request)
    assert draft.publishable, draft.diagnostics
    result = vr.publish_rebuild(draft, store, store.logical_revision)
    assert result.detail["revision"] == 2
    fresh = store.load_snapshot()
    assert fresh.revision == 2
    assert len(fresh.tasks) == 4
    carried = [
        task
        for task in fresh.tasks
        if task.outcome is vr.TaskOutcome.COMPLETED
    ]
    assert len(carried) == 1
    assert carried[0].carried_from == completed.task_id
    assert carried[0].freshness is vr.TaskFreshness.FRESH
    new_task = [
        task
        for task in fresh.tasks
        if task.carried_from is None and task.locator.get("gid") == "99"
    ]
    assert new_task and new_task[0].outcome is vr.TaskOutcome.PENDING
    # Old revision rows stay queryable as history.
    legacy = store.load_snapshot(revision=1)
    assert (
        legacy.task_by_id[completed.task_id].outcome
        is vr.TaskOutcome.COMPLETED
    )
    assert store.load_revision_meta(1).state == "archived"
    # The rebuild reset the saved cursor page for re-validation.
    cursor = store.load_cursor()
    assert cursor is None or cursor.page_id is None


def test_summary_counts_and_filters(queue):
    store, _, _ = queue
    snapshot = store.load_snapshot()
    _complete(store, snapshot.tasks[0])
    snapshot = store.load_snapshot()
    summary = vr.summarize_snapshot(snapshot)
    assert summary.total_tasks == 3
    assert summary.tasks_by_outcome["completed"] == 1
    assert summary.actionable_tasks == 2
    assert summary.completion_ratio == pytest.approx(1 / 3)
    eligible_actionable = vr.eligible_pages(
        snapshot, vr.QueueFilter.ACTIONABLE
    )
    assert len(eligible_actionable) == 2
    assert len(vr.eligible_pages(snapshot, vr.QueueFilter.COMPLETED)) == 1
    assert len(vr.eligible_pages(snapshot, vr.QueueFilter.ALL)) == 3
