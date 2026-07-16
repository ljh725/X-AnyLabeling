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


def test_unselected_rectangle_edge_is_available_as_preselection(canvas):
    """An unselected rectangle exposes a non-mutating edge preview."""
    shape = _rectangle()
    canvas.shapes = [shape]
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)

    candidate = canvas._rect_edge_hit_candidate(QtCore.QPointF(10.0, 60.0))

    assert candidate is not None
    assert candidate.shape is shape
    assert candidate.edge_name == "left"
    assert canvas.selected_shapes == []


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


def test_multiple_selection_exposes_only_a_preselection_candidate(canvas):
    """A multi-selection may preview an edge but cannot edit it directly."""
    first = _rectangle()
    second = _rectangle(x=150.0)
    canvas.shapes = [first, second]
    canvas.selected_shapes = [first, second]
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)

    candidate = canvas._rect_edge_hit_candidate(QtCore.QPointF(10.0, 60.0))

    assert candidate is not None
    assert candidate.shape is first
    assert candidate.edge_name == "left"


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


def test_enabling_edge_editing_enters_edit_mode_without_disabling_it():
    """Enabling the capability exits create mode and keeps it enabled."""
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
    assert mode_switches == [True]


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


def _release_event(point: QtCore.QPointF) -> QtGui.QMouseEvent:
    """Build a left-button mouse-release event at ``point``."""
    return QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonRelease,
        QtCore.QPointF(point),
        QtCore.QPointF(point),
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )


def _sync_canvas_selection(canvas: canvas_module.Canvas) -> None:
    """Make a bare Canvas apply its emitted selection synchronously."""

    def apply_selection(shapes: list[Shape]) -> None:
        """Mirror LabelingWidget.shape_selection_changed for unit tests."""
        for old_shape in canvas.selected_shapes:
            old_shape.selected = False
        canvas.selected_shapes = list(shapes)
        for new_shape in canvas.selected_shapes:
            new_shape.selected = True

    canvas.selection_changed.connect(apply_selection)


def _clear_override_cursor():
    """Pop every entry from the global override-cursor stack."""
    while QtWidgets.QApplication.overrideCursor() is not None:
        QtWidgets.QApplication.restoreOverrideCursor()


def test_hovering_an_unselected_edge_does_not_change_selection(canvas):
    """Edge preselection is visual only, even with auto-highlight enabled."""
    shape = _rectangle()
    canvas.shapes = [shape]
    canvas.h_shape_is_hovered = True
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)
    canvas.pixmap = None
    emitted = []
    canvas.selection_changed.connect(emitted.append)
    _clear_override_cursor()

    canvas.mouseMoveEvent(_move_event(QtCore.QPointF(10.0, 60.0)))

    assert canvas.rect_edge_hover_edge is not None
    assert canvas.rect_edge_hover_edge.shape is shape
    assert canvas.selected_shapes == []
    assert emitted == []
    assert canvas.current_cursor() == canvas_module.CURSOR_POINT
    _clear_override_cursor()


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


def test_clicking_a_preselected_edge_only_selects_the_rectangle(canvas):
    """A click confirms the rectangle without changing geometry or undo."""
    shape = _rectangle()
    original_points = _point_tuples(shape)
    canvas.shapes = [shape]
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)
    canvas.pixmap = None
    _sync_canvas_selection(canvas)
    moved = []
    canvas.shape_moved.connect(lambda: moved.append(True))

    canvas.mousePressEvent(_press_event(QtCore.QPointF(10.0, 60.0)))

    assert canvas.rect_edge_pending_edge is not None
    assert canvas.rect_edge_dragging is False
    assert canvas.selected_shapes == []

    canvas.mouseReleaseEvent(_release_event(QtCore.QPointF(10.0, 60.0)))

    assert canvas.selected_shapes == [shape]
    assert _point_tuples(shape) == original_points
    assert canvas.rect_edge_pending_edge is None
    assert canvas.rect_edge_dragging is False
    assert canvas.shapes_backups == []
    assert moved == []


