"""Deterministic replay helpers for lifecycle, state and action spans."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .schema import EventEnvelope


def replay_events(events: Iterable[EventEnvelope]) -> dict[str, object]:
    """Reconstruct session clocks, feature versions and action spans."""
    ordered = sorted(
        events,
        key=lambda event: (
            event.occurred_at_utc,
            event.monotonic_ms,
            event.event_id,
        ),
    )
    sessions: dict[str, list[EventEnvelope]] = defaultdict(list)
    states: dict[int, dict[str, object]] = {}
    current_states: dict[str, object] = {}
    action_spans: list[dict[str, object]] = []
    for event in ordered:
        sessions[event.project_session_id].append(event)
        if event.event_type == "feature_state_snapshot":
            features = (
                event.payload.get("features", {}) if event.payload else {}
            )
            current_states = (
                dict(features) if isinstance(features, dict) else {}
            )
            states[event.feature_state_version] = dict(current_states)
        elif event.event_type == "feature_state_changed":
            changes = event.payload.get("changes", {}) if event.payload else {}
            if isinstance(changes, dict):
                for key, value in changes.items():
                    current_states[key] = value
            states[event.feature_state_version] = dict(current_states)
        if event.event_type == "action_span":
            action_spans.append(
                {
                    "event_id": event.event_id,
                    "action": _action_name(event),
                    "project_session_id": event.project_session_id,
                    "image_id": event.image_id,
                    "shape_id": event.shape_id,
                    "object_episode_id": event.object_episode_id,
                    "feature_state_version": event.feature_state_version,
                    "result": event.result,
                    "duration_ms": event.duration_ms,
                    "correlation_id": event.correlation_id,
                }
            )
    session_rows = [
        _replay_session(session_id, rows)
        for session_id, rows in sorted(sessions.items())
    ]
    return {
        "sessions": session_rows,
        "feature_states": {
            str(version): state for version, state in sorted(states.items())
        },
        "action_spans": action_spans,
    }


def _replay_session(
    session_id: str, events: list[EventEnvelope]
) -> dict[str, object]:
    """Integrate wall, focused and active monotonic time for one session."""
    if not events:
        return {"project_session_id": session_id}
    focused = True
    idle = False
    focused_ms = 0
    active_ms = 0
    for previous, current in zip(events, events[1:]):
        elapsed = max(0, current.monotonic_ms - previous.monotonic_ms)
        if focused:
            focused_ms += elapsed
            if not idle:
                active_ms += elapsed
        if current.event_type == "focus_changed" and current.payload:
            focused = bool(current.payload.get("focused", focused))
        elif current.event_type == "idle_changed" and current.payload:
            idle = bool(current.payload.get("idle", idle))
    return {
        "project_session_id": session_id,
        "started_monotonic_ms": events[0].monotonic_ms,
        "ended_monotonic_ms": events[-1].monotonic_ms,
        "wall_ms": max(0, events[-1].monotonic_ms - events[0].monotonic_ms),
        "focused_ms": focused_ms,
        "active_ms": active_ms,
        "event_count": len(events),
    }


def _action_name(event: EventEnvelope) -> str:
    """Return the action label from a span or its event type."""
    if event.payload and event.payload.get("action"):
        return str(event.payload["action"])
    return event.event_type
