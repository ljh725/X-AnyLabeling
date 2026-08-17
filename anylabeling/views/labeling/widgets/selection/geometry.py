"""Geometry helpers for rubber-band selection."""

from collections.abc import Callable, Iterable

from PyQt6 import QtCore


def normalize_selection_rect(start, end) -> QtCore.QRectF:
    """Return a normalized image-space rectangle for two points."""
    return QtCore.QRectF(start, end).normalized()


def _shape_hit_rect(shape, tolerance: float) -> QtCore.QRectF:
    """Return a non-empty selection rectangle for a shape."""
    rect = shape.bounding_rect()
    if rect.width() > 0 and rect.height() > 0:
        return rect
    center = rect.center()
    return QtCore.QRectF(
        center.x() - tolerance,
        center.y() - tolerance,
        tolerance * 2,
        tolerance * 2,
    )


def shapes_intersecting_rect(
    shapes: Iterable,
    selection_rect: QtCore.QRectF,
    is_interactive: Callable,
    tolerance: float = 1.0,
) -> list:
    """Return interactive shapes whose bounds intersect a selection rect.

    The first implementation intentionally uses bounding rectangles. It is
    predictable for all supported shape types, including points and lines,
    and keeps the gesture path independent from shape-specific paint paths.
    """
    if selection_rect.isEmpty():
        return []
    return [
        shape
        for shape in shapes
        if is_interactive(shape)
        and _shape_hit_rect(shape, tolerance).intersects(selection_rect)
    ]
