# Extracted verbatim from canvas.py; class method, not a standalone module.
    def _draw_crosshair(self, painter: QtGui.QPainter) -> None:
        """Draw cursor-aligned guides without leaking painter state."""
        if (
            not self.cross_line_show
            or not self._crosshair_cursor_active
            or self.pixmap is None
            or self.pixmap.isNull()
        ):
            return

        scale = max(float(self.scale), 1e-12)
        pen = QtGui.QPen(
            QtGui.QColor(self.cross_line_color),
            max(1, int(round(self.cross_line_width / scale))),
            Qt.PenStyle.DashLine,
        )
        painter.save()
        try:
            painter.setPen(pen)
            painter.setOpacity(self.cross_line_opacity)
            painter.drawLine(
                QtCore.QPointF(self.prev_move_point.x(), 0),
                QtCore.QPointF(self.prev_move_point.x(), self.pixmap.height()),
            )
            painter.drawLine(
                QtCore.QPointF(0, self.prev_move_point.y()),
                QtCore.QPointF(self.pixmap.width(), self.prev_move_point.y()),
            )
        finally:
            painter.restore()
