import json

from anylabeling.services.inspection.handoff import (
    build_status,
    dense_review_available,
    handoff_payload,
    issue_context,
    spatial_omission_status,
)
from anylabeling.services.inspection.manifest import build_manifest
from anylabeling.services.inspection.models import RunScope
from anylabeling.services.inspection.profiles import default_profiles
from anylabeling.services.inspection.runner import InspectionRunner


def _report(tmp_path):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"fake")
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
                    },
                    {
                        "label": "person",
                        "shape_type": "rectangle",
                        "points": [[0, 0], [10, 10]],
                        "xanylabeling_shape_id": "id2",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = build_manifest(str(tmp_path))
    return InspectionRunner().run(
        manifest, default_profiles()[0], RunScope.DATASET
    )


def test_dense_review_is_available():
    assert dense_review_available() is True
    assert spatial_omission_status()["state"] == "available"


def test_status_separates_issue_handling_from_other_dimensions(tmp_path):
    report = _report(tmp_path)
    issue = report.issues[0]
    status = build_status(
        report,
        {issue.family_key: {"decision": "false_positive"}},
        checked=None,
    )
    assert status.execution["state"] == "completed"
    assert status.issue_handling["false_positive"] == 1
    assert status.object_review["state"] == "available"
    assert status.spatial_omission["state"] == "available"
    assert status.formal_acceptance["state"] == "unchanged"
    assert any("不能证明" in note for note in status.notes)


def test_issue_context_and_handoff_keep_rule_evidence(tmp_path):
    report = _report(tmp_path)
    issue = report.issues[0]
    context = issue_context(issue)
    assert context["object_ids"] == ["id1", "id2"]
    assert context["rules"][0]["rule_id"] == "duplicate_boxes"
    payload = handoff_payload(issue)
    assert payload["available"] is True
    assert payload["protocol"] == "dense-review.v1"
