"""QPainter renderer for the transient rubber-band selection rectangle."""

from PyQt6 import QtCore, QtGui


class RubberBandRenderer:
    """Draw a lightweight selection rectangle over the canvas image."""

    def draw(self, painter: QtGui.QPainter, rect: QtCore.QRectF) -> None:
        """Paint ``rect`` using image-space painter coordinates."""
        if rect is None or rect.isEmpty():
            return
        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor(30, 144, 255, 220), 1.5))
        painter.setBrush(QtGui.QBrush(QtGui.QColor(30, 144, 255, 45)))
        painter.drawRect(rect)
        painter.restore()
