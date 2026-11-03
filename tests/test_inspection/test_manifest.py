import json
from pathlib import Path

from anylabeling.services.inspection.manifest import (
    build_manifest,
    changed_relative_paths,
    filter_manifest,
    load_file_snapshot,
    memory_file_snapshot,
)


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
