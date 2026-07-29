"""Tests for the shared label-to-shape-type contract."""

from anylabeling.views.labeling.label_shape_contract import (
    DEFAULT_POINT_LABEL_SET,
    DEFAULT_POINT_LABELS,
    DEFAULT_RECTANGLE_LABEL_SET,
    DEFAULT_RECTANGLE_LABELS,
    DEFAULT_SHARED_LABELS,
    POINT_SHAPE_TYPE,
    RECTANGLE_SHAPE_TYPE,
    expected_shape_type_for_label,
    labels_to_csv,
)
from anylabeling.views.labeling.widgets.inspector import rule_config_widget
from anylabeling.views.labeling.widgets.inspector.quality import l1_rules
from anylabeling.views.labeling.widgets.inspector.validation_engine import (
    GroupIdKeypointIntegrity,
)


def test_default_shape_type_lookup_uses_shared_contract():
    """Default labels should map to their shared shape type."""
    assert expected_shape_type_for_label("person") == RECTANGLE_SHAPE_TYPE
    assert expected_shape_type_for_label("head") == RECTANGLE_SHAPE_TYPE
    assert expected_shape_type_for_label("nose") == POINT_SHAPE_TYPE
    assert expected_shape_type_for_label("unknown") is None


def test_l1_rules_use_shared_label_sets():
    """L1 rules should not carry a separate copy of label bindings."""
    assert l1_rules.RECTANGLE_LABELS == DEFAULT_RECTANGLE_LABEL_SET
    assert l1_rules.POINT_LABELS == DEFAULT_POINT_LABEL_SET


def test_inspector_defaults_use_shared_contract_order():
    """Inspector rule defaults should render the shared contract."""
    assert rule_config_widget.DEFAULT_RECT_LABELS == labels_to_csv(
        DEFAULT_RECTANGLE_LABELS
    )
    assert rule_config_widget.DEFAULT_POINT_LABELS == labels_to_csv(
        DEFAULT_POINT_LABELS
    )
    assert rule_config_widget.DEFAULT_SHARED_LABELS == labels_to_csv(
        DEFAULT_SHARED_LABELS
    )


def test_keypoint_integrity_uses_shared_point_labels():
    """Inspector group integrity should use the shared point label set."""
    assert GroupIdKeypointIntegrity.COCO_KEYPOINTS == DEFAULT_POINT_LABEL_SET
