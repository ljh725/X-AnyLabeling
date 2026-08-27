"""Deterministic aggregation for high-frequency input bursts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class CompletedBurst:
    """One completed burst summarized without storing input samples."""

    action: str
    input_source: str
    input_count: int
    started_ms: int
    ended_ms: int
    image_id: str | None = None
    shape_id: str | None = None
    object_episode_id: str | None = None
    edit_target: str | None = None
    start_summary: dict[str, Any] = field(default_factory=dict)
    end_summary: dict[str, Any] = field(default_factory=dict)
    net_change: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> int:
        """Return the monotonic duration covered by this burst."""
        return max(0, self.ended_ms - self.started_ms)


@dataclass
class _OpenBurst:
    """Mutable internal burst state."""

    action: str
    input_source: str
    input_count: int
    started_ms: int
    last_ms: int
    image_id: str | None = None
    shape_id: str | None = None
    object_episode_id: str | None = None
    edit_target: str | None = None
    start_summary: dict[str, Any] = field(default_factory=dict)
    end_summary: dict[str, Any] = field(default_factory=dict)
    net_change: dict[str, Any] = field(default_factory=dict)


class BurstAggregator:
    """Group adjacent same-kind inputs separated by a silence window."""

    def __init__(self, silence_ms: int = 300) -> None:
        """Initialize the aggregator with a positive silence threshold."""
        if silence_ms < 0:
            raise ValueError("silence_ms must be non-negative")
        self.silence_ms = silence_ms
        self._open: _OpenBurst | None = None

    def add(
        self,
        action: str,
        input_source: str,
        monotonic_ms: int,
        *,
        identity: Mapping[str, Any] | None = None,
        start_summary: Mapping[str, Any] | None = None,
        end_summary: Mapping[str, Any] | None = None,
        net_change: Mapping[str, Any] | None = None,
        edit_target: str | None = None,
    ) -> list[CompletedBurst]:
        """Add one input and return bursts closed before it."""
        if monotonic_ms < 0:
            raise ValueError("monotonic_ms must be non-negative")
        completed: list[CompletedBurst] = []
        current = self._open
        if current is not None and (
            current.action != action
            or current.input_source != input_source
            or monotonic_ms - current.last_ms > self.silence_ms
        ):
            completed.append(self._finish())
            current = None
        if current is None:
            identity = identity or {}
            self._open = _OpenBurst(
                action=action,
                input_source=input_source,
                input_count=1,
                started_ms=monotonic_ms,
                last_ms=monotonic_ms,
                image_id=identity.get("image_id"),
                shape_id=identity.get("shape_id"),
                object_episode_id=identity.get("object_episode_id"),
                edit_target=edit_target,
                start_summary=dict(start_summary or {}),
                end_summary=dict(end_summary or {}),
                net_change=dict(net_change or {}),
            )
        else:
            current.input_count += 1
            current.last_ms = monotonic_ms
            if end_summary:
                current.end_summary = dict(end_summary)
            if net_change:
                current.net_change = dict(net_change)
        return completed

    def flush(self) -> list[CompletedBurst]:
        """Close and return the current burst, if any."""
        return [self._finish()] if self._open is not None else []

    def reset(self) -> list[CompletedBurst]:
        """Close the current burst and reset aggregation state."""
        return self.flush()

    def _finish(self) -> CompletedBurst:
        """Convert the open state to an immutable summary."""
        if self._open is None:
            raise RuntimeError("no open burst")
        current = self._open
        self._open = None
        return CompletedBurst(
            action=current.action,
            input_source=current.input_source,
            input_count=current.input_count,
            started_ms=current.started_ms,
            ended_ms=current.last_ms,
            image_id=current.image_id,
            shape_id=current.shape_id,
            object_episode_id=current.object_episode_id,
            edit_target=current.edit_target,
            start_summary=dict(current.start_summary),
            end_summary=dict(current.end_summary),
            net_change=dict(current.net_change),
        )
