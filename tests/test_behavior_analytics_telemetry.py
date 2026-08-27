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
    path = next((tmp_path / "events").glob("events-*.jsonl"))
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


def test_select_shape_without_image_visit_does_not_interrupt_work(tmp_path):
    """A missing UI lifecycle event must not raise into annotation work."""
    recorder = LocalEventRecorder(tmp_path, enabled=True)
    telemetry = BehaviorTelemetry(str(tmp_path), recorder)
    telemetry.start_project()

    assert telemetry.select_shape("shape-a") is None

    telemetry.shutdown()
    path = next((tmp_path / "events").glob("events-*.jsonl"))
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert not any(row["event_type"] == "shape_selected" for row in rows)

def test_burst_boundaries_close_on_selection_focus_image_and_shutdown(tmp_path):
    """High-frequency inputs close at every semantic lifecycle boundary."""
    recorder = LocalEventRecorder(tmp_path / "logs", enabled=True)
    telemetry = BehaviorTelemetry(str(tmp_path / "project"), recorder)
    telemetry.start_project()
    telemetry.enter_image(str(tmp_path / "image-a.jpg"))
    telemetry.select_shape("shape-a")

    telemetry.record_burst("selection_pan", input_source="mouse", monotonic_ms=10)
    telemetry.select_shape("shape-b")
    telemetry.record_burst("focus_pan", input_source="mouse", monotonic_ms=20)
    telemetry.focus_changed(False)
    telemetry.record_burst("image_zoom", input_source="wheel", monotonic_ms=30)
    telemetry.enter_image(str(tmp_path / "image-b.jpg"))
    telemetry.record_burst("shutdown_zoom", input_source="wheel", monotonic_ms=40)
    assert telemetry.shutdown() is True

    path = next((tmp_path / "logs" / "events").glob("events-*.jsonl"))
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    actions = [
        row["payload"]["action"]
        for row in rows
        if row["event_type"] == "action_span"
        and row.get("payload", {}).get("action") in {
            "selection_pan",
            "focus_pan",
            "image_zoom",
            "shutdown_zoom",
        }
    ]
    assert actions == [
        "selection_pan",
        "focus_pan",
        "image_zoom",
        "shutdown_zoom",
    ]

def test_semantic_actions_emit_v3_action_spans_with_safe_context(tmp_path):
    """UI-facing semantic names share one terminal ActionSpan contract."""
    recorder = LocalEventRecorder(tmp_path / "logs", enabled=True)
    telemetry = BehaviorTelemetry(str(tmp_path / "project"), recorder)
    telemetry.start_project()
    telemetry.enter_image(str(tmp_path / "image.jpg"))
    telemetry.select_shape("shape-a")
    telemetry.action(
        "label_edit",
        input_source="mouse",
        result="success",
        payload={"label_key": "changed"},
        context={"shape_type": "rectangle", "label_key": "changed"},
    )
    telemetry.action(
        "labels_saved",
        input_source="keyboard",
        result="success",
        payload={"saved_after_change": True},
    )
    telemetry.action(
        "quality_review",
        input_source="mouse",
        result="success",
        payload={"quality_rule": "review_decision"},
    )
    telemetry.action(
        "session_interrupted",
        input_source="system",
        result="interrupted",
        interruption_reason="test_boundary",
    )
    assert telemetry.shutdown() is True

    path = next((tmp_path / "logs" / "events").glob("events-*.jsonl"))
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    actions = [
        row["payload"]["action"]
        for row in rows
        if row["event_type"] == "action_span"
    ]
    assert {"label_edit", "labels_saved", "quality_review"} <= set(actions)
    interrupted = [
        row
        for row in rows
        if row.get("payload", {}).get("action") == "session_interrupted"
    ]
    assert interrupted[0]["result"] == "interrupted"
    assert interrupted[0]["interruption_reason"] == "test_boundary"



