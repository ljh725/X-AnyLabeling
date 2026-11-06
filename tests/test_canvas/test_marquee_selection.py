"""Ctrl-drag selection must never edit geometry or create undo entries."""

import copy

import pytest
from PyQt6 import QtCore, QtGui, QtTest, QtWidgets

from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.canvas import Canvas

Qt = QtCore.Qt
CTRL = Qt.KeyboardModifier.ControlModifier
NONE = Qt.KeyboardModifier.NoModifier
PRESS = QtCore.QEvent.Type.MouseButtonPress
MOVE = QtCore.QEvent.Type.MouseMove
RELEASE = QtCore.QEvent.Type.MouseButtonRelease


def rectangle(left, top, right, bottom):
    shape = Shape(label="object", shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(x, y)
        for x, y in (
            (left, top),
            (right, top),
            (right, bottom),
            (left, bottom),
        )
    ]
    shape.close()
    return shape


def mouse(canvas, kind, xy, modifiers=CTRL, held=True):
    pos = (QtCore.QPointF(*xy) + canvas.offset_to_center()) * canvas.scale
    button = (
        Qt.MouseButton.NoButton if kind == MOVE else Qt.MouseButton.LeftButton
    )
    buttons = (
        Qt.MouseButton.LeftButton
        if held and kind != RELEASE
        else Qt.MouseButton.NoButton
    )
    event = QtGui.QMouseEvent(kind, pos, pos, button, buttons, modifiers)
    QtWidgets.QApplication.sendEvent(canvas, event)


def drag(canvas, start, end, release_modifiers=CTRL):
    mouse(canvas, PRESS, start)
    mouse(canvas, MOVE, end)
    mouse(canvas, RELEASE, end, release_modifiers)


@pytest.fixture
def canvas(qt_application):
    widget = Canvas(parent=None)
    widget.pixmap = QtGui.QPixmap(200, 200)
    widget.pixmap.fill(QtGui.QColor("black"))
    widget.resize(200, 200)

    def select(shapes):
        for shape in widget.selected_shapes:
            shape.selected = False
        widget.selected_shapes = shapes
        for shape in shapes:
            shape.selected = True

    widget.selection_changed.connect(select)
    yield widget
    widget.close()
    widget.restore_cursor()


@pytest.mark.parametrize("reverse", [False, True])
def test_overlapping_shapes_are_added_once_without_editing(canvas, reverse):
    first = rectangle(20, 20, 40, 40)
    second = rectangle(60, 60, 90, 90)
    partial = rectangle(90, 90, 120, 120)
    outside = rectangle(150, 150, 170, 170)
    canvas.load_shapes([first, second, partial, outside])
    canvas.select_shapes([outside, first])
    before = [copy.deepcopy(s.to_dict()) for s in canvas.shapes]
    history = len(canvas.shapes_backups)
    moved = QtTest.QSignalSpy(canvas.shape_moved)
    pan = QtTest.QSignalSpy(canvas.pan_request)
    start, end = (10, 10), (100, 100)
    if reverse:
        start, end = end, start
    drag(canvas, start, end)
    assert canvas.selected_shapes == [outside, first, second, partial]
    assert [s.to_dict() for s in canvas.shapes] == before
    assert len(canvas.shapes_backups) == history
    assert len(moved) == len(pan) == 0
    assert not canvas.interaction_in_progress()
    assert not canvas.is_pointer_down


def test_hidden_shapes_are_skipped_and_locks_are_preserved(canvas):
    visible = rectangle(20, 20, 40, 40)
    hidden = rectangle(50, 20, 70, 40)
    filtered = rectangle(80, 20, 100, 40)
    locked = rectangle(20, 50, 40, 70)
    hidden.visible = False
    locked.locked = True
    canvas.load_shapes([visible, hidden, filtered, locked])
    canvas.set_shape_visible(filtered, False)
    drag(canvas, (10, 10), (110, 110))
    assert canvas.selected_shapes == [visible, locked]
    assert locked.locked


