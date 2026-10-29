"""Shared viewport memory keyed by image size.

One review round usually walks a folder of images that all share a single
camera resolution. Remembering the viewport per file forces the user to
re-aim the view on every page, so this store keeps one viewport per exact
image size instead: every image of the same size reuses the last viewport the
user actually chose, and a differently sized image starts from its own group.

The store is deliberately Qt-free and session-scoped. It never writes to disk;
callers decide when a round begins and when to forget a group.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Optional, Tuple

SizeKey = Tuple[int, int]
DEFAULT_MAX_GROUPS = 64


@dataclass(frozen=True)
class SharedViewState:
    """Immutable image-coordinate viewport snapshot.

    Attributes:
        zoom_mode: Viewport zoom mode, matching ``LabelingWidget`` constants.
        zoom_value: Zoom percentage, always positive.
        center_x: Image-space X coordinate shown at the viewport centre.
        center_y: Image-space Y coordinate shown at the viewport centre.
    """

    zoom_mode: int
    zoom_value: float
    center_x: float
    center_y: float

    def __post_init__(self) -> None:
        """Validate the snapshot before it can enter the store."""
        if isinstance(self.zoom_mode, bool) or not isinstance(
            self.zoom_mode, int
        ):
            raise TypeError("zoom_mode must be an integer")
        if self.zoom_mode not in (0, 1, 2):
            raise ValueError(f"unsupported zoom mode: {self.zoom_mode}")
        if isinstance(self.zoom_value, bool) or not isinstance(
            self.zoom_value, (int, float)
        ):
            raise TypeError("zoom_value must be a number")
        zoom_value = float(self.zoom_value)
        if not math.isfinite(zoom_value) or zoom_value <= 0:
            raise ValueError("zoom_value must be positive and finite")
        for name in ("center_x", "center_y"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a number")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        object.__setattr__(self, "zoom_value", zoom_value)
        object.__setattr__(self, "center_x", float(self.center_x))
        object.__setattr__(self, "center_y", float(self.center_y))


class SharedViewStateStore:
    """Keep at most one viewport per exact image size.

    Groups are evicted least-recently-used first once ``max_groups`` is
    reached, so walking a folder of thousands of differently sized images
    cannot grow the store without bound.
    """

    def __init__(self, *, max_groups: int = DEFAULT_MAX_GROUPS) -> None:
        """Initialize an empty session store.

        Args:
            max_groups: Upper bound on remembered size groups.

        Raises:
            TypeError: If ``max_groups`` is not an integer.
            ValueError: If ``max_groups`` is not positive.
        """
        if isinstance(max_groups, bool) or not isinstance(max_groups, int):
            raise TypeError("max_groups must be an integer")
        if max_groups <= 0:
            raise ValueError("max_groups must be positive")
        self._max_groups = max_groups
        self._states: OrderedDict[SizeKey, SharedViewState] = OrderedDict()

    @staticmethod
    def size_key(width: object, height: object) -> Optional[SizeKey]:
        """Return the exact ``(width, height)`` key, or ``None`` if invalid."""
        if isinstance(width, bool) or isinstance(height, bool):
            return None
        try:
            width_value = int(width)
            height_value = int(height)
        except (TypeError, ValueError):
            return None
        if width_value <= 0 or height_value <= 0:
            return None
        return (width_value, height_value)

    def remember(
        self,
        size: Optional[SizeKey],
        state: SharedViewState,
    ) -> None:
        """Store one group viewport, marking the group most recently used.

        Args:
            size: Target image size key, or ``None`` to ignore the update.
            state: Viewport snapshot chosen by the user.

        Raises:
            TypeError: If ``state`` is not a ``SharedViewState``.
        """
        if not isinstance(state, SharedViewState):
            raise TypeError("state must be a SharedViewState")
        if size is None:
            return
        self._states[size] = state
        self._states.move_to_end(size)
        while len(self._states) > self._max_groups:
            self._states.popitem(last=False)

    def recall(self, size: Optional[SizeKey]) -> Optional[SharedViewState]:
        """Return the remembered viewport for one size, if any.

        Args:
            size: Target image size key.

        Returns:
            The stored snapshot, or ``None`` when the group is unknown.
        """
        if size is None:
            return None
        state = self._states.get(size)
        if state is not None:
            self._states.move_to_end(size)
        return state

    def forget(self, size: Optional[SizeKey]) -> bool:
        """Drop one size group.

        Args:
            size: Target image size key.

        Returns:
            True when a stored group was actually removed.
        """
        if size is None:
            return False
        return self._states.pop(size, None) is not None

    def clear(self) -> None:
        """Drop every group, e.g. when a new dataset round begins."""
        self._states.clear()

    def __len__(self) -> int:
        """Return the number of remembered size groups."""
        return len(self._states)

    def snapshot(self) -> Mapping[SizeKey, SharedViewState]:
        """Return a read-only copy for diagnostics and tests."""
        return dict(self._states)


__all__ = [
    "DEFAULT_MAX_GROUPS",
    "SharedViewState",
    "SharedViewStateStore",
    "SizeKey",
]
