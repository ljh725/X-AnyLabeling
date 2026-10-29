"""Shift-click rectangle fitting for the labeling canvas."""

from PyQt6 import QtCore, QtGui
from PyQt6.QtCore import Qt

from ..rect_edge_click import point_fit_decision, proposed_point_fit_box
from ..shape import Shape


class PointFitMixin:
    """Own point-fit state, preview, and commit behavior."""

    def _clear_point_fit(self, keep_press: bool = False) -> None:
        """Clear the point-fit preview and optionally consume its release."""
        if self._point_fit_cursor is not None:
            self.setToolTip("")
        self._point_fit_target = None
        self._point_fit_start = None
        self._point_fit_pending_box = None
        self._point_fit_cursor = None
        if not keep_press:
            self._point_fit_pressed = False
        self.update()

    def _point_fit_selected_rectangle(self) -> Shape | None:
        """Return the one visible, unlocked rectangle eligible for fitting."""
        if (
            not self.editing()
            or self.is_auto_labeling
            or self.is_brush_mode
            or self.is_magic_wand_mode
            or not self._has_valid_pixmap()
            or len(self.selected_shapes) != 1
        ):
            return None
        shape = self.selected_shapes[0]
        if (
            shape not in self.shapes
            or shape.shape_type != "rectangle"
            or shape.locked
            or not shape.visible
            or not self.is_visible(shape)
            or len(shape.points) != 4
        ):
            return None
        return shape

    @staticmethod
    def _point_fit_shape_box(
        shape: Shape,
    ) -> tuple[float, float, float, float]:
        """Return the image-coordinate bounds of a rectangle."""
        xs = [point.x() for point in shape.points]
        ys = [point.y() for point in shape.points]
        return min(xs), min(ys), max(xs), max(ys)

    def _point_fit_valid_box(
        self, box: tuple[float, float, float, float]
    ) -> bool:
        """Reject undersized or out-of-image fitting proposals."""
        left, top, right, bottom = box
        return (
            right - left >= 1
            and bottom - top >= 1
            and 0 <= left <= right <= self.pixmap.width()
            and 0 <= top <= bottom <= self.pixmap.height()
        )

    def _update_point_fit(self, shape: Shape, pos: QtCore.QPointF) -> None:
        """Calculate a non-mutating preview for the selected rectangle."""
        box = self._point_fit_shape_box(shape)
        decision = point_fit_decision(box, (pos.x(), pos.y()), self.scale)
        proposal = (
            proposed_point_fit_box(box, decision.edge, (pos.x(), pos.y()))
            if decision.edge is not None
            else None
        )
        self._point_fit_target = shape
        self._point_fit_cursor = QtCore.QPointF(pos)
        self._point_fit_pending_box = (
            proposal
            if proposal and self._point_fit_valid_box(proposal)
            else None
        )
        if decision.edge is None:
            hint = QtCore.QCoreApplication.translate(
                "Canvas", "Unable to infer corner."
            )
        elif self._point_fit_pending_box is None:
            hint = QtCore.QCoreApplication.translate(
                "Canvas", "Rectangle is outside the image or too small."
            )
        else:
            hint = ""
        self.setToolTip(hint)
        self.update()

    def _point_fit_move(
        self, pos: QtCore.QPointF, modifiers: Qt.KeyboardModifier
    ) -> bool:
        """Preview a fit or consume a cancelled in-progress gesture."""
        if not modifiers & Qt.KeyboardModifier.ShiftModifier:
            if self._point_fit_pressed:
                self._clear_point_fit(keep_press=True)
                return True
            if self._point_fit_cursor is not None:
                self._clear_point_fit()
            return False
        shape = self._point_fit_selected_rectangle()
        if shape is None or (
            self._point_fit_pressed and shape is not self._point_fit_target
        ):
            self._clear_point_fit(keep_press=self._point_fit_pressed)
            return self._point_fit_pressed
        self._update_point_fit(shape, pos)
        return True

    def _point_fit_press(
        self, pos: QtCore.QPointF, modifiers: Qt.KeyboardModifier
    ) -> bool:
        """Capture one Shift-left gesture when a valid target is selected."""
        shape = self._point_fit_selected_rectangle()
        if not modifiers & Qt.KeyboardModifier.ShiftModifier or shape is None:
            return False
        self._point_fit_pressed = True
        self._point_fit_start = tuple((p.x(), p.y()) for p in shape.points)
        self._update_point_fit(shape, pos)
        return True

    def _point_fit_release(
        self, pos: QtCore.QPointF, modifiers: Qt.KeyboardModifier
    ) -> bool:
        """Commit one valid fit and record it as one undoable operation."""
        if not self._point_fit_pressed:
            return False
        shape = self._point_fit_target
        start = self._point_fit_start
        valid = (
            bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
            and shape is not None
            and shape is self._point_fit_selected_rectangle()
            and tuple((p.x(), p.y()) for p in shape.points) == start
        )
        if valid:
            self._update_point_fit(shape, pos)
        proposal = self._point_fit_pending_box if valid else None
        changed = (
            proposal is not None
            and proposal != self._point_fit_shape_box(shape)
        )
        if changed:
            current = [item.to_dict() for item in self.shapes]
            if (
                not self.shapes_backups
                or [item.to_dict() for item in self.shapes_backups[-1]]
                != current
            ):
                self.store_shapes()
            left, top, right, bottom = proposal
            shape.points = [
                QtCore.QPointF(left, top),
                QtCore.QPointF(right, top),
                QtCore.QPointF(right, bottom),
                QtCore.QPointF(left, bottom),
            ]
            self.store_shapes()
            self.shape_moved.emit()
        self._clear_point_fit()
        if changed:
            self.deselect_shape()
        return True

    def _point_fit_handle_release_event(
        self, event: QtGui.QMouseEvent
    ) -> bool:
        """Consume the mouse release belonging to a point-fit gesture."""
        if (
            event.button() != Qt.MouseButton.LeftButton
            or not self._point_fit_pressed
        ):
            return False
        if not self._point_fit_release(
            self.transform_pos(event.position()), event.modifiers()
        ):
            return False
        event.accept()
        return True

    def _paint_point_fit(self, painter: QtGui.QPainter) -> None:
        """Draw the pending rectangle and point without modifying data."""
        if self._point_fit_cursor is None:
            return
        painter.save()
        color = (
            QtGui.QColor("#00d9e8")
            if self._point_fit_pending_box
            else QtGui.QColor("#ff5c5c")
        )
        pen = QtGui.QPen(color)
        pen.setCosmetic(True)
        pen.setWidth(2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self._point_fit_pending_box:
            left, top, right, bottom = self._point_fit_pending_box
            painter.drawRect(
                QtCore.QRectF(left, top, right - left, bottom - top)
            )
        painter.drawEllipse(
            self._point_fit_cursor, 4 / self.scale, 4 / self.scale
        )
        painter.restore()
