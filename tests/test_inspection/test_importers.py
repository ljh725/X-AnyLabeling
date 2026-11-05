import json
from pathlib import Path

from anylabeling.services.inspection.importers import (
    export_report,
    import_legacy_report,
)
from anylabeling.services.inspection.manifest import build_manifest
from anylabeling.services.inspection.models import RunScope
from anylabeling.services.inspection.profiles import default_profiles
from anylabeling.services.inspection.runner import InspectionRunner


def _manifest(tmp_path):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"fake")
    (tmp_path / "a.json").write_text(
        json.dumps(
            {
                "version": "4.2.1",
                "imageWidth": 100,
                "imageHeight": 80,
                "imagePath": "a.jpg",
                "shapes": [
                    {
                        "label": "person",
                        "shape_type": "rectangle",
                        "points": [[0, 0], [10, 10]],
                        "xanylabeling_shape_id": "id1",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return build_manifest(str(tmp_path))


def test_import_tsv_resolves_and_reports_ambiguity(tmp_path):
    manifest = _manifest(tmp_path)
    path = tmp_path / "review.tsv"
    path.write_text(
        "issue_id\tfile_path\tshape_index\tshape_id\trule_name\tseverity\tmessage\tlabel\tgroup_id\n"
        "i1\ta.jpg\t0\tid1\tdup\twarning\toverlap\tperson\t\n"
        "i2\tunknown.jpg\t0\tid9\tdup\twarning\tmissing\tperson\t\n"
        "\t\t\t\t\t\t\t\t\n",
        encoding="utf-8",
    )
    result = import_legacy_report(str(path), manifest=manifest)
    assert len(result.issues) == 2
    assert result.issues[0].location.relative_path == "a.jpg"
    assert result.issues[0].location.ambiguous is False
    assert result.issues[1].location.ambiguous is True
    assert result.ambiguous


def test_import_json_list_and_missing_path(tmp_path):
    manifest = _manifest(tmp_path)
    path = tmp_path / "issues.json"
    path.write_text(
        json.dumps(
            [
                {
                    "file_path": "a.jpg",
                    "shape_id": "id1",
                    "rule_id": "dup",
                    "severity": "error",
                    "message": "x",
                },
                {"rule_id": "dup", "message": "no path"},
            ]
        ),
        encoding="utf-8",
    )
    result = import_legacy_report(str(path), manifest=manifest)
    assert len(result.issues) == 1
    assert len(result.errors) == 1


def test_export_complete_report_and_lossy_tsv(tmp_path):
    manifest = _manifest(tmp_path)
    report = InspectionRunner().run(
        manifest, default_profiles()[0], RunScope.DATASET
    )
    json_path = tmp_path / "out" / "report.json"
    tsv_path = tmp_path / "out" / "report.tsv"
    export_report(report, str(json_path), str(tsv_path))
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "inspection-report.v1"
    assert payload["exported_at"]
    assert tsv_path.read_text(encoding="utf-8").startswith("issue_id")


def test_native_report_round_trip_preserves_issue_identity(tmp_path):
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
    report = InspectionRunner().run(
        manifest, default_profiles()[0], RunScope.DATASET
    )
    assert report.issues
    json_path = tmp_path / "report.json"
    export_report(report, str(json_path))
    imported = import_legacy_report(str(json_path), manifest=manifest)
    assert len(imported.issues) == 1
    source = report.issues[0]
    restored = imported.issues[0]
    assert restored.issue_id == source.issue_id
    assert restored.family_key == source.family_key
    assert restored.location.object_ids == source.location.object_ids
    assert restored.verification is source.verification


def test_native_report_round_trip_keeps_every_source_and_context(tmp_path):
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
                        "group_id": 1,
                        "xanylabeling_shape_id": "id1",
                    },
                    {
                        "label": "person",
                        "shape_type": "rectangle",
                        "points": [[0, 0], [10, 10]],
                        "group_id": 1,
                        "xanylabeling_shape_id": "id2",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = build_manifest(str(tmp_path))
    profile = default_profiles()[0]
    profile = type(profile).from_dict(
        {
            **profile.to_dict(),
            "rules": [
                {"rule_id": "duplicate_boxes"},
                {"rule_id": "legacy_same_group_duplicate"},
            ],
        }
    )
    report = InspectionRunner().run(manifest, profile, RunScope.DATASET)
    assert report.issues
    issue = report.issues[0]
    assert {item.rule_id for item in issue.evidence} == {
        "duplicate_boxes",
        "legacy_same_group_duplicate",
    }
    json_path = tmp_path / "full-report.json"
    export_report(report, str(json_path))
    imported = import_legacy_report(str(json_path), manifest=manifest)
    assert imported.format == "native-report"
    assert imported.lossy is False
    assert imported.context["run_id"] == report.run_id
    assert imported.context["profile_id"] == profile.profile_id
    restored = imported.issues[0]
    assert len(restored.evidence) == 2
    versions = {
        item.rule_id: item.implementation_version
        for item in restored.evidence
    }
    assert versions == {"duplicate_boxes": "1.0.0", "legacy_same_group_duplicate": "l2-13.v1"}
    original_metrics = {
        item.rule_id: dict(item.metrics) for item in issue.evidence
    }
    restored_metrics = {
        item.rule_id: dict(item.metrics) for item in restored.evidence
    }
    assert restored_metrics == original_metrics
    assert restored.location.region == issue.location.region
    assert restored.location.group_id == issue.location.group_id
    assert restored.decision is issue.decision
    assert restored.verification is issue.verification
    assert [dict(item) for item in restored.history] == [
        dict(item) for item in issue.history
    ]


def test_unknown_report_schema_is_not_downgraded_to_rows(tmp_path):
    path = tmp_path / "future.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "inspection-report.v9",
                "run_id": "future",
                "issues": [
                    {"file_path": "a.jpg", "rule_name": "dup", "message": "x"}
                ],
            }
        ),
        encoding="utf-8",
    )
    result = import_legacy_report(str(path))
    assert result.format == "legacy-rows"
    assert result.issues == ()
    assert result.errors
    assert "无法核验" in result.errors[0]["error"]


def test_tsv_import_is_marked_lossy(tmp_path):
    path = tmp_path / "legacy.tsv"
    path.write_text(
        "issue_id\tfile_path\tshape_index\tshape_id\trule_name\tseverity\tmessage\tlabel\tgroup_id\n"
        "i1\ta.jpg\t0\tid1\tdup\twarning\toverlap\tperson\t\n",
        encoding="utf-8",
    )
    result = import_legacy_report(str(path))
    assert result.lossy is True
    assert result.warnings
