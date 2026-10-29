"""Interaction contracts for selected-rectangle edge editing."""

from collections.abc import Iterator

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.canvas import Canvas


@pytest.fixture(scope="module")
def app() -> QtWidgets.QApplication:
    """Create the Qt application for canvas tests."""
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def canvas(app: QtWidgets.QApplication) -> Iterator[Canvas]:
    """Create a selected rectangle on an in-memory image."""
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
    widget.store_shapes()
    yield widget
    widget.close()
    widget.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def send(
    canvas: Canvas,
    kind: QtCore.QEvent.Type,
    point: tuple[float, float],
    held: bool = False,
) -> None:
    """Send a normal left-button event at an image-space point."""
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
    event = QtGui.QMouseEvent(
        kind, pos, pos, button, buttons, QtCore.Qt.KeyboardModifier.NoModifier
    )
    {
        QtCore.QEvent.Type.MouseMove: canvas.mouseMoveEvent,
        QtCore.QEvent.Type.MouseButtonPress: canvas.mousePressEvent,
        QtCore.QEvent.Type.MouseButtonRelease: canvas.mouseReleaseEvent,
    }[kind](event)


def bounds(shape: Shape) -> tuple[float, float, float, float]:
    """Return the rectangle bounds."""
    xs = [point.x() for point in shape.points]
    ys = [point.y() for point in shape.points]
    return min(xs), min(ys), max(xs), max(ys)


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ((100, 150), (90, 150), (90, 100, 200, 200)),
        ((200, 150), (210, 150), (100, 100, 210, 200)),
        ((150, 100), (150, 90), (100, 90, 200, 200)),
        ((150, 200), (150, 210), (100, 100, 200, 210)),
    ],
)
def test_one_edge_drag_and_undo(
    canvas: Canvas,
    start: tuple[float, float],
    end: tuple[float, float],
    expected: tuple[float, float, float, float],
) -> None:
    """Dragging changes one edge, keeps selection, and can be undone."""
    canvas.set_rectangle_edge_enabled(True)
    send(canvas, QtCore.QEvent.Type.MouseMove, start)
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, start)
    send(canvas, QtCore.QEvent.Type.MouseMove, end, held=True)
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, end)
    assert bounds(canvas.shapes[0]) == expected
    assert canvas.selected_shapes == [canvas.shapes[0]]
    canvas.restore_shape()
    assert bounds(canvas.shapes[0]) == (100, 100, 200, 200)


def test_corner_has_priority_over_edge(canvas: Canvas) -> None:
    """A corner hit is never claimed by rectangle edge editing."""
    canvas.set_rectangle_edge_enabled(True)
    assert canvas._rectangle_edge_hit(QtCore.QPointF(100, 100)) is None


def test_box_touching_image_extent_can_edit_another_edge(canvas: Canvas) -> None:
    """A box ending at image height remains editable without changing it."""
    shape = canvas.shapes[0]
    shape.points = [QtCore.QPointF(x, y) for x, y in
                    ((100, 100), (200, 100), (200, 300), (100, 300))]
    canvas.set_rectangle_edge_enabled(True)
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (100, 180))
    send(canvas, QtCore.QEvent.Type.MouseMove, (90, 180), held=True)
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (90, 180))
    assert bounds(shape) == (90, 100, 200, 300)


def test_hovered_edge_has_white_feedback(canvas: Canvas) -> None:
    """The selected edge retains the existing white visual feedback."""
    canvas.set_rectangle_edge_enabled(True)
    send(canvas, QtCore.QEvent.Type.MouseMove, (100, 150))
    image = QtGui.QImage(300, 300, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor("black"))
    painter = QtGui.QPainter(image)
    canvas._paint_rectangle_edge(painter)
    painter.end()
    assert image.pixelColor(100, 150) == QtGui.QColor("white")


def test_unselected_and_locked_shapes_cannot_expose_edges(
    canvas: Canvas,
) -> None:
    """Only one visible, unlocked and selected rectangle is eligible."""
    canvas.set_rectangle_edge_enabled(True)
    canvas.shapes[0].locked = True
    assert canvas._rectangle_edge_hit(QtCore.QPointF(100, 150)) is None
    canvas.shapes[0].locked = False
    canvas.selected_shapes = []
    assert canvas._rectangle_edge_hit(QtCore.QPointF(100, 150)) is None


def test_disable_restores_active_drag(canvas: Canvas) -> None:
    """Disabling the feature cancels a live drag without adding history."""
    canvas.set_rectangle_edge_enabled(True)
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (100, 150))
    send(canvas, QtCore.QEvent.Type.MouseMove, (90, 150), held=True)
    canvas.set_rectangle_edge_enabled(False)
    assert bounds(canvas.shapes[0]) == (100, 100, 200, 200)
    assert len(canvas.shapes_backups) == 1


