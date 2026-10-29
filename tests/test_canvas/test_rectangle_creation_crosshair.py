"""Contracts for the temporary two-point rectangle crosshair."""

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml
from PyQt6 import QtCore, QtGui, QtTest, QtWidgets

from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.canvas import Canvas


@pytest.fixture(scope="module")
def app() -> QtWidgets.QApplication:
    """Provide an offscreen Qt application."""
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def canvas(app: QtWidgets.QApplication) -> Iterator[Canvas]:
    """Prepare a blank canvas without user image or annotation files."""
    widget = Canvas(parent=None)
    widget.pixmap = QtGui.QPixmap(200, 200)
    widget.resize(200, 200)
    yield widget
    widget.close()
    widget.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def _drawing_rectangle(canvas: Canvas) -> None:
    """Enter two-point rectangle creation on the fixture canvas."""
    canvas.create_mode = "rectangle"
    canvas.set_editing(False)


def test_guide_only_during_rectangle_creation(canvas: Canvas) -> None:
    """Editing and non-rectangle drawing do not expose the guide."""
    canvas._update_crosshair_cursor(QtCore.QPointF(40, 60))
    assert not canvas._rectangle_creation_crosshair_enabled()
    _drawing_rectangle(canvas)
    canvas.create_mode = "polygon"
    canvas._update_crosshair_cursor(QtCore.QPointF(40, 60))
    assert not canvas._rectangle_creation_crosshair_enabled()
    canvas.create_mode = "rectangle"
    canvas._update_crosshair_cursor(QtCore.QPointF(40, 60))
    assert canvas._rectangle_creation_crosshair_enabled()


@pytest.mark.parametrize("enabled", [True, False])
def test_rectangle_completion_obeys_auto_edit_setting(
    canvas: Canvas, enabled: bool
) -> None:
    """Finishing a two-click rectangle switches only when enabled."""
    from anylabeling.views.labeling.settings.runtime_applier import (
        SettingsRuntimeApplier,
    )

    host = SimpleNamespace(
        canvas=canvas,
        _auto_switch_signal_connected=False,
        set_edit_mode=lambda: canvas.set_editing(True),
    )
    applier = SettingsRuntimeApplier(host)
    applier.set_auto_switch_to_edit_mode(enabled)
    canvas.show()
    _drawing_rectangle(canvas)
    QtTest.QTest.mouseClick(canvas, QtCore.Qt.MouseButton.LeftButton,
                            pos=QtCore.QPoint(30, 30))
    QtTest.QTest.mouseMove(canvas, QtCore.QPoint(120, 120))
    QtTest.QTest.mouseClick(canvas, QtCore.Qt.MouseButton.LeftButton,
                            pos=QtCore.QPoint(120, 120))
    assert len(canvas.shapes) == 1
    assert canvas.editing() is enabled


def test_guide_remains_visible_after_first_point(canvas: Canvas) -> None:
    """The guide remains visible while previewing the second point."""
    _drawing_rectangle(canvas)
    canvas.current = Shape(shape_type="rectangle")
    canvas.current.add_point(QtCore.QPointF(10, 10))
    canvas._update_crosshair_cursor(QtCore.QPointF(40, 60))
    painter = MagicMock()
    canvas._draw_rectangle_crosshair(painter)
    assert painter.drawLine.call_count == 2
    assert painter.restore.called


def test_guide_is_suppressed_by_pending_extreme_draft(
    canvas: Canvas,
) -> None:
    """A four-extreme draft owns the canvas and hides the guide."""
    _drawing_rectangle(canvas)
    canvas._update_crosshair_cursor(QtCore.QPointF(40, 60))
    assert canvas._rectangle_creation_crosshair_enabled()
    canvas.rectangle_creation = SimpleNamespace(draft=object())
    assert not canvas._rectangle_creation_crosshair_enabled()
    canvas.rectangle_creation = SimpleNamespace(draft=None)
    assert canvas._rectangle_creation_crosshair_enabled()


def test_crosshair_clears_on_exit_and_image_switch(canvas: Canvas) -> None:
    """Leaving, losing focus or switching image clears the pointer state."""
    _drawing_rectangle(canvas)
    canvas._update_crosshair_cursor(QtCore.QPointF(40, 60))
    canvas.leaveEvent(QtCore.QEvent(QtCore.QEvent.Type.Leave))
    assert not canvas._crosshair_cursor_active
    canvas._update_crosshair_cursor(QtCore.QPointF(40, 60))
    canvas.focusOutEvent(QtGui.QFocusEvent(QtCore.QEvent.Type.FocusOut))
    assert not canvas._crosshair_cursor_active
    canvas._update_crosshair_cursor(QtCore.QPointF(40, 60))
    canvas.load_pixmap(QtGui.QPixmap(200, 200))
    assert not canvas._crosshair_cursor_active
    canvas._update_crosshair_cursor(QtCore.QPointF(40, 60))
    canvas.cancel_drawing()
    assert not canvas._crosshair_cursor_active


def test_switch_and_outside_image_disable_guide(canvas: Canvas) -> None:
    """The drawing switch and image boundary control guide visibility."""
    _drawing_rectangle(canvas)
    canvas._update_crosshair_cursor(QtCore.QPointF(40, 60))
    assert canvas._rectangle_creation_crosshair_enabled()
    canvas.set_rectangle_creation_crosshair(False)
    assert not canvas._rectangle_creation_crosshair_enabled()
    canvas.set_rectangle_creation_crosshair(True)
    canvas._update_crosshair_cursor(QtCore.QPointF(-1, 60))
    assert not canvas._rectangle_creation_crosshair_enabled()
    canvas._update_crosshair_cursor(QtCore.QPointF(40, 60))
    assert canvas._rectangle_creation_crosshair_enabled()


def test_native_crosshair_yields_to_the_creation_guide(
    canvas: Canvas,
) -> None:
    """The two crosshairs never paint on top of each other."""
    _drawing_rectangle(canvas)
    canvas.set_cross_line(True, 2.0, "#00FF00", 0.5, show_when_drawing=True)
    canvas._update_crosshair_cursor(QtCore.QPointF(40, 60))
    assert canvas._rectangle_creation_crosshair_enabled()
    assert not canvas._native_crosshair_enabled()
    canvas.set_rectangle_creation_crosshair(False)
    assert canvas._native_crosshair_enabled()


def test_default_config_enables_guide_independently() -> None:
    """The new switch has its own default and ignores the legacy flag."""
    path = (
        Path(__file__).parents[2]
        / "anylabeling/configs/xanylabeling_config.yaml"
    )
    config = yaml.safe_load(path.read_text(encoding="utf8"))
    crosshair = config["canvas"]["crosshair"]
    assert crosshair["show_when_drawing"] is True
    assert crosshair["show"] is True
