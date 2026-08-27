"""Regression tests for the corrected v4 event contract."""

import pytest

from anylabeling.services.behavior_analytics import (
    EVENT_SCHEMA_VERSION,
    EventEnvelope,
    EventType,
    EventValidationError,
    SelectionSource,
)


def _event(**overrides):
    """Return a minimal event mapping for contract tests."""
    data = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_id": "v4-event",
        "event_type": EventType.ACTION_SPAN.value,
        "occurred_at_utc": "2026-08-25T00:00:00.000Z",
        "local_date": "2026-08-25",
        "timezone_offset": "+08:00",
        "monotonic_ms": 1000,
        "app_session_id": "app-anon",
        "project_session_id": "project-anon",
        "project_id": "project-anon",
        "feature_state_version": 1,
        "input_source": "mouse",
        "result": "success",
        "payload": {"action": "geometry_adjust"},
    }
    data.update(overrides)
    return data


def test_v4_is_current_and_old_versions_remain_readable():
    """The reader accepts v1-v4 while v4 is the current writer contract."""
    assert EVENT_SCHEMA_VERSION == 4
    for version in (1, 2, 3):
        row = _event(
            schema_version=version,
            event_id=f"v{version}",
            event_type=EventType.PROJECT_SESSION_STARTED.value,
            payload=None,
            sequence_no=1 if version == 3 else None,
        )
        assert EventEnvelope.from_mapping(row).schema_version == version
    assert EventEnvelope.from_mapping(_event()).schema_version == 4


def test_v4_action_uses_explicit_monotonic_boundaries():
    """A terminal action has a non-negative explicit half-open interval."""
    event = EventEnvelope.from_mapping(
        _event(
            action_id="action-1",
            action_phase="committed",
            action_type="geometry_adjust",
            started_monotonic_ms=900,
            ended_monotonic_ms=1000,
            duration_ms=100,
        )
    )
    assert event.effective_duration_ms == 100
    with pytest.raises(EventValidationError, match="ended_monotonic_ms"):
        EventEnvelope.from_mapping(
            _event(
                action_id="action-2",
                action_phase="committed",
                action_type="geometry_adjust",
                started_monotonic_ms=900,
            )
        )
    with pytest.raises(EventValidationError, match="must not precede"):
        EventEnvelope.from_mapping(
            _event(
                action_id="action-3",
                action_phase="committed",
                action_type="geometry_adjust",
                started_monotonic_ms=1001,
                ended_monotonic_ms=1000,
            )
        )


def test_v4_selection_and_episode_end_carry_auditable_metadata():
    """Selection source/batch and explicit episode end are schema fields."""
    selected = EventEnvelope.from_mapping(
        _event(
            event_type=EventType.SHAPE_SELECTED.value,
            shape_id="shape-1",
            object_episode_id="episode-1",
            selection_source=SelectionSource.PROGRAMMATIC_SYNC.value,
            selection_batch_id="batch-1",
            payload=None,
        )
    )
    assert selected.selection_batch_id == "batch-1"
    ended = EventEnvelope.from_mapping(
        _event(
            event_type=EventType.OBJECT_EPISODE_ENDED.value,
            shape_id="shape-1",
            object_episode_id="episode-1",
            episode_end_reason="selection_changed",
            selection_source=SelectionSource.CANVAS_SINGLE.value,
            payload=None,
        )
    )
    assert ended.episode_end_reason == "selection_changed"
