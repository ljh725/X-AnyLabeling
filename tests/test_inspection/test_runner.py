import json
import threading
from pathlib import Path

from anylabeling.services.inspection.manifest import build_manifest
from anylabeling.services.inspection.models import (
    CoverageState,
    Manifest,
    RunScope,
    RunState,
)
from anylabeling.services.inspection.profiles import (
    build_default_catalog,
    default_profiles,
)
from anylabeling.services.inspection.rules import RuleOutcome
from anylabeling.services.inspection.runner import InspectionRunner


def _write_image(path: Path) -> None:
    path.write_bytes(b"fake-image-bytes")


def _write_annotation(path: Path, shapes, *, width=100, height=80) -> None:
    path.write_text(
        json.dumps(
            {
                "version": "4.2.1",
                "imageWidth": width,
                "imageHeight": height,
                "imagePath": path.with_suffix(".jpg").name,
                "shapes": shapes,
            }
        ),
        encoding="utf-8",
    )


def _shape(shape_id, label="person", points=None, group_id=None):
    return {
        "label": label,
        "shape_type": "rectangle",
        "points": points or [[0, 0], [10, 10]],
        "group_id": group_id,
        "xanylabeling_shape_id": shape_id,
    }


def _dataset(tmp_path):
    image = tmp_path / "a.jpg"
    _write_image(image)
    _write_annotation(tmp_path / "a.json", [_shape("id1")])
    return build_manifest(str(tmp_path))


def test_completed_run_has_explicit_coverage(tmp_path):
    manifest = _dataset(tmp_path)
    report = InspectionRunner().run(
        manifest, default_profiles()[0], RunScope.DATASET
    )
    assert report.state is RunState.COMPLETED
    assert report.completed_files == 1
    assert report.failed_files == 0
    assert report.issues == ()
    assert {
        entry.rule_id for entry in report.coverage
    } == {
        rule.rule_id for rule in default_profiles()[0].enabled_rules
    }


def test_missing_annotation_is_partial_not_success(tmp_path):
    image = tmp_path / "a.jpg"
    _write_image(image)
    manifest = build_manifest(str(tmp_path))
    report = InspectionRunner().run(
        manifest, default_profiles()[0], RunScope.DATASET
    )
    assert report.state is RunState.PARTIAL
    assert report.not_run_files == 1
    assert all(
        entry.state.value in ("skipped", "not_run")
        for entry in report.coverage
        if entry.relative_path == "a.jpg"
    )


def test_malformed_annotation_is_partial_with_failure(tmp_path):
    image = tmp_path / "a.jpg"
    _write_image(image)
    (tmp_path / "a.json").write_text("{bad", encoding="utf-8")
    manifest = build_manifest(str(tmp_path))
    report = InspectionRunner().run(
        manifest, default_profiles()[0], RunScope.DATASET
    )
    assert report.state is RunState.PARTIAL
    assert report.failed_files == 1
    assert any(
        entry.state.value == "failed" for entry in report.coverage
    )


def test_empty_scope_fails_instead_of_zero_issue_success(tmp_path):
    manifest = build_manifest(str(tmp_path))
    report = InspectionRunner().run(
        manifest, default_profiles()[0], RunScope.DATASET
    )
    assert report.state is RunState.FAILED
    assert report.error


def test_cancel_keeps_partial_evidence_and_remaining_coverage(tmp_path):
    for name in ("a.jpg", "b.jpg"):
        image = tmp_path / name
        _write_image(image)
        _write_annotation(
            tmp_path / f"{name[:-4]}.json",
            [_shape("id1"), _shape("id2")],
        )
    manifest = build_manifest(str(tmp_path))
    cancel = threading.Event()

    def progress(index, total, path):
        if index == 1:
            cancel.set()

    report = InspectionRunner().run(
        manifest,
        default_profiles()[0],
        RunScope.DATASET,
        cancel_event=cancel,
        progress=progress,
    )
    assert report.state is RunState.CANCELLED
    assert report.issues
    assert any(
        entry.state.value == "cancelled" for entry in report.coverage
    )


