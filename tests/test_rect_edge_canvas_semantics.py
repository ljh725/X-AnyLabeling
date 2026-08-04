"""Tests for rectangle-edge selection and mode-switch semantics."""

import os
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

from anylabeling.views.labeling.label_widget import (  # noqa: E402
    LabelingWidget,
)
from anylabeling.views.labeling.rect_edge_alignment import (  # noqa: E402
    apply_edge_coord,
    geometry_from_shape,
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


def _activate_edge_drag(canvas, shape, edge_name):
    """Put ``canvas`` into an active drag for one rectangle edge."""
    active_edge = next(
        edge for edge in iter_edges(shape) if edge.edge_name == edge_name
    )
    canvas.shapes = [shape]
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)
    canvas.rect_edge_active_edge = active_edge
    canvas.rect_edge_drag_start_points = list(shape.points)
    canvas.rect_edge_dragging = True


def _select(canvas, *shapes):
    """Mark shapes as formally selected on the canvas."""
    canvas.selected_shapes = list(shapes)
    for shape in canvas.shapes:
        shape.selected = shape in shapes


def _enable_edge_hit(canvas, shapes, selected, scale=1.0):
    """Configure common rectangle-edge hit-test state."""
    canvas.shapes = list(shapes)
    _select(canvas, *selected)
    canvas.scale = scale
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)
    canvas.pixmap = None


def _use_identity_pixmap(canvas, width=200, height=200):
    """Give mouse-event tests a pixmap with no transform offset."""
    canvas.pixmap = QtGui.QPixmap(width, height)
    canvas.resize(width, height)


def test_unselected_rectangle_edge_is_not_available_as_preselection(canvas):
    """An unselected rectangle does not expose direct edge editing."""
    shape = _rectangle()
    _enable_edge_hit(canvas, [shape], [])

    candidate = canvas._rect_edge_hit_candidate(QtCore.QPointF(10.0, 60.0))

    assert candidate is None
    assert canvas.selected_shapes == []


def test_only_unique_selected_rectangle_exposes_edge_hit(canvas):
    """Only the single selected rectangle can expose a mouse edge."""
    shape = _rectangle()
    _enable_edge_hit(canvas, [shape], [shape])

    candidate = canvas._rect_edge_hit_candidate(QtCore.QPointF(10.0, 60.0))

    assert candidate is not None
    assert candidate.shape is shape
    assert candidate.edge_name == "left"


def test_multiple_selection_blocks_edge_preselection(canvas):
    """Multi-selection does not provide mouse edge editing."""
    first = _rectangle()
    second = _rectangle(x=150.0)
    _enable_edge_hit(canvas, [first, second], [first, second])

    candidate = canvas._rect_edge_hit_candidate(QtCore.QPointF(10.0, 60.0))

    assert candidate is None


def test_create_mode_keeps_edge_capability_enabled_but_dormant(canvas):
    """Create mode suppresses edge hits without changing the user setting."""
    shape = _rectangle()
    canvas.shapes = [shape]
    _select(canvas, shape)
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
    _select(canvas, shape)
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
    _select(canvas, shape)
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


def _move_event(
    point,
    buttons=QtCore.Qt.MouseButton.NoButton,
    modifiers=QtCore.Qt.KeyboardModifier.NoModifier,
):
    """Build a minimal mouse-move event at ``point``."""
    return QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseMove,
        QtCore.QPointF(point),
        QtCore.QPointF(point),
        buttons,
        buttons,
        modifiers,
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


def _clear_override_cursor():
    """Pop every entry from the global override-cursor stack."""
    while QtWidgets.QApplication.overrideCursor() is not None:
        QtWidgets.QApplication.restoreOverrideCursor()


def test_hovering_an_unselected_edge_does_not_create_edge_feedback(canvas):
    """Unselected rectangles fall through to the normal hover path."""
    shape = _rectangle()
    canvas.shapes = [shape]
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)
    _use_identity_pixmap(canvas)
    emitted = []
    canvas.selection_changed.connect(emitted.append)
    _clear_override_cursor()

    canvas.mouseMoveEvent(_move_event(QtCore.QPointF(10.0, 60.0)))

    assert canvas.rect_edge_hover_edge is None
    assert canvas.selected_shapes == []
    assert emitted == []
    _clear_override_cursor()


def test_hovering_a_selected_rect_edge_shows_pointing_hand_cursor(canvas):
    """Hovering a selected vertical edge uses the horizontal resize cursor."""
    shape = _rectangle()
    _enable_edge_hit(canvas, [shape], [shape])
    _clear_override_cursor()

    canvas.mouseMoveEvent(_move_event(QtCore.QPointF(10.0, 60.0)))

    assert canvas.rect_edge_hover_edge is not None
    assert canvas.current_cursor() == canvas_module.CURSOR_SIZE_HOR
    _clear_override_cursor()


