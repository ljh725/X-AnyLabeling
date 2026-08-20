"""Tests for the fixed-format analysis bundle export."""

import hashlib
import json
from dataclasses import replace

import pytest

from anylabeling.services.behavior_analytics import (
    EventEnvelope,
    EventType,
    export_analysis_bundle,
)


def _event(event_id, action, duration_ms):
    """Create a valid episode event."""
    return EventEnvelope.from_mapping(
        {
            "schema_version": 1,
            "event_id": event_id,
            "event_type": EventType.ACTION_SPAN.value,
            "occurred_at_utc": f"2026-08-20T00:00:0{event_id}.000Z",
            "local_date": "2026-08-20",
            "timezone_offset": "+08:00",
            "monotonic_ms": int(event_id) * 100,
            "app_session_id": "app-1",
            "project_session_id": "project-session-1",
            "project_id": "project-1",
            "feature_state_version": 1,
            "input_source": "mouse",
            "result": "success",
            "image_id": "image-1",
            "shape_id": "shape-1",
            "object_episode_id": "episode-1",
            "duration_ms": duration_ms,
            "payload": {"action": action},
        }
    )


def test_bundle_has_fixed_files_and_manifest_hashes(tmp_path):
    """All required files are published with verifiable hashes."""
    target = export_analysis_bundle(
        tmp_path / "bundle",
        [
            replace(
                _event("1", "select", 100),
                payload={
                    "action": "select",
                    "private_path": "C:\\private\\image.jpg",
                },
            ),
            _event("2", "adjust", 300),
        ],
    )
    expected = {
        "manifest.json",
        "summary.json",
        "action_counts.csv",
        "action_durations.csv",
        "transitions.csv",
        "common_sequences.csv",
        "object_episodes.csv",
        "feature_comparisons.csv",
        "representative_traces.jsonl",
    }
    assert {path.name for path in target.iterdir()} == expected
    manifest = json.loads(
        (target / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["privacy_fields_removed"] == 1
    assert "private_path" not in (
        target / "representative_traces.jsonl"
    ).read_text(encoding="utf-8")
    for filename, metadata in manifest["files"].items():
        path = target / filename
        assert metadata["bytes"] == path.stat().st_size
        assert (
            metadata["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        )


def test_bundle_is_bounded_and_does_not_overwrite_existing_output(tmp_path):
    """Trace limits and atomic no-overwrite behavior are enforced."""
    target = tmp_path / "bundle"
    events = [_event(str(index), "adjust", index) for index in range(1, 5)]
    export_analysis_bundle(target, events, representative_trace_limit=1)
    traces = (
        (target / "representative_traces.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(traces) == 1
    with pytest.raises(FileExistsError):
        export_analysis_bundle(target, events)