def test_missing_rule_requires_explicit_partial_mode(tmp_path):
    manifest = _dataset(tmp_path)
    profile = default_profiles()[0]
    profile = type(profile).from_dict(
        {
            **profile.to_dict(),
            "rules": [
                {"rule_id": "label_required"},
                {"rule_id": "not_registered"},
            ],
        }
    )
    strict = InspectionRunner(allow_partial_profile=False).run(
        manifest, profile, RunScope.DATASET
    )
    assert strict.state is RunState.FAILED
    subset = InspectionRunner(allow_partial_profile=True).run(
        manifest, profile, RunScope.DATASET
    )
    assert subset.state is RunState.PARTIAL
    assert subset.error


def test_manifest_error_counts_as_requested_and_failed(tmp_path):
    manifest = _dataset(tmp_path)
    manifest = Manifest(
        dataset_root=manifest.dataset_root,
        output_root=manifest.output_root,
        files=manifest.files,
        errors=(
            {
                "relative_path": "broken.jpg",
                "image_path": str(tmp_path / "broken.jpg"),
                "error": "invalid image dimensions",
            },
        ),
    )
    report = InspectionRunner().run(
        manifest, default_profiles()[0], RunScope.DATASET
    )
    assert report.state is RunState.PARTIAL
    assert report.requested_files == 2
    assert report.failed_files == 1
    assert any(
        entry.relative_path == "broken.jpg"
        and entry.rule_id == "__manifest__"
        and entry.state is CoverageState.FAILED
        for entry in report.coverage
    )
    assert any(
        issue.title == "文件读取失败" for issue in report.issues
    )


def test_invalid_dimensions_are_kept_as_failed_file(tmp_path):
    image = tmp_path / "bad.jpg"
    _write_image(image)
    (tmp_path / "bad.json").write_text(
        json.dumps(
            {
                "version": "4.2.1",
                "imageWidth": "not-a-number",
                "imageHeight": 80,
                "shapes": [],
            }
        ),
        encoding="utf-8",
    )
    manifest = build_manifest(str(tmp_path))
    assert manifest.file_count == 1
    assert manifest.files[0].annotation_state == "error"
    report = InspectionRunner().run(
        manifest, default_profiles()[0], RunScope.DATASET
    )
    assert report.state is RunState.PARTIAL
    assert report.requested_files == 1
    assert report.failed_files == 1


def test_summary_counts_objects_per_file_and_images(tmp_path):
    for name in ("a.jpg", "b.jpg"):
        _write_image(tmp_path / name)
        _write_annotation(
            tmp_path / f"{name[:-4]}.json",
            [_shape("id1"), _shape("id2")],
        )
    manifest = build_manifest(str(tmp_path))
    report = InspectionRunner().run(
        manifest, default_profiles()[0], RunScope.DATASET
    )
    summary = report.summary()
    assert summary["issue_count"] == 2
    # The same object ids exist in two different images: they are four
    # distinct objects, not two.
    assert summary["object_count"] == 4
    assert summary["image_count"] == 2
    assert summary["requested_files"] == 2
    assert summary["verification_counts"]["current"] == 2


def test_duplicate_pair_evidence_is_merged_across_rules(tmp_path):
    image = tmp_path / "a.jpg"
    _write_image(image)
    shapes = [
        _shape("id1", group_id=1),
        _shape("id2", group_id=1, points=[[0, 0], [10, 10]]),
    ]
    _write_annotation(tmp_path / "a.json", shapes)
    manifest = build_manifest(str(tmp_path))
    profile = default_profiles()[0]
    profile = type(profile).from_dict(
        {
            **profile.to_dict(),
            "rules": [
                {"rule_id": "duplicate_boxes"},
                {"rule_id": "legacy_same_group_duplicate"},
            ],
        }
    )
    report = InspectionRunner().run(manifest, profile, RunScope.DATASET)
    assert len(report.issues) == 1
    assert {
        item.rule_id for item in report.issues[0].evidence
    } == {"duplicate_boxes", "legacy_same_group_duplicate"}


