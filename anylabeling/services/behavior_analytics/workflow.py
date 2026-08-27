"""Deterministic object-workflow timeline and bottleneck facts.

The module is deliberately independent of Qt and of the event recorder.  It
turns the privacy-safe event envelope into one shared fact model used by the
summary, sequence and bottleneck exporters.  No function in this module
guesses an object from geometry or from a later selection event.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Iterable, Mapping

from .catalog import sanitize_event
from .schema import EventEnvelope
from .versions import WORKFLOW_TIMELINE_VERSION

_MAX_MONOTONIC = 2**63 - 1
DEFAULT_IDLE_BOUNDARY_MS = 600_000
SUPPORTED_SHAPES = (
    "polygon",
    "rectangle",
    "rotation",
    "quadrilateral",
    "point",
    "line",
    "circle",
    "linestrip",
    "cuboid",
)

WORKFLOW_STAGES = (
    "image_to_first_operation",
    "target_search_gap",
    "creation_intent",
    "creation_geometry",
    "creation_label",
    "navigation",
    "geometry",
    "label_attribute",
    "ai",
    "quality",
    "rework",
    "save",
    "action_gap",
    "system_wait",
    "unattributed",
)


def _value(event: EventEnvelope | Mapping[str, Any], name: str) -> Any:
    """Read a field from either an envelope or a test mapping."""
    if isinstance(event, EventEnvelope):
        return getattr(event, name, None)
    return event.get(name)


def _payload(event: EventEnvelope | Mapping[str, Any]) -> dict[str, Any]:
    """Return a shallow, privacy-safe payload mapping."""
    payload = _value(event, "payload")
    return dict(payload) if isinstance(payload, Mapping) else {}


def _action_name(event: EventEnvelope | Mapping[str, Any]) -> str | None:
    """Return the explicit semantic action name, if present."""
    action_type = _value(event, "action_type")
    payload = _payload(event)
    action = payload.get("action") or action_type
    return str(action) if action not in (None, "") else None


def _creation_id(event: EventEnvelope | Mapping[str, Any]) -> str | None:
    """Return a creation token without accepting free-form identity data."""
    value = _value(event, "creation_workflow_id")
    if value is None:
        value = _payload(event).get("creation_workflow_id")
    return str(value) if value not in (None, "") else None


def _workflow_type(event: EventEnvelope | Mapping[str, Any]) -> str:
    """Classify an event as an existing-object or creation workflow fact."""
    payload = _payload(event)
    explicit = payload.get("workflow_type") or _value(event, "workflow_type")
    if explicit in {"create", "creation", "creation_workflow"}:
        return "creation"
    if _creation_id(event) or payload.get("initial_source"):
        return "creation"
    return "edit"


def _stage_for_action(action: str | None, payload: Mapping[str, Any]) -> str:
    """Map one action to a stable, neutral workflow stage."""
    explicit = payload.get("workflow_stage") or payload.get("stage")
    if explicit in WORKFLOW_STAGES:
        return str(explicit)
    if action in {"creation_intent", "create_intent", "workflow_started"}:
        return "creation_intent"
    if action in {"create_draw", "creation_geometry", "shape_draw"}:
        return "creation_geometry"
    if action in {"create_label", "creation_label"}:
        return "creation_label"
    if action in {"zoom", "pan", "image_navigate", "view_navigation"}:
        return "navigation"
    if action in {
        "geometry_adjust",
        "rectangle_adjust",
        "keypoint_adjust",
        "keyboard_nudge",
        "shape_created",
    }:
        return "geometry"
    if action in {"label_edit", "attribute_edit"}:
        return "label_attribute"
    if action in {"ai_correct", "ai_create"}:
        return "ai"
    if action in {"inspector_review", "quality_review"}:
        return "quality"
    if action in {"rework", "undo", "redo", "shape_restored"}:
        return "rework"
    if action in {"labels_saved", "shape_saved", "save"}:
        return "save"
    if action is None:
        return "unattributed"
    return "unattributed"


def _event_sort_key(
    event: EventEnvelope | Mapping[str, Any],
) -> tuple[Any, ...]:
    """Return the canonical event ordering key."""
    sequence = _value(event, "sequence_no")
    return (
        str(_value(event, "app_session_id") or ""),
        sequence if isinstance(sequence, int) else _MAX_MONOTONIC,
        int(_value(event, "monotonic_ms") or 0),
        str(_value(event, "event_id") or ""),
    )


def _interval(event: EventEnvelope | Mapping[str, Any]) -> tuple[int, int]:
    """Return a non-negative half-open interval for an event."""
    start = _value(event, "started_monotonic_ms")
    end = _value(event, "ended_monotonic_ms")
    point = int(_value(event, "monotonic_ms") or 0)
    start = point if start is None else int(start)
    end = point if end is None else int(end)
    return min(start, end), max(start, end)


def _duration(interval: tuple[int, int]) -> int:
    """Return the duration of a half-open interval."""
    return max(0, interval[1] - interval[0])


def _merge(intervals: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping or touching half-open intervals."""
    ordered = sorted((a, b) for a, b in intervals if b > a)
    merged: list[tuple[int, int]] = []
    for start, end in ordered:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _subtract(
    base: Iterable[tuple[int, int]], cuts: Iterable[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Subtract a union of half-open intervals from another interval set."""
    result: list[tuple[int, int]] = []
    cuts_union = _merge(cuts)
    for start, end in _merge(base):
        cursor = start
        for cut_start, cut_end in cuts_union:
            if cut_end <= cursor:
                continue
            if cut_start >= end:
                break
            if cut_start > cursor:
                result.append((cursor, min(cut_start, end)))
            cursor = max(cursor, cut_end)
            if cursor >= end:
                break
        if cursor < end:
            result.append((cursor, end))
    return [(start, end) for start, end in result if end > start]


def _union_ms(intervals: Iterable[tuple[int, int]]) -> int:
    """Return the length of an interval union."""
    return sum(_duration(item) for item in _merge(intervals))


def _percentile(values: Iterable[int], percentile: float) -> int | None:
    """Return a deterministic linear percentile rounded to milliseconds."""
    ordered = sorted(int(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * (
        position - lower
    )
    return int(round(value))


@dataclass(frozen=True)
class WorkflowAction:
    """One privacy-safe semantic action in a workflow timeline."""

    event_id: str
    action: str
    stage: str
    start_ms: int
    end_ms: int
    result: str
    input_source: str | None
    edit_target: str | None
    shape_type: str | None
    input_count: int | None = None
    rework: bool = False
    start_ratio: float | None = None
    end_ratio: float | None = None
    direction: str | None = None
    selection_state: str | None = None

    @property
    def duration_ms(self) -> int:
        """Return the non-negative action duration."""
        return max(0, self.end_ms - self.start_ms)

    def to_dict(self) -> dict[str, Any]:
        """Return the fixed, privacy-safe JSON representation."""
        return {
            "event_id": self.event_id,
            "action": self.action,
            "stage": self.stage,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "duration_ms": self.duration_ms,
            "result": self.result,
            "input_source": self.input_source,
            "edit_target": self.edit_target,
            "shape_type": self.shape_type,
            "input_count": self.input_count,
            "rework": self.rework,
            "start_ratio": self.start_ratio,
            "end_ratio": self.end_ratio,
            "direction": self.direction,
            "selection_state": self.selection_state,
        }


@dataclass
class WorkflowRecord:
    """One complete or explicitly incomplete object workflow."""

    object_episode_id: str
    project_id: str | None
    image_id: str | None
    shape_id: str | None
    workflow_type: str
    creation_mode: str | None
    shape_type: str | None
    size_bucket: str | None
    started_ms: int
    ended_ms: int | None = None
    end_reason: str | None = None
    creation_workflow_id: str | None = None
    actions: list[WorkflowAction] = field(default_factory=list)
    boundary_events: list[str] = field(default_factory=list)
    integrity: str = "complete"
    exclusion_reason: str | None = None
    focus_transitions: list[tuple[int, bool]] = field(default_factory=list)
    idle_transitions: list[tuple[int, bool]] = field(default_factory=list)
    image_to_first_operation_ms: int | None = None
    target_search_gap_ms: int | None = None

    def close(self, end_ms: int, reason: str) -> None:
        """Close a workflow once, preserving the first explicit boundary."""
        if self.ended_ms is not None:
            return
        self.ended_ms = max(self.started_ms, int(end_ms))
        self.end_reason = reason

    @property
    def duration_ms(self) -> int | None:
        """Return wall duration when both workflow boundaries are known."""
        if self.ended_ms is None:
            return None
        return max(0, self.ended_ms - self.started_ms)

    def to_dict(self) -> dict[str, Any]:
        """Return one stable JSONL timeline row."""
        decomposition = decompose_workflow(self)
        return {
            "timeline_schema_version": WORKFLOW_TIMELINE_VERSION,
            "object_episode_id": self.object_episode_id,
            "project_id": self.project_id,
            "image_id": self.image_id,
            "shape_id": self.shape_id,
            "workflow_type": self.workflow_type,
            "creation_mode": self.creation_mode,
            "creation_workflow_id": self.creation_workflow_id,
            "shape_type": self.shape_type,
            "size_bucket": self.size_bucket,
            "started_ms": self.started_ms,
            "ended_ms": self.ended_ms,
            "end_reason": self.end_reason,
            "actions": [action.to_dict() for action in self.actions],
            "intervals": decomposition["intervals"],
            "time": decomposition["time"],
            "stage_times_ms": decomposition["stage_times_ms"],
            "integrity": self.integrity,
            "exclusion_reason": self.exclusion_reason,
            "image_to_first_operation_ms": self.image_to_first_operation_ms,
            "target_search_gap_ms": self.target_search_gap_ms,
        }


@dataclass(frozen=True)
class WorkflowTimeline:
    """Shared timeline facts and structured exclusions."""

    records: tuple[WorkflowRecord, ...]
    excluded: tuple[dict[str, Any], ...]
    image_visits: tuple[dict[str, Any], ...]
    sorted_event_count: int
    sequence_gap_count: int

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable timeline envelope."""
        return {
            "timeline_schema_version": WORKFLOW_TIMELINE_VERSION,
            "records": [record.to_dict() for record in self.records],
            "excluded": list(self.excluded),
            "image_visits": list(self.image_visits),
            "sorted_event_count": self.sorted_event_count,
            "sequence_gap_count": self.sequence_gap_count,
        }


def _as_events(
    events: Iterable[EventEnvelope | Mapping[str, Any]],
) -> list[EventEnvelope | Mapping[str, Any]]:
    """Normalize and privacy-sanitize event inputs without writing them."""
    result: list[EventEnvelope | Mapping[str, Any]] = []
    for item in events:
        event = item
        if not isinstance(item, EventEnvelope):
            event = EventEnvelope.from_mapping(item)
        sanitized, _ = sanitize_event(event)
        result.append(sanitized)
    return sorted(result, key=_event_sort_key)


def _new_record(
    event: EventEnvelope | Mapping[str, Any], key: str, workflow_type: str
) -> WorkflowRecord:
    """Create a record from its first explicit identity-bearing event."""
    payload = _payload(event)
    context = _value(event, "context")
    context = context if isinstance(context, Mapping) else {}
    shape_type = payload.get("shape_type") or context.get("shape_type")
    size_bucket = payload.get("size_bucket") or context.get("size_bucket")
    return WorkflowRecord(
        object_episode_id=key,
        project_id=_value(event, "project_id"),
        image_id=_value(event, "image_id"),
        shape_id=_value(event, "shape_id"),
        workflow_type=workflow_type,
        creation_mode=(
            payload.get("creation_mode")
            or payload.get("initial_source")
            or _value(event, "initial_source")
        ),
        shape_type=str(shape_type) if shape_type else None,
        size_bucket=str(size_bucket) if size_bucket else None,
        started_ms=_interval(event)[0],
        creation_workflow_id=_creation_id(event),
    )


def _add_action(
    record: WorkflowRecord, event: EventEnvelope | Mapping[str, Any]
) -> None:
    """Append one terminal action, ignoring programmatic lifecycle callbacks."""
    action = _action_name(event)
    if not action or _value(event, "event_type") != "action_span":
        return
    payload = _payload(event)
    context = _value(event, "context")
    context = context if isinstance(context, Mapping) else {}
    start_ms, end_ms = _interval(event)
    action = str(action)
    if action in {"select", "selection_sync", "mode_changed"} and (
        _value(event, "input_source") == "system"
    ):
        return
    shape_type = payload.get("shape_type") or context.get("shape_type")
    record.actions.append(
        WorkflowAction(
            event_id=str(_value(event, "event_id") or ""),
            action=action,
            stage=_stage_for_action(action, payload),
            start_ms=start_ms,
            end_ms=end_ms,
            result=str(_value(event, "result") or "unknown"),
            input_source=(
                str(_value(event, "input_source"))
                if _value(event, "input_source") is not None
                else None
            ),
            edit_target=(
                str(_value(event, "edit_target") or payload.get("edit_target"))
                if (_value(event, "edit_target") or payload.get("edit_target"))
                else None
            ),
            shape_type=str(shape_type) if shape_type else record.shape_type,
            input_count=(
                int(payload["input_count"])
                if isinstance(payload.get("input_count"), int)
                else None
            ),
            rework=bool(payload.get("rework") or payload.get("rework_facts")),
            start_ratio=(
                float(payload["start_ratio"])
                if isinstance(payload.get("start_ratio"), (int, float))
                else None
            ),
            end_ratio=(
                float(payload["end_ratio"])
                if isinstance(payload.get("end_ratio"), (int, float))
                else None
            ),
            direction=(
                str(payload["direction"])
                if payload.get("direction") is not None
                else None
            ),
            selection_state=(
                str(payload["selection_state"])
                if payload.get("selection_state") is not None
                else None
            ),
        )
    )
    if record.shape_type is None and shape_type:
        record.shape_type = str(shape_type)
    if record.size_bucket is None:
        candidate = payload.get("size_bucket") or context.get("size_bucket")
        if candidate:
            record.size_bucket = str(candidate)


def _boundary_reason(event: EventEnvelope | Mapping[str, Any]) -> str:
    """Return a normalized workflow boundary reason."""
    return str(
        _value(event, "episode_end_reason")
        or _payload(event).get("end_reason")
        or "boundary"
    )


def build_workflow_timeline(
    events: Iterable[EventEnvelope | Mapping[str, Any]],
    *,
    idle_boundary_ms: int = DEFAULT_IDLE_BOUNDARY_MS,
    include_incomplete: bool = True,
) -> WorkflowTimeline:
    """Build all object workflows from explicit selection/creation facts.

    Creation tokens are provisional until a shape-created fact supplies an
    object identity.  A missing identity is reported in ``excluded`` rather
    than silently attached to a later object.
    """
    if idle_boundary_ms < 0:
        raise ValueError("idle_boundary_ms must be non-negative")
    ordered = _as_events(events)
    records: dict[str, WorkflowRecord] = {}
    aliases: dict[str, str] = {}
    creation_records: dict[str, WorkflowRecord] = {}
    excluded: list[dict[str, Any]] = []
    image_visits: dict[str, dict[str, Any]] = {}
    last_sequence: dict[str, int] = {}
    sequence_gaps = 0
    open_key: dict[tuple[str, str], str] = {}

    for event in ordered:
        session = str(_value(event, "app_session_id") or "")
        sequence = _value(event, "sequence_no")
        if isinstance(sequence, int):
            previous = last_sequence.get(session)
            if previous is not None and sequence != previous + 1:
                sequence_gaps += 1
            last_sequence[session] = sequence
        event_type = str(_value(event, "event_type") or "")
        point = int(_value(event, "monotonic_ms") or 0)
        image_id = _value(event, "image_id")
        if event_type == "image_visit_started" and image_id:
            image_visits[str(image_id)] = {
                "image_id": str(image_id),
                "started_ms": point,
                "first_operation_ms": None,
                "image_to_first_operation_ms": None,
            }
        is_user_fact = _value(event, "input_source") != "system"
        if image_id and is_user_fact:
            visit = image_visits.setdefault(
                str(image_id),
                {
                    "image_id": str(image_id),
                    "started_ms": None,
                    "first_operation_ms": point,
                    "image_to_first_operation_ms": None,
                },
            )
            if visit["first_operation_ms"] is None:
                visit["first_operation_ms"] = point
                if visit["started_ms"] is not None:
                    visit["image_to_first_operation_ms"] = max(
                        0, point - visit["started_ms"]
                    )

        creation_id = _creation_id(event)
        episode_id = _value(event, "object_episode_id")
        shape_id = _value(event, "shape_id")
        workflow_type = _workflow_type(event)
        if event_type in {"creation_workflow_started", "creation_intent"} or (
            creation_id
            and _action_name(event) in {"creation_intent", "create_intent"}
        ):
            if creation_id and creation_id not in creation_records:
                record = _new_record(
                    event, f"creation:{creation_id}", "creation"
                )
                record.actions.append(
                    WorkflowAction(
                        event_id=str(_value(event, "event_id") or ""),
                        action="creation_intent",
                        stage="creation_intent",
                        start_ms=point,
                        end_ms=point,
                        result=str(_value(event, "result") or "success"),
                        input_source=(
                            str(_value(event, "input_source"))
                            if _value(event, "input_source") is not None
                            else None
                        ),
                        edit_target=None,
                        shape_type=record.shape_type,
                    )
                )
                creation_records[creation_id] = record
            continue

        if event_type == "shape_selected" and episode_id:
            source = str(_value(event, "selection_source") or "")
            if source in {"programmatic_sync", "restored_state", "system"}:
                continue
            key = str(episode_id)
            if key not in records:
                records[key] = _new_record(event, key, "edit")
            open_key[(session, str(image_id or ""))] = key
            continue

        if event_type == "shape_created" and shape_id:
            key = str(episode_id or shape_id)
            if creation_id and creation_id in creation_records:
                record = creation_records.pop(creation_id)
                aliases[record.object_episode_id] = key
                record.object_episode_id = key
                record.shape_id = str(shape_id)
                created_payload = _payload(event)
                record.creation_mode = (
                    created_payload.get("creation_mode")
                    or created_payload.get("initial_source")
                    or record.creation_mode
                )
                record.shape_type = (
                    created_payload.get("shape_type") or record.shape_type
                )
                if episode_id:
                    record.object_episode_id = str(episode_id)
                records[key] = record
            elif key not in records:
                records[key] = _new_record(event, key, "creation")
            record = records[key]
            record.shape_id = str(shape_id)
            if record.ended_ms is None and _action_name(event):
                _add_action(record, event)
            continue

        key = str(episode_id) if episode_id else None
        if key is None and creation_id and creation_id in creation_records:
            key = creation_records[creation_id].object_episode_id
        if key is None and event_type == "action_span" and is_user_fact:
            excluded.append(
                {
                    "event_id": _value(event, "event_id"),
                    "reason": "no_object_identity",
                    "image_id": image_id,
                }
            )
            continue
        if key is None:
            continue
        provisional = (
            creation_records.get(creation_id)
            if creation_id and episode_id is None
            else None
        )
        if provisional is not None:
            record = provisional
        else:
            if key not in records:
                records[key] = _new_record(event, key, workflow_type)
            record = records[key]
        if record.image_id is None and image_id:
            record.image_id = str(image_id)
        if record.shape_id is None and shape_id:
            record.shape_id = str(shape_id)
        if event_type == "action_span":
            _add_action(record, event)
        elif event_type == "creation_workflow_ended":
            record.close(
                point, str(_payload(event).get("end_reason") or "cancelled")
            )
            record.integrity = "cancelled"
            record.exclusion_reason = "creation_cancelled"
        elif event_type == "object_episode_ended":
            record.boundary_events.append(str(_value(event, "event_id") or ""))
            record.close(point, _boundary_reason(event))
        elif event_type == "focus_changed":
            value = bool(_payload(event).get("focused", True))
            record.focus_transitions.append((point, value))
        elif event_type == "idle_changed":
            value = bool(_payload(event).get("idle", False))
            record.idle_transitions.append((point, value))

    # A creation token may have been committed with a shape id but no episode
    # id.  It is still a valid object workflow; use the shape id as its key.
    for token, record in creation_records.items():
        if record.object_episode_id.startswith("creation:"):
            record.integrity = "incomplete"
            record.exclusion_reason = "creation_identity_missing"
            if include_incomplete:
                records[record.object_episode_id] = record
            else:
                excluded.append(
                    {
                        "workflow_id": token,
                        "reason": record.exclusion_reason,
                    }
                )

    for record in records.values():
        if record.ended_ms is None:
            record.integrity = "unclosed"
            record.exclusion_reason = "missing_workflow_end"
        record.actions.sort(
            key=lambda action: (
                action.start_ms,
                action.end_ms,
                action.event_id,
            )
        )
        if record.actions and record.started_ms > record.actions[0].start_ms:
            record.started_ms = record.actions[0].start_ms
        if record.ended_ms is not None:
            record.ended_ms = max(record.ended_ms, record.started_ms)
        visit = (
            image_visits.get(str(record.image_id)) if record.image_id else None
        )
        if visit and visit.get("first_operation_ms") is not None:
            record.image_to_first_operation_ms = visit.get(
                "image_to_first_operation_ms"
            )

    # Target-search gaps are image-level facts.  They are assigned only to
    # the first operation of the next object on that image, so a gap cannot
    # be duplicated across multiple object workflows.
    records_by_image: dict[str, list[WorkflowRecord]] = defaultdict(list)
    for record in records.values():
        if record.image_id:
            records_by_image[record.image_id].append(record)
    for image_id, image_records in records_by_image.items():
        image_records.sort(
            key=lambda item: (
                item.started_ms,
                item.object_episode_id,
            )
        )
        previous_end: int | None = None
        visit = image_visits.get(image_id)
        first_operation = (
            visit.get("first_operation_ms") if visit is not None else None
        )
        for record in image_records:
            if previous_end is not None:
                record.target_search_gap_ms = max(
                    0, record.started_ms - previous_end
                )
            elif first_operation is not None:
                record.target_search_gap_ms = max(
                    0, record.started_ms - first_operation
                )
            if record.ended_ms is not None:
                previous_end = max(
                    previous_end or record.ended_ms, record.ended_ms
                )

    return WorkflowTimeline(
        records=tuple(
            sorted(
                records.values(),
                key=lambda record: (
                    record.project_id or "",
                    record.started_ms,
                    record.object_episode_id,
                ),
            )
        ),
        excluded=tuple(excluded),
        image_visits=tuple(image_visits[key] for key in sorted(image_visits)),
        sorted_event_count=len(ordered),
        sequence_gap_count=sequence_gaps,
    )


def _focus_active_intervals(
    record: WorkflowRecord,
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Derive focused and active intervals from optional state transitions."""
    if record.ended_ms is None:
        return [], []
    start, end = record.started_ms, record.ended_ms
    if not record.focus_transitions and not record.idle_transitions:
        return [(start, end)], [(start, end)]
    # The event-level session tracker already records transitions.  The
    # compact record stores only transition points, so replay them in order.
    transitions = [
        (point, value, "focus") for point, value in record.focus_transitions
    ]
    transitions += [
        (point, value, "idle") for point, value in record.idle_transitions
    ]
    transitions.sort(key=lambda item: item[0])
    focused = True
    idle = False
    focused_result: list[tuple[int, int]] = []
    active_result: list[tuple[int, int]] = []
    cursor = start
    for point, value, kind in transitions:
        point = max(start, min(end, point))
        if point > cursor and focused:
            focused_result.append((cursor, point))
            if not idle:
                active_result.append((cursor, point))
        if kind == "focus":
            focused = value
        else:
            idle = value
        cursor = point
    if cursor < end and focused:
        focused_result.append((cursor, end))
        if not idle:
            active_result.append((cursor, end))
    return _merge(focused_result), _merge(active_result)


def decompose_workflow(
    record: WorkflowRecord,
    *,
    idle_boundary_ms: int = DEFAULT_IDLE_BOUNDARY_MS,
) -> dict[str, Any]:
    """Decompose one workflow into mutually exclusive interval facts."""
    if record.ended_ms is None:
        return {
            "time": {
                "wall_ms": None,
                "focused_ms": None,
                "active_ms": None,
                "action_union_ms": None,
                "conservation_ok": False,
                "failure_reason": "missing_workflow_end",
            },
            "intervals": [],
            "stage_times_ms": {stage: None for stage in WORKFLOW_STAGES},
        }
    start, end = record.started_ms, record.ended_ms
    actions = [
        (max(start, action.start_ms), min(end, action.end_ms), action)
        for action in record.actions
        if min(end, action.end_ms) > max(start, action.start_ms)
    ]
    action_intervals = [(a, b) for a, b, _ in actions]
    focused, active = _focus_active_intervals(record)
    action_union = _merge(action_intervals)
    active_action = _merge(_intersect(active, action_union))
    residual = _subtract(active, action_union)
    intervals: list[dict[str, Any]] = []
    stage_times = {stage: 0 for stage in WORKFLOW_STAGES}
    for a, b, action in actions:
        stage_times[action.stage] += b - a
    # A deterministic gap classification over the active residual.
    first_action = min((a for a, _, _ in actions), default=None)
    last_action = max((b for _, b, _ in actions), default=None)
    for a, b in residual:
        if first_action is not None and b <= first_action:
            category = "pre_action_gap"
        elif (
            first_action is not None
            and last_action is not None
            and a >= first_action
            and b <= last_action
            and b - a <= idle_boundary_ms
        ):
            category = "inter_action_gap"
        else:
            category = "unattributed"
        stage_times[
            "action_gap" if category != "unattributed" else "unattributed"
        ] += (b - a)
        intervals.append({"start_ms": a, "end_ms": b, "kind": category})
    wait_intervals = _subtract(focused, active)
    for a, b in wait_intervals:
        stage_times["system_wait"] += b - a
        intervals.append({"start_ms": a, "end_ms": b, "kind": "system_wait"})
    for a, b in action_union:
        intervals.append({"start_ms": a, "end_ms": b, "kind": "action_union"})
    wall_ms = end - start
    focused_ms = _union_ms(focused)
    active_ms = _union_ms(active)
    action_union_ms = _union_ms(action_union)
    conservation_ok = active_ms == action_union_ms + sum(
        item["end_ms"] - item["start_ms"]
        for item in intervals
        if item["kind"]
        in {"pre_action_gap", "inter_action_gap", "unattributed"}
    )
    for stage in WORKFLOW_STAGES:
        if stage_times[stage] == 0:
            stage_times[stage] = None
    return {
        "time": {
            "wall_ms": wall_ms,
            "focused_ms": focused_ms,
            "active_ms": active_ms,
            "action_union_ms": action_union_ms,
            "conservation_ok": conservation_ok,
            "failure_reason": (
                None if conservation_ok else "time_not_conserved"
            ),
        },
        "intervals": sorted(
            intervals,
            key=lambda item: (item["start_ms"], item["end_ms"], item["kind"]),
        ),
        "stage_times_ms": stage_times,
    }


def _intersect(
    left: Iterable[tuple[int, int]], right: Iterable[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Return intersections of two interval sets."""
    result: list[tuple[int, int]] = []
    for left_start, left_end in _merge(left):
        for right_start, right_end in _merge(right):
            start = max(left_start, right_start)
            end = min(left_end, right_end)
            if end > start:
                result.append((start, end))
    return _merge(result)


def object_workflow_summary(
    timeline: WorkflowTimeline | Iterable[WorkflowRecord],
) -> list[dict[str, Any]]:
    """Return fixed-column per-workflow summaries with null omissions."""
    records = (
        timeline.records
        if isinstance(timeline, WorkflowTimeline)
        else tuple(timeline)
    )
    rows = []
    for record in records:
        decomposition = decompose_workflow(record)
        time = decomposition["time"]
        stage = decomposition["stage_times_ms"]
        durations = [action.duration_ms for action in record.actions]
        zooms = [
            action for action in record.actions if action.action == "zoom"
        ]
        rows.append(
            {
                "project_id": record.project_id,
                "image_id": record.image_id,
                "shape_id": record.shape_id,
                "object_episode_id": record.object_episode_id,
                "workflow_type": record.workflow_type,
                "creation_mode": record.creation_mode,
                "shape_type": record.shape_type,
                "size_bucket": record.size_bucket,
                "started_ms": record.started_ms,
                "ended_ms": record.ended_ms,
                "wall_ms": time["wall_ms"],
                "focused_ms": time["focused_ms"],
                "active_ms": time["active_ms"],
                "action_union_ms": time["action_union_ms"],
                "action_count": len(record.actions),
                "action_duration_ms": sum(durations) if durations else 0,
                "zoom_count": len(zooms),
                "zoom_start": (zooms[0].start_ratio if zooms else None),
                "zoom_end": (zooms[-1].end_ratio if zooms else None),
                "stage_times_ms": json_stage_times(stage),
                "rework_ms": sum(
                    action.duration_ms
                    for action in record.actions
                    if action.rework
                ),
                "save_count": sum(
                    action.stage == "save" for action in record.actions
                ),
                "integrity": record.integrity,
                "exclusion_reason": record.exclusion_reason,
                "conservation_ok": time["conservation_ok"],
            }
        )
    return rows


def json_stage_times(stage: Mapping[str, Any]) -> dict[str, Any]:
    """Return a stable stage mapping suitable for CSV JSON cells."""
    return {name: stage.get(name) for name in WORKFLOW_STAGES}


def sequence_metrics(
    timeline: WorkflowTimeline | Iterable[WorkflowRecord],
    *,
    min_length: int = 3,
    max_length: int = 6,
) -> list[dict[str, Any]]:
    """Compute n-gram durations from each window's own interval only."""
    if min_length < 1 or max_length < min_length:
        raise ValueError("invalid sequence length range")
    records = (
        timeline.records
        if isinstance(timeline, WorkflowTimeline)
        else tuple(timeline)
    )
    samples: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for record in records:
        actions = record.actions
        for size in range(min_length, max_length + 1):
            for index in range(0, len(actions) - size + 1):
                window = actions[index : index + size]
                duration = max(0, window[-1].end_ms - window[0].start_ms)
                samples[tuple(item.action for item in window)].append(duration)
    rows = []
    for sequence, values in sorted(samples.items(), key=lambda item: item[0]):
        rows.append(
            {
                "sequence": list(sequence),
                "length": len(sequence),
                "count": len(values),
                "total_ms": sum(values),
                "median_ms": int(median(values)),
                "p75_ms": _percentile(values, 0.75),
                "p90_ms": _percentile(values, 0.90),
                "p95_ms": _percentile(values, 0.95),
            }
        )
    return sorted(rows, key=lambda row: (-row["count"], row["sequence"]))


def project_bottlenecks(
    timeline: WorkflowTimeline | Iterable[WorkflowRecord],
) -> list[dict[str, Any]]:
    """Aggregate non-overlapping action facts into a stable project ranking."""
    records = (
        timeline.records
        if isinstance(timeline, WorkflowTimeline)
        else tuple(timeline)
    )
    contributions: dict[tuple[str, str], list[tuple[int, int, str]]] = (
        defaultdict(list)
    )
    durations: dict[tuple[str, str], list[int]] = defaultdict(list)
    object_ids: dict[tuple[str, str], set[str]] = defaultdict(set)
    all_intervals: list[tuple[int, int, str, str, str]] = []
    for record in records:
        for action in record.actions:
            if action.end_ms <= action.start_ms:
                continue
            key = (action.stage, action.action)
            contributions[key].append(
                (action.start_ms, action.end_ms, record.object_episode_id)
            )
            durations[key].append(action.duration_ms)
            object_ids[key].add(record.object_episode_id)
            all_intervals.append(
                (
                    action.start_ms,
                    action.end_ms,
                    action.stage,
                    action.action,
                    action.event_id,
                )
            )
    # Sweep all actions and assign each atomic interval to one deterministic
    # owner.  This keeps project totals non-overlapping while retaining every
    # action fact in the timeline.
    points = sorted(
        {point for start, end, *_ in all_intervals for point in (start, end)}
    )
    totals: dict[tuple[str, str], int] = defaultdict(int)
    for left, right in zip(points, points[1:]):
        if right <= left:
            continue
        covering = [
            item
            for item in all_intervals
            if item[0] <= left and item[1] >= right
        ]
        if not covering:
            continue
        owner = sorted(
            covering,
            key=lambda item: (item[0], item[1], item[2], item[3], item[4]),
        )[0]
        totals[(owner[2], owner[3])] += right - left
    project_active = sum(totals.values())
    rows = []
    for key in sorted(contributions):
        stage, action = key
        total = totals[key]
        values = durations[key]
        rows.append(
            {
                "stage": stage,
                "action": action,
                "total_ms": total,
                "share": total / project_active if project_active else None,
                "cumulative_share": None,
                "count": len(values),
                "object_coverage": len(object_ids[key]),
                "median_ms": int(median(values)) if values else None,
                "p75_ms": _percentile(values, 0.75),
                "p90_ms": _percentile(values, 0.90),
                "p95_ms": _percentile(values, 0.95),
                "rework_ms": sum(
                    action_item.duration_ms
                    for record in records
                    for action_item in record.actions
                    if action_item.stage == stage
                    and action_item.action == action
                    and action_item.rework
                ),
                "duration_coverage": 1.0 if values else 0.0,
                "ranking": None,
                "project_active_ms": project_active,
                "algorithm_version": WORKFLOW_TIMELINE_VERSION,
            }
        )
    rows.sort(
        key=lambda row: (
            -row["total_ms"],
            -row["object_coverage"],
            row["stage"],
            row["action"],
        )
    )
    cumulative = 0.0
    for index, row in enumerate(rows, 1):
        row["ranking"] = index
        cumulative += row["share"] or 0.0
        row["cumulative_share"] = cumulative
    return rows


# Short aliases keep the API discoverable for callers that use noun-first
# naming while the canonical functions remain explicit.
build_object_workflow_timeline = build_workflow_timeline
build_timeline = build_workflow_timeline
calculate_project_bottlenecks = project_bottlenecks