def test_hovering_a_selected_horizontal_edge_shows_vertical_resize(canvas):
    """Hovering a selected horizontal edge uses the vertical resize cursor."""
    shape = _rectangle()
    _enable_edge_hit(canvas, [shape], [shape])
    _clear_override_cursor()

    canvas.mouseMoveEvent(_move_event(QtCore.QPointF(60.0, 10.0)))

    assert canvas.rect_edge_hover_edge is not None
    assert canvas.rect_edge_hover_edge.edge_name == "top"
    assert canvas.current_cursor() == canvas_module.CURSOR_SIZE_VER
    _clear_override_cursor()


def test_dragging_a_rect_edge_keeps_resize_cursor(canvas):
    """Crossing the drag threshold activates only the pressed edge."""
    shape = _rectangle()
    _enable_edge_hit(canvas, [shape], [shape])
    _clear_override_cursor()

    canvas.mousePressEvent(_press_event(QtCore.QPointF(10.0, 60.0)))
    assert canvas.rect_edge_pending_edge is not None
    assert canvas.rect_edge_dragging is False
    assert canvas.selected_shapes == [shape]

    canvas.mouseMoveEvent(
        _move_event(
            QtCore.QPointF(20.0, 60.0),
            buttons=QtCore.Qt.MouseButton.LeftButton,
        )
    )
    assert canvas.rect_edge_dragging is True
    assert canvas.rect_edge_active_edge is not None
    assert canvas.rect_edge_active_edge.shape is shape
    assert canvas.selected_shapes == [shape]
    assert shape.selected is True
    assert canvas.current_cursor() == canvas_module.CURSOR_SIZE_HOR
    _clear_override_cursor()


def test_clicking_a_selected_edge_keeps_the_rectangle_selected(canvas):
    """A plain edge click keeps selection and does not create geometry undo."""
    shape = _rectangle()
    original_points = _point_tuples(shape)
    _enable_edge_hit(canvas, [shape], [shape])
    moved = []
    canvas.shape_moved.connect(lambda: moved.append(True))

    canvas.mousePressEvent(_press_event(QtCore.QPointF(10.0, 60.0)))

    assert canvas.rect_edge_pending_edge is not None
    assert canvas.rect_edge_dragging is False
    assert canvas.selected_shapes == [shape]

    canvas.mouseReleaseEvent(_release_event(QtCore.QPointF(10.0, 60.0)))

    assert canvas.selected_shapes == [shape]
    assert shape.selected is True
    assert _point_tuples(shape) == original_points
    assert canvas.rect_edge_pending_edge is None
    assert canvas.rect_edge_dragging is False
    assert canvas.shapes_backups == []
    assert moved == []


def test_selected_edge_drag_starts_on_first_nonzero_screen_move(canvas):
    """An edge starts immediately on its first non-zero move."""
    shape = _rectangle()
    original_points = _point_tuples(shape)
    _enable_edge_hit(canvas, [shape], [shape])
    moved = []
    canvas.shape_moved.connect(lambda: moved.append(True))

    canvas.mousePressEvent(_press_event(QtCore.QPointF(10.0, 60.0)))
    canvas.mouseMoveEvent(
        _move_event(
            QtCore.QPointF(11.0, 60.0),
            buttons=QtCore.Qt.MouseButton.LeftButton,
        )
    )

    assert canvas.rect_edge_dragging is True
    assert canvas.selected_shapes == [shape]
    assert shape.selected is True
    assert _point_tuples(shape) != original_points
    assert geometry_from_shape(shape).x_min == 11.0

    canvas.mouseReleaseEvent(_release_event(QtCore.QPointF(11.0, 60.0)))

    assert canvas.rect_edge_dragging is False
    assert canvas.rect_edge_pending_edge is None
    assert moved == [True]


def test_pending_edge_same_position_move_does_not_start_drag(canvas):
    """A same-position move remains a no-op pending gesture."""
    shape = _rectangle()
    original_points = _point_tuples(shape)
    _enable_edge_hit(canvas, [shape], [shape])
    moved = []
    canvas.shape_moved.connect(lambda: moved.append(True))

    canvas.mousePressEvent(_press_event(QtCore.QPointF(10.0, 60.0)))
    canvas.mouseMoveEvent(
        _move_event(
            QtCore.QPointF(10.0, 60.0),
            buttons=QtCore.Qt.MouseButton.LeftButton,
        )
    )

    assert canvas.rect_edge_dragging is False
    assert canvas.rect_edge_pending_edge is not None
    assert _point_tuples(shape) == original_points

    canvas.mouseReleaseEvent(_release_event(QtCore.QPointF(10.0, 60.0)))

    assert canvas.shapes_backups == []
    assert moved == []


