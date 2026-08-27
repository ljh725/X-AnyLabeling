"""High-level semantic telemetry coordinator for the annotation UI."""

from __future__ import annotations

from typing import Any, Mapping

from .action_span import ActionSpanTracker, CompletedAction
from .activity import ActivityTracker
from .burst import BurstAggregator, CompletedBurst
from .catalog import sanitize_payload, validate_payload
from .clock import ClockReading
from .feature_state import FeatureState, FeatureStateTracker
from .identifiers import new_session_id
from .recorder import LocalEventRecorder
from .schema import EVENT_SCHEMA_VERSION, EventEnvelope
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
        self.actions = ActionSpanTracker()
        self.activity = ActivityTracker()
        self._creation_workflows: dict[str, dict[str, Any]] = {}

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
        self.interrupt_actions(reason="image_changed")
        episode = self.tracker.end_episode("image_changed")
        self._emit_episode_end(episode)
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
        edit_target: str | None = None,
        start_summary: Mapping[str, Any] | None = None,
        end_summary: Mapping[str, Any] | None = None,
        net_change_summary: Mapping[str, Any] | None = None,
    ) -> None:
        """Aggregate one high-frequency input without storing samples."""
        reading = self.tracker.clock.read()
        for transition in self.activity.input_received(reading):
            if transition.value:
                self.tracker.pause_activity("idle_started")
            else:
                self.tracker.resume_activity()
            self._emit(
                "idle_changed",
                input_source="system",
                result="success",
                payload={"idle": transition.value},
                image_id=(
                    self.tracker.object_episode.image_id
                    if self.tracker.object_episode
                    else None
                ),
                shape_id=(
                    self.tracker.object_episode.shape_id
                    if self.tracker.object_episode
                    else None
                ),
                object_episode_id=(
                    self.tracker.object_episode.object_episode_id
                    if self.tracker.object_episode
                    else None
                ),
                _reading=transition.reading,
            )
        completed = self.bursts.add(
            action,
            input_source,
            reading.monotonic_ms if monotonic_ms is None else monotonic_ms,
            identity=(
                {
                    "image_id": (
                        self.tracker.image_visit.image_id
                        if self.tracker.image_visit
                        else None
                    ),
                    "shape_id": (
                        self.tracker.object_episode.shape_id
                        if self.tracker.object_episode
                        else None
                    ),
                    "object_episode_id": (
                        self.tracker.object_episode.object_episode_id
                        if self.tracker.object_episode
                        else None
                    ),
                }
            ),
            start_summary=start_summary,
            end_summary=end_summary,
            net_change=net_change_summary,
            edit_target=edit_target,
        )
        for burst in completed:
            self._emit_completed_burst(burst)

    def flush_bursts(self) -> None:
        """Emit any open high-frequency burst at a lifecycle boundary."""
        for burst in self.bursts.flush():
            self._emit_completed_burst(burst)

    def begin_creation(
        self,
        creation_mode: str,
        *,
        initial_source: str | None = None,
        shape_type: str | None = None,
        input_source: str = "keyboard",
        creation_workflow_id: str | None = None,
    ) -> str:
        """Start a creation workflow before a shape identity exists."""
        token = creation_workflow_id or new_session_id("creation")
        reading = self.tracker.clock.read()
        self._creation_workflows[token] = {
            "started_ms": reading.monotonic_ms,
            "creation_mode": creation_mode,
            "initial_source": initial_source or creation_mode,
            "shape_type": shape_type,
            "closed": False,
        }
        self._emit(
            "creation_workflow_started",
            input_source=input_source,
            result="success",
            creation_workflow_id=token,
            workflow_type="creation",
            creation_stage="intent",
            payload={
                "action": "creation_intent",
                "creation_workflow_id": token,
                "creation_mode": creation_mode,
                "initial_source": initial_source or creation_mode,
                "shape_type": shape_type,
                "workflow_type": "creation",
                "workflow_stage": "creation_intent",
            },
            action_id=new_session_id("action"),
            action_phase="committed",
            action_type="creation_intent",
            started_monotonic_ms=reading.monotonic_ms,
            ended_monotonic_ms=reading.monotonic_ms,
            duration_ms=0,
        )
        return token

    def start_creation(self, *args: Any, **kwargs: Any) -> str:
        """Compatibility alias for :meth:`begin_creation`."""
        return self.begin_creation(*args, **kwargs)

    def _creation_phase(
        self,
        token: str,
        phase: str,
        *,
        input_source: str = "mouse",
        result: str = "success",
        ended_monotonic_ms: int | None = None,
    ) -> bool:
        """Emit one terminal creation phase without storing text or geometry."""
        state = self._creation_workflows.get(token)
        if state is None or state.get("closed"):
            return False
        reading = self.tracker.clock.read()
        end = (
            reading.monotonic_ms
            if ended_monotonic_ms is None
            else ended_monotonic_ms
        )
        start = int(state.setdefault(f"{phase}_started_ms", end))
        return self._emit(
            "action_span",
            input_source=input_source,
            result=result,
            payload={
                "action": phase,
                "creation_workflow_id": token,
                "creation_mode": state.get("creation_mode"),
                "initial_source": state.get("initial_source"),
                "shape_type": state.get("shape_type"),
                "workflow_type": "creation",
                "workflow_stage": (
                    "creation_label"
                    if phase == "create_label"
                    else "creation_geometry"
                ),
            },
            creation_workflow_id=token,
            workflow_type="creation",
            creation_stage=phase,
            action_id=new_session_id("action"),
            action_phase=("committed" if result == "success" else result),
            action_type=phase,
            started_monotonic_ms=start,
            ended_monotonic_ms=max(start, end),
            duration_ms=max(0, end - start),
        )

    def begin_create_draw(self, token: str) -> bool:
        """Begin the geometry phase of a creation workflow."""
        state = self._creation_workflows.get(token)
        if state is None or state.get("closed"):
            return False
        state["create_draw_started_ms"] = (
            self.tracker.clock.read().monotonic_ms
        )
        return True

    def finish_create_draw(
        self, token: str, *, result: str = "success"
    ) -> bool:
        """Commit or cancel the geometry phase."""
        return self._creation_phase(token, "create_draw", result=result)

    def begin_create_label(self, token: str) -> bool:
        """Begin a real label-input phase; callers must not call this for prefill."""
        state = self._creation_workflows.get(token)
        if state is None or state.get("closed"):
            return False
        state["create_label_started_ms"] = (
            self.tracker.clock.read().monotonic_ms
        )
        return True

    def finish_create_label(
        self, token: str, *, result: str = "success"
    ) -> bool:
        """Commit or cancel the label phase without recording label text."""
        return self._creation_phase(token, "create_label", result=result)

    def commit_creation(
        self,
        token: str,
        shape_id: str,
        *,
        object_episode_id: str | None = None,
        shape_type: str | None = None,
    ) -> bool:
        """Bind a creation token to a shape identity exactly once."""
        state = self._creation_workflows.get(token)
        if state is None or state.get("closed"):
            return False
        reading = self.tracker.clock.read()
        state["closed"] = True
        return self._emit(
            "shape_created",
            input_source="mouse",
            result="success",
            shape_id=shape_id,
            object_episode_id=object_episode_id,
            creation_workflow_id=token,
            workflow_type="creation",
            creation_stage="committed",
            payload={
                "initial_source": state.get("initial_source"),
                "creation_mode": state.get("creation_mode"),
                "creation_workflow_id": token,
                "shape_type": shape_type or state.get("shape_type"),
                "workflow_type": "creation",
            },
            _reading=reading,
        )

    def cancel_creation(
        self, token: str, *, reason: str = "cancelled"
    ) -> bool:
        """Close a provisional creation workflow without a shape-created fact."""
        state = self._creation_workflows.get(token)
        if state is None or state.get("closed"):
            return False
        state["closed"] = True
        reading = self.tracker.clock.read()
        return self._emit(
            "creation_workflow_ended",
            input_source="system",
            result="cancelled",
            creation_workflow_id=token,
            workflow_type="creation",
            creation_stage="cancelled",
            payload={
                "creation_workflow_id": token,
                "workflow_type": "creation",
                "end_reason": reason,
            },
            _reading=reading,
        )

    def _emit_completed_burst(self, burst: CompletedBurst) -> None:
        """Write one summarized burst as a regular action span."""
        episode_id = burst.object_episode_id
        self._emit(
            "action_span",
            input_source=burst.input_source,
            result=(
                "no_change"
                if burst.net_change.get("changed") is False
                else "success"
            ),
            duration_ms=burst.duration_ms,
            payload={
                "action": burst.action,
                "input_count": burst.input_count,
                "start_summary": burst.start_summary
                or {"monotonic_ms": burst.started_ms},
                "end_summary": burst.end_summary
                or {"monotonic_ms": burst.ended_ms},
                "net_change": burst.net_change,
                "edit_target": burst.edit_target,
            },
            action_id=new_session_id("action"),
            action_phase="committed",
            started_monotonic_ms=burst.started_ms,
            ended_monotonic_ms=burst.ended_ms,
            action_type=burst.action,
            image_id=burst.image_id,
            shape_id=burst.shape_id,
            object_episode_id=episode_id,
            edit_target=burst.edit_target,
            net_change_summary=burst.net_change or None,
            unattributed_reason=(
                None if episode_id is not None else "no_active_object"
            ),
        )

    def begin_action(
        self,
        action: str,
        *,
        input_source: str,
        edit_target: str | None = None,
        context: Mapping[str, Any] | None = None,
        participating_features: tuple[str, ...] = (),
        action_id: str | None = None,
    ) -> str:
        """Begin one semantic action at the current monotonic time."""
        episode = self.tracker.object_episode
        reading = self.tracker.clock.read()
        return self.actions.begin(
            action,
            started_monotonic_ms=reading.monotonic_ms,
            input_source=input_source,
            image_id=episode.image_id if episode else None,
            shape_id=episode.shape_id if episode else None,
            object_episode_id=episode.object_episode_id if episode else None,
            edit_target=edit_target,
            context=context,
            context_version=(
                str(context.get("context_version"))
                if context and context.get("context_version")
                else None
            ),
            participating_features=participating_features,
            action_id=action_id,
        )

    def finish_action(
        self,
        action_id: str,
        *,
        result: str = "success",
        net_change: Mapping[str, Any] | None = None,
        interruption_reason: str | None = None,
    ) -> CompletedAction:
        """Finish and emit one action span, with terminal idempotency."""
        reading = self.tracker.clock.read()
        completed = self.actions.finish(
            action_id,
            ended_monotonic_ms=reading.monotonic_ms,
            result=result,
            net_change=net_change,
            interruption_reason=interruption_reason,
        )
        for feature in completed.participating_features:
            self.feature_state.mark_used(feature)
        if completed.result == "success":
            self.tracker.record_action(changed=True)
        self._emit_completed_action(completed)
        return completed

    def interrupt_actions(self, reason: str = "lifecycle_boundary") -> None:
        """Interrupt open actions at a lifecycle boundary."""
        reading = self.tracker.clock.read()
        for completed in self.actions.interrupt_all(
            reading.monotonic_ms, reason=reason
        ):
            self._emit_completed_action(completed)

    def _emit_completed_action(self, action: CompletedAction) -> None:
        """Emit a completed action without exposing raw geometry."""
        self._emit(
            "action_span",
            input_source=action.input_source,
            result=action.result,
            duration_ms=action.duration_ms,
            payload={
                "action": action.action,
                "input_count": action.input_count,
                "net_change": action.net_change,
                "edit_target": action.edit_target,
                "context": action.context,
                "participating_features": list(action.participating_features),
            },
            action_id=action.action_id,
            action_phase=action.action_phase,
            started_monotonic_ms=action.started_monotonic_ms,
            ended_monotonic_ms=action.ended_monotonic_ms,
            action_type=action.action,
            edit_target=action.edit_target,
            context_version=action.context_version,
            context=action.context,
            participating_features=list(action.participating_features),
            net_change_summary=(
                dict(action.net_change) if action.net_change else None
            ),
            image_id=action.image_id,
            shape_id=action.shape_id,
            object_episode_id=action.object_episode_id,
            interruption_reason=action.interruption_reason,
            unattributed_reason=(
                None if action.object_episode_id else "no_active_object"
            ),
        )

    def focus_changed(self, focused: bool) -> bool:
        """Record a window activation change for active-time boundaries."""
        reading = self.tracker.clock.read()
        if focused:
            self.tracker.resume_activity()
        else:
            self.flush_bursts()
            self.tracker.pause_activity("focus_lost")
        transitions = self.activity.focus_changed(focused, reading)
        episode = self.tracker.object_episode
        unattributed_reason = (
            None if episode is not None else "no_active_object"
        )
        result = True
        for transition in transitions:
            if transition.kind == "idle":
                if transition.value:
                    self.tracker.pause_activity("idle_started")
                else:
                    self.tracker.resume_activity()
            event_type = (
                "focus_changed"
                if transition.kind == "focused"
                else "idle_changed"
            )
            result = (
                self._emit(
                    event_type,
                    input_source="system",
                    result="success",
                    payload={
                        (
                            transition.kind
                            if transition.kind == "focused"
                            else "idle"
                        ): transition.value
                    },
                    image_id=episode.image_id if episode else None,
                    shape_id=episode.shape_id if episode else None,
                    object_episode_id=(
                        episode.object_episode_id if episode else None
                    ),
                    unattributed_reason=unattributed_reason,
                    _reading=transition.reading,
                )
                and result
            )
        return result

    def observe_activity(self) -> bool:
        """Emit an idle transition when the configured quiet interval elapses."""
        reading = self.tracker.clock.read()
        transitions = self.activity.observe(reading)
        episode = self.tracker.object_episode
        result = True
        for transition in transitions:
            if transition.value:
                self.tracker.pause_activity("idle_started")
            result = (
                self._emit(
                    "idle_changed",
                    input_source="system",
                    result="success",
                    payload={"idle": transition.value},
                    image_id=episode.image_id if episode else None,
                    shape_id=episode.shape_id if episode else None,
                    object_episode_id=(
                        episode.object_episode_id if episode else None
                    ),
                    unattributed_reason=(
                        None if episode is not None else "no_active_object"
                    ),
                    _reading=transition.reading,
                )
                and result
            )
        return result

    def select_shape(
        self,
        shape_id: str,
        *,
        selection_source: str = "user_canvas_single",
        selection_batch_id: str | None = None,
    ) -> str | None:
        """Start an object episode and emit one auditable selection fact."""
        if self.tracker.image_visit is None:
            return None
        if selection_source in {"user_multi", "programmatic_sync"}:
            selection_batch_id = selection_batch_id or new_session_id(
                "selection-batch"
            )
        if (
            selection_source in {"user_multi", "programmatic_sync"}
            and selection_batch_id
            and self.tracker.object_episode is not None
            and self.tracker.object_episode.selection_batch_id
            == selection_batch_id
        ):
            return self.tracker.object_episode.object_episode_id
        self.flush_bursts()
        reading = self.tracker.clock.read()
        episode = self.tracker.select_shape(
            shape_id,
            selection_source=selection_source,
            selection_batch_id=selection_batch_id,
            reading=reading,
        )
        if self.tracker.closed_episodes:
            previous = self.tracker.closed_episodes[-1]
            if (
                previous.ended_at == reading
                and previous.object_episode_id != episode.object_episode_id
            ):
                self._emit_episode_end(previous)
        input_source = (
            "system"
            if selection_source
            in {"programmatic_sync", "restored_state", "system"}
            else "mouse"
        )
        self._emit(
            "shape_selected",
            input_source=input_source,
            result="success",
            image_id=episode.image_id,
            shape_id=episode.shape_id,
            object_episode_id=episode.object_episode_id,
            selection_source=selection_source,
            selection_batch_id=selection_batch_id,
            _reading=reading,
        )
        return episode.object_episode_id

    def clear_shape(self) -> bool:
        """Close the current object episode when the selection is cleared."""
        self.flush_bursts()
        episode = self.tracker.clear_shape()
        self._emit_episode_end(episode)
        return episode is not None

    def action(
        self,
        event_type: str,
        *,
        input_source: str,
        result: str,
        payload: Mapping[str, Any] | None = None,
        duration_ms: int | None = None,
        correlation_id: str | None = None,
        action_id: str | None = None,
        edit_target: str | None = None,
        context: Mapping[str, Any] | None = None,
        participating_features: list[str] | None = None,
        interruption_reason: str | None = None,
        net_change_summary: Mapping[str, Any] | None = None,
    ) -> bool:
        """Emit one semantic action using the current session context."""
        episode = self.tracker.object_episode
        unattributed_reason = (
            None if episode is not None else "no_active_object"
        )
        semantic_actions = {
            "geometry_adjust",
            "rectangle_adjust",
            "keypoint_adjust",
            "keyboard_nudge",
            "zoom",
            "pan",
            "label_edit",
            "attribute_edit",
            "shape_created",
            "shape_deleted",
            "shape_restored",
            "inspector_review",
            "quality_review",
            "image_navigate",
            "undo",
            "redo",
            "ai_correct",
            "session_interrupted",
            "mode_changed",
        }
        if event_type == "labels_saved":
            action_label = "labels_saved"
            event_type = "action_span"
            payload = dict(payload or {})
            payload.setdefault("action", action_label)
        elif event_type in semantic_actions:
            action_label = event_type
            event_type = "action_span"
            payload = dict(payload or {})
            payload.setdefault("action", action_label)
        reading = self.tracker.clock.read()
        for transition in self.activity.input_received(reading):
            self._emit(
                "idle_changed",
                input_source="system",
                result="success",
                payload={"idle": transition.value},
                image_id=(
                    self.tracker.object_episode.image_id
                    if self.tracker.object_episode
                    else None
                ),
                shape_id=(
                    self.tracker.object_episode.shape_id
                    if self.tracker.object_episode
                    else None
                ),
                object_episode_id=(
                    self.tracker.object_episode.object_episode_id
                    if self.tracker.object_episode
                    else None
                ),
                _reading=transition.reading,
            )
        if participating_features:
            for feature in participating_features:
                self.feature_state.mark_used(feature)
        if result == "success" and event_type == "action_span":
            self.tracker.record_action(changed=True)
        if event_type == "action_span":
            reading = self.tracker.clock.read()
            duration = max(0, duration_ms or 0)
            phase = {
                "success": "committed",
                "cancelled": "cancelled",
                "no_change": "no_change",
            }.get(result, "interrupted")
            emitted = self._emit(
                event_type,
                input_source=input_source,
                result=result,
                payload=payload,
                duration_ms=duration_ms,
                correlation_id=correlation_id,
                action_id=action_id or new_session_id("action"),
                action_phase=phase,
                started_monotonic_ms=reading.monotonic_ms - duration,
                ended_monotonic_ms=reading.monotonic_ms,
                action_type=(
                    str(payload.get("action"))
                    if payload and payload.get("action")
                    else event_type
                ),
                edit_target=edit_target,
                context_version=(
                    str(context.get("context_version"))
                    if context and context.get("context_version")
                    else None
                ),
                context=context,
                participating_features=participating_features,
                interruption_reason=interruption_reason,
                net_change_summary=net_change_summary,
                image_id=episode.image_id if episode else None,
                shape_id=episode.shape_id if episode else None,
                object_episode_id=(
                    episode.object_episode_id if episode else None
                ),
                unattributed_reason=unattributed_reason,
            )
            if (
                payload
                and payload.get("action") == "shape_deleted"
                and episode is not None
            ):
                deleted_episode = self.tracker.end_episode("shape_deleted")
                self._emit_episode_end(deleted_episode)
            return emitted
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
            unattributed_reason=unattributed_reason,
        )

    def mark_saved(self) -> bool:
        """Record a save fact once for the changed selected object."""
        if not self.tracker.mark_saved():
            return False
        return self._emit(
            "shape_saved",
            input_source="menu",
            result="success",
            payload={"saved_after_change": True},
        )

    def close_project(self) -> None:
        """Emit project closure and release nested session state."""
        if self.tracker.project_session is None:
            return
        episode = self.tracker.end_episode("project_closed")
        self._emit_episode_end(episode)
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
        self.interrupt_actions(reason="application_shutdown")
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
        creation_workflow_id: str | None = None,
        workflow_type: str | None = None,
        creation_stage: str | None = None,
        correlation_id: str | None = None,
        action_id: str | None = None,
        action_phase: str | None = None,
        started_monotonic_ms: int | None = None,
        ended_monotonic_ms: int | None = None,
        action_type: str | None = None,
        edit_target: str | None = None,
        context_version: str | None = None,
        context: Mapping[str, Any] | None = None,
        participating_features: list[str] | None = None,
        interruption_reason: str | None = None,
        net_change_summary: Mapping[str, Any] | None = None,
        selection_source: str | None = None,
        selection_batch_id: str | None = None,
        episode_end_reason: str | None = None,
        unattributed_reason: str | None = None,
        _reading: ClockReading | None = None,
    ) -> bool:
        """Build and submit one validated event envelope."""
        project = self.tracker.project_session
        if project is None:
            return False
        reading = _reading or self.tracker.clock.read()
        if feature_state_version is None:
            feature_state_version = self.feature_state.version
        visit = self.tracker.image_visit
        payload_dict, _ = sanitize_payload(event_type, payload)
        validate_payload(event_type, payload_dict)
        event = EventEnvelope(
            schema_version=EVENT_SCHEMA_VERSION,
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
            creation_workflow_id=creation_workflow_id,
            workflow_type=workflow_type,
            creation_stage=creation_stage,
            correlation_id=correlation_id,
            duration_ms=duration_ms,
            payload=payload_dict or None,
            action_id=action_id,
            action_phase=action_phase,
            started_monotonic_ms=started_monotonic_ms,
            ended_monotonic_ms=ended_monotonic_ms,
            action_type=action_type,
            edit_target=edit_target,
            context_version=context_version,
            context=dict(context) if context else None,
            participating_features=participating_features,
            net_change_summary=(
                dict(net_change_summary) if net_change_summary else None
            ),
            interruption_reason=interruption_reason,
            selection_source=selection_source,
            selection_batch_id=selection_batch_id,
            episode_end_reason=episode_end_reason,
            unattributed_reason=unattributed_reason,
        )
        return self.recorder.emit(event)

    def _emit_episode_end(self, episode: Any) -> bool:
        """Emit the explicit v4 close fact for one episode once."""
        if episode is None or episode.ended_at is None:
            return False
        return self._emit(
            "object_episode_ended",
            input_source="system",
            result="success",
            image_id=episode.image_id,
            shape_id=episode.shape_id,
            object_episode_id=episode.object_episode_id,
            duration_ms=episode.wall_ms,
            payload={
                "selection_source": episode.selection_source,
                "selection_batch_id": episode.selection_batch_id,
                "boundary_summary": {
                    "start_monotonic_ms": episode.started_at.monotonic_ms,
                    "end_monotonic_ms": episode.ended_at.monotonic_ms,
                },
            },
            selection_source=episode.selection_source,
            selection_batch_id=episode.selection_batch_id,
            episode_end_reason=episode.end_reason,
            _reading=episode.ended_at,
        )
