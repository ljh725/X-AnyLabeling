"""Wheel gesture priority for direct/traditional navigation modes.

One wheel event must produce exactly one behaviour: brush radius, rectangle
editing, compare split, zoom or scroll.  The tests drive ``Canvas.wheelEvent``
directly so modifier handling is verified without a visible window.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtGui, QtTest, QtWidgets

from anylabeling.resources import resources  # noqa: F401
from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.canvas import Canvas

Qt = QtCore.Qt
ALT = Qt.KeyboardModifier.AltModifier
CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
NO_MOD = Qt.KeyboardModifier.NoModifier
HORIZONTAL = Qt.Orientation.Horizontal
VERTICAL = Qt.Orientation.Vertical


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def canvas(app):
    widget = Canvas(parent=None, wheel_navigation_mode="direct")
    widget.pixmap = QtGui.QPixmap(200, 200)
    widget.pixmap.fill(QtGui.QColor("black"))
    widget.resize(200, 200)
    yield widget
    widget.close()
    widget.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def wheel(canvas, delta=120, pixel=None, modifiers=NO_MOD, point=(100, 100)):
    position = QtCore.QPointF(*point)
    angle = QtCore.QPoint(0, delta)
    pixel_delta = QtCore.QPoint(*pixel) if pixel else QtCore.QPoint()
    event = QtGui.QWheelEvent(
        position,
        position,
        pixel_delta,
        angle,
        Qt.MouseButton.NoButton,
        modifiers,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    canvas.wheelEvent(event)


def make_rectangle():
    shape = Shape(label="object", shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(50, 50),
        QtCore.QPointF(150, 50),
        QtCore.QPointF(150, 100),
        QtCore.QPointF(50, 100),
    ]
    shape.close()
    return shape


def test_invalid_mode_falls_back_to_direct(app):
    widget = Canvas(parent=None, wheel_navigation_mode="unsupported")
    assert widget.wheel_navigation_mode == "direct"
    widget.close()
    widget.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def test_direct_bare_wheel_zooms_without_scrolling(canvas):
    zooms = QtTest.QSignalSpy(canvas.zoom_request)
    scrolls = QtTest.QSignalSpy(canvas.scroll_request)

    wheel(canvas, delta=120)

    assert len(zooms) == 1
    assert len(scrolls) == 0


def test_traditional_bare_wheel_scrolls_without_zooming(canvas):
    canvas.wheel_navigation_mode = "traditional"
    zooms = QtTest.QSignalSpy(canvas.zoom_request)
    scrolls = QtTest.QSignalSpy(canvas.scroll_request)

    wheel(canvas, delta=120)

    assert len(zooms) == 0
    assert len(scrolls) == 1
    assert [list(args)[1] for args in scrolls] == [VERTICAL]


@pytest.mark.parametrize("mode", ["direct", "traditional"])
def test_ctrl_wheel_always_zooms(canvas, mode):
    canvas.wheel_navigation_mode = mode
    zooms = QtTest.QSignalSpy(canvas.zoom_request)
    scrolls = QtTest.QSignalSpy(canvas.scroll_request)

    wheel(canvas, delta=-120, modifiers=CTRL)

    assert len(zooms) == 1
    assert len(scrolls) == 0


@pytest.mark.parametrize("mode", ["direct", "traditional"])
def test_shift_wheel_always_scrolls(canvas, mode):
    canvas.wheel_navigation_mode = mode
    zooms = QtTest.QSignalSpy(canvas.zoom_request)
    scrolls = QtTest.QSignalSpy(canvas.scroll_request)

    wheel(canvas, delta=-120, modifiers=SHIFT)

    assert len(zooms) == 0
    assert [list(args)[1] for args in scrolls] == [VERTICAL]


def test_horizontal_wheel_only_scrolls_in_traditional_mode(canvas):
    zooms = QtTest.QSignalSpy(canvas.zoom_request)
    scrolls = QtTest.QSignalSpy(canvas.scroll_request)

    wheel(canvas, delta=0, pixel=(120, 0), modifiers=NO_MOD)
    assert len(zooms) == 0
    assert len(scrolls) == 0

    canvas.wheel_navigation_mode = "traditional"
    wheel(canvas, delta=0, pixel=(120, 0), modifiers=NO_MOD)
    assert len(zooms) == 0
    assert len(scrolls) == 1


def test_horizontal_component_is_scrolled_alone(canvas):
    canvas.wheel_navigation_mode = "traditional"
    scrolls = QtTest.QSignalSpy(canvas.scroll_request)
    position = QtCore.QPointF(100, 100)
    event = QtGui.QWheelEvent(
        position,
        position,
        QtCore.QPoint(100, 0),
        QtCore.QPoint(100, 0),
        Qt.MouseButton.NoButton,
        NO_MOD,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )

    canvas.wheelEvent(event)

    assert len(scrolls) == 1
    assert list(scrolls[0])[1] == HORIZONTAL


def test_alt_wheel_resizes_brush_without_zooming(canvas):
    canvas.is_brush_mode = True
    radius = canvas.brush_radius
    zooms = QtTest.QSignalSpy(canvas.zoom_request)
    scrolls = QtTest.QSignalSpy(canvas.scroll_request)

    wheel(canvas, delta=120, modifiers=ALT)

    assert canvas.brush_radius != radius
    assert len(zooms) == 0
    assert len(scrolls) == 0


def test_alt_wheel_edits_selected_rectangle_only(canvas):
    shape = make_rectangle()
    canvas.mode = Canvas.EDIT
    canvas.enable_wheel_rectangle_editing = True
    canvas.auto_highlight_shape = False
    canvas.shapes = [shape]
    canvas.selected_shapes = [shape]
    width = shape.bounding_rect().width()
    zooms = QtTest.QSignalSpy(canvas.zoom_request)
    moved = QtTest.QSignalSpy(canvas.shape_moved)

    image_point = QtCore.QPointF(100, 75)
    widget_point = (
        image_point * canvas.scale + canvas.offset_to_center()
    )
    wheel(
        canvas,
        delta=120,
        modifiers=ALT,
        point=(widget_point.x(), widget_point.y()),
    )

    assert len(zooms) == 0
    assert len(moved) == 1
    assert shape.bounding_rect().width() > width


def test_alt_shift_wheel_adjusts_compare_split(canvas):
    canvas.compare_pixmap = QtGui.QPixmap(20, 20)
    zooms = QtTest.QSignalSpy(canvas.zoom_request)
    changed = QtTest.QSignalSpy(canvas.split_position_changed)

    wheel(canvas, delta=120, modifiers=ALT | SHIFT)

    assert len(zooms) == 0
    assert len(changed) == 1
    assert canvas.split_position == pytest.approx(0.52)


def test_unmatched_modifiers_and_empty_delta_do_nothing(canvas):
    zooms = QtTest.QSignalSpy(canvas.zoom_request)
    scrolls = QtTest.QSignalSpy(canvas.scroll_request)

    wheel(canvas, modifiers=CTRL | SHIFT)
    assert len(zooms) == 0
    assert len(scrolls) == 0

    empty = QtGui.QWheelEvent(
        QtCore.QPointF(100, 100),
        QtCore.QPointF(100, 100),
        QtCore.QPoint(),
        QtCore.QPoint(),
        Qt.MouseButton.NoButton,
        NO_MOD,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    canvas.wheelEvent(empty)
    assert len(zooms) == 0
    assert len(scrolls) == 0


def test_navigation_does_not_create_geometry_backups(canvas):
    before = len(canvas.shapes_backups)

    wheel(canvas, modifiers=CTRL)
    wheel(canvas, modifiers=SHIFT)
    canvas.wheel_navigation_mode = "traditional"
    wheel(canvas, delta=120)

    assert len(canvas.shapes_backups) == before


def test_no_image_wheel_event_is_harmless(app):
    widget = Canvas(parent=None)
    zooms = QtTest.QSignalSpy(widget.zoom_request)

    wheel(widget, delta=120)
    wheel(widget, delta=120, modifiers=CTRL)

    assert len(zooms) == 0
    assert widget.shapes == []
    widget.close()
    widget.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def test_interaction_in_progress_tracks_drawing_state(canvas):
    assert not canvas.interaction_in_progress()

    canvas.current = Shape(shape_type="rectangle")
    assert canvas.interaction_in_progress()

    canvas.current = None
    assert not canvas.interaction_in_progress()
