"""Geometry tests for Ctrl rubber-band selection."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PyQt6.QtCore")

from anylabeling.views.labeling.widgets.selection.geometry import (  # noqa: E402
    normalize_selection_rect,
    shapes_intersecting_rect,
)


class _Shape:
    """Shape double exposing the Canvas geometry contract."""

    def __init__(self, rect):
        self.rect = rect

    def bounding_rect(self):
        """Return the configured bounding rectangle."""
        return self.rect


def test_normalize_selection_rect_accepts_reverse_drag():
    """Dragging in any direction yields a positive rectangle."""
    rect = normalize_selection_rect(
        QtCore.QPointF(10, 20), QtCore.QPointF(2, 4)
    )
    assert rect == QtCore.QRectF(2, 4, 8, 16)


def test_shapes_intersecting_rect_keeps_interactive_candidates():
    """Hidden candidates are filtered before selection is committed."""
    inside = _Shape(QtCore.QRectF(2, 2, 4, 4))
    outside = _Shape(QtCore.QRectF(30, 30, 4, 4))
    hidden = _Shape(QtCore.QRectF(3, 3, 4, 4))
    result = shapes_intersecting_rect(
        [inside, outside, hidden],
        QtCore.QRectF(0, 0, 10, 10),
        lambda shape: shape is not hidden,
    )
    assert result == [inside]
