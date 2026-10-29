"""Exercise Shift point fitting through real canvas mouse handlers."""

from collections.abc import Iterator

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.canvas import Canvas


@pytest.fixture(scope="module")
def app() -> QtWidgets.QApplication:
    """Provide a Qt application for isolated canvas tests."""
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def canvas(app: QtWidgets.QApplication) -> Iterator[Canvas]:
    """Create one selected rectangle on a blank in-memory image."""
    widget = Canvas(parent=None)
    widget.pixmap = QtGui.QPixmap(300, 300)
    widget.resize(300, 300)
    shape = Shape(label="person", shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(100, 100),
        QtCore.QPointF(200, 100),
        QtCore.QPointF(200, 200),
        QtCore.QPointF(100, 200),
    ]
    shape.close()
    shape.selected = True
    widget.shapes = [shape]
    widget.selected_shapes = [shape]

    def update_selection(shapes: list[Shape]) -> None:
        for existing in widget.shapes:
            existing.selected = existing in shapes
        widget.selected_shapes = shapes

    widget.selection_changed.connect(update_selection)
    widget.store_shapes()
    yield widget
    widget.close()
    widget.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def send(
    canvas: Canvas,
    kind: QtCore.QEvent.Type,
    point: tuple[float, float],
    shift: bool = True,
    buttons: QtCore.Qt.MouseButton | None = None,
) -> None:
    """Send a mouse event at an image-space position."""
    pos = (QtCore.QPointF(*point) + canvas.offset_to_center()) * canvas.scale
    button = (
        QtCore.Qt.MouseButton.NoButton
        if kind == QtCore.QEvent.Type.MouseMove
        else QtCore.Qt.MouseButton.LeftButton
    )
    if buttons is None:
        buttons = (
            button
            if kind == QtCore.QEvent.Type.MouseButtonPress
            else QtCore.Qt.MouseButton.NoButton
        )
    modifiers = (
        QtCore.Qt.KeyboardModifier.ShiftModifier
        if shift
        else QtCore.Qt.KeyboardModifier.NoModifier
    )
    event = QtGui.QMouseEvent(kind, pos, pos, button, buttons, modifiers)
    {
        QtCore.QEvent.Type.MouseMove: canvas.mouseMoveEvent,
        QtCore.QEvent.Type.MouseButtonPress: canvas.mousePressEvent,
        QtCore.QEvent.Type.MouseButtonRelease: canvas.mouseReleaseEvent,
    }[kind](event)


def coordinates(shape: Shape) -> tuple[float, float, float, float]:
    """Return the rectangle bounds for assertions."""
    xs = [point.x() for point in shape.points]
    ys = [point.y() for point in shape.points]
    return min(xs), min(ys), max(xs), max(ys)


def test_fit_inside_near_center_preview_commit_and_undo(
    canvas: Canvas,
) -> None:
    """Fit one corner and restore the original rectangle with one undo."""
    point = (151.5, 120)
    send(canvas, QtCore.QEvent.Type.MouseMove, point)
    assert canvas._point_fit_pending_box == (100, 120, 151.5, 200)
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, point)
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, point)
    assert coordinates(canvas.shapes[0]) == (100, 120, 151.5, 200)
    canvas.restore_shape()
    assert coordinates(canvas.shapes[0]) == (100, 100, 200, 200)


def test_fit_preserves_opposite_edge_at_image_extent(canvas: Canvas) -> None:
    """Preview and fit keep a fixed edge at the full image height."""
    shape = canvas.shapes[0]
    shape.points = [QtCore.QPointF(x, y) for x, y in
                    ((100, 100), (200, 100), (200, 300), (100, 300))]
    send(canvas, QtCore.QEvent.Type.MouseMove, (170, 150))
    assert canvas._point_fit_pending_box == (100, 150, 170, 300)
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (170, 150))
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (170, 150))
    assert coordinates(shape) == (100, 150, 170, 300)


def test_center_band_rejects_without_changing_selection(
    canvas: Canvas,
) -> None:
    """Ambiguous clicks do not alter the rectangle or its selection."""
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150.5, 120))
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (150.5, 120))
    assert coordinates(canvas.shapes[0]) == (100, 100, 200, 200)
    assert canvas.selected_shapes == [canvas.shapes[0]]