def test_fast_edge_drag_updates_on_its_first_move_event(canvas):
    """A fast drag does not lose its initial movement to a fixed threshold."""
    shape = _rectangle()
    _enable_edge_hit(canvas, [shape], [shape])

    canvas.mousePressEvent(_press_event(QtCore.QPointF(10.0, 60.0)))
    canvas.mouseMoveEvent(
        _move_event(
            QtCore.QPointF(42.0, 60.0),
            buttons=QtCore.Qt.MouseButton.LeftButton,
        )
    )

    geometry = geometry_from_shape(shape)
    assert canvas.rect_edge_dragging is True
    assert geometry is not None
    assert geometry.x_min == 42.0


@pytest.mark.parametrize("scale", [0.5, 1.0, 2.0, 4.0])
def test_edge_drag_has_no_fixed_start_delay_at_each_zoom(canvas, scale):
    """A one-screen-pixel move starts edge dragging at every zoom level."""
    shape = _rectangle()
    canvas.shapes = [shape]
    _select(canvas, shape)
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)
    canvas.scale = scale
    canvas.pixmap = QtGui.QPixmap(200, 200)
    canvas.resize(int(200 * scale), int(200 * scale))
    press = QtCore.QPointF(10.0 * scale, 60.0 * scale)
    move = QtCore.QPointF(press.x() + 1.0, press.y())

    canvas.mousePressEvent(_press_event(press))
    canvas.mouseMoveEvent(
        _move_event(move, buttons=QtCore.Qt.MouseButton.LeftButton)
    )

    geometry = geometry_from_shape(shape)
    assert canvas.rect_edge_dragging is True
    assert geometry is not None
    assert geometry.x_min == pytest.approx(10.0 + 1.0 / scale)


@pytest.mark.parametrize("scale", [0.5, 1.0, 2.0, 4.0])
def test_corner_drag_has_no_fixed_start_delay_at_each_zoom(canvas, scale):
    """A one-screen-pixel move updates the native corner drag at each zoom."""
    shape = _rectangle()
    canvas.shapes = [shape]
    _select(canvas, shape)
    canvas.set_editing(True)
    canvas.scale = scale
    canvas.pixmap = QtGui.QPixmap(200, 200)
    canvas.resize(int(200 * scale), int(200 * scale))
    canvas.h_hape = shape
    canvas.h_vertex = 0

    canvas.mouseMoveEvent(
        _move_event(
            QtCore.QPointF(10.0 * scale + 1.0, 10.0 * scale + 1.0),
            buttons=QtCore.Qt.MouseButton.LeftButton,
        )
    )

    assert shape.points[0].x() == pytest.approx(10.0 + 1.0 / scale)
    assert shape.points[0].y() == pytest.approx(10.0 + 1.0 / scale)


def test_pending_edge_drag_precision_scales_first_move_delta(canvas):
    """Precision mode scales motion without changing edge hit semantics."""
    shape = _rectangle()
    _enable_edge_hit(canvas, [shape], [shape])
    canvas.set_precision_mode("fixed")
    canvas.set_precision_factor(4)
    canvas.precision_mode_locked = True

    assert canvas._rect_edge_hit_candidate(QtCore.QPointF(10.0, 60.0))
    canvas.mousePressEvent(_press_event(QtCore.QPointF(10.0, 60.0)))
    canvas.mouseMoveEvent(
        _move_event(
            QtCore.QPointF(18.0, 60.0),
            buttons=QtCore.Qt.MouseButton.LeftButton,
        )
    )

    geometry = geometry_from_shape(shape)
    assert canvas.rect_edge_dragging is True
    assert geometry is not None
    assert geometry.x_min == 12.0


def test_precision_mode_does_not_change_small_rectangle_edge_hit_zones(canvas):
    """Precision mode leaves epsilon and the small-box outer-side rule intact."""
    shape = _rectangle(width=30.0, height=14.0)
    _enable_edge_hit(canvas, [shape], [shape])
    canvas.set_precision_mode("fixed")
    canvas.set_precision_factor(4)
    canvas.precision_mode_locked = True

    assert canvas._rect_edge_hit_candidate(QtCore.QPointF(25.0, 12.0)) is None
    candidate = canvas._rect_edge_hit_candidate(QtCore.QPointF(25.0, 8.0))

    assert candidate is not None
    assert candidate.edge_name == "top"


