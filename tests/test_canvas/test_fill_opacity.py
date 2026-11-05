"""Fill-only opacity: the canvas slider scales annotation fill alpha.

The outline, vertices, labels and editing hints must keep their own styles,
and the visualization export keeps its independent fill rules.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.resources import resources  # noqa: F401
from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.canvas import Canvas


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def canvas(app):
    widget = Canvas(parent=None)
    widget.pixmap = QtGui.QPixmap(100, 100)
    widget.pixmap.fill(QtGui.QColor("black"))
    widget.resize(100, 100)
    widget.scale = 1.0
    widget.show_masks = True
    widget.show_texts = False
    widget.show_labels = False
    widget.show_scores = False
    widget.show_attributes = False
    widget.show_linking = False
    widget.show_groups = False
    widget.show_degrees = False
    widget.cross_line_show = False
    widget.h_shape = None
    widget.current = None
    yield widget
    widget.close()
    widget.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def make_rectangle(left=20, top=20, right=80, bottom=80):
    shape = Shape(label="object", shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(left, top),
        QtCore.QPointF(right, top),
        QtCore.QPointF(right, bottom),
        QtCore.QPointF(left, bottom),
    ]
    shape.close()
    shape.line_width = 1.0
    return shape


def render_canvas(canvas):
    image = QtGui.QImage(canvas.size(), QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor("black"))
    canvas.render(image)
    return image


def render_shape(shape, opacity):
    image = QtGui.QImage(100, 100, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    shape.paint(painter, opacity)
    painter.end()
    return image


def test_shape_fill_alpha_is_scaled_without_touching_outlines():
    shape = make_rectangle()
    shape.fill = True
    shape.line_color = QtGui.QColor(0, 0, 255, 255)
    shape.fill_color = QtGui.QColor(255, 0, 0, 200)

    alphas = []
    for opacity in (1.0, 0.5, 0.0, 1.0):
        image = render_shape(shape, opacity)
        alphas.append(image.pixelColor(50, 50).alpha())
        border = image.pixelColor(20, 50)
        assert border.alpha() > 0

    assert alphas == pytest.approx((200, 100, 0, 200), abs=2)
    # The shared fill colour must not be mutated by the multiplier.
    assert shape.fill_color.alpha() == 200


def test_mask_fill_is_scaled_once_and_border_stays_readable(canvas):
    shape = make_rectangle()
    shape.line_color = QtGui.QColor(255, 0, 0, 255)
    shape.selected = False
    canvas.shapes = [shape]
    canvas.selected_shapes = []
    canvas.mask_opacity = 200

    reds = []
    for opacity in (1.0, 0.5, 0.0):
        canvas.shape_opacity = opacity
        image = render_canvas(canvas)
        reds.append(image.pixelColor(50, 50).red())
        border = image.pixelColor(20, 50)
        assert border.red() > 100

    assert reds[0] == pytest.approx(200, abs=2)
    assert reds[1] == pytest.approx(100, abs=2)
    assert reds[2] == pytest.approx(0, abs=2)


def test_selected_preview_fill_uses_the_same_multiplier(canvas):
    shape = make_rectangle()
    shape.selected = True
    shape.line_color = QtGui.QColor(255, 0, 0, 255)
    shape.select_fill_color = QtGui.QColor(0, 255, 0, 155)
    canvas.show_masks = False
    canvas._fill_drawing = True
    canvas.shapes = [shape]
    canvas.selected_shapes = [shape]

    canvas.shape_opacity = 1.0
    opaque = render_canvas(canvas)
    canvas.shape_opacity = 0.0
    transparent = render_canvas(canvas)

    assert opaque.pixelColor(50, 50).green() == pytest.approx(155, abs=2)
    assert transparent.pixelColor(50, 50).green() == 0
    assert transparent.pixelColor(20, 50).alpha() == 255


def test_visualization_export_keeps_its_own_fill_rules(canvas):
    shape = make_rectangle()
    shape.line_color = QtGui.QColor(0, 255, 0, 255)
    canvas.shapes = [shape]
    canvas.shape_opacity = 0.0

    exported = canvas.render_visualization(
        canvas.pixmap,
        [shape],
        show_labels=False,
        show_scores=False,
        show_groups=False,
        show_texts=False,
        show_masks=False,
    )

    assert exported.pixelColor(20, 50).green() > 100
    assert exported.pixelColor(20, 50).alpha() == 255


@pytest.mark.parametrize("kind", ["polygon", "rotation", "circle"])
def test_mixed_shape_fill_roundtrip_preserves_outline_and_geometry(kind):
    shape = make_rectangle()
    shape.shape_type = kind
    if kind == "circle":
        shape.points = [QtCore.QPointF(30, 50), QtCore.QPointF(70, 50)]
    shape.fill = True
    shape.line_color = QtGui.QColor(0, 0, 255, 255)
    shape.fill_color = QtGui.QColor(255, 0, 0, 200)
    before = shape.to_dict()
    images = [render_shape(shape, opacity) for opacity in (1, 0.5, 0, 1)]
    # The centre is safely inside all these geometries.
    assert [im.pixelColor(50, 50).alpha() for im in images] == pytest.approx(
        [200, 100, 0, 200], abs=2
    )
    assert images[0] == images[3]
    assert shape.to_dict() == before
    # Blue outline pixels remain even when the fill is fully hidden.
    assert any(
        images[2].pixelColor(x, y).blue() > 200
        and images[2].pixelColor(x, y).alpha() > 100
        for x in range(100)
        for y in range(100)
    )


@pytest.mark.parametrize(
    "kind, points",
    [
        ("point", [(50, 50)]),
        ("line", [(20, 20), (80, 80)]),
        ("linestrip", [(20, 20), (50, 80), (80, 20)]),
    ],
)
def test_nonfill_markers_do_not_disappear_at_zero_opacity(kind, points):
    shape = Shape(label="object", shape_type=kind)
    shape.points = [QtCore.QPointF(x, y) for x, y in points]
    shape.line_color = QtGui.QColor(0, 0, 255, 255)
    assert render_shape(shape, 0) == render_shape(shape, 1)


def test_live_brush_mask_scales_once_and_keeps_its_outline(canvas):
    import numpy as np

    shape = make_rectangle()
    shape.shape_type = "polygon"
    shape.line_color = QtGui.QColor(255, 0, 0, 255)
    shape.mask = np.zeros((100, 100), dtype=np.uint8)
    shape.mask[20:81, 20:81] = 255
    shape._brush_using_mask = True
    canvas.shapes = [shape]
    canvas.show_masks = False
    canvas.mask_opacity = 200
    values = []
    for opacity in (1, 0.5, 0, 1):
        canvas.shape_opacity = opacity
        image = render_canvas(canvas)
        values.append(image.pixelColor(50, 50).red())
        assert image.pixelColor(20, 50).red() > 100
    assert values == pytest.approx([200, 100, 0, 200], abs=2)


def test_actual_rectangle_creation_fill_keeps_crosshair_at_zero(canvas):
    canvas.show_masks = False
    canvas._fill_drawing = True
    canvas.create_mode = "rectangle"
    canvas.current = Shape(label="object", shape_type="rectangle")
    canvas.current.add_point(QtCore.QPointF(20, 20))
    canvas.line.points = [QtCore.QPointF(20, 20), QtCore.QPointF(80, 80)]
    canvas.line.shape_type = "rectangle"
    canvas.line.fill = True
    canvas.line.fill_color = QtGui.QColor(255, 0, 0, 200)
    canvas.line.line_color = QtGui.QColor(0, 0, 255, 255)
    canvas.shape_opacity = 1
    full = render_canvas(canvas)
    canvas.shape_opacity = 0
    empty = render_canvas(canvas)
    assert full.pixelColor(50, 50).red() > empty.pixelColor(50, 50).red()
    assert empty.pixelColor(20, 50).blue() > 100
