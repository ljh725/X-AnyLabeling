"""Pure layout pass for keypoint label anti-occlusion.

No Qt widget dependency beyond QtCore geometry types. Callable from
Canvas.paintEvent after the label rects are computed.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Tuple
from PyQt6 import QtCore

Leader = Tuple[QtCore.QPointF, QtCore.QPoint]


@dataclass
class LabelItem:
    """One keypoint label candidate for the layout pass."""

    shape_ref: object
    group_id: Optional[int]
    anchor: QtCore.QPointF  # keypoint center in image coords
    rect: QtCore.QRect  # current label rect in image coords


_DIRECTIONS = [
    (0, -1),
    (1, -1),
    (1, 0),
    (1, 1),
    (0, 1),
    (-1, 1),
    (-1, 0),
    (-1, -1),
]


def layout_keypoint_labels(
    items: List[LabelItem],
    canvas_size: QtCore.QSize,
    step: int = 14,
    max_tries: int = 8,
    gap: int = 2,
    obstacles: Optional[List[QtCore.QRect]] = None,
    leader_threshold: int = 5,
) -> Tuple[List[LabelItem], List[Leader]]:
    """Reposition overlapping point labels per group.

    The algorithm is best-effort. If no collision-free position is found,
    the label is clamped to the canvas bounds and may still overlap dense
    obstacles.

    Args:
        items: label candidates (only point-type labels should be passed).
        canvas_size: image size in image coords (labels must stay inside).
        step: displacement distance per try, in image px.
        max_tries: number of direction attempts along each of 8 rays.
        gap: minimum spacing kept between rects (added via margins).
        obstacles: optional list of rects that labels must avoid but will
            not be moved (e.g. non-point label rects).
        leader_threshold: minimum Euclidean distance (in px) between the
            original and new rect centers before a leader line is emitted.

    Returns:
        (laid_items, leaders) where leaders is a list of
        (anchor_point, nearest_rect_edge_point) pairs for labels that
        moved far enough to warrant a leader line.
    """
    canvas_rect = QtCore.QRect(0, 0, canvas_size.width(), canvas_size.height())
    placed = list(obstacles or [])  # across ALL groups + obstacles
    groups: dict[Optional[int], list[tuple[int, LabelItem]]] = {}
    for idx, it in enumerate(items):
        groups.setdefault(it.group_id, []).append((idx, it))

    results = []
    for _gid, group in groups.items():
        group.sort(key=lambda pair: (pair[1].anchor.y(), pair[1].anchor.x()))
        for idx, it in group:
            chosen = it.rect
            if not _conflicts(chosen, placed, gap) and canvas_rect.contains(
                chosen
            ):
                pass
            else:
                chosen = _search(
                    chosen,
                    it.anchor,
                    step,
                    max_tries,
                    gap,
                    placed,
                    canvas_rect,
                )
            placed.append(chosen)
            leader: Optional[Leader] = None
            if _moved_far(it.rect, chosen, leader_threshold):
                leader = (
                    QtCore.QPointF(it.anchor),
                    _nearest_edge(chosen, it.anchor),
                )
            results.append(
                (idx, chosen, it.shape_ref, it.group_id, it.anchor, leader)
            )

    results.sort(key=lambda row: row[0])
    laid = [
        LabelItem(
            shape_ref=row[2],
            group_id=row[3],
            anchor=row[4],
            rect=row[1],
        )
        for row in results
    ]
    leaders = [row[5] for row in results if row[5] is not None]
    return laid, leaders


def _conflicts(
    rect: QtCore.QRect, placed: List[QtCore.QRect], gap: int
) -> bool:
    """Return True if ``rect`` intersects any placed rect with margin.

    Args:
        rect: candidate label rect.
        placed: rects already placed or marked as obstacles.
        gap: additional margin added around ``rect`` before intersection test.

    Returns:
        True when the expanded candidate intersects at least one placed rect.
    """
    expanded = rect.adjusted(-gap, -gap, gap, gap)
    return any(expanded.intersects(p) for p in placed)


def _search(
    start: QtCore.QRect,
    anchor: QtCore.QPointF,
    step: int,
    max_tries: int,
    gap: int,
    placed: List[QtCore.QRect],
    canvas_rect: QtCore.QRect,
) -> QtCore.QRect:
    """Try displacements away from anchor along 8 rays.

    Directions are ordered so rays pointing away from the anchor are tried
    first. The first candidate that stays inside the canvas and does not
    conflict with any placed rect is returned. If none of the rays succeed,
    ``start`` is clamped to the canvas bounds and returned.

    Args:
        start: original label rect.
        anchor: keypoint center to move away from.
        step: displacement distance per try.
        max_tries: number of steps along each ray.
        gap: minimum spacing kept between rects.
        placed: rects already placed or marked as obstacles.
        canvas_rect: valid canvas bounds.

    Returns:
        A non-conflicting candidate rect, or ``start`` clamped to canvas.
    """
    cx, cy = anchor.x(), anchor.y()

    def outward_key(d):
        return -(
            (start.center().x() - cx) * d[0] + (start.center().y() - cy) * d[1]
        )

    def candidate(dx: int, dy: int, k: int) -> QtCore.QRect:
        return start.translated(int(dx * step * k), int(dy * step * k))

    ordered = sorted(_DIRECTIONS, key=outward_key)
    for dx, dy in ordered:
        for k in range(1, max_tries + 1):
            cand = candidate(dx, dy, k)
            if canvas_rect.contains(cand) and not _conflicts(
                cand, placed, gap
            ):
                return cand
    return _clamp_to_canvas(start, canvas_rect)


def _clamp_to_canvas(
    rect: QtCore.QRect, canvas_rect: QtCore.QRect
) -> QtCore.QRect:
    """Return ``rect`` moved so its top-left lies inside ``canvas_rect``.

    The function first tries to keep the full rect inside the canvas by
    shifting the top-left corner left/up when the right/bottom edges
    overflow. If the canvas is smaller than the rect, the top-left corner
    is clamped to the canvas origin instead.
    """
    new_x = rect.x()
    new_y = rect.y()
    if rect.right() > canvas_rect.right():
        new_x = canvas_rect.right() - rect.width() + 1
    if rect.bottom() > canvas_rect.bottom():
        new_y = canvas_rect.bottom() - rect.height() + 1
    if new_x < canvas_rect.left():
        new_x = canvas_rect.left()
    if new_y < canvas_rect.top():
        new_y = canvas_rect.top()
    return QtCore.QRect(new_x, new_y, rect.width(), rect.height())


def _moved_far(orig: QtCore.QRect, new: QtCore.QRect, threshold: int) -> bool:
    """Return True when the center displacement exceeds ``threshold``.

    Args:
        orig: original label rect.
        new: repositioned label rect.
        threshold: minimum Euclidean distance before a leader is warranted.

    Returns:
        True when the squared distance between centers is at least
        ``threshold`` squared.
    """
    dx = orig.center().x() - new.center().x()
    dy = orig.center().y() - new.center().y()
    return dx * dx + dy * dy >= threshold * threshold


def _nearest_edge(rect: QtCore.QRect, anchor: QtCore.QPointF) -> QtCore.QPoint:
    """Return the closest point on ``rect`` boundary to ``anchor``.

    Args:
        rect: label rect whose boundary is used as the leader endpoint.
        anchor: keypoint center in image coords.

    Returns:
        A point guaranteed to lie on one of the four edges of ``rect``.
    """
    ax, ay = anchor.x(), anchor.y()
    left, top = rect.left(), rect.top()
    right, bottom = rect.right(), rect.bottom()

    def _clamp(value: float, low: int, high: int) -> int:
        return int(min(max(value, low), high))

    candidates = [
        (_clamp(ax, left, right), top),
        (_clamp(ax, left, right), bottom),
        (left, _clamp(ay, top, bottom)),
        (right, _clamp(ay, top, bottom)),
    ]
    best = candidates[0]
    best_dist = (ax - best[0]) ** 2 + (ay - best[1]) ** 2
    for cx, cy in candidates[1:]:
        dist = (ax - cx) ** 2 + (ay - cy) ** 2
        if dist < best_dist:
            best = (cx, cy)
            best_dist = dist
    return QtCore.QPoint(*best)
