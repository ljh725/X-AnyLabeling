import json

import pytest

from anylabeling.services.inspection.models import (
    Decision,
    FeedbackRecord,
    FileSnapshot,
    Manifest,
    RunReport,
    RunScope,
    RunState,
    ReviewSession,
)
from anylabeling.services.inspection.storage import (
    FeedbackStore,
    InspectionStorage,
    ProjectBindingStore,
    ReportStore,
    RevisionConflict,
    SessionStore,
    StorageError,
    atomic_write_json,
    storage_root,
)


def _report(run_id="run-1"):
    return RunReport(
        run_id=run_id,
        state=RunState.COMPLETED,
        scope=RunScope.DATASET,
        dataset_root="D:/data",
        output_root="D:/labels",
        manifest_fingerprint="fingerprint",
        profile_snapshot={"profile": {"profile_id": "generic"}},
        coverage=(),
        issues=(),
        requested_files=1,
        completed_files=1,
    )


def test_report_store_round_trip_and_index(tmp_path):
    store = ReportStore(str(tmp_path))
    path = store.save(_report())
    assert path
    loaded = store.load("run-1")
    assert loaded.run_id == "run-1"
    assert loaded.state is RunState.COMPLETED
    entries = store.list_reports()
    assert entries[0]["run_id"] == "run-1"
    assert store.read_issue_page("run-1") == ()


def test_report_manifest_sidecar_round_trip(tmp_path):
    store = ReportStore(str(tmp_path))
    manifest = Manifest(
        dataset_root="D:/data",
        output_root="D:/labels",
        files=(
            FileSnapshot(
                relative_path="a.jpg",
                image_path="D:/data/a.jpg",
                annotation_path="D:/labels/a.json",
                annotation_digest="digest",
            ),
        ),
    )
    store.save(_report(), manifest)
    loaded = store.load_manifest("run-1")
    assert loaded.file_count == 1
    assert loaded.files[0].annotation_digest == "digest"


def test_report_store_rejects_unknown_and_bad_schema(tmp_path):
    store = ReportStore(str(tmp_path))
    with pytest.raises(Exception):
        store.load("missing")
    atomic_write_json(
        tmp_path / "reports" / "bad.json",
        {"schema_version": "future", "run_id": "bad"},
    )
    with pytest.raises(StorageError):
        store.load("bad")


def test_feedback_revision_conflict_preserves_both(tmp_path):
    store = FeedbackStore(str(tmp_path))
    record = FeedbackRecord(
        family_key="f1",
        issue_id="i1",
        decision=Decision.CONFIRMED_ERROR,
    )
    revision = store.upsert(record, 0)
    assert revision == 1
    assert store.load().records["f1"].decision is Decision.CONFIRMED_ERROR
    with pytest.raises(RevisionConflict) as error:
        store.upsert(record, 0)
    assert error.value.conflict_path
    assert (tmp_path / error.value.conflict_path.split("\\")[-1]).exists()


def test_session_revision_is_checked(tmp_path):
    store = SessionStore(str(tmp_path))
    session = ReviewSession(
        report_id="run-1",
        dataset_root="D:/data",
        output_root="D:/labels",
    )
    saved = store.save(session, 0)
    assert saved.revision == 1
    with pytest.raises(RevisionConflict):
        store.save(session, 0)


def test_project_binding_is_isolated_by_output_root(tmp_path):
    store = ProjectBindingStore(str(tmp_path))
    store.save("D:/data", "D:/out1", "generic", 1, "fp1")
    assert store.load("D:/data", "D:/out1")["profile_id"] == "generic"
    assert store.load("D:/data", "D:/out2") is None


def test_storage_facade_and_preferred_root(tmp_path):
    preferred = tmp_path / "preferred"
    storage = InspectionStorage.open(
        "D:/data", "D:/out", str(preferred)
    )
    assert storage.root == str(preferred)
    assert storage.reports.root == str(preferred)


def test_storage_root_uses_output_directory(tmp_path):
    root = storage_root("D:/data", str(tmp_path))
    assert root.endswith("inspection")
    assert (tmp_path / ".xanylabeling" / "inspection").exists()
