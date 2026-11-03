from anylabeling.services.dense_review.models import (
    LabelRule,
    ReviewRules,
)
from anylabeling.services.dense_review.signatures import (
    content_hash,
    shape_category_signature,
    shape_geometry_signature,
)

from .conftest import make_shape


def _rules(**box_rules):
    return ReviewRules(
        rules={
            label: LabelRule(label=label, box_rule=rule)
            for label, rule in box_rules.items()
        }
    )


def test_rectangle_vertex_order_and_numeric_spelling_are_equivalent():
    shape = make_shape("a", "A", (10, 20, 30, 40))
    reordered = make_shape("a", "A", (10, 20, 30, 40))
    reordered.set_points_raw(
        [(30, 40), (10, 20), (30, 20), (10, 40)]
    )
    float_shape = make_shape("a", "A", (10, 20, 30, 40))
    float_shape.set_points_raw(
        [(10.0, 20.0), (30.0, 20.0), (30.0, 40.0), (10.0, 40.0)]
    )
    rules = _rules(A="visible")
    for other in (reordered, float_shape):
        assert shape_geometry_signature(
            shape, rules
        ) == shape_geometry_signature(other, rules)
        assert shape_category_signature(
            shape, rules
        ) == shape_category_signature(other, rules)


def test_tiny_coordinate_change_is_detected():
    shape = make_shape("a", "A", (10, 20, 30, 40))
    moved = make_shape("a", "A", (10, 20, 30.01, 40))
    rules = _rules(A="visible")
    assert shape_geometry_signature(
        shape, rules
    ) != shape_geometry_signature(moved, rules)


def test_unknown_box_rule_includes_label_in_geometry_signature():
    left = make_shape("a", "A", (10, 20, 30, 40))
    right = make_shape("b", "C", (10, 20, 30, 40))
    unknown = ReviewRules()
    known = _rules(A="visible", C="visible")
    assert shape_geometry_signature(
        left, unknown
    ) != shape_geometry_signature(right, unknown)
    assert shape_geometry_signature(
        left, known
    ) == shape_geometry_signature(right, known)
    assert shape_category_signature(
        left, known
    ) != shape_category_signature(right, known)


def test_category_note_changes_category_only():
    shape = make_shape("a", "A", (10, 20, 30, 40))
    first = ReviewRules(
        rules={"A": LabelRule(label="A", box_rule="visible", note="举手")}
    )
    second = ReviewRules(
        rules={"A": LabelRule(label="A", box_rule="visible", note="写字")}
    )
    assert shape_geometry_signature(
        shape, first
    ) == shape_geometry_signature(shape, second)
    assert shape_category_signature(
        shape, first
    ) != shape_category_signature(shape, second)


def test_box_rule_change_changes_geometry_signature():
    shape = make_shape("a", "A", (10, 20, 30, 40))
    assert shape_geometry_signature(
        shape, _rules(A="visible")
    ) != shape_geometry_signature(shape, _rules(A="full"))


def test_content_hash_ignores_visibility_and_lock_but_tracks_content():
    shape = make_shape("a", "A", (10, 20, 30, 40))
    baseline = content_hash([shape])
    shape.locked = True
    shape.visible = False
    assert content_hash([shape]) == baseline
    shape.attributes = {"pose": "standing"}
    assert content_hash([shape]) != baseline
    changed = make_shape("a", "A", (10, 20, 31, 40))
    assert content_hash([changed]) != baseline
