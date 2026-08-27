"""Tests for project-wide persistent Shape identity assignment."""

import json

from anylabeling.views.labeling.shape_identity_project import (
    discover_project_json_files,
    ensure_project_shape_ids,
)


def _write_json(path, shapes):
    """Write a minimal annotation JSON fixture."""
    path.write_text(
        json.dumps({"imagePath": "image.jpg", "shapes": shapes}),
        encoding="utf-8",
    )


def test_project_assignment_repairs_all_files_and_preserves_existing_ids(
    tmp_path,
):
    """The batch action writes only files needing identity repairs."""
    nested = tmp_path / "nested"
    nested.mkdir()
    first = tmp_path / "first.json"
    second = nested / "second.json"
    _write_json(first, [{"label": "a"}, {"label": "b"}])
    _write_json(second, [{"xanylabeling_shape_id": "existing"}])
    before_second = second.read_bytes()

    paths = discover_project_json_files([str(tmp_path), str(nested)])
    result = ensure_project_shape_ids(paths)

    assert result.files_scanned == 2
    assert result.files_changed == 1
    assert result.shapes_assigned == 2
    assert result.files_failed == 0
    assert second.read_bytes() == before_second
    first_shapes = json.loads(first.read_text(encoding="utf-8"))["shapes"]
    assert len({shape["xanylabeling_shape_id"] for shape in first_shapes}) == 2
    assert all(
        next(iter(shape)) == "xanylabeling_shape_id" for shape in first_shapes
    )
    assert all(
        set(shape) == {"xanylabeling_shape_id", "label"}
        for shape in first_shapes
    )


def test_project_assignment_repairs_duplicate_ids_and_reports_bad_file(
    tmp_path,
):
    """Duplicate IDs are repaired while malformed files are isolated."""
    duplicate = tmp_path / "duplicate.json"
    malformed = tmp_path / "malformed.json"
    _write_json(
        duplicate,
        [
            {"xanylabeling_shape_id": "same"},
            {"xanylabeling_shape_id": "same"},
        ],
    )
    malformed.write_text(
        json.dumps({"shapes": "not-an-array"}),
        encoding="utf-8",
    )

    result = ensure_project_shape_ids(
        discover_project_json_files([str(tmp_path)])
    )

    assert result.files_changed == 1
    assert result.shapes_assigned == 1
    assert result.files_failed == 1
    duplicate_shapes = json.loads(duplicate.read_text(encoding="utf-8"))[
        "shapes"
    ]
    assert duplicate_shapes[0]["xanylabeling_shape_id"] == "same"
    assert duplicate_shapes[1]["xanylabeling_shape_id"] != "same"
    failures = [item for item in result.file_results if item.error]
    assert failures[0].path == str(malformed)


def test_project_assignment_deduplicates_overlapping_roots(tmp_path):
    """Overlapping image and annotation roots do not process files twice."""
    annotation = tmp_path / "annotation.json"
    _write_json(annotation, [{"label": "a"}])

    paths = discover_project_json_files([str(tmp_path), str(annotation)])

    assert paths == (str(annotation),)


def test_project_assignment_moves_existing_identity_to_first_position(
    tmp_path,
):
    """Existing IDs are reordered without adding or removing other fields."""
    annotation = tmp_path / "annotation.json"
    original_shape = {
        "label": "reading",
        "points": [[1, 2], [3, 4]],
        "shape_type": "rectangle",
        "flags": {},
        "xanylabeling_shape_id": "existing-id",
    }
    _write_json(annotation, [original_shape])

    result = ensure_project_shape_ids([str(annotation)])

    shape = json.loads(annotation.read_text(encoding="utf-8"))["shapes"][0]
    assert result.files_changed == 1
    assert result.shapes_assigned == 0
    assert list(shape) == [
        "xanylabeling_shape_id",
        "label",
        "points",
        "shape_type",
        "flags",
    ]
    assert shape["xanylabeling_shape_id"] == "existing-id"
    assert shape["points"] == original_shape["points"]
