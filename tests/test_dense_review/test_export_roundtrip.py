"""Training-export and legacy round-trip tests for dense-review progress.

The repository's real training-label export entry point is
``LabelingWidget.export_yolo_annotation`` in
``anylabeling/views/labeling/utils/export.py``.  The GUI part only collects
a classes file and paths; the actual JSON -> YOLO conversion is
``LabelConverter.custom_to_yolo`` in
``anylabeling/views/labeling/label_converter.py``.  These tests exercise
that converter headlessly on a temporary label file written by
``LabelFile``, so the export covers the same conversion used for training.
"""

import json

from PIL import Image

from anylabeling.services.dense_review import (
    coverage as coverage_service,
)
from anylabeling.services.dense_review.session import DenseReviewSession
from anylabeling.services.dense_review.storage import (
    DENSE_REVIEW_FIELD,
    load_payload,
)
from anylabeling.views.labeling.label_converter import LabelConverter
from anylabeling.views.labeling.label_file import LabelFile

from .conftest import make_config, make_shape


def _write_image(tmp_path):
    image_path = tmp_path / "image.png"
    Image.new("RGB", (200, 200), color=(220, 220, 220)).save(image_path)
    return image_path


def _annotation():
    return {
        "version": "4.2.1",
        "flags": {"reviewed": True},
        "checked": True,
        "shapes": [
            {
                "label": "A",
                "shape_type": "rectangle",
                "points": [[10, 10], [50, 10], [50, 50], [10, 50]],
                "xanylabeling_shape_id": "id1",
                "group_id": 3,
                "score": 0.5,
                "difficult": True,
                "flags": {"hard": True},
                "attributes": {"occluded": False, "vendor": "keep"},
                "review_status": "pending",
                "vendor_extension": {"nested": [1, 2]},
            },
            {
                "label": "B",
                "shape_type": "rectangle",
                "points": [[70, 10], [110, 10], [110, 50], [70, 50]],
                "xanylabeling_shape_id": "id2",
                "review_status": "pending",
            },
            {
                "label": "C",
                "shape_type": "polygon",
                "points": [
                    [10, 100],
                    [50, 100],
                    [50, 140],
                    [10, 140],
                ],
                "xanylabeling_shape_id": "id3",
            },
        ],
        "imagePath": "image.png",
        "imageData": None,
        "imageHeight": 200,
        "imageWidth": 200,
        "tags": ["night"],
        "project_meta": {"batch": "b1"},
        "custom_top_level": [1, 2, 3],
    }


