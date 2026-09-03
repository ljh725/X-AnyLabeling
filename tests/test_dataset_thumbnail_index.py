"""Tests for dataset thumbnail index references and pagination."""

import json

from anylabeling.views.labeling.dataset_index import DatasetFilterIndex


def _write_dataset(tmp_path, shapes):
    """Create one image/JSON pair for index tests."""
    image_path = tmp_path / "sample.jpg"
    image_path.write_bytes(b"image")
    json_path = tmp_path / "sample.json"
    json_path.write_text(json.dumps({"shapes": shapes}), encoding="utf-8")
    return image_path, json_path


def test_geometry_read_keeps_legacy_default_shape_contract(tmp_path):
    """Geometry extraction is opt-in so existing index callers stay stable."""
    image_path, json_path = _write_dataset(
        tmp_path,
        [
            {
                "label": "person",
                "shape_type": "rectangle",
                "xanylabeling_shape_id": "a" * 32,
                "points": [[4, 8], [1, 2]],
            }
        ],
    )

    legacy, error = DatasetFilterIndex._read_shapes(str(json_path))
    geometry, geometry_error = DatasetFilterIndex._read_shapes(
        str(json_path), include_geometry=True
    )

    assert error == geometry_error == ""
    assert legacy == [("person", "-1", "rectangle")]
    assert geometry == [
        ("person", "-1", "rectangle", "a" * 32, 1.0, 2.0, 4.0, 8.0)
    ]
    assert image_path.exists()


def test_thumbnail_query_returns_stable_bounded_page(tmp_path):
    """Indexed thumbnail rows expose identity, bbox and deterministic order."""
    image_path, _ = _write_dataset(
        tmp_path,
        [
            {
                "label": "person",
                "shape_type": "rectangle",
                "xanylabeling_shape_id": f"{index:032x}",
                "points": [[index, 0], [index + 3, 4]],
            }
            for index in range(3)
        ],
    )
    index = DatasetFilterIndex(":memory:")
    try:
        index.rebuild([str(image_path)], dataset_root=str(tmp_path))
        assert index.query_label_counts() == [("person", 3)]
        page = index.query_thumbnail_objects("person", limit=200, offset=1)
        assert page.total == 3
        assert page.limit == 100
        assert page.offset == 1
        assert len(page.items) == 2
        assert page.items[0].shape_id == f"{1:032x}"
        assert page.items[0].bbox == (1.0, 0.0, 4.0, 4.0)
        assert page.items[0].image_path == str(image_path)
    finally:
        index.close()


def test_thumbnail_query_preserves_invalid_bbox_as_non_selectable_metadata(
    tmp_path,
):
    """Shapes without usable points remain visible with a missing bbox."""
    image_path, _ = _write_dataset(
        tmp_path,
        [
            {
                "label": "point",
                "shape_type": "point",
                "xanylabeling_shape_id": "b" * 32,
                "points": [],
            }
        ],
    )
    index = DatasetFilterIndex(":memory:")
    try:
        index.rebuild([str(image_path)], dataset_root=str(tmp_path))
        page = index.query_thumbnail_objects("point")
        assert page.items[0].bbox is None
        assert page.items[0].shape_id == "b" * 32
    finally:
        index.close()
