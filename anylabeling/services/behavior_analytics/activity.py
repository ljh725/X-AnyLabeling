"""Focus and idle state transitions for active-time accounting."""

from __future__ import annotations

from dataclasses import dataclass

from .clock import ClockReading


@dataclass(frozen=True)
class ActivityTransition:
    """One observable focus or idle state transition."""

    kind: str
    value: bool
    reading: ClockReading


class ActivityTracker:
    """Track focus and inactivity without treating idle time as active work."""

    def __init__(self, idle_threshold_ms: int = 120_000) -> None:
        """Initialize the tracker with a positive idle threshold."""
        if idle_threshold_ms <= 0:
            raise ValueError("idle_threshold_ms must be positive")
        self.idle_threshold_ms = idle_threshold_ms
        self.focused = True
        self.idle = False
        self._last_input_ms: int | None = None

    def focus_changed(
        self, focused: bool, reading: ClockReading
    ) -> list[ActivityTransition]:
        """Apply a window focus change and return emitted transitions."""
        transitions: list[ActivityTransition] = []
        if self.focused != focused:
            self.focused = focused
            transitions.append(ActivityTransition("focused", focused, reading))
        if not focused and self.idle:
            self.idle = False
            transitions.append(ActivityTransition("idle", False, reading))
        return transitions

    def input_received(
        self, reading: ClockReading
    ) -> list[ActivityTransition]:
        """Record a semantic user input and leave the idle state if needed."""
        self._last_input_ms = reading.monotonic_ms
        if not self.focused or not self.idle:
            return []
        self.idle = False
        return [ActivityTransition("idle", False, reading)]

    def observe(self, reading: ClockReading) -> list[ActivityTransition]:
        """Emit an idle transition after the configured silent interval."""
        if (
            not self.focused
            or self.idle
            or self._last_input_ms is None
            or reading.monotonic_ms - self._last_input_ms
            < self.idle_threshold_ms
        ):
            return []
        self.idle = True
        return [ActivityTransition("idle", True, reading)]
