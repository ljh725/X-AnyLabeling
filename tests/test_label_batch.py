"""Pure safe-label-batch planning and transactional migration tests."""

import json

import anylabeling.views.labeling.widgets.label_batch as label_batch_module

from anylabeling.views.labeling.widgets.appearance.config import (
    save_project_palette,
)
from anylabeling.views.labeling.widgets.label_batch import (
    BatchMigrationEngine,
    FilesystemCandidateProvider,
    LabelMetadataDraft,
    build_label_change_plan,
    find_merge_conflicts,
    transform_annotation_data,
)


def _draft(
    label, *, color=(0, 114, 178), value=None, delete=False, visible=True
):
    """Build a compact test draft."""
    return LabelMetadataDraft(
        label=label,
        color=color,
        value=value,
        delete=delete,
        visible=visible,
    )


def test_draft_plan_separates_visual_and_dataset_changes_without_mutation():
    """A color-only edit never becomes a dataset migration."""
    original = {"person": _draft("person")}
    edited = {"person": _draft("person", color=(1, 2, 3))}
    plan = build_label_change_plan(original, edited)
    assert plan.has_visual_changes
    assert not plan.has_dataset_changes
    assert original["person"].color == (0, 114, 178)


def test_merge_conflicts_are_explicit():
    """Renaming to an existing label requires a second confirmation."""
    conflicts = find_merge_conflicts(
        {"head_old": "head"}, {"head_old", "head"}
    )
    assert [(item.source, item.target) for item in conflicts] == [
        ("head_old", "head")
    ]


def test_candidate_provider_uses_only_trustworthy_subset_and_falls_back():
    """An index result outside the requested scope is treated as stale."""
    paths = ["a.png", "b.png"]
    provider = FilesystemCandidateProvider(lambda _labels: ["a.png"])
    assert provider.candidates(frozenset({"old"}), paths) == ("a.png",)
    stale = FilesystemCandidateProvider(lambda _labels: ["outside.png"])
    assert stale.candidates(frozenset({"old"}), paths) == tuple(paths)


def test_transform_preserves_unknown_fields_and_skips_noop():
    """Only target label fields and shape removal are transformed."""
    data = {
        "version": "x",
        "custom": {"keep": True},
        "shapes": [
            {"label": "old", "points": [[1, 2]], "extension": "keep"},
            {"label": "other", "points": []},
        ],
    }
    transformed = transform_annotation_data(data, {"old": "new"}, ())
    assert transformed.changed
    assert transformed.matched_shapes == 1
    assert transformed.data["custom"] == {"keep": True}
    assert transformed.data["shapes"][0]["extension"] == "keep"
    noop = transform_annotation_data(data, {"missing": "new"}, ())
    assert not noop.changed


def test_transaction_stage_commit_and_restore(tmp_path):
    """Atomic commit leaves a manifest and restore returns original JSON."""
    source = tmp_path / "sample.json"
    source.write_text(
        json.dumps({"shapes": [{"label": "old", "points": [[1, 2]]}]}),
        encoding="utf-8",
    )
    plan = build_label_change_plan(
        {"old": _draft("old")},
        {"old": _draft("old", value="new")},
    )
    engine = BatchMigrationEngine(
        str(tmp_path / ".xanylabeling" / "transactions")
    )
    staged = engine.stage([str(source)], plan)
    assert staged.files[0].status == "staged"
    committed = engine.commit(staged, str(tmp_path))
    assert committed.counts["succeeded"] == 1
    assert (
        json.loads(source.read_text(encoding="utf-8"))["shapes"][0]["label"]
        == "new"
    )
    restored = engine.restore(committed.manifest_path)
    assert restored.counts["succeeded"] == 1
    assert (
        json.loads(source.read_text(encoding="utf-8"))["shapes"][0]["label"]
        == "old"
    )


def test_commit_records_fingerprint_and_restore_skips_only_changed_files(
    tmp_path,
):
    """Recovery isolates post-commit edits while restoring safe peers."""
    sources = [tmp_path / "first.json", tmp_path / "second.json"]
    for source in sources:
        source.write_text(
            json.dumps({"shapes": [{"label": "old"}]}), encoding="utf-8"
        )
    plan = build_label_change_plan(
        {"old": _draft("old")},
        {"old": _draft("old", value="new")},
    )
    engine = BatchMigrationEngine(str(tmp_path / "transactions"))
    committed = engine.commit(
        engine.stage([str(path) for path in sources], plan), str(tmp_path)
    )
    manifest = json.loads(
        open(committed.manifest_path, encoding="utf-8").read()
    )
    assert all(
        entry.get("committed_fingerprint") for entry in manifest["entries"]
    )

    sources[1].write_text(
        json.dumps({"shapes": [{"label": "manual-edit"}]}), encoding="utf-8"
    )
    restored = engine.restore(
        committed.manifest_path, require_committed_fingerprint=True
    )

    assert restored.counts["succeeded"] == 1
    assert restored.counts["conflict"] == 1
    assert (
        json.loads(sources[0].read_text(encoding="utf-8"))["shapes"][0][
            "label"
        ]
        == "old"
    )
    assert (
        json.loads(sources[1].read_text(encoding="utf-8"))["shapes"][0][
            "label"
        ]
        == "manual-edit"
    )


