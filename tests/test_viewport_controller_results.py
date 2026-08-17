"""Qt facade tests for structured viewport capture and apply results."""

from PyQt6 import QtGui, QtWidgets

from anylabeling.views.labeling.widgets.canvas import Canvas
from anylabeling.views.labeling.widgets.viewport_controller import (
    ViewportController,
)
from anylabeling.views.labeling.widgets.viewport_state_machine import (
    ViewportState,
)
from anylabeling.views.labeling.widgets.zoom_widget import ZoomWidget


def _viewport_widgets(qapp):
    canvas = Canvas()
    canvas.load_pixmap(QtGui.QPixmap(800, 600))
    canvas.scale = 2.0
    canvas.adjustSize()
    scroll_area = QtWidgets.QScrollArea()
    scroll_area.resize(400, 300)
    scroll_area.setWidget(canvas)
    scroll_area.show()
    zoom_widget = ZoomWidget(200)
    qapp.processEvents()
    return canvas, scroll_area, zoom_widget


def test_capture_and_apply_return_complete_results(qapp):
    canvas, scroll_area, zoom_widget = _viewport_widgets(qapp)
    controller = ViewportController()

    captured = controller.capture_result(canvas, zoom_widget, 2)

    assert captured.success is True
    assert isinstance(captured.state, ViewportState)

    horizontal = scroll_area.horizontalScrollBar()
    vertical = scroll_area.verticalScrollBar()
    horizontal.setValue(horizontal.maximum())
    vertical.setValue(vertical.maximum())
    applied = controller.apply_result(captured.state, canvas, zoom_widget)

    assert applied.success is True
    assert zoom_widget.value() == captured.state.zoom_value


def test_capture_without_scroll_area_is_reported_as_failure(qapp):
    canvas = Canvas()
    canvas.load_pixmap(QtGui.QPixmap(100, 80))
    canvas.scale = 1.0
    zoom_widget = ZoomWidget(100)
    controller = ViewportController()

    result = controller.capture_result(canvas, zoom_widget, 0)

    assert result.success is False
    assert result.state is None
    assert result.reason == "invalid_canvas"


def test_capture_with_zero_scale_is_rejected(qapp):
    canvas, _scroll_area, zoom_widget = _viewport_widgets(qapp)
    canvas.scale = 0.0
    controller = ViewportController()

    result = controller.capture_result(canvas, zoom_widget, 2)

    assert result.success is False
    assert result.reason == "invalid_canvas"


def test_viewport_apply_survives_resize_and_clamps_cross_size_center(qapp):
    canvas, scroll_area, zoom_widget = _viewport_widgets(qapp)
    controller = ViewportController()
    state = ViewportState(2, 250, 100000.0, 100000.0)

    scroll_area.resize(600, 400)
    qapp.processEvents()
    result = controller.apply_result(state, canvas, zoom_widget)

    assert result.success is True
    assert (
        scroll_area.horizontalScrollBar().value()
        <= scroll_area.horizontalScrollBar().maximum()
    )
    assert (
        scroll_area.verticalScrollBar().value()
        <= scroll_area.verticalScrollBar().maximum()
    )


def test_apply_without_scroll_area_does_not_change_zoom(qapp):
    canvas = Canvas()
    canvas.load_pixmap(QtGui.QPixmap(100, 80))
    canvas.scale = 1.0
    zoom_widget = ZoomWidget(100)
    controller = ViewportController()
    state = ViewportState(2, 250, 10.0, 20.0)

    result = controller.apply_result(state, canvas, zoom_widget)

    assert result.success is False
    assert zoom_widget.value() == 100
