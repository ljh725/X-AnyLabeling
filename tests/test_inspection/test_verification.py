import json
from pathlib import Path

from dataclasses import replace

from anylabeling.services.inspection.manifest import (
    build_manifest,
    memory_file_snapshot,
)
from anylabeling.services.inspection.models import RunScope
from anylabeling.services.inspection.profiles import (
    build_default_catalog,
    default_profiles,
)
from anylabeling.services.inspection.runner import InspectionRunner
from anylabeling.services.inspection.verification import (
    verify_report_context,
)


def _report_and_manifest(tmp_path):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"fake")
    annotation = tmp_path / "a.json"
    annotation.write_text(
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
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = build_manifest(str(tmp_path))
    report = InspectionRunner().run(
        manifest, default_profiles()[0], RunScope.DATASET
    )
    return report, manifest, annotation


def _memory(tmp_path, points, unsaved=True):
    return memory_file_snapshot(
        str(tmp_path / "a.jpg"),
        "a.jpg",
        [
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": points,
                "xanylabeling_shape_id": "id1",
            }
        ],
        image_width=100,
        image_height=80,
        unsaved=unsaved,
    )


def test_unchanged_report_context_is_current(tmp_path):
    report, manifest, _ = _report_and_manifest(tmp_path)
    verification = verify_report_context(
        report,
        manifest,
        build_default_catalog(),
        str(tmp_path),
        "",
        default_profiles()[0],
    )
    assert verification.current is True
    assert verification.reasons == ()


def test_changed_annotation_marks_file_stale(tmp_path):
    report, manifest, annotation = _report_and_manifest(tmp_path)
    payload = json.loads(annotation.read_text(encoding="utf-8"))
    payload["shapes"][0]["points"] = [[1, 1], [11, 11]]
    annotation.write_text(json.dumps(payload), encoding="utf-8")
    verification = verify_report_context(
        report,
        manifest,
        build_default_catalog(),
        str(tmp_path),
        "",
        default_profiles()[0],
    )
    assert verification.current is False
    assert "a.jpg" in verification.stale_files
    assert verification.reasons


def test_changed_profile_marks_config_stale(tmp_path):
    report, manifest, _ = _report_and_manifest(tmp_path)
    changed = replace(default_profiles()[0], stage="in_progress")
    verification = verify_report_context(
        report,
        manifest,
        build_default_catalog(),
        str(tmp_path),
        "",
        changed,
    )
    assert verification.current is False
    assert verification.config_changed is True


def test_matching_memory_snapshot_keeps_context_current(tmp_path):
    report, manifest, _ = _report_and_manifest(tmp_path)
    verification = verify_report_context(
        report,
        manifest,
        build_default_catalog(),
        str(tmp_path),
        "",
        default_profiles()[0],
        memory_files={"a.jpg": _memory(tmp_path, [[0, 0], [10, 10]])},
    )
    assert verification.current is True
    assert verification.pending_files == ()


def test_missing_identity_does_not_cause_false_pending(tmp_path):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"fake")
    annotation = tmp_path / "a.json"
    annotation.write_text(
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
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = build_manifest(str(tmp_path))
    report = InspectionRunner().run(
        manifest, default_profiles()[0], RunScope.DATASET
    )
    memory = memory_file_snapshot(
        str(image),
        "a.jpg",
        [
            {
                "label": "person",
                "shape_type": "rectangle",
                "points": [[0, 0], [10, 10]],
            }
        ],
        image_width=100,
        image_height=80,
    )
    verification = verify_report_context(
        report,
        manifest,
        build_default_catalog(),
        str(tmp_path),
        "",
        default_profiles()[0],
        memory_files={"a.jpg": memory},
    )
    assert verification.current is True


def test_unsaved_memory_change_is_pending_not_stale(tmp_path):
    report, manifest, _ = _report_and_manifest(tmp_path)
    verification = verify_report_context(
        report,
        manifest,
        build_default_catalog(),
        str(tmp_path),
        "",
        default_profiles()[0],
        memory_files={"a.jpg": _memory(tmp_path, [[5, 5], [31, 31]])},
    )
    assert verification.current is False
    assert verification.pending_files == ("a.jpg",)
    assert verification.stale_files == ()


def test_disk_change_still_wins_when_memory_matches_report(tmp_path):
    report, manifest, annotation = _report_and_manifest(tmp_path)
    payload = json.loads(annotation.read_text(encoding="utf-8"))
    payload["shapes"][0]["points"] = [[1, 1], [11, 11]]
    annotation.write_text(json.dumps(payload), encoding="utf-8")
    verification = verify_report_context(
        report,
        manifest,
        build_default_catalog(),
        str(tmp_path),
        "",
        default_profiles()[0],
        memory_files={"a.jpg": _memory(tmp_path, [[0, 0], [10, 10]])},
    )
    assert verification.current is False
    assert verification.stale_files == ("a.jpg",)


def test_missing_manifest_is_explicit(tmp_path):
    report, _, _ = _report_and_manifest(tmp_path)
    verification = verify_report_context(
        report,
        None,
        build_default_catalog(),
        str(tmp_path),
        "",
        default_profiles()[0],
    )
    assert verification.current is False
    assert verification.missing_manifest is True
