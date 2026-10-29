"""Label visibility mode: labels only for selected shapes plus hover preview."""

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.views.labeling.label_widget import LabelingWidget
from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.canvas import Canvas


@pytest.fixture(scope="module")
def app() -> QtWidgets.QApplication:
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def canvas(app: QtWidgets.QApplication):
    widget = Canvas(parent=None)
    widget.pixmap = QtGui.QPixmap(240, 180)
    widget.pixmap.fill(QtGui.QColor("white"))
    widget.resize(240, 180)
    first = make_rectangle("cat", 20, 20, 90, 80)
    second = make_rectangle("dog", 120, 60, 200, 140)
    widget.load_shapes([first, second])
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


def render(canvas):
    image = QtGui.QImage(canvas.size(), QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor("black"))
    canvas.render(image)
    return image


def test_default_mode_shows_every_label(canvas):
    for shape in canvas.shapes:
        assert canvas.label_text_visible(shape)


def test_selected_only_hides_unselected_labels(canvas):
    first, second = canvas.shapes
    first.selected = True
    canvas.show_labels_only_selected = True

    assert canvas.label_text_visible(first)
    assert not canvas.label_text_visible(second)


def test_hover_previews_the_unselected_label(canvas):
    first, second = canvas.shapes
    first.selected = True
    canvas.show_labels_only_selected = True

    canvas.h_shape = second
    assert canvas.label_text_visible(second)
    assert canvas.label_text_visible(first)

    canvas.h_shape = None
    assert not canvas.label_text_visible(second)


def test_hover_preview_is_limited_to_the_hovered_shape(canvas):
    first, second = canvas.shapes
    canvas.show_labels_only_selected = True
    canvas.h_shape = second

    assert canvas.label_text_visible(second)
    assert not canvas.label_text_visible(first)


def test_selected_only_mode_changes_rendered_output(canvas):
    first, second = canvas.shapes
    first.selected = True
    canvas.selected_shapes = [first]

    shown = render(canvas)
    canvas.show_labels_only_selected = True
    hidden = render(canvas)

    assert shown != hidden


def test_action_switch_updates_canvas_and_config():
    from types import SimpleNamespace
    from unittest.mock import Mock

    host = SimpleNamespace(
        _config={},
        canvas=SimpleNamespace(
            show_labels_only_selected=False, update=Mock()
        ),
    )

    LabelingWidget.set_canvas_params(
        host, "show_labels_only_selected", True
    )

    assert host.canvas.show_labels_only_selected is True
    assert host._config["show_labels_only_selected"] is True
    host.canvas.update.assert_called_once()
