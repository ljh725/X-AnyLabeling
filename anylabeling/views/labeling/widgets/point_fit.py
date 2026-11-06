"""Shift-click rectangle fitting for the labeling canvas."""

import math

from PyQt6 import QtCore, QtGui
from PyQt6.QtCore import Qt

from ..rect_edge_click import (
    OPPOSITE_CORNER,
    corner_point,
    point_fit_decision,
    proposed_inward_point_fit_box,
    proposed_point_fit_box,
)
from ..rectangle_preview import (
    FIT_CANDIDATE_COLOR,
    FIT_CANDIDATE_WIDTH,
    PointFitPreview,
    build_remaining_outline,
    rectangle_box_from_points,
)
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
        self._point_fit_anchor = None
        self._point_fit_corner = None
        self._point_fit_hover_corner = None
        self._point_fit_box = None
        self._point_fit_inward = False
        self._point_fit_source_target = None
        self._point_fit_source_box = None
        self._point_fit_pointer = None
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
        """Validate clipped proposals using the canvas image extent."""
        left, top, right, bottom = box
        return (
            all(math.isfinite(value) for value in box)
            and right - left >= 1
            and bottom - top >= 1
            and 0 <= left <= right <= self.pixmap.width()
            and 0 <= top <= bottom <= self.pixmap.height()
        )

    def _point_fit_clamp_box(
        self, box: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float] | None:
        """Clip a proposal before checking its remaining image area."""
        if not all(math.isfinite(value) for value in box):
            return None
        left, top, right, bottom = box
        width, height = self.pixmap.width(), self.pixmap.height()
        clipped = (
            max(0.0, min(left, width)),
            max(0.0, min(top, height)),
            max(0.0, min(right, width)),
            max(0.0, min(bottom, height)),
        )
        return clipped if self._point_fit_valid_box(clipped) else None

    def _point_fit_candidate_source_changed(self, target: Shape) -> bool:
        """Return whether the candidate no longer matches its source."""
        return (
            self._point_fit_source_target is not target
            or self._point_fit_source_box is None
            or self._point_fit_shape_box(target) != self._point_fit_source_box
        )

    def _point_fit_capture_geometry_changed(self, target: Shape) -> bool:
        """Return whether a captured gesture lost its press-time geometry."""
        return (
            self._point_fit_box is not None
            and self._point_fit_shape_box(target) != self._point_fit_box
        )

    def _update_point_fit(
        self, shape: Shape, pos: QtCore.QPointF, inward: bool = False
    ) -> None:
        """Calculate a non-mutating preview for the selected rectangle."""
        box = (
            self._point_fit_box
            if self._point_fit_pressed and self._point_fit_box is not None
            else self._point_fit_shape_box(shape)
        )
        point = (pos.x(), pos.y())
        corner = (
            self._point_fit_corner
            if self._point_fit_pressed
            else point_fit_decision(
                box, point, self.scale,
                previous_corner=(
                    self._point_fit_hover_corner
                    if not self._point_fit_candidate_source_changed(shape)
                    else None
                ),
            ).edge
        )
        if not self._point_fit_pressed:
            self._point_fit_hover_corner = corner
        if self._point_fit_pressed:
            inward = self._point_fit_inward
        if corner is None:
            proposal = None
            anchor = None
        else:
            build = (
                proposed_inward_point_fit_box
                if inward
                else proposed_point_fit_box
            )
            proposal = build(box, corner, point)
            anchor = corner_point(
                box,
                corner if inward else OPPOSITE_CORNER[corner],
            )
        width, height = self.pixmap.width(), self.pixmap.height()
        # Record the source of this candidate: the same target with different
        # coordinates or a different target invalidates it.
        self._point_fit_source_target = shape
        self._point_fit_source_box = box
        self._point_fit_pointer = QtCore.QPointF(pos)
        self._point_fit_inward = bool(inward)
        self._point_fit_target = shape
        self._point_fit_cursor = QtCore.QPointF(
            max(0.0, min(pos.x(), width)),
            max(0.0, min(pos.y(), height)),
        )
        self._point_fit_anchor = (
            (max(0.0, min(anchor[0], width)), max(0.0, min(anchor[1], height)))
            if anchor is not None
            else None
        )
        self._point_fit_pending_box = (
            self._point_fit_clamp_box(proposal)
            if proposal is not None
            else None
        )
        if corner is None:
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
        if (
            self._point_fit_pressed
            and self._point_fit_capture_geometry_changed(shape)
        ):
            # Another edit entry moved the captured rectangle: drop the
            # gesture but keep its press so the release is consumed.
            self._clear_point_fit(keep_press=True)
            return True
        inward = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        self._update_point_fit(shape, pos, inward)
        return True

    def _point_fit_refresh_from_cursor(
        self, modifiers: Qt.KeyboardModifier
    ) -> bool:
        """Refresh modifier-only changes without waiting for a mouse move."""
        if (
            self.is_loading
            or self._space_pressed
            or self._right_pan_start is not None
            or self._rectangle_edge_drag is not None
            or (
                (self._pointer_down or QtGui.QGuiApplication.mouseButtons())
                and not self._point_fit_pressed
            )
        ):
            return False
        local = self.mapFromGlobal(QtGui.QCursor.pos())
        if not self.rect().contains(local):
            if not self._point_fit_pressed:
                self._clear_point_fit()
            return False
        handled = self._point_fit_move(
            self.transform_pos(QtCore.QPointF(local)), modifiers
        )
        if handled and self._rectangle_edge_hover is not None:
            self._rectangle_edge_cancel()
        return handled

    def _point_fit_press(
        self, pos: QtCore.QPointF, modifiers: Qt.KeyboardModifier
    ) -> bool:
        """Capture one Shift-left gesture when a valid target is selected."""
        shape = self._point_fit_selected_rectangle()
        if not modifiers & Qt.KeyboardModifier.ShiftModifier or shape is None:
            return False
        self._update_point_fit(
            shape, pos, bool(modifiers & Qt.KeyboardModifier.AltModifier)
        )
        if self._point_fit_pending_box is None:
            self._clear_point_fit()
            return False
        self._point_fit_box = self._point_fit_shape_box(shape)
        # Capture exactly the corner used by the visible, stabilised preview.
        self._point_fit_corner = self._point_fit_hover_corner
        self._point_fit_inward = bool(
            modifiers & Qt.KeyboardModifier.AltModifier
        )
        self._point_fit_pressed = True
        self._point_fit_start = tuple((p.x(), p.y()) for p in shape.points)
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
            inward = bool(modifiers & Qt.KeyboardModifier.AltModifier)
            self._update_point_fit(shape, pos, inward)
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

    def _build_point_fit_preview(self) -> PointFitPreview | None:
        """Snapshot the fit target, candidate, and shared-edge outline.

        The pending candidate is only reused while its recorded source target
        and original geometry still match the rectangle. A hover preview is
        recomputed from the current geometry and the recorded pointer before
        this snapshot; a captured gesture whose geometry changed elsewhere is
        cancelled and its release stays consumed.
        """
        if self._point_fit_cursor is None:
            return None
        target = self._point_fit_target
        if (
            target is not None
            and self._point_fit_selected_rectangle() is target
        ):
            if self._point_fit_pressed:
                if self._point_fit_capture_geometry_changed(target):
                    self._clear_point_fit(keep_press=True)
                    return None
            elif self._point_fit_candidate_source_changed(target):
                pointer = self._point_fit_pointer
                if pointer is None:
                    pointer = self._point_fit_cursor
                self._update_point_fit(target, pointer, self._point_fit_inward)
                target = self._point_fit_target
                if self._point_fit_selected_rectangle() is not target:
                    target = None
        else:
            target = None
        box = (
            rectangle_box_from_points(target.points)
            if target is not None
            else None
        )
        candidate = self._point_fit_pending_box if box is not None else None
        outline_path = None
        if candidate is not None and candidate != box:
            outline_path = build_remaining_outline(
                box, candidate, scale=self.scale
            )
        return PointFitPreview(
            target=target if box is not None else None,
            box=box,
            candidate_box=candidate,
            outline_path=outline_path,
        )

    def _paint_point_fit(self, painter: QtGui.QPainter) -> None:
        """Draw the pending rectangle, its fixed corner, and the point."""
        preview = self._point_fit_preview
        if preview is None:
            return
        painter.save()
        color = (
            QtGui.QColor(FIT_CANDIDATE_COLOR)
            if preview.valid
            else QtGui.QColor("#ff5c5c")
        )
        pen = QtGui.QPen(color)
        pen.setCosmetic(True)
        pen.setWidthF(FIT_CANDIDATE_WIDTH)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if preview.candidate_differs:
            left, top, right, bottom = preview.candidate_box
            candidate_path = QtGui.QPainterPath()
            candidate_path.addRect(
                QtCore.QRectF(left, top, right - left, bottom - top)
            )
            painter.drawPath(candidate_path)
        if preview.valid and self._point_fit_anchor is not None:
            anchor_x, anchor_y = self._point_fit_anchor
            painter.setBrush(color)
            painter.drawEllipse(
                QtCore.QPointF(anchor_x, anchor_y),
                3 / self.scale,
                3 / self.scale,
            )
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(
            self._point_fit_cursor, 4 / self.scale, 4 / self.scale
        )
        painter.restore()
