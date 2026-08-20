"""Tests for the pure-Python behavior analytics contracts."""

import json
from pathlib import Path

import pytest
import yaml

from anylabeling.services.behavior_analytics import (
    EVENT_CATALOG,
    EVENT_SCHEMA_VERSION,
    EventEnvelope,
    EventType,
    EventValidationError,
    sanitize_payload,
)
from anylabeling.services.behavior_analytics.catalog import validate_payload


def _event_data(**overrides):
    """Return the smallest valid event mapping for tests."""
    data = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_id": "event-1",
        "event_type": EventType.ACTION_SPAN.value,
        "occurred_at_utc": "2026-08-20T01:02:03.000Z",
        "local_date": "2026-08-20",
        "timezone_offset": "+08:00",
        "monotonic_ms": 100,
        "app_session_id": "app-1",
        "project_session_id": "project-session-1",
        "project_id": "project-1",
        "feature_state_version": 1,
        "input_source": "mouse",
        "result": "success",
        "image_id": "image-1",
        "shape_id": "shape-1",
        "object_episode_id": "object-1-edit-1",
        "duration_ms": 250,
        "payload": {"action": "rectangle_adjust"},
    }
    data.update(overrides)
    return data


def test_event_round_trip_is_json_compatible():
    """An event can be serialized and reconstructed without data loss."""
    event = EventEnvelope.from_mapping(_event_data())
    encoded = json.dumps(event.to_dict(), ensure_ascii=False)
    assert EventEnvelope.from_mapping(json.loads(encoded)) == event


def test_event_rejects_missing_required_fields():
    """Missing envelope fields fail before reaching the writer."""
    data = _event_data()
    data.pop("project_id")
    with pytest.raises(EventValidationError, match="project_id"):
        EventEnvelope.from_mapping(data)


def test_event_rejects_negative_duration_and_unknown_schema():
    """Temporal values and schema versions are bounded by the contract."""
    with pytest.raises(EventValidationError, match="duration_ms"):
        EventEnvelope.from_mapping(_event_data(duration_ms=-1))
    with pytest.raises(
        EventValidationError, match="unsupported schema_version"
    ):
        EventEnvelope.from_mapping(_event_data(schema_version=99))


def test_catalog_requires_action_payload():
    """Cataloged event types enforce their required payload keys."""
    assert EventType.ACTION_SPAN.value in EVENT_CATALOG
    with pytest.raises(ValueError, match="action"):
        validate_payload(EventType.ACTION_SPAN.value, {})
    validate_payload(EventType.ACTION_SPAN.value, {"action": "select"})


def test_payload_sanitization_drops_unregistered_fields():
    """Free text and paths cannot pass the event payload allow-list."""
    payload, removed = sanitize_payload(
        EventType.ACTION_SPAN.value,
        {
            "action": "rectangle_adjust",
            "start_summary": {"width_delta": 2},
            "absolute_path": "C:\\private\\image.jpg",
            "free_text": "private note",
        },
    )
    assert payload == {
        "action": "rectangle_adjust",
        "start_summary": {"width_delta": 2},
    }
    assert removed == 2


def test_fixture_contains_boundary_events():
    """The shared fixture covers midnight, switching, state and tombstones."""
    fixture = "tests/fixtures/behavior_analytics/events.jsonl"
    with open(fixture, encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    event_types = {row["event_type"] for row in rows}
    assert EventType.FEATURE_STATE_SNAPSHOT.value in event_types
    assert EventType.FEATURE_STATE_CHANGED.value in event_types
    assert EventType.SHAPE_DELETED.value in event_types
    assert {row["local_date"] for row in rows} == {
        "2026-08-20",
        "2026-08-21",
    }
    selected = [
        (row["shape_id"], row["object_episode_id"])
        for row in rows
        if row["event_type"] == EventType.SHAPE_SELECTED.value
    ]
    assert selected == [
        ("shape-a", "shape-a-episode-1"),
        ("shape-b", "shape-b-episode-1"),
        ("shape-a", "shape-a-episode-2"),
    ]


def test_default_behavior_analytics_config_is_disabled():
    """The shipped configuration keeps behavior collection opt-in."""
    config_path = Path("anylabeling/configs/xanylabeling_config.yaml")
    with config_path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    analytics = config["behavior_analytics"]
    assert analytics["enabled"] is False
    assert analytics["retention_days"] > 0
    assert analytics["queue_max_events"] > 0
