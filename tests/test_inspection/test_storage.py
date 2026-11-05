import json
import os
import pathlib

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
    dataset_identity,
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
    with pytest.raises(RevisionConflict) as error:
        store.save(session, 0)
    assert error.value.conflict_path
    assert (tmp_path / error.value.conflict_path.split("\\")[-1]).exists()
    conflict = json.loads(
        (tmp_path / error.value.conflict_path.split("\\")[-1]).read_text(
            encoding="utf-8"
        )
    )
    assert conflict["current"]["report_id"] == "run-1"
    assert conflict["attempted"]["report_id"] == "run-1"


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
    identity = dataset_identity("D:/data")
    assert storage.root == str(preferred / identity)
    assert storage.reports.root == str(preferred / identity)
    assert storage.profiles_dir == str(preferred / "profiles")


def test_storage_root_uses_output_directory(tmp_path):
    root = storage_root("D:/data", str(tmp_path))
    assert root.endswith(dataset_identity("D:/data"))
    assert (tmp_path / ".xanylabeling" / "inspection").exists()


def _issue(family_key, index):
    return InspectionIssue(
        issue_id=f"issue-{index}",
        family_key=family_key,
        title="t",
        message="m",
        severity=IssueSeverity.WARNING,
        location=IssueLocation(relative_path="a.jpg", object_ids=("id1",)),
        evidence=(),
    )


def test_report_store_batches_issues_and_round_trips(tmp_path):
    store = ReportStore(str(tmp_path), batch_size=2)
    report = RunReport(
        run_id="batched",
        state=RunState.COMPLETED,
        scope=RunScope.DATASET,
        dataset_root="D:/data",
        output_root="",
        manifest_fingerprint="f",
        profile_snapshot={"profile": {"profile_id": "generic"}},
        coverage=(),
        issues=tuple(_issue(f"f{i}", i) for i in range(5)),
        requested_files=1,
        completed_files=1,
    )
    path = store.save(report)
    loaded = store.load("batched")
    assert [issue.family_key for issue in loaded.issues] == [
        f"f{i}" for i in range(5)
    ]
    raw = pathlib.Path(path).read_text(encoding="utf-8")
    assert '"issues": [' in raw


def test_report_store_pagination_is_bounded(tmp_path):
    store = ReportStore(str(tmp_path), max_page_size=2)
    report = RunReport(
        run_id="paged",
        state=RunState.COMPLETED,
        scope=RunScope.DATASET,
        dataset_root="D:/data",
        output_root="",
        manifest_fingerprint="f",
        profile_snapshot={"profile": {"profile_id": "generic"}},
        coverage=(),
        issues=tuple(_issue(f"f{i}", i) for i in range(5)),
    )
    store.save(report)
    page = store.read_issue_page("paged", offset=1, limit=2)
    assert [item["family_key"] for item in page] == ["f1", "f2"]
    with pytest.raises(StorageError):
        store.read_issue_page("paged", offset=0, limit=3)
    with pytest.raises(StorageError):
        store.read_issue_page("paged", offset=0, limit=-1)


def test_report_store_cache_is_bounded(tmp_path):
    store = ReportStore(str(tmp_path), cache_size=2)
    for index in range(4):
        report = _report(run_id=f"run-{index}")
        store.save(report)
        store.load(f"run-{index}")
    assert len(store._cache) <= 2
    # Evicted reports are still readable from disk.
    assert store.load("run-0").run_id == "run-0"


def test_report_store_alternative_location_and_write_failure(
    tmp_path, monkeypatch
):
    store = ReportStore(str(tmp_path))
    report = _report(run_id="exported")
    target = tmp_path / "elsewhere" / "report.json"
    path = store.save_to(str(target), report)
    assert pathlib.Path(path).is_file()
    assert store.load_from(path).run_id == "exported"

    monkeypatch.setattr(
        storage_module,
        "os",
        _ExplodingOs(storage_module.os),
    )
    with pytest.raises(OSError):
        store.save(_report(run_id="failing"))
    # Nothing half-written is left behind and the index is untouched.
    assert not (tmp_path / "reports" / "failing.json").exists()
    assert all(
        entry["run_id"] != "failing" for entry in store.list_reports()
    )


