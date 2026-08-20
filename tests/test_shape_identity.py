"""Shape identity lifecycle tests."""

from anylabeling.views.labeling.widgets.canvas import Canvas  # noqa: F401
from anylabeling.views.labeling.shape import Shape


def _shape_data(shape_id="shape-from-json"):
    """Return a minimal rectangle mapping."""
    return {
        "xanylabeling_shape_id": shape_id,
        "label": "person",
        "score": None,
        "points": [[1.0, 2.0], [10.0, 20.0]],
        "group_id": None,
        "description": "",
        "difficult": False,
        "shape_type": "rectangle",
        "flags": {},
        "attributes": {},
        "kie_linking": [],
    }


def test_new_shape_gets_top_level_identity():
    """Newly created shapes have a non-empty identity."""
    shape = Shape(shape_type="rectangle")
    assert shape.xanylabeling_shape_id
    assert shape.to_dict()["xanylabeling_shape_id"] == (
        shape.xanylabeling_shape_id
    )


def test_file_load_and_edit_preserve_identity():
    """Geometry and label edits do not change a loaded shape ID."""
    shape = Shape().load_from_dict(_shape_data())
    original = shape.xanylabeling_shape_id
    shape.label = "head"
    shape.points[0].setX(3.0)
    assert shape.xanylabeling_shape_id == original
    assert shape.to_dict()["xanylabeling_shape_id"] == original


def test_missing_legacy_identity_is_lazily_generated():
    """Legacy JSON gets an in-memory identity without changing its content."""
    data = _shape_data()
    data.pop("xanylabeling_shape_id")
    shape = Shape().load_from_dict(data)
    assert shape.xanylabeling_shape_id
    assert "xanylabeling_shape_id" in shape.to_dict()


def test_copy_for_new_object_regenerates_identity():
    """Copy/paste style creation gets a new ID while retaining annotation data."""
    shape = Shape().load_from_dict(_shape_data())
    copied = shape.copy_for_new_object()
    assert copied.xanylabeling_shape_id != shape.xanylabeling_shape_id
    assert copied.label == shape.label
    assert copied.points == shape.points


def test_load_without_preserving_identity_regenerates_identity():
    """External paste/import can explicitly create a new identity."""
    shape = Shape().load_from_dict(_shape_data(), preserve_shape_id=False)
    assert shape.xanylabeling_shape_id != "shape-from-json"


def test_shape_identity_is_not_stored_in_reserved_fields():
    """The identity remains separate from group and user metadata fields."""
    serialized = Shape().load_from_dict(_shape_data()).to_dict()
    assert serialized["group_id"] is None
    assert serialized["flags"] == {}
    assert serialized["attributes"] == {}
    assert serialized["kie_linking"] == []
    assert "xanylabeling_shape_id" not in serialized["flags"]
