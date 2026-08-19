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


def test_visual_only_palette_update_does_not_touch_annotation_json(tmp_path):
    """Display metadata is written to the sidecar, never the annotation file."""
    source = tmp_path / "sample.json"
    source.write_text(
        json.dumps({"shapes": [{"label": "person"}]}), encoding="utf-8"
    )
    before = source.read_bytes(), source.stat().st_mtime_ns
    save_project_palette(str(tmp_path), {"person": (1, 2, 3)})
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before