def test_other_selection_falls_back_to_normal_object_selection(canvas):
    """Unselected rectangle edges do not bypass existing selection logic."""
    target = _rectangle()
    other = _rectangle(x=150.0)
    original_points = _point_tuples(target)
    canvas.shapes = [target, other]
    _select(canvas, other)
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)
    _use_identity_pixmap(canvas)

    canvas.mousePressEvent(_press_event(QtCore.QPointF(10.0, 60.0)))
    assert canvas.rect_edge_pending_edge is None
    assert canvas.selected_shapes == [target]
    assert target.selected is True
    assert other.selected is False

    canvas.mouseMoveEvent(
        _move_event(
            QtCore.QPointF(30.0, 60.0),
            buttons=QtCore.Qt.MouseButton.LeftButton,
        )
    )

    assert canvas.rect_edge_dragging is False
    assert canvas.rect_edge_active_edge is None
    assert canvas.selected_shapes == [target]
    assert _point_tuples(target) != original_points

    canvas.mouseReleaseEvent(_release_event(QtCore.QPointF(30.0, 60.0)))

    assert canvas.selected_shapes == [target]
    assert target.selected is True
    assert canvas.rect_edge_active_edge is None
    assert canvas.rect_edge_hover_edge is None


def test_close_vertical_edges_keep_the_preselected_target_on_press(canvas):
    """Press jitter must not switch between nearby vertical rectangle edges."""
    target = _rectangle(width=90.0)
    neighbor = _rectangle(x=104.0, width=90.0)
    neighbor_points = _point_tuples(neighbor)
    _enable_edge_hit(canvas, [target, neighbor], [target])
    _clear_override_cursor()

    canvas.mouseMoveEvent(_move_event(QtCore.QPointF(101.0, 60.0)))

    assert canvas.rect_edge_hover_edge is not None
    assert canvas.rect_edge_hover_edge.shape is target
    assert canvas.rect_edge_hover_edge.edge_name == "right"

    canvas.mousePressEvent(_press_event(QtCore.QPointF(103.0, 60.0)))

    assert canvas.rect_edge_pending_edge is not None
    assert canvas.rect_edge_pending_edge.shape is target
    assert canvas.rect_edge_pending_edge.edge_name == "right"

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
    _enable_edge_hit(canvas, [target, neighbor], [target])
    _clear_override_cursor()

    canvas.mouseMoveEvent(_move_event(QtCore.QPointF(60.0, 101.0)))

    assert canvas.rect_edge_hover_edge is not None
    assert canvas.rect_edge_hover_edge.shape is target
    assert canvas.rect_edge_hover_edge.edge_name == "bottom"

    canvas.mousePressEvent(_press_event(QtCore.QPointF(60.0, 103.0)))

    assert canvas.rect_edge_pending_edge is not None
    assert canvas.rect_edge_pending_edge.shape is target
    assert canvas.rect_edge_pending_edge.edge_name == "bottom"

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
    """A small rectangle can still drag a side from outside that side."""
    shape = _rectangle(width=6.0)
    _enable_edge_hit(canvas, [shape], [shape])
    _clear_override_cursor()

    canvas.mouseMoveEvent(_move_event(QtCore.QPointF(16.5, 60.0)))

    assert canvas.rect_edge_hover_edge is not None
    assert canvas.rect_edge_hover_edge.edge_name == "right"

    canvas.mousePressEvent(_press_event(QtCore.QPointF(16.5, 60.0)))
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
    _enable_edge_hit(canvas, [shape], [shape])

    candidate = canvas._rect_edge_hit_candidate(QtCore.QPointF(10.0, 10.0))

    assert candidate is None


def test_rectangle_corner_beats_an_overlapping_other_rectangle_edge(canvas):
    """A corner handle outranks another rectangle's overlapping edge."""
    corner_shape = _rectangle()
    crossing_shape = _rectangle(y=-90.0, height=200.0)
    _enable_edge_hit(canvas, [corner_shape, crossing_shape], [corner_shape])

    candidate = canvas._rect_edge_hit_candidate(QtCore.QPointF(10.0, 10.0))

    assert candidate is None


def test_non_rectangle_vertex_beats_an_overlapping_rectangle_edge(canvas):
    """Other shape vertices do not steal the selected rectangle's edge."""
    rectangle = _rectangle()
    polygon = Shape(label="hand", shape_type="polygon")
    polygon.points = [
        QtCore.QPointF(10.0, 60.0),
        QtCore.QPointF(0.0, 50.0),
        QtCore.QPointF(0.0, 70.0),
    ]
    _enable_edge_hit(canvas, [rectangle, polygon], [rectangle])

    candidate = canvas._rect_edge_hit_candidate(QtCore.QPointF(10.0, 60.0))

    assert candidate is not None
    assert candidate.shape is rectangle
    assert candidate.edge_name == "left"


