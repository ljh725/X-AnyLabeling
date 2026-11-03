"""Pure screen-space layout for rectangle-size overlay boxes."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from .models import BBox, CandidateId

RectXYWH = Tuple[float, float, float, float]
_SPATIAL_CELL_SIZE_PX = 48.0


@dataclass(frozen=True)
class OverlayLayoutItem:
    """Measured overlay box and its target geometry.

    Attributes:
        candidate_id: Stable identity copied from the source issue.
        bbox: Target rectangle in the same screen space as the viewport.
        box_width: Measured overlay width in screen pixels.
        box_height: Measured overlay height in screen pixels.
        label_rect: Optional standard label box as ``(x, y, width, height)``.
    """

    candidate_id: CandidateId
    bbox: BBox
    box_width: float
    box_height: float
    label_rect: Optional[RectXYWH] = None


@dataclass(frozen=True)
class OverlayLayoutPlacement:
    """Final screen-space placement for one overlay item."""

    candidate_id: CandidateId
    rect: RectXYWH


def _anchor_fits(
    x: float,
    y: float,
    width: float,
    height: float,
    viewport: BBox,
) -> bool:
    """Return whether a box fits completely inside the viewport."""
    vx_min, vy_min, vx_max, vy_max = viewport
    return (
        x >= vx_min
        and y >= vy_min
        and x + width <= vx_max
        and y + height <= vy_max
    )


def _clamp_into(
    x: float,
    y: float,
    width: float,
    height: float,
    viewport: BBox,
) -> tuple[float, float]:
    """Clamp a box top-left into the viewport's available near corner."""
    vx_min, vy_min, vx_max, vy_max = viewport
    x_max = max(vx_min, vx_max - width)
    y_max = max(vy_min, vy_max - height)
    return (
        min(max(x, vx_min), x_max),
        min(max(y, vy_min), y_max),
    )


def pick_overlay_anchor(
    bbox: BBox,
    text_width: float,
    text_height: float,
    gap: float,
    viewport: BBox,
    label_rect: Optional[RectXYWH] = None,
) -> tuple[float, float]:
    """Choose the legacy-compatible preferred anchor for one overlay.

    Args:
        bbox: Target rectangle in a consistent coordinate space.
        text_width: Complete overlay box width.
        text_height: Complete overlay box height.
        gap: Gap between the overlay and its anchor geometry.
        viewport: Visible ``(x_min, y_min, x_max, y_max)`` bounds.
        label_rect: Optional standard label box in ``(x, y, w, h)`` form.

    Returns:
        Overlay top-left position.
    """
    x_min, y_min, _x_max, _y_max = bbox
    if label_rect is not None:
        label_x, label_y, label_width, _label_height = label_rect
        above_y = label_y - text_height - gap
        for candidate_x in (
            label_x,
            label_x + (label_width - text_width) / 2.0,
            label_x + label_width - text_width,
        ):
            if _anchor_fits(
                candidate_x,
                above_y,
                text_width,
                text_height,
                viewport,
            ):
                return (candidate_x, above_y)

    candidates = (
        (x_min, y_min - text_height - gap),
        (x_min, y_min + gap),
        (x_min - text_width - gap, y_min - text_height - gap),
        (x_min + gap, y_min + gap),
    )
    for candidate_x, candidate_y in candidates:
        if _anchor_fits(
            candidate_x,
            candidate_y,
            text_width,
            text_height,
            viewport,
        ):
            return (candidate_x, candidate_y)
    return _clamp_into(
        x_min,
        y_min - text_height - gap,
        text_width,
        text_height,
        viewport,
    )


