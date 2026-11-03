"""Drag refresh scheduling for CUSTOM-003.

The production canvas must stop painting the stale position before moving a
rectangle and must let Qt coalesce the remaining refresh requests.  These
tests drive real press/move/release events and count actual paint events, so a
regression that drops the final frame or moves a shape less often is visible,
not just a source-text change.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.canvas import Canvas


@pytest.fixture(scope="module")
def app() -> QtWidgets.QApplication:
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def make_rectangle(label: str, bounds: tuple[float, float, float, float]) -> Shape:
    left, top, right, bottom = bounds
    shape = Shape(label=label, shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(left, top),
        QtCore.QPointF(right, top),
        QtCore.QPointF(right, bottom),
        QtCore.QPointF(left, bottom),
    ]
    shape.close()
    return shape


def rectangle_bounds(shape: Shape) -> tuple[float, float, float, float]:
    xs = [point.x() for point in shape.points]
    ys = [point.y() for point in shape.points]
    return min(xs), min(ys), max(xs), max(ys)


@pytest.fixture
def canvas(app: QtWidgets.QApplication) -> Iterator[Canvas]:
    """A visible canvas holding one selected, editable rectangle."""
    widget = Canvas(parent=None)
    widget.pixmap = QtGui.QPixmap(400, 300)
    widget.pixmap.fill(QtGui.QColor("white"))
    widget.resize(400, 300)
    widget.scale = 1.0
    shape = make_rectangle("person", (100, 100, 200, 200))
    shape.selected = True
    widget.shapes = [shape]
    widget.selected_shapes = [shape]
    widget.store_shapes()
    widget.set_editing(True)
    widget.show()
    app.processEvents()
    yield widget
    widget.restore_cursor()
    widget.close()
    widget.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def send(
    canvas: Canvas,
    kind: QtCore.QEvent.Type,
    point: tuple[float, float],
    held: bool = False,
    modifiers: QtCore.Qt.KeyboardModifier = QtCore.Qt.KeyboardModifier.NoModifier,
) -> None:
    """Deliver one left-button event at an image-space point."""
    pos = (QtCore.QPointF(*point) + canvas.offset_to_center()) * canvas.scale
    button = (
        QtCore.Qt.MouseButton.NoButton
        if kind == QtCore.QEvent.Type.MouseMove
        else QtCore.Qt.MouseButton.LeftButton
    )
    buttons = (
        QtCore.Qt.MouseButton.LeftButton
        if held or kind == QtCore.QEvent.Type.MouseButtonPress
        else QtCore.Qt.MouseButton.NoButton
    )
    event = QtGui.QMouseEvent(kind, pos, pos, button, buttons, modifiers)
    {
        QtCore.QEvent.Type.MouseMove: canvas.mouseMoveEvent,
        QtCore.QEvent.Type.MouseButtonPress: canvas.mousePressEvent,
        QtCore.QEvent.Type.MouseButtonRelease: canvas.mouseReleaseEvent,
    }[kind](event)


@pytest.fixture
def paints(monkeypatch) -> list:
    """Record every paintEvent of the canvas while still running the original."""
    recorded: list = []
    original = Canvas.paintEvent

    def counting(self, event):
        recorded.append(event.rect())
        return original(self, event)

    monkeypatch.setattr(Canvas, "paintEvent", counting)
    return recorded


def test_moves_before_the_event_loop_are_coalesced(
    canvas: Canvas, paints: list, app: QtWidgets.QApplication
) -> None:
    """Several queued moves produce one paint of the newest geometry."""
    shape = canvas.shapes[0]
    send(canvas, QtCore.QEvent.Type.MouseMove, (150, 150))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 150))
    app.processEvents()
    paints.clear()

    for step in range(1, 7):
        send(canvas, QtCore.QEvent.Type.MouseMove, (150 + step, 150 + step), held=True)
        assert not paints, "a move must not paint the stale position"

    app.processEvents()
    assert len(paints) == 1
    assert rectangle_bounds(shape) == (106, 106, 206, 206)


def test_one_paint_per_move_when_the_loop_runs(
    canvas: Canvas, paints: list, app: QtWidgets.QApplication
) -> None:
    """With an idle event loop every move still yields exactly one frame."""
    send(canvas, QtCore.QEvent.Type.MouseMove, (150, 150))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 150))
    app.processEvents()
    paints.clear()

    for step in range(1, 6):
        send(canvas, QtCore.QEvent.Type.MouseMove, (150 + step, 150 + step), held=True)
        app.processEvents()

    assert len(paints) == 5


def test_release_keeps_final_geometry_and_commits_once(
    canvas: Canvas, paints: list, app: QtWidgets.QApplication
) -> None:
    """Release stores the drop position, emits once and paints the last frame."""
    shape = canvas.shapes[0]
    moved = []
    canvas.shape_moved.connect(lambda: moved.append(True))
    backups_before = len(canvas.shapes_backups)

    send(canvas, QtCore.QEvent.Type.MouseMove, (150, 150))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 150))
    for step in range(1, 6):
        send(canvas, QtCore.QEvent.Type.MouseMove, (150 + step, 150 + step), held=True)
    paints.clear()
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (155, 155))
    app.processEvents()

    assert rectangle_bounds(shape) == (105, 105, 205, 205)
    assert moved == [True]
    assert len(canvas.shapes_backups) == backups_before + 1
    assert canvas.is_shape_restorable
    assert len(paints) == 1, "the released position must still be painted"


def test_vertex_drag_is_coalesced(
    canvas: Canvas, paints: list, app: QtWidgets.QApplication
) -> None:
    """Corner dragging follows the same single-frame rule."""
    shape = canvas.shapes[0]
    send(canvas, QtCore.QEvent.Type.MouseMove, (100, 100))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (100, 100))
    app.processEvents()
    paints.clear()

    for step in range(1, 6):
        send(canvas, QtCore.QEvent.Type.MouseMove, (100 - step, 100 - step), held=True)
    app.processEvents()

    assert len(paints) == 1
    assert rectangle_bounds(shape) == (95, 95, 200, 200)


def test_drag_at_image_border_stays_inside(
    canvas: Canvas, paints: list, app: QtWidgets.QApplication
) -> None:
    """The final frame uses the clipped geometry, not the raw pointer position."""
    shape = canvas.shapes[0]
    send(canvas, QtCore.QEvent.Type.MouseMove, (150, 150))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 150))
    send(canvas, QtCore.QEvent.Type.MouseMove, (20, 20), held=True)
    app.processEvents()

    assert rectangle_bounds(shape) == (0, 0, 100, 100)

    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (20, 20))
    app.processEvents()
    assert rectangle_bounds(shape) == (0, 0, 100, 100)


def test_pointer_leaving_the_image_keeps_the_shape(
    canvas: Canvas, paints: list, app: QtWidgets.QApplication
) -> None:
    """Leaving the pixmap is still a no-move, as before the refresh change."""
    shape = canvas.shapes[0]
    send(canvas, QtCore.QEvent.Type.MouseMove, (150, 150))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 150))
    send(canvas, QtCore.QEvent.Type.MouseMove, (-80, -90), held=True)
    app.processEvents()

    assert rectangle_bounds(shape) == (100, 100, 200, 200)


def test_locked_shape_does_not_move(
    canvas: Canvas, paints: list, app: QtWidgets.QApplication
) -> None:
    """A locked rectangle keeps its position while dragging over it."""
    shape = canvas.shapes[0]
    shape.locked = True
    send(canvas, QtCore.QEvent.Type.MouseMove, (150, 150))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 150))
    for step in range(1, 4):
        send(canvas, QtCore.QEvent.Type.MouseMove, (150 + step, 150 + step), held=True)
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (153, 153))
    app.processEvents()

    assert rectangle_bounds(shape) == (100, 100, 200, 200)


def test_multi_selection_moves_together(
    canvas: Canvas, paints: list, app: QtWidgets.QApplication
) -> None:
    """A grouped drag moves every selected rectangle and paints one frame."""
    other = make_rectangle("person", (250, 100, 320, 160))
    other.selected = True
    canvas.shapes.append(other)
    canvas.selected_shapes = [canvas.shapes[0], other]
    canvas.store_shapes()

    send(canvas, QtCore.QEvent.Type.MouseMove, (150, 150))
    send(
        canvas,
        QtCore.QEvent.Type.MouseButtonPress,
        (150, 150),
        modifiers=QtCore.Qt.KeyboardModifier.ControlModifier,
    )
    paints.clear()
    for step in range(1, 5):
        send(canvas, QtCore.QEvent.Type.MouseMove, (150 + step, 150 + step), held=True)
    app.processEvents()

    assert len(paints) == 1
    assert rectangle_bounds(canvas.shapes[0]) == (104, 104, 204, 204)
    assert rectangle_bounds(other) == (254, 104, 324, 164)


def test_undo_restores_geometry_before_the_drag(
    canvas: Canvas, paints: list, app: QtWidgets.QApplication
) -> None:
    """One undo after a coalesced drag restores the pre-drag rectangle."""
    shape = canvas.shapes[0]
    send(canvas, QtCore.QEvent.Type.MouseMove, (150, 150))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 150))
    for step in range(1, 5):
        send(canvas, QtCore.QEvent.Type.MouseMove, (150 + step, 150 + step), held=True)
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (154, 154))
    app.processEvents()
    assert rectangle_bounds(shape) == (104, 104, 204, 204)

    canvas.restore_shape()
    app.processEvents()
    assert rectangle_bounds(canvas.shapes[0]) == (100, 100, 200, 200)


def test_hover_still_refreshes_the_highlight(
    canvas: Canvas, paints: list, app: QtWidgets.QApplication
) -> None:
    """Hover feedback relies on the shared refresh request, so it must paint."""
    send(canvas, QtCore.QEvent.Type.MouseMove, (150, 150))
    app.processEvents()
    assert canvas.h_shape is canvas.shapes[0]
    assert paints

    paints.clear()
    send(canvas, QtCore.QEvent.Type.MouseMove, (380, 280))
    app.processEvents()
    assert canvas.h_shape is None
    assert paints, "leaving the shape must clear the old highlight"


def test_drawing_preview_still_repaints(
    canvas: Canvas, paints: list, app: QtWidgets.QApplication
) -> None:
    """Creating a rectangle still shows the live preview while dragging."""
    canvas.set_editing(False)
    canvas.create_mode = "rectangle"
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (40, 40))
    app.processEvents()
    paints.clear()
    for step in range(1, 5):
        send(canvas, QtCore.QEvent.Type.MouseMove, (40 + step * 5, 40 + step * 5), held=True)
    app.processEvents()

    assert paints
    assert (canvas.line[1].x(), canvas.line[1].y()) == (60.0, 60.0)