def test_unselected_overlapping_rectangles_keep_small_target_priority(canvas):
    """Normal object selection still prefers the smaller overlapping target."""
    big = _rectangle(width=120.0, height=120.0)
    small = _rectangle(x=40.0, y=40.0, width=20.0, height=20.0)
    canvas.shapes = [big, small]
    canvas.set_rect_edge_align_enabled(True)
    canvas.set_editing(True)
    canvas.pixmap = None

    candidates = canvas._shape_hit_candidates(QtCore.QPointF(50.0, 50.0))

    assert candidates[:2] == [small, big]


def test_selected_rectangle_edge_uses_finite_segment(canvas):
    """A point near an infinite extension does not hit a finite edge segment."""
    shape = _rectangle()
    _enable_edge_hit(canvas, [shape], [shape])

    candidate = canvas._rect_edge_hit_candidate(QtCore.QPointF(10.0, 120.0))

    assert candidate is None


@pytest.mark.parametrize(
    ("point", "edge_name"),
    [
        (QtCore.QPointF(5.0, 60.0), "left"),
        (QtCore.QPointF(15.0, 60.0), "left"),
        (QtCore.QPointF(115.0, 60.0), "right"),
        (QtCore.QPointF(105.0, 60.0), "right"),
        (QtCore.QPointF(60.0, 5.0), "top"),
        (QtCore.QPointF(60.0, 15.0), "top"),
        (QtCore.QPointF(60.0, 115.0), "bottom"),
        (QtCore.QPointF(60.0, 105.0), "bottom"),
    ],
)
def test_normal_rectangle_edges_hit_inside_and_outside(
    canvas, point, edge_name
):
    """A normal rectangle allows both inner and outer edge hot zones."""
    shape = _rectangle(width=100.0, height=100.0)
    _enable_edge_hit(canvas, [shape], [shape])

    candidate = canvas._rect_edge_hit_candidate(point)

    assert candidate is not None
    assert candidate.edge_name == edge_name


@pytest.mark.parametrize(
    ("width", "height", "point", "edge_name"),
    [
        (14.0, 40.0, QtCore.QPointF(9.0, 30.0), "left"),
        (14.0, 40.0, QtCore.QPointF(25.0, 30.0), "right"),
        (40.0, 14.0, QtCore.QPointF(30.0, 9.0), "top"),
        (40.0, 14.0, QtCore.QPointF(30.0, 25.0), "bottom"),
    ],
)
def test_small_rectangle_edges_hit_only_from_outside(
    canvas, width, height, point, edge_name
):
    """Small rectangle edge hot zones are pushed outside the box."""
    shape = _rectangle(width=width, height=height)
    _enable_edge_hit(canvas, [shape], [shape])

    candidate = canvas._rect_edge_hit_candidate(point)

    assert candidate is not None
    assert candidate.edge_name == edge_name


@pytest.mark.parametrize(
    "point",
    [
        QtCore.QPointF(11.0, 17.0),
        QtCore.QPointF(39.0, 17.0),
        QtCore.QPointF(25.0, 11.0),
        QtCore.QPointF(25.0, 23.0),
    ],
)
def test_small_rectangle_inside_does_not_hit_edges(canvas, point):
    """Inside a small rectangle stays available for normal movement."""
    shape = _rectangle(width=30.0, height=14.0)
    _enable_edge_hit(canvas, [shape], [shape])

    candidate = canvas._rect_edge_hit_candidate(point)

    assert candidate is None


@pytest.mark.parametrize(
    ("scale", "point", "edge_name"),
    [
        (0.5, QtCore.QPointF(28.0, 20.0), None),
        (1.0, QtCore.QPointF(28.0, 20.0), None),
        (2.0, QtCore.QPointF(28.0, 20.0), "right"),
        (4.0, QtCore.QPointF(28.0, 20.0), "right"),
    ],
)
def test_zoom_changes_small_rectangle_strategy(
    canvas, scale, point, edge_name
):
    """The 3x-epsilon size decision is based on screen-space dimensions."""
    shape = _rectangle(width=20.0, height=20.0)
    _enable_edge_hit(canvas, [shape], [shape], scale=scale)

    candidate = canvas._rect_edge_hit_candidate(point)

    if edge_name is None:
        assert candidate is None
    else:
        assert candidate is not None
        assert candidate.edge_name == edge_name