@pytest.mark.parametrize("start", [(20, 20), (20, 40), (40, 40)])
def test_drag_can_start_on_selected_vertex_edge_or_body(canvas, start):
    shape = rectangle(20, 20, 60, 60)
    second = rectangle(70, 70, 90, 90)
    canvas.load_shapes([shape, second])
    canvas.select_shapes([shape])
    canvas.set_rectangle_edge_enabled(True)
    mouse(canvas, MOVE, start, NONE, held=False)
    before = [list(s.points) for s in canvas.shapes]
    drag(canvas, start, (100, 100))
    assert canvas.selected_shapes == [shape, second]
    assert [s.points for s in canvas.shapes] == before


def test_ctrl_click_still_adds_and_toggles_selection(canvas):
    first = rectangle(20, 20, 60, 60)
    second = rectangle(100, 100, 140, 140)
    canvas.load_shapes([first, second])
    for xy, expected in (
        ((40, 40), [first]),
        ((120, 120), [first, second]),
        ((40, 40), [second]),
    ):
        mouse(canvas, MOVE, xy, NONE, held=False)
        mouse(canvas, PRESS, xy)
        mouse(canvas, RELEASE, (xy[0] + 1, xy[1] + 1))
        assert canvas.selected_shapes == expected


def test_empty_drag_keeps_previous_selection(canvas):
    shape = rectangle(20, 20, 40, 40)
    canvas.load_shapes([shape])
    canvas.select_shapes([shape])
    drag(canvas, (110, 110), (180, 180))
    assert canvas.selected_shapes == [shape]


def test_buttonless_move_before_release_keeps_marquee(canvas):
    shapes = [rectangle(20, 20, 40, 40), rectangle(60, 60, 90, 90)]
    canvas.load_shapes(shapes)
    for _ in range(3):
        canvas.select_shapes([])
        mouse(canvas, PRESS, (10, 10))
        mouse(canvas, MOVE, (100, 100))
        assert canvas._marquee_dragging
        # A hover/synthesized move must not discard a gesture awaiting release.
        mouse(canvas, MOVE, (100, 100), NONE, held=False)
        mouse(canvas, RELEASE, (100, 100), NONE)
        assert canvas.selected_shapes == shapes


def test_ctrl_double_click_press_can_begin_next_marquee(canvas):
    shapes = [rectangle(20, 20, 40, 40), rectangle(60, 60, 90, 90)]
    canvas.load_shapes(shapes)
    drag(canvas, (10, 10), (100, 100))
    canvas.select_shapes([])
    edited = QtTest.QSignalSpy(canvas.edit_label_requested)
    mouse(canvas, QtCore.QEvent.Type.MouseButtonDblClick, (10, 10))
    mouse(canvas, MOVE, (100, 100))
    mouse(canvas, RELEASE, (100, 100))
    assert canvas.selected_shapes == shapes
    assert len(edited) == 0


@pytest.mark.parametrize("reverse", [False, True])
def test_partial_overlap_selects_multiple_shapes_on_repeated_drags(
    canvas, reverse
):
    shapes = [rectangle(20, 20, 80, 80), rectangle(100, 20, 160, 80)]
    outside = rectangle(170, 100, 190, 130)
    canvas.load_shapes(shapes + [outside])
    start, end = (50, 40), (120, 60)
    if reverse:
        start, end = end, start
    original = [list(shape.points) for shape in canvas.shapes]
    for _ in range(4):
        canvas.select_shapes([])
        drag(canvas, start, end)
        assert canvas.selected_shapes == shapes
        assert [shape.points for shape in canvas.shapes] == original


