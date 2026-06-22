"""Category layout mode for pose keypoint labels.

A **self-contained** module implementing the ``category`` layout mode:
labels are stacked by body-part group around the person bounding box.

This file is intended for **code migration**.  It bundles every helper
the new mode needs (prefix detection, body-part grouping, bbox
fallback, head-row ordering) so it can be dropped into a target
project without dragging in the rest of ``pose_layout.py``.

Migration target contract
-------------------------
The host project must provide:

1. A ``PoseLabelItem`` dataclass with at least these attributes::

        shape_ref: object          # carries original ``.label``
        label: str                 # display text (may be mutated)
        keypoint_index: int        # COCO index 0..16
        group_id: Optional[int]
        anchor: QtCore.QPointF
        rect: QtCore.QRect         # mutated in place
        direction: str
        leader_start: QtCore.QPointF
        leader_end: QtCore.QPoint

2. A constant mapping ``COCO_KEYPOINT_INDEX: Dict[str, int]`` (label
   -> 0..16) and ``BODY_PARTS: Dict[str, List[str]]`` with keys
   ``head``/``la``/``ra``/``ll``/``rl``.  Both exist in
   ``pose_constants.py`` of X-AnyLabeling and can be reused directly.

3. ``QtCore.QRect`` / ``QtCore.QPointF`` / ``QtCore.QPoint`` from PyQt6.

Integration (see migration/README.md for the full checklist):
    - In ``apply_layout()`` dispatcher, add a ``"category"`` branch
      that calls :func:`layout_category`.
    - In the settings panel, add a button whose key is ``"category"``.

Layout overview
---------------

::

         [l_ear][l_eye][nose][r_eye][r_ear]   <- head row (bbox top)
       ┌────────────────────────────────┐
    [la]│                                │[ra]
    [la]│           person               │[ra]   <- arm sub-column
    [la]│                                │[ra]
    [ll]│                                │[rl]
    [ll]│                                │[rl]   <- leg sub-column
    [ll]│                                │[rl]
       └────────────────────────────────┘
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PyQt6 import QtCore

# -----------------------------------------------------------------------
# Type aliases (mirrors host project conventions)
# -----------------------------------------------------------------------

MidLine = Optional[Tuple[float, float]]  # (mid_x, shoulder_distance)


# -----------------------------------------------------------------------
# Body-part helpers
# -----------------------------------------------------------------------


def _body_part_group(
    keypoint_index: int,
    coco_keypoint_index: Dict[str, int],
    body_parts: Dict[str, List[str]],
) -> str:
    """Map a COCO *keypoint_index* to its body-part group.

    Args:
        keypoint_index: Index into the host COCO keypoint order.
        coco_keypoint_index: ``{label: index}`` mapping from the host
            constants module.
        body_parts: ``{part: [labels]}`` mapping; expected keys are
            ``head``/``la``/``ra``/``ll``/``rl``.

    Returns:
        One of ``"head"`` / ``"la"`` / ``"ra"`` / ``"ll"`` / ``"rl"``.
        Falls back to ``"head"`` for out-of-range indices.
    """
    for part, labels in body_parts.items():
        for name in labels:
            if coco_keypoint_index.get(name) == keypoint_index:
                return part
    return "head"


def _is_lateral_prefix(label: str) -> Optional[str]:
    """Return ``"left"`` / ``"right"`` if *label* starts with a lateral prefix.

    Matching is case-insensitive and only anchored at the start of the
    label to avoid false positives such as ``light_``.  Returns
    ``None`` when no lateral prefix is present.

    Args:
        label: Original keypoint label (e.g. ``l_sho``, ``Right_elb``).

    Returns:
        ``"left"`` / ``"right"`` / ``None``.
    """
    if not label:
        return None
    low = label.lower()
    if low.startswith("l_") or low.startswith("left_"):
        return "left"
    if low.startswith("r_") or low.startswith("right_"):
        return "right"
    return None


def _original_label(item) -> str:
    """Return the original keypoint label carried by *item*.

    ``item.label`` may hold display text mutated by a label-display
    mode (e.g. ``"#3"``), which loses the ``l_``/``r_`` prefix needed
    by :func:`_is_lateral_prefix`.  We recover the original label via
    the shape reference when possible.
    """
    shape = getattr(item, "shape_ref", None)
    label = getattr(shape, "label", None)
    if isinstance(label, str) and label:
        return label
    return getattr(item, "label", "")


def _head_lateral_rank(item) -> int:
    """Return -1/0/+1 for left/centre/right placement of a head label.

    Used only to order the head row in :func:`layout_category`.  The
    original label is recovered from the shape reference so a display
    mode that hides the prefix still orders correctly.
    """
    side = _is_lateral_prefix(_original_label(item))
    if side == "left":
        return -1
    if side == "right":
        return 1
    return 0


# -----------------------------------------------------------------------
# Geometry helper (bbox fallback when the host passes None)
# -----------------------------------------------------------------------


def _compute_bbox(items) -> Optional[QtCore.QRectF]:
    """Compute the bounding rect of all item anchors with padding.

    Used only when the caller passes ``bbox=None`` so the category
    layout can still place labels around an inferred region.
    """
    if not items:
        return None
    xs = [it.anchor.x() for it in items]
    ys = [it.anchor.y() for it in items]
    pad = 20.0
    return QtCore.QRectF(
        min(xs) - pad,
        min(ys) - pad,
        max(xs) - min(xs) + 2 * pad,
        max(ys) - min(ys) + 2 * pad,
    )


# -----------------------------------------------------------------------
# Public layout function
# -----------------------------------------------------------------------


def layout_category(
    items: List,
    mid: MidLine,
    bbox: Optional[QtCore.QRectF],
    column_gap: float,
    coco_keypoint_index: Dict[str, int],
    body_parts: Dict[str, List[str]],
) -> List:
    """Stack labels by body-part group around the person bbox.

    Groups (see *body_parts*):

    - ``head`` – arranged horizontally along the upper bbox edge with
      ``nose`` centred and l_/r_ prefixes on their sides.
    - ``la`` + ``ll`` – stacked vertically on the **left** of the
      bbox (arm above, leg below); each sub-group is internally
      sorted by Y.
    - ``ra`` + ``rl`` – stacked vertically on the **right** of the
      bbox (arm above, leg below).

    Leader lines connect each placed label back to its keypoint
    anchor so the visual association is preserved.

    Args:
        items: Label candidates (rects mutated in place).  Each item
            must expose ``keypoint_index``, ``anchor`` (``QPointF``),
            ``rect`` (``QRect``), ``leader_start``/``leader_end``.
        mid: Body midline ``(mid_x, shoulder_distance)`` or ``None``.
            (Accepted for dispatcher signature symmetry; the category
            layout keys off *body_parts* rather than the midline.)
        bbox: Person bounding rect.  If ``None`` a fallback bbox is
            computed from the item anchors.
        column_gap: Vertical gap between stacked labels, in image px.
        coco_keypoint_index: Host constant mapping label -> COCO idx.
        body_parts: Host constant mapping part -> list of labels.

    Returns:
        The mutated *items* list (for chaining).
    """
    if not items:
        return items
    if bbox is None:
        bbox = _compute_bbox(items)
    if bbox is None:
        return items
    gap = column_gap
    max_w = max(it.rect.width() for it in items)

    # -- Partition by body-part group --------------------------------
    head_items: List = []
    left_items: List = []  # la, ll
    right_items: List = []  # ra, rl
    for item in items:
        part = _body_part_group(
            item.keypoint_index, coco_keypoint_index, body_parts
        )
        if part == "head":
            head_items.append(item)
        elif part in ("la", "ll"):
            left_items.append(item)
        else:  # ra, rl, or unknown fallback -> right
            right_items.append(item)

    # Sort the side stacks: arm-before-leg, then by Y within each arm/leg.
    left_items.sort(
        key=lambda it: (
            (
                0
                if _body_part_group(
                    it.keypoint_index, coco_keypoint_index, body_parts
                )
                == "la"
                else 1
            ),
            it.anchor.y(),
        )
    )
    right_items.sort(
        key=lambda it: (
            (
                0
                if _body_part_group(
                    it.keypoint_index, coco_keypoint_index, body_parts
                )
                == "ra"
                else 1
            ),
            it.anchor.y(),
        )
    )

    bbox_x = bbox.x()
    bbox_y = bbox.y()
    bbox_x2 = bbox.x() + bbox.width()

    # -- Left column (la above, ll below) -----------------------------
    lx = bbox_x - max_w - gap
    cy = bbox_y
    for item in left_items:
        ny = max(item.anchor.y() - item.rect.height() / 2, cy)
        item.rect.moveTo(int(lx), int(ny))
        item.leader_start = QtCore.QPointF(
            item.anchor.x() - 2, item.anchor.y()
        )
        item.leader_end = QtCore.QPoint(
            item.rect.right(), int(item.rect.y() + item.rect.height() / 2)
        )
        cy = item.rect.bottom() + gap

    # -- Right column (ra above, rl below) ----------------------------
    rx2 = bbox_x2 + gap
    cy = bbox_y
    for item in right_items:
        ny = max(item.anchor.y() - item.rect.height() / 2, cy)
        item.rect.moveTo(int(rx2), int(ny))
        item.leader_start = QtCore.QPointF(
            item.anchor.x() + 2, item.anchor.y()
        )
        item.leader_end = QtCore.QPoint(
            item.rect.left(), int(item.rect.y() + item.rect.height() / 2)
        )
        cy = item.rect.bottom() + gap

    # -- Head row (horizontal, nose centred) -------------------------
    if head_items:
        tcx = (bbox_x + bbox_x2) / 2
        head_items.sort(key=_head_lateral_rank)
        centre = [it for it in head_items if _head_lateral_rank(it) == 0]
        left_h = [it for it in head_items if _head_lateral_rank(it) < 0]
        right_h = [it for it in head_items if _head_lateral_rank(it) > 0]
        ny0 = bbox_y - head_items[0].rect.height() - gap
        # Centre (nose).
        for item in centre:
            nx = tcx - item.rect.width() / 2
            item.rect.moveTo(int(nx), int(ny0))
            item.leader_start = QtCore.QPointF(
                item.anchor.x(), item.anchor.y() - 2
            )
            item.leader_end = QtCore.QPoint(
                int(item.rect.x() + item.rect.width() / 2),
                item.rect.bottom(),
            )
        # Left-prefixed head labels stack leftward from centre.
        head_off = (max_w / 2 + gap / 2) * 0.5
        cx = tcx - head_off
        for item in left_h:
            nx = cx - item.rect.width()
            item.rect.moveTo(int(nx), int(ny0))
            item.leader_start = QtCore.QPointF(
                item.anchor.x(), item.anchor.y() - 2
            )
            item.leader_end = QtCore.QPoint(
                int(item.rect.x() + item.rect.width() / 2),
                item.rect.bottom(),
            )
            cx = item.rect.x() - gap
        # Right-prefixed head labels stack rightward from centre.
        cx = tcx + head_off
        for item in right_h:
            item.rect.moveTo(int(cx), int(ny0))
            item.leader_start = QtCore.QPointF(
                item.anchor.x(), item.anchor.y() - 2
            )
            item.leader_end = QtCore.QPoint(
                int(item.rect.x() + item.rect.width() / 2),
                item.rect.bottom(),
            )
            cx = item.rect.right() + gap
    return items