def test_preselected_edge_drag_starts_only_after_screen_threshold(canvas):
    """An unselected edge upgrades to formal selection after a clear drag."""
    shape = _rectangle()
    original_points = _point_tuples(shape)
    canvas.shapes = [shape]
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)
    canvas.pixmap = None
    _sync_canvas_selection(canvas)
    moved = []
    canvas.shape_moved.connect(lambda: moved.append(True))

    canvas.mousePressEvent(_press_event(QtCore.QPointF(10.0, 60.0)))
    canvas.mouseMoveEvent(
        _move_event(
            QtCore.QPointF(12.0, 60.0),
            buttons=QtCore.Qt.MouseButton.LeftButton,
        )
    )

    assert canvas.rect_edge_dragging is False
    assert canvas.selected_shapes == []
    assert _point_tuples(shape) == original_points

    canvas.mouseMoveEvent(
        _move_event(
            QtCore.QPointF(18.0, 60.0),
            buttons=QtCore.Qt.MouseButton.LeftButton,
        )
    )

    assert canvas.rect_edge_dragging is True
    assert canvas.selected_shapes == [shape]
    assert _point_tuples(shape) != original_points

    canvas.mouseReleaseEvent(_release_event(QtCore.QPointF(18.0, 60.0)))

    assert canvas.rect_edge_dragging is False
    assert canvas.rect_edge_pending_edge is None
    assert moved == [True]


def test_other_selection_requires_click_before_edge_drag(canvas):
    """A different selection prevents one-gesture target switching."""
    target = _rectangle()
    other = _rectangle(x=150.0)
    original_points = _point_tuples(target)
    canvas.shapes = [target, other]
    canvas.selected_shapes = [other]
    other.selected = True
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)
    canvas.pixmap = None
    _sync_canvas_selection(canvas)

    canvas.mousePressEvent(_press_event(QtCore.QPointF(10.0, 60.0)))
    canvas.mouseMoveEvent(
        _move_event(
            QtCore.QPointF(30.0, 60.0),
            buttons=QtCore.Qt.MouseButton.LeftButton,
        )
    )

    assert canvas.rect_edge_dragging is False
    assert canvas.selected_shapes == [other]
    assert _point_tuples(target) == original_points

    canvas.mouseReleaseEvent(_release_event(QtCore.QPointF(30.0, 60.0)))

    assert canvas.selected_shapes == [target]
    assert _point_tuples(target) == original_points
    assert canvas.rect_edge_hover_edge is None
    assert canvas.current_cursor() == canvas_module.CURSOR_DEFAULT


def test_close_vertical_edges_keep_the_preselected_target_on_press(canvas):
    """Press jitter must not switch between nearby vertical rectangle edges."""
    target = _rectangle(width=90.0)
    neighbor = _rectangle(x=104.0, width=90.0)
    neighbor_points = _point_tuples(neighbor)
    canvas.shapes = [target, neighbor]
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)
    canvas.pixmap = None
    _sync_canvas_selection(canvas)
    _clear_override_cursor()

    canvas.mouseMoveEvent(_move_event(QtCore.QPointF(101.0, 60.0)))

    assert canvas.rect_edge_hover_edge is not None
    assert canvas.rect_edge_hover_edge.shape is target
    assert canvas.rect_edge_hover_edge.edge_name == "right"

    canvas.mousePressEvent(_press_event(QtCore.QPointF(103.0, 60.0)))

    assert canvas.rect_edge_pending_edge is not None
    assert canvas.rect_edge_pending_edge.shape is target
    assert canvas.rect_edge_pending_edge.edge_name == "right"

    canvas.mouseReleaseEvent(_release_event(QtCore.QPointF(103.0, 60.0)))
    canvas.mousePressEvent(_press_event(QtCore.QPointF(103.0, 60.0)))

    assert canvas.selected_shapes == [target]
    assert canvas.rect_edge_active_edge is not None
    assert canvas.rect_edge_active_edge.shape is target
    assert canvas.rect_edge_active_edge.edge_name == "right"

    canvas.mouseMoveEvent(
        _move_event(
            QtCore.QPointF(90.0, 60.0),
            buttons=QtCore.Qt.MouseButton.LeftButton,
        )
    )
    canvas.mouseReleaseEvent(_release_event(QtCore.QPointF(90.0, 60.0)))

    assert max(point.x() for point in target.points) == 90.0
    assert _point_tuples(neighbor) == neighbor_points
    _clear_override_cursor()


