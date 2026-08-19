"""Pure-Python tests for the review sidecar store.

Covers schema creation, snapshot round trips, relational constraints,
transactional rollback, schema-version policy, migration with backup,
backup copies, writer-lease conflicts, stale takeover, and optimistic
logical-revision blocking.  The file is self-contained and runnable
alone.
"""

import json
import os
import os.path as osp
import sqlite3

import pytest

from anylabeling.views.labeling import virtual_review as vr


def _write_annotation(root, name, shapes, width=1000, height=800):
    """Write one annotation pair and return both absolute paths."""

    image_path = osp.join(root, f"{name}.png")
    label_path = osp.join(root, f"{name}.json")
    with open(image_path, "wb") as handle:
        handle.write(b"\x89PNG-fake")
    with open(label_path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "imageWidth": width,
                "imageHeight": height,
                "shapes": shapes,
            },
            handle,
        )
    return image_path, label_path


def _person(name="person", group_id=None, x=10, y=10):
    """Return one rectangle shape payload."""

    return {
        "label": name,
        "shape_type": "rectangle",
        "group_id": group_id,
        "points": [[x, y], [x + 50, y + 60]],
    }


@pytest.fixture()
def queue_sidecar(tmp_path):
    """Publish a tiny two-file queue and return the sidecar path."""

    root = tmp_path / "ds"
    root.mkdir()
    first = _write_annotation(
        root,
        "a",
        [_person(group_id=1), _person(x=500, y=400)],
    )
    second = _write_annotation(root, "b", [_person(group_id=2)])
    sidecar = tmp_path / "q.xreview.sqlite3"
    request = vr.QueueBuildRequest(
        files=vr.descriptors_from_lists(
            str(root),
            [first[0], second[0]],
            [first[1], second[1]],
        ),
        criteria=vr.VirtualTaskCriteria(
            labels=frozenset({"person"}),
            shape_types=frozenset({"rectangle"}),
        ),
        packing_options=vr.VirtualPackingOptions(mode="single"),
        reference_viewport=(1200.0, 800.0),
        sidecar_path=str(sidecar),
    )
    draft = vr.scan_dataset(request)
    assert draft.publishable, draft.diagnostics
    vr.publish_new_queue(draft)
    return str(sidecar), str(root), (first, second), request


