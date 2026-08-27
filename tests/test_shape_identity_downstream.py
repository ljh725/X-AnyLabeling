"""Contracts for downstream consumers of persistent Shape identities."""

import csv
import json

from anylabeling.views.labeling.widgets.inspector.quality import (
    load_threshold_profile,
    run_quality_check,
    write_report_json,
    write_review_tsv,
)
from anylabeling.views.labeling.widgets.inspector.quality.quality_review_queue import (
    QualityReviewQueue,
)


def _target_shape() -> dict:
    """Return a stable-ID Shape that deterministically fails an L1 rule."""
    return {
        "xanylabeling_shape_id": "persistent-target",
        "label": "",
        "shape_type": "rectangle",
        "points": [[10, 10], [20, 20]],
    }


def _valid_shape() -> dict:
    """Return an unrelated Shape inserted to change array ordinals."""
    return {
        "xanylabeling_shape_id": "unrelated-shape",
        "label": "person",
        "shape_type": "rectangle",
        "group_id": 1,
        "points": [[100, 100], [300, 500]],
    }


def _write_annotation(path, shapes: list[dict]) -> None:
    """Write one quality-check annotation fixture."""
    path.write_text(
        json.dumps(
            {
                "imagePath": "a.jpg",
                "imageWidth": 1000,
                "imageHeight": 1000,
                "shapes": shapes,
            }
        ),
        encoding="utf-8",
    )


def _target_issue_map(report) -> dict[tuple[str, str], str]:
    """Return stable issue IDs for the target Shape keyed by rule and metric."""
    return {
        (
            issue.rule_id,
            issue.primary_metric.name if issue.primary_metric else "",
        ): issue.issue_id()
        for issue in report.issues
        if issue.shape_id == "persistent-target"
    }


def test_quality_issue_identity_survives_shape_reordering(tmp_path):
    """Persistent review identity does not depend on a Shape array index."""
    annotation = tmp_path / "annotation.json"
    profile = load_threshold_profile()
    _write_annotation(annotation, [_target_shape()])
    before = run_quality_check([str(annotation)], profile=profile)
    before_ids = _target_issue_map(before)
    before_indices = {
        issue.shape_index
        for issue in before.issues
        if issue.shape_id == "persistent-target"
    }

    _write_annotation(annotation, [_valid_shape(), _target_shape()])
    after = run_quality_check([str(annotation)], profile=profile)
    after_ids = _target_issue_map(after)
    after_indices = {
        issue.shape_index
        for issue in after.issues
        if issue.shape_id == "persistent-target"
    }

    assert before_ids
    assert before_ids == after_ids
    assert before_indices == {0}
    assert after_indices == {1}


def test_quality_outputs_and_feedback_preserve_shape_id(tmp_path):
    """Report, review TSV, queue, and feedback retain the stable Shape key."""
    annotation = tmp_path / "annotation.json"
    report_path = tmp_path / "report.json"
    review_path = tmp_path / "review.tsv"
    feedback_path = tmp_path / "feedback.tsv"
    _write_annotation(annotation, [_target_shape()])
    report = run_quality_check(
        [str(annotation)], profile=load_threshold_profile()
    )

    write_report_json(report, str(report_path))
    write_review_tsv(report, str(review_path))
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    with review_path.open("r", encoding="utf-8", newline="") as handle:
        review_rows = list(csv.DictReader(handle, delimiter="\t"))
    queue = QualityReviewQueue()
    queue.load_report(str(report_path))
    queue.write_feedback(str(feedback_path))
    with feedback_path.open("r", encoding="utf-8", newline="") as handle:
        feedback_rows = list(csv.DictReader(handle, delimiter="\t"))

    persisted_issues = [
        issue for issue in payload["issues"] if issue["shape_id"]
    ]
    persisted_review_rows = [row for row in review_rows if row["shape_id"]]
    persisted_queue_items = [item for item in queue if item.shape_id]
    persisted_feedback_rows = [row for row in feedback_rows if row["shape_id"]]
    assert persisted_issues
    assert persisted_review_rows
    assert persisted_queue_items
    assert persisted_feedback_rows
    assert all(
        issue["shape_id"] == "persistent-target" for issue in persisted_issues
    )
    assert all(
        row["shape_id"] == "persistent-target" for row in persisted_review_rows
    )
    assert all(
        item.shape_id == "persistent-target" for item in persisted_queue_items
    )
    assert all(
        row["shape_id"] == "persistent-target"
        for row in persisted_feedback_rows
    )
