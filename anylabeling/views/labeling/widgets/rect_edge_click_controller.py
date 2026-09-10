"""Bridge finite click regions to the existing canvas edge transactions."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PyQt6 import QtCore, QtGui, QtWidgets

from .. import rect_edge_alignment as rea
from .. import rect_edge_click as rec

if TYPE_CHECKING:
    from .canvas import Canvas


def translate(text: str) -> str:
    """Translate click-specific messages in a stable context."""
    return QtCore.QCoreApplication.translate("RectangleEdgeClick", text)


@dataclass(frozen=True)
class ClickLock:
    """Freeze the target, geometry and precise press position until release."""

    edge: rea.RectEdgeRef
    box: rec.Box
    point: QtCore.QPointF
    points: tuple[tuple[float, float], ...]


class RectEdgeClickController:
    """Own transient click state without extending the edge drag state model."""

    def __init__(self, canvas: Canvas) -> None:
        """Attach to one canvas; no state is stored on annotation shapes."""
        self.canvas = canvas
        self.lock: ClickLock | None = None
        self.preview: QtCore.QRectF | None = None
        self.pointer: QtCore.QPointF | None = None
        self.preview_box: rec.Box | None = None
        self.preview_shape = None
        self.consume_release = False
        self.last_commit: tuple[object, QtCore.QPointF, float] | None = None
        self.message = ""

    def active(self, modifiers: QtCore.Qt.KeyboardModifier) -> bool:
        """Require a selected editable rectangle and refinement or Alt."""
        canvas = self.canvas
        reserved = (
            QtCore.Qt.KeyboardModifier.ControlModifier
            | QtCore.Qt.KeyboardModifier.MetaModifier
        )
        return bool(
            not modifiers & reserved
            and canvas._selected_rect_edge_shape() is not None
            and canvas.pixmap is not None
            and not canvas.pixmap.isNull()
            and (
                canvas.rectangle_review_refinement_enabled
                or modifiers & QtCore.Qt.KeyboardModifier.AltModifier
            )
        )

    def clear(self) -> None:
        """Cancel transient state while swallowing an interrupted release."""
        self.consume_release |= self.lock is not None
        self.lock = None
        self.preview = None
        self.preview_box = None
        self.preview_shape = None
        self.last_commit = None
        self.pointer = None
        if self.message:
            self.notify("")

    def promote(self) -> None:
        """Hand a pending click over to the existing edge drag transaction."""
        self.lock = None
        self.preview = None
        self.preview_box = None
        self.preview_shape = None

    def notify(self, message: str) -> None:
        """Send a deduplicated status message without opening a dialog."""
        if message == self.message:
            return
        self.message = message
        self.canvas.setStatusTip(message)
        QtWidgets.QApplication.sendEvent(
            self.canvas, QtGui.QStatusTipEvent(message)
        )

    def decision(
        self, pos: QtCore.QPointF
    ) -> tuple[rec.ClickDecision, rea.RectGeometry | None]:
        """Validate the original box and classify an image-space position."""
        canvas = self.canvas
        geometry = rea.geometry_from_shape(canvas._selected_rect_edge_shape())
        if geometry is None or not self.valid_box(self.box(geometry)):
            return rec.ClickDecision(None, rec.REASON_INVALID_BOX), geometry
        if not self.in_image(pos):
            return rec.ClickDecision(None, rec.REASON_OUT_OF_RANGE), geometry
        return (
            rec.classify(self.box(geometry), (pos.x(), pos.y()), canvas.scale),
            geometry,
        )

    @staticmethod
    def box(geometry: rea.RectGeometry) -> rec.Box:
        """Convert the shared geometry value into pure coordinates."""
        return (geometry.x_min, geometry.y_min, geometry.x_max, geometry.y_max)

    def in_image(self, pos: QtCore.QPointF) -> bool:
        """Use the existing last-pixel boundary convention, without clamp."""
        pixmap = self.canvas.pixmap
        return bool(
            pixmap is not None
            and 0 <= pos.x() <= pixmap.width() - 1
            and 0 <= pos.y() <= pixmap.height() - 1
        )

    def valid_box(self, box: rec.Box) -> bool:
        """Reject undersized or out-of-image proposals before mutation."""
        left, top, right, bottom = box
        return (
            right - left >= 1
            and bottom - top >= 1
            and self.in_image(QtCore.QPointF(left, top))
            and self.in_image(QtCore.QPointF(right, bottom))
        )

    def at_vertex(self, pos: QtCore.QPointF) -> bool:
        """Preserve the original selected rectangle's vertex drag handles."""
        canvas = self.canvas
        shape = canvas._selected_rect_edge_shape()
        return bool(
            shape is not None
            and shape.nearest_vertex(pos, canvas.epsilon / canvas.scale)
            is not None
        )

    def hover(
        self, pos: QtCore.QPointF, modifiers: QtCore.Qt.KeyboardModifier
    ) -> bool:
        """Preview one candidate, consuming hover only within its domain."""
        canvas = self.canvas
        self.pointer = QtCore.QPointF(pos)
        previous = self.preview_box
        self.preview = None
        self.preview_box = None
        self.preview_shape = None
        if not self.active(modifiers) or self.at_vertex(pos):
            self.notify("")
            if previous is not None:
                canvas.update()
            return False
        decision, geometry = self.decision(pos)
        if decision.reason in (
            rec.REASON_OUT_OF_RANGE,
            rec.REASON_INVALID_BOX,
        ):
            self.notify("")
            if previous is not None:
                canvas.update()
            return False
        canvas.un_highlight()
        canvas.rect_edge_state.set_hover(None)
        canvas.override_cursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.preview_box = self.box(geometry)
        self.preview_shape = canvas._selected_rect_edge_shape()
        if decision.edge is not None:
            edge = rea.edge_from_geometry(
                self.preview_shape, geometry, decision.edge
            )
            proposal = rec.proposed_box(
                self.preview_box, decision.edge, (pos.x(), pos.y())
            )
            if self.valid_box(proposal):
                self.preview = self.rect(proposal)
                canvas.rect_edge_state.set_hover(edge)
                canvas.override_cursor(canvas._rect_edge_cursor(edge))
                self.notify(
                    translate("Click to move the {edge} edge here.").format(
                        edge=self.edge_label(decision.edge)
                    )
                )
            else:
                self.notify(
                    translate("Rejected: image bounds or minimum size.")
                )
        else:
            self.notify(translate("Region boundary; rectangle unchanged."))
        canvas.update()
        return True

    @staticmethod
    def rect(box: rec.Box) -> QtCore.QRectF:
        """Return a painter rectangle in image coordinates."""
        return QtCore.QRectF(box[0], box[1], box[2] - box[0], box[3] - box[1])

    @staticmethod
    def edge_label(edge: str) -> str:
        """Localize one side name independently of the workbench widget."""
        return translate(
            {
                "top": "Top",
                "right": "Right",
                "bottom": "Bottom",
                "left": "Left",
            }[edge]
        )

    def double_click(self, event: QtGui.QMouseEvent) -> bool:
        """Suppress only a nearby second click on the same selected object."""
        if self.last_commit is None:
            return False
        shape, position, timestamp = self.last_commit
        return bool(
            shape is self.canvas._selected_rect_edge_shape()
            and (time.monotonic() - timestamp) * 1000
            < QtWidgets.QApplication.doubleClickInterval()
            and QtCore.QLineF(position, event.position()).length()
            <= QtWidgets.QApplication.styleHints().mouseDoubleClickDistance()
        )

    def press(self, pos: QtCore.QPointF, event: QtGui.QMouseEvent) -> bool:
        """Lock a click or consume a rejected point before native selection."""
        self.consume_release = False
        if not self.active(event.modifiers()):
            return False
        if self.double_click(event):
            self.consume_release = True
            return True
        if self.at_vertex(pos):
            return False
        decision, geometry = self.decision(pos)
        if decision.reason == rec.REASON_OUT_OF_RANGE:
            return False
        if decision.edge is None:
            self.consume_release = True
            self.notify(
                translate("Region boundary; rectangle unchanged.")
                if decision.reason == rec.REASON_DEAD_ZONE
                else translate("Rejected: image bounds or minimum size.")
            )
            return True
        canvas = self.canvas
        shape = canvas._selected_rect_edge_shape()
        canvas.clear_rect_edge_alignment()
        edge = rea.edge_from_geometry(shape, geometry, decision.edge)
        self.lock = ClickLock(
            edge,
            self.box(geometry),
            QtCore.QPointF(pos),
            tuple((p.x(), p.y()) for p in shape.points),
        )
        canvas.prev_point = QtCore.QPointF(pos)
        canvas.prev_pan_point = event.position()
        canvas.rect_edge_state.begin_pending(edge, event.position(), pos)
        self.hover(pos, event.modifiers())
        return True

    def lock_valid(self, modifiers: QtCore.Qt.KeyboardModifier) -> bool:
        """Revalidate identity, visibility, mode and unchanged source points."""
        lock = self.lock
        return bool(
            lock is not None
            and self.active(modifiers)
            and self.canvas._rect_edge_pending_is_valid()
            and lock.edge.shape is self.canvas._selected_rect_edge_shape()
            and tuple((p.x(), p.y()) for p in lock.edge.shape.points)
            == lock.points
        )

    def move(self, event: QtGui.QMouseEvent) -> bool:
        """Cancel stale presses before the native pending-to-drag path runs."""
        if self.consume_release:
            if event.buttons() & QtCore.Qt.MouseButton.LeftButton:
                return True
            self.consume_release = False
        if self.lock is not None and (
            not event.buttons() & QtCore.Qt.MouseButton.LeftButton
            or not self.lock_valid(event.modifiers())
        ):
            self.canvas.clear_rect_edge_alignment()
            self.canvas.update()
            return True
        return False

    def release(self, event: QtGui.QMouseEvent) -> bool:
        """Commit the locked coordinate, or let a promoted drag finish."""
        canvas = self.canvas
        if self.consume_release:
            self.consume_release = False
            return True
        if self.lock is None:
            return False
        if not self.lock_valid(event.modifiers()):
            canvas.clear_rect_edge_alignment()
            self.consume_release = False
            canvas.update()
            return True
        lock = self.lock
        if canvas._rect_edge_pending_has_moved(event.position()):
            canvas._start_rect_edge_drag(lock.edge, lock.point)
            pos = canvas.transform_pos(event.position())
            canvas._rect_edge_drag_update(
                canvas._effective_drag_pos(pos, event)
            )
            return False
        self.commit(lock, event.position())
        return True

    def commit(self, lock: ClickLock, screen_pos: QtCore.QPointF) -> None:
        """Use the existing dirty, undo and edge feedback notification chain."""
        canvas = self.canvas
        edge = lock.edge
        point = (lock.point.x(), lock.point.y())
        proposal = rec.proposed_box(lock.box, edge.edge_name, point)
        self.lock = None
        canvas.clear_rect_edge_alignment()
        if not self.valid_box(proposal):
            self.notify(translate("Rejected: image bounds or minimum size."))
            canvas.update()
            return
        coord = point[0] if edge.axis == rea.RECT_EDGE_AXIS_X else point[1]
        if math.isclose(coord, edge.coord, rel_tol=0.0, abs_tol=1e-9):
            canvas.update()
            return
        canvas.rectangle_review_edge_drag_started.emit(edge.edge_name)
        rea.apply_edge_coord(edge.shape, edge.edge_name, coord)
        canvas.notify_shape_changed(edge.shape)
        canvas.store_shapes()
        canvas.shape_moved.emit()
        refreshed = rea.edge_from_geometry(
            edge.shape, rea.geometry_from_shape(edge.shape), edge.edge_name
        )
        canvas.rect_edge_state.active_edge = refreshed
        canvas.rectangle_review_edge_drag_delta.emit(coord - edge.coord)
        canvas._set_rectangle_review_feedback(
            refreshed, "committed", edge.coord
        )
        canvas.rectangle_review_edge_drag_finished.emit(True)
        canvas.rect_edge_state.active_edge = None
        canvas.rectangle_review_feedback_changed.emit(
            canvas.rectangle_review_feedback_snapshot
        )
        canvas._emit_show_shape_from_shape(edge.shape, lock.point)
        self.last_commit = (
            edge.shape,
            QtCore.QPointF(screen_pos),
            time.monotonic(),
        )
        self.notify(
            translate(
                "{edge} edge moved to click (delta {delta:+.1f}px)."
            ).format(
                edge=self.edge_label(edge.edge_name), delta=coord - edge.coord
            )
        )
        canvas.override_cursor(QtCore.Qt.CursorShape.ArrowCursor)
        canvas.update()

    def modifiers_changed(self, modifiers: QtCore.Qt.KeyboardModifier) -> None:
        """Refresh Alt previews without requiring an extra mouse movement."""
        if self.lock is not None and not self.active(modifiers):
            self.canvas.clear_rect_edge_alignment()
        if self.lock is not None or self.canvas.rect_edge_dragging:
            return
        if self.pointer is not None and self.hover(self.pointer, modifiers):
            return
        self.preview = None
        self.preview_box = None
        self.canvas.rect_edge_state.set_hover(None)
        self.canvas.override_cursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.notify("")
        self.canvas.update()

    def draw(self, painter: QtGui.QPainter) -> None:
        """Draw bounded diagonal guides and the exact uncommitted rectangle."""
        canvas = self.canvas
        if (
            self.preview_box is None
            or self.preview_shape is not canvas._selected_rect_edge_shape()
            or canvas.rect_edge_dragging
        ):
            return
        painter.save()
        painter.setClipRect(QtCore.QRectF(canvas.pixmap.rect()))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        pen = QtGui.QPen(QtGui.QColor(160, 160, 160, 130))
        pen.setCosmetic(True)
        pen.setStyle(QtCore.Qt.PenStyle.DotLine)
        painter.setPen(pen)
        outer = self.rect(rec.effective_box(self.preview_box))
        painter.drawRect(outer)
        painter.drawLine(outer.topLeft(), outer.bottomRight())
        painter.drawLine(outer.topRight(), outer.bottomLeft())
        if self.preview is not None:
            pen.setColor(QtGui.QColor(255, 220, 80, 230))
            pen.setStyle(QtCore.Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRect(self.preview)
        painter.restore()
