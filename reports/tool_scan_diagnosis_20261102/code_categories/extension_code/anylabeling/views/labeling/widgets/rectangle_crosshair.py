"""Temporary crosshair for two-point rectangle creation."""

from __future__ import annotations

from PyQt6 import QtCore, QtGui

GUIDE_COLOR = QtGui.QColor(0, 150, 230, 220)
GUIDE_WIDTH = 1.5


class RectangleCrosshairMixin:
    """Track and render the two-point rectangle drawing guide.

    The guide is a fork-specific behaviour: it is only visible while a
    two-point rectangle is being drawn, so editing and other creation
    modes stay free of full-image lines. Visibility is controlled by
    ``canvas.crosshair.show_when_drawing`` and is independent from the
    native ``canvas.crosshair.show`` setting, which keeps driving the
    always-on crosshair.
    """

    def _rectangle_creation_crosshair_enabled(
        self, cursor_active: bool | None = None
    ) -> bool:
        """Return whether the current drawing context should show a guide."""
        if cursor_active is None:
            cursor_active = getattr(self, "_crosshair_cursor_active", False)
        workflow = getattr(self, "rectangle_creation", None)
        return bool(
            getattr(self, "rectangle_creation_crosshair_show", True)
            and self.drawing()
            and self.create_mode == "rectangle"
            and self.pixmap is not None
            and not self.pixmap.isNull()
            and (workflow is None or workflow.draft is None)
            and cursor_active
        )

    def _native_crosshair_enabled(self) -> bool:
        """Return whether the always-on native crosshair should be painted.

        While the two-point creation guide is visible the native lines are
        suppressed so the canvas never shows two superimposed crosshairs
        with different styling.
        """
        return bool(
            self.cross_line_show
            and not self._rectangle_creation_crosshair_enabled()
        )

    def _update_crosshair_cursor(self, pos: QtCore.QPointF) -> None:
        """Track the pointer and redraw when a visible guide changes."""
        previous = self.prev_move_point
        was_active = getattr(self, "_crosshair_cursor_active", False)
        was_visible = self._rectangle_creation_crosshair_enabled(was_active)
        self.prev_move_point = QtCore.QPointF(pos)
        self._crosshair_cursor_active = bool(
            self.pixmap is not None
            and not self.pixmap.isNull()
            and 0 <= pos.x() < self.pixmap.width()
            and 0 <= pos.y() < self.pixmap.height()
        )
        is_visible = self._rectangle_creation_crosshair_enabled()
        if (
            previous != pos or was_active != self._crosshair_cursor_active
        ) and (was_visible or is_visible):
            self.update()

    def _clear_crosshair_cursor(self) -> None:
        """Clear the pointer state and repaint a previously visible guide."""
        was_visible = self._rectangle_creation_crosshair_enabled()
        self._crosshair_cursor_active = False
        if was_visible:
            self.update()

    def _draw_rectangle_crosshair(self, painter: QtGui.QPainter) -> None:
        """Draw the fork's cyan guide across the image when eligible."""
        if not self._rectangle_creation_crosshair_enabled():
            return
        bounds = QtCore.QRectF(
            0.0, 0.0, float(self.pixmap.width()), float(self.pixmap.height())
        )
        point = self.prev_move_point
        painter.save()
        try:
            pen = QtGui.QPen(QtGui.QColor(GUIDE_COLOR))
            pen.setCosmetic(True)
            pen.setWidthF(GUIDE_WIDTH)
            pen.setStyle(QtCore.Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawLine(
                QtCore.QPointF(point.x(), bounds.top()),
                QtCore.QPointF(point.x(), bounds.bottom()),
            )
            painter.drawLine(
                QtCore.QPointF(bounds.left(), point.y()),
                QtCore.QPointF(bounds.right(), point.y()),
            )
        finally:
            painter.restore()
