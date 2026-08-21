"""Local annotation behavior analytics contracts and utilities."""

from .catalog import EVENT_CATALOG, EventDefinition, sanitize_payload
from .activity import ActivityTracker, ActivityTransition
from .burst import BurstAggregator, CompletedBurst
from .clock import ClockReading, SystemClock
from .feature_state import (
    DEFAULT_FEATURE_KEYS,
    FeatureDefinition,
    FeatureRegistry,
    FeatureState,
    FeatureStateTracker,
)
from .identifiers import IdentifierHasher, new_session_id
from .analysis import (
    AnalysisFilter,
    ReadQuality,
    calculate_statistics,
    read_events,
)
from .bundle import export_analysis_bundle
from .recorder import LocalEventRecorder, RecorderHealth
from .retention import CleanupSummary, cleanup_event_logs
from .replay import replay_events
from .schema import (
    ANALYTICS_ALGORITHM_VERSION,
    EVENT_SCHEMA_VERSION,
    EventEnvelope,
    EventResult,
    EventType,
    EventValidationError,
    InputSource,
)
from .session import ImageVisit, ObjectEpisode, ProjectSession, SessionTracker
from .telemetry import BehaviorTelemetry

__all__ = [
    "ANALYTICS_ALGORITHM_VERSION",
    "ActivityTracker",
    "ActivityTransition",
    "BurstAggregator",
    "CompletedBurst",
    "AnalysisFilter",
    "ReadQuality",
    "DEFAULT_FEATURE_KEYS",
    "EVENT_CATALOG",
    "EVENT_SCHEMA_VERSION",
    "EventDefinition",
    "EventEnvelope",
    "EventResult",
    "EventType",
    "EventValidationError",
    "FeatureState",
    "FeatureDefinition",
    "FeatureRegistry",
    "FeatureStateTracker",
    "ClockReading",
    "BehaviorTelemetry",
    "IdentifierHasher",
    "ImageVisit",
    "InputSource",
    "LocalEventRecorder",
    "ObjectEpisode",
    "ProjectSession",
    "SessionTracker",
    "SystemClock",
    "RecorderHealth",
    "CleanupSummary",
    "cleanup_event_logs",
    "replay_events",
    "new_session_id",
    "sanitize_payload",
    "calculate_statistics",
    "read_events",
    "export_analysis_bundle",
]
