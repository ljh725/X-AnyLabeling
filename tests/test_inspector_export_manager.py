"""Tests for Inspector export diagnostics and resource boundaries."""

import json

from anylabeling.views.labeling.widgets.inspector.export_manager import (
    ExportManager,
)
from anylabeling.views.labeling.widgets.inspector.validation_engine import (
    Issue,
    ValidationReport,
)


def _write_annotation(path, image_path="sample.jpg"):
    """Write a minimal annotation JSON and return the path."""
    payload = {
        "imagePath": image_path,
        "shapes": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _report_for(paths, rule_name="label_rule"):
    """Build a validation report containing one issue per path."""
    return ValidationReport(
        total_files=len(paths),
        issues=[
            Issue(
                rule_name=rule_name,
                severity="error",
                message="issue",
                file_path=str(path),
                shape_index=0,
            )
            for path in paths
        ],
    )


def test_export_copies_json_and_associated_image(tmp_path):
    """Export should copy both JSON and the image from imagePath."""
    labels_dir = tmp_path / "labels"
    labels_dir.mkdir()
    json_path = _write_annotation(labels_dir / "sample.json")
    image_path = labels_dir / "sample.jpg"
    image_path.write_bytes(b"image")

    out_dir = tmp_path / "out"
    result = ExportManager().export(_report_for([json_path]), str(out_dir))

    assert result.copied_files == 1
    assert result.copied_images == 1
    assert not result.errors
    assert not result.warnings
    assert (out_dir / "label_rule" / "sample.json").is_file()
    assert (out_dir / "label_rule" / "sample.jpg").is_file()


def test_export_reports_missing_associated_image(tmp_path):
    """Missing images should be reported as warnings, not swallowed."""
    json_path = _write_annotation(tmp_path / "missing_image.json")

    result = ExportManager().export(
        _report_for([json_path]),
        str(tmp_path / "out"),
    )

    assert result.copied_files == 1
    assert result.copied_images == 0
    assert not result.errors
    assert len(result.warnings) == 1
    assert str(json_path) == result.warnings[0][0]
    assert "Associated image not found" in result.warnings[0][1]


def test_export_reports_invalid_json_during_image_lookup(tmp_path):
    """Invalid JSON should still copy but produce an image lookup warning."""
    json_path = tmp_path / "bad.json"
    json_path.write_text("{bad", encoding="utf-8")

    result = ExportManager().export(
        _report_for([json_path]),
        str(tmp_path / "out"),
    )

    assert result.copied_files == 1
    assert not result.errors
    assert len(result.warnings) == 1
    assert "invalid JSON" in result.warnings[0][1]
    assert (tmp_path / "out" / "label_rule" / "bad.json").is_file()


def test_export_records_missing_source_as_error(tmp_path):
    """Missing source JSON should be an export error."""
    json_path = tmp_path / "does_not_exist.json"

    result = ExportManager().export(
        _report_for([json_path]),
        str(tmp_path / "out"),
    )

    assert result.copied_files == 0
    assert len(result.errors) == 1
    assert str(json_path) == result.errors[0][0]
    assert "Source not found" in result.errors[0][1]


def test_export_can_cancel_before_copying(tmp_path):
    """Cancellation callback should stop before the next copy task."""
    json_path = _write_annotation(tmp_path / "sample.json")

    result = ExportManager().export(
        _report_for([json_path]),
        str(tmp_path / "out"),
        cancel_callback=lambda: True,
    )

    assert result.cancelled is True
    assert result.copied_files == 0
    assert not (tmp_path / "out" / "label_rule" / "sample.json").exists()


def test_export_progress_uses_file_copy_task_total(tmp_path):
    """Progress should report file-copy tasks, not only rule folders."""
    first = _write_annotation(tmp_path / "first.json", "first.jpg")
    second = _write_annotation(tmp_path / "second.json", "second.jpg")
    events = []

    result = ExportManager().export(
        _report_for([first, second]),
        str(tmp_path / "out"),
        progress_callback=lambda current, total, name: events.append(
            (current, total, name)
        ),
    )

    assert result.total_copy_tasks == 2
    assert events[0] == (0, 2, "")
    assert events[-1][0:2] == (2, 2)