def _candidate_anchors(
    item: OverlayLayoutItem,
    viewport: BBox,
    gap: float,
    stack_limit: int,
) -> tuple[tuple[float, float], ...]:
    """Return deterministic preferred and collision-fallback anchors."""
    x_min, y_min, x_max, y_max = item.bbox
    width = item.box_width
    height = item.box_height
    primary = pick_overlay_anchor(
        item.bbox,
        width,
        height,
        gap,
        viewport,
        label_rect=item.label_rect,
    )
    candidates = [primary]

    if item.label_rect is not None:
        label_x, label_y, label_width, label_height = item.label_rect
        candidates.extend(
            [
                (label_x, label_y - height - gap),
                (
                    label_x + (label_width - width) / 2.0,
                    label_y - height - gap,
                ),
                (
                    label_x + label_width - width,
                    label_y - height - gap,
                ),
                (label_x, label_y + label_height + gap),
            ]
        )

    center_x = (x_min + x_max - width) / 2.0
    right_x = x_max - width
    candidates.extend(
        [
            (x_min, y_min - height - gap),
            (center_x, y_min - height - gap),
            (right_x, y_min - height - gap),
            (x_min + gap, y_min + gap),
            (x_max - width - gap, y_min + gap),
            (x_min, y_max + gap),
            (center_x, y_max + gap),
            (right_x, y_max + gap),
            (x_min - width - gap, y_min),
            (x_max + gap, y_min),
            (x_min + gap, y_max - height - gap),
            (x_max - width - gap, y_max - height - gap),
        ]
    )

    stack_step = height + gap
    for step in range(1, stack_limit + 1):
        candidates.append((primary[0], primary[1] + step * stack_step))
        candidates.append((primary[0], primary[1] - step * stack_step))

    unique = []
    seen = set()
    for candidate_x, candidate_y in candidates:
        clamped = _clamp_into(
            candidate_x,
            candidate_y,
            width,
            height,
            viewport,
        )
        key = (round(clamped[0], 6), round(clamped[1], 6))
        if key in seen:
            continue
        seen.add(key)
        unique.append(clamped)
    return tuple(unique)


def _rectangles_collide(
    first: RectXYWH,
    second: RectXYWH,
    collision_gap: float,
) -> bool:
    """Return whether rectangles overlap or violate the requested gap."""
    first_x, first_y, first_width, first_height = first
    second_x, second_y, second_width, second_height = second
    return not (
        first_x + first_width + collision_gap <= second_x
        or second_x + second_width + collision_gap <= first_x
        or first_y + first_height + collision_gap <= second_y
        or second_y + second_height + collision_gap <= first_y
    )


def _intersection_area(first: RectXYWH, second: RectXYWH) -> float:
    """Return ordinary intersection area for two rectangles."""
    first_x, first_y, first_width, first_height = first
    second_x, second_y, second_width, second_height = second
    overlap_width = max(
        0.0,
        min(first_x + first_width, second_x + second_width)
        - max(first_x, second_x),
    )
    overlap_height = max(
        0.0,
        min(first_y + first_height, second_y + second_height)
        - max(first_y, second_y),
    )
    return overlap_width * overlap_height


class _SpatialRectIndex:
    """Index occupied rectangles by screen-space grid cells.

    The layout algorithm still performs exact collision and overlap checks.
    The grid only removes rectangles that cannot geometrically contribute, so
    placement results remain identical to a full occupied-list scan.
    """

    def __init__(self, cell_size: float) -> None:
        """Initialize an empty index with one positive finite cell size."""
        self._cell_size = cell_size
        self._rects: list[RectXYWH] = []
        self._indices_by_cell: dict[tuple[int, int], list[int]] = {}

    def add(self, rect: RectXYWH) -> None:
        """Add one occupied rectangle to every grid cell it intersects."""
        rect_index = len(self._rects)
        self._rects.append(rect)
        for cell in self._cells_for(rect):
            self._indices_by_cell.setdefault(cell, []).append(rect_index)

    def nearby(
        self,
        rect: RectXYWH,
        *,
        padding: float = 0.0,
    ) -> tuple[RectXYWH, ...]:
        """Return occupied rectangles that may overlap a padded query."""
        indices = set()
        for cell in self._cells_for(rect, padding=padding):
            indices.update(self._indices_by_cell.get(cell, ()))
        return tuple(self._rects[index] for index in sorted(indices))

    def _cells_for(
        self,
        rect: RectXYWH,
        *,
        padding: float = 0.0,
    ) -> tuple[tuple[int, int], ...]:
        """Return all grid cells touched by one optionally padded rectangle."""
        x, y, width, height = rect
        left = math.floor((x - padding) / self._cell_size)
        top = math.floor((y - padding) / self._cell_size)
        right = math.floor((x + width + padding) / self._cell_size)
        bottom = math.floor((y + height + padding) / self._cell_size)
        return tuple(
            (cell_x, cell_y)
            for cell_y in range(top, bottom + 1)
            for cell_x in range(left, right + 1)
        )


