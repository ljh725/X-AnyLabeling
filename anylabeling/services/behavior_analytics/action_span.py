"""Semantic action-span state machine for behavior analytics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .identifiers import new_session_id


def compare_action_summaries(
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compare bounded action summaries without retaining geometry snapshots."""
    before = dict(before or {})
    after = dict(after or {})
    keys = {
        "width_delta_bucket",
        "height_delta_bucket",
        "distance_bucket",
        "direction",
        "changed",
    }
    differences = sorted(
        key for key in keys if before.get(key) != after.get(key)
    )
    return {
        "changed": bool(differences),
        "changed_fields": differences,
        "before_available": bool(before),
        "after_available": bool(after),
    }


@dataclass(frozen=True)
class CompletedAction:
    """Immutable summary of one completed semantic action."""

    action_id: str
    action: str
    started_monotonic_ms: int
    ended_monotonic_ms: int
    result: str
    input_source: str
    image_id: str | None = None
    shape_id: str | None = None
    object_episode_id: str | None = None
    edit_target: str | None = None
    net_change: Mapping[str, Any] | None = None
    input_count: int = 1
    context: Mapping[str, Any] | None = None
    context_version: str | None = None
    participating_features: tuple[str, ...] = ()
    action_phase: str = "committed"
    interruption_reason: str | None = None

    @property
    def duration_ms(self) -> int:
        """Return the non-negative monotonic duration."""
        return max(0, self.ended_monotonic_ms - self.started_monotonic_ms)


@dataclass
class _OpenAction:
    """Mutable internal action state until a terminal outcome is known."""

    action_id: str
    action: str
    started_monotonic_ms: int
    input_source: str
    image_id: str | None
    shape_id: str | None
    object_episode_id: str | None
    edit_target: str | None
    context: dict[str, Any] | None
    context_version: str | None
    participating_features: tuple[str, ...]
    input_count: int = 1


class ActionSpanTracker:
    """Track semantic actions and guarantee one terminal outcome per ID."""

    def __init__(self) -> None:
        """Initialize an empty action tracker."""
        self._open: dict[str, _OpenAction] = {}
        self._completed: dict[str, CompletedAction] = {}

    @property
    def open_count(self) -> int:
        """Return the number of actions waiting for a terminal outcome."""
        return len(self._open)

    def begin(
        self,
        action: str,
        *,
        started_monotonic_ms: int,
        input_source: str,
        image_id: str | None = None,
        shape_id: str | None = None,
        object_episode_id: str | None = None,
        edit_target: str | None = None,
        context: Mapping[str, Any] | None = None,
        context_version: str | None = None,
        participating_features: tuple[str, ...] = (),
        action_id: str | None = None,
    ) -> str:
        """Begin one action and return its stable action ID."""
        if not action:
            raise ValueError("action must not be empty")
        if started_monotonic_ms < 0:
            raise ValueError("started_monotonic_ms must be non-negative")
        action_id = action_id or new_session_id("action")
        if action_id in self._open:
            raise ValueError(f"action already open: {action_id}")
        self._open[action_id] = _OpenAction(
            action_id=action_id,
            action=action,
            started_monotonic_ms=started_monotonic_ms,
            input_source=input_source,
            image_id=image_id,
            shape_id=shape_id,
            object_episode_id=object_episode_id,
            edit_target=edit_target,
            context=dict(context) if context else None,
            context_version=context_version,
            participating_features=tuple(participating_features),
        )
        return action_id

    def add_input(self, action_id: str, count: int = 1) -> None:
        """Increase the summarized input count for an open action."""
        if count < 1:
            raise ValueError("count must be positive")
        action = self._open.get(action_id)
        if action is None:
            raise KeyError(action_id)
        action.input_count += count

    def finish(
        self,
        action_id: str,
        *,
        ended_monotonic_ms: int,
        result: str = "success",
        net_change: Mapping[str, Any] | None = None,
        interruption_reason: str | None = None,
    ) -> CompletedAction:
        """Finish an action once and return its immutable summary."""
        existing = self._completed.get(action_id)
        if existing is not None:
            return existing
        action = self._open.pop(action_id, None)
        if action is None:
            raise KeyError(action_id)
        if ended_monotonic_ms < action.started_monotonic_ms:
            raise ValueError("ended time precedes action start")
        completed = CompletedAction(
            action_id=action.action_id,
            action=action.action,
            started_monotonic_ms=action.started_monotonic_ms,
            ended_monotonic_ms=ended_monotonic_ms,
            result=result,
            input_source=action.input_source,
            image_id=action.image_id,
            shape_id=action.shape_id,
            object_episode_id=action.object_episode_id,
            edit_target=action.edit_target,
            net_change=dict(net_change) if net_change else None,
            input_count=action.input_count,
            context=action.context,
            context_version=action.context_version,
            participating_features=action.participating_features,
            action_phase=(
                "committed"
                if result == "success"
                else (
                    "cancelled"
                    if result == "cancelled"
                    else (
                        "no_change" if result == "no_change" else "interrupted"
                    )
                )
            ),
            interruption_reason=interruption_reason,
        )
        self._completed[action_id] = completed
        return completed

    def commit(
        self,
        action_id: str,
        *,
        ended_monotonic_ms: int,
        net_change: Mapping[str, Any] | None = None,
    ) -> CompletedAction:
        """Commit an action, idempotently returning its terminal summary."""
        return self.finish(
            action_id,
            ended_monotonic_ms=ended_monotonic_ms,
            result="success",
            net_change=net_change,
        )

    def cancel(
        self, action_id: str, *, ended_monotonic_ms: int
    ) -> CompletedAction:
        """Cancel an action without counting it as a successful edit."""
        return self.finish(
            action_id,
            ended_monotonic_ms=ended_monotonic_ms,
            result="cancelled",
        )

    def no_change(
        self, action_id: str, *, ended_monotonic_ms: int
    ) -> CompletedAction:
        """Finish an action whose privacy-safe summary did not change."""
        return self.finish(
            action_id,
            ended_monotonic_ms=ended_monotonic_ms,
            result="no_change",
        )

    def interrupt_all(
        self, ended_monotonic_ms: int, reason: str = "lifecycle_boundary"
    ) -> list[CompletedAction]:
        """Interrupt every open action at a lifecycle boundary."""
        return [
            self.finish(
                action_id,
                ended_monotonic_ms=ended_monotonic_ms,
                result="interrupted",
                interruption_reason=reason,
            )
            for action_id in tuple(self._open)
        ]
