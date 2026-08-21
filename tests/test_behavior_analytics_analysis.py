"""Tests for deterministic event reading and phase-two aggregates."""

import json

from anylabeling.services.behavior_analytics import (
    AnalysisFilter,
    EventEnvelope,
    EventType,
    calculate_statistics,
    read_events,
    replay_events,
)


def _event(event_id, event_type, *, action=None, **overrides):
    """Build a compact event for aggregation tests."""
    payload = {} if action is None else {"action": action}
    data = {
        "schema_version": 1,
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at_utc": f"2026-08-20T00:00:{int(event_id):02d}.000Z",
        "local_date": "2026-08-20",
        "timezone_offset": "+08:00",
        "monotonic_ms": int(event_id) * 1000,
        "app_session_id": "app-1",
        "project_session_id": "project-session-1",
        "project_id": "project-1",
        "feature_state_version": 1,
        "input_source": "mouse",
        "result": "success",
        "image_id": "image-1",
        "shape_id": "shape-1",
        "object_episode_id": "shape-1-episode-1",
        "payload": payload,
    }
    data.update(overrides)
    return EventEnvelope.from_mapping(data)


def test_read_events_filters_and_reports_invalid_lines(tmp_path):
    """Reader keeps valid selected events and classifies damaged input."""
    path = tmp_path / "events.jsonl"
    valid = _event("1", EventType.ACTION_SPAN.value, action="select")
    outside = _event(
        "2",
        EventType.ACTION_SPAN.value,
        action="adjust",
        local_date="2026-08-21",
    )
    rows = [
        json.dumps(valid.to_dict()),
        json.dumps(outside.to_dict()),
        "{not-json}",
        json.dumps({"schema_version": 99}),
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    events, quality = read_events(
        [path],
        event_filter=AnalysisFilter(local_dates=frozenset({"2026-08-20"})),
    )
    assert [event.event_id for event in events] == ["1"]
    assert quality.read_count == 4
    assert quality.accepted_count == 1
    assert quality.filtered_count == 1
    assert quality.corrupt_count == 1
    assert quality.unknown_schema_count == 1
    assert quality.metadata["actual_local_dates"] == ["2026-08-20"]
    assert quality.metadata["input_schema_versions"] == [1]


def test_reader_classifies_incomplete_tail_unknown_fields_and_references(
    tmp_path,
):
    """Tail damage is isolated while optional future fields remain readable."""
    path = tmp_path / "events.jsonl"
    valid = _event("1", EventType.ACTION_SPAN.value, action="select")
    data = valid.to_dict()
    data["future_optional_field"] = "ignored"
    path.write_text(
        json.dumps(data) + "\n{" + '"event_id":"incomplete"',
        encoding="utf-8",
    )
    events, quality = read_events([path])
    assert [event.event_id for event in events] == ["1"]
    assert quality.incomplete_count == 1
    assert quality.unknown_field_count == 1
    assert quality.reason_counts["incomplete_tail"] == 1
    assert quality.missing_reference_count > 0


def test_statistics_are_deterministic_and_include_sequences():
    """Counts, durations, transitions and 3-step sequences are reproducible."""
    events = [
        _event("1", EventType.SHAPE_SELECTED.value, action="select"),
        _event(
            "2",
            EventType.ACTION_SPAN.value,
            action="zoom",
            duration_ms=100,
        ),
        _event(
            "3",
            EventType.ACTION_SPAN.value,
            action="adjust",
            duration_ms=300,
        ),
        _event(
            "4",
            EventType.ACTION_SPAN.value,
            action="adjust",
            duration_ms=500,
        ),
    ]
    result = calculate_statistics(events)
    assert result["event_count"] == 4
    durations = {row["action"]: row for row in result["action_durations"]}
    assert durations["adjust"]["median_ms"] == 400.0
    assert durations["adjust"]["p95_ms"] == 490.0
    assert {row["count"] for row in result["transitions"]} == {1}
    assert result["common_sequences"][0]["sequence"] == [
        "select",
        "zoom",
        "adjust",
    ]
    again = calculate_statistics(events)
    assert result == again


def test_statistics_separate_object_episode_contexts():
    """A new episode does not create a cross-episode sequence."""
    events = [
        _event("1", EventType.SHAPE_SELECTED.value, action="select"),
        _event(
            "2",
            EventType.ACTION_SPAN.value,
            action="adjust",
            duration_ms=100,
            object_episode_id="shape-1-episode-2",
        ),
        _event(
            "3",
            EventType.ACTION_SPAN.value,
            action="save",
            object_episode_id="shape-1-episode-2",
        ),
    ]
    result = calculate_statistics(events)
    assert result["common_sequences"] == []
    assert len(result["object_episodes"]) == 2


def test_replay_integrates_wall_focused_active_time_and_feature_versions():
    """Replay keeps focus/idle boundaries and state versions deterministic."""
    events = [
        _event(
            "1",
            EventType.PROJECT_SESSION_STARTED.value,
            image_id=None,
            shape_id=None,
            object_episode_id=None,
        ),
        _event(
            "2",
            EventType.FEATURE_STATE_SNAPSHOT.value,
            image_id=None,
            shape_id=None,
            object_episode_id=None,
            payload={
                "features": {
                    "rectangle_refinement": {
                        "configured": True,
                        "active": True,
                        "used": False,
                    }
                }
            },
        ),
        _event(
            "3",
            EventType.FOCUS_CHANGED.value,
            image_id=None,
            shape_id=None,
            object_episode_id=None,
            payload={"focused": False},
        ),
        _event(
            "4",
            EventType.FOCUS_CHANGED.value,
            image_id=None,
            shape_id=None,
            object_episode_id=None,
            payload={"focused": True},
        ),
        _event(
            "5",
            EventType.ACTION_SPAN.value,
            action="adjust",
            duration_ms=100,
        ),
    ]
    replay = replay_events(events)
    session = replay["sessions"][0]
    assert session["wall_ms"] == 4000
    assert session["focused_ms"] == 3000
    assert session["active_ms"] == 3000
    assert "1" in replay["feature_states"]
