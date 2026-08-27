"""Tests for measurement-quality contracts introduced by schema v2."""

import json

import yaml

from anylabeling.services.behavior_analytics import (
    ActionSpanTracker,
    EventEnvelope,
    build_shape_context,
)


def _event(schema_version=2):
    """Build a minimal v1/v2-compatible event."""
    return {
        "schema_version": schema_version,
        "event_id": "event-1",
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
        "action_id": "action-1",
        "action_phase": "committed",
        "started_monotonic_ms": 100,
        "ended_monotonic_ms": 250,
        "context_version": "1.0",
        "context": {"shape_type": "rectangle"},
        "participating_features": ["rectangle_refinement"],
        "payload": {"action": "rectangle_adjust"},
    }


def test_v1_and_v2_events_are_readable_and_v2_fields_round_trip():
    """Compatibility keeps v1 while preserving the v2 action contract."""
    v2 = EventEnvelope.from_mapping(_event())
    v1 = EventEnvelope.from_mapping(_event(schema_version=1))

    assert v2.duration_ms is None
    assert v2.action_id == "action-1"
    assert v2.started_monotonic_ms == 100
    assert v2.ended_monotonic_ms == 250
    assert (
        EventEnvelope.from_mapping(json.loads(json.dumps(v2.to_dict()))) == v2
    )
    assert v1.schema_version == 1


def test_action_span_tracker_has_one_terminal_outcome():
    """Committed and interrupted actions are removed exactly once."""
    tracker = ActionSpanTracker()
    action_id = tracker.begin(
        "rectangle_adjust",
        started_monotonic_ms=100,
        input_source="mouse",
        edit_target="right_edge",
    )
    tracker.add_input(action_id, 3)
    completed = tracker.finish(
        action_id,
        ended_monotonic_ms=250,
        result="success",
        net_change={"width_delta_bucket": "small"},
    )

    assert tracker.open_count == 0
    assert completed.duration_ms == 150
    assert completed.input_count == 4


def test_action_span_tracker_interrupts_open_actions():
    """Lifecycle boundaries emit interrupted actions without fake success."""
    tracker = ActionSpanTracker()
    tracker.begin(
        "geometry_adjust", started_monotonic_ms=10, input_source="mouse"
    )
    interrupted = tracker.interrupt_all(30)

    assert len(interrupted) == 1
    assert interrupted[0].result == "interrupted"
    assert interrupted[0].interruption_reason == "lifecycle_boundary"
    assert interrupted[0].duration_ms == 20


def test_shape_context_is_bucketed_and_does_not_store_raw_label_or_points():
    """Context contains bounded summaries and a salted label key."""
    context = build_shape_context(
        points=[(0, 0), (20, 0), (20, 10), (0, 10)],
        shape_type="rectangle",
        label="private-label",
        initial_source="ai",
        salt=b"test-salt",
    )

    assert context["shape_type"] == "rectangle"
    assert context["size_bucket"] == "small"
    assert context["aspect_ratio_bucket"] == "wide"
    assert context["initial_source"] == "ai"
    assert context["label_key"] != "private-label"
    assert "points" not in context


def test_measurement_config_keeps_recording_disabled_and_thresholds_versioned():
    """The new quality thresholds are explicit and opt-in remains unchanged."""
    with open(
        "anylabeling/configs/xanylabeling_config.yaml", encoding="utf-8"
    ) as stream:
        analytics = yaml.safe_load(stream)["behavior_analytics"]

    assert analytics["enabled"] is False
    assert analytics["action_schema_version"] == 2
    assert analytics["feature_comparison_min_samples"] == 30
    assert analytics["anomaly_episode_event_count"] == 100