@pytest.mark.parametrize("shape_type", ["point", "line", "polygon", "circle"])
def test_marquee_uses_shape_geometry(canvas, shape_type):
    shape = Shape(label="object", shape_type=shape_type)
    if shape_type == "point":
        points = [(50, 50)]
    elif shape_type == "line":
        points = [(10, 50), (100, 50)]
    elif shape_type == "circle":
        points = [(50, 50), (100, 50)]
    else:
        points = [(10, 10), (100, 10), (100, 100)]
    shape.points = [QtCore.QPointF(*point) for point in points]
    canvas.load_shapes([shape])
    drag(canvas, (45, 45), (60, 60))
    assert canvas.selected_shapes == [shape]
    canvas.select_shapes([])
    # Within the polygon/circle's bounding box but outside its geometry.
    drag(canvas, (1, 90), (10, 100))
    assert canvas.selected_shapes == []


def test_transform_and_early_ctrl_release(canvas):
    shape = rectangle(20, 20, 60, 60)
    canvas.load_shapes([shape])
    canvas.scale = 0.6
    canvas.pan_offset = QtCore.QPointF(18, -12)
    canvas.resize(400, 300)
    drag(canvas, (10, 10), (80, 80), release_modifiers=NONE)
    assert canvas.selected_shapes == [shape]


@pytest.mark.parametrize(
    "cancel", ["escape", "focus", "mode", "load", "reset", "loading"]
)
def test_cancellation_consumes_remaining_drag(canvas, cancel):
    shape = rectangle(20, 20, 60, 60)
    canvas.load_shapes([shape])
    canvas.select_shapes([shape])
    original = list(shape.points)
    mouse(canvas, PRESS, (10, 10))
    mouse(canvas, MOVE, (80, 80))
    assert canvas.interaction_in_progress()
    if cancel == "escape":
        QtTest.QTest.keyClick(canvas, Qt.Key.Key_Escape)
    elif cancel == "focus":
        canvas.focusOutEvent(None)
    elif cancel == "mode":
        canvas.set_editing(False)
    elif cancel == "load":
        canvas.load_shapes([shape])
    elif cancel == "reset":
        canvas.reset_state()
    else:
        canvas.set_loading(True)
    pan = QtTest.QSignalSpy(canvas.pan_request)
    mouse(canvas, MOVE, (100, 100))
    mouse(canvas, RELEASE, (100, 100))
    assert shape.points == original
    assert len(pan) == 0
    assert canvas._marquee_start is None
    assert not canvas._marquee_dragging
    assert not canvas._marquee_cancelled
    if cancel == "escape":
        assert canvas.selected_shapes == [shape]


def test_overlay_appears_only_after_drag_threshold(canvas):
    mouse(canvas, PRESS, (10, 10))
    assert not canvas._marquee_dragging
    mouse(canvas, MOVE, (12, 12))
    assert not canvas._marquee_dragging
    mouse(canvas, MOVE, (100, 100))
    assert canvas._marquee_dragging
    # Compare renders so the test exercises the real paint path.
    with_overlay = canvas.grab().toImage()
    mouse(canvas, RELEASE, (100, 100))
    without_overlay = canvas.grab().toImage()
    assert with_overlay.pixelColor(50, 50) != without_overlay.pixelColor(
        50, 50
    )


def test_normal_left_drag_still_moves_selected_shape(canvas):
    shape = rectangle(20, 20, 60, 60)
    canvas.load_shapes([shape])
    canvas.select_shapes([shape])
    mouse(canvas, MOVE, (40, 40), NONE, held=False)
    mouse(canvas, PRESS, (40, 40), NONE)
    mouse(canvas, MOVE, (50, 50), NONE)
    mouse(canvas, RELEASE, (50, 50), NONE)
    assert shape.points[0] == QtCore.QPointF(30, 30)


def test_create_mode_keeps_ctrl_drawing_gesture(canvas):
    canvas.set_editing(False)
    canvas.create_mode = "rectangle"
    mouse(canvas, PRESS, (20, 20))
    assert canvas.current is not None
    assert canvas._marquee_start is None
    mouse(canvas, RELEASE, (20, 20))
