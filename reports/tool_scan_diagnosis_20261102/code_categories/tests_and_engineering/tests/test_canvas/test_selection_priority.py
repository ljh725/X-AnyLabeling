"""Native hit ordering with hidden, focused and locked objects."""

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.canvas import Canvas


@pytest.fixture(scope="module")
def app() -> QtWidgets.QApplication:
    """Create the Qt application for canvas tests."""
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def canvas(app: QtWidgets.QApplication):
    """Create an empty canvas with a valid in-memory image."""
    widget = Canvas(parent=None)
    widget.pixmap = QtGui.QPixmap(200, 200)
    widget.pixmap.fill(QtGui.QColor("white"))
    widget.resize(200, 200)
    yield widget
    widget.close()
    widget.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def make_rectangle(label, left, top, right, bottom):
    shape = Shape(label=label, shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(left, top),
        QtCore.QPointF(right, top),
        QtCore.QPointF(right, bottom),
        QtCore.QPointF(left, bottom),
    ]
    shape.close()
    return shape


def candidates(canvas, point):
    return canvas._shape_hit_candidates(QtCore.QPointF(*point))


def test_focus_hiding_removes_unselected_hits(canvas):
    big = make_rectangle("big", 0, 0, 180, 180)
    small = make_rectangle("small", 80, 80, 120, 120)
    canvas.load_shapes([big, small])
    small.selected = True
    canvas.selected_shapes = [small]

    assert candidates(canvas, (10, 10)) == [big]

    canvas.hide_backround = True
    canvas.set_hiding(True)

    assert candidates(canvas, (10, 10)) == []
    assert candidates(canvas, (100, 100)) == [small]


def test_visible_shape_stays_hittable_after_unhiding(canvas):
    big = make_rectangle("big", 0, 0, 180, 180)
    canvas.load_shapes([big])
    canvas.hide_backround = True
    canvas.set_hiding(True)
    canvas.set_hiding(False)

    assert candidates(canvas, (10, 10)) == [big]


def test_rectangle_edge_defers_to_topmost_shape(canvas):
    target = make_rectangle("target", 40, 40, 160, 160)
    cover = make_rectangle("cover", 30, 80, 60, 120)
    target.selected = True
    canvas.load_shapes([target, cover])
    canvas.selected_shapes = [target]
    canvas.set_rectangle_edge_enabled(True)

    assert candidates(canvas, (40, 100))[0] is cover
    assert canvas._rectangle_edge_hit(QtCore.QPointF(40, 100)) is None


def test_rectangle_edge_works_without_competing_shape(canvas):
    target = make_rectangle("target", 40, 40, 160, 160)
    target.selected = True
    canvas.load_shapes([target])
    canvas.selected_shapes = [target]
    canvas.set_rectangle_edge_enabled(True)

    assert canvas._rectangle_edge_hit(QtCore.QPointF(40, 100)) == (
        target,
        "left",
    )


def test_hidden_cover_does_not_block_edge_editing(canvas):
    target = make_rectangle("target", 40, 40, 160, 160)
    cover = make_rectangle("cover", 30, 80, 60, 120)
    target.selected = True
    canvas.load_shapes([target, cover])
    canvas.selected_shapes = [target]
    canvas.set_rectangle_edge_enabled(True)
    canvas.visible[cover] = False

    assert canvas._rectangle_edge_hit(QtCore.QPointF(40, 100)) == (
        target,
        "left",
    )


def test_locked_shape_can_still_be_selected_by_interior(canvas):
    locked = make_rectangle("locked", 20, 20, 180, 180)
    locked.locked = True
    canvas.load_shapes([locked])

    assert candidates(canvas, (100, 100)) == [locked]
