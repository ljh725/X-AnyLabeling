import json
from pathlib import Path

from dataclasses import replace

from anylabeling.services.inspection.manifest import (
    build_manifest,
    memory_file_snapshot,
)
from anylabeling.services.inspection.models import RunScope
from anylabeling.services.inspection.profiles import (
    build_default_catalog,
    default_profiles,
)
from anylabeling.services.inspection.runner import InspectionRunner
from anylabeling.services.inspection.verification import (
    verify_report_context,
)


def _report_and_manifest(tmp_path):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"fake")
    annotation = tmp_path / "a.json"
    annotation.write_text(
        json.dumps(
            {
                "version": "4.2.1",
                "imageWidth": 100,
                "imageHeight": 80,
                "shapes": [
                    {
                        "label": "person",
                        "shape_type": "rectangle",
                        "points": [[0, 0], [10, 10]],
                        "xanylabeling_shape_id": "id1",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = build_manifest(str(tmp_path))
    report = InspectionRunner().run(
        manifest, default_profiles()[0], RunScope.DATASET
    )
    return report, manifest, annotation


def _memory(tmp_path, points, unsaved=True):
    return memory_file_snapshot(
        str(tmp_path / "a.jpg"),
        "a.jpg",
        [
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": points,
                "xanylabeling_shape_id": "id1",
            }
        ],
        image_width=100,
        image_height=80,
        unsaved=unsaved,
    )


def test_unchanged_report_context_is_current(tmp_path):
    report, manifest, _ = _report_and_manifest(tmp_path)
    verification = verify_report_context(
        report,
        manifest,
        build_default_catalog(),
        str(tmp_path),
        "",
        default_profiles()[0],
    )
    assert verification.current is True
    assert verification.reasons == ()


def test_changed_annotation_marks_file_stale(tmp_path):
    report, manifest, annotation = _report_and_manifest(tmp_path)
    payload = json.loads(annotation.read_text(encoding="utf-8"))
    payload["shapes"][0]["points"] = [[1, 1], [11, 11]]
    annotation.write_text(json.dumps(payload), encoding="utf-8")
    verification = verify_report_context(
        report,
        manifest,
        build_default_catalog(),
        str(tmp_path),
        "",
        default_profiles()[0],
    )
    assert verification.current is False
    assert "a.jpg" in verification.stale_files
    assert verification.reasons


def test_changed_profile_marks_config_stale(tmp_path):
    report, manifest, _ = _report_and_manifest(tmp_path)
    changed = replace(default_profiles()[0], stage="in_progress")
    verification = verify_report_context(
        report,
        manifest,
        build_default_catalog(),
        str(tmp_path),
        "",
        changed,
    )
    assert verification.current is False
    assert verification.config_changed is True


def test_matching_memory_snapshot_keeps_context_current(tmp_path):
    report, manifest, _ = _report_and_manifest(tmp_path)
    verification = verify_report_context(
        report,
        manifest,
        build_default_catalog(),
        str(tmp_path),
        "",
        default_profiles()[0],
        memory_files={"a.jpg": _memory(tmp_path, [[0, 0], [10, 10]])},
    )
    assert verification.current is True
    assert verification.pending_files == ()


def test_missing_identity_does_not_cause_false_pending(tmp_path):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"fake")
    annotation = tmp_path / "a.json"
    annotation.write_text(
        json.dumps(
            {
                "version": "4.2.1",
                "imageWidth": 100,
                "imageHeight": 80,
                "shapes": [
                    {
                        "label": "person",
                        "shape_type": "rectangle",
                        "points": [[0, 0], [10, 10]],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = build_manifest(str(tmp_path))
    report = InspectionRunner().run(
        manifest, default_profiles()[0], RunScope.DATASET
    )
    memory = memory_file_snapshot(
        str(image),
        "a.jpg",
        [
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[0, 0], [10, 10]],
            }
        ],
        image_width=100,
        image_height=80,
    )
    verification = verify_report_context(
        report,
        manifest,
        build_default_catalog(),
        str(tmp_path),
        "",
        default_profiles()[0],
        memory_files={"a.jpg": memory},
    )
    assert verification.current is True


def test_unsaved_memory_change_is_pending_not_stale(tmp_path):
    report, manifest, _ = _report_and_manifest(tmp_path)
    verification = verify_report_context(
        report,
        manifest,
        build_default_catalog(),
        str(tmp_path),
        "",
        default_profiles()[0],
        memory_files={"a.jpg": _memory(tmp_path, [[5, 5], [31, 31]])},
    )
    assert verification.current is False
    assert verification.pending_files == ("a.jpg",)
    assert verification.stale_files == ()


def test_disk_change_still_wins_when_memory_matches_report(tmp_path):
    report, manifest, annotation = _report_and_manifest(tmp_path)
    payload = json.loads(annotation.read_text(encoding="utf-8"))
    payload["shapes"][0]["points"] = [[1, 1], [11, 11]]
    annotation.write_text(json.dumps(payload), encoding="utf-8")
    verification = verify_report_context(
        report,
        manifest,
        build_default_catalog(),
        str(tmp_path),
        "",
        default_profiles()[0],
        memory_files={"a.jpg": _memory(tmp_path, [[0, 0], [10, 10]])},
    )
    assert verification.current is False
    assert verification.stale_files == ("a.jpg",)


def test_missing_manifest_is_explicit(tmp_path):
    report, _, _ = _report_and_manifest(tmp_path)
    verification = verify_report_context(
        report,
        None,
        build_default_catalog(),
        str(tmp_path),
        "",
        default_profiles()[0],
    )
    assert verification.current is False
    assert verification.missing_manifest is True


def test_explicit_output_root_cleared_back_to_default_is_detected(tmp_path):
    report, manifest, _ = _report_and_manifest(tmp_path)
    explicit = tmp_path / "out"
    explicit.mkdir()
    report = replace(report, output_root=str(explicit))
    verification = verify_report_context(
        report,
        manifest,
        build_default_catalog(),
        str(tmp_path),
        "",
        default_profiles()[0],
    )
    assert verification.output_changed is True
    assert verification.current is False


def test_memory_report_detects_same_size_image_replacement(tmp_path):
    report, manifest, _ = _report_and_manifest(tmp_path)
    memory_report = replace(
        report,
        source_kind="memory",
        output_root="",
    )
    # Replace the image with different bytes but the same dimensions.
    (tmp_path / "a.jpg").write_bytes(b"other-bytes")
    memory = memory_file_snapshot(
        str(tmp_path / "a.jpg"),
        "a.jpg",
        [],
        image_width=100,
        image_height=80,
    )
    verification = verify_report_context(
        memory_report,
        manifest,
        build_default_catalog(),
        str(tmp_path),
        "",
        default_profiles()[0],
        memory_files={"a.jpg": memory},
    )
    assert verification.current is False
    assert "图片内容已变化" in " ".join(verification.reasons)


def test_report_without_image_identity_is_not_trusted(tmp_path):
    report, manifest, _ = _report_and_manifest(tmp_path)
    stripped = replace(
        report,
        issues=(),
        manifest_fingerprint=report.manifest_fingerprint,
    )
    # Simulate an old in-memory report snapshot that never recorded image
    # identity: it must not be treated as current even when shapes match.
    old_manifest = type(manifest)(
        dataset_root=manifest.dataset_root,
        output_root=manifest.output_root,
        files=tuple(
            replace(
                file,
                annotation_state="memory",
                image_digest="",
                image_digest_kind="",
            )
            for file in manifest.files
        ),
        errors=manifest.errors,
        excluded=manifest.excluded,
        complete=manifest.complete,
        generated_at=manifest.generated_at,
    )
    memory = memory_file_snapshot(
        str(tmp_path / "a.jpg"),
        "a.jpg",
        [],
        image_width=100,
        image_height=80,
    )
    verification = verify_report_context(
        stripped,
        old_manifest,
        build_default_catalog(),
        str(tmp_path),
        "",
        default_profiles()[0],
        memory_files={"a.jpg": memory},
    )
    assert verification.current is False
    assert any("图片身份" in reason for reason in verification.reasons)


def test_memory_report_requires_matching_canvas_snapshot(tmp_path):
    report, manifest, _ = _report_and_manifest(tmp_path)
    memory_report = replace(
        report,
        manifest_fingerprint=manifest.fingerprint(),
    )
    snapshot = memory_file_snapshot(
        str(tmp_path / "a.jpg"),
        "a.jpg",
        [],
        image_width=100,
        image_height=80,
    )
    replacement = type(manifest)(
        dataset_root=manifest.dataset_root,
        output_root=manifest.output_root,
        files=(replace(snapshot, annotation_state="memory"),),
        errors=(),
        excluded=(),
        complete=True,
        generated_at=manifest.generated_at,
    )
    verification = verify_report_context(
        memory_report,
        replacement,
        build_default_catalog(),
        str(tmp_path),
        "",
        default_profiles()[0],
        memory_files={},
    )
    assert verification.current is False
    assert "未保存画布" in " ".join(verification.reasons)


def test_save_normalization_keeps_report_current(tmp_path):
    report, manifest, annotation = _report_and_manifest(tmp_path)
    # Re-saving writes the canonical four-point rectangle and formatted JSON:
    # the bytes change but the annotation content does not.
    payload = json.loads(annotation.read_text(encoding="utf-8"))
    payload["shapes"][0]["points"] = [
        [0, 0],
        [10, 0],
        [10, 10],
        [0, 10],
    ]
    annotation.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    verification = verify_report_context(
        report,
        manifest,
        build_default_catalog(),
        str(tmp_path),
        "",
        default_profiles()[0],
    )
    assert verification.current is True, verification.reasons
    assert verification.stale_files == ()


def test_external_annotation_modification_is_detected(tmp_path):
    report, manifest, annotation = _report_and_manifest(tmp_path)
    payload = json.loads(annotation.read_text(encoding="utf-8"))
    payload["shapes"][0]["label"] = "car"
    annotation.write_text(json.dumps(payload), encoding="utf-8")
    verification = verify_report_context(
        report,
        manifest,
        build_default_catalog(),
        str(tmp_path),
        "",
        default_profiles()[0],
    )
    assert verification.current is False
    assert verification.stale_files == ("a.jpg",)
    assert any("标注内容已变化" in reason for reason in verification.reasons)


def test_exif_orientation_change_is_detected(tmp_path):
    from PIL import Image

    image = tmp_path / "a.jpg"
    Image.new("RGB", (100, 80)).save(image)
    (tmp_path / "a.json").write_text(
        json.dumps(
            {
                "version": "4.2.1",
                "imageWidth": 100,
                "imageHeight": 80,
                "shapes": [],
            }
        ),
        encoding="utf-8",
    )
    manifest = build_manifest(str(tmp_path), hash_images=True)
    report = InspectionRunner().run(
        manifest, default_profiles()[0], RunScope.DATASET
    )
    # Give the report a recorded orientation and keep the image bytes intact.
    rotated = replace(
        manifest,
        files=tuple(
            replace(file, image_orientation="6") for file in manifest.files
        ),
    )
    report = replace(report, output_root="")
    verification = verify_report_context(
        report,
        rotated,
        build_default_catalog(),
        str(tmp_path),
        "",
        default_profiles()[0],
    )
    # The current image reports orientation 1, so the recorded 6 is stale.
    assert verification.current is False
    assert any("方向" in reason for reason in verification.reasons)


def test_context_summary_lists_boundary_and_versions(tmp_path):
    from anylabeling.services.inspection.verification import (
        report_context_summary,
    )

    report, manifest, _ = _report_and_manifest(tmp_path)
    summary = report_context_summary(report, manifest)
    assert summary["config_digest"] == report.config_digest
    assert summary["rule_versions"]["duplicate_boxes"] == "1.0.0"
    entry = summary["files"][0]
    assert entry["relative_path"] == "a.jpg"
    assert entry["image_width"] == 100
    assert entry["image_height"] == 80
    assert entry["annotation_normalized_digest"]
    assert "image_orientation" in entry
