"""Direct edge dragging for one selected rectangle."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PyQt6 import QtCore, QtGui
from PyQt6.QtCore import Qt

from ..shape import Shape


@dataclass
class EdgeDrag:
    """Keep the selected edge and its pre-drag geometry together."""

    shape: Shape
    edge: str
    press: QtCore.QPointF
    points: list[QtCore.QPointF]
    changed: bool = False


class RectangleEdgeMixin:
    """Provide transient selected-rectangle edge editing."""

    def set_rectangle_edge_enabled(self, enabled: bool) -> None:
        """Enable edge editing or cancel an in-progress drag on disable."""
        if not enabled:
            self._rectangle_edge_cancel()
        self._rectangle_edge_enabled = bool(enabled)
        self.update()

    def _rectangle_edge_hit(
        self, pos: QtCore.QPointF
    ) -> tuple[Shape, str] | None:
        """Find an eligible edge, with vertex and small-box priority."""
        if not self._rectangle_edge_enabled:
            return None
        shape = self._point_fit_selected_rectangle()
        if shape is None or self.scale <= 0:
            return None
        epsilon = self.epsilon / self.scale
        left, top, right, bottom = self._point_fit_shape_box(shape)
        if (
            not all(
                math.isfinite(value) for value in (left, top, right, bottom)
            )
            or right - left < 1
            or bottom - top < 1
        ):
            return None
        for center, radius, edge in self._rectangle_edge_handles(shape):
            if (
                math.hypot(pos.x() - center.x(), pos.y() - center.y())
                <= radius
            ):
                return (
                    (shape, edge)
                    if self._rectangle_edge_native_priority(shape, pos)
                    else None
                )
        if shape.nearest_vertex(pos, epsilon) is not None:
            return None
        small = min(right - left, bottom - top) * self.scale < 3 * self.epsilon
        x, y = pos.x(), pos.y()
        candidates = []
        if top <= y <= bottom:
            candidates.append(
                (abs(x - left), "left", x > left, left, right - left)
            )
            candidates.append(
                (
                    abs(x - right),
                    "right",
                    x < right,
                    self.pixmap.width() - right,
                    right - left,
                )
            )
        if left <= x <= right:
            candidates.append(
                (abs(y - top), "top", y > top, top, bottom - top)
            )
            candidates.append(
                (
                    abs(y - bottom),
                    "bottom",
                    y < bottom,
                    self.pixmap.height() - bottom,
                    bottom - top,
                )
            )
        if not candidates:
            return None
        candidates.sort(key=lambda candidate: candidate[0])
        distance, edge, inward, outside_space, span = candidates[0]
        if len(candidates) > 1 and math.isclose(
            distance, candidates[1][0], rel_tol=1e-12, abs_tol=1e-12
        ):
            return None
        tolerance = epsilon
        if inward:
            available = (
                max(0.0, epsilon - max(0.0, outside_space))
                if small
                else epsilon
            )
            tolerance = min(available, span / 4)
        if distance > tolerance and not math.isclose(
            distance, tolerance, rel_tol=1e-12, abs_tol=1e-12
        ):
            return None
        if not self._rectangle_edge_native_priority(shape, pos):
            return None
        return (shape, edge)

    def _rectangle_edge_handles(self, shape: Shape) -> list:
        """Expose small-box edge midpoints without covering its centre."""
        if not self._rectangle_edge_enabled or self.scale <= 0:
            return []
        left, top, right, bottom = self._point_fit_shape_box(shape)
        width, height = right - left, bottom - top
        if (
            not all(math.isfinite(v) for v in (left, top, right, bottom))
            or min(width, height) < 1
            or min(width, height) * self.scale >= 3 * self.epsilon
        ):
            return []
        radius = min(3 / self.scale, width / 4, height / 4)
        cx, cy = (left + right) / 2, (top + bottom) / 2
        return [
            (QtCore.QPointF(left, cy), radius, "left"),
            (QtCore.QPointF(right, cy), radius, "right"),
            (QtCore.QPointF(cx, top), radius, "top"),
            (QtCore.QPointF(cx, bottom), radius, "bottom"),
        ]

    def _rectangle_edge_native_priority(
        self, shape: Shape, pos: QtCore.QPointF
    ) -> bool:
        """Only claim the pointer while native ordering keeps this shape.

        The rectangle being edited is already selected, but another object
        may be on top at this point. In that case the click belongs to the
        native selection path instead of an edge drag.
        """
        candidates = self._shape_hit_candidates(pos)
        return not candidates or candidates[0] is shape

    def _rectangle_edge_cancel(self) -> None:
        """Restore live geometry and clear the current edge interaction."""
        drag = self._rectangle_edge_drag
        had_interaction = (
            drag is not None or self._rectangle_edge_hover is not None
        )
        if drag is not None and drag.changed and drag.shape in self.shapes:
            drag.shape.points = [QtCore.QPointF(p) for p in drag.points]
        self._rectangle_edge_drag = None
        self._rectangle_edge_hover = None
        if had_interaction:
            self.restore_cursor()
            self.update()

    def _rectangle_edge_hover_move(self, pos: QtCore.QPointF) -> bool:
        """Update edge highlight when no button gesture is active."""
        hit = self._rectangle_edge_hit(pos)
        old = self._rectangle_edge_hover
        self._rectangle_edge_hover = hit
        if hit is None:
            if old is not None:
                self.restore_cursor()
                self.update()
            return False
        cursor = (
            Qt.CursorShape.SizeHorCursor
            if hit[1] in ("left", "right")
            else Qt.CursorShape.SizeVerCursor
        )
        self.override_cursor(cursor)
        self.update()
        return True

    def _rectangle_edge_press(
        self, pos: QtCore.QPointF, event: QtGui.QMouseEvent
    ) -> bool:
        """Capture a direct edge press without changing selection."""
        if event.modifiers() != Qt.KeyboardModifier.NoModifier:
            return False
        hit = self._rectangle_edge_hit(pos)
        if hit is None:
            return False
        shape, edge = hit
        self._rectangle_edge_drag = EdgeDrag(
            shape,
            edge,
            QtCore.QPointF(pos),
            [QtCore.QPointF(p) for p in shape.points],
        )
        self._rectangle_edge_hover = hit
        self.update()
        return True

    def _rectangle_edge_drag_move(
        self, pos: QtCore.QPointF, event: QtGui.QMouseEvent
    ) -> bool:
        """Move the captured edge after the first actual pointer movement."""
        drag = self._rectangle_edge_drag
        if drag is None:
            return False
        if not event.buttons() & Qt.MouseButton.LeftButton:
            self._rectangle_edge_cancel()
            return True
        if drag.shape is not self._point_fit_selected_rectangle():
            self._rectangle_edge_cancel()
            return True
        if pos == drag.press and not drag.changed:
            return True
        original = self._point_fit_shape_box(drag.shape)
        xs, ys = [p.x() for p in drag.points], [p.y() for p in drag.points]
        left, top, right, bottom = min(xs), min(ys), max(xs), max(ys)
        delta = pos - drag.press
        max_x, max_y = self.pixmap.width(), self.pixmap.height()
        if drag.edge == "left":
            left = max(0.0, min(left + delta.x(), right - 1))
        elif drag.edge == "right":
            right = min(float(max_x), max(right + delta.x(), left + 1))
        elif drag.edge == "top":
            top = max(0.0, min(top + delta.y(), bottom - 1))
        else:
            bottom = min(float(max_y), max(bottom + delta.y(), top + 1))
        updated = (left, top, right, bottom)
        if updated == original:
            return True
        if not drag.changed:
            current = [shape.to_dict() for shape in self.shapes]
            if (
                not self.shapes_backups
                or [shape.to_dict() for shape in self.shapes_backups[-1]]
                != current
            ):
                self.store_shapes()
        drag.shape.points = [
            QtCore.QPointF(left, top),
            QtCore.QPointF(right, top),
            QtCore.QPointF(right, bottom),
            QtCore.QPointF(left, bottom),
        ]
        drag.changed = True
        self.repaint()
        return True

    def _rectangle_edge_release_event(self, event: QtGui.QMouseEvent) -> bool:
        """Commit a captured drag as one undo entry on mouse release."""
        drag = self._rectangle_edge_drag
        if drag is None or event.button() != Qt.MouseButton.LeftButton:
            return False
        original = [(p.x(), p.y()) for p in drag.points]
        changed = (
            drag.changed
            and [(p.x(), p.y()) for p in drag.shape.points] != original
        )
        if changed:
            self.store_shapes()
            self.shape_moved.emit()
        self._rectangle_edge_drag = None
        self._rectangle_edge_hover = None
        self.restore_cursor()
        self.update()
        event.accept()
        return True

    def _paint_rectangle_edge(self, painter: QtGui.QPainter) -> None:
        """Highlight the hovered or actively dragged edge."""
        if not self._rectangle_edge_enabled:
            return
        selected = self._point_fit_selected_rectangle()
        if selected is not None:
            handles = self._rectangle_edge_handles(selected)
            if handles:
                painter.save()
                pen = QtGui.QPen(QtGui.QColor("white"))
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.setBrush(QtGui.QColor("white"))
                for center, radius, _ in handles:
                    painter.drawEllipse(center, radius, radius)
                painter.restore()
        hit = self._rectangle_edge_hover
        if hit is None:
            return
        shape, edge = hit
        if shape not in self.shapes:
            return
        left, top, right, bottom = self._point_fit_shape_box(shape)
        endpoints = {
            "left": ((left, top), (left, bottom)),
            "right": ((right, top), (right, bottom)),
            "top": ((left, top), (right, top)),
            "bottom": ((left, bottom), (right, bottom)),
        }
        start, end = endpoints[edge]
        painter.save()
        pen = QtGui.QPen(QtGui.QColor(255, 255, 255))
        pen.setCosmetic(True)
        pen.setWidthF(2.0 if self._rectangle_edge_drag else 1.5)
        painter.setPen(pen)
        painter.drawLine(QtCore.QPointF(*start), QtCore.QPointF(*end))
        painter.restore()