def test_close_horizontal_edges_keep_the_preselected_target_on_press(canvas):
    """Press jitter must not switch between nearby horizontal edges."""
    target = _rectangle(height=90.0)
    neighbor = _rectangle(y=104.0, height=90.0)
    neighbor_points = _point_tuples(neighbor)
    canvas.shapes = [target, neighbor]
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)
    canvas.pixmap = None
    _sync_canvas_selection(canvas)
    _clear_override_cursor()

    canvas.mouseMoveEvent(_move_event(QtCore.QPointF(60.0, 101.0)))

    assert canvas.rect_edge_hover_edge is not None
    assert canvas.rect_edge_hover_edge.shape is target
    assert canvas.rect_edge_hover_edge.edge_name == "bottom"

    canvas.mousePressEvent(_press_event(QtCore.QPointF(60.0, 103.0)))

    assert canvas.rect_edge_pending_edge is not None
    assert canvas.rect_edge_pending_edge.shape is target
    assert canvas.rect_edge_pending_edge.edge_name == "bottom"

    canvas.mouseReleaseEvent(_release_event(QtCore.QPointF(60.0, 103.0)))
    canvas.mousePressEvent(_press_event(QtCore.QPointF(60.0, 103.0)))

    assert canvas.selected_shapes == [target]
    assert canvas.rect_edge_active_edge is not None
    assert canvas.rect_edge_active_edge.shape is target
    assert canvas.rect_edge_active_edge.edge_name == "bottom"

    canvas.mouseMoveEvent(
        _move_event(
            QtCore.QPointF(60.0, 90.0),
            buttons=QtCore.Qt.MouseButton.LeftButton,
        )
    )
    canvas.mouseReleaseEvent(_release_event(QtCore.QPointF(60.0, 90.0)))

    assert max(point.y() for point in target.points) == 90.0
    assert _point_tuples(neighbor) == neighbor_points
    _clear_override_cursor()


def test_narrow_rectangle_keeps_the_preselected_opposite_edge(canvas):
    """One narrow rectangle must preserve the exact preselected side."""
    shape = _rectangle(width=6.0)
    canvas.shapes = [shape]
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)
    canvas.pixmap = None
    _sync_canvas_selection(canvas)
    _clear_override_cursor()

    canvas.mouseMoveEvent(_move_event(QtCore.QPointF(15.5, 60.0)))

    assert canvas.rect_edge_hover_edge is not None
    assert canvas.rect_edge_hover_edge.edge_name == "right"

    canvas.mousePressEvent(_press_event(QtCore.QPointF(13.0, 60.0)))
    canvas.mouseReleaseEvent(_release_event(QtCore.QPointF(13.0, 60.0)))
    canvas.mousePressEvent(_press_event(QtCore.QPointF(13.0, 60.0)))

    assert canvas.selected_shapes == [shape]
    assert canvas.rect_edge_active_edge is not None
    assert canvas.rect_edge_active_edge.edge_name == "right"

    canvas.mouseMoveEvent(
        _move_event(
            QtCore.QPointF(25.0, 60.0),
            buttons=QtCore.Qt.MouseButton.LeftButton,
        )
    )
    canvas.mouseReleaseEvent(_release_event(QtCore.QPointF(25.0, 60.0)))

    assert min(point.x() for point in shape.points) == 10.0
    assert max(point.x() for point in shape.points) == 25.0
    _clear_override_cursor()


def test_rectangle_corner_keeps_vertex_priority_over_preselected_edge(canvas):
    """A rectangle corner remains a vertex target rather than an edge."""
    shape = _rectangle()
    canvas.shapes = [shape]
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)

    candidate = canvas._rect_edge_hit_candidate(QtCore.QPointF(10.0, 10.0))

    assert candidate is None


def test_rectangle_corner_beats_an_overlapping_other_rectangle_edge(canvas):
    """A corner handle outranks another rectangle's overlapping edge."""
    corner_shape = _rectangle()
    crossing_shape = _rectangle(y=-90.0, height=200.0)
    canvas.shapes = [corner_shape, crossing_shape]
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)

    candidate = canvas._rect_edge_hit_candidate(QtCore.QPointF(10.0, 10.0))

    assert candidate is None


def test_non_rectangle_vertex_beats_an_overlapping_rectangle_edge(canvas):
    """A polygon vertex outranks an overlapping rectangle edge."""
    rectangle = _rectangle()
    polygon = Shape(label="hand", shape_type="polygon")
    polygon.points = [
        QtCore.QPointF(10.0, 60.0),
        QtCore.QPointF(0.0, 50.0),
        QtCore.QPointF(0.0, 70.0),
    ]
    canvas.shapes = [rectangle, polygon]
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)

    candidate = canvas._rect_edge_hit_candidate(QtCore.QPointF(10.0, 60.0))

    assert candidate is None
