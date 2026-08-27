"""Versioned event envelope for local annotation behavior analytics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .versions import ANALYTICS_ALGORITHM_VERSION, EVENT_ENVELOPE_VERSION

EVENT_SCHEMA_VERSION = EVENT_ENVELOPE_VERSION
SUPPORTED_EVENT_SCHEMA_VERSIONS = (1, 2, 3, 4)


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
    SHAPE_SAVED = "shape_saved"
    SHAPE_EDITED = "shape_edited"
    ACTION_SPAN = "action_span"
    FOCUS_CHANGED = "focus_changed"
    IDLE_CHANGED = "idle_changed"
    RECORDING_GAP = "recording_gap"
    OBJECT_EPISODE_ENDED = "object_episode_ended"
    CREATION_WORKFLOW_STARTED = "creation_workflow_started"
    CREATION_WORKFLOW_ENDED = "creation_workflow_ended"


class SelectionSource(str, Enum):
    """Stable origin of an object selection fact."""

    CANVAS_SINGLE = "user_canvas_single"
    LIST_SINGLE = "user_list_single"
    USER_MULTI = "user_multi"
    PROGRAMMATIC_SYNC = "programmatic_sync"
    RESTORED_STATE = "restored_state"
    SYSTEM = "system"


class EpisodeEndReason(str, Enum):
    """Versioned reasons that close an object workflow episode."""

    SELECTION_CHANGED = "selection_changed"
    IMAGE_CHANGED = "image_changed"
    SHAPE_DELETED = "shape_deleted"
    SELECTION_CLEARED = "selection_cleared"
    PROJECT_CLOSED = "project_closed"
    RECORDING_STOPPED = "recording_stopped"


class UnattributedReason(str, Enum):
    """Structured reasons for actions without an active object episode."""

    NO_ACTIVE_OBJECT = "no_active_object"
    EPISODE_CLOSED = "episode_closed"
    PROGRAMMATIC_UPDATE = "programmatic_update"
    LEGACY_MISSING_CONTEXT = "legacy_missing_context"
    UNKNOWN = "unknown"


ACTION_PHASES = frozenset(
    {"started", "committed", "cancelled", "no_change", "interrupted"}
)

TERMINAL_RESULTS = frozenset(
    {"success", "cancelled", "failed", "no_change", "interrupted"}
)


class EventResult(str, Enum):
    """Outcome categories used by semantic actions."""

    SUCCESS = "success"
    CANCELLED = "cancelled"
    NO_CHANGE = "no_change"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    # Legacy v2 value retained for backward-compatible reads.
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
    sequence_no: int | None = None
    image_id: str | None = None
    shape_id: str | None = None
    object_episode_id: str | None = None
    correlation_id: str | None = None
    duration_ms: int | None = None
    payload: dict[str, Any] | None = None
    action_id: str | None = None
    action_phase: str | None = None
    started_monotonic_ms: int | None = None
    ended_monotonic_ms: int | None = None
    context_version: str | None = None
    context: dict[str, Any] | None = None
    participating_features: list[str] | None = None
    action_type: str | None = None
    edit_target: str | None = None
    net_change_summary: dict[str, Any] | None = None
    interruption_reason: str | None = None
    selection_source: str | None = None
    selection_batch_id: str | None = None
    episode_end_reason: str | None = None
    unattributed_reason: str | None = None
    privacy_fields_removed: int | None = None
    creation_workflow_id: str | None = None
    workflow_type: str | None = None
    creation_stage: str | None = None

    def __post_init__(self) -> None:
        """Validate the envelope at construction time."""
        self.validate()

    def validate(self) -> None:
        """Validate required values and basic temporal constraints."""
        self._validate_identity()
        self._validate_action_contract()
        self._validate_temporal_values()
        self._validate_optional_values()
        self._validate_v3_contract()
        self._validate_v4_contract()
        self._validate_catalog_payload()

    def _validate_identity(self) -> None:
        """Validate schema and envelope identity fields."""
        if self.schema_version not in SUPPORTED_EVENT_SCHEMA_VERSIONS:
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
        if self.schema_version == 3 and (
            not isinstance(self.sequence_no, int) or self.sequence_no < 1
        ):
            raise EventValidationError(
                "schema_version 3 requires a positive sequence_no"
            )
        if self.sequence_no is not None and (
            not isinstance(self.sequence_no, int) or self.sequence_no < 1
        ):
            raise EventValidationError(
                "sequence_no must be a positive int or None"
            )
        if not isinstance(self.feature_state_version, int):
            raise EventValidationError("feature_state_version must be an int")
        if self.feature_state_version < 0:
            raise EventValidationError(
                "feature_state_version must be non-negative"
            )

    def _validate_action_contract(self) -> None:
        """Validate v2 action fields when a v2 action is present."""
        if (
            self.schema_version in (2, 3)
            and self.event_type == EventType.ACTION_SPAN.value
            and any(
                value is not None
                for value in (
                    self.action_id,
                    self.action_phase,
                    self.started_monotonic_ms,
                    self.ended_monotonic_ms,
                )
            )
        ):
            required = {
                "action_id": self.action_id,
                "action_phase": self.action_phase,
                "started_monotonic_ms": self.started_monotonic_ms,
            }
            missing = sorted(
                name for name, value in required.items() if value in (None, "")
            )
            if missing:
                raise EventValidationError(
                    "v2 action_span missing fields: " + ", ".join(missing)
                )
            if (
                self.action_phase != "started"
                and self.ended_monotonic_ms is None
            ):
                raise EventValidationError(
                    "completed v2 action_span requires ended_monotonic_ms"
                )

    def _validate_v3_contract(self) -> None:
        """Validate fields that are mandatory in the v3 envelope."""
        if self.schema_version != 3:
            return
        if self.result not in TERMINAL_RESULTS:
            raise EventValidationError(
                f"v3 result must be terminal, got {self.result!r}"
            )
        if self.result == "interrupted" and not self.interruption_reason:
            raise EventValidationError(
                "v3 interrupted event requires interruption_reason"
            )
        if self.event_type == EventType.ACTION_SPAN.value:
            required = {
                "action_id": self.action_id,
                "action_phase": self.action_phase,
                "action_type": self.action_type,
                "started_monotonic_ms": self.started_monotonic_ms,
                "ended_monotonic_ms": self.ended_monotonic_ms,
            }
            missing = sorted(
                name for name, value in required.items() if value in (None, "")
            )
            if missing:
                raise EventValidationError(
                    "v3 action_span missing fields: " + ", ".join(missing)
                )
        if self.event_type == EventType.RECORDING_GAP.value:
            payload = self.payload or {}
            required = {
                "gap_start_sequence_no",
                "gap_end_sequence_no",
                "gap_reason",
            }
            missing = sorted(required - payload.keys())
            if missing:
                raise EventValidationError(
                    "v3 recording_gap missing fields: " + ", ".join(missing)
                )

    def _validate_v4_contract(self) -> None:
        """Validate corrected v4 ordering, episode and action semantics."""
        if self.schema_version != 4:
            return
        if self.selection_source is not None:
            valid = {item.value for item in SelectionSource}
            if self.selection_source not in valid:
                raise EventValidationError(
                    f"unsupported selection_source {self.selection_source!r}"
                )
        if self.episode_end_reason is not None:
            valid = {item.value for item in EpisodeEndReason}
            if self.episode_end_reason not in valid:
                raise EventValidationError(
                    "unsupported episode_end_reason "
                    f"{self.episode_end_reason!r}"
                )
        if self.unattributed_reason is not None:
            valid = {item.value for item in UnattributedReason}
            if self.unattributed_reason not in valid:
                raise EventValidationError(
                    "unsupported unattributed_reason "
                    f"{self.unattributed_reason!r}"
                )
        if (
            self.privacy_fields_removed is not None
            and self.privacy_fields_removed < 0
        ):
            raise EventValidationError(
                "privacy_fields_removed must be non-negative"
            )
        if self.event_type == EventType.OBJECT_EPISODE_ENDED.value:
            if not self.object_episode_id:
                raise EventValidationError(
                    "object_episode_ended requires object_episode_id"
                )
            if not self.episode_end_reason:
                raise EventValidationError(
                    "object_episode_ended requires episode_end_reason"
                )
        if self.event_type == EventType.SHAPE_SELECTED.value:
            if not self.selection_source:
                raise EventValidationError(
                    "v4 shape_selected requires selection_source"
                )
            if (
                self.selection_source
                in {
                    SelectionSource.USER_MULTI.value,
                    SelectionSource.PROGRAMMATIC_SYNC.value,
                }
                and not self.selection_batch_id
            ):
                raise EventValidationError(
                    "batched shape_selected requires selection_batch_id"
                )
        # A v4 action may be a legacy-shaped read-only row when no timing
        # fields are present. Once the action contract is used, terminal
        # actions must carry both monotonic boundaries.
        if self.event_type == EventType.ACTION_SPAN.value and any(
            value is not None
            for value in (
                self.action_id,
                self.action_phase,
                self.started_monotonic_ms,
                self.ended_monotonic_ms,
            )
        ):
            required = {
                "action_id": self.action_id,
                "action_phase": self.action_phase,
                "action_type": self.action_type,
                "started_monotonic_ms": self.started_monotonic_ms,
            }
            missing = sorted(
                name for name, value in required.items() if value in (None, "")
            )
            if missing:
                raise EventValidationError(
                    "v4 action_span missing fields: " + ", ".join(missing)
                )
            if self.action_phase != "started" and (
                self.ended_monotonic_ms is None
                or self.result not in TERMINAL_RESULTS
            ):
                raise EventValidationError(
                    "completed v4 action_span requires terminal result and "
                    "ended_monotonic_ms"
                )

    def _validate_catalog_payload(self) -> None:
        """Apply event-type payload requirements without import cycles."""
        from .catalog import validate_payload

        try:
            validate_payload(self.event_type, self.payload)
        except (TypeError, ValueError) as exc:
            raise EventValidationError(str(exc)) from exc

    def _validate_temporal_values(self) -> None:
        """Validate action and duration monotonic values."""
        if self.duration_ms is not None and (
            not isinstance(self.duration_ms, int) or self.duration_ms < 0
        ):
            raise EventValidationError(
                "duration_ms must be a non-negative int or None"
            )
        if (
            self.action_phase is not None
            and self.action_phase not in ACTION_PHASES
        ):
            raise EventValidationError(
                f"unsupported action_phase {self.action_phase!r}"
            )
        for field_name in ("started_monotonic_ms", "ended_monotonic_ms"):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, int) or value < 0):
                raise EventValidationError(
                    f"{field_name} must be a non-negative int or None"
                )
        if (
            self.started_monotonic_ms is not None
            and self.ended_monotonic_ms is not None
            and self.ended_monotonic_ms < self.started_monotonic_ms
        ):
            raise EventValidationError(
                "ended_monotonic_ms must not precede started_monotonic_ms"
            )
        if (
            self.schema_version >= 4
            and self.duration_ms is not None
            and self.started_monotonic_ms is not None
            and self.ended_monotonic_ms is not None
            and self.duration_ms
            != self.ended_monotonic_ms - self.started_monotonic_ms
        ):
            raise EventValidationError(
                "v4 duration_ms must equal the action monotonic interval"
            )

    def _validate_optional_values(self) -> None:
        """Validate optional payload, context and summary containers."""
        if self.payload is not None and not isinstance(self.payload, dict):
            raise EventValidationError("payload must be a dictionary or None")
        if self.context is not None and not isinstance(self.context, dict):
            raise EventValidationError("context must be a dictionary or None")
        if self.participating_features is not None and not isinstance(
            self.participating_features, list
        ):
            raise EventValidationError(
                "participating_features must be a list or None"
            )
        if self.action_type is not None and not isinstance(
            self.action_type, str
        ):
            raise EventValidationError("action_type must be a string or None")
        if self.edit_target is not None and not isinstance(
            self.edit_target, str
        ):
            raise EventValidationError("edit_target must be a string or None")
        if self.net_change_summary is not None and not isinstance(
            self.net_change_summary, dict
        ):
            raise EventValidationError(
                "net_change_summary must be a dictionary or None"
            )
        if self.interruption_reason is not None and (
            not isinstance(self.interruption_reason, str)
            or not self.interruption_reason
        ):
            raise EventValidationError(
                "interruption_reason must be a non-empty string or None"
            )
        for field_name in (
            "selection_source",
            "selection_batch_id",
            "episode_end_reason",
            "unattributed_reason",
        ):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, str) or not value):
                raise EventValidationError(
                    f"{field_name} must be a non-empty string or None"
                )
        if self.privacy_fields_removed is not None and not isinstance(
            self.privacy_fields_removed, int
        ):
            raise EventValidationError("privacy_fields_removed must be an int")
        for field_name in (
            "creation_workflow_id",
            "workflow_type",
            "creation_stage",
        ):
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, str) or not value):
                raise EventValidationError(
                    f"{field_name} must be a non-empty string or None"
                )

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
        if self.sequence_no is not None:
            result["sequence_no"] = self.sequence_no
        optional = {
            "image_id": self.image_id,
            "shape_id": self.shape_id,
            "object_episode_id": self.object_episode_id,
            "correlation_id": self.correlation_id,
            "duration_ms": self.duration_ms,
            "payload": self.payload,
            "action_id": self.action_id,
            "action_phase": self.action_phase,
            "started_monotonic_ms": self.started_monotonic_ms,
            "ended_monotonic_ms": self.ended_monotonic_ms,
            "context_version": self.context_version,
            "context": self.context,
            "participating_features": self.participating_features,
            "action_type": self.action_type,
            "edit_target": self.edit_target,
            "net_change_summary": self.net_change_summary,
            "interruption_reason": self.interruption_reason,
            "selection_source": self.selection_source,
            "selection_batch_id": self.selection_batch_id,
            "episode_end_reason": self.episode_end_reason,
            "unattributed_reason": self.unattributed_reason,
            "privacy_fields_removed": self.privacy_fields_removed,
            "creation_workflow_id": self.creation_workflow_id,
            "workflow_type": self.workflow_type,
            "creation_stage": self.creation_stage,
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

    @property
    def effective_duration_ms(self) -> int | None:
        """Return recorded duration or derive it from monotonic boundaries."""
        if (
            self.schema_version >= 4
            and self.started_monotonic_ms is not None
            and self.ended_monotonic_ms is not None
        ):
            return self.ended_monotonic_ms - self.started_monotonic_ms
        if self.duration_ms is not None:
            return self.duration_ms
        if (
            self.started_monotonic_ms is None
            or self.ended_monotonic_ms is None
        ):
            return None
        return self.ended_monotonic_ms - self.started_monotonic_ms