def test_exact_three_epsilon_boundary_uses_normal_strategy(canvas):
    """A rectangle exactly at 3x epsilon is not classified as small."""
    shape = _rectangle(width=30.0, height=30.0)
    _enable_edge_hit(canvas, [shape], [shape])

    candidate = canvas._rect_edge_hit_candidate(QtCore.QPointF(15.0, 25.0))

    assert candidate is not None
    assert candidate.edge_name == "left"


@pytest.mark.parametrize(
    ("edge_name", "target", "coord_attr", "expected"),
    [
        ("left", QtCore.QPointF(-20.0, 40.0), "x_min", 0.0),
        ("right", QtCore.QPointF(120.0, 40.0), "x_max", 99.0),
        ("top", QtCore.QPointF(40.0, -20.0), "y_min", 0.0),
        ("bottom", QtCore.QPointF(40.0, 120.0), "y_max", 79.0),
    ],
)
def test_active_edge_drag_is_clamped_to_image_bounds(
    canvas, edge_name, target, coord_attr, expected
):
    """Direct edge dragging follows the canvas image-boundary contract."""
    shape = _rectangle(width=60.0, height=50.0)
    canvas.pixmap = QtGui.QPixmap(100, 80)
    _activate_edge_drag(canvas, shape, edge_name)

    canvas._rect_edge_drag_update(target)

    geometry = geometry_from_shape(shape)
    assert geometry is not None
    assert getattr(geometry, coord_attr) == expected


def test_repeated_clamped_edge_drag_is_noop(canvas, monkeypatch):
    """Dragging farther past an already-clamped edge emits no redundant work."""
    shape = _rectangle(width=60.0, height=50.0)
    canvas.pixmap = QtGui.QPixmap(100, 80)
    _activate_edge_drag(canvas, shape, "right")
    canvas._rect_edge_drag_update(QtCore.QPointF(120.0, 40.0))
    changed = []
    shown = []
    updates = []
    canvas.shape_changed.connect(changed.append)
    canvas.show_shape.connect(lambda *args: shown.append(args))
    monkeypatch.setattr(canvas, "update", lambda: updates.append(True))

    canvas._rect_edge_drag_update(QtCore.QPointF(130.0, 40.0))

    assert changed == []
    assert shown == []
    assert updates == []


def test_focus_loss_rolls_back_an_active_edge_drag(canvas):
    """Losing focus restores the geometry captured at drag start."""
    shape = _rectangle()
    original_points = _point_tuples(shape)
    _activate_edge_drag(canvas, shape, "left")
    apply_edge_coord(shape, "left", 30.0)

    canvas.focusOutEvent(QtGui.QFocusEvent(QtCore.QEvent.Type.FocusOut))

    assert _point_tuples(shape) == original_points
    assert canvas.rect_edge_dragging is False
    assert canvas.rect_edge_active_edge is None


@pytest.mark.parametrize(
    "event_type",
    [
        QtCore.QEvent.Type.UngrabMouse,
        QtCore.QEvent.Type.WindowDeactivate,
    ],
)
def test_interruption_event_rolls_back_an_active_edge_drag(canvas, event_type):
    """Mouse-grab loss and window deactivation cancel live geometry."""
    shape = _rectangle()
    original_points = _point_tuples(shape)
    _activate_edge_drag(canvas, shape, "right")
    apply_edge_coord(shape, "right", 140.0)

    canvas.event(QtCore.QEvent(event_type))

    assert _point_tuples(shape) == original_points
    assert canvas.rect_edge_dragging is False


def test_active_drag_without_left_button_is_cancelled(canvas):
    """A stale active state cannot mutate geometry without a held button."""
    shape = _rectangle()
    original_points = _point_tuples(shape)
    canvas.pixmap = None
    _activate_edge_drag(canvas, shape, "left")
    apply_edge_coord(shape, "left", 30.0)

    canvas.mouseMoveEvent(_move_event(QtCore.QPointF(50.0, 60.0)))

    assert _point_tuples(shape) == original_points
    assert canvas.rect_edge_dragging is False


def test_edge_hit_checks_each_shape_vertex_once(canvas, monkeypatch):
    """The rectangle-edge hover path does not repeat vertex hit testing."""
    shape = _rectangle()
    calls = []
    nearest_vertex = shape.nearest_vertex

    def counted_nearest_vertex(point, epsilon):
        """Record one delegated nearest-vertex query."""
        calls.append((point, epsilon))
        return nearest_vertex(point, epsilon)

    monkeypatch.setattr(shape, "nearest_vertex", counted_nearest_vertex)
    _enable_edge_hit(canvas, [shape], [shape])

    candidate = canvas._rect_edge_hit_candidate(QtCore.QPointF(10.0, 60.0))

    assert candidate is not None
    assert len(calls) == 1


