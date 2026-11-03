# Extracted verbatim from canvas.py; class method, not a standalone module.
    def _draw_crosshair(self, painter: QtGui.QPainter) -> None:
        """Draw two-point rectangle creation guides across the full image."""
        if not self._rectangle_creation_crosshair_enabled():
            return

        bounds = QtCore.QRectF(
            0.0,
            0.0,
            float(self.pixmap.width()),
            float(self.pixmap.height()),
        )
        self._rectangle_guide_renderer.render(
            painter,
            self.prev_move_point,
            bounds,
            image_scale=self.scale,
        )
