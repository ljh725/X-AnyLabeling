"""Three label-layout algorithms for pose keypoint labels.

Pure functions operating on :class:`PoseLabelItem` lists.  No Qt widget
dependency beyond ``QtCore`` geometry types so the algorithms can be
unit-tested in isolation.

The three modes mirror the HTML prototype ``0616_code.html``:

- **direct** – place each label along its body-relative direction.
- **anti**  – *direct* + collision avoidance (push outward until no overlap).
- **column** – split into left/right/top columns outside the person bbox.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from PyQt6 import QtCore

from .pose_constants import (
    BODY_PARTS,
    COCO_KEYPOINT_INDEX,
    DIRECTION_VECTORS,
    LAYOUT_PRIORITY,
    LABEL_TO_BODY_PART,
)
from .pose_category_layout import layout_category

# Type aliases
MidLine = Optional[Tuple[float, float]]  # (mid_x, shoulder_distance)


@dataclass
class PoseLabelItem:
    """One keypoint label candidate for the layout pass.

    All coordinates are in **image space** (the painter is already
    scaled by ``Canvas.scale``).  ``rect`` is modified in-place by the
    layout functions.
    """

    shape_ref: object
    label: str
    keypoint_index: int
    group_id: Optional[int]
    anchor: QtCore.QPointF
    rect: QtCore.QRect
    direction: str = "up"
    leader_start: QtCore.QPointF = field(
        default_factory=lambda: QtCore.QPointF(0, 0)
    )
    leader_end: QtCore.QPoint = field(
        default_factory=lambda: QtCore.QPoint(0, 0)
    )
    occluded: bool = False
    color_hex: str = "#ffffff"

    @property
    def anchor_x(self) -> float:
        """X coordinate of the keypoint anchor."""
        return self.anchor.x()

    @property
    def anchor_y(self) -> float:
        """Y coordinate of the keypoint anchor."""
        return self.anchor.y()


# -----------------------------------------------------------------------
# Midline computation
# -----------------------------------------------------------------------


def compute_midline(
    keypoint_positions: Dict[int, QtCore.QPointF],
) -> MidLine:
    """Compute the body midline from shoulder keypoints.

    Args:
        keypoint_positions: Mapping COCO index -> position.  Only
            indices 5 (l_sho) and 6 (r_sho) are used; falls back to
            nose (0) if shoulders are missing.

    Returns:
        ``(mid_x, shoulder_distance)`` or ``None`` if no reference
        keypoint is available.
    """
    left_sho = keypoint_positions.get(5)
    right_sho = keypoint_positions.get(6)
    if left_sho is not None and right_sho is not None:
        mx = (left_sho.x() + right_sho.x()) / 2.0
        sd = abs(right_sho.x() - left_sho.x())
        if sd < 1:
            sd = 60.0
        return (mx, sd)
    nose = keypoint_positions.get(0)
    if nose is not None:
        return (nose.x(), 60.0)
    return None


# -----------------------------------------------------------------------
# Direction computation
# -----------------------------------------------------------------------


def compute_direction(
    keypoint_index: int,
    pos: QtCore.QPointF,
    mid: MidLine,
) -> str:
    """Determine the outward direction for a keypoint.

    Logic mirrors ``compDir`` in the HTML prototype.
    """
    if mid is None:
        return "up"
    mx, sd = mid
    rx = pos.x() - mx
    threshold = sd * 0.15
    is_head = keypoint_index <= 4
    is_lower = keypoint_index >= 11
    if abs(rx) <= threshold:
        return "up"
    if rx < 0:
        if is_head:
            return "left-up"
        if is_lower:
            return "left-down"
        return "left"
    if is_head:
        return "right-up"
    if is_lower:
        return "right-down"
    return "right"


# -----------------------------------------------------------------------
# Geometry helpers
# -----------------------------------------------------------------------


def _rects_overlap(a: QtCore.QRect, b: QtCore.QRect) -> bool:
    """Return ``True`` when two rects intersect."""
    return a.intersects(b)


def _any_overlap(rect: QtCore.QRect, placed: List[QtCore.QRect]) -> bool:
    """Return ``True`` if *rect* overlaps any rect in *placed*."""
    return any(_rects_overlap(rect, p) for p in placed)


def _count_overlaps(items: List[PoseLabelItem]) -> int:
    """Count the number of overlapping label pairs."""
    count = 0
    n = len(items)
    for i in range(n):
        for j in range(i + 1, n):
            if _rects_overlap(items[i].rect, items[j].rect):
                count += 1
    return count


def _mark_occluded(items: List[PoseLabelItem]) -> None:
    """Set ``occluded`` flag on items that overlap at least one other."""
    n = len(items)
    for i in range(n):
        for j in range(n):
            if i != j and _rects_overlap(items[i].rect, items[j].rect):
                items[i].occluded = True
                break


# -----------------------------------------------------------------------
# Layout 1: direct
# -----------------------------------------------------------------------


def layout_direct(
    items: List[PoseLabelItem],
    mid: MidLine,
    leader_length: float,
    gap: float = 2.0,
) -> List[PoseLabelItem]:
    """Place labels along each keypoint's outward direction.

    No collision avoidance.  Leader lines are drawn from the keypoint
    to the label edge.
    """
    for item in items:
        vec = DIRECTION_VECTORS.get(item.direction, (0, -1))
        lsx = item.anchor_x + gap * vec[0]
        lsy = item.anchor_y + gap * vec[1]
        lex = item.anchor_x + (gap + leader_length) * vec[0]
        ley = item.anchor_y + (gap + leader_length) * vec[1]
        _place_rect(item, lex, ley, lsx, lsy)
    return items


def _place_rect(
    item: PoseLabelItem,
    edge_x: float,
    edge_y: float,
    lead_start_x: float,
    lead_start_y: float,
) -> None:
    """Position ``item.rect`` relative to the leader endpoint.

    The rect is aligned so its edge touches the leader endpoint,
    depending on the item's direction.
    """
    w = item.rect.width()
    h = item.rect.height()
    d = item.direction
    if d in ("left", "left-up", "left-down"):
        nx = edge_x - w
        ny = edge_y - h / 2
    elif d in ("right", "right-up", "right-down"):
        nx = edge_x
        ny = edge_y - h / 2
    elif d == "up":
        nx = edge_x - w / 2
        ny = edge_y - h
    else:
        nx = edge_x - w / 2
        ny = edge_y
    item.rect.moveTo(int(nx), int(ny))
    item.leader_start = QtCore.QPointF(lead_start_x, lead_start_y)
    item.leader_end = QtCore.QPoint(int(edge_x), int(edge_y))


# -----------------------------------------------------------------------
# Layout 2: anti-occlusion
# -----------------------------------------------------------------------


def layout_anti(
    items: List[PoseLabelItem],
    mid: MidLine,
    leader_length: float,
    gap: float = 2.0,
    search_step: float = 4.0,
    search_max: float = 120.0,
) -> List[PoseLabelItem]:
    """Direct placement + collision avoidance.

    Items are processed in priority order (limbs first, face last).
    Each item is pushed outward along its direction until no overlap
    with already-placed items is found.
    """
    layout_direct(items, mid, leader_length, gap)
    priority_sorted = sorted(
        items,
        key=lambda it: (
            LAYOUT_PRIORITY.index(it.keypoint_index)
            if it.keypoint_index in LAYOUT_PRIORITY
            else len(LAYOUT_PRIORITY)
        ),
    )
    placed: List[QtCore.QRect] = []
    for item in priority_sorted:
        vec = DIRECTION_VECTORS.get(item.direction, (0, -1))
        found = False
        extra = 0.0
        while extra <= search_max:
            ex = item.anchor_x + (gap + leader_length + extra) * vec[0]
            ey = item.anchor_y + (gap + leader_length + extra) * vec[1]
            w = item.rect.width()
            h = item.rect.height()
            d = item.direction
            if d in ("left", "left-up", "left-down"):
                nx, ny = ex - w, ey - h / 2
            elif d in ("right", "right-up", "right-down"):
                nx, ny = ex, ey - h / 2
            elif d == "up":
                nx, ny = ex - w / 2, ey - h
            else:
                nx, ny = ex - w / 2, ey
            candidate = QtCore.QRect(int(nx), int(ny), w, h)
            if not _any_overlap(candidate, placed):
                lsx = item.anchor_x + gap * vec[0]
                lsy = item.anchor_y + gap * vec[1]
                _place_rect(item, ex, ey, lsx, lsy)
                found = True
                break
            extra += search_step
        if not found:
            for e2 in range(
                int(search_step), int(search_max) + 1, int(search_step)
            ):
                for pv in ((0, -1), (0, 1)):
                    nx2 = item.rect.x() + e2 * pv[0]
                    ny2 = item.rect.y() + e2 * pv[1]
                    candidate2 = QtCore.QRect(
                        nx2, ny2, item.rect.width(), item.rect.height()
                    )
                    if not _any_overlap(candidate2, placed):
                        item.rect.moveTo(nx2, ny2)
                        found = True
                        break
                if found:
                    break
        placed.append(QtCore.QRect(item.rect))
    return items


# -----------------------------------------------------------------------
# Layout 3: column
# -----------------------------------------------------------------------


def layout_column(
    items: List[PoseLabelItem],
    mid: MidLine,
    bbox: Optional[QtCore.QRectF],
    column_gap: float,
) -> List[PoseLabelItem]:
    """Split labels into left / right / top columns.

    Labels are stacked vertically outside the person bounding box.
    """
    if not items:
        return items
    if bbox is None:
        bbox = _compute_bbox(items)
    if bbox is None:
        return items
    gap = column_gap
    max_w = max(it.rect.width() for it in items)
    left_items: List[PoseLabelItem] = []
    right_items: List[PoseLabelItem] = []
    top_items: List[PoseLabelItem] = []
    for item in items:
        if mid is not None:
            rx = item.anchor_x - mid[0]
            threshold = mid[1] * 0.15
        else:
            rx = 0
            threshold = 1
        if abs(rx) <= threshold and item.keypoint_index <= 4:
            top_items.append(item)
        elif rx < 0:
            left_items.append(item)
        else:
            right_items.append(item)
    left_items.sort(key=lambda it: it.anchor_y)
    right_items.sort(key=lambda it: it.anchor_y)
    top_items.sort(key=lambda it: it.anchor_y)
    bbox_x = bbox.x()
    bbox_y = bbox.y()
    bbox_x2 = bbox.x() + bbox.width()
    lx = bbox_x - max_w - gap
    cy = bbox_y
    for item in left_items:
        ny = max(item.anchor_y - item.rect.height() / 2, cy)
        item.rect.moveTo(int(lx), int(ny))
        item.leader_start = QtCore.QPointF(item.anchor_x - 2, item.anchor_y)
        item.leader_end = QtCore.QPoint(
            item.rect.right(), int(item.rect.y() + item.rect.height() / 2)
        )
        cy = item.rect.bottom() + gap
    rx2 = bbox_x2 + gap
    cy = bbox_y
    for item in right_items:
        ny = max(item.anchor_y - item.rect.height() / 2, cy)
        item.rect.moveTo(int(rx2), int(ny))
        item.leader_start = QtCore.QPointF(item.anchor_x + 2, item.anchor_y)
        item.leader_end = QtCore.QPoint(
            item.rect.left(), int(item.rect.y() + item.rect.height() / 2)
        )
        cy = item.rect.bottom() + gap
    tcx = (bbox_x + bbox_x2) / 2
    cy = bbox_y
    for i, item in enumerate(top_items):
        col = -1 if i % 2 == 0 else 1
        nx = tcx + col * (max_w / 2 + gap / 2) - item.rect.width() / 2
        ny = cy - item.rect.height() - gap
        item.rect.moveTo(int(nx), int(ny))
        item.leader_start = QtCore.QPointF(item.anchor_x, item.anchor_y - 2)
        item.leader_end = QtCore.QPoint(
            int(item.rect.x() + item.rect.width() / 2), item.rect.bottom()
        )
        cy = item.rect.y()
    return items


def _compute_bbox(
    items: List[PoseLabelItem],
) -> Optional[QtCore.QRectF]:
    """Compute the bounding rect of all item anchors with padding."""
    if not items:
        return None
    xs = [it.anchor_x for it in items]
    ys = [it.anchor_y for it in items]
    pad = 20.0
    return QtCore.QRectF(
        min(xs) - pad,
        min(ys) - pad,
        max(xs) - min(xs) + 2 * pad,
        max(ys) - min(ys) + 2 * pad,
    )


# -----------------------------------------------------------------------
# Public dispatcher
# -----------------------------------------------------------------------


def apply_layout(
    items: List[PoseLabelItem],
    mid: MidLine,
    bbox: Optional[QtCore.QRectF],
    layout_mode: str,
    leader_length: float,
    column_gap: float = 8.0,
) -> Tuple[List[PoseLabelItem], int]:
    """Dispatch to the correct layout function and return overlap count.

    Args:
        items: Label candidates (rects will be modified in-place).
        mid: Body midline from :func:`compute_midline`.
        bbox: Person bounding rect (for column layout).
        layout_mode: ``"direct"`` | ``"anti"`` | ``"column"`` |
            ``"category"``.
        leader_length: Base leader length in image px.
        column_gap: Vertical gap for column layout.

    Returns:
        ``(items, overlap_count)``.
    """
    if not items:
        return items, 0
    if layout_mode == "direct":
        layout_direct(items, mid, leader_length)
    elif layout_mode == "anti":
        layout_anti(items, mid, leader_length)
    elif layout_mode == "column":
        layout_column(items, mid, bbox, column_gap)
    elif layout_mode == "category":
        layout_category(
            items,
            mid,
            bbox,
            column_gap,
            coco_keypoint_index=COCO_KEYPOINT_INDEX,
            body_parts=BODY_PARTS,
        )
    else:
        layout_direct(items, mid, leader_length)
    overlap_count = _count_overlaps(items)
    _mark_occluded(items)
    return items, overlap_count
