"""Versioned event envelope for local annotation behavior analytics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

EVENT_SCHEMA_VERSION = 1
ANALYTICS_ALGORITHM_VERSION = "1.0"


class EventValidationError(ValueError):
    """Raised when an event does not satisfy the behavior event contract."""


class EventType(str, Enum):
    """Stable semantic event types emitted by the annotation application."""

    APP_SESSION_STARTED = "app_session_started"
    APP_SESSION_ENDED = "app_session_ended"
    PROJECT_SESSION_STARTED = "project_session_started"
    PROJECT_SESSION_ENDED = "project_session_ended"
    FEATURE_STATE_SNAPSHOT = "feature_state_snapshot"
    FEATURE_STATE_CHANGED = "feature_state_changed"
    IMAGE_VISIT_STARTED = "image_visit_started"
    IMAGE_VISIT_ENDED = "image_visit_ended"
    SHAPE_CREATED = "shape_created"
    SHAPE_SELECTED = "shape_selected"
    SHAPE_DELETED = "shape_deleted"
    SHAPE_EDITED = "shape_edited"
    ACTION_SPAN = "action_span"
    FOCUS_CHANGED = "focus_changed"
    IDLE_CHANGED = "idle_changed"


class EventResult(str, Enum):
    """Outcome categories used by semantic actions."""

    SUCCESS = "success"
    CANCELLED = "cancelled"
    NO_CHANGE = "no_change"
    FAILED = "failed"
    INCOMPLETE = "incomplete"


class InputSource(str, Enum):
    """User or system source that caused a semantic event."""

    MOUSE = "mouse"
    WHEEL = "wheel"
    KEYBOARD = "keyboard"
    MENU = "menu"
    TOOLBAR = "toolbar"
    AI = "ai"
    SYSTEM = "system"
    IMPORT = "import"
    UNKNOWN = "unknown"


_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "event_id",
        "event_type",
        "occurred_at_utc",
        "local_date",
        "timezone_offset",
        "monotonic_ms",
        "app_session_id",
        "project_session_id",
        "project_id",
        "feature_state_version",
        "input_source",
        "result",
    }
)


@dataclass(frozen=True)
class EventEnvelope:
    """Immutable, serializable envelope around one semantic event.

    Args:
        schema_version: Version of the event envelope contract.
        event_id: Unique identifier of this event.
        event_type: Stable semantic event type.
        occurred_at_utc: ISO-8601 UTC timestamp.
        local_date: Local calendar date in ``YYYY-MM-DD`` form.
        timezone_offset: Offset used to derive ``local_date``.
        monotonic_ms: Monotonic process timestamp used for durations.
        app_session_id: Identifier for the application process session.
        project_session_id: Identifier for one project open-to-close session.
        project_id: Anonymous stable project identifier.
        feature_state_version: Referenced feature-state version.
        input_source: Source of the semantic action.
        result: Outcome of the event.
        image_id: Anonymous stable image identifier, when applicable.
        shape_id: Stable shape identifier, when applicable.
        object_episode_id: Continuous interaction-round identifier.
        correlation_id: Identifier shared by related events.
        duration_ms: Monotonic duration for a completed action.
        payload: Event-specific, privacy-filtered fields.
    """

    schema_version: int
    event_id: str
    event_type: str
    occurred_at_utc: str
    local_date: str
    timezone_offset: str
    monotonic_ms: int
    app_session_id: str
    project_session_id: str
    project_id: str
    feature_state_version: int
    input_source: str
    result: str
    image_id: str | None = None
    shape_id: str | None = None
    object_episode_id: str | None = None
    correlation_id: str | None = None
    duration_ms: int | None = None
    payload: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Validate the envelope at construction time."""
        self.validate()

    def validate(self) -> None:
        """Validate required values and basic temporal constraints."""
        if self.schema_version != EVENT_SCHEMA_VERSION:
            raise EventValidationError(
                f"unsupported schema_version {self.schema_version!r}"
            )
        for field_name in _REQUIRED_FIELDS:
            if getattr(self, field_name) in (None, ""):
                raise EventValidationError(
                    f"required field {field_name!r} is empty"
                )
        if not isinstance(self.monotonic_ms, int) or self.monotonic_ms < 0:
            raise EventValidationError(
                "monotonic_ms must be a non-negative int"
            )
        if not isinstance(self.feature_state_version, int):
            raise EventValidationError("feature_state_version must be an int")
        if self.feature_state_version < 0:
            raise EventValidationError(
                "feature_state_version must be non-negative"
            )
        if self.duration_ms is not None and (
            not isinstance(self.duration_ms, int) or self.duration_ms < 0
        ):
            raise EventValidationError(
                "duration_ms must be a non-negative int or None"
            )
        if self.payload is not None and not isinstance(self.payload, dict):
            raise EventValidationError("payload must be a dictionary or None")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible event mapping."""
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "occurred_at_utc": self.occurred_at_utc,
            "local_date": self.local_date,
            "timezone_offset": self.timezone_offset,
            "monotonic_ms": self.monotonic_ms,
            "app_session_id": self.app_session_id,
            "project_session_id": self.project_session_id,
            "project_id": self.project_id,
            "feature_state_version": self.feature_state_version,
            "input_source": self.input_source,
            "result": self.result,
        }
        optional = {
            "image_id": self.image_id,
            "shape_id": self.shape_id,
            "object_episode_id": self.object_episode_id,
            "correlation_id": self.correlation_id,
            "duration_ms": self.duration_ms,
            "payload": self.payload,
        }
        result.update(
            {
                key: value
                for key, value in optional.items()
                if value is not None
            }
        )
        return result

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "EventEnvelope":
        """Create an envelope from a decoded JSON mapping.

        Args:
            data: Decoded event mapping.

        Returns:
            A validated event envelope.

        Raises:
            EventValidationError: If the input is not a valid event mapping.
        """
        if not isinstance(data, Mapping):
            raise EventValidationError("event must be a mapping")
        missing = [field for field in _REQUIRED_FIELDS if field not in data]
        if missing:
            raise EventValidationError(
                f"missing required fields: {', '.join(sorted(missing))}"
            )
        values = dict(data)
        values["payload"] = values.get("payload")
        try:
            return cls(
                **{
                    field: values.get(field)
                    for field in cls.__dataclass_fields__
                }
            )
        except TypeError as exc:
            raise EventValidationError(str(exc)) from exc
