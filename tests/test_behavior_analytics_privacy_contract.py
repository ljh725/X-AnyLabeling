"""End-to-end privacy contract tests for recording and export layers."""

import json
from pathlib import Path

from anylabeling.services.behavior_analytics import (
    EventEnvelope,
    LocalEventRecorder,
    export_analysis_bundle,
)


def _private_event() -> EventEnvelope:
    """Build one event containing representative forbidden values."""
    return EventEnvelope.from_mapping(
        {
            "schema_version": 2,
            "event_id": "privacy-contract-1",
            "event_type": "action_span",
            "occurred_at_utc": "2026-08-22T01:00:00.000Z",
            "local_date": "2026-08-22",
            "timezone_offset": "+08:00",
            "monotonic_ms": 100,
            "app_session_id": "app-privacy",
            "project_session_id": "project-privacy",
            "project_id": "project-anon",
            "feature_state_version": 1,
            "input_source": "mouse",
            "result": "success",
            "image_id": "image-anon",
            "shape_id": "shape-anon",
            "object_episode_id": "episode-anon",
            "action_id": "action-privacy",
            "action_phase": "committed",
            "started_monotonic_ms": 10,
            "ended_monotonic_ms": 100,
            "context": {
                "shape_type": "rectangle",
                "points": [[0, 0], [10, 10]],
                "absolute_path": "C:/private/image.jpg",
            },
            "net_change_summary": {
                "width_delta": 2,
                "points": [[0, 0]],
                "free_text": "private note",
            },
            "payload": {
                "action": "geometry_adjust",
                "start_summary": {
                    "monotonic_ms": 10,
                    "points": [[0, 0]],
                },
                "end_summary": {
                    "monotonic_ms": 100,
                    "pixels": "raw-pixels",
                },
                "free_text": "private payload",
                "absolute_path": "D:/secret/image.jpg",
            },
        }
    )


def test_recording_and_export_apply_the_same_privacy_count(tmp_path):
    """Neither layer stores forbidden values and both report removals."""
    event = _private_event()
    recorder = LocalEventRecorder(tmp_path / "recording", enabled=True)
    assert recorder.emit(event)
    assert recorder.flush(timeout=1.0)
    assert recorder.close(timeout=1.0)
    recorded = next((tmp_path / "recording").rglob("*.jsonl"))
    recorded_text = recorded.read_text(encoding="utf-8")
    assert recorder.health.privacy_fields_removed == 8
    for forbidden in (
        "points",
        "raw-pixels",
        "private note",
        "private payload",
        "C:/private",
        "D:/secret",
    ):
        assert forbidden not in recorded_text

    target = export_analysis_bundle(tmp_path / "bundle", [event])
    manifest = json.loads(
        (target / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["privacy_fields_removed"] == 8
    exported_text = "\n".join(
        path.read_text(encoding="utf-8") for path in target.iterdir()
    )
    for forbidden in (
        "points",
        "raw-pixels",
        "private note",
        "private payload",
        "C:/private",
        "D:/secret",
    ):
        assert forbidden not in exported_text