def test_manifest_errors_without_successful_files_keep_counts(tmp_path):
    manifest = Manifest(
        dataset_root=str(tmp_path),
        output_root="",
        files=(),
        errors=(
            {
                "relative_path": "a.jpg",
                "image_path": str(tmp_path / "a.jpg"),
                "error": "invalid image dimensions",
            },
            {
                "relative_path": "b.jpg",
                "image_path": str(tmp_path / "b.jpg"),
                "error": "permission denied",
            },
        ),
    )
    report = InspectionRunner().run(
        manifest, default_profiles()[0], RunScope.DATASET
    )
    assert report.state is RunState.FAILED
    assert report.requested_files == 2
    assert report.failed_files == 2
    assert len([issue for issue in report.issues if issue.title == "文件读取失败"]) == 2
    assert {
        entry.relative_path for entry in report.coverage
        if entry.rule_id == "__manifest__"
    } == {"a.jpg", "b.jpg"}


def test_excluded_files_are_counted_and_visible(tmp_path):
    image = tmp_path / "a.jpg"
    _write_image(image)
    _write_annotation(tmp_path / "a.json", [_shape("id1")])
    other = tmp_path / "b.jpg"
    _write_image(other)
    manifest = build_manifest(str(tmp_path), excluded_paths=[str(other)])
    report = InspectionRunner().run(
        manifest, default_profiles()[0], RunScope.DATASET
    )
    assert report.excluded_files == 1
    assert any(
        entry.relative_path == "b.jpg"
        and entry.rule_id == "__excluded__"
        and entry.state is CoverageState.SKIPPED
        for entry in report.coverage
    )
    assert any("显式排除 1 个文件" in note for note in report.scope_notes)


def test_cancelled_scan_reports_cancelled_not_completed(tmp_path):
    for name in ("a.jpg", "b.jpg"):
        _write_image(tmp_path / name)
        _write_annotation(tmp_path / f"{name[:-4]}.json", [_shape("id1")])
    calls = {"count": 0}

    def should_cancel() -> bool:
        calls["count"] += 1
        return calls["count"] >= 2

    manifest = build_manifest(
        str(tmp_path),
        image_paths=[
            str(tmp_path / "a.jpg"),
            str(tmp_path / "b.jpg"),
        ],
        should_cancel=should_cancel,
    )
    assert manifest.complete is False
    assert manifest.file_count == 1
    report = InspectionRunner().run(
        manifest, default_profiles()[0], RunScope.DATASET
    )
    assert report.state is RunState.CANCELLED
    assert any("扫描阶段被取消" in note for note in report.scope_notes)


def test_rule_timeout_isolated_as_failure(tmp_path):
    image = tmp_path / "a.jpg"
    _write_image(image)
    _write_annotation(tmp_path / "a.json", [_shape("id1")])
    manifest = build_manifest(str(tmp_path))
    catalog = build_default_catalog()

    def slow_rule(context, parameters):
        import time as _time

        _time.sleep(0.05)
        return RuleOutcome(state=CoverageState.COMPLETED)

    from anylabeling.services.inspection.models import RuleMeta

    catalog.register(
        RuleMeta(
            rule_id="slow_rule",
            implementation_version="1.0.0",
            name="slow",
            description="slow",
            stage="post_label",
            scope="image",
        ),
        slow_rule,
    )
    profile = default_profiles()[0]
    profile = type(profile).from_dict(
        {**profile.to_dict(), "rules": [{"rule_id": "slow_rule"}]}
    )
    report = InspectionRunner(
        catalog, rule_timeout_s=0.01
    ).run(manifest, profile, RunScope.DATASET)
    assert report.state is RunState.PARTIAL
    assert report.failed_files == 1
    entry = next(
        item for item in report.coverage if item.rule_id == "slow_rule"
    )
    assert entry.state is CoverageState.FAILED
    assert "超时" in entry.reason
    assert entry.truncated is True
    assert report.truncated is True