def test_small_rectangle_inner_area_is_not_edge(canvas: Canvas) -> None:
    """A small box uses its interior for moving, not edge dragging."""
    canvas.set_rectangle_edge_enabled(True)
    canvas.shapes[0].points = [
        QtCore.QPointF(100, 100),
        QtCore.QPointF(128, 100),
        QtCore.QPointF(128, 128),
        QtCore.QPointF(100, 128),
    ]
    assert canvas._rectangle_edge_hit(QtCore.QPointF(101, 114)) is None
    assert canvas._rectangle_edge_hit(QtCore.QPointF(98, 114))[1] == "left"


def test_edge_click_without_motion_keeps_selection_and_history(
    canvas: Canvas,
) -> None:
    """A stationary click neither changes geometry nor adds an undo step."""
    canvas.set_rectangle_edge_enabled(True)
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (100, 150))
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (100, 150))
    assert bounds(canvas.shapes[0]) == (100, 100, 200, 200)
    assert canvas.selected_shapes == [canvas.shapes[0]]
    assert len(canvas.shapes_backups) == 1


def test_drag_cannot_flip_rectangle(canvas: Canvas) -> None:
    """Dragging past the opposite edge preserves the minimum width."""
    canvas.set_rectangle_edge_enabled(True)
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (100, 150))
    send(canvas, QtCore.QEvent.Type.MouseMove, (250, 150), held=True)
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (250, 150))
    assert bounds(canvas.shapes[0]) == (199, 100, 200, 200)


def test_escape_cancels_live_drag(canvas: Canvas) -> None:
    """Escape restores the pre-drag rectangle and keeps undo unchanged."""
    canvas.set_rectangle_edge_enabled(True)
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (100, 150))
    send(canvas, QtCore.QEvent.Type.MouseMove, (90, 150), held=True)
    event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_Escape,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    canvas.keyPressEvent(event)
    assert bounds(canvas.shapes[0]) == (100, 100, 200, 200)
    assert len(canvas.shapes_backups) == 1


def test_image_switch_cancels_live_drag(canvas: Canvas) -> None:
    """Changing the pixmap restores a live drag before discarding shapes."""
    canvas.set_rectangle_edge_enabled(True)
    shape = canvas.shapes[0]
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (100, 150))
    send(canvas, QtCore.QEvent.Type.MouseMove, (90, 150), held=True)
    canvas.load_pixmap(QtGui.QPixmap(300, 300))
    assert bounds(shape) == (100, 100, 200, 200)
    assert canvas._rectangle_edge_drag is None


def test_shift_fit_replaces_edge_hover(canvas: Canvas) -> None:
    """The existing Shift fit takes priority over an edge hover."""
    canvas.set_rectangle_edge_enabled(True)
    send(canvas, QtCore.QEvent.Type.MouseMove, (100, 150))
    assert canvas._rectangle_edge_hover is not None
    pos = QtCore.QPointF(151.5, 120)
    event = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseMove,
        pos,
        pos,
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.ShiftModifier,
    )
    canvas.mouseMoveEvent(event)
    assert canvas._rectangle_edge_hover is None
    assert canvas._point_fit_pending_box == (100, 120, 151.5, 200)


def test_main_window_exposes_translated_edge_toggle(
    app: QtWidgets.QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real window exposes the switch and its default shortcut."""
    from pathlib import Path

    import yaml

    from anylabeling.resources import resources  # noqa: F401
    from anylabeling.services.auto_labeling import model_manager
    from anylabeling.views.labeling import label_widget as module

    config_path = (
        Path(__file__).parents[2]
        / "anylabeling/configs/xanylabeling_config.yaml"
    )
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    monkeypatch.setattr(module, "save_config", lambda _config: True)
    monkeypatch.setattr(model_manager, "get_config", lambda: config)
    translator = QtCore.QTranslator()
    assert translator.load(":/languages/translations/zh_CN.qm")
    app.installTranslator(translator)
    window = QtWidgets.QMainWindow()
    wrapper = QtWidgets.QWidget()
    wrapper.parent = window
    widget = module.LabelingWidget(parent=wrapper, config=config)
    window.setCentralWidget(widget)
    try:
        action = widget.rectangle_edge_action
        assert action.text() == "矩形框编辑"
        assert action.shortcut().toString() == "Ctrl+Shift+E"
        assert not widget.canvas._rectangle_edge_enabled
        action.trigger()
        assert widget.canvas._rectangle_edge_enabled
        action.trigger()
        assert not widget.canvas._rectangle_edge_enabled
    finally:
        widget.close()
        window.close()
        app.removeTranslator(translator)
