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


def test_enabled_recorder_writes_hourly_jsonl_shard(tmp_path):
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
    path = tmp_path / "events" / "events-2026-08-20-01.jsonl"
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



def test_sequence_allocator_is_monotonic_across_rejection_and_recovery(
    tmp_path,
):
    """Rejected queue admission consumes a visible sequence number."""
    recorder = LocalEventRecorder(
        tmp_path,
        enabled=True,
        queue_max_events=1,
        start_worker=False,
    )
    first = _event(event_id="sequence-1")
    rejected = _event(event_id="sequence-2")
    recovered = _event(event_id="sequence-3")
    assert recorder.emit(first) is True
    assert recorder.emit(rejected) is False
    queued = recorder._queue.get_nowait()
    recorder._queue.task_done()
    recorder._write_batch([queued])
    assert recorder.emit(recovered) is True
    queued = recorder._queue.get_nowait()
    recorder._queue.task_done()
    recorder._write_batch([queued])
    recorder._finalize_all_shards()
    path = next((tmp_path / "events").glob("*.jsonl"))
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [row["sequence_no"] for row in rows] == [1, 3]
    assert recorder.health.sequence_gaps == 1

    second_session = LocalEventRecorder(
        tmp_path / "second", enabled=True, start_worker=False
    )
    assert second_session.emit(_event(event_id="other-session")) is True
    queued = second_session._queue.get_nowait()
    second_session._queue.task_done()
    second_session._write_batch([queued])
    second_session._finalize_all_shards()
    path = next((tmp_path / "second" / "events").glob("*.jsonl"))
    assert json.loads(path.read_text().splitlines()[0])["sequence_no"] == 1

def test_recorder_rotates_handles_across_utc_hours_and_finalizes_each_manifest(
    tmp_path,
):
    """Cross-hour batches create independent complete shards without empty hours."""
    recorder = LocalEventRecorder(
        tmp_path, enabled=True, start_worker=False, batch_size=8
    )
    first = _event(
        event_id="hour-1",
        occurred_at_utc="2026-08-21T01:59:59.000Z",
        local_date="2026-08-21",
    )
    second = _event(
        event_id="hour-2",
        occurred_at_utc="2026-08-21T03:00:00.000Z",
        local_date="2026-08-21",
    )
    assert recorder.emit(first) is True
    assert recorder.emit(second) is True
    queued = [recorder._queue.get_nowait(), recorder._queue.get_nowait()]
    for _ in queued:
        recorder._queue.task_done()
    recorder._write_batch(queued)
    recorder._finalize_all_shards()
    shards = sorted((tmp_path / "events").glob("events-*.jsonl"))
    assert [path.name for path in shards] == [
        "events-2026-08-21-01.jsonl",
        "events-2026-08-21-03.jsonl",
    ]
    for shard in shards:
        manifest = json.loads(
            shard.with_name(f"{shard.stem}.manifest.json").read_text(
                encoding="utf-8"
            )
        )
        assert manifest["manifest_complete"] is True
        assert manifest["schema_versions"] == {"4": 1}

def test_recorder_write_failure_is_counted_and_observable(tmp_path):
    """A failed shard write increments both write and sequence-gap facts."""
    event_dir = tmp_path / "events"
    event_dir.mkdir()
    (event_dir / "events-2026-08-20-01.jsonl").mkdir()
    recorder = LocalEventRecorder(tmp_path, enabled=True, start_worker=False)
    event = _event()
    assert recorder.emit(event) is True
    queued = recorder._queue.get_nowait()
    recorder._queue.task_done()
    recorder._write_batch([queued])
    assert recorder.health.write_errors == 1
    assert recorder.health.sequence_gaps == 1

