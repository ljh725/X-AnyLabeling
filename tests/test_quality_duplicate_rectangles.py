"""Tests for the read-only duplicate rectangle L2 rule."""

import json

from anylabeling.views.labeling.widgets.inspector.quality.l2_rules import (
    FileContext,
    l2_13_duplicate_rectangles,
)
from anylabeling.views.labeling.widgets.inspector.quality.matching import (
    MatchingCfg,
)
from anylabeling.views.labeling.widgets.inspector.quality.quality_issue import (
    QcFile,
    QcShape,
)
from anylabeling.views.labeling.widgets.inspector.quality.threshold_profile import (
    RuleThreshold,
    ThresholdProfile,
)
from anylabeling.views.labeling.widgets.inspector.quality import geometry
from anylabeling.views.labeling.widgets.inspector.quality.report_writer import (
    run_quality_check,
    write_report_json,
    write_review_tsv,
)


def _shape(index, label="person", group_id=1, points=None):
    """Build a rectangle QA shape."""
    return QcShape(
        shape_index=index,
        label=label,
        shape_type="rectangle",
        points=points or [(0.0, 0.0), (10.0, 10.0)],
        group_id=group_id,
    )


def _run(shapes):
    """Run only the duplicate rectangle rule with default thresholds."""
    qc_file = QcFile("sample.json", "sample.jpg", 100, 100, shapes)
    profile = ThresholdProfile(
        "test", "v1", config={"duplicate_rectangles": {}}
    )
    rule = RuleThreshold(
        "L2-13",
        "duplicate_rectangles",
        True,
        "warning",
        "duplicate_rectangle_iou",
        "higher_is_worse",
    )
    return l2_13_duplicate_rectangles(
        FileContext(qc_file, MatchingCfg()), profile, MatchingCfg(), rule
    )


def test_same_group_duplicate_is_one_error_with_pair_evidence():
    """Same-group near-identical rectangles produce one error pair."""
    issues = _run([_shape(0), _shape(1)])
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].match["duplicate_shape_index"] == 1
    assert issues[0].metrics["duplicate_iou"] == 1.0


def test_unrelated_group_duplicate_is_warning_and_order_stable():
    """Different groups remain reviewable warnings with stable pair order."""
    issues = _run([_shape(1, group_id=2), _shape(0, group_id=3)])
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].shape_index == 0
    assert issues[0].match["duplicate_shape_index"] == 1


def test_different_labels_and_nested_person_head_are_excluded():
    """Different labels do not turn valid class nesting into duplicates."""
    issues = _run(
        [
            _shape(0, label="person", points=[(0, 0), (20, 20)]),
            _shape(1, label="head", points=[(1, 1), (10, 10)]),
        ]
    )
    assert issues == []


def test_invalid_and_non_rectangle_shapes_are_skipped():
    """Invalid geometry and non-rectangles remain delegated to L1 rules."""
    invalid = _shape(0, points=[(0, 0), (0, 0)])
    point = QcShape(1, "person", "point", [(0.0, 0.0)], 1)
    assert _run([invalid, point]) == []


def test_spatial_candidates_match_expected_overlapping_pairs():
    """Spatial bucketing returns the same qualifying pairs as an oracle."""
    shapes = [
        _shape(0, points=[(0, 0), (10, 10)]),
        _shape(1, points=[(0, 0), (10, 10)]),
        _shape(2, points=[(1000, 1000), (1010, 1010)]),
    ]
    issues = _run(shapes)
    expected = []
    for left_index in range(len(shapes)):
        for right_index in range(left_index + 1, len(shapes)):
            left_bbox = geometry.shape_bbox(
                shapes[left_index].shape_type, shapes[left_index].points
            )
            right_bbox = geometry.shape_bbox(
                shapes[right_index].shape_type, shapes[right_index].points
            )
            if geometry.iou(left_bbox, right_bbox) >= 0.95:
                expected.append((left_index, right_index))
    actual = [
        (issue.shape_index, issue.match["duplicate_shape_index"])
        for issue in issues
    ]
    assert actual == expected


def test_full_quality_report_and_review_tsv_include_duplicate_evidence(
    tmp_path,
):
    """The public quality driver emits one stable, read-only duplicate issue."""
    path = tmp_path / "sample.json"
    path.write_text(
        json.dumps(
            {
                "imagePath": "sample.jpg",
                "imageWidth": 100,
                "imageHeight": 100,
                "shapes": [
                    {
                        "label": "person",
                        "shape_type": "rectangle",
                        "points": [[0, 0], [10, 10]],
                        "group_id": 4,
                    },
                    {
                        "label": "person",
                        "shape_type": "rectangle",
                        "points": [[0, 0], [10, 10]],
                        "group_id": 4,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    report = run_quality_check([str(path)])
    duplicates = [
        issue
        for issue in report.issues
        if issue.rule_name == "duplicate_rectangles"
    ]
    assert len(duplicates) == 1
    assert duplicates[0].match["duplicate_shape_index"] == 1
    report_path = write_report_json(report, str(tmp_path / "report.json"))
    review_path = write_review_tsv(report, str(tmp_path / "review.tsv"))
    report_payload = json.loads(
        (tmp_path / "report.json").read_text(encoding="utf-8")
    )
    assert (
        report_payload["summary"]["issues_by_rule"]["duplicate_rectangles"]
        == 1
    )
    assert "duplicate_rectangles" in (tmp_path / "review.tsv").read_text(
        encoding="utf-8"
    )
    assert report_path.endswith("report.json")
    assert review_path.endswith("review.tsv")
