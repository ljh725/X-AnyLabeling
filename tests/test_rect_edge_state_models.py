"""Tests for rectangle-edge interaction state and rendering."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtGui  # noqa: E402

from anylabeling.views.labeling.rect_edge_alignment import (  # noqa: E402
    iter_edges,
)
from anylabeling.views.labeling.rect_edge_interaction import (  # noqa: E402
    RectEdgeInteractionController,
    RectEdgePhase,
)
from anylabeling.views.labeling.shape import Shape  # noqa: E402


def _rectangle():
    """Return a rectangle suitable for state-model tests."""
    shape = Shape(label="person", shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(10.0, 10.0),
        QtCore.QPointF(60.0, 10.0),
        QtCore.QPointF(60.0, 50.0),
        QtCore.QPointF(10.0, 50.0),
    ]
    return shape


def test_rect_edge_controller_has_explicit_mouse_phases():
    """Mouse edge interaction follows idle-hover-pending-dragging."""
    shape = _rectangle()
    edge = next(item for item in iter_edges(shape) if item.edge_name == "left")
    state = RectEdgeInteractionController()

    assert state.phase is RectEdgePhase.IDLE

    state.set_hover(edge)
    assert state.phase is RectEdgePhase.HOVER

    state.begin_pending(
        edge,
        QtCore.QPointF(10.0, 30.0),
        QtCore.QPointF(10.0, 30.0),
    )
    assert state.phase is RectEdgePhase.PENDING

    state.start_drag(edge, shape.points)
    assert state.phase is RectEdgePhase.DRAGGING

    restore = state.cancel_drag()
    assert restore is not None
    assert restore[0] is shape
    assert [(point.x(), point.y()) for point in restore[1]] == [
        (10.0, 10.0),
        (60.0, 10.0),
        (60.0, 50.0),
        (10.0, 50.0),
    ]
    assert state.phase is RectEdgePhase.IDLE


def test_shape_edge_rendering_uses_parameter_not_model_state():
    """Edge-edit colour override is passed to paint, not stored on Shape."""
    shape = _rectangle()
    shape.selected = True
    shape.line_color = QtGui.QColor(255, 0, 0)
    shape.select_line_color = QtGui.QColor(0, 255, 0)
    image = QtGui.QImage(80, 70, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    try:
        shape.paint(painter, force_unselected=True)
    finally:
        painter.end()

    edge_pixel = image.pixelColor(30, 10)
    assert edge_pixel.red() > edge_pixel.green()
    assert not hasattr(shape, "edge_editing")
