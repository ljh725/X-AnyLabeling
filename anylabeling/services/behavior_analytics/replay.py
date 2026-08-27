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
    action_by_id: dict[str, dict[str, object]] = {}
    feature_used: defaultdict[str, set[str]] = defaultdict(set)
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
            row = {
                "event_id": event.event_id,
                "action_id": event.action_id
                or event.correlation_id
                or event.event_id,
                "action": _action_name(event),
                "action_phase": event.action_phase or "committed",
                "project_session_id": event.project_session_id,
                "image_id": event.image_id,
                "shape_id": event.shape_id,
                "object_episode_id": event.object_episode_id,
                "feature_state_version": event.feature_state_version,
                "result": event.result,
                "duration_ms": event.effective_duration_ms,
                "started_monotonic_ms": event.started_monotonic_ms,
                "ended_monotonic_ms": event.ended_monotonic_ms,
                "edit_target": event.edit_target,
                "context_version": event.context_version,
                "participating_features": event.participating_features or [],
                "correlation_id": event.correlation_id,
            }
            action_by_id[str(row["action_id"])] = row
            for feature in event.participating_features or []:
                feature_used[str(feature)].add(event.project_session_id)
    session_rows = [
        _replay_session(session_id, rows)
        for session_id, rows in sorted(sessions.items())
    ]
    action_spans = [
        action_by_id[action_id] for action_id in sorted(action_by_id)
    ]
    episodes = _replay_episodes(ordered)
    return {
        "sessions": session_rows,
        "feature_states": {
            str(version): state for version, state in sorted(states.items())
        },
        "action_spans": action_spans,
        "object_episodes": episodes,
        "feature_used": {
            key: sorted(value) for key, value in sorted(feature_used.items())
        },
        "terminal_integrity": {
            "action_count": len(action_spans),
            "complete_count": sum(
                row["action_phase"]
                in {
                    "committed",
                    "cancelled",
                    "no_change",
                    "interrupted",
                }
                for row in action_spans
            ),
        },
    }


def _replay_episodes(events: list[EventEnvelope]) -> list[dict[str, object]]:
    """Rebuild object episodes and active segments from boundary events."""
    grouped: defaultdict[str, list[EventEnvelope]] = defaultdict(list)
    for event in events:
        if event.object_episode_id:
            grouped[event.object_episode_id].append(event)
    rows = []
    for episode_id, episode_events in sorted(grouped.items()):
        episode_events = sorted(
            episode_events,
            key=lambda event: (
                event.monotonic_ms,
                (
                    event.sequence_no
                    if event.sequence_no is not None
                    else 2**63 - 1
                ),
                event.event_id,
            ),
        )
        start = next(
            (
                event.monotonic_ms
                for event in episode_events
                if event.event_type == "shape_selected"
            ),
            episode_events[0].monotonic_ms,
        )
        explicit_end = next(
            (
                event.monotonic_ms
                for event in episode_events
                if event.event_type == "object_episode_ended"
            ),
            None,
        )
        is_v4 = any(event.schema_version >= 4 for event in episode_events)
        if is_v4 and explicit_end is None:
            rows.append(
                {
                    "object_episode_id": episode_id,
                    "project_session_id": episode_events[0].project_session_id,
                    "image_id": episode_events[0].image_id,
                    "shape_id": episode_events[0].shape_id,
                    "started_monotonic_ms": start,
                    "ended_monotonic_ms": None,
                    "wall_ms": None,
                    "changed": any(
                        event.event_type == "action_span"
                        and event.result == "success"
                        for event in episode_events
                    ),
                    "saved_after_change": any(
                        event.event_type == "shape_saved"
                        or bool(
                            (event.payload or {}).get("saved_after_change")
                        )
                        for event in episode_events
                    ),
                    "end_reason": None,
                    "terminal_integrity": "unclosed",
                    "segments": [],
                }
            )
            continue
        end = explicit_end or episode_events[-1].monotonic_ms
        boundaries = [
            event
            for event in events
            if event.monotonic_ms >= start
            and event.monotonic_ms <= end
            and event.project_session_id
            == episode_events[0].project_session_id
        ]
        focused = True
        idle = False
        segment_start = start
        segments = []
        for event in boundaries:
            if event.event_type == "focus_changed" and event.payload:
                next_focused = bool(event.payload.get("focused", focused))
                if focused and not next_focused:
                    segments.append(
                        {
                            "started_monotonic_ms": segment_start,
                            "ended_monotonic_ms": event.monotonic_ms,
                            "end_reason": "focus_lost",
                        }
                    )
                    segment_start = event.monotonic_ms
                focused = next_focused
            elif event.event_type == "idle_changed" and event.payload:
                next_idle = bool(event.payload.get("idle", idle))
                if not idle and next_idle:
                    segments.append(
                        {
                            "started_monotonic_ms": segment_start,
                            "ended_monotonic_ms": event.monotonic_ms,
                            "end_reason": "idle_started",
                        }
                    )
                    segment_start = event.monotonic_ms
                idle = next_idle
        segments.append(
            {
                "started_monotonic_ms": segment_start,
                "ended_monotonic_ms": end,
                "end_reason": "episode_end",
            }
        )
        end_reason = None
        for event in reversed(episode_events):
            if event.event_type == "object_episode_ended":
                end_reason = event.episode_end_reason or "unknown"
                break
            if event.event_type in {
                "shape_deleted",
                "image_visit_ended",
                "project_session_ended",
            }:
                end_reason = {
                    "shape_deleted": "shape_deleted",
                    "image_visit_ended": "image_changed",
                    "project_session_ended": "project_closed",
                }[event.event_type]
                break
        rows.append(
            {
                "object_episode_id": episode_id,
                "project_session_id": episode_events[0].project_session_id,
                "image_id": episode_events[0].image_id,
                "shape_id": episode_events[0].shape_id,
                "started_monotonic_ms": start,
                "ended_monotonic_ms": end,
                "wall_ms": max(0, end - start),
                "changed": any(
                    event.event_type == "action_span"
                    and event.result == "success"
                    for event in episode_events
                ),
                "saved_after_change": any(
                    event.event_type == "shape_saved"
                    or bool((event.payload or {}).get("saved_after_change"))
                    for event in episode_events
                ),
                "end_reason": end_reason,
                "terminal_integrity": "complete" if end_reason else "unknown",
                "segments": segments,
            }
        )
    return rows


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
