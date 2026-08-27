"""Event catalog and privacy allow-list for behavior analytics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .schema import EventType


@dataclass(frozen=True)
class EventDefinition:
    """Validation metadata for one semantic event type."""

    required_payload: frozenset[str] = frozenset()
    optional_payload: frozenset[str] = frozenset()


EVENT_CATALOG: dict[str, EventDefinition] = {
    EventType.SHAPE_CREATED.value: EventDefinition(
        optional_payload=frozenset({"initial_source", "shape_type"}),
    ),
    EventType.SHAPE_DELETED.value: EventDefinition(
        optional_payload=frozenset({"delete_reason", "undo_of_action_id"}),
    ),
    EventType.SHAPE_SAVED.value: EventDefinition(
        optional_payload=frozenset({"saved_after_change", "action_id"}),
    ),
    EventType.FEATURE_STATE_SNAPSHOT.value: EventDefinition(
        required_payload=frozenset({"features"}),
    ),
    EventType.FEATURE_STATE_CHANGED.value: EventDefinition(
        required_payload=frozenset({"changes"}),
    ),
    EventType.ACTION_SPAN.value: EventDefinition(
        required_payload=frozenset({"action"}),
        optional_payload=frozenset(
            {
                "input_count",
                "net_change",
                "start_summary",
                "end_summary",
                "edit_target",
                "context",
                "participating_features",
                "saved_after_change",
                "rework_facts",
                "initial_source",
                "attribute_category",
                "issue_rule",
                "quality_rule",
                "navigation_direction",
                "creation_workflow_id",
                "workflow_type",
                "creation_mode",
                "creation_stage",
                "workflow_stage",
                "size_bucket",
                "complexity_bucket",
                "rework",
                "start_ratio",
                "end_ratio",
                "direction",
                "selection_state",
                "net_change_bucket",
                "shape_type",
                "label_key",
                "attribute_category",
                "issue_rule",
                "quality_rule",
                "navigation_direction",
                "initial_source",
                "attribute_category",
                "issue_rule",
                "quality_rule",
                "navigation_direction",
                "shape_type",
                "label_key",
                "attribute_category",
                "issue_rule",
                "quality_rule",
                "navigation_direction",
            }
        ),
    ),
    EventType.FOCUS_CHANGED.value: EventDefinition(
        required_payload=frozenset({"focused"}),
    ),
    EventType.IDLE_CHANGED.value: EventDefinition(
        required_payload=frozenset({"idle"}),
    ),
    EventType.RECORDING_GAP.value: EventDefinition(
        required_payload=frozenset(
            {"gap_start_sequence_no", "gap_end_sequence_no", "gap_reason"}
        ),
        optional_payload=frozenset({"dropped_count", "write_error_count"}),
    ),
    EventType.OBJECT_EPISODE_ENDED.value: EventDefinition(
        optional_payload=frozenset(
            {"selection_source", "selection_batch_id", "boundary_summary"}
        ),
    ),
    EventType.CREATION_WORKFLOW_STARTED.value: EventDefinition(
        optional_payload=frozenset(
            {
                "action",
                "creation_workflow_id",
                "creation_mode",
                "initial_source",
                "shape_type",
                "workflow_type",
                "workflow_stage",
            }
        ),
    ),
    EventType.CREATION_WORKFLOW_ENDED.value: EventDefinition(
        optional_payload=frozenset(
            {"creation_workflow_id", "workflow_type", "end_reason"}
        ),
    ),
}


_CONTEXT_FIELDS = frozenset(
    {
        "context_version",
        "shape_type",
        "edit_target",
        "point_count_bucket",
        "size_bucket",
        "aspect_ratio_bucket",
        "label_key",
        "initial_source",
        "attribute_category",
        "issue_rule",
        "quality_rule",
        "navigation_direction",
        "creation_workflow_id",
        "workflow_type",
        "creation_mode",
        "creation_stage",
        "workflow_stage",
        "complexity_bucket",
        "attribute_category",
        "issue_rule",
        "quality_rule",
        "navigation_direction",
    }
)
_SUMMARY_FIELDS = frozenset(
    {
        "monotonic_ms",
        "changed",
        "input_count",
        "width_delta",
        "height_delta",
        "width_delta_bucket",
        "height_delta_bucket",
        "distance_bucket",
        "direction",
        "before_hash",
        "after_hash",
        "saved_after_change",
        "undo_of_action_id",
        "action_id",
        "attribute_category",
        "before_bool",
        "after_bool",
        "change_kind",
        "start_ratio",
        "end_ratio",
        "direction_class",
        "net_change_bucket",
    }
)
_NESTED_PAYLOAD_FIELDS = frozenset(
    {"context", "net_change", "start_summary", "end_summary", "rework_facts"}
)


def _sanitize_mapping(
    value: Mapping[str, Any], allowed: frozenset[str]
) -> tuple[dict[str, Any], int]:
    """Keep only scalar values from a registered nested summary."""
    sanitized: dict[str, Any] = {}
    removed = 0
    for key, item in value.items():
        if key not in allowed or isinstance(item, (Mapping, list, tuple, set)):
            removed += 1
            continue
        sanitized[key] = item
    return sanitized, removed


def sanitize_payload(
    event_type: str, payload: Mapping[str, Any] | None
) -> tuple[dict[str, Any], int]:
    """Filter an event payload and all registered nested summaries.

    The returned count includes removed top-level and nested fields. Values that
    are mappings or sequences inside a registered summary are removed as a
    whole, preventing points, pixels, paths, or free text hidden below an
    otherwise allowed key from reaching either storage or export.

    Args:
        event_type: Stable event type name.
        payload: Raw event-specific payload.

    Returns:
        A tuple of sanitized payload and removed-field count.
    """
    if payload is None:
        return {}, 0
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping or None")
    definition = EVENT_CATALOG.get(event_type, EventDefinition())
    allowed = definition.required_payload | definition.optional_payload
    sanitized = {key: payload[key] for key in allowed if key in payload}
    removed_count = len(payload) - len(sanitized)
    for key in list(sanitized):
        value = sanitized[key]
        if key == "context" and isinstance(value, Mapping):
            sanitized[key], nested_removed = _sanitize_mapping(
                value, _CONTEXT_FIELDS
            )
            removed_count += nested_removed
        elif key in _NESTED_PAYLOAD_FIELDS:
            if not isinstance(value, Mapping):
                sanitized.pop(key)
                removed_count += 1
                continue
            sanitized[key], nested_removed = _sanitize_mapping(
                value, _SUMMARY_FIELDS
            )
            removed_count += nested_removed
    participating = sanitized.get("participating_features")
    if isinstance(participating, (list, tuple)):
        original_count = len(participating)
        sanitized["participating_features"] = sorted(
            {str(value) for value in participating if isinstance(value, str)}
        )
        removed_count += original_count - len(
            sanitized["participating_features"]
        )
    return sanitized, removed_count


def sanitize_event(event: Any) -> tuple[Any, int]:
    """Sanitize payload and top-level context fields on one event envelope."""
    from dataclasses import replace

    payload, removed = sanitize_payload(event.event_type, event.payload)
    context = event.context
    if isinstance(context, Mapping):
        context, nested_removed = _sanitize_mapping(context, _CONTEXT_FIELDS)
        removed += nested_removed
    elif context is not None:
        context = None
        removed += 1
    net_change = event.net_change_summary
    if isinstance(net_change, Mapping):
        net_change, nested_removed = _sanitize_mapping(
            net_change, _SUMMARY_FIELDS
        )
        removed += nested_removed
    elif net_change is not None:
        net_change = None
        removed += 1
    return (
        replace(
            event,
            payload=payload or None,
            context=context or None,
            net_change_summary=net_change or None,
            privacy_fields_removed=(event.privacy_fields_removed or 0)
            + removed,
        ),
        removed,
    )


def validate_payload(
    event_type: str, payload: Mapping[str, Any] | None
) -> None:
    """Validate required payload keys for a cataloged event type."""
    if payload is None:
        payload = {}
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping or None")
    definition = EVENT_CATALOG.get(event_type)
    if definition is None:
        return
    missing = definition.required_payload - payload.keys()
    if missing:
        raise ValueError(
            f"event {event_type!r} missing payload fields: "
            f"{', '.join(sorted(missing))}"
        )