def _validate_layout(
    items: tuple[OverlayLayoutItem, ...],
    viewport: BBox,
    gap: float,
    collision_gap: float,
) -> None:
    """Validate layout inputs before producing partial output."""
    values = tuple(float(value) for value in viewport)
    if len(values) != 4 or not all(math.isfinite(value) for value in values):
        raise ValueError("Overlay viewport must contain four finite values")
    if values[2] < values[0] or values[3] < values[1]:
        raise ValueError("Overlay viewport must be normalized")
    if not math.isfinite(gap) or gap < 0:
        raise ValueError("Overlay gap must be finite and non-negative")
    if not math.isfinite(collision_gap) or collision_gap < 0:
        raise ValueError(
            "Overlay collision_gap must be finite and non-negative"
        )

    candidate_ids = set()
    for item in items:
        try:
            duplicate = item.candidate_id in candidate_ids
            candidate_ids.add(item.candidate_id)
        except TypeError as exc:
            raise ValueError("Overlay candidate_id must be hashable") from exc
        if duplicate:
            raise ValueError("Overlay candidate_id values must be unique")
        geometry = tuple(float(value) for value in item.bbox)
        dimensions = (float(item.box_width), float(item.box_height))
        if len(geometry) != 4 or not all(
            math.isfinite(value) for value in geometry + dimensions
        ):
            raise ValueError("Overlay item geometry must be finite")
        if geometry[2] < geometry[0] or geometry[3] < geometry[1]:
            raise ValueError("Overlay item bbox must be normalized")
        if dimensions[0] <= 0 or dimensions[1] <= 0:
            raise ValueError("Overlay box dimensions must be positive")
        if item.label_rect is not None:
            label_values = tuple(float(value) for value in item.label_rect)
            if len(label_values) != 4 or not all(
                math.isfinite(value) for value in label_values
            ):
                raise ValueError("Overlay label_rect must be finite")
            if label_values[2] < 0 or label_values[3] < 0:
                raise ValueError(
                    "Overlay label_rect dimensions cannot be negative"
                )


def layout_overlay_items(
    items: Iterable[OverlayLayoutItem],
    viewport: BBox,
    *,
    gap: float = 6.0,
    collision_gap: float = 4.0,
) -> Tuple[OverlayLayoutPlacement, ...]:
    """Lay out every measured overlay without silently dropping dense items.

    Input order is preserved. Each item first tries the legacy single-box
    anchor, then deterministic alternatives around its target and vertical
    stacking positions. If no collision-free position exists, the candidate
    with the smallest total overlap area is selected.

    Args:
        items: Measured overlay items in desired paint order.
        viewport: Visible screen-space bounds.
        gap: Anchor gap around target/label geometry.
        collision_gap: Minimum spacing between overlay boxes.

    Returns:
        Immutable placements in input order.

    Raises:
        ValueError: If geometry, identities, or spacing values are invalid.
    """
    item_tuple = tuple(items)
    viewport_tuple = tuple(float(value) for value in viewport)
    numeric_gap = float(gap)
    numeric_collision_gap = float(collision_gap)
    _validate_layout(
        item_tuple,
        viewport_tuple,
        numeric_gap,
        numeric_collision_gap,
    )

    occupied = _SpatialRectIndex(_SPATIAL_CELL_SIZE_PX)
    placements = []
    # Bound candidate generation while the spatial index keeps ordinary
    # collision queries close to linear for dispersed and moderately dense
    # annotations. Exact overlap scoring is restricted to nearby cells.
    # The renderer still retains every item through the minimum-overlap
    # fallback when the finite collision-free candidate set is exhausted.
    stack_limit = min(max(1, len(item_tuple)), 16)
    for item in item_tuple:
        anchors = _candidate_anchors(
            item,
            viewport_tuple,
            numeric_gap,
            stack_limit,
        )
        candidate_rects = tuple(
            (
                anchor_x,
                anchor_y,
                float(item.box_width),
                float(item.box_height),
            )
            for anchor_x, anchor_y in anchors
        )
        chosen = next(
            (
                rect
                for rect in candidate_rects
                if not any(
                    _rectangles_collide(
                        rect,
                        existing,
                        numeric_collision_gap,
                    )
                    for existing in occupied.nearby(
                        rect,
                        padding=numeric_collision_gap,
                    )
                )
            ),
            None,
        )
        if chosen is None:
            chosen = min(
                candidate_rects,
                key=lambda rect: sum(
                    _intersection_area(rect, existing)
                    for existing in occupied.nearby(rect)
                ),
            )
        occupied.add(chosen)
        placements.append(
            OverlayLayoutPlacement(
                candidate_id=item.candidate_id,
                rect=chosen,
            )
        )
    return tuple(placements)


__all__ = [
    "OverlayLayoutItem",
    "OverlayLayoutPlacement",
    "RectXYWH",
    "layout_overlay_items",
    "pick_overlay_anchor",
]
