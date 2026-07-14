"""Tests for rectangle-edge selection and mode-switch semantics."""

import os
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

from anylabeling.views.labeling.label_widget import (  # noqa: E402
    LabelingWidget,
)
from anylabeling.views.labeling.rect_edge_alignment import (  # noqa: E402
    apply_edge_coord,
    iter_edges,
)
from anylabeling.views.labeling.shape import Shape  # noqa: E402
from anylabeling.views.labeling.widgets import (  # noqa: E402
    canvas as canvas_module,
)


def _rectangle(x=10.0, y=10.0, width=100.0, height=100.0):
    """Return a canonical four-point rectangle."""
    shape = Shape(label="person", shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(x, y),
        QtCore.QPointF(x + width, y),
        QtCore.QPointF(x + width, y + height),
        QtCore.QPointF(x, y + height),
    ]
    return shape


def _point_tuples(shape):
    """Return shape points as plain tuples for stable comparisons."""
    return [(point.x(), point.y()) for point in shape.points]


def test_edge_hit_does_not_capture_an_unselected_rectangle(canvas):
    """An unselected rectangle edge remains available to shape selection."""
    shape = _rectangle()
    canvas.shapes = [shape]
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)

    candidate = canvas._rect_edge_hit_candidate(QtCore.QPointF(10.0, 60.0))

    assert candidate is None


def test_edge_hit_targets_the_single_selected_rectangle(canvas):
    """A selected rectangle exposes its edge as a local control handle."""
    shape = _rectangle()
    canvas.shapes = [shape]
    canvas.selected_shapes = [shape]
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)

    candidate = canvas._rect_edge_hit_candidate(QtCore.QPointF(10.0, 60.0))

    assert candidate is not None
    assert candidate.shape is shape
    assert candidate.edge_name == "left"


def test_edge_hit_is_ambiguous_for_multiple_selected_rectangles(canvas):
    """Multiple selected rectangles do not expose one implicit edge target."""
    first = _rectangle()
    second = _rectangle(x=150.0)
    canvas.shapes = [first, second]
    canvas.selected_shapes = [first, second]
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)

    candidate = canvas._rect_edge_hit_candidate(QtCore.QPointF(10.0, 60.0))

    assert candidate is None


def test_create_mode_keeps_edge_capability_enabled_but_dormant(canvas):
    """Create mode suppresses edge hits without changing the user setting."""
    shape = _rectangle()
    canvas.shapes = [shape]
    canvas.selected_shapes = [shape]
    canvas.set_rect_edge_align_enabled(True)

    canvas.set_editing(False)

    assert canvas.rect_edge_align_enabled is True
    assert canvas._rect_edge_hit_candidate(QtCore.QPointF(10.0, 60.0)) is None


def test_entering_create_mode_cancels_an_active_edge_drag(canvas):
    """A mode switch restores live edge geometry before clearing drag state."""
    shape = _rectangle()
    original_points = _point_tuples(shape)
    active_edge = next(
        edge for edge in iter_edges(shape) if edge.edge_name == "left"
    )
    canvas.shapes = [shape]
    canvas.selected_shapes = [shape]
    canvas.set_rect_edge_align_enabled(True)
    canvas.rect_edge_active_edge = active_edge
    canvas.rect_edge_drag_start_points = list(shape.points)
    canvas.rect_edge_dragging = True
    apply_edge_coord(shape, "left", 30.0)
    assert _point_tuples(shape) != original_points

    canvas.set_editing(False)

    assert _point_tuples(shape) == original_points
    assert canvas.rect_edge_dragging is False
    assert canvas.rect_edge_active_edge is None
    assert canvas.rect_edge_drag_start_points is None
    assert canvas.rect_edge_align_enabled is True