def test_result_shortcut_rejects_legacy_manifest_without_fingerprint(tmp_path):
    """The no-picker recovery path requires verifiable commit state."""
    source = tmp_path / "sample.json"
    source.write_text(
        json.dumps({"shapes": [{"label": "old"}]}), encoding="utf-8"
    )
    plan = build_label_change_plan(
        {"old": _draft("old")},
        {"old": _draft("old", value="new")},
    )
    engine = BatchMigrationEngine(str(tmp_path / "transactions"))
    committed = engine.commit(engine.stage([str(source)], plan), str(tmp_path))
    manifest_path = committed.manifest_path
    manifest = json.loads(open(manifest_path, encoding="utf-8").read())
    for entry in manifest["entries"]:
        entry.pop("committed_fingerprint", None)
    with open(manifest_path, "w", encoding="utf-8") as stream:
        json.dump(manifest, stream)

    denied = engine.restore(manifest_path, require_committed_fingerprint=True)

    assert denied.counts["conflict"] == 1
    assert (
        json.loads(source.read_text(encoding="utf-8"))["shapes"][0]["label"]
        == "new"
    )


def test_transaction_skips_noop_without_touching_file(tmp_path):
    """No matching labels never enter the write set."""
    source = tmp_path / "sample.json"
    source.write_text(
        json.dumps({"shapes": [{"label": "other"}]}), encoding="utf-8"
    )
    before = source.stat().st_mtime_ns
    plan = build_label_change_plan(
        {"old": _draft("old")},
        {"old": _draft("old", value="new")},
    )
    engine = BatchMigrationEngine(str(tmp_path / "transactions"))
    staged = engine.stage([str(source)], plan)
    assert staged.files[0].status == "skipped"
    assert source.stat().st_mtime_ns == before


def test_transaction_cancellation_happens_before_replacement(tmp_path):
    """Cancelling staging leaves the source untouched and records a manifest."""
    source = tmp_path / "sample.json"
    source.write_text(
        json.dumps({"shapes": [{"label": "old"}]}), encoding="utf-8"
    )
    plan = build_label_change_plan(
        {"old": _draft("old")},
        {"old": _draft("old", value="new")},
    )
    engine = BatchMigrationEngine(str(tmp_path / "transactions"))
    staged = engine.stage([str(source)], plan, cancel_check=lambda: True)
    assert staged.cancelled
    assert (
        json.loads(source.read_text(encoding="utf-8"))["shapes"][0]["label"]
        == "old"
    )


def test_transaction_detects_source_change_and_reports_partial_failure(
    tmp_path,
):
    """A concurrent source edit prevents that file from being replaced."""
    source = tmp_path / "sample.json"
    source.write_text(
        json.dumps({"shapes": [{"label": "old"}]}), encoding="utf-8"
    )
    plan = build_label_change_plan(
        {"old": _draft("old")},
        {"old": _draft("old", value="new")},
    )
    engine = BatchMigrationEngine(str(tmp_path / "transactions"))
    staged = engine.stage([str(source)], plan)
    source.write_text(
        json.dumps({"shapes": [{"label": "other"}]}), encoding="utf-8"
    )
    result = engine.commit(staged, str(tmp_path))
    assert result.counts["failed"] == 1
    assert (
        json.loads(source.read_text(encoding="utf-8"))["shapes"][0]["label"]
        == "other"
    )


def test_transaction_records_invalid_json_as_failure(tmp_path):
    """A malformed candidate is never copied into the replacement set."""
    source = tmp_path / "invalid.json"
    source.write_text("{not-json", encoding="utf-8")
    plan = build_label_change_plan(
        {"old": _draft("old")},
        {"old": _draft("old", value="new")},
    )
    engine = BatchMigrationEngine(str(tmp_path / "transactions"))
    staged = engine.stage([str(source)], plan)
    assert staged.counts["failed"] == 1
    assert source.read_text(encoding="utf-8") == "{not-json"


