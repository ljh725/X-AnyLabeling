"""Half-open monotonic interval algebra used by time attribution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, order=True)
class MonoInterval:
    """A non-negative half-open interval ``[start_ms, end_ms)``."""

    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        """Reject inverted or negative monotonic boundaries."""
        if self.start_ms < 0 or self.end_ms < self.start_ms:
            raise ValueError(
                "interval boundaries must be non-negative and ordered"
            )

    @property
    def duration_ms(self) -> int:
        """Return the interval duration."""
        return self.end_ms - self.start_ms

    def clip(self, boundary: "MonoInterval") -> "MonoInterval | None":
        """Return the intersection with another interval."""
        start = max(self.start_ms, boundary.start_ms)
        end = min(self.end_ms, boundary.end_ms)
        return MonoInterval(start, end) if start < end else None


def normalize_intervals(
    intervals: Iterable[MonoInterval],
) -> list[MonoInterval]:
    """Sort intervals and merge overlaps while keeping adjacency distinct."""
    ordered = sorted(
        (item for item in intervals if item.duration_ms > 0),
        key=lambda item: (item.start_ms, item.end_ms),
    )
    merged: list[MonoInterval] = []
    for current in ordered:
        if merged and current.start_ms < merged[-1].end_ms:
            merged[-1] = MonoInterval(
                merged[-1].start_ms, max(merged[-1].end_ms, current.end_ms)
            )
        else:
            merged.append(current)
    return merged


def intersect_intervals(
    left: Iterable[MonoInterval], right: Iterable[MonoInterval]
) -> list[MonoInterval]:
    """Return the normalized pairwise intersection."""
    result = []
    for first in normalize_intervals(left):
        for second in normalize_intervals(right):
            clipped = first.clip(second)
            if clipped:
                result.append(clipped)
    return normalize_intervals(result)


def subtract_intervals(
    minuend: Iterable[MonoInterval], subtrahend: Iterable[MonoInterval]
) -> list[MonoInterval]:
    """Subtract a normalized interval set from another interval set."""
    remaining = normalize_intervals(minuend)
    for cut in normalize_intervals(subtrahend):
        next_remaining: list[MonoInterval] = []
        for item in remaining:
            if cut.end_ms <= item.start_ms or cut.start_ms >= item.end_ms:
                next_remaining.append(item)
                continue
            if item.start_ms < cut.start_ms:
                next_remaining.append(
                    MonoInterval(item.start_ms, cut.start_ms)
                )
            if cut.end_ms < item.end_ms:
                next_remaining.append(MonoInterval(cut.end_ms, item.end_ms))
        remaining = next_remaining
    return normalize_intervals(remaining)


def union_duration_ms(intervals: Iterable[MonoInterval]) -> int:
    """Return the duration of the normalized union."""
    return sum(item.duration_ms for item in normalize_intervals(intervals))


def interval_rows(intervals: Iterable[MonoInterval]) -> list[dict[str, int]]:
    """Serialize intervals with stable field names."""
    return [
        {
            "start_ms": item.start_ms,
            "end_ms": item.end_ms,
            "duration_ms": item.duration_ms,
        }
        for item in normalize_intervals(intervals)
    ]
