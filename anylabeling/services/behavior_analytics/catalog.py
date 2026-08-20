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
    EventType.FEATURE_STATE_SNAPSHOT.value: EventDefinition(
        required_payload=frozenset({"features"}),
    ),
    EventType.FEATURE_STATE_CHANGED.value: EventDefinition(
        required_payload=frozenset({"changes"}),
    ),
    EventType.ACTION_SPAN.value: EventDefinition(
        required_payload=frozenset({"action"}),
        optional_payload=frozenset(
            {"input_count", "net_change", "start_summary", "end_summary"}
        ),
    ),
    EventType.FOCUS_CHANGED.value: EventDefinition(
        required_payload=frozenset({"focused"}),
    ),
    EventType.IDLE_CHANGED.value: EventDefinition(
        required_payload=frozenset({"idle"}),
    ),
}


def sanitize_payload(
    event_type: str, payload: Mapping[str, Any] | None
) -> tuple[dict[str, Any], int]:
    """Filter event payload fields through the event catalog.

    Unknown event types accept no payload fields until explicitly registered.
    The returned count is the number of removed top-level fields, allowing the
    writer and analysis export to report privacy normalization without keeping
    the removed values.

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
    return sanitized, len(payload) - len(sanitized)


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
