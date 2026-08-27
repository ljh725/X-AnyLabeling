"""Contract tests for the complete object workflow fact layer."""

from anylabeling.services.behavior_analytics import (
    EventEnvelope,
    build_workflow_timeline,
    object_workflow_summary,
    project_bottlenecks,
    workflow_sequence_metrics,
)


def _event(event_id, event_type, monotonic_ms, **extra):
    """Build one minimal v4 event for timeline tests."""
    data = {
        "schema_version": 4,
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at_utc": "2026-08-25T00:00:00.000Z",
        "local_date": "2026-08-25",
        "timezone_offset": "+08:00",
        "monotonic_ms": monotonic_ms,
        "sequence_no": monotonic_ms // 10 or 1,
        "app_session_id": "app",
        "project_session_id": "project-session",
        "project_id": "project",
        "feature_state_version": 1,
        "input_source": "mouse",
        "result": "success",
        "image_id": "image",
        "shape_id": "shape",
        "object_episode_id": "episode",
        "payload": None,
    }
    data.update(extra)
    return EventEnvelope.from_mapping(data)


def _action(event_id, name, start, end, **extra):
    """Build one terminal action span."""
    payload = {"action": name}
    payload.update(extra.pop("payload", {}))
    return _event(
        event_id,
        "action_span",
        end,
        action_id=event_id,
        action_phase="committed",
        action_type=name,
        started_monotonic_ms=start,
        ended_monotonic_ms=end,
        duration_ms=end - start,
        payload=payload,
        **extra,
    )


def test_timeline_keeps_creation_phases_and_uses_one_object_identity():
    """Creation intent, draw and label are one workflow after commit."""
    events = [
        _event(
            "intent",
            "creation_workflow_started",
            100,
            creation_workflow_id="create-1",
            workflow_type="creation",
            payload={"creation_workflow_id": "create-1"},
        ),
        _action(
            "draw",
            "create_draw",
            120,
            300,
            object_episode_id=None,
            shape_id=None,
            creation_workflow_id="create-1",
            payload={"creation_workflow_id": "create-1"},
        ),
        _action(
            "label",
            "create_label",
            320,
            500,
            object_episode_id=None,
            shape_id=None,
            creation_workflow_id="create-1",
            input_source="keyboard",
            payload={"creation_workflow_id": "create-1"},
        ),
        _event(
            "created",
            "shape_created",
            520,
            shape_id="shape-1",
            object_episode_id="episode-1",
            creation_workflow_id="create-1",
            payload={
                "creation_workflow_id": "create-1",
                "initial_source": "r_then_label",
                "creation_mode": "r_then_label",
                "shape_type": "rectangle",
            },
        ),
        _action(
            "adjust",
            "rectangle_adjust",
            540,
            600,
            shape_id="shape-1",
            object_episode_id="episode-1",
            payload={"shape_type": "rectangle", "edit_target": "right"},
        ),
        _event(
            "ended",
            "object_episode_ended",
            700,
            shape_id="shape-1",
            object_episode_id="episode-1",
            episode_end_reason="selection_cleared",
        ),
    ]
    timeline = build_workflow_timeline(events)
    assert len(timeline.records) == 1
    record = timeline.records[0]
    assert record.object_episode_id == "episode-1"
    assert record.creation_mode == "r_then_label"
    assert [item.action for item in record.actions] == [
        "creation_intent",
        "create_draw",
        "create_label",
        "rectangle_adjust",
    ]
    assert record.to_dict()["stage_times_ms"]["creation_label"] == 180


def test_time_decomposition_conserves_active_time_and_closes_idle_recovery():
    """Idle true only contributes wait until the explicit false recovery."""
    events = [
        _event(
            "selected",
            "shape_selected",
            100,
            selection_source="user_canvas_single",
        ),
        _event("idle-on", "idle_changed", 200, payload={"idle": True}),
        _event("idle-off", "idle_changed", 400, payload={"idle": False}),
        _action("a", "geometry_adjust", 450, 500),
        _event(
            "ended",
            "object_episode_ended",
            600,
            episode_end_reason="selection_cleared",
        ),
    ]
    record = build_workflow_timeline(events).records[0]
    time = record.to_dict()["time"]
    assert time["wall_ms"] == 500
    assert time["conservation_ok"] is True
    assert time["active_ms"] == 300


def test_overlapping_actions_are_preserved_but_project_contribution_is_not_doubled():
    """Action facts remain separate while the project ranking uses a union."""
    events = [
        _event(
            "selected",
            "shape_selected",
            0,
            selection_source="user_canvas_single",
        ),
        _action("a", "geometry_adjust", 100, 500),
        _action("b", "zoom", 300, 700, input_source="wheel"),
        _event(
            "ended",
            "object_episode_ended",
            800,
            episode_end_reason="selection_cleared",
        ),
    ]
    timeline = build_workflow_timeline(events)
    assert timeline.records[0].to_dict()["time"]["action_union_ms"] == 600
    rows = project_bottlenecks(timeline)
    assert sum(row["total_ms"] for row in rows) == 600
    assert rows[0]["ranking"] == 1


def test_sequence_duration_uses_each_window_not_the_whole_episode():
    """Three-action windows have their own start/end duration."""
    events = [
        _event(
            "selected",
            "shape_selected",
            0,
            selection_source="user_canvas_single",
        ),
        _action("a", "geometry_adjust", 100, 200),
        _action("b", "label_edit", 300, 400),
        _action("c", "attribute_edit", 500, 600),
        _action("d", "save", 700, 800),
        _event(
            "ended",
            "object_episode_ended",
            1000,
            episode_end_reason="selection_cleared",
        ),
    ]
    rows = workflow_sequence_metrics(build_workflow_timeline(events))
    three = [row for row in rows if row["length"] == 3]
    assert sum(row["total_ms"] for row in three) == 1000
    assert sum(row["count"] for row in three) == 2


def test_summary_omits_missing_zoom_context_and_exposes_neutral_integrity():
    """No zoom is represented by null range fields, not a fabricated zero."""
    events = [
        _event(
            "selected",
            "shape_selected",
            0,
            selection_source="user_canvas_single",
        ),
        _action("a", "geometry_adjust", 100, 200),
        _event(
            "ended",
            "object_episode_ended",
            300,
            episode_end_reason="selection_cleared",
        ),
    ]
    row = object_workflow_summary(build_workflow_timeline(events))[0]
    assert row["zoom_count"] == 0
    assert row["zoom_start"] is None
    assert row["zoom_end"] is None
    assert "visual" not in str(row).lower()
