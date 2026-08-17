"""Narrow LabelingWidget adapter tests for the viewport load lifecycle."""

from types import MethodType, SimpleNamespace

from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.views.labeling.label_widget import LabelingWidget
from anylabeling.views.labeling.widgets.canvas import Canvas
from anylabeling.views.labeling.widgets.viewport_controller import (
    ViewportController,
)
from anylabeling.views.labeling.widgets.viewport_state_machine import (
    ViewportSource,
)
from anylabeling.views.labeling.widgets.zoom_widget import ZoomWidget


class _Action:
    """Minimal QAction stand-in for the UI synchronization adapter."""

    def __init__(self):
        self.checked = False

    def setChecked(self, value):
        self.checked = value


def _build_widget(qapp):
    canvas = Canvas()
    pixmap = QtGui.QPixmap(800, 600)
    canvas.load_pixmap(pixmap)
    canvas.scale = 1.0
    canvas.adjustSize()
    scroll_area = QtWidgets.QScrollArea()
    scroll_area.resize(400, 300)
    scroll_area.setWidget(canvas)
    scroll_area.show()
    zoom_widget = ZoomWidget(100)
    qapp.processEvents()

    widget = SimpleNamespace(
        viewport_controller=ViewportController(),
        canvas=canvas,
        zoom_widget=zoom_widget,
        image=QtGui.QImage(800, 600, QtGui.QImage.Format.Format_RGB32),
        filename=None,
        _config={"keep_prev_viewport": False, "keep_prev_scale": False},
        FIT_WINDOW=0,
        FIT_WIDTH=1,
        MANUAL_ZOOM=2,
        zoom_mode=0,
        actions=SimpleNamespace(fit_window=_Action(), fit_width=_Action()),
        scroll_bars={
            QtCore.Qt.Orientation.Horizontal: scroll_area.horizontalScrollBar(),
            QtCore.Qt.Orientation.Vertical: scroll_area.verticalScrollBar(),
        },
    )
    widget.adjust_scale = lambda initial=False: (
        zoom_widget.setValue(100 if initial else zoom_widget.value())
    )
    widget.paint_canvas = lambda: (
        setattr(canvas, "scale", zoom_widget.value() / 100.0),
        canvas.adjustSize(),
        canvas.update(),
    )
    widget._apply_default_image_view = MethodType(
        LabelingWidget._apply_default_image_view, widget
    )
    widget._sync_viewport_ui = MethodType(
        LabelingWidget._sync_viewport_ui, widget
    )
    return widget, scroll_area


def _load(widget, filename):
    widget.filename = filename
    return LabelingWidget._apply_viewport_load_plan(widget, filename)


def test_load_plan_supports_inherit_reverse_and_exact_restore(qapp, tmp_path):
    widget, scroll_area = _build_widget(qapp)
    first = str(tmp_path / "first.png")
    second = str(tmp_path / "second.png")

    assert _load(widget, first) is True
    widget.zoom_widget.setValue(250)
    widget.canvas.scale = 2.5
    widget.canvas.adjustSize()
    scroll_area.horizontalScrollBar().setValue(
        scroll_area.horizontalScrollBar().maximum()
    )
    widget.viewport_controller.on_file_leaving(
        first, widget.canvas, widget.zoom_widget, widget.MANUAL_ZOOM
    )

    widget._config["keep_prev_viewport"] = True
    plan = widget.viewport_controller.resolve_load_plan(
        second, keep_prev_viewport=True, keep_prev_scale=False
    )
    assert plan.source is ViewportSource.PREVIOUS_VIEWPORT
    assert _load(widget, second) is True

    widget.viewport_controller.on_file_leaving(
        second, widget.canvas, widget.zoom_widget, widget.MANUAL_ZOOM
    )
    exact_plan = widget.viewport_controller.resolve_load_plan(
        first, keep_prev_viewport=False, keep_prev_scale=False
    )
    assert exact_plan.source is ViewportSource.EXACT
    assert _load(widget, first) is True
    assert widget.zoom_widget.value() == 250


def test_exact_restore_survives_window_resize_and_a_toggle(qapp, tmp_path):
    widget, scroll_area = _build_widget(qapp)
    filename = str(tmp_path / "image.png")

    assert _load(widget, filename) is True
    widget.zoom_widget.setValue(300)
    widget.canvas.scale = 3.0
    widget.canvas.adjustSize()
    widget.viewport_controller.on_file_leaving(
        filename, widget.canvas, widget.zoom_widget, widget.MANUAL_ZOOM
    )

    widget._config["keep_prev_viewport"] = False
    scroll_area.resize(700, 500)
    qapp.processEvents()
    plan = widget.viewport_controller.resolve_load_plan(
        filename, keep_prev_viewport=False, keep_prev_scale=False
    )
    assert plan.source is ViewportSource.EXACT
    assert _load(widget, filename) is True
    assert widget.zoom_widget.value() == 300