def test_disabling_edge_editing_cancels_an_active_drag(canvas):
    """Manual disable restores geometry instead of dropping live drag state."""
    shape = _rectangle()
    original_points = _point_tuples(shape)
    active_edge = next(
        edge for edge in iter_edges(shape) if edge.edge_name == "right"
    )
    canvas.shapes = [shape]
    canvas.selected_shapes = [shape]
    canvas.set_rect_edge_align_enabled(True)
    canvas.rect_edge_active_edge = active_edge
    canvas.rect_edge_drag_start_points = list(shape.points)
    canvas.rect_edge_dragging = True
    apply_edge_coord(shape, "right", 140.0)
    assert _point_tuples(shape) != original_points

    canvas.set_rect_edge_align_enabled(False)

    assert _point_tuples(shape) == original_points
    assert canvas.rect_edge_dragging is False
    assert canvas.rect_edge_align_enabled is False


def test_mouse_press_revalidates_a_stale_hover_edge(canvas):
    """A cached edge cannot start a drag after its rectangle is deselected."""
    shape = _rectangle()
    stale_edge = next(
        edge for edge in iter_edges(shape) if edge.edge_name == "left"
    )
    canvas.rect_edge_align_enabled = True
    canvas.rect_edge_hover_edge = stale_edge
    canvas.selected_shapes = []
    canvas.shapes = []
    event = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonPress,
        QtCore.QPointF(10.0, 60.0),
        QtCore.QPointF(10.0, 60.0),
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )

    canvas.mousePressEvent(event)

    assert canvas.rect_edge_hover_edge is None
    assert canvas.rect_edge_active_edge is None
    assert canvas.rect_edge_dragging is False


def test_enabling_edge_editing_does_not_exit_create_mode():
    """The preference can be enabled while drawing without changing mode."""
    calls = []
    mode_switches = []
    canvas = types.SimpleNamespace(
        drawing=lambda: True,
        set_rect_edge_align_enabled=calls.append,
    )
    widget = types.SimpleNamespace(
        canvas=canvas,
        set_edit_mode=lambda: mode_switches.append(True),
        status=lambda message: None,
        tr=lambda message: message,
    )

    LabelingWidget.toggle_rect_edge_align(widget, True)

    assert calls == [True]
    assert mode_switches == []


def _move_event(point, buttons=QtCore.Qt.MouseButton.NoButton):
    """Build a minimal mouse-move event at ``point``."""
    return QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseMove,
        QtCore.QPointF(point),
        QtCore.QPointF(point),
        buttons,
        buttons,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )


def _press_event(point):
    """Build a left-button mouse-press event at ``point``."""
    return QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonPress,
        QtCore.QPointF(point),
        QtCore.QPointF(point),
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )


def _clear_override_cursor():
    """Pop every entry from the global override-cursor stack."""
    while QtWidgets.QApplication.overrideCursor() is not None:
        QtWidgets.QApplication.restoreOverrideCursor()


def test_hovering_a_selected_rect_edge_shows_pointing_hand_cursor(canvas):
    """Hovering a selected rectangle edge switches the cursor to pointing hand."""
    shape = _rectangle()
    canvas.shapes = [shape]
    canvas.selected_shapes = [shape]
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)
    # Neutralize ``offset_to_center`` so widget coordinates map 1:1 onto
    # image coordinates (the default 640x480 pixmap would otherwise shift
    # the transformed position away from the edge).
    canvas.pixmap = None
    _clear_override_cursor()

    canvas.mouseMoveEvent(_move_event(QtCore.QPointF(10.0, 60.0)))

    assert canvas.rect_edge_hover_edge is not None
    assert canvas.current_cursor() == canvas_module.CURSOR_POINT
    _clear_override_cursor()


def test_dragging_a_rect_edge_shows_closed_hand_cursor(canvas):
    """Pressing/dragging a hovered edge switches the cursor to closed hand."""
    shape = _rectangle()
    canvas.shapes = [shape]
    canvas.selected_shapes = [shape]
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)
    canvas.pixmap = None
    _clear_override_cursor()

    canvas.mousePressEvent(_press_event(QtCore.QPointF(10.0, 60.0)))
    assert canvas.rect_edge_dragging is True
    assert canvas.current_cursor() == canvas_module.CURSOR_MOVE

    canvas.mouseMoveEvent(
        _move_event(
            QtCore.QPointF(12.0, 60.0),
            buttons=QtCore.Qt.MouseButton.LeftButton,
        )
    )
    assert canvas.current_cursor() == canvas_module.CURSOR_MOVE
    _clear_override_cursor()