def _write_annotation(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def _make_session(shapes, payload=None):
    session = DenseReviewSession.from_shapes(
        make_config(),
        shapes,
        "fp",
        200,
        200,
        payload,
    )
    session.confirm_batch("batch-0", ("category", "geometry"))
    session.ensure_coverage()
    for region in list(session.state.coverage.regions):
        session.complete_region(region.region_id)
    return session


def _dense_payload():
    shapes = [
        make_shape("id1", "A", (10, 10, 50, 50)),
        make_shape("id2", "B", (70, 10, 110, 50)),
        make_shape("id3", "C", (10, 100, 50, 140), "polygon"),
    ]
    session = _make_session(shapes)
    return session.to_payload()


def _write_round_trip_file(tmp_path):
    _write_image(tmp_path)
    path = tmp_path / "image.json"
    _write_annotation(path, _annotation())
    label_file = LabelFile(str(path))
    payload = _dense_payload()
    label_file.other_data[DENSE_REVIEW_FIELD] = payload
    label_file.save(
        filename=str(path),
        shapes=[shape.to_dict() for shape in label_file.shapes],
        image_path="image.png",
        image_height=200,
        image_width=200,
        other_data=label_file.other_data,
        flags=label_file.flags,
    )
    return path, payload


def test_saved_file_keeps_progress_out_of_shapes(tmp_path):
    path, payload = _write_round_trip_file(tmp_path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved[DENSE_REVIEW_FIELD] == payload
    assert saved["checked"] is True
    for shape in saved["shapes"]:
        assert DENSE_REVIEW_FIELD not in json.dumps(shape)
    # The namespace can only be a top-level key, never repeated inside an
    # object entry that a training export could pick up.
    assert json.dumps(saved).count(DENSE_REVIEW_FIELD) == 1


def test_legacy_fields_and_shape_extensions_survive_round_trip(tmp_path):
    _write_image(tmp_path)
    path = tmp_path / "image.json"
    _write_annotation(path, _annotation())
    loaded = LabelFile(str(path))
    assert loaded.other_data["checked"] is True
    assert loaded.other_data["project_meta"] == {"batch": "b1"}
    assert loaded.other_data["custom_top_level"] == [1, 2, 3]
    assert DENSE_REVIEW_FIELD not in loaded.other_data
    shapes = {shape.xanylabeling_shape_id: shape for shape in loaded.shapes}
    assert shapes["id1"].other_data["review_status"] == "pending"
    assert shapes["id1"].other_data["vendor_extension"] == {"nested": [1, 2]}
    assert shapes["id1"].attributes == {
        "occluded": False,
        "vendor": "keep",
    }

    loaded.save(
        filename=str(path),
        shapes=[shape.to_dict() for shape in loaded.shapes],
        image_path="image.png",
        image_height=200,
        image_width=200,
        other_data=loaded.other_data,
        flags=loaded.flags,
    )
    reloaded = LabelFile(str(path))
    assert reloaded.other_data["checked"] is True
    assert reloaded.other_data["project_meta"] == {"batch": "b1"}
    assert reloaded.other_data["custom_top_level"] == [1, 2, 3]
    assert reloaded.other_data["tags"] == ["night"]
    assert DENSE_REVIEW_FIELD not in reloaded.other_data
    shapes = {shape.xanylabeling_shape_id: shape for shape in reloaded.shapes}
    assert shapes["id1"].other_data["review_status"] == "pending"
    assert shapes["id1"].other_data["vendor_extension"] == {"nested": [1, 2]}
    assert shapes["id1"].attributes == {
        "occluded": False,
        "vendor": "keep",
    }
    assert shapes["id1"].flags == {"hard": True}
    assert shapes["id1"].group_id == 3
    assert shapes["id1"].score == 0.5
    assert shapes["id1"].difficult is True
    for shape in reloaded.shapes:
        assert DENSE_REVIEW_FIELD not in shape.other_data


def test_training_export_contains_only_training_fields(tmp_path):
    path, _payload = _write_round_trip_file(tmp_path)
    classes_path = tmp_path / "classes.txt"
    classes_path.write_text("A\nB\n", encoding="utf-8")
    output_path = tmp_path / "labels" / "image.txt"
    output_path.parent.mkdir()
    converter = LabelConverter(classes_file=str(classes_path))

    is_empty = converter.custom_to_yolo(str(path), str(output_path), "hbb")

    assert is_empty is False
    text = output_path.read_text(encoding="utf-8")
    assert DENSE_REVIEW_FIELD not in text
    lines = [line for line in text.splitlines() if line.strip()]
    assert len(lines) == 2
    for line in lines:
        parts = line.split()
        assert len(parts) == 5
        assert int(parts[0]) in (0, 1)
        assert all(float(value) >= 0.0 for value in parts[1:])


def test_old_program_rewrite_without_namespace_does_not_restore(
    tmp_path,
):
    path, _payload = _write_round_trip_file(tmp_path)
    rewritten = json.loads(path.read_text(encoding="utf-8"))
    rewritten.pop(DENSE_REVIEW_FIELD)
    rewritten["checked"] = True
    rewritten["shapes"][0]["label"] = "B"
    rewritten["shapes"][0]["review_status"] = "passed"
    rewritten["shapes"][0]["points"] = [
        [85, 85],
        [95, 85],
        [95, 95],
        [85, 95],
    ]
    _write_annotation(path, rewritten)

    reloaded = LabelFile(str(path))
    payload = load_payload(reloaded.other_data)
    assert payload is None
    session = DenseReviewSession.from_shapes(
        make_config(),
        reloaded.shapes,
        "fp",
        200,
        200,
        payload,
    )
    assert session.has_payload is False
    assert not session.object("id1").confirmed_both()
    assert not session.object("id2").confirmed_both()
    assert session.state.coverage is None
    assert not session.completion_status().complete


def test_old_program_edit_invalidates_confirmations_and_coverage(
    tmp_path,
):
    path, _payload = _write_round_trip_file(tmp_path)
    rewritten = json.loads(path.read_text(encoding="utf-8"))
    assert DENSE_REVIEW_FIELD in rewritten
    rewritten["checked"] = True
    rewritten["shapes"][0]["label"] = "B"
    rewritten["shapes"][0]["points"] = [
        [85, 85],
        [95, 85],
        [95, 95],
        [85, 95],
    ]
    _write_annotation(path, rewritten)

    reloaded = LabelFile(str(path))
    payload = load_payload(reloaded.other_data)
    assert payload is not None
    session = DenseReviewSession.from_shapes(
        make_config(),
        reloaded.shapes,
        "fp",
        200,
        200,
        payload,
    )
    assert session.has_payload is True
    assert not session.object("id1").confirmed_both()
    assert session.object("id2").confirmed_both()
    counts = coverage_service.coverage_counts(session.state.coverage)
    assert counts["completed"] < counts["total"]
    assert not session.completion_status().complete
