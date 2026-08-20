"""Tests for the non-blocking local event recorder."""

import json

from anylabeling.services.behavior_analytics import (
    EVENT_SCHEMA_VERSION,
    EventEnvelope,
    EventType,
    LocalEventRecorder,
)


def _event(**overrides):
    """Return a valid event for recorder tests."""
    data = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_id": "recorder-event-1",
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
        "payload": {"action": "rectangle_adjust"},
    }
    data.update(overrides)
    return EventEnvelope.from_mapping(data)


def test_disabled_recorder_does_not_touch_disk(tmp_path):
    """The default-off path does not create a behavior directory."""
    recorder = LocalEventRecorder(tmp_path, enabled=False)
    assert recorder.emit(_event()) is False
    assert not tmp_path.exists() or not list(tmp_path.iterdir())


def test_enabled_recorder_writes_monthly_jsonl_shard(tmp_path):
    """Accepted events are written in the background and remain readable."""
    recorder = LocalEventRecorder(tmp_path, enabled=True)
    assert recorder.emit(
        _event(
            payload={
                "action": "rectangle_adjust",
                "private_path": "C:\\private\\image.jpg",
            }
        )
    )
    assert recorder.flush(timeout=1.0) is True
    assert recorder.close(timeout=1.0) is True
    path = tmp_path / "events" / "events-2026-08.jsonl"
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["payload"] == {"action": "rectangle_adjust"}
    assert recorder.health.written == 1
    assert recorder.health.privacy_fields_removed == 1


def test_queue_full_is_fail_open(tmp_path):
    """A full queue rejects a new event without blocking the caller."""
    recorder = LocalEventRecorder(
        tmp_path,
        enabled=True,
        queue_max_events=1,
        start_worker=False,
    )
    assert recorder.emit(_event()) is True
    assert recorder.emit(_event(event_id="recorder-event-2")) is False
    assert recorder.health.dropped == 1
    assert recorder.close(timeout=0.01) is False


def test_oversized_event_is_rejected(tmp_path):
    """A bounded event payload is rejected before reaching the queue."""
    recorder = LocalEventRecorder(tmp_path, enabled=True, max_event_bytes=100)
    assert recorder.emit(_event()) is False
    assert recorder.health.invalid == 1
    recorder.close()
