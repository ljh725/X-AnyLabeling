"""QPainter-based renderer for pose keypoint annotations.

The renderer is called from ``Canvas.paintEvent`` after the painter has
already been scaled by ``Canvas.scale``.  All geometry (keypoint
positions, skeleton edges, bbox) is in image coordinates.  Font size,
padding, border width, and leader length are divided by *scale* so they
remain visually constant across zoom levels.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from PyQt6 import QtCore, QtGui
from PyQt6.QtCore import Qt

from .pose_config import PoseDisplayConfig
from .pose_constants import (
    COCO_KEYPOINT_INDEX,
    COCO_KEYPOINT_SET,
    LABEL_TO_BODY_PART,
    SKELETON_EDGES,
)
from .pose_layout import (
    MidLine,
    PoseLabelItem,
    apply_layout,
    compute_direction,
    compute_midline,
)

# -----------------------------------------------------------------------
# Colour helpers
# -----------------------------------------------------------------------


def _luminance(hex_color: str) -> float:
    """Compute relative luminance (0–1) from a hex colour string."""
    c = QtGui.QColor(hex_color)
    if not c.isValid():
        return 0.0
    return (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) / 255.0


def _auto_font_color(bg_hex: str) -> str:
    """Return black or white depending on background luminance."""
    return "#000000" if _luminance(bg_hex) > 0.55 else "#ffffff"


def _get_font_color(config: PoseDisplayConfig, bg_hex: str) -> str:
    """Resolve the font colour based on config mode."""
    mode = config.font_color_mode
    if mode == "white":
        return "#ffffff"
    if mode == "black":
        return "#000000"
    if mode == "auto":
        return _auto_font_color(bg_hex)
    if mode == "yellow":
        return "#ffff00"
    if mode == "custom":
        return config.custom_font_color
    return "#ffffff"


def _get_keypoint_color(
    config: PoseDisplayConfig,
    keypoint_index: int,
    label: str,
    person_index: int,
) -> str:
    """Return the colour for a keypoint based on color_mode."""
    if config.color_mode == "person":
        return config.get_person_color(person_index)
    part = LABEL_TO_BODY_PART.get(label)
    if part and part in config.body_colors:
        return config.body_colors[part]
    return "#7f849c"


# -----------------------------------------------------------------------
# Shape grouping
# -----------------------------------------------------------------------


def _group_shapes_by_person(
    shapes: List[Any],
) -> Tuple[Dict[int, List[Any]], Dict[int, Optional[Any]], List[int]]:
    """Split shapes into person groups.

    Args:
        shapes: All shapes on the canvas.

    Returns:
        ``(groups, person_rects, ordered_gids)`` where *groups* maps
        ``group_id`` -> list of keypoint shapes, *person_rects* maps
        ``group_id`` -> the person rectangle shape (or ``None``), and
        *ordered_gids* is the display order of group ids.
    """
    groups: Dict[int, List[Any]] = {}
    person_rects: Dict[int, Optional[Any]] = {}
    for shape in shapes:
        if not getattr(shape, "visible", True):
            continue
        if getattr(shape, "hidden_by_filter", False):
            continue
        gid = getattr(shape, "group_id", None)
        if gid is None:
            continue
        if shape.shape_type == "point" and shape.label in COCO_KEYPOINT_SET:
            groups.setdefault(gid, []).append(shape)
            person_rects.setdefault(gid, None)
        elif (
            shape.shape_type == "rectangle"
            and getattr(shape, "label", "") == "person"
        ):
            person_rects[gid] = shape
    ordered_gids = sorted(groups.keys())
    return groups, person_rects, ordered_gids


def _keypoint_positions(
    keypoint_shapes: List[Any],
) -> Dict[int, QtCore.QPointF]:
    """Build a mapping COCO index -> QPointF from keypoint shapes."""
    positions: Dict[int, QtCore.QPointF] = {}
    for shape in keypoint_shapes:
        idx = COCO_KEYPOINT_INDEX.get(shape.label)
        if idx is not None and shape.points:
            positions[idx] = QtCore.QPointF(shape.points[0])
    return positions


# -----------------------------------------------------------------------
# Main renderer
# -----------------------------------------------------------------------


class PoseRenderer:
    """Render pose keypoint annotations onto a QPainter.

    The painter must already be in the scaled state (``painter.scale(s, s)``
    done by ``Canvas.paintEvent``).  The renderer does **not** call
    ``painter.save()`` / ``painter.restore()`` or ``painter.scale()``.
    """

    def __init__(self, config: PoseDisplayConfig):
        """Store the config reference (mutated externally by panels).

        Args:
            config: Shared :class:`PoseDisplayConfig` instance.
        """
        self.config = config

    def render(
        self,
        painter: QtGui.QPainter,
        shapes: List[Any],
        pixmap_size: QtCore.QSize,
        scale: float,
        show_labels: bool = True,
        label_on_selection: bool = False,
        hovered_group_id: Optional[int] = None,
        zoom_reveals: bool = False,
        label_display_mode: str = "label",
    ) -> int:
        """Render visible pose annotations and return overlap count.

        Only groups whose shapes are ``shape.visible=True`` (i.e. not
        filtered out by the native filter engine) are rendered. This is
        the "filtered pose display" — Pose View + active gid filter.

        Args:
            painter: QPainter already scaled by *scale*.
            shapes: Canvas shapes list.
            pixmap_size: Image pixel dimensions.
            scale: Current zoom scale.
            show_labels: When True, render keypoint labels.
            label_display_mode: Text content: label / id / both.

        Returns:
            Number of overlapping label pairs.
        """
        cfg = self.config
        groups, person_rects, ordered_gids = _group_shapes_by_person(shapes)
        if not groups:
            return 0
        total_overlap = 0
        for pi, gid in enumerate(ordered_gids):
            kp_shapes = groups[gid]
            # Skip groups whose shapes are all filtered out (invisible).
            if not any(getattr(s, "visible", True) for s in kp_shapes):
                continue
            kp_positions = _keypoint_positions(kp_shapes)
            mid = compute_midline(kp_positions)
            person_color = cfg.get_person_color(pi)
            person_rect_shape = person_rects.get(gid)
            bbox = self._get_bbox(person_rect_shape)

            if cfg.show_bbox and bbox is not None:
                self._draw_bbox(painter, bbox, person_color, scale)
            if cfg.show_midline and mid is not None:
                self._draw_midline(painter, mid, kp_positions, scale)
            if cfg.show_skeleton:
                self._draw_skeleton(painter, kp_positions, cfg, pi, scale)
            self._draw_keypoints(painter, kp_shapes, cfg, pi, scale)
            if show_labels:
                items = self._build_label_items(
                    kp_shapes,
                    mid,
                    cfg,
                    pi,
                    scale,
                    label_display_mode=label_display_mode,
                )
                items, overlap = apply_layout(
                    items,
                    mid,
                    bbox,
                    cfg.layout_mode,
                    leader_length=cfg.leader_length / scale,
                    column_gap=cfg.column_gap / scale,
                )
                total_overlap += overlap
                self._draw_labels(painter, items, cfg, scale)
        return total_overlap

    # -- Drawing primitives ---------------------------------------------

    def _get_bbox(
        self, person_rect_shape: Optional[Any]
    ) -> Optional[QtCore.QRectF]:
        """Extract the bounding rect from a person rectangle shape.

        Uses the shape's own ``bounding_rect`` so the result is correct
        regardless of whether the rectangle is stored as 2 diagonal
        points or 4 corner points (the previous pts[0]/pts[1] logic
        collapsed to a flat top line for 4-point rectangles).
        """
        if person_rect_shape is None:
            return None
        try:
            rect = person_rect_shape.bounding_rect()
        except Exception:
            return None
        if rect is None or rect.isEmpty():
            return None
        return QtCore.QRectF(rect)

    def _draw_bbox(
        self,
        painter: QtGui.QPainter,
        bbox: QtCore.QRectF,
        color_hex: str,
        scale: float,
    ) -> None:
        """Draw the person bounding box rectangle."""
        pen = QtGui.QPen(QtGui.QColor(color_hex), 2.0 / scale)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(bbox)
        label_font = QtGui.QFont("Arial", max(1, int(round(12.0 / scale))))
        label_font.setBold(True)
        painter.setFont(label_font)
        painter.drawText(
            QtCore.QPointF(bbox.x(), bbox.y() - 4.0 / scale),
            "person",
        )

    def _draw_midline(
        self,
        painter: QtGui.QPainter,
        mid: MidLine,
        kp_positions: Dict[int, QtCore.QPointF],
        scale: float,
    ) -> None:
        """Draw a dashed vertical midline through the body."""
        if not kp_positions:
            return
        mx = mid[0]
        ys = [p.y() for p in kp_positions.values()]
        if not ys:
            return
        pen = QtGui.QPen(
            QtGui.QColor(137, 180, 250, 76),
            1.0 / scale,
            Qt.PenStyle.DashLine,
        )
        pen.setDashPattern([4 / scale, 4 / scale])
        painter.setPen(pen)
        top_y = min(ys) - 30
        bot_y = max(ys) + 30
        painter.drawLine(QtCore.QPointF(mx, top_y), QtCore.QPointF(mx, bot_y))

    def _draw_skeleton(
        self,
        painter: QtGui.QPainter,
        kp_positions: Dict[int, QtCore.QPointF],
        cfg: PoseDisplayConfig,
        person_index: int,
        scale: float,
    ) -> None:
        """Draw skeleton edges between keypoints."""
        pen_width = 2.0 / scale
        for idx_a, idx_b in SKELETON_EDGES:
            pa = kp_positions.get(idx_a)
            pb = kp_positions.get(idx_b)
            if pa is None or pb is None:
                continue
            if cfg.color_mode == "person":
                color_hex = cfg.get_person_color(person_index)
            else:
                color_hex = self._skeleton_edge_color(idx_a, idx_b, cfg)
            pen = QtGui.QPen(QtGui.QColor(color_hex), pen_width)
            painter.setPen(pen)
            painter.setOpacity(0.6)
            painter.drawLine(pa, pb)
            painter.setOpacity(1.0)

    def _skeleton_edge_color(
        self,
        idx_a: int,
        idx_b: int,
        cfg: PoseDisplayConfig,
    ) -> str:
        """Determine the colour for a skeleton edge by body part."""
        for idx in (idx_a, idx_b):
            label = None
            for name, ki in COCO_KEYPOINT_INDEX.items():
                if ki == idx:
                    label = name
                    break
            if label:
                part = LABEL_TO_BODY_PART.get(label)
                if part and part in cfg.body_colors:
                    return cfg.body_colors[part]
        return "#7f849c"

    def _build_label_items(
        self,
        kp_shapes: List[Any],
        mid: MidLine,
        cfg: PoseDisplayConfig,
        person_index: int,
        scale: float,
        label_display_mode: str = "label",
    ) -> List[PoseLabelItem]:
        """Construct PoseLabelItem list for layout."""
        font = QtGui.QFont("Arial", max(1, int(round(cfg.font_size / scale))))
        font.setBold(True)
        fm = QtGui.QFontMetrics(font)
        pad_x = 6.0 / scale
        pad_y = 2.0 / scale
        items: List[PoseLabelItem] = []
        for shape in kp_shapes:
            if not shape.points:
                continue
            gid = getattr(shape, "group_id", None)
            # Text content follows label_display_mode (label/id/both).
            if label_display_mode == "id":
                display_text = str(gid) if gid is not None else ""
            elif label_display_mode == "both":
                display_text = (
                    f"{shape.label} #{gid}" if gid is not None else shape.label
                )
            else:  # "label"
                display_text = shape.label
            text_rect = fm.tightBoundingRect(display_text)
            w = int(text_rect.width() + 2 * pad_x)
            h = int(fm.height() + 2 * pad_y)
            pt = shape.points[0]
            anchor = QtCore.QPointF(pt.x(), pt.y())
            ki = COCO_KEYPOINT_INDEX.get(shape.label, 0)
            direction = compute_direction(ki, anchor, mid)
            color_hex = _get_keypoint_color(cfg, ki, shape.label, person_index)
            rect = QtCore.QRect(int(anchor.x()), int(anchor.y()), w, h)
            items.append(
                PoseLabelItem(
                    shape_ref=shape,
                    label=display_text,
                    keypoint_index=ki,
                    group_id=gid,
                    anchor=anchor,
                    rect=rect,
                    direction=direction,
                    color_hex=color_hex,
                )
            )
        return items

    def _draw_keypoints(
        self,
        painter: QtGui.QPainter,
        kp_shapes: List[Any],
        cfg: PoseDisplayConfig,
        person_index: int,
        scale: float,
    ) -> None:
        """Draw keypoint circles with selection highlight."""
        radius = 5.0 / scale
        stroke_w = 1.5 / scale
        for shape in kp_shapes:
            if not shape.points:
                continue
            pt = shape.points[0]
            ki = COCO_KEYPOINT_INDEX.get(shape.label, 0)
            color_hex = _get_keypoint_color(cfg, ki, shape.label, person_index)
            painter.setBrush(QtGui.QColor(color_hex))
            painter.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), stroke_w))
            painter.drawEllipse(pt, radius, radius)
            if getattr(shape, "selected", False):
                dash_pen = QtGui.QPen(
                    QtGui.QColor("#89b4fa"),
                    1.5 / scale,
                    Qt.PenStyle.DashLine,
                )
                dash_pen.setDashPattern([3 / scale, 3 / scale])
                painter.setPen(dash_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(pt, radius * 1.8, radius * 1.8)

    def _draw_labels(
        self,
        painter: QtGui.QPainter,
        items: List[PoseLabelItem],
        cfg: PoseDisplayConfig,
        scale: float,
    ) -> None:
        """Draw leader lines, label backgrounds, and text."""
        if not items:
            return
        font = QtGui.QFont("Arial", max(1, int(round(cfg.font_size / scale))))
        font.setBold(True)
        painter.setFont(font)
        pad_x = 6.0 / scale
        pad_y = 2.0 / scale
        if cfg.show_leader:
            leader_pen = QtGui.QPen(
                QtGui.QColor(255, 255, 255, 128), 1.0 / scale
            )
            painter.setPen(leader_pen)
            for item in items:
                painter.drawLine(
                    item.leader_start,
                    QtCore.QPointF(item.leader_end),
                )
        for item in items:
            shape = item.shape_ref
            if not getattr(shape, "visible", True):
                continue
            if getattr(shape, "hidden_by_filter", False):
                continue
            bg_hex = item.color_hex
            if item.occluded and cfg.occlusion_highlight:
                bg = QtGui.QColor(243, 139, 168, 76)
            else:
                bg = QtGui.QColor(bg_hex)
                bg.setAlphaF(cfg.opacity)
            painter.setBrush(bg)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(item.rect, 3, 3)
            fc_hex = _get_font_color(cfg, bg_hex)
            text_x = item.rect.x() + pad_x
            text_y = item.rect.y() + pad_y + painter.fontMetrics().ascent()
            if cfg.font_shadow:
                painter.setPen(QtGui.QColor(0, 0, 0, 178))
                painter.drawText(
                    QtCore.QPointF(
                        text_x + 1.0 / scale,
                        text_y + 1.0 / scale,
                    ),
                    item.label,
                )
            painter.setPen(QtGui.QColor(fc_hex))
            painter.drawText(QtCore.QPointF(text_x, text_y), item.label)
