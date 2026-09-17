"""Deterministic spatial rounds for dense rectangle review."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Iterable, Literal, Sequence

Axis = Literal["x", "y"]


@dataclass(frozen=True)
class RectangleSnapshot:
    """Minimal immutable rectangle input used by the partitioner."""

    shape_id: str
    center_x: float
    center_y: float
    source_index: int


@dataclass(frozen=True)
class RoundBoundary:
    """Frozen one-dimensional visual boundary for one review round."""

    axis: Axis
    start: float
    end: float


@dataclass(frozen=True)
class RoundPartition:
    """Stable balanced groups and their frozen display boundaries."""

    axis: Axis
    limit: int
    rounds: tuple[tuple[str, ...], ...]
    boundaries: tuple[RoundBoundary, ...]

    @property
    def count(self) -> int:
        """Return the number of rounds, including an empty zero-data round."""
        return len(self.rounds)

    def round_for(self, shape_id: str) -> int | None:
        """Return the zero-based round containing ``shape_id``."""
        for index, members in enumerate(self.rounds):
            if shape_id in members:
                return index
        return None


def _balanced_sizes(total: int, limit: int) -> tuple[int, ...]:
    """Return stable near-equal group sizes that never exceed ``limit``."""
    if limit < 1:
        raise ValueError("round limit must be positive")
    if total < 1:
        return (0,)
    round_count = int(math.ceil(total / limit))
    base, remainder = divmod(total, round_count)
    return tuple(
        base + (1 if index < remainder else 0) for index in range(round_count)
    )


def build_round_partition(
    snapshots: Iterable[RectangleSnapshot],
    image_size: tuple[float, float],
    limit: int = 10,
) -> RoundPartition:
    """Build one deterministic balanced spatial partition.

    Args:
        snapshots: Rectangle identities and centers for the current image.
        image_size: Image width and height in pixels.
        limit: Maximum number of rectangles in one round.

    Returns:
        A frozen partition whose member order follows image orientation.
    """
    if limit < 1:
        raise ValueError("round limit must be positive")
    width, height = (max(0.0, float(value)) for value in image_size)
    axis: Axis = "x" if width >= height else "y"
    entries = list(snapshots)
    if axis == "x":
        entries.sort(
            key=lambda item: (
                item.center_x,
                item.center_y,
                item.source_index,
                item.shape_id,
            )
        )

        def primary(item: RectangleSnapshot) -> float:
            """Return the horizontal ordering coordinate."""
            return item.center_x

        extent = width
    else:
        entries.sort(
            key=lambda item: (
                item.center_y,
                item.center_x,
                item.source_index,
                item.shape_id,
            )
        )

        def primary(item: RectangleSnapshot) -> float:
            """Return the vertical ordering coordinate."""
            return item.center_y

        extent = height

    sizes = _balanced_sizes(len(entries), limit)
    grouped: list[list[RectangleSnapshot]] = []
    offset = 0
    for size in sizes:
        grouped.append(entries[offset : offset + size])
        offset += size

    rounds = tuple(tuple(item.shape_id for item in group) for group in grouped)
    if not entries:
        return RoundPartition(
            axis=axis,
            limit=limit,
            rounds=rounds,
            boundaries=(RoundBoundary(axis, 0.0, extent),),
        )

    cuts = [0.0]
    for left, right in zip(grouped, grouped[1:]):
        cuts.append((primary(left[-1]) + primary(right[0])) / 2.0)
    cuts.append(extent)
    boundaries = tuple(
        RoundBoundary(axis, cuts[index], cuts[index + 1])
        for index in range(len(grouped))
    )
    return RoundPartition(axis, limit, rounds, boundaries)


class RoundReviewSession:
    """Mutable navigation state over one frozen image partition."""

    def __init__(self, default_limit: int = 10) -> None:
        if default_limit < 1:
            raise ValueError("round limit must be positive")
        self.applied_limit = int(default_limit)
        self.pending_limit = int(default_limit)
        self.image_key: str | None = None
        self.image_size = (0.0, 0.0)
        self.current_round = 0
        self.partition = build_round_partition(
            (), self.image_size, default_limit
        )

    def set_pending_limit(self, limit: int) -> None:
        """Set the limit applied when a different image is next loaded."""
        if limit < 1:
            raise ValueError("round limit must be positive")
        self.pending_limit = int(limit)

    def load_image(
        self,
        image_key: str,
        image_size: tuple[float, float],
        snapshots: Iterable[RectangleSnapshot],
    ) -> None:
        """Commit the pending limit and freeze a partition for a new image."""
        self.image_key = str(image_key)
        self.image_size = tuple(float(value) for value in image_size)
        self.applied_limit = self.pending_limit
        self.partition = build_round_partition(
            snapshots, self.image_size, self.applied_limit
        )
        self.current_round = 0

    @property
    def round_count(self) -> int:
        """Return the number of frozen rounds."""
        return self.partition.count

    @property
    def current_members(self) -> tuple[str, ...]:
        """Return identities assigned to the current round."""
        return self.partition.rounds[self.current_round]

    @property
    def current_boundary(self) -> RoundBoundary:
        """Return the current frozen boundary."""
        return self.partition.boundaries[self.current_round]

    def select_round(self, index: int) -> bool:
        """Select a valid zero-based round without changing the partition."""
        if not 0 <= index < self.round_count:
            return False
        changed = index != self.current_round
        self.current_round = index
        return changed

    def round_for(self, shape_id: str) -> int | None:
        """Return the frozen round for a shape identity."""
        return self.partition.round_for(shape_id)

    def add_to_current(self, shape_id: str) -> int:
        """Append one new review-window shape to the current round."""
        return self._append_to_round(shape_id, self.current_round)

    def add_by_position(self, snapshot: RectangleSnapshot) -> int:
        """Assign one main-window shape using the frozen spatial boundaries."""
        coordinate = (
            snapshot.center_x
            if self.partition.axis == "x"
            else snapshot.center_y
        )
        target = self.round_count - 1
        for index, boundary in enumerate(self.partition.boundaries):
            if coordinate <= boundary.end or index == self.round_count - 1:
                target = index
                break
        return self._append_to_round(snapshot.shape_id, target)

    def _append_to_round(self, shape_id: str, round_index: int) -> int:
        """Append an identity without moving existing members or boundaries."""
        existing = self.round_for(shape_id)
        if existing is not None:
            return existing
        rounds = [list(members) for members in self.partition.rounds]
        rounds[round_index].append(shape_id)
        self.partition = replace(
            self.partition,
            rounds=tuple(tuple(members) for members in rounds),
        )
        return round_index

    def remove(self, shape_id: str) -> bool:
        """Remove an identity while preserving empty rounds and boundaries."""
        found = False
        rounds = []
        for members in self.partition.rounds:
            filtered = tuple(
                member for member in members if member != shape_id
            )
            found = found or len(filtered) != len(members)
            rounds.append(filtered)
        if found:
            self.partition = replace(self.partition, rounds=tuple(rounds))
        return found


def rectangle_snapshots(shapes: Sequence[object]) -> list[RectangleSnapshot]:
    """Create partition inputs from live rectangle-like Shape objects."""
    snapshots = []
    for index, shape in enumerate(shapes):
        if getattr(shape, "shape_type", None) != "rectangle":
            continue
        shape_id = str(getattr(shape, "xanylabeling_shape_id", "") or "")
        points = tuple(getattr(shape, "points", ()) or ())
        if not shape_id or not points:
            continue
        x_values = [float(point.x()) for point in points]
        y_values = [float(point.y()) for point in points]
        snapshots.append(
            RectangleSnapshot(
                shape_id=shape_id,
                center_x=(min(x_values) + max(x_values)) / 2.0,
                center_y=(min(y_values) + max(y_values)) / 2.0,
                source_index=index,
            )
        )
    return snapshots