def test_shift_released_before_mouse_cancels(canvas: Canvas) -> None:
    """An incomplete modifier gesture never commits a fit."""
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (151.5, 120))
    send(
        canvas,
        QtCore.QEvent.Type.MouseButtonRelease,
        (151.5, 120),
        shift=False,
    )
    assert coordinates(canvas.shapes[0]) == (100, 100, 200, 200)


def test_locked_shape_cannot_be_fitted(canvas: Canvas) -> None:
    """A locked rectangle retains its original geometry."""
    canvas.shapes[0].locked = True
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (151.5, 120))
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (151.5, 120))
    assert coordinates(canvas.shapes[0]) == (100, 100, 200, 200)


def test_overlapping_shape_does_not_steal_target(canvas: Canvas) -> None:
    """A fit applies to the selected rectangle, not an overlapping one."""
    other = Shape(label="other", shape_type="rectangle")
    other.points = [
        QtCore.QPointF(x, y)
        for x, y in ((140, 110), (250, 110), (250, 250), (140, 250))
    ]
    other.close()
    canvas.shapes.append(other)
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (151.5, 120))
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (151.5, 120))
    assert coordinates(canvas.shapes[0]) == (100, 120, 151.5, 200)
    assert coordinates(other) == (140, 110, 250, 250)


def test_release_and_repress_shift_does_not_restore_cancelled_gesture(
    canvas: Canvas,
) -> None:
    """Repressing Shift after cancellation cannot commit the old gesture."""
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (151.5, 120))
    event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyRelease,
        QtCore.Qt.Key.Key_Shift,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    canvas.keyReleaseEvent(event)
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (151.5, 120))
    assert coordinates(canvas.shapes[0]) == (100, 100, 200, 200)


def test_focus_loss_clears_preview(canvas: Canvas) -> None:
    """Window focus loss clears a transient preview without mutation."""
    send(canvas, QtCore.QEvent.Type.MouseMove, (151.5, 120))
    assert canvas._point_fit_pending_box is not None
    canvas.focusOutEvent(QtGui.QFocusEvent(QtCore.QEvent.Type.FocusOut))
    assert canvas._point_fit_pending_box is None
    assert coordinates(canvas.shapes[0]) == (100, 100, 200, 200)


def test_load_pixmap_cancels_in_progress_fit(canvas: Canvas) -> None:
    """Changing image clears pending fit state before loading new shapes."""
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (151.5, 120))
    canvas.load_pixmap(QtGui.QPixmap(300, 300))
    assert canvas._point_fit_pending_box is None
    assert canvas._point_fit_pressed is False


def test_fit_requires_unique_selected_rectangle(canvas: Canvas) -> None:
    """A multi-selection cannot be modified as a point-fit target."""
    other = Shape(label="other", shape_type="rectangle")
    other.points = [
        QtCore.QPointF(x, y)
        for x, y in ((20, 20), (50, 20), (50, 50), (20, 50))
    ]
    other.close()
    other.selected = True
    canvas.shapes.append(other)
    canvas.selected_shapes.append(other)
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (151.5, 120))
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (151.5, 120))
    assert coordinates(canvas.shapes[0]) == (100, 100, 200, 200)
    assert coordinates(other) == (20, 20, 50, 50)


def test_fit_records_one_undo_step_and_emits_moved(canvas: Canvas) -> None:
    """Successful fitting signals a change and stores one new snapshot."""
    moves = []
    canvas.shape_moved.connect(lambda: moves.append(True))
    baseline = len(canvas.shapes_backups)
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (151.5, 120))
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (151.5, 120))
    assert len(canvas.shapes_backups) == baseline + 1
    assert moves == [True]


def test_invalid_proposal_does_not_create_undo(canvas: Canvas) -> None:
    """An out-of-image proposal is rejected without creating history."""
    baseline = len(canvas.shapes_backups)
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (310, 120))
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (310, 120))
    assert coordinates(canvas.shapes[0]) == (100, 100, 200, 200)
    assert len(canvas.shapes_backups) == baseline


def test_ambiguous_hint_uses_compiled_chinese_translation(
    canvas: Canvas, app: QtWidgets.QApplication
) -> None:
    """Ambiguous fit feedback is available in the embedded translation."""
    from anylabeling.resources import resources  # noqa: F401

    translator = QtCore.QTranslator()
    assert translator.load(":/languages/translations/zh_CN.qm")
    app.installTranslator(translator)
    try:
        send(canvas, QtCore.QEvent.Type.MouseMove, (150.5, 120))
        assert canvas.toolTip() == "无法判断角点。"
    finally:
        app.removeTranslator(translator)