def test_report_store_rejects_report_over_resource_limit(tmp_path):
    store = ReportStore(str(tmp_path), max_report_issues=2)
    report = RunReport(
        run_id="too-large",
        state=RunState.COMPLETED,
        scope=RunScope.DATASET,
        dataset_root="D:/data",
        output_root="",
        manifest_fingerprint="f",
        profile_snapshot={"profile": {"profile_id": "generic"}},
        coverage=(),
        issues=tuple(_issue(f"f{i}", i) for i in range(3)),
    )
    with pytest.raises(StorageError):
        store.save(report)
    assert not store.list_reports()


class _ExplodingOs:
    """Wrapper that fails on file replacement, simulating a full disk."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def replace(self, source, target):
        raise OSError("disk full (simulated)")


from anylabeling.services.inspection import storage as storage_module  # noqa: E402
from anylabeling.services.inspection.models import (  # noqa: E402
    InspectionIssue,
    IssueLocation,
    IssueSeverity,
)


def test_same_output_directory_isolates_datasets(tmp_path):
    shared_output = tmp_path / "labels"
    storage_a = InspectionStorage.open("D:/dataset-a", str(shared_output))
    storage_b = InspectionStorage.open("D:/dataset-b", str(shared_output))
    assert storage_a.root != storage_b.root
    assert storage_a.dataset_key != storage_b.dataset_key


def test_feedback_never_reuses_another_dataset_record(tmp_path):
    store = FeedbackStore(
        str(tmp_path), dataset_key="key-a", dataset_root="D:/a"
    )
    record = FeedbackRecord(
        family_key="f1",
        issue_id="i1",
        decision=Decision.FALSE_POSITIVE,
        dataset_key="key-a",
    )
    store.upsert(record, 0)
    other = FeedbackStore(
        str(tmp_path), dataset_key="key-b", dataset_root="D:/b"
    )
    snapshot = other.load()
    assert snapshot.records == {}
    assert snapshot.foreign_records == 1


def test_legacy_shared_root_without_owner_is_not_activated(tmp_path):
    shared_output = tmp_path / "labels"
    legacy_root = shared_output / ".xanylabeling" / "inspection"
    legacy_root.mkdir(parents=True)
    (legacy_root / "feedback.json").write_text(
        json.dumps(
            {
                "schema_version": "inspection-feedback.v1",
                "revision": 3,
                "records": {
                    "f1": {
                        "family_key": "f1",
                        "issue_id": "i1",
                        "decision": "false_positive",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    storage = InspectionStorage.open("D:/dataset-a", str(shared_output))
    assert storage.root != str(legacy_root)
    assert storage.migration_notes
    # A shared legacy record cannot prove which dataset it belongs to, so it
    # is preserved as a side file instead of being activated.
    assert storage.feedback.load().records == {}
    assert (pathlib.Path(storage.root) / "feedback.legacy-unverified.json").exists()
    assert (legacy_root / "feedback.json").exists()


def test_legacy_shared_root_with_matching_owner_is_migrated(tmp_path):
    shared_output = tmp_path / "labels"
    legacy_root = shared_output / ".xanylabeling" / "inspection"
    legacy_root.mkdir(parents=True)
    (legacy_root / "session.json").write_text(
        json.dumps(
            {
                "schema_version": "inspection-session.v1",
                "report_id": "run-1",
                "dataset_root": os.path.abspath("D:/dataset-a"),
                "output_root": os.path.abspath(str(shared_output)),
                "filters": {},
                "cursor": {},
                "revision": 1,
            }
        ),
        encoding="utf-8",
    )
    (legacy_root / "feedback.json").write_text(
        json.dumps(
            {
                "schema_version": "inspection-feedback.v1",
                "revision": 3,
                "records": {
                    "f1": {
                        "family_key": "f1",
                        "issue_id": "i1",
                        "decision": "false_positive",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    storage = InspectionStorage.open("D:/dataset-a", str(shared_output))
    assert storage.feedback.load().records["f1"].decision is (
        Decision.FALSE_POSITIVE
    )
    assert storage.sessions.load() is not None
    assert storage.migration_notes