def test_edge_hover_does_not_force_synchronous_repaint(canvas, monkeypatch):
    """Edge hover schedules state updates without a synchronous repaint."""
    shape = _rectangle()
    _enable_edge_hit(canvas, [shape], [shape])
    repaint_calls = []
    monkeypatch.setattr(canvas, "repaint", lambda: repaint_calls.append(True))

    canvas.mouseMoveEvent(_move_event(QtCore.QPointF(10.0, 60.0)))

    assert canvas.rect_edge_hover_edge is not None
    assert repaint_calls == []


def test_selected_rectangle_drag_updates_without_repaint(canvas, monkeypatch):
    """Whole-rectangle dragging schedules a paint instead of forcing repaint."""
    shape = _rectangle(width=40.0, height=30.0)
    canvas.pixmap = QtGui.QPixmap(100, 80)
    canvas.resize(100, 80)
    canvas.shapes = [shape]
    canvas.set_editing(True)
    canvas.mousePressEvent(_press_event(QtCore.QPointF(20.0, 20.0)))
    updates = []
    repaints = []
    shown = []
    monkeypatch.setattr(canvas, "_update_crosshair_cursor", lambda _pos: None)
    monkeypatch.setattr(canvas, "update", lambda: updates.append(True))
    monkeypatch.setattr(canvas, "repaint", lambda: repaints.append(True))
    canvas.show_shape.connect(lambda *args: shown.append(args))

    canvas.mouseMoveEvent(
        _move_event(
            QtCore.QPointF(25.0, 25.0),
            buttons=QtCore.Qt.MouseButton.LeftButton,
        )
    )

    assert _point_tuples(shape) == [
        (15.0, 15.0),
        (55.0, 15.0),
        (55.0, 45.0),
        (15.0, 45.0),
    ]
    assert updates == [True]
    assert repaints == []
    assert canvas.moving_shape is True
    assert shown


def test_selected_rectangle_drag_noop_skips_paint_and_status(
    canvas, monkeypatch
):
    """A blocked whole-rectangle drag does not spend a redundant frame."""
    shape = _rectangle(x=50.0, y=10.0, width=49.0, height=30.0)
    canvas.pixmap = QtGui.QPixmap(100, 80)
    canvas.resize(100, 80)
    canvas.shapes = [shape]
    canvas.set_editing(True)
    canvas.mousePressEvent(_press_event(QtCore.QPointF(70.0, 20.0)))
    updates = []
    repaints = []
    shown = []
    changed = []
    monkeypatch.setattr(canvas, "_update_crosshair_cursor", lambda _pos: None)
    monkeypatch.setattr(canvas, "update", lambda: updates.append(True))
    monkeypatch.setattr(canvas, "repaint", lambda: repaints.append(True))
    canvas.show_shape.connect(lambda *args: shown.append(args))
    canvas.shape_changed.connect(changed.append)

    canvas.mouseMoveEvent(
        _move_event(
            QtCore.QPointF(130.0, 20.0),
            buttons=QtCore.Qt.MouseButton.LeftButton,
        )
    )

    assert _point_tuples(shape) == [
        (50.0, 10.0),
        (99.0, 10.0),
        (99.0, 40.0),
        (50.0, 40.0),
    ]
    assert updates == []
    assert repaints == []
    assert shown == []
    assert changed == []
    assert canvas.moving_shape is False


def test_selected_rectangle_vertex_drag_repaints_each_changed_frame(
    canvas, monkeypatch
):
    """Dragging a rectangle corner presents every accepted geometry frame."""
    shape = _rectangle(width=16.0, height=16.0)
    _use_identity_pixmap(canvas, width=100, height=100)
    canvas.shapes = [shape]
    _select(canvas, shape)
    canvas.set_editing(True)
    canvas.h_hape = shape
    canvas.h_vertex = 0
    updates = []
    repaints = []
    monkeypatch.setattr(canvas, "_update_crosshair_cursor", lambda _pos: None)
    monkeypatch.setattr(canvas, "update", lambda: updates.append(True))
    monkeypatch.setattr(canvas, "repaint", lambda: repaints.append(True))

    canvas.mouseMoveEvent(
        _move_event(
            QtCore.QPointF(12.0, 12.0),
            buttons=QtCore.Qt.MouseButton.LeftButton,
        )
    )

    assert _point_tuples(shape) == [
        (12.0, 12.0),
        (26.0, 12.0),
        (26.0, 26.0),
        (12.0, 26.0),
    ]
    assert updates == []
    assert repaints == [True]
    assert canvas.moving_shape is True


