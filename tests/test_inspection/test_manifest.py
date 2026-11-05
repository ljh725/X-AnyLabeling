import json
from pathlib import Path

from anylabeling.services.inspection.manifest import (
    build_manifest,
    changed_relative_paths,
    compare_manifests,
    filter_manifest,
    load_file_snapshot,
    memory_file_snapshot,
)
from anylabeling.services.inspection.models import RunScope
from anylabeling.services.inspection.profiles import default_profiles
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


def test_missing_annotation_is_explicit(tmp_path):
    image = tmp_path / "a.jpg"
    _write_image(image)
    snapshot = load_file_snapshot(str(image), str(tmp_path))
    assert snapshot.annotation_state == "missing"
    assert snapshot.shapes == ()


def test_malformed_annotation_is_explicit(tmp_path):
    image = tmp_path / "a.jpg"
    _write_image(image)
    (tmp_path / "a.json").write_text("{not-json", encoding="utf-8")
    snapshot = load_file_snapshot(str(image), str(tmp_path))
    assert snapshot.annotation_state == "error"
    assert snapshot.error


def test_duplicate_identity_gets_ephemeral_snapshot_id(tmp_path):
    image = tmp_path / "a.jpg"
    _write_image(image)
    _write_annotation(
        tmp_path / "a.json",
        [
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[0, 0], [10, 10]],
                "xanylabeling_shape_id": "same",
            },
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[2, 2], [12, 12]],
                "xanylabeling_shape_id": "same",
            },
        ],
    )
    snapshot = load_file_snapshot(str(image), str(tmp_path))
    assert snapshot.shapes[0].identity_valid is True
    assert snapshot.shapes[0].shape_id == "same"
    assert snapshot.shapes[1].identity_valid is False
    assert snapshot.shapes[1].shape_id.startswith("ephemeral-")


def test_memory_snapshot_is_unsaved_and_has_digest(tmp_path):
    image = tmp_path / "a.jpg"
    _write_image(image)
    snapshot = memory_file_snapshot(
        str(image),
        "a.jpg",
        [
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[0, 0], [10, 10]],
                "xanylabeling_shape_id": "id1",
            }
        ],
        image_width=100,
        image_height=80,
    )
    assert snapshot.unsaved is True
    assert snapshot.annotation_state == "memory"
    assert len(snapshot.annotation_digest) == 64


def test_manifest_and_changed_paths(tmp_path):
    for name in ("a.jpg", "b.jpg"):
        image = tmp_path / name
        _write_image(image)
        _write_annotation(tmp_path / f"{name[:-4]}.json", [])
    manifest = build_manifest(str(tmp_path))
    assert manifest.file_count == 2
    assert manifest.complete is True

    (tmp_path / "a.json").write_text(
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
    updated = build_manifest(str(tmp_path))
    changed = changed_relative_paths(manifest, updated)
    assert changed == ("a.jpg",)
    filtered = filter_manifest(updated, ["b.jpg"])
    assert filtered.file_count == 1
    assert filtered.files[0].relative_path == "b.jpg"


def test_malformed_points_are_reported_not_trimmed(tmp_path):
    image = tmp_path / "a.jpg"
    _write_image(image)
    _write_annotation(
        tmp_path / "a.json",
        [
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[0, 0], ["bad", 5], [10, 10]],
                "xanylabeling_shape_id": "id1",
            },
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[0, 0], [float("nan"), 5], [10, 10]],
                "xanylabeling_shape_id": "id2",
            },
        ],
    )
    snapshot = load_file_snapshot(str(image), str(tmp_path))
    assert snapshot.shapes[0].input_errors
    assert not snapshot.shapes[0].input_valid
    assert snapshot.shapes[0].input_errors[0].startswith("第 1 个点")
    # The remaining two points must not be expanded into a fabricated legal
    # rectangle: the original structure is preserved as an invalid input.
    assert len(snapshot.shapes[0].points) == 2
    assert snapshot.shapes[1].input_errors
    report = InspectionRunner().run(
        build_manifest(str(tmp_path)), default_profiles()[0], RunScope.DATASET
    )
    geometry = [
        issue
        for issue in report.issues
        if "bbox_geometry_valid" in issue.rule_ids
    ]
    assert geometry, "malformed coordinates must be reported, not ignored"
    assert any("原始坐标存在异常" in issue.message for issue in geometry)
    assert report.state.value in ("partial", "completed")


def test_changed_scope_sees_new_missing_annotation_and_image_change(tmp_path):
    for name in ("a.jpg", "b.jpg"):
        _write_image(tmp_path / name)
        _write_annotation(tmp_path / f"{name[:-4]}.json", [])
    previous = build_manifest(str(tmp_path))
    # A new image without any JSON must be in the changed set even though its
    # annotation digest is empty in both manifests.
    _write_image(tmp_path / "c.jpg")
    current = build_manifest(str(tmp_path))
    delta = compare_manifests(previous, current)
    assert "c.jpg" in delta.added
    assert "c.jpg" in delta.changed
    assert "a.jpg" not in delta.changed

    # Replacing the image bytes changes the image identity of an existing
    # file even when its annotation is untouched.
    (tmp_path / "a.jpg").write_bytes(b"different-image-bytes")
    current = build_manifest(str(tmp_path))
    delta = compare_manifests(previous, current)
    assert "a.jpg" in delta.modified

    (tmp_path / "b.jpg").unlink()
    current = build_manifest(str(tmp_path))
    delta = compare_manifests(previous, current)
    assert "b.jpg" in delta.removed

    forced = compare_manifests(previous, current, config_changed=True)
    assert set(forced.changed) == {"a.jpg", "c.jpg"}
    assert forced.reasons["a.jpg"] == "方案或规则实现版本变化"
    assert forced.reasons["c.jpg"] == "新增文件"


def test_excluded_files_are_recorded_with_reason(tmp_path):
    for name in ("a.jpg", "b.jpg"):
        (tmp_path / name).write_bytes(b"fake-image-bytes")
    manifest = build_manifest(
        str(tmp_path), excluded_paths=[str(tmp_path / "a.jpg")]
    )
    assert [file.relative_path for file in manifest.files] == ["b.jpg"]
    assert len(manifest.excluded) == 1
    assert manifest.excluded[0]["relative_path"] == "a.jpg"
    assert manifest.excluded[0]["reason"]


def test_memory_snapshot_fixes_image_identity(tmp_path):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"image-content")
    snapshot = memory_file_snapshot(
        str(image),
        "a.jpg",
        [],
        image_width=10,
        image_height=10,
    )
    assert snapshot.image_digest
    assert snapshot.image_digest_kind == "content"
    assert snapshot.annotation_state == "memory"
