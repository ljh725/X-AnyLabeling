"""Marquee selection synchronizes the real label list and bulk actions."""

import pytest
from PyQt6 import QtCore, QtTest, QtWidgets

from tests.test_canvas.test_marquee_selection import (
    CTRL,
    NONE,
    PRESS,
    MOVE,
    RELEASE,
    drag,
    mouse,
    rectangle,
)
from tests.test_labeling.test_canvas_display_retention import (
    image_path,
    window,
)


@pytest.mark.parametrize("start", [(10, 10), (30, 30)])
def test_marquee_selection_drives_label_list_and_bulk_delete(
    window, tmp_path, start
):
    view = window.labeling_widget.view
    view._config["auto_save"] = False
    assert view.load_file(image_path(tmp_path, "marquee.png", size=(200, 200)))
    view.set_zoom(100)
    first = rectangle(20, 20, 60, 60)
    second = rectangle(70, 70, 90, 90)
    outside = rectangle(140, 140, 180, 180)
    view.load_shapes([first, second, outside], update_last_label=False)
    view.toggle_draw_mode(edit=True)
    canvas = view.canvas
    canvas.select_shapes([first] if start == (30, 30) else [])
    history = len(canvas.shapes_backups)
    view.dirty = False

    drag(canvas, start, (100, 100))

    assert canvas.selected_shapes == [first, second]
    assert [item.shape() for item in view.label_list.selected_items()] == [
        first,
        second,
    ]
    assert view.actions.delete.isEnabled()
    assert view.actions.edit.isEnabled()
    assert not view.dirty
    assert len(canvas.shapes_backups) == history

    view.delete_selected_shape()
    assert canvas.shapes == [outside]
    assert len(view.label_list) == 1
    assert view.dirty


@pytest.mark.parametrize("native", [False, True])
def test_repeated_marquees_with_event_loop(window, tmp_path, native):
    view = window.labeling_widget.view
    view._config["auto_save"] = False
    assert view.load_file(image_path(tmp_path, "repeat.png", size=(400, 300)))
    view.set_zoom(100)
    shapes = [rectangle(40 + i * 80, 50, 90 + i * 80, 120) for i in range(3)]
    view.load_shapes(shapes, update_last_label=False)
    view.toggle_draw_mode(edit=True)
    canvas = view.canvas
    app = QtWidgets.QApplication.instance()
    canvas.setFocus()
    app.processEvents()
    edited = QtTest.QSignalSpy(canvas.edit_label_requested)

    def send(kind, xy, modifiers=CTRL, held=True):
        if native:
            point = (
                (QtCore.QPointF(*xy) + canvas.offset_to_center())
                * canvas.scale
            ).toPoint()
            if kind == PRESS:
                QtTest.QTest.mousePress(
                    canvas, QtCore.Qt.MouseButton.LeftButton, modifiers, point
                )
            elif kind == RELEASE:
                QtTest.QTest.mouseRelease(
                    canvas, QtCore.Qt.MouseButton.LeftButton, modifiers, point
                )
            elif kind == QtCore.QEvent.Type.MouseButtonDblClick:
                QtTest.QTest.mouseDClick(
                    canvas, QtCore.Qt.MouseButton.LeftButton, modifiers, point
                )
            else:
                mouse(canvas, kind, xy, modifiers, held=held)
        else:
            mouse(canvas, kind, xy, modifiers, held=held)
        app.processEvents()

    for attempt in range(6):
        # Clear the previous selection as an operator would between marquee drags.
        send(MOVE, (340, 200), NONE, held=False)
        send(PRESS, (340, 200), NONE)
        send(RELEASE, (340, 200), NONE)
        assert canvas.selected_shapes == [], attempt
        start, end = (
            ((20, 30), (290, 160)) if attempt == 0 else ((60, 80), (220, 100))
        )
        if attempt % 2:
            start, end = end, start
        send(MOVE, start, NONE, held=False)
        send(
            QtCore.QEvent.Type.MouseButtonDblClick if attempt % 2 else PRESS,
            start,
        )
        send(MOVE, end)
        assert canvas._marquee_dragging, attempt
        if attempt % 2:
            send(MOVE, end, NONE, held=False)
        send(RELEASE, end)
        assert canvas.selected_shapes == shapes, attempt
        assert [
            item.shape() for item in view.label_list.selected_items()
        ] == shapes
    assert len(edited) == 0
