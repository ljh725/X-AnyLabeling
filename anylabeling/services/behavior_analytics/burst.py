"""Deterministic aggregation for high-frequency input bursts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompletedBurst:
    """One completed burst summarized without storing input samples."""

    action: str
    input_source: str
    input_count: int
    started_ms: int
    ended_ms: int

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


class BurstAggregator:
    """Group adjacent same-kind inputs separated by a silence window."""

    def __init__(self, silence_ms: int = 300) -> None:
        """Initialize the aggregator with a positive silence threshold."""
        if silence_ms < 0:
            raise ValueError("silence_ms must be non-negative")
        self.silence_ms = silence_ms
        self._open: _OpenBurst | None = None

    def add(
        self, action: str, input_source: str, monotonic_ms: int
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
            self._open = _OpenBurst(
                action=action,
                input_source=input_source,
                input_count=1,
                started_ms=monotonic_ms,
                last_ms=monotonic_ms,
            )
        else:
            current.input_count += 1
            current.last_ms = monotonic_ms
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
        )
