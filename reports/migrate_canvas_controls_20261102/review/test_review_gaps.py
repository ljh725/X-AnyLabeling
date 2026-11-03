import runpy
import pytest
from PyQt6 import QtCore, QtWidgets

_source = runpy.run_path("tests/test_labeling/test_canvas_display_retention.py")
window = _source["window"]
image_path = _source["image_path"]

@pytest.mark.parametrize("parameter", ["brightness", "contrast"])
def test_keep_latest_pending_display_value(window, tmp_path, parameter):
    widget = window.labeling_widget.view
    panel = widget.canvas_adjustment
    first = image_path(tmp_path, "first.png")
    second = image_path(tmp_path, "second.png")
    assert widget.load_file(first)
    widget._on_inline_brightness_contrast(70, 70)
    panel.set_brightness_contrast(70, 70)
    getattr(panel, parameter + "_pin").click()
    getattr(panel, parameter + "_slider").setValue(90)
    assert panel._bc_update_timer.isActive()
    assert widget.load_file(second)
    actual = getattr(panel, parameter + "_slider").value()
    assert actual == 90, f"retained stale {parameter}: {actual}, expected latest slider value 90"


def test_traditional_fit_width_does_not_require_horizontal_scroll(window, tmp_path):
    widget = window.labeling_widget.view
    app = QtWidgets.QApplication.instance()
    path = image_path(tmp_path, "tall.png", size=(1000, 3000))
    assert widget.load_file(path)
    widget.apply_wheel_navigation_mode("traditional")
    app.processEvents()
    widget.set_fit_width(True)
    app.processEvents()
    area = widget._canvas_scroll_area
    horizontal = area.horizontalScrollBar()
    assert horizontal.maximum() == 0, f"fit-width overflows: horizontal range={horizontal.maximum()}, area={area.width()}, viewport={area.viewport().width()}, canvas={widget.canvas.width()}"


@pytest.mark.parametrize("size, zoom", [((1600,1200),150), ((64,64),100), ((1000,3000),80)])
def test_mode_roundtrip_after_layout_events(window, tmp_path, size, zoom):
    widget = window.labeling_widget.view
    app = QtWidgets.QApplication.instance()
    path = image_path(tmp_path, "view.png", size=size)
    assert widget.load_file(path)
    widget.set_zoom(zoom)
    app.processEvents()
    before=widget._current_shared_view()
    widget.apply_wheel_navigation_mode("traditional")
    app.processEvents()
    widget.apply_wheel_navigation_mode("direct")
    app.processEvents()
    after=widget._current_shared_view()
    assert after.center_x == pytest.approx(before.center_x,abs=2)
    assert after.center_y == pytest.approx(before.center_y,abs=2)


def test_four_extreme_draft_defers_mode_switch(window, tmp_path):
    widget = window.labeling_widget.view
    path = image_path(tmp_path, "extreme.png", size=(1600,1200))
    assert widget.load_file(path)
    creation = widget.canvas.rectangle_creation
    creation.start_extreme()
    assert creation.draft.accept(100, 100)
    creation.refresh()
    assert widget.canvas.current is None
    widget.apply_wheel_navigation_mode("traditional")
    assert widget.canvas.wheel_navigation_mode == "direct", "navigation mode remapped while a four-extreme draft is active"
    assert widget._pending_wheel_navigation_mode == "traditional"
    creation.cancel()
