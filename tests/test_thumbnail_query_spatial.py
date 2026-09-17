from anylabeling.views.labeling.dataset_index.thumbnail_query import (
    _spatial_order,
)
from anylabeling.views.labeling.rect_edge_click import classify_axis


def _row(path, order, index, shape_id, box):
    return (
        path,
        path + ".json",
        order,
        index,
        shape_id,
        "label",
        *box,
        None,
        "",
        0,
        "",
        "rectangle",
        100,
        100,
        "sig",
        "unreviewed",
        1,
        1,
        1,
        1,
    )


def test_spatial_order_groups_by_image_and_is_stable():
    rows = [
        _row("a.jpg", 0, 2, "c", (80, 80, 90, 90)),
        _row("a.jpg", 0, 0, "a", (0, 0, 10, 10)),
        _row("a.jpg", 0, 1, "b", (20, 0, 30, 10)),
        _row("b.jpg", 1, 0, "d", (0, 0, 2, 2)),
    ]
    ordered = _spatial_order(rows)
    assert [row[4] for row in ordered] == ["a", "b", "c", "d"]


def test_spatial_order_keeps_invalid_boxes_last_per_image():
    rows = [
        _row("a.jpg", 0, 0, "bad", (None, 0, 1, 1)),
        _row("a.jpg", 0, 1, "good", (0, 0, 2, 2)),
    ]
    assert [row[4] for row in _spatial_order(rows)] == ["good", "bad"]


def test_axis_classification_uses_committed_center_half():
    box = (10.0, 20.0, 30.0, 40.0)
    assert classify_axis(box, (10.0, 35.0), "x").edge == "left"
    assert classify_axis(box, (30.0, 35.0), "x").edge == "right"
    assert classify_axis(box, (25.0, 20.0), "y").edge == "top"
    assert classify_axis(box, (25.0, 40.0), "y").edge == "bottom"