def test_rect_edge_drag_repaints_each_changed_frame(canvas, monkeypatch):
    """Dragging one rectangle edge does not coalesce visible geometry frames."""
    shape = _rectangle(width=40.0, height=30.0)
    _use_identity_pixmap(canvas, width=100, height=100)
    canvas.shapes = [shape]
    _select(canvas, shape)
    _activate_edge_drag(canvas, shape, "left")
    updates = []
    repaints = []
    monkeypatch.setattr(canvas, "update", lambda: updates.append(True))
    monkeypatch.setattr(canvas, "repaint", lambda: repaints.append(True))

    canvas._rect_edge_drag_update(QtCore.QPointF(20.0, 20.0))

    assert _point_tuples(shape) == [
        (20.0, 10.0),
        (50.0, 10.0),
        (50.0, 40.0),
        (20.0, 40.0),
    ]
    assert updates == []
    assert repaints == [True]


def test_live_geometry_drag_defers_heavy_overlays(canvas):
    """Live geometry dragging uses the lightweight overlay pass."""
    shape = _rectangle(width=40.0, height=30.0)
    canvas.shapes = [shape]
    _select(canvas, shape)
    canvas.moving_shape = True

    assert canvas._should_defer_drag_overlays() is True

    canvas.h_vertex = 0
    assert canvas._should_defer_drag_overlays() is True
    canvas.h_vertex = None

    canvas.moving_shape = False
    _activate_edge_drag(canvas, shape, "left")
    assert canvas._should_defer_drag_overlays() is True
    canvas.rect_edge_dragging = False

    canvas.moving_shape = True
    canvas.h_cuboid_face = 0
    assert canvas._should_defer_drag_overlays() is True
    canvas.h_cuboid_face = None

    canvas.moving_shape = False
    assert canvas._should_defer_drag_overlays() is False


def test_canvas_commits_selection_before_emitting_signal(canvas):
    """Canvas owns selected_shapes and Shape.selected before notification."""
    first = _rectangle()
    second = _rectangle(x=150.0)
    canvas.shapes = [first, second]
    canvas.select_shapes([first])
    observed = []

    def observe(selected_shapes):
        """Capture state as it exists inside the signal callback."""
        observed.append(
            (
                list(canvas.selected_shapes),
                first.selected,
                second.selected,
                list(selected_shapes),
            )
        )

    canvas.selection_changed.connect(observe)
    canvas.select_shapes([second])

    assert canvas.selected_shapes == [second]
    assert first.selected is False
    assert second.selected is True
    assert observed == [([second], False, True, [second])]


def test_selection_change_clears_rect_edge_hover_and_pending(canvas):
    """Formal selection ownership invalidates stale mouse edge state."""
    first = _rectangle()
    second = _rectangle(x=150.0)
    _enable_edge_hit(canvas, [first, second], [first])
    canvas.mouseMoveEvent(_move_event(QtCore.QPointF(10.0, 60.0)))
    canvas.mousePressEvent(_press_event(QtCore.QPointF(10.0, 60.0)))
    assert canvas.rect_edge_hover_edge is not None
    assert canvas.rect_edge_pending_edge is not None

    canvas.select_shapes([second])

    assert canvas.selected_shapes == [second]
    assert canvas.rect_edge_hover_edge is None
    assert canvas.rect_edge_pending_edge is None
    assert canvas.rect_edge_active_edge is None


def test_edge_press_keeps_selection_without_external_signal_writer(canvas):
    """Direct edge editing does not depend on LabelingWidget state writeback."""
    selected = _rectangle()
    _enable_edge_hit(canvas, [selected], [selected])

    canvas.mousePressEvent(_press_event(QtCore.QPointF(10.0, 60.0)))

    assert canvas.rect_edge_pending_edge is not None
    assert canvas.selected_shapes == [selected]
    assert selected.selected is True


def test_edge_drag_keeps_selection_derived_observers_stable(canvas):
    """Edge dragging does not clear or re-emit the formal selection."""
    shape = _rectangle()
    _enable_edge_hit(canvas, [shape], [shape])
    selection_events = []
    canvas.selection_changed.connect(selection_events.append)

    canvas.mousePressEvent(_press_event(QtCore.QPointF(10.0, 60.0)))
    canvas.mouseMoveEvent(
        _move_event(
            QtCore.QPointF(11.0, 60.0),
            buttons=QtCore.Qt.MouseButton.LeftButton,
        )
    )

    assert canvas.selected_shapes == [shape]
    assert shape.selected is True
    assert selection_events == []