def test_create_initializes_schema_and_meta(tmp_path):
    sidecar = str(tmp_path / "fresh.xreview.sqlite3")
    store = vr.ReviewStore.create(sidecar, dataset_root_hint="X:/ds")
    try:
        names = {
            row[0]
            for row in store.raw_connection().execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert vr.expected_tables() <= names
        assert store.meta("schema_version") == str(vr.SCHEMA_VERSION)
        assert store.meta("dataset_root_hint") == "X:/ds"
        assert store.logical_revision == 1
        assert store.active_revision == 0
    finally:
        store.close()


def test_snapshot_round_trip_survives_reopen(queue_sidecar):
    sidecar, _, _, _ = queue_sidecar
    store = vr.ReviewStore.open(sidecar)
    try:
        snapshot = store.load_snapshot()
    finally:
        store.close()
    reopened = vr.ReviewStore.open(sidecar)
    try:
        again = reopened.load_snapshot()
    finally:
        reopened.close()
    assert again.revision == snapshot.revision
    assert [f.label_rel_path for f in again.files] == [
        f.label_rel_path for f in snapshot.files
    ]
    assert [p.task_ids for p in again.pages] == [
        p.task_ids for p in snapshot.pages
    ]
    assert [t.locator for t in again.tasks] == [
        t.locator for t in snapshot.tasks
    ]


def test_foreign_keys_reject_unknown_file_task(queue_sidecar):
    sidecar, _, _, _ = queue_sidecar
    conn = sqlite3.connect(sidecar)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO atomic_task (revision, task_id, file_id, "
                "source_order, locator_json, created_at, updated_at) "
                "VALUES (1, 't-x', 'no-such-file', 0, '{}', "
                "'2024-01-01T00:00:00+00:00', "
                "'2024-01-01T00:00:00+00:00')"
            )
    finally:
        conn.close()


def test_unique_constraints_reject_duplicates(queue_sidecar):
    sidecar, _, _, _ = queue_sidecar
    store = vr.ReviewStore.open(sidecar)
    try:
        snapshot = store.load_snapshot()
        page = snapshot.pages[0]
        task = snapshot.tasks[0]
        conn = store.raw_connection()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO review_page (revision, page_id, file_id, "
                "page_order) VALUES (1, 'p-dup', ?, 0)",
                (page.file_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO page_task (revision, page_id, task_id, slot)"
                " VALUES (1, ?, ?, 1)",
                (page.page_id, task.task_id),
            )
    finally:
        store.close()


def test_outcome_batch_rolls_back_completely(queue_sidecar):
    sidecar, _, _, _ = queue_sidecar
    store = vr.ReviewStore.open(sidecar)
    try:
        snapshot = store.load_snapshot()
        logical = store.logical_revision
        first, second = snapshot.tasks[0], snapshot.tasks[1]
        changes = [
            vr.OutcomeChange(
                first.task_id,
                vr.TaskOutcome.COMPLETED,
                reviewed_signature=first.current_signature,
            ),
            vr.OutcomeChange("no-such-task", vr.TaskOutcome.SKIPPED),
        ]
        with pytest.raises(vr.NotFound):
            store.apply_outcomes(snapshot.revision, changes, logical)
        fresh = store.load_snapshot()
        assert fresh.task_by_id[first.task_id].outcome is (
            vr.TaskOutcome.PENDING
        )
        assert fresh.task_by_id[second.task_id].outcome is (
            vr.TaskOutcome.PENDING
        )
        assert store.logical_revision == logical
    finally:
        store.close()


def test_untrusted_binding_blocks_outcome(queue_sidecar):
    sidecar, _, _, _ = queue_sidecar
    store = vr.ReviewStore.open(sidecar)
    try:
        snapshot = store.load_snapshot()
        task = snapshot.tasks[0]
        logical = store.logical_revision
        report = vr.FileReconcileReport(
            file_id=task.file_id,
            availability="available",
            task_bindings={
                task.task_id: vr.TaskBinding(
                    vr.BindingState.AMBIGUOUS, reason="test"
                )
            },
        )
        store.record_reconciliation(snapshot.revision, [report], logical)
        with pytest.raises(vr.InvalidOutcomeTarget):
            store.apply_outcomes(
                snapshot.revision,
                [vr.OutcomeChange(task.task_id, vr.TaskOutcome.COMPLETED)],
                store.logical_revision,
            )
    finally:
        store.close()


def test_newer_schema_version_rejected_editable_only(tmp_path):
    sidecar = str(tmp_path / "newer.xreview.sqlite3")
    store = vr.ReviewStore.create(sidecar)
    store.close()
    conn = sqlite3.connect(sidecar)
    conn.execute(
        "UPDATE queue_meta SET value = '99' " "WHERE key = 'schema_version'"
    )
    conn.commit()
    conn.close()
    before = open(sidecar, "rb").read()
    with pytest.raises(vr.SchemaVersionTooNew):
        vr.ReviewStore.open(sidecar, editable=True)
    assert open(sidecar, "rb").read() == before
    diagnostic = vr.ReviewStore.open(sidecar, editable=False)
    diagnostic.close()
    assert open(sidecar, "rb").read() == before


def _register_synthetic_migrations(fail=False):
    """Register a v0 -> v1 migration, returning a cleanup callable."""

    def upgrade(conn):
        if fail:
            raise RuntimeError("synthetic migration failure")
        from anylabeling.views.labeling.virtual_review.schema import (
            initialize_schema,
        )

        initialize_schema(conn, "test")

    migration = vr.Migration(0, 1, "synthetic-v1", upgrade)
    vr.MIGRATIONS.register(migration)
    return lambda: vr.MIGRATIONS._migrations.remove(migration)


def _craft_v0_sidecar(path):
    """Write a database that only knows schema_version 0."""

    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE queue_meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "INSERT INTO queue_meta (key, value) VALUES " "('schema_version', '0')"
    )
    conn.commit()
    conn.close()


def test_migration_backs_up_and_records_history(tmp_path):
    sidecar = str(tmp_path / "old.xreview.sqlite3")
    _craft_v0_sidecar(sidecar)
    cleanup = _register_synthetic_migrations()
    try:
        store = vr.ReviewStore.open(sidecar)
        try:
            assert store.meta("schema_version") == str(vr.SCHEMA_VERSION)
            history = (
                store.raw_connection()
                .execute(
                    "SELECT from_version, to_version, backup_path "
                    "FROM migration_history"
                )
                .fetchall()
            )
            assert history and history[0][0] == 0
            assert osp.exists(str(history[0][2]))
        finally:
            store.close()
        backups = list(tmp_path.glob("old.xreview.sqlite3.pre-v1.*"))
        assert backups, "pre-migration backup was not written"
    finally:
        cleanup()


def test_failed_migration_rolls_back_version(tmp_path):
    sidecar = str(tmp_path / "old-fail.xreview.sqlite3")
    _craft_v0_sidecar(sidecar)
    cleanup = _register_synthetic_migrations(fail=True)
    try:
        with pytest.raises((vr.MigrationFailure, RuntimeError)):
            vr.ReviewStore.open(sidecar)
        conn = sqlite3.connect(sidecar)
        try:
            version = conn.execute(
                "SELECT value FROM queue_meta " "WHERE key = 'schema_version'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert version == "0"
    finally:
        cleanup()


def test_backup_to_produces_valid_copy(queue_sidecar):
    sidecar, _, _, _ = queue_sidecar
    store = vr.ReviewStore.open(sidecar)
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
        backup_path = str(sidecar + ".backup.xreview.sqlite3")
        store.backup_to(backup_path)
    finally:
        store.close()
    backup = vr.ReviewStore.open(backup_path, editable=False)
    try:
        copy = backup.load_snapshot()
        assert (
            copy.task_by_id[task.task_id].outcome is vr.TaskOutcome.COMPLETED
        )
    finally:
        backup.close()


def test_second_live_writer_gets_read_only_fallback(queue_sidecar):
    sidecar, _, _, _ = queue_sidecar
    first = vr.ReviewStore.open(sidecar)
    try:
        with pytest.raises(vr.LeaseHeld) as info:
            vr.ReviewStore.open(sidecar)
        assert info.value.stale is False
        reader = vr.ReviewStore.open(sidecar, editable=False)
        try:
            with pytest.raises(vr.ReadOnlyStore):
                reader.apply_outcomes(
                    1,
                    [vr.OutcomeChange("any", vr.TaskOutcome.SKIPPED)],
                    1,
                )
        finally:
            reader.close()
    finally:
        first.close()
    second = vr.ReviewStore.open(sidecar)
    try:
        assert second.lease_info()["instance_id"] == second.instance_id
    finally:
        second.close()


def test_stale_lease_requires_explicit_takeover(tmp_path):
    sidecar = str(tmp_path / "stale.xreview.sqlite3")
    store = vr.ReviewStore.create(sidecar)
    store.close()
    conn = sqlite3.connect(sidecar)
    old = "2000-01-01T00:00:00+00:00"
    conn.execute(
        "INSERT INTO writer_lease (id, instance_id, pid, host, "
        "acquired_at, heartbeat_at) VALUES (1, 'ghost', 999999999, "
        "'not-a-host', ?, ?)",
        (old, old),
    )
    conn.commit()
    conn.close()
    with pytest.raises(vr.LeaseHeld) as info:
        vr.ReviewStore.open(sidecar)
    assert info.value.stale is True
    owner = vr.ReviewStore.open(sidecar, takeover=True)
    try:
        holder = owner.lease_info()
        assert holder["instance_id"] == owner.instance_id
        events = (
            owner.raw_connection()
            .execute("SELECT kind FROM reconciliation_event")
            .fetchall()
        )
        assert ("lease_takeover",) in events
    finally:
        owner.close()


def test_unexpected_logical_revision_blocks_write(queue_sidecar):
    sidecar, _, _, _ = queue_sidecar
    store = vr.ReviewStore.open(sidecar)
    try:
        snapshot = store.load_snapshot()
        stale_view = store.logical_revision
        store.apply_outcomes(
            snapshot.revision,
            [
                vr.OutcomeChange(
                    snapshot.tasks[0].task_id,
                    vr.TaskOutcome.NEEDS_REWORK,
                )
            ],
            stale_view,
        )
        with pytest.raises(vr.RevisionConflict):
            store.apply_outcomes(
                snapshot.revision,
                [
                    vr.OutcomeChange(
                        snapshot.tasks[1].task_id,
                        vr.TaskOutcome.SKIPPED,
                    )
                ],
                stale_view,
            )
        final = store.load_snapshot()
        assert (
            final.task_by_id[snapshot.tasks[1].task_id].outcome
            is vr.TaskOutcome.PENDING
        )
    finally:
        store.close()


def test_commit_cursor_requires_existing_page(queue_sidecar):
    sidecar, _, _, _ = queue_sidecar
    store = vr.ReviewStore.open(sidecar)
    try:
        with pytest.raises(vr.NotFound):
            store.commit_cursor(
                1,
                "no-such-page",
                vr.QueueFilter.ACTIONABLE,
                store.logical_revision,
            )
    finally:
        store.close()


def test_missing_file_availability_preserves_progress(queue_sidecar):
    sidecar, _, _, _ = queue_sidecar
    store = vr.ReviewStore.open(sidecar)
    try:
        snapshot = store.load_snapshot()
        task = snapshot.task_by_id[snapshot.pages[-1].task_ids[0]]
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
        report = vr.FileReconcileReport(
            file_id=task.file_id,
            availability="missing",
            task_bindings={
                task.task_id: vr.TaskBinding(
                    vr.BindingState.MISSING, reason="file gone"
                )
            },
        )
        store.record_reconciliation(
            snapshot.revision, [report], store.logical_revision
        )
        final = store.load_snapshot()
        record = final.task_by_id[task.task_id]
        assert record.outcome is vr.TaskOutcome.COMPLETED
        assert record.binding_state is vr.BindingState.MISSING
        assert record.freshness is vr.TaskFreshness.UNRESOLVED
        assert (
            final.file_by_id[task.file_id].availability
            is vr.FileAvailability.MISSING
        )
    finally:
        store.close()


def test_manual_binding_records_and_restores_mutability(
    queue_sidecar,
):
    sidecar, _, _, _ = queue_sidecar
    store = vr.ReviewStore.open(sidecar)
    try:
        snapshot = store.load_snapshot()
        task = snapshot.tasks[0]
        report = vr.FileReconcileReport(
            file_id=task.file_id,
            task_bindings={
                task.task_id: vr.TaskBinding(vr.BindingState.AMBIGUOUS)
            },
        )
        store.record_reconciliation(
            snapshot.revision, [report], store.logical_revision
        )
        with pytest.raises(vr.InvalidOutcomeTarget):
            store.apply_outcomes(
                snapshot.revision,
                [vr.OutcomeChange(task.task_id, vr.TaskOutcome.SKIPPED)],
                store.logical_revision,
            )
        store.record_manual_binding(
            snapshot.revision,
            task.task_id,
            task.current_signature,
            store.logical_revision,
        )
        result = store.apply_outcomes(
            snapshot.revision,
            [vr.OutcomeChange(task.task_id, vr.TaskOutcome.SKIPPED)],
            store.logical_revision,
        )
        assert result.logical_revision > 1
    finally:
        store.close()


def test_invalid_sidecar_files_fail_closed(tmp_path):
    missing = str(tmp_path / "nope.xreview.sqlite3")
    with pytest.raises(vr.InvalidSidecar):
        vr.ReviewStore.open(missing)
    foreign = str(tmp_path / "foreign.xreview.sqlite3")
    conn = sqlite3.connect(foreign)
    conn.execute("CREATE TABLE other (x INTEGER)")
    conn.commit()
    conn.close()
    with pytest.raises(vr.InvalidSidecar):
        vr.ReviewStore.open(foreign)
