"""Canvas integration tests for Ctrl click and rubber-band selection."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtGui  # noqa: E402


def _rectangle(x, y, width=20, height=20):
    """Build a rectangle for mouse-selection tests."""
    from anylabeling.views.labeling.shape import Shape

    shape = Shape(label="person", shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(x, y),
        QtCore.QPointF(x + width, y),
        QtCore.QPointF(x + width, y + height),
        QtCore.QPointF(x, y + height),
    ]
    return shape


def _point(x, y):
    """Build a point shape for precise hit-test coverage."""
    from anylabeling.views.labeling.shape import Shape

    shape = Shape(label="person", shape_type="point")
    shape.points = [QtCore.QPointF(x, y)]
    return shape


def _mouse_event(event_type, point, button, buttons, modifiers):
    """Build a mouse event with explicit button and modifier state."""
    return QtGui.QMouseEvent(
        event_type,
        QtCore.QPointF(point),
        QtCore.QPointF(point),
        button,
        buttons,
        modifiers,
    )


def _prepare(canvas, shapes):
    """Configure a canvas for image-space mouse events."""
    canvas.shapes = list(shapes)
    canvas.visible = {shape: True for shape in shapes}
    canvas.pixmap = QtGui.QPixmap(200, 120)
    canvas.resize(200, 120)
    canvas.set_editing(True)


@pytest.mark.parametrize("label_on_selection", [False, True])
def test_ctrl_click_selected_shape_removes_it(canvas, label_on_selection):
    """A second Ctrl click toggles an already selected shape off."""
    shape = _point(30, 30)
    _prepare(canvas, [shape])
    canvas.label_on_selection = label_on_selection
    canvas._set_selected_shapes([shape])
    modifiers = QtCore.Qt.KeyboardModifier.ControlModifier

    canvas.mousePressEvent(
        _mouse_event(
            QtCore.QEvent.Type.MouseButtonPress,
            QtCore.QPointF(30, 30),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.LeftButton,
            modifiers,
        )
    )
    canvas.mouseReleaseEvent(
        _mouse_event(
            QtCore.QEvent.Type.MouseButtonRelease,
            QtCore.QPointF(30, 30),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.NoButton,
            modifiers,
        )
    )

    assert canvas.selected_shapes == []
    assert shape.selected is False


def test_plain_click_selected_shape_keeps_selection(canvas):
    """A non-modified click does not act as a toggle operation."""
    shape = _point(30, 30)
    _prepare(canvas, [shape])
    canvas._set_selected_shapes([shape])

    canvas.mousePressEvent(
        _mouse_event(
            QtCore.QEvent.Type.MouseButtonPress,
            QtCore.QPointF(30, 30),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
    )
    canvas.mouseReleaseEvent(
        _mouse_event(
            QtCore.QEvent.Type.MouseButtonRelease,
            QtCore.QPointF(30, 30),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
    )

    assert canvas.selected_shapes == [shape]


def test_ctrl_drag_from_blank_adds_intersecting_shapes(canvas):
    """Ctrl dragging from blank space appends the box candidates once."""
    first = _rectangle(20, 20)
    second = _rectangle(80, 40)
    _prepare(canvas, [first, second])
    canvas._set_selected_shapes([first])
    modifiers = QtCore.Qt.KeyboardModifier.ControlModifier

    canvas.mousePressEvent(
        _mouse_event(
            QtCore.QEvent.Type.MouseButtonPress,
            QtCore.QPointF(5, 5),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.LeftButton,
            modifiers,
        )
    )
    canvas.mouseMoveEvent(
        _mouse_event(
            QtCore.QEvent.Type.MouseMove,
            QtCore.QPointF(110, 75),
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.MouseButton.LeftButton,
            modifiers,
        )
    )
    canvas.mouseReleaseEvent(
        _mouse_event(
            QtCore.QEvent.Type.MouseButtonRelease,
            QtCore.QPointF(110, 75),
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.NoButton,
            modifiers,
        )
    )

    assert canvas.selected_shapes == [first, second]
    assert first.selected is True
    assert second.selected is True
