"""Tests for crosshair cursor tracking and isolated painting."""

from unittest.mock import MagicMock

import pytest
from PyQt6 import QtCore, QtGui

from anylabeling.views.labeling.widgets.canvas import Canvas


def _move_event(point: QtCore.QPointF) -> QtGui.QMouseEvent:
    """Build a mouse-move event at a canvas-local point."""
    return QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseMove,
        QtCore.QPointF(point),
        QtCore.QPointF(point),
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )


def _prepare_canvas(canvas: Canvas) -> None:
    """Load a pixmap whose image and widget coordinate spaces coincide."""
    pixmap = QtGui.QPixmap(100, 80)
    pixmap.fill(QtGui.QColor("#202020"))
    canvas.resize(pixmap.size())
    canvas.load_pixmap(pixmap)


def test_mouse_move_schedules_crosshair_update_on_empty_canvas(
    canvas: Canvas, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Crosshair movement must not depend on shape hover or drawing."""
    _prepare_canvas(canvas)
    update_calls = []
    monkeypatch.setattr(canvas, "update", lambda: update_calls.append(True))

    canvas.mouseMoveEvent(_move_event(QtCore.QPointF(20.0, 30.0)))

    assert canvas.prev_move_point == QtCore.QPointF(20.0, 30.0)
    assert canvas._crosshair_cursor_active is True
    assert update_calls == [True]


def test_mouse_move_updates_before_drawing_branch_returns(
    canvas: Canvas, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A create-mode early return must still schedule crosshair painting."""
    _prepare_canvas(canvas)
    canvas.mode = canvas.CREATE
    canvas.current = None
    update_calls = []
    monkeypatch.setattr(canvas, "update", lambda: update_calls.append(True))

    canvas.mouseMoveEvent(_move_event(QtCore.QPointF(40.0, 25.0)))

    assert canvas.prev_move_point == QtCore.QPointF(40.0, 25.0)
    assert canvas._crosshair_cursor_active is True
    assert update_calls == [True]


def test_crosshair_hides_outside_pixmap_without_repainting_again(
    canvas: Canvas, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Leaving the image repaints once; outside-to-outside motion does not."""
    _prepare_canvas(canvas)
    update_calls = []
    monkeypatch.setattr(canvas, "update", lambda: update_calls.append(True))
    canvas.mouseMoveEvent(_move_event(QtCore.QPointF(20.0, 30.0)))

    update_calls.clear()
    canvas.mouseMoveEvent(_move_event(QtCore.QPointF(-1.0, 30.0)))

    assert canvas._crosshair_cursor_active is False
    assert update_calls == [True]

    update_calls.clear()
    canvas.mouseMoveEvent(_move_event(QtCore.QPointF(-2.0, 31.0)))

    assert canvas.prev_move_point == QtCore.QPointF(-2.0, 31.0)
    assert update_calls == []


def test_hidden_crosshair_tracks_position_without_scheduling_update(
    canvas: Canvas, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hidden crosshair keeps cursor state ready for later re-enabling."""
    _prepare_canvas(canvas)
    canvas.cross_line_show = False
    update_calls = []
    monkeypatch.setattr(canvas, "update", lambda: update_calls.append(True))

    canvas.mouseMoveEvent(_move_event(QtCore.QPointF(15.0, 16.0)))

    assert canvas.prev_move_point == QtCore.QPointF(15.0, 16.0)
    assert canvas._crosshair_cursor_active is True
    assert update_calls == []


def test_leave_event_and_pixmap_load_clear_crosshair_cursor(
    canvas: Canvas, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Canvas lifecycle transitions must invalidate stale cursor guides."""
    _prepare_canvas(canvas)
    canvas._update_crosshair_cursor(QtCore.QPointF(10.0, 12.0))
    update_calls = []
    monkeypatch.setattr(canvas, "update", lambda: update_calls.append(True))
    monkeypatch.setattr(canvas, "store_moving_shape", lambda: None)
    monkeypatch.setattr(canvas, "un_highlight", lambda: None)
    monkeypatch.setattr(canvas, "restore_cursor", lambda: None)

    canvas.leaveEvent(None)

    assert canvas._crosshair_cursor_active is False
    assert update_calls == [True]

    canvas._update_crosshair_cursor(QtCore.QPointF(10.0, 12.0))
    replacement = QtGui.QPixmap(120, 90)
    replacement.fill(QtGui.QColor("#303030"))
    canvas.load_pixmap(replacement)

    assert canvas._crosshair_cursor_active is False


def test_draw_crosshair_draws_two_lines_and_restores_painter_state(
    canvas: Canvas,
) -> None:
    """Crosshair rendering must be complete and painter-state isolated."""
    _prepare_canvas(canvas)
    canvas.prev_move_point = QtCore.QPointF(30.0, 20.0)
    canvas._crosshair_cursor_active = True
    canvas.cross_line_width = 2.0
    canvas.cross_line_opacity = 0.4
    canvas.scale = 2.0
    painter = MagicMock()

    canvas._draw_crosshair(painter)

    painter.save.assert_called_once_with()
    painter.restore.assert_called_once_with()
    painter.setOpacity.assert_called_once_with(0.4)
    assert painter.setPen.call_args.args[0].width() == 1
    assert painter.drawLine.call_count == 2
    vertical = painter.drawLine.call_args_list[0].args
    horizontal = painter.drawLine.call_args_list[1].args
    assert vertical == (
        QtCore.QPointF(30.0, 0.0),
        QtCore.QPointF(30.0, 80.0),
    )
    assert horizontal == (
        QtCore.QPointF(0.0, 20.0),
        QtCore.QPointF(100.0, 20.0),
    )

    image = QtGui.QImage(
        100,
        80,
        QtGui.QImage.Format.Format_ARGB32_Premultiplied,
    )
    qt_painter = QtGui.QPainter(image)
    try:
        qt_painter.setOpacity(0.75)
        canvas._draw_crosshair(qt_painter)
        assert qt_painter.opacity() == pytest.approx(0.75)
    finally:
        qt_painter.end()


def test_draw_crosshair_skips_inactive_cursor(canvas: Canvas) -> None:
    """No guides are painted before the cursor enters the image."""
    _prepare_canvas(canvas)
    canvas._crosshair_cursor_active = False
    painter = MagicMock()

    canvas._draw_crosshair(painter)

    painter.save.assert_not_called()
    painter.drawLine.assert_not_called()
