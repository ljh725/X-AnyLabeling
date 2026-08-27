"""Pure-Python object workflow state-machine regression tests."""

from dataclasses import dataclass

from anylabeling.services.behavior_analytics import (
    EventEnvelope,
    SessionTracker,
    SelectionSource,
    calculate_statistics,
)


@dataclass
class _Reading:
    """Deterministic clock reading used by the state-machine tests."""

    occurred_at_utc: str
    local_date: str
    timezone_offset: str
    monotonic_ms: int


class _Clock:
    """Clock returning the supplied readings in order."""

    def __init__(self):
        self._readings = iter(
            _Reading(
                f"2026-08-25T00:00:{index:02d}Z",
                "2026-08-25",
                "+00:00",
                index * 100,
            )
            for index in range(10)
        )

    def read(self):
        """Return the next deterministic reading."""
        return next(self._readings)


def test_a_b_a_episode_boundaries_are_shared_and_idempotent(tmp_path):
    """Every switch closes once and the next episode starts at that boundary."""
    tracker = SessionTracker(str(tmp_path), clock=_Clock())
    tracker.start_project()
    tracker.enter_image(str(tmp_path / "image.jpg"))
    first_a = tracker.select_shape(
        "a", selection_source="user_canvas_single"
    )
    shape_b = tracker.select_shape(
        "b", selection_source="user_list_single"
    )
    second_a = tracker.select_shape(
        "a", selection_source="user_canvas_single"
    )
    assert first_a.ended_at == shape_b.started_at
    assert shape_b.ended_at == second_a.started_at
    assert first_a.end_reason == "selection_changed"
    assert shape_b.end_reason == "selection_changed"
    assert first_a.selection_source == "user_canvas_single"
    assert shape_b.selection_source == "user_list_single"
    assert tracker.end_episode("selection_cleared") is second_a
    assert tracker.end_episode("selection_cleared") is None
    assert [item.object_episode_id for item in tracker.closed_episodes] == [
        first_a.object_episode_id,
        shape_b.object_episode_id,
        second_a.object_episode_id,
    ]


def test_batch_selection_keeps_one_subject_metadata(tmp_path):
    """A batch identifier is retained on the single workflow subject."""
    tracker = SessionTracker(str(tmp_path), clock=_Clock())
    tracker.start_project()
    tracker.enter_image(str(tmp_path / "image.jpg"))
    episode = tracker.select_shape(
        "a",
        selection_source="programmatic_sync",
        selection_batch_id="batch-1",
    )
    same = tracker.select_shape(
        "a",
        selection_source="programmatic_sync",
        selection_batch_id="batch-1",
    )
    assert same is episode
    assert episode.selection_batch_id == "batch-1"
    assert tracker.closed_episodes == []


def test_v4_cycle_export_uses_explicit_boundary_and_percentiles():
    """A controlled v4 sample produces reproducible cycle and conservation facts."""
    def event(event_id, event_type, monotonic_ms, **extra):
        data = {
            "schema_version": 4,
            "event_id": event_id,
            "event_type": event_type,
            "occurred_at_utc": "2026-08-25T00:00:00.000Z",
            "local_date": "2026-08-25",
            "timezone_offset": "+08:00",
            "monotonic_ms": monotonic_ms,
            "sequence_no": monotonic_ms,
            "app_session_id": "app",
            "project_session_id": "project",
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
        if event_type == "action_span" and data["payload"] is None:
            data["payload"] = {"action": data.get("action_type", "geometry_adjust")}
        return EventEnvelope.from_mapping(data)

    events = [
        event(
            "selected",
            "shape_selected",
            1000,
            selection_source=SelectionSource.CANVAS_SINGLE.value,
        ),
        event(
            "action",
            "action_span",
            1300,
            action_id="action",
            action_phase="committed",
            action_type="geometry_adjust",
            started_monotonic_ms=1100,
            ended_monotonic_ms=1300,
            duration_ms=200,
        ),
        event(
            "ended",
            "object_episode_ended",
            2000,
            episode_end_reason="selection_changed",
            selection_source=SelectionSource.CANVAS_SINGLE.value,
        ),
    ]
    result = calculate_statistics(events)
    cycle = result["episode_cycle_metrics"]
    assert cycle["positive_count"] == 1
    assert cycle["duration_summary"]["median_ms"] == 1000
    assert cycle["duration_summary"]["p90_ms"] == 1000
    assert result["episode_time_decomposition"][0]["conservation_ok"]
