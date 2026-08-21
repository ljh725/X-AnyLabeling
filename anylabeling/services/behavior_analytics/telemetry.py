"""High-level semantic telemetry coordinator for the annotation UI."""

from __future__ import annotations

from typing import Any, Mapping

from .burst import BurstAggregator, CompletedBurst
from .catalog import sanitize_payload, validate_payload
from .feature_state import FeatureState, FeatureStateTracker
from .identifiers import new_session_id
from .recorder import LocalEventRecorder
from .schema import EventEnvelope
from .session import SessionTracker


class BehaviorTelemetry:
    """Coordinate session state, feature versions and local event recording."""

    def __init__(
        self,
        project_root: str,
        recorder: LocalEventRecorder,
        *,
        tracker: SessionTracker | None = None,
        feature_state: FeatureStateTracker | None = None,
        burst_silence_ms: int = 300,
    ) -> None:
        """Initialize telemetry for one project root."""
        self.recorder = recorder
        self.tracker = tracker or SessionTracker(project_root)
        self.feature_state = feature_state or FeatureStateTracker()
        self.bursts = BurstAggregator(burst_silence_ms)

    def start_project(
        self, features: Mapping[str, FeatureState] | None = None
    ) -> None:
        """Start a project session and emit its snapshot."""
        project = self.tracker.start_project()
        self._emit(
            "project_session_started",
            input_source="system",
            result="success",
            feature_state_version=0,
        )
        snapshot = self.feature_state.start_snapshot(features)
        self._emit(
            "feature_state_snapshot",
            input_source="system",
            result="success",
            payload={"features": snapshot["features"]},
            feature_state_version=snapshot["version"],
            project_session_id=project.project_session_id,
        )

    def apply_feature_state(
        self, features: Mapping[str, FeatureState]
    ) -> bool:
        """Emit one versioned state change when effective state differs."""
        change = self.feature_state.apply_changes(features)
        if change is None:
            return False
        self._emit(
            "feature_state_changed",
            input_source="menu",
            result="success",
            payload={"changes": change["changes"]},
        )
        return True

    def enter_image(self, image_path: str) -> None:
        """Start an image visit in the current project session."""
        self.flush_bursts()
        self.close_image()
        visit = self.tracker.enter_image(image_path)
        self._emit(
            "image_visit_started",
            input_source="system",
            result="success",
            image_id=visit.image_id,
            payload={},
        )

    def close_image(self) -> None:
        """Close the current image visit, if one is active."""
        self.flush_bursts()
        visit = self.tracker.image_visit
        if visit is None:
            return
        reading = self.tracker.clock.read()
        duration_ms = max(
            0, reading.monotonic_ms - visit.started_at.monotonic_ms
        )
        self._emit(
            "image_visit_ended",
            input_source="system",
            result="success",
            image_id=visit.image_id,
            duration_ms=duration_ms,
        )
        self.tracker.image_visit = None
        self.tracker.object_episode = None

    def record_burst(
        self,
        action: str,
        *,
        input_source: str,
        monotonic_ms: int | None = None,
    ) -> None:
        """Aggregate one high-frequency input without storing samples."""
        reading = self.tracker.clock.read()
        completed = self.bursts.add(
            action,
            input_source,
            reading.monotonic_ms if monotonic_ms is None else monotonic_ms,
        )
        for burst in completed:
            self._emit_completed_burst(burst)

    def flush_bursts(self) -> None:
        """Emit any open high-frequency burst at a lifecycle boundary."""
        for burst in self.bursts.flush():
            self._emit_completed_burst(burst)

    def _emit_completed_burst(self, burst: CompletedBurst) -> None:
        """Write one summarized burst as a regular action span."""
        self._emit(
            "action_span",
            input_source=burst.input_source,
            result="success",
            duration_ms=burst.duration_ms,
            payload={
                "action": burst.action,
                "input_count": burst.input_count,
                "start_summary": {"monotonic_ms": burst.started_ms},
                "end_summary": {"monotonic_ms": burst.ended_ms},
            },
        )

    def focus_changed(self, focused: bool) -> bool:
        """Record a window activation change for active-time boundaries."""
        return self._emit(
            "focus_changed",
            input_source="system",
            result="success",
            payload={"focused": bool(focused)},
        )

    def select_shape(self, shape_id: str) -> str | None:
        """Start an object episode when an image visit is available."""
        if self.tracker.image_visit is None:
            return None
        episode = self.tracker.select_shape(shape_id)
        self._emit(
            "shape_selected",
            input_source="mouse",
            result="success",
            image_id=episode.image_id,
            shape_id=episode.shape_id,
            object_episode_id=episode.object_episode_id,
        )
        return episode.object_episode_id

    def action(
        self,
        event_type: str,
        *,
        input_source: str,
        result: str,
        payload: Mapping[str, Any] | None = None,
        duration_ms: int | None = None,
        correlation_id: str | None = None,
    ) -> bool:
        """Emit one semantic action using the current session context."""
        episode = self.tracker.object_episode
        return self._emit(
            event_type,
            input_source=input_source,
            result=result,
            payload=payload,
            duration_ms=duration_ms,
            correlation_id=correlation_id,
            image_id=episode.image_id if episode else None,
            shape_id=episode.shape_id if episode else None,
            object_episode_id=(episode.object_episode_id if episode else None),
        )

    def close_project(self) -> None:
        """Emit project closure and release nested session state."""
        if self.tracker.project_session is None:
            return
        self.close_image()
        self._emit(
            "project_session_ended",
            input_source="system",
            result="success",
        )
        self.tracker.close_project()

    def shutdown(self) -> bool:
        """Close the project and flush the recorder before application exit."""
        self.flush_bursts()
        self.close_project()
        return self.recorder.close(timeout=1.0)

    def _emit(
        self,
        event_type: str,
        *,
        input_source: str,
        result: str,
        payload: Mapping[str, Any] | None = None,
        duration_ms: int | None = None,
        feature_state_version: int | None = None,
        project_session_id: str | None = None,
        image_id: str | None = None,
        shape_id: str | None = None,
        object_episode_id: str | None = None,
        correlation_id: str | None = None,
    ) -> bool:
        """Build and submit one validated event envelope."""
        project = self.tracker.project_session
        if project is None:
            return False
        reading = self.tracker.clock.read()
        if feature_state_version is None:
            feature_state_version = self.feature_state.version
        visit = self.tracker.image_visit
        payload_dict, _ = sanitize_payload(event_type, payload)
        validate_payload(event_type, payload_dict)
        event = EventEnvelope(
            schema_version=1,
            event_id=new_session_id("event"),
            event_type=event_type,
            occurred_at_utc=reading.occurred_at_utc,
            local_date=reading.local_date,
            timezone_offset=reading.timezone_offset,
            monotonic_ms=reading.monotonic_ms,
            app_session_id=project.app_session_id,
            project_session_id=project_session_id
            or project.project_session_id,
            project_id=project.project_id,
            feature_state_version=feature_state_version,
            input_source=input_source,
            result=result,
            image_id=image_id or (visit.image_id if visit else None),
            shape_id=shape_id,
            object_episode_id=object_episode_id,
            correlation_id=correlation_id,
            duration_ms=duration_ms,
            payload=payload_dict or None,
        )
        return self.recorder.emit(event)
