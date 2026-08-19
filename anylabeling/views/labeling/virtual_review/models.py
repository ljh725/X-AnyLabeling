"""Data models for virtual target review.

The models deliberately do not import Qt or the mutable ``Shape`` class.  The
labeling widget adapts its shapes into :class:`VirtualShapeView` instances and
uses the stable runtime ids stored in those views for a review session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import math
from typing import Any, Iterable, Optional


class GroupIdMode(StrEnum):
    """Modes supported by the group-id criterion."""

    ANY = "any"
    VALID = "valid"
    MISSING = "missing"
    EXACT = "exact"


class PackingMode(StrEnum):
    """Named density presets for virtual-review page packing."""

    SINGLE = "single"
    BALANCED = "balanced"
    DENSE = "dense"


def normalize_group_id(value: Any) -> Optional[str]:
    """Return a canonical non-negative group id, or ``None``.

    Boolean values are rejected because ``bool`` is a subclass of ``int`` but
    is not a meaningful annotation group id.  Numeric strings are accepted to
    tolerate JSON files that serialize ids as strings.
    """

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return str(value) if value >= 0 else None
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return str(int(text))
    return None


@dataclass(frozen=True)
class VirtualShapeView:
    """Immutable shape information needed to build virtual tasks."""

    shape_id: str
    label: str
    shape_type: str
    group_id: Any = None
    width: Optional[float] = None
    height: Optional[float] = None
    bbox: Optional[tuple[float, float, float, float]] = None
    base_visible: bool = True

    @property
    def normalized_group_id(self) -> Optional[str]:
        """Return the canonical group id for this shape, if valid."""

        return normalize_group_id(self.group_id)


@dataclass(frozen=True)
class VirtualTaskCriteria:
    """Anchor-selection criteria for one virtual review session."""

    labels: frozenset[str] = field(default_factory=frozenset)
    shape_types: frozenset[str] = field(default_factory=frozenset)
    group_id_mode: GroupIdMode = GroupIdMode.ANY
    group_id: Optional[str] = None
    min_width: Optional[float] = None
    max_width: Optional[float] = None
    min_height: Optional[float] = None
    max_height: Optional[float] = None

    def __post_init__(self) -> None:
        """Normalize collection and scalar inputs for predictable matching."""

        object.__setattr__(
            self, "labels", frozenset(str(x) for x in self.labels)
        )
        object.__setattr__(
            self,
            "shape_types",
            frozenset(str(x) for x in self.shape_types),
        )
        mode = self.group_id_mode
        if not isinstance(mode, GroupIdMode):
            mode = GroupIdMode(str(mode))
        object.__setattr__(self, "group_id_mode", mode)
        object.__setattr__(
            self,
            "group_id",
            None if self.group_id is None else str(self.group_id),
        )
        for name in ("min_width", "max_width", "min_height", "max_height"):
            value = getattr(self, name)
            if value is not None:
                value = float(value)
                if not math.isfinite(value) or value < 0:
                    raise ValueError(
                        f"{name} must be a finite non-negative number"
                    )
            object.__setattr__(self, name, value)
        if (
            self.min_width is not None
            and self.max_width is not None
            and self.min_width > self.max_width
        ):
            raise ValueError("min_width must not exceed max_width")
        if (
            self.min_height is not None
            and self.max_height is not None
            and self.min_height > self.max_height
        ):
            raise ValueError("min_height must not exceed max_height")
        if self.group_id_mode is GroupIdMode.EXACT and self.group_id is None:
            raise ValueError("group_id is required for exact group-id mode")


@dataclass(frozen=True)
class VirtualTask:
    """One immutable review task produced for an image."""

    task_id: str
    anchor_id: str
    member_ids: tuple[str, ...]
    group_id: Optional[str] = None
    anchor_index: int = 0
    bbox: Optional[tuple[float, float, float, float]] = None
    anchor_bbox: Optional[tuple[float, float, float, float]] = None

    def contains(self, shape_id: str) -> bool:
        """Return whether ``shape_id`` belongs to this task."""

        return shape_id in self.member_ids


def union_bboxes(
    bboxes: Iterable[Optional[tuple[float, float, float, float]]],
) -> Optional[tuple[float, float, float, float]]:
    """Return the union of valid ``(left, top, right, bottom)`` boxes."""

    valid = [box for box in bboxes if box is not None]
    if not valid:
        return None
    return (
        min(box[0] for box in valid),
        min(box[1] for box in valid),
        max(box[2] for box in valid),
        max(box[3] for box in valid),
    )


@dataclass(frozen=True)
class VirtualPackingOptions:
    """Validated screen-space constraints for virtual page packing."""

    mode: PackingMode = PackingMode.BALANCED
    max_tasks_per_page: Optional[int] = None
    min_projected_anchor_px: Optional[float] = None
    min_projected_gap_px: Optional[float] = None
    fit_margin: float = 1.35

    def __post_init__(self) -> None:
        """Normalize a preset and reject unsafe numeric options."""
        mode = self.mode
        if not isinstance(mode, PackingMode):
            mode = PackingMode(str(mode))
        object.__setattr__(self, "mode", mode)
        defaults = {
            PackingMode.SINGLE: (1, 0.0, 0.0),
            PackingMode.BALANCED: (2, 160.0, 48.0),
            PackingMode.DENSE: (3, 120.0, 32.0),
        }
        default_max, default_size, default_gap = defaults[mode]
        raw_max_tasks = self.max_tasks_per_page
        if raw_max_tasks is None:
            max_tasks = default_max
        else:
            if isinstance(raw_max_tasks, bool):
                raise ValueError("max_tasks_per_page must be an integer")
            try:
                max_tasks = int(raw_max_tasks)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "max_tasks_per_page must be an integer"
                ) from exc
            if float(raw_max_tasks) != max_tasks:
                raise ValueError("max_tasks_per_page must be an integer")
        if mode is PackingMode.SINGLE:
            max_tasks = 1
        if max_tasks < 1 or max_tasks > 3:
            raise ValueError("max_tasks_per_page must be between 1 and 3")
        object.__setattr__(self, "max_tasks_per_page", max_tasks)
        for name, default in (
            ("min_projected_anchor_px", default_size),
            ("min_projected_gap_px", default_gap),
        ):
            raw_value = getattr(self, name)
            value = float(default if raw_value is None else raw_value)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
            object.__setattr__(self, name, value)
        margin = float(self.fit_margin)
        if not math.isfinite(margin) or margin <= 0:
            raise ValueError("fit_margin must be finite and positive")
        object.__setattr__(self, "fit_margin", margin)

    @classmethod
    def preset(cls, mode: PackingMode | str) -> "VirtualPackingOptions":
        """Return conservative defaults for a named density mode."""
        return cls(mode=PackingMode(mode))


@dataclass(frozen=True)
class VirtualReviewPage:
    """One immutable page containing one or more atomic review tasks."""

    page_id: str
    task_ids: tuple[str, ...]
    member_ids: tuple[str, ...]
    anchor_ids: tuple[str, ...]
    bbox: Optional[tuple[float, float, float, float]] = None
    projected_scale: float = 0.0
    min_projected_anchor_px: float = 0.0
    fallback: bool = False

    @property
    def task_count(self) -> int:
        """Return the number of atomic tasks on this page."""
        return len(self.task_ids)


@dataclass(frozen=True)
class VirtualPackingResult:
    """Immutable output and diagnostics from one packing operation."""

    pages: tuple[VirtualReviewPage, ...]
    atomic_task_count: int
    singleton_fallback_count: int = 0

    @property
    def page_count(self) -> int:
        """Return the generated page count."""
        return len(self.pages)

    @property
    def combined_page_count(self) -> int:
        """Return pages containing more than one atomic task."""
        return sum(page.task_count > 1 for page in self.pages)


__all__ = [
    "GroupIdMode",
    "PackingMode",
    "VirtualShapeView",
    "VirtualPackingOptions",
    "VirtualPackingResult",
    "VirtualReviewPage",
    "VirtualTask",
    "VirtualTaskCriteria",
    "normalize_group_id",
    "union_bboxes",
]
