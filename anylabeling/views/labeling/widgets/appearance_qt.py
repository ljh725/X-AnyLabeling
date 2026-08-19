"""PyQt adapter for toolkit-neutral annotation visual styles."""

from PyQt6 import QtCore, QtGui

from .appearance.types import VisualStyle


class QtAppearanceAdapter:
    """Convert immutable visual styles into short-lived Qt paint objects."""

    @staticmethod
    def color(rgb, alpha=255) -> QtGui.QColor:
        """Create a QColor from an RGB tuple and opacity."""
        return QtGui.QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]), int(alpha))

    @classmethod
    def semantic_pen(cls, style: VisualStyle, scale: float) -> QtGui.QPen:
        """Create the inner semantic pen with screen-stable width."""
        pen = QtGui.QPen(
            cls.color(style.base_color, round(style.object_opacity * 255))
        )
        pen.setWidth(
            max(1, int(round(style.semantic_width / max(scale, 1e-6))))
        )
        return pen

    @classmethod
    def contrast_pen(cls, style: VisualStyle, scale: float) -> QtGui.QPen:
        """Create the outer contrast pen with screen-stable width."""
        color = cls.color(style.outer_color)
        color.setAlphaF(float(style.object_opacity))
        pen = QtGui.QPen(color)
        pen.setWidth(
            max(1, int(round(style.outline_width / max(scale, 1e-6))))
        )
        return pen

    @classmethod
    def fill_brush(cls, style: VisualStyle) -> QtGui.QBrush:
        """Create the configured low-opacity fill brush."""
        return QtGui.QBrush(cls.color(style.base_color, style.fill_opacity))

    @staticmethod
    def badge_text(style: VisualStyle) -> str:
        """Return collision-tolerant identity text for an optional badge."""
        parts = [part for part in (style.label_badge, style.gid_badge) if part]
        return " #".join(parts) if parts else ""

    @staticmethod
    def no_brush() -> QtGui.QBrush:
        """Return a reusable no-fill brush."""
        return QtGui.QBrush(QtCore.Qt.BrushStyle.NoBrush)
