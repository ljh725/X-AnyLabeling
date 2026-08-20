"""Tests for the semantic telemetry coordinator."""

import json

from anylabeling.services.behavior_analytics import (
    BehaviorTelemetry,
    FeatureState,
    LocalEventRecorder,
)


def test_telemetry_emits_snapshot_state_and_a_b_a_events(tmp_path):
    """One coordinator preserves feature versions and object identities."""
    recorder = LocalEventRecorder(tmp_path, enabled=True)
    telemetry = BehaviorTelemetry(str(tmp_path), recorder)
    telemetry.start_project({"rectangle_refinement": FeatureState(True, True)})
    telemetry.enter_image(str(tmp_path / "image-a.jpg"))
    first_a = telemetry.select_shape("shape-a")
    telemetry.select_shape("shape-b")
    second_a = telemetry.select_shape("shape-a")
    telemetry.action(
        "action_span",
        input_source="mouse",
        result="success",
        payload={"action": "rectangle_adjust"},
        duration_ms=250,
    )
    telemetry.close_project()
    assert recorder.flush(timeout=1.0) is True
    assert recorder.close(timeout=1.0) is True
    path = tmp_path / "events" / "events-2026-08.jsonl"
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    selected = [
        (row["shape_id"], row["object_episode_id"])
        for row in rows
        if row["event_type"] == "shape_selected"
    ]
    assert selected[0][0] == selected[2][0] == "shape-a"
    assert first_a != second_a
    assert rows[1]["event_type"] == "feature_state_snapshot"
    assert rows[1]["feature_state_version"] == 1
    assert any(row["event_type"] == "project_session_ended" for row in rows)
