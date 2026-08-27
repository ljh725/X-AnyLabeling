"""Focused acceptance tests for v2 metrics and bundle contracts."""

import json
from pathlib import Path

from anylabeling.services.behavior_analytics import (
    EventEnvelope,
    calculate_statistics,
    export_analysis_bundle,
    read_events,
)

FIXTURES = Path("tests/fixtures/behavior_analytics")


def test_v2_fixture_exposes_quality_and_layered_metrics():
    """A complete v2 fixture produces all measurement layers."""
    events, quality = read_events([FIXTURES / "behavior_analytics_v2.jsonl"])
    result = calculate_statistics(events)

    assert quality.metadata["input_schema_versions"] == [2]
    assert result["action_metrics"]
    assert result["episode_metrics"]
    assert result["image_metrics"]
    assert result["rework_metrics"]
    assert (
        "action_duration_coverage" in result["measurement_quality"]["metrics"]
    )


def test_v2_bundle_adds_quality_image_and_rework_files(tmp_path):
    """The v2 bundle keeps legacy files and publishes new fixed files."""
    events, quality = read_events([FIXTURES / "behavior_analytics_v2.jsonl"])
    target = export_analysis_bundle(
        tmp_path / "bundle", events, quality=quality
    )

    assert (target / "image_metrics.csv").exists()
    assert (target / "rework_metrics.csv").exists()
    assert (target / "measurement_quality.json").exists()
    manifest = json.loads(
        (target / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["bundle_schema_version"] == "2.0"
    for filename, metadata in manifest["files"].items():
        assert metadata["bytes"] == (target / filename).stat().st_size


def test_v2_privacy_sanitizes_nested_geometry_and_paths(tmp_path):
    """Nested context and net-change payloads never leak raw geometry."""
    event = EventEnvelope.from_mapping(
        {
            "schema_version": 2,
            "event_id": "privacy-1",
            "event_type": "action_span",
            "occurred_at_utc": "2026-08-21T01:00:00.000Z",
            "local_date": "2026-08-21",
            "timezone_offset": "+08:00",
            "monotonic_ms": 100,
            "app_session_id": "app-1",
            "project_session_id": "project-1",
            "project_id": "project-1",
            "feature_state_version": 1,
            "input_source": "mouse",
            "result": "success",
            "action_id": "privacy-action",
            "action_phase": "committed",
            "started_monotonic_ms": 10,
            "ended_monotonic_ms": 100,
            "context": {"points": [[0, 0]], "absolute_path": "C:/secret"},
            "net_change_summary": {"points": [[0, 0]], "changed": True},
            "payload": {"action": "adjust"},
        }
    )
    target = export_analysis_bundle(tmp_path / "bundle", [event])
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in target.iterdir()
    )
    assert "absolute_path" not in text
    assert "points" not in text
