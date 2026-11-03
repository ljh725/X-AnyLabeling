"""Shared visual roles for rectangle guide overlays."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6 import QtCore, QtGui


@dataclass(frozen=True)
class RectangleGuidePalette:
    """Colors used by rectangle positioning and candidate feedback."""

    guide: tuple[int, int, int, int] = (0, 150, 230, 220)
    candidate: tuple[int, int, int, int] = (220, 130, 0, 255)
    rejected: tuple[int, int, int, int] = (210, 60, 60, 255)


class RectangleGuideOverlayRenderer:
    """Render shared crosshair, candidate, and rejection feedback."""

    def __init__(self, palette: RectangleGuidePalette | None = None) -> None:
        """Initialize the renderer with an optional visual palette."""
        self.palette = palette or RectangleGuidePalette()

    def guide_pen(self) -> QtGui.QPen:
        """Return the fixed-screen-width cyan guide pen."""
        pen = QtGui.QPen(QtGui.QColor(*self.palette.guide))
        pen.setCosmetic(True)
        pen.setWidthF(1.5)
        pen.setStyle(QtCore.Qt.PenStyle.DashLine)
        return pen

    def candidate_pen(self) -> QtGui.QPen:
        """Return the valid-candidate pen derived from the guide style."""
        pen = self.guide_pen()
        pen.setColor(QtGui.QColor(*self.palette.candidate))
        return pen

    def rejected_pen(self) -> QtGui.QPen:
        """Return the rejected-position pen derived from the guide style."""
        pen = self.guide_pen()
        pen.setColor(QtGui.QColor(*self.palette.rejected))
        pen.setWidthF(2.0)
        return pen

    def render(
        self,
        painter: QtGui.QPainter,
        point: QtCore.QPointF,
        bounds: QtCore.QRectF,
        *,
        candidate_rect: QtCore.QRectF | None = None,
        rejected: bool = False,
        rejected_text: str = "",
        image_scale: float = 1.0,
    ) -> None:
        """Draw rectangle positioning guides without leaking painter state.

        Args:
            painter: Active painter operating in image coordinates.
            point: Current pointer position in image coordinates.
            bounds: Area spanned by the horizontal and vertical guides.
            candidate_rect: Optional valid rectangle proposal.
            rejected: Whether to draw an invalid-position marker.
            rejected_text: Optional message placed beside the marker.
            image_scale: Current canvas scale used for image-space marker size.
        """
        painter.save()
        try:
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.setPen(self.guide_pen())
            painter.drawLine(
                QtCore.QPointF(point.x(), bounds.top()),
                QtCore.QPointF(point.x(), bounds.bottom()),
            )
            painter.drawLine(
                QtCore.QPointF(bounds.left(), point.y()),
                QtCore.QPointF(bounds.right(), point.y()),
            )
            if candidate_rect is not None:
                painter.setPen(self.candidate_pen())
                painter.drawRect(candidate_rect)
            elif rejected:
                painter.setPen(self.rejected_pen())
                radius = 6 / max(float(image_scale), 1e-6)
                painter.drawLine(
                    QtCore.QPointF(point.x() - radius, point.y() - radius),
                    QtCore.QPointF(point.x() + radius, point.y() + radius),
                )
                painter.drawLine(
                    QtCore.QPointF(point.x() - radius, point.y() + radius),
                    QtCore.QPointF(point.x() + radius, point.y() - radius),
                )
                if rejected_text:
                    painter.drawText(
                        QtCore.QPointF(point.x() + radius, point.y() - radius),
                        rejected_text,
                    )
        finally:
            painter.restore()