def test_transaction_reports_replacement_failure_without_losing_backup(
    tmp_path, monkeypatch
):
    """An atomic replacement error remains recoverable through the manifest."""
    source = tmp_path / "sample.json"
    source.write_text(
        json.dumps({"shapes": [{"label": "old"}]}), encoding="utf-8"
    )
    plan = build_label_change_plan(
        {"old": _draft("old")},
        {"old": _draft("old", value="new")},
    )
    engine = BatchMigrationEngine(str(tmp_path / "transactions"))
    staged = engine.stage([str(source)], plan)
    original_replace = label_batch_module.os.replace

    def fail_source_replace(source_path, target_path):
        if target_path == str(source):
            raise PermissionError("replacement denied")
        original_replace(source_path, target_path)

    monkeypatch.setattr(label_batch_module.os, "replace", fail_source_replace)
    result = engine.commit(staged, str(tmp_path))
    assert result.counts["failed"] == 1
    assert result.files[0].backup_path
    assert source.exists()


def test_preflight_counts_matching_shapes_and_files_without_writing(tmp_path):
    """Preflight reports per-batch counts and leaves files untouched."""
    source = tmp_path / "sample.json"
    payload = json.dumps(
        {
            "shapes": [
                {"label": "old", "points": [[1, 2]]},
                {"label": "old", "points": [[3, 4]]},
                {"label": "keep", "points": []},
            ]
        }
    )
    source.write_text(payload, encoding="utf-8")
    before = source.stat().st_mtime_ns
    plan = build_label_change_plan(
        {"old": _draft("old")},
        {"old": _draft("old", value="new")},
    )
    engine = BatchMigrationEngine(str(tmp_path / "transactions"))
    summary = engine.preflight([str(source)], plan)
    assert summary.candidate_files == 1
    assert summary.matching_shapes == 2
    assert source.stat().st_mtime_ns == before
    assert source.read_text(encoding="utf-8") == payload


def test_preflight_is_cancellable_and_tolerates_invalid_files(tmp_path):
    """Cancel stops iteration early; unreadable files are skipped."""
    broken = tmp_path / "broken.json"
    broken.write_text("{not-json", encoding="utf-8")
    plan = build_label_change_plan(
        {"old": _draft("old")},
        {"old": _draft("old", value="new")},
    )
    engine = BatchMigrationEngine(str(tmp_path / "transactions"))
    assert (
        engine.preflight([str(broken), str(broken)], plan).matching_shapes == 0
    )
    calls = []

    def cancelled():
        calls.append(True)
        return True

    engine.preflight([str(broken)], plan, cancel_check=cancelled)
    assert calls


def test_visual_only_palette_update_does_not_touch_annotation_json(tmp_path):
    """Display metadata is written to the sidecar, never the annotation file."""
    source = tmp_path / "sample.json"
    source.write_text(
        json.dumps({"shapes": [{"label": "person"}]}), encoding="utf-8"
    )
    before = source.read_bytes(), source.stat().st_mtime_ns
    save_project_palette(str(tmp_path), {"person": (1, 2, 3)})
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before


def test_batch_write_gate_blocks_overlapping_owners():
    """The gate is exclusive per root and released only by its owner."""
    from anylabeling.views.labeling.widgets.label_batch import (
        BatchWriteGate,
    )

    assert BatchWriteGate.try_acquire("root", "object-relabel")
    assert not BatchWriteGate.try_acquire("root", "label-batch")
    assert not BatchWriteGate.try_acquire("root", "object-relabel")
    assert BatchWriteGate.try_acquire("other", "label-batch")
    BatchWriteGate.release("root", "label-batch")
    assert not BatchWriteGate.try_acquire("root", "label-batch")
    BatchWriteGate.release("root", "object-relabel")
    BatchWriteGate.release("other", "label-batch")
    assert BatchWriteGate.try_acquire("root", "label-batch")
    BatchWriteGate.release("root", "label-batch")


def test_source_change_during_transform_cannot_be_committed(tmp_path) -> None:
    """A write between parsing and staging cannot become the new baseline."""
    source = tmp_path / "race.json"
    source.write_text('{"shapes": []}', encoding="utf-8")
    external = '{"shapes": [], "new_external_field": true}'

    def transform(_path, original):
        """Simulate an external edit while the worker stages its old read."""
        source.write_text(external, encoding="utf-8")
        return label_batch_module.StagedTransform(
            dict(original, stale_edit=True), changed=True
        )

    engine = label_batch_module.JsonTransactionEngine(str(tmp_path / "txn"))
    staged = engine.stage_files([str(source)], transform)
    result = engine.commit(staged, str(tmp_path))
    assert not result.counts.get("succeeded", 0)
    assert source.read_text(encoding="utf-8") == external
