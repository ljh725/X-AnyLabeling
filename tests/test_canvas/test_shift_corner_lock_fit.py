"""Exercise the Shift corner-lock drag through real canvas handlers.

The lock flow previews immediately, lets the pointer leave the box, and
commits the rectangle spanned by the fixed corner and the click. These
tests drive the real canvas key and mouse handlers so the round entry, the
left-button ownership, and the single undo step are all observed together.
"""

from collections.abc import Iterator

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.views.labeling.shape import Shape
from anylabeling.views.labeling.widgets.canvas import Canvas

BOX = (100.0, 100.0, 200.0, 200.0)


@pytest.fixture(scope="module")
def app() -> QtWidgets.QApplication:
    """Provide a Qt application for isolated canvas tests."""
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def canvas(app: QtWidgets.QApplication) -> Iterator[Canvas]:
    """Create one selected rectangle on a blank in-memory image."""
    widget = Canvas(parent=None)
    widget.pixmap = QtGui.QPixmap(300, 300)
    widget.resize(300, 300)
    shape = Shape(label="person", shape_type="rectangle")
    shape.points = [QtCore.QPointF(x, y) for x, y in (
        (100, 100), (200, 100), (200, 200), (100, 200),
    )]
    shape.close()
    shape.selected = True
    widget.shapes = [shape]
    widget.selected_shapes = [shape]

    def update_selection(shapes: list[Shape]) -> None:
        for existing in widget.shapes:
            existing.selected = existing in shapes
        widget.selected_shapes = shapes

    widget.selection_changed.connect(update_selection)
    widget.store_shapes()
    yield widget
    widget.close()
    widget.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def send(
    canvas: Canvas,
    kind: QtCore.QEvent.Type,
    point: tuple[float, float],
    shift: bool = True,
    alt: bool = False,
    buttons: QtCore.Qt.MouseButton | None = None,
) -> None:
    """Send a mouse event at an image-space position."""
    pos = (QtCore.QPointF(*point) + canvas.offset_to_center()) * canvas.scale
    button = (
        QtCore.Qt.MouseButton.NoButton
        if kind == QtCore.QEvent.Type.MouseMove
        else QtCore.Qt.MouseButton.LeftButton
    )
    if buttons is None:
        buttons = (
            button
            if kind in (
                QtCore.QEvent.Type.MouseButtonPress,
                QtCore.QEvent.Type.MouseButtonDblClick,
            )
            else QtCore.Qt.MouseButton.NoButton
        )
    modifiers = QtCore.Qt.KeyboardModifier.NoModifier
    if shift:
        modifiers |= QtCore.Qt.KeyboardModifier.ShiftModifier
    if alt:
        modifiers |= QtCore.Qt.KeyboardModifier.AltModifier
    event = QtGui.QMouseEvent(kind, pos, pos, button, buttons, modifiers)
    {
        QtCore.QEvent.Type.MouseMove: canvas.mouseMoveEvent,
        QtCore.QEvent.Type.MouseButtonPress: canvas.mousePressEvent,
        QtCore.QEvent.Type.MouseButtonDblClick: canvas.mouseDoubleClickEvent,
        QtCore.QEvent.Type.MouseButtonRelease: canvas.mouseReleaseEvent,
    }[kind](event)


def key_event(
    canvas: Canvas,
    key: QtCore.Qt.Key,
    modifiers: QtCore.Qt.KeyboardModifier,
    *,
    release: bool = False,
) -> None:
    """Send a real key press or release to the canvas."""
    event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyRelease
        if release
        else QtCore.QEvent.Type.KeyPress,
        key,
        modifiers,
    )
    (canvas.keyReleaseEvent if release else canvas.keyPressEvent)(event)


def stationary_pointer(monkeypatch, canvas: Canvas, point) -> None:
    """Provide cursor coordinates without moving the user's real mouse."""
    local = (QtCore.QPointF(*point) + canvas.offset_to_center()) * canvas.scale
    monkeypatch.setattr(canvas, "mapFromGlobal", lambda _pos: local.toPoint())


def press_shift(canvas, monkeypatch, point: tuple[float, float]) -> None:
    """Press Shift while the cursor sits at an image position."""
    stationary_pointer(monkeypatch, canvas, point)
    key_event(
        canvas,
        QtCore.Qt.Key.Key_Shift,
        QtCore.Qt.KeyboardModifier.ShiftModifier,
    )


def release_shift(canvas: Canvas) -> None:
    """Release Shift so the next press starts a new round."""
    key_event(
        canvas,
        QtCore.Qt.Key.Key_Shift,
        QtCore.Qt.KeyboardModifier.NoModifier,
        release=True,
    )


def drag(
    canvas: Canvas,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    alt: bool = False,
) -> None:
    """Press, move past the threshold, and release with Shift held."""
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, start, alt=alt)
    send(
        canvas,
        QtCore.QEvent.Type.MouseMove,
        end,
        alt=alt,
        buttons=QtCore.Qt.MouseButton.LeftButton,
    )
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, end, alt=alt)


def lose_the_release(canvas: Canvas, monkeypatch) -> None:
    """Lock the corner, drag, then drop the focus without a release.

    The canvas receives the focus-loss cancel, so the left release that the
    user makes outside the window never reaches it. The gesture is left
    waiting for that release.
    """
    press_shift(canvas, monkeypatch, (120, 180))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 150))
    send(
        canvas,
        QtCore.QEvent.Type.MouseMove,
        (250, 60),
        buttons=QtCore.Qt.MouseButton.LeftButton,
    )
    canvas.focusOutEvent(QtGui.QFocusEvent(QtCore.QEvent.Type.FocusOut))


def coordinates(shape: Shape) -> tuple[float, float, float, float]:
    """Return the rectangle bounds for assertions."""
    xs = [point.x() for point in shape.points]
    ys = [point.y() for point in shape.points]
    return min(xs), min(ys), max(xs), max(ys)


def test_shift_outside_the_box_locks_the_first_clear_zone(canvas, monkeypatch):
    """An outside start keeps the click fit until the pointer enters a zone."""
    press_shift(canvas, monkeypatch, (250, 120))
    assert canvas._point_fit_entry == "native"
    assert canvas._point_fit_locked_corner is None
    assert canvas._point_fit_pending_box == (100, 120, 250, 200)
    # Reaching the clear bottom-left zone locks its opposite corner.
    send(canvas, QtCore.QEvent.Type.MouseMove, (151.5, 120))
    assert canvas._point_fit_entry == "lock"
    assert canvas._point_fit_locked_corner == "bottom_left"
    assert canvas._point_fit_locked_box == BOX
    assert canvas._point_fit_pending_box == (100, 120, 151.5, 200)
    # Every later move keeps that corner, including one back outside.
    send(canvas, QtCore.QEvent.Type.MouseMove, (250, 60))
    assert canvas._point_fit_locked_corner == "bottom_left"
    assert canvas._point_fit_pending_box == (100, 60, 250, 200)
    drag(canvas, (250, 60), (250, 60))
    assert coordinates(canvas.shapes[0]) == (100, 60, 250, 200)


def test_shift_outside_commits_before_reaching_a_clear_zone(
    canvas, monkeypatch
):
    """A click outside the box still commits the classic click fit."""
    press_shift(canvas, monkeypatch, (250, 120))
    assert canvas._point_fit_entry == "native"
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (250, 120))
    assert canvas._point_fit_pressed
    assert not canvas._point_fit_lock_click
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (250, 120))
    assert coordinates(canvas.shapes[0]) == (100, 120, 250, 200)


def test_shift_outside_waits_in_the_cross_buffer(canvas, monkeypatch):
    """The buffer keeps the classic fit until a zone is unambiguous."""
    shape = canvas.shapes[0]
    shape.points = [QtCore.QPointF(x, y) for x, y in (
        (100, 100), (112, 100), (112, 112), (100, 112),
    )]
    press_shift(canvas, monkeypatch, (200, 106))
    assert canvas._point_fit_entry == "native"
    # The centre buffer of the tiny box cannot choose a corner yet.
    send(canvas, QtCore.QEvent.Type.MouseMove, (106, 106))
    assert canvas._point_fit_entry == "native"
    assert canvas._point_fit_locked_corner is None
    # Leaving the buffer again keeps the classic preview.
    send(canvas, QtCore.QEvent.Type.MouseMove, (200, 106))
    assert canvas._point_fit_entry == "native"
    assert canvas._point_fit_locked_corner is None
    send(canvas, QtCore.QEvent.Type.MouseMove, (109, 103))
    assert canvas._point_fit_entry == "lock"
    assert canvas._point_fit_locked_corner == "bottom_left"
    assert canvas._point_fit_pending_box == (100, 103, 109, 112)


def test_shift_on_the_outline_keeps_the_original_flow(canvas, monkeypatch):
    """The outline itself belongs to the original flow, not the buffer."""
    press_shift(canvas, monkeypatch, (150, 100))
    assert canvas._point_fit_entry == "native"
    assert canvas._point_fit_locked_corner is None


@pytest.mark.parametrize(
    ("point", "corner", "fixed", "candidate"),
    [
        ((120, 120), "bottom_right", (200, 200), (120, 120, 200, 200)),
        ((180, 120), "bottom_left", (100, 200), (100, 120, 180, 200)),
        ((120, 180), "top_right", (200, 100), (120, 100, 200, 180)),
        ((180, 180), "top_left", (100, 100), (100, 100, 180, 180)),
    ],
)
def test_shift_in_a_corner_zone_locks_and_previews_immediately(
    canvas, monkeypatch, point, corner, fixed, candidate
):
    """The starting region selects the moving corner in all four zones."""
    press_shift(canvas, monkeypatch, point)
    assert canvas._point_fit_entry == "lock"
    assert canvas._point_fit_locked_corner == corner
    assert canvas._point_fit_locked_box == BOX
    preview = canvas._build_point_fit_preview()
    assert preview is not None
    assert preview.fixed_point == fixed
    assert preview.pointer == point
    assert preview.candidate_box == candidate
    assert preview.guides


def test_locked_corner_survives_centre_and_outside_moves(canvas, monkeypatch):
    """Moving across the axes or out of the box never re-chooses a corner."""
    press_shift(canvas, monkeypatch, (120, 180))
    for point, expected in (
        ((75, 230), (75, 100, 200, 230)),
        ((126, 177), (126, 100, 200, 177)),
        ((120, 180), (120, 100, 200, 180)),
        ((150.5, 150.5), (150.5, 100, 200, 150.5)),
        ((250, 250), (200, 100, 250, 250)),
        ((245, 65), (200, 65, 245, 100)),
        ((50, 50), (50, 50, 200, 100)),
    ):
        send(canvas, QtCore.QEvent.Type.MouseMove, point)
        assert canvas._point_fit_locked_corner == "top_right"
        preview = canvas._build_point_fit_preview()
        assert preview.fixed_point == (200, 100)
        assert preview.candidate_box == expected
    assert coordinates(canvas.shapes[0]) == BOX


def test_buffer_start_waits_for_a_clear_zone(canvas, monkeypatch):
    """A small box starts undecided and locks on the first clear zone."""
    shape = canvas.shapes[0]
    shape.points = [QtCore.QPointF(x, y) for x, y in (
        (100, 100), (112, 100), (112, 112), (100, 112),
    )]
    press_shift(canvas, monkeypatch, (106, 106))
    assert canvas._point_fit_entry == "lock"
    assert canvas._point_fit_locked_corner is None
    assert canvas._point_fit_pending_box is None
    assert canvas._point_fit_cursor is None
    send(canvas, QtCore.QEvent.Type.MouseMove, (109, 103))
    assert canvas._point_fit_locked_corner == "bottom_left"
    assert canvas._point_fit_pending_box == (100, 103, 109, 112)
    send(canvas, QtCore.QEvent.Type.MouseMove, (101, 111))
    assert canvas._point_fit_locked_corner == "bottom_left"


def test_waiting_zone_hands_the_press_back_to_the_original_flow(
    canvas, monkeypatch
):
    """A press before the lock keeps the whole press, move, and release."""
    shape = canvas.shapes[0]
    shape.points = [QtCore.QPointF(x, y) for x, y in (
        (100, 100), (112, 100), (112, 112), (100, 112),
    )]
    press_shift(canvas, monkeypatch, (106, 106))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (106, 106))
    assert not canvas._point_fit_pressed
    assert canvas._point_fit_entry == "finished"
    send(
        canvas,
        QtCore.QEvent.Type.MouseMove,
        (116, 116),
        buttons=QtCore.Qt.MouseButton.LeftButton,
    )
    assert canvas._point_fit_locked_corner is None
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (116, 116))
    assert coordinates(shape) == (110, 110, 122, 122)
    send(canvas, QtCore.QEvent.Type.MouseMove, (119, 113))
    assert canvas._build_point_fit_preview() is None


def test_locked_click_outside_the_box_commits_once(canvas, monkeypatch):
    """A press outside the box still uses the locked corner."""
    shape = canvas.shapes[0]
    moves = []
    canvas.shape_moved.connect(lambda: moves.append(True))
    baseline = len(canvas.shapes_backups)
    press_shift(canvas, monkeypatch, (120, 180))
    send(canvas, QtCore.QEvent.Type.MouseMove, (250, 60))
    preview = canvas._build_point_fit_preview()
    assert preview is not None and preview.guides
    assert preview.fixed_point == (200.0, 100.0)
    assert preview.pointer == (250.0, 60.0)
    assert preview.candidate_box == (200.0, 60.0, 250.0, 100.0)
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (250, 60))
    assert canvas._point_fit_pressed
    assert canvas._point_fit_lock_click
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (250, 60))
    assert coordinates(shape) == (200, 60, 250, 100)
    assert len(canvas.shapes_backups) == baseline + 1
    assert moves == [True]
    canvas.restore_shape()
    assert coordinates(canvas.shapes[0]) == BOX


def test_locked_drag_can_cross_the_fixed_corner(canvas, monkeypatch):
    """Dragging past both fixed axes turns the fixed corner inside out."""
    shape = canvas.shapes[0]
    press_shift(canvas, monkeypatch, (120, 180))
    drag(canvas, (150, 150), (50, 50))
    assert coordinates(shape) == (50, 50, 200, 100)
    canvas.restore_shape()
    assert coordinates(canvas.shapes[0]) == BOX


def test_locked_click_matches_the_clipped_release(canvas, monkeypatch):
    """The orange preview and the release share clipping and commit."""
    shape = canvas.shapes[0]
    press_shift(canvas, monkeypatch, (120, 180))
    send(canvas, QtCore.QEvent.Type.MouseMove, (310, -10))
    preview = canvas._build_point_fit_preview()
    assert preview is not None
    assert preview.candidate_box == (200.0, 0.0, 300.0, 100.0)
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (310, -10))
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (310, -10))
    assert coordinates(shape) == (200, 0, 300, 100)


def test_locked_click_commits_without_drag_and_ends_the_round(canvas, monkeypatch):
    """The recorded bottom-right click commits instead of switching modes."""
    shape = canvas.shapes[0]
    moves = []
    canvas.shape_moved.connect(lambda: moves.append(True))
    baseline = len(canvas.shapes_backups)
    press_shift(canvas, monkeypatch, (180, 180))
    assert canvas._point_fit_locked_corner == "top_left"
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (180, 180))
    assert coordinates(shape) == BOX
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (180, 180))
    assert coordinates(shape) == (100, 100, 180, 180)
    assert moves == [True]
    assert len(canvas.shapes_backups) == baseline + 1
    assert canvas._point_fit_locked_corner is None
    shape.selected = True
    canvas.selected_shapes = [shape]
    send(canvas, QtCore.QEvent.Type.MouseMove, (160, 159))
    assert canvas._build_point_fit_preview() is None
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (160, 159))
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (160, 159))
    assert moves == [True]
    release_shift(canvas)
    shape.selected = True
    canvas.selected_shapes = [shape]
    press_shift(canvas, monkeypatch, (168, 116))
    assert canvas._point_fit_locked_corner == "bottom_left"


def test_locked_invalid_release_keeps_the_box_and_the_corner(
    canvas, monkeypatch
):
    """A candidate thinner than one image pixel never commits or unlocks."""
    shape = canvas.shapes[0]
    moves = []
    canvas.shape_moved.connect(lambda: moves.append(True))
    baseline = len(canvas.shapes_backups)
    press_shift(canvas, monkeypatch, (120, 180))
    send(canvas, QtCore.QEvent.Type.MouseMove, (200.5, 150))
    assert canvas._point_fit_pending_box is None
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (200.5, 150))
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (200.5, 150))
    assert coordinates(shape) == BOX
    assert moves == []
    assert len(canvas.shapes_backups) == baseline
    # The click only ended; the same original corner is still locked.
    assert canvas._point_fit_locked_corner == "top_right"
    assert canvas._point_fit_locked_box == BOX
    # The round keeps running so the retry needs no new Shift press.
    assert canvas._point_fit_entry == "lock"
    # Moving to a valid position previews with that same corner.
    send(canvas, QtCore.QEvent.Type.MouseMove, (150, 130))
    preview = canvas._build_point_fit_preview()
    assert preview is not None
    assert preview.fixed_point == (200, 100)
    assert preview.candidate_box == (150, 100, 200, 130)
    # A second click now commits exactly once.
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 130))
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (150, 130))
    assert coordinates(shape) == (150, 100, 200, 130)
    assert moves == [True]
    assert len(canvas.shapes_backups) == baseline + 1
    canvas.restore_shape()
    assert coordinates(canvas.shapes[0]) == BOX


def test_locked_click_on_the_fixed_corner_keeps_the_corner(
    canvas, monkeypatch
):
    """A release on the fixed corner has no area, so the click only ends."""
    shape = canvas.shapes[0]
    moves = []
    canvas.shape_moved.connect(lambda: moves.append(True))
    baseline = len(canvas.shapes_backups)
    press_shift(canvas, monkeypatch, (120, 180))
    # The fixed corner and the pointer coincide: no image area to commit.
    send(canvas, QtCore.QEvent.Type.MouseMove, (200, 100))
    assert canvas._point_fit_pending_box is None
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (200, 100))
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (200, 100))
    assert coordinates(shape) == BOX
    assert moves == []
    assert len(canvas.shapes_backups) == baseline
    assert canvas._point_fit_locked_corner == "top_right"
    send(canvas, QtCore.QEvent.Type.MouseMove, (150, 130))
    assert canvas._point_fit_pending_box == (150, 100, 200, 130)


def test_releasing_shift_during_the_locked_drag_cancels(canvas, monkeypatch):
    """Releasing Shift clears the preview and keeps the release consumed."""
    shape = canvas.shapes[0]
    moves = []
    canvas.shape_moved.connect(lambda: moves.append(True))
    press_shift(canvas, monkeypatch, (120, 180))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 150))
    send(
        canvas,
        QtCore.QEvent.Type.MouseMove,
        (50, 50),
        buttons=QtCore.Qt.MouseButton.LeftButton,
    )
    assert canvas._point_fit_pending_box == (50.0, 50.0, 200.0, 100.0)
    release_shift(canvas)
    assert canvas._point_fit_pending_box is None
    assert canvas._point_fit_locked_corner is None
    assert not canvas._point_fit_pressed
    assert canvas._point_fit_release_pending
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (50, 50), shift=False)
    assert coordinates(shape) == BOX
    assert moves == []
    assert not canvas._point_fit_pressed
    assert not canvas._point_fit_release_pending


def test_alt_does_not_change_a_locked_round(canvas, monkeypatch):
    """Alt cannot switch a locked round to a same-side corner fit."""
    shape = canvas.shapes[0]
    baseline = len(canvas.shapes_backups)
    press_shift(canvas, monkeypatch, (180, 120))
    assert canvas._point_fit_locked_corner == "bottom_left"
    key_event(
        canvas,
        QtCore.Qt.Key.Key_Alt,
        QtCore.Qt.KeyboardModifier.ShiftModifier
        | QtCore.Qt.KeyboardModifier.AltModifier,
    )
    assert canvas._point_fit_locked_corner == "bottom_left"
    assert canvas._point_fit_pending_box == (100, 120, 180, 200)
    # The click still confirms the locked opposite-corner preview.
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (180, 120), alt=True)
    assert canvas._point_fit_lock_click
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (180, 120), alt=True)
    assert coordinates(shape) == (100, 120, 180, 200)
    assert len(canvas.shapes_backups) == baseline + 1


def test_alt_then_shift_keeps_the_locked_corner(canvas, monkeypatch):
    """Pressing Alt first changes nothing about the Shift round."""
    stationary_pointer(monkeypatch, canvas, (180, 120))
    key_event(
        canvas, QtCore.Qt.Key.Key_Alt, QtCore.Qt.KeyboardModifier.AltModifier
    )
    key_event(
        canvas,
        QtCore.Qt.Key.Key_Shift,
        QtCore.Qt.KeyboardModifier.ShiftModifier
        | QtCore.Qt.KeyboardModifier.AltModifier,
    )
    assert canvas._point_fit_entry == "lock"
    assert canvas._point_fit_locked_corner == "bottom_left"
    assert canvas._point_fit_pending_box == (100, 120, 180, 200)
    key_event(
        canvas,
        QtCore.Qt.Key.Key_Alt,
        QtCore.Qt.KeyboardModifier.ShiftModifier,
        release=True,
    )
    assert canvas._point_fit_locked_corner == "bottom_left"
    assert canvas._point_fit_pending_box == (100, 120, 180, 200)
    drag(canvas, (150, 150), (50, 50))
    assert coordinates(canvas.shapes[0]) == (50, 50, 100, 200)


def test_alt_during_the_locked_drag_keeps_the_drag_mode(canvas, monkeypatch):
    """Alt pressed after the press cannot re-choose the corner."""
    shape = canvas.shapes[0]
    press_shift(canvas, monkeypatch, (120, 180))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (120, 180))
    send(
        canvas,
        QtCore.QEvent.Type.MouseMove,
        (60, 60),
        alt=True,
        buttons=QtCore.Qt.MouseButton.LeftButton,
    )
    assert canvas._point_fit_pending_box == (60.0, 60.0, 200.0, 100.0)
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (60, 60), alt=True)
    assert coordinates(shape) == (60, 60, 200, 100)


def test_focus_loss_and_image_change_clear_the_lock(canvas, monkeypatch):
    """Window focus loss and a new image end the locked round."""
    press_shift(canvas, monkeypatch, (180, 120))
    assert canvas._point_fit_locked_corner == "bottom_left"
    canvas.focusOutEvent(QtGui.QFocusEvent(QtCore.QEvent.Type.FocusOut))
    assert canvas._point_fit_locked_corner is None
    assert canvas._point_fit_entry == "finished"
    send(canvas, QtCore.QEvent.Type.MouseMove, (120, 180))
    assert canvas._build_point_fit_preview() is None
    press_shift(canvas, monkeypatch, (120, 180))
    assert canvas._point_fit_locked_corner == "top_right"
    canvas.load_pixmap(QtGui.QPixmap(300, 300))
    assert canvas._point_fit_locked_corner is None
    assert canvas._point_fit_locked_target is None


def test_geometry_change_elsewhere_clears_the_lock(canvas, monkeypatch):
    """Another edit that moves the original box drops the locked corner."""
    press_shift(canvas, monkeypatch, (180, 120))
    shape = canvas.shapes[0]
    shape.points = [QtCore.QPointF(x, y) for x, y in (
        (100, 80), (200, 80), (200, 200), (100, 200),
    )]
    send(canvas, QtCore.QEvent.Type.MouseMove, (180, 120))
    assert canvas._point_fit_locked_corner is None
    assert canvas._point_fit_pending_box is None


def test_focus_loss_mid_drag_keeps_the_release_consumed(canvas, monkeypatch):
    """A cancelled locked drag still owns its pending left release."""
    shape = canvas.shapes[0]
    moves = []
    selections = []
    canvas.shape_moved.connect(lambda: moves.append(True))
    canvas.selection_changed.connect(
        lambda shapes: selections.append(list(shapes))
    )
    baseline = len(canvas.shapes_backups)
    press_shift(canvas, monkeypatch, (120, 180))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 150))
    send(
        canvas,
        QtCore.QEvent.Type.MouseMove,
        (250, 60),
        buttons=QtCore.Qt.MouseButton.LeftButton,
    )
    assert canvas._point_fit_pending_box == (200.0, 60.0, 250.0, 100.0)
    canvas.focusOutEvent(QtGui.QFocusEvent(QtCore.QEvent.Type.FocusOut))
    assert canvas._point_fit_pending_box is None
    assert canvas._point_fit_locked_corner is None
    assert not canvas._point_fit_pressed
    assert canvas._point_fit_release_pending
    # Waiting for the release is not an active edit any more.
    assert not canvas.interaction_in_progress()
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (250, 60))
    assert not canvas._point_fit_pressed
    assert not canvas._point_fit_release_pending
    assert not canvas.interaction_in_progress()
    assert coordinates(shape) == BOX
    assert len(canvas.shapes_backups) == baseline
    assert moves == []
    assert selections == []
    # The next ordinary gesture must still work after the consumed release.
    release_shift(canvas)
    press_shift(canvas, monkeypatch, (250, 120))
    drag(canvas, (151.5, 120), (151.5, 120))
    assert coordinates(shape) == (100, 120, 151.5, 200)


def test_image_change_mid_drag_keeps_the_release_consumed(canvas, monkeypatch):
    """Switching the image cancels the drag but still owns its release."""
    shape = canvas.shapes[0]
    moves = []
    canvas.shape_moved.connect(lambda: moves.append(True))
    baseline = len(canvas.shapes_backups)
    press_shift(canvas, monkeypatch, (180, 120))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 150))
    send(
        canvas,
        QtCore.QEvent.Type.MouseMove,
        (250, 60),
        buttons=QtCore.Qt.MouseButton.LeftButton,
    )
    canvas.load_pixmap(QtGui.QPixmap(300, 300), clear_shapes=False)
    assert canvas._point_fit_pending_box is None
    assert canvas._point_fit_locked_corner is None
    # The press is given up; only its release is still owed.
    assert not canvas._point_fit_pressed
    assert canvas._point_fit_release_pending
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (250, 60))
    assert not canvas._point_fit_pressed
    assert coordinates(shape) == BOX
    assert len(canvas.shapes_backups) == baseline
    assert moves == []


def test_releasing_shift_before_click_clears_the_live_preview(
    canvas, monkeypatch
):
    """Shift alone starts a live preview and releasing it cancels."""
    shape = canvas.shapes[0]
    baseline = len(canvas.shapes_backups)
    press_shift(canvas, monkeypatch, (180, 180))
    assert canvas._point_fit_pending_box == (100, 100, 180, 180)
    release_shift(canvas)
    assert canvas._build_point_fit_preview() is None
    assert canvas._point_fit_locked_corner is None
    send(canvas, QtCore.QEvent.Type.MouseMove, (120, 180), shift=False)
    assert canvas._build_point_fit_preview() is None
    assert coordinates(shape) == BOX
    assert len(canvas.shapes_backups) == baseline


def test_alt_commit_inside_a_locked_round_resolves_the_round(
    canvas, monkeypatch
):
    """An Alt-held commit still ends the round for the held Shift."""
    shape = canvas.shapes[0]
    press_shift(canvas, monkeypatch, (180, 120))
    key_event(
        canvas,
        QtCore.Qt.Key.Key_Alt,
        QtCore.Qt.KeyboardModifier.ShiftModifier
        | QtCore.Qt.KeyboardModifier.AltModifier,
    )
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (180, 120), alt=True)
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (180, 120), alt=True)
    assert coordinates(shape) == (100, 120, 180, 200)
    assert canvas._point_fit_entry == "finished"
    # A completed inside round stays finished even if the shape is selected.
    shape.selected = True
    canvas.selected_shapes = [shape]
    send(canvas, QtCore.QEvent.Type.MouseMove, (196, 140))
    assert canvas._build_point_fit_preview() is None


def test_repeated_cancels_still_consume_the_release(canvas, monkeypatch):
    """Reset then image change must both keep the pending release owned."""
    shape = canvas.shapes[0]
    moves = []
    canvas.shape_moved.connect(lambda: moves.append(True))
    press_shift(canvas, monkeypatch, (180, 120))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 150))
    send(
        canvas,
        QtCore.QEvent.Type.MouseMove,
        (250, 60),
        buttons=QtCore.Qt.MouseButton.LeftButton,
    )
    canvas.reset_state()
    assert canvas._point_fit_pending_box is None
    assert canvas._point_fit_locked_corner is None
    canvas.load_pixmap(QtGui.QPixmap(300, 300), clear_shapes=False)
    assert canvas._point_fit_release_pending
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (250, 60))
    assert not canvas._point_fit_pressed
    assert not canvas._point_fit_release_pending
    assert coordinates(shape) == BOX
    assert moves == []


def test_focus_loss_then_image_change_still_consumes_the_release(
    canvas, monkeypatch
):
    """Focus loss followed by an image change keeps the release owned."""
    shape = canvas.shapes[0]
    moves = []
    canvas.shape_moved.connect(lambda: moves.append(True))
    baseline = len(canvas.shapes_backups)
    press_shift(canvas, monkeypatch, (180, 120))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 150))
    send(
        canvas,
        QtCore.QEvent.Type.MouseMove,
        (250, 60),
        buttons=QtCore.Qt.MouseButton.LeftButton,
    )
    canvas.focusOutEvent(QtGui.QFocusEvent(QtCore.QEvent.Type.FocusOut))
    assert canvas._point_fit_pending_box is None
    canvas.load_pixmap(QtGui.QPixmap(300, 300), clear_shapes=False)
    assert canvas._point_fit_release_pending
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (250, 60))
    assert not canvas._point_fit_pressed
    assert not canvas._point_fit_release_pending
    assert coordinates(shape) == BOX
    assert len(canvas.shapes_backups) == baseline
    assert moves == []


def test_undelivered_release_does_not_block_the_next_drag(canvas, monkeypatch):
    """A lost release must not swallow the following ordinary drag."""
    shape = canvas.shapes[0]
    moves = []
    canvas.shape_moved.connect(lambda: moves.append(True))
    press_shift(canvas, monkeypatch, (180, 120))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 150))
    send(
        canvas,
        QtCore.QEvent.Type.MouseMove,
        (250, 60),
        buttons=QtCore.Qt.MouseButton.LeftButton,
    )
    canvas.focusOutEvent(QtGui.QFocusEvent(QtCore.QEvent.Type.FocusOut))
    # The release never reaches the canvas; a bare hover must not steal it.
    send(canvas, QtCore.QEvent.Type.MouseMove, (150, 150), shift=False)
    assert canvas._point_fit_release_pending
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 150), shift=False)
    assert not canvas._point_fit_pressed
    assert not canvas._point_fit_release_pending
    send(
        canvas,
        QtCore.QEvent.Type.MouseMove,
        (170, 130),
        shift=False,
        buttons=QtCore.Qt.MouseButton.LeftButton,
    )
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (170, 130), shift=False)
    assert coordinates(shape) == (120, 80, 220, 180)
    assert moves == [True]


def test_undelivered_release_then_direct_press_starts_normally(
    canvas, monkeypatch
):
    """A direct left press after a lost release starts a normal drag."""
    shape = canvas.shapes[0]
    press_shift(canvas, monkeypatch, (180, 120))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 150))
    send(
        canvas,
        QtCore.QEvent.Type.MouseMove,
        (250, 60),
        buttons=QtCore.Qt.MouseButton.LeftButton,
    )
    canvas.focusOutEvent(QtGui.QFocusEvent(QtCore.QEvent.Type.FocusOut))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 150), shift=False)
    assert not canvas._point_fit_pressed
    send(
        canvas,
        QtCore.QEvent.Type.MouseMove,
        (170, 130),
        shift=False,
        buttons=QtCore.Qt.MouseButton.LeftButton,
    )
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (170, 130), shift=False)
    assert coordinates(shape) == (120, 80, 220, 180)


def test_release_while_loading_is_consumed_and_clears_ownership(
    canvas, monkeypatch
):
    """A release during image loading is consumed without committing."""
    shape = canvas.shapes[0]
    moves = []
    canvas.shape_moved.connect(lambda: moves.append(True))
    baseline = len(canvas.shapes_backups)
    press_shift(canvas, monkeypatch, (180, 120))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 150))
    send(
        canvas,
        QtCore.QEvent.Type.MouseMove,
        (250, 60),
        buttons=QtCore.Qt.MouseButton.LeftButton,
    )
    canvas.load_pixmap(QtGui.QPixmap(300, 300), clear_shapes=False)
    canvas.is_loading = True
    try:
        send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (250, 60))
        assert not canvas._point_fit_pressed
        assert canvas._point_fit_pending_box is None
        assert coordinates(shape) == BOX
        assert len(canvas.shapes_backups) == baseline
        assert moves == []
    finally:
        canvas.is_loading = False
    # A new operation starts immediately after loading ends.
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 150), shift=False)
    send(
        canvas,
        QtCore.QEvent.Type.MouseMove,
        (170, 130),
        shift=False,
        buttons=QtCore.Qt.MouseButton.LeftButton,
    )
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (170, 130), shift=False)
    assert coordinates(shape) == (120, 80, 220, 180)


def test_moving_with_the_button_after_a_cancel_does_not_move_the_box(
    canvas, monkeypatch
):
    """A cancelled gesture swallows the button-held moves that follow it."""
    shape = canvas.shapes[0]
    moves = []
    canvas.shape_moved.connect(lambda: moves.append(True))
    baseline = len(canvas.shapes_backups)
    # One ordinary click seeds the native drag origin used by later moves.
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 150), shift=False)
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (150, 150), shift=False)
    press_shift(canvas, monkeypatch, (120, 180))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 150))
    send(
        canvas,
        QtCore.QEvent.Type.MouseMove,
        (250, 60),
        buttons=QtCore.Qt.MouseButton.LeftButton,
    )
    assert canvas._point_fit_pending_box == (200.0, 60.0, 250.0, 100.0)
    release_shift(canvas)
    assert not canvas._point_fit_pressed
    assert canvas._point_fit_release_pending
    # Shift is up but the button is still down: these moves belong to the
    # cancelled gesture and must not reach the native shape drag.
    send(
        canvas,
        QtCore.QEvent.Type.MouseMove,
        (120, 120),
        shift=False,
        buttons=QtCore.Qt.MouseButton.LeftButton,
    )
    send(
        canvas,
        QtCore.QEvent.Type.MouseMove,
        (60, 240),
        shift=False,
        buttons=QtCore.Qt.MouseButton.LeftButton,
    )
    assert coordinates(shape) == BOX
    assert canvas.selected_shapes == [shape]
    assert len(canvas.shapes_backups) == baseline
    assert moves == []
    send(
        canvas,
        QtCore.QEvent.Type.MouseButtonRelease,
        (60, 240),
        shift=False,
    )
    assert not canvas._point_fit_pressed
    assert coordinates(shape) == BOX
    assert moves == []


def test_lost_release_clears_the_interaction_after_a_bare_move(
    canvas, monkeypatch
):
    """A bare move proves the button is up; the late release stays owned."""
    shape = canvas.shapes[0]
    moves = []
    canvas.shape_moved.connect(lambda: moves.append(True))
    press_shift(canvas, monkeypatch, (180, 120))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 150))
    send(
        canvas,
        QtCore.QEvent.Type.MouseMove,
        (250, 60),
        buttons=QtCore.Qt.MouseButton.LeftButton,
    )
    canvas.focusOutEvent(QtGui.QFocusEvent(QtCore.QEvent.Type.FocusOut))
    assert canvas._point_fit_release_pending
    send(canvas, QtCore.QEvent.Type.MouseMove, (150, 150), shift=False)
    assert not canvas.interaction_in_progress()
    assert not canvas.is_pointer_down
    assert canvas._point_fit_release_pending
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (150, 150))
    assert not canvas._point_fit_pressed
    assert not canvas._point_fit_release_pending
    assert coordinates(shape) == BOX
    assert moves == []


@pytest.mark.parametrize("hover_first", [False, True])
def test_a_lost_release_does_not_block_the_next_lock(
    canvas, monkeypatch, hover_first
):
    """A fresh Shift press locks the corner again after a lost release."""
    shape = canvas.shapes[0]
    moves = []
    selections = []
    canvas.shape_moved.connect(lambda: moves.append(True))
    canvas.selection_changed.connect(
        lambda shapes: selections.append(list(shapes))
    )
    baseline = len(canvas.shapes_backups)
    lose_the_release(canvas, monkeypatch)
    assert canvas._point_fit_release_pending
    release_shift(canvas)
    if hover_first:
        # A buttonless move home proves the old press ended before Shift.
        send(canvas, QtCore.QEvent.Type.MouseMove, (120, 180), shift=False)
    press_shift(canvas, monkeypatch, (120, 180))
    assert canvas._point_fit_entry == "lock"
    assert canvas._point_fit_locked_corner == "top_right"
    assert canvas._point_fit_locked_box == BOX
    assert canvas._point_fit_pending_box == (120, 100, 200, 180)
    assert coordinates(shape) == BOX
    assert moves == []
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (120, 180))
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (120, 180))
    assert coordinates(shape) == (120, 100, 200, 180)
    assert canvas.selected_shapes == []
    assert len(canvas.shapes_backups) == baseline + 1
    assert moves == [True]
    assert selections == [[]]


def test_a_late_release_keeps_the_newly_locked_corner(canvas, monkeypatch):
    """The old release only ends its ownership and keeps the new lock."""
    shape = canvas.shapes[0]
    moves = []
    canvas.shape_moved.connect(lambda: moves.append(True))
    lose_the_release(canvas, monkeypatch)
    release_shift(canvas)
    press_shift(canvas, monkeypatch, (180, 120))
    assert canvas._point_fit_entry == "lock"
    assert canvas._point_fit_locked_corner == "bottom_left"
    # The old release finally arrives while the new corner is locked.
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (250, 60))
    assert not canvas._point_fit_release_pending
    assert canvas._point_fit_entry == "lock"
    assert canvas._point_fit_locked_corner == "bottom_left"
    assert canvas.selected_shapes == [shape]
    assert coordinates(shape) == BOX
    # The new round still drags from its own corner and commits once.
    drag(canvas, (150, 150), (60, 250))
    assert coordinates(shape) == (60, 200, 100, 250)
    assert moves == [True]
    canvas.restore_shape()
    assert coordinates(canvas.shapes[0]) == BOX


def test_a_lost_release_does_not_block_a_buffer_round(
    canvas, monkeypatch
):
    """The waiting zone of a new round still updates after a lost release."""
    shape = canvas.shapes[0]
    lose_the_release(canvas, monkeypatch)
    release_shift(canvas)
    shape.points = [QtCore.QPointF(x, y) for x, y in (
        (100, 100), (112, 100), (112, 112), (100, 112),
    )]
    press_shift(canvas, monkeypatch, (106, 106))
    assert canvas._point_fit_entry == "lock"
    assert canvas._point_fit_locked_corner is None
    assert canvas._point_fit_release_pending
    send(canvas, QtCore.QEvent.Type.MouseMove, (109, 103))
    assert canvas._point_fit_locked_corner == "bottom_left"


def test_alt_outside_the_canvas_keeps_the_owed_release(
    canvas, monkeypatch
):
    """Pressing Alt with the cursor outside never drops the release owed."""
    shape = canvas.shapes[0]
    moves = []
    canvas.shape_moved.connect(lambda: moves.append(True))
    baseline = len(canvas.shapes_backups)
    lose_the_release(canvas, monkeypatch)
    assert canvas._point_fit_release_pending
    # A bare move clears the stale pointer flag; the release stays owed.
    send(canvas, QtCore.QEvent.Type.MouseMove, (150, 150), shift=False)
    assert not canvas.is_pointer_down
    monkeypatch.setattr(
        canvas, "mapFromGlobal", lambda _pos: QtCore.QPoint(-20, -20)
    )
    key_event(
        canvas,
        QtCore.Qt.Key.Key_Alt,
        QtCore.Qt.KeyboardModifier.AltModifier,
    )
    assert canvas._point_fit_release_pending
    # The old release still belongs to the fit, not to the native path.
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (250, 60))
    assert not canvas._point_fit_release_pending
    assert canvas.selected_shapes == [shape]
    assert coordinates(shape) == BOX
    assert len(canvas.shapes_backups) == baseline
    assert moves == []


def test_a_held_button_keeps_the_next_shift_from_locking(
    canvas, monkeypatch
):
    """A still-held old press keeps the next Shift from locking."""
    shape = canvas.shapes[0]
    moves = []
    canvas.shape_moved.connect(lambda: moves.append(True))
    lose_the_release(canvas, monkeypatch)
    release_shift(canvas)
    monkeypatch.setattr(
        canvas,
        "_point_fit_mouse_buttons",
        lambda: QtCore.Qt.MouseButton.LeftButton,
    )
    assert canvas.is_pointer_down
    press_shift(canvas, monkeypatch, (180, 120))
    assert canvas._point_fit_entry is None
    assert canvas._point_fit_locked_corner is None
    assert canvas._point_fit_release_pending
    # The moves of the old held press still belong to the cancelled gesture.
    send(
        canvas,
        QtCore.QEvent.Type.MouseMove,
        (120, 120),
        shift=False,
        buttons=QtCore.Qt.MouseButton.LeftButton,
    )
    send(
        canvas,
        QtCore.QEvent.Type.MouseMove,
        (60, 240),
        shift=False,
        buttons=QtCore.Qt.MouseButton.LeftButton,
    )
    assert coordinates(shape) == BOX
    assert canvas.selected_shapes == [shape]
    assert moves == []


def test_stationary_shift_press_clears_the_edge_hint(canvas, monkeypatch, app):
    """Pressing Shift replaces an edge hover with the fit preview."""
    canvas.set_rectangle_edge_enabled(True)
    # Start from a balanced cursor stack so the assertion isolates this canvas.
    while QtWidgets.QApplication.overrideCursor() is not None:
        QtWidgets.QApplication.restoreOverrideCursor()
    send(canvas, QtCore.QEvent.Type.MouseMove, (100, 130), shift=False)
    assert canvas._rectangle_edge_hover is not None
    assert QtWidgets.QApplication.overrideCursor() is not None
    stationary_pointer(monkeypatch, canvas, (100, 130))
    key_event(
        canvas, QtCore.Qt.Key.Key_Shift,
        QtCore.Qt.KeyboardModifier.ShiftModifier,
    )
    assert canvas._point_fit_pending_box == (100, 130, 200, 200)
    assert canvas._rectangle_edge_hover is None
    assert QtWidgets.QApplication.overrideCursor() is None


def test_locked_drag_takes_over_a_native_drag(canvas, monkeypatch):
    """The locked press never reaches the native shape drag."""
    shape = canvas.shapes[0]
    press_shift(canvas, monkeypatch, (120, 180))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (180, 120))
    send(
        canvas,
        QtCore.QEvent.Type.MouseMove,
        (150, 150),
        buttons=QtCore.Qt.MouseButton.LeftButton,
    )
    assert canvas.is_pointer_down
    assert canvas._point_fit_pending_box == (150.0, 100.0, 200.0, 150.0)
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (150, 150))
    assert coordinates(shape) == (150, 100, 200, 150)


def test_locked_preview_suppresses_the_native_crosshair(canvas, monkeypatch):
    """Live fit guides replace the native crosshair until cancellation."""
    canvas.cross_line_show = True
    press_shift(canvas, monkeypatch, (180, 120))
    assert not canvas._native_crosshair_enabled()
    release_shift(canvas)
    assert canvas._native_crosshair_enabled()


def test_locked_preview_paints_a_solid_point_and_guides(
    canvas, monkeypatch, app
):
    """The fixed point, candidate and guides paint before any click."""
    canvas.cross_line_show = False
    press_shift(canvas, monkeypatch, (120, 180))
    hover = render(canvas)
    assert is_orange(hover.pixelColor(200, 100))
    assert not any(
        is_invalid_red(hover.pixelColor(200 + dx, 100 + dy))
        for dx in range(-4, 5)
        for dy in range(-4, 5)
    )
    assert any(
        is_orange(hover.pixelColor(120, y)) for y in range(112, 168)
    )
    send(canvas, QtCore.QEvent.Type.MouseMove, (250, 60))
    dragged = render(canvas)
    assert is_orange(dragged.pixelColor(200, 100))
    assert any(
        is_orange(dragged.pixelColor(250 + dx, 60 + dy))
        for dx in range(-5, 6)
        for dy in range(-5, 6)
    )
    # The vertical guide leaves the original box above the fixed point.
    assert any(
        is_orange(dragged.pixelColor(250, y)) for y in range(10, 55)
    )
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (250, 60))
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (250, 60))
    assert coordinates(canvas.shapes[0]) == (200, 60, 250, 100)


def render(canvas: Canvas) -> QtGui.QImage:
    """Render the widget to an opaque image."""
    image = QtGui.QImage(canvas.size(), QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor("white"))
    painter = QtGui.QPainter(image)
    try:
        canvas.render(painter)
    finally:
        painter.end()
    return image


def is_orange(color: QtGui.QColor) -> bool:
    """Return whether a pixel carries the orange fit candidate."""
    red, green, blue = color.red(), color.green(), color.blue()
    return red - blue > 40 and red > green > blue


def is_invalid_red(color: QtGui.QColor) -> bool:
    """Return whether a pixel carries the invalid-candidate red."""
    red, green, blue = color.red(), color.green(), color.blue()
    return red > 200 and red - green > 100 and red - blue > 100


def test_outside_commit_finishes_the_round_for_a_held_shift(
    canvas, monkeypatch
):
    """A committed outside click must not reopen the preview on the same Shift."""
    shape = canvas.shapes[0]
    press_shift(canvas, monkeypatch, (250, 120))
    assert canvas._point_fit_entry == "native"
    drag(canvas, (250, 120), (250, 120))
    assert coordinates(shape) == (100, 120, 250, 200)
    assert canvas._point_fit_entry == "finished"
    # Shift stays held: reselecting the rectangle and moving must not refit.
    shape = canvas.shapes[0]
    shape.selected = True
    canvas.selected_shapes = [shape]
    send(canvas, QtCore.QEvent.Type.MouseMove, (180, 140))
    assert canvas._build_point_fit_preview() is None
    assert canvas._point_fit_pending_box is None
    send(canvas, QtCore.QEvent.Type.MouseMove, (120, 180))
    assert canvas._build_point_fit_preview() is None
    # Only a new Shift press starts the next round.
    release_shift(canvas)
    press_shift(canvas, monkeypatch, (250, 150))
    assert canvas._point_fit_entry == "native"
    assert canvas._point_fit_pending_box == (100, 150, 250, 200)


def test_invalid_locked_click_keeps_the_solid_point_while_the_pointer_rests(
    canvas, monkeypatch
):
    """The locked marker survives the click that clears the transient preview."""
    canvas.cross_line_show = False
    press_shift(canvas, monkeypatch, (120, 180))
    assert canvas._point_fit_locked_corner == "top_right"
    # On the fixed corner's own vertical line: no image area to commit.
    send(canvas, QtCore.QEvent.Type.MouseMove, (200, 150))
    assert canvas._point_fit_pending_box is None
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (200, 150))
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (200, 150))
    assert coordinates(canvas.shapes[0]) == BOX
    assert canvas._point_fit_locked_corner == "top_right"
    # No further mouse event: the marker must already be back.
    preview = canvas._build_point_fit_preview()
    assert preview is not None
    assert preview.fixed_point == (200, 100)
    assert preview.candidate_box is None
    image = render(canvas)
    assert is_orange(image.pixelColor(200, 100))
    # Moving to a valid spot and clicking again commits exactly once.
    moves = []
    canvas.shape_moved.connect(lambda: moves.append(True))
    send(canvas, QtCore.QEvent.Type.MouseMove, (150, 130))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 130))
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (150, 130))
    assert coordinates(canvas.shapes[0]) == (150, 100, 200, 130)
    assert moves == [True]


def test_click_without_a_candidate_keeps_the_inside_lock_eligibility(
    canvas, monkeypatch
):
    """An accepted native click must not disable the later inside lock."""
    shape = canvas.shapes[0]
    baseline = len(canvas.shapes_backups)
    # The top edge is outside the lock zones and its centre has no candidate.
    press_shift(canvas, monkeypatch, (150, 100))
    assert canvas._point_fit_entry == "native"
    send(canvas, QtCore.QEvent.Type.MouseMove, (150, 120))
    assert canvas._point_fit_pending_box is None
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (150, 120))
    assert not canvas._point_fit_pressed
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (150, 120))
    assert canvas._point_fit_entry == "native"
    assert canvas._point_fit_round_locks
    # Shift is still held: entering the bottom-left zone locks its opposite.
    send(canvas, QtCore.QEvent.Type.MouseMove, (120, 180))
    assert canvas._point_fit_entry == "lock"
    assert canvas._point_fit_locked_corner == "top_right"
    assert canvas._point_fit_pending_box == (120, 100, 200, 180)
    assert coordinates(shape) == BOX
    assert len(canvas.shapes_backups) == baseline


def test_loading_before_the_release_never_commits(canvas, monkeypatch):
    """A loading image consumes the click instead of writing geometry."""
    shape = canvas.shapes[0]
    moves = []
    canvas.shape_moved.connect(lambda: moves.append(True))
    baseline = len(canvas.shapes_backups)
    press_shift(canvas, monkeypatch, (180, 180))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (180, 180))
    assert canvas._point_fit_pressed
    canvas.set_loading(True, "review probe")
    assert not canvas._point_fit_pressed
    assert canvas._point_fit_release_pending
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (180, 180))
    assert coordinates(shape) == BOX
    assert moves == []
    assert len(canvas.shapes_backups) == baseline
    assert not canvas._point_fit_release_pending


def test_cancelled_round_blocks_the_still_held_shift(canvas, monkeypatch):
    """Focus loss spends the Shift: later moves cannot revive the preview."""
    press_shift(canvas, monkeypatch, (250, 250))
    assert canvas._point_fit_entry == "native"
    assert canvas._point_fit_pending_box is not None
    canvas.focusOutEvent(QtGui.QFocusEvent(QtCore.QEvent.Type.FocusOut))
    assert canvas._point_fit_round_spent
    send(canvas, QtCore.QEvent.Type.MouseMove, (150, 150))
    assert canvas._build_point_fit_preview() is None
    assert canvas._point_fit_entry is None
    # Only a new real Shift press restarts fitting.
    press_shift(canvas, monkeypatch, (250, 250))
    assert canvas._point_fit_entry == "native"
    assert canvas._point_fit_pending_box is not None


def test_release_discovering_a_cancel_leaves_no_release_debt(
    canvas, monkeypatch
):
    """A cancel noticed by the release itself must not await another one."""
    press_shift(canvas, monkeypatch, (250, 250))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (250, 250))
    assert canvas._point_fit_pressed
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (250, 250),
         shift=False)
    assert not canvas._point_fit_release_pending
    assert not canvas._point_fit_pressed
    assert canvas._point_fit_round_spent
    assert coordinates(canvas.shapes[0]) == BOX


@pytest.mark.parametrize("lost_release", [False, True])
def test_double_click_on_a_locked_preview_still_confirms(
    canvas, monkeypatch, lost_release
):
    """Qt may deliver the quick retry as a double click; it stays a fit."""
    shape = canvas.shapes[0]
    edits = []
    canvas.edit_label_requested.connect(lambda: edits.append(True))
    if lost_release:
        lose_the_release(canvas, monkeypatch)
        release_shift(canvas)
        press_shift(canvas, monkeypatch, (120, 180))
        assert canvas._point_fit_release_pending
    else:
        press_shift(canvas, monkeypatch, (120, 180))
        # Invalid vertical line: the first click commits nothing.
        drag(canvas, (200, 150), (200, 150))
    assert coordinates(shape) == BOX
    send(canvas, QtCore.QEvent.Type.MouseMove, (150, 130))
    assert canvas._point_fit_pending_box == (150, 100, 200, 130)
    send(canvas, QtCore.QEvent.Type.MouseButtonDblClick, (150, 130))
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (150, 130))
    assert edits == []
    assert coordinates(shape) == (150, 100, 200, 130)
    assert len(canvas.shapes_backups) == 2


def test_locked_preview_follows_a_pan_of_the_image(canvas, monkeypatch):
    """A stationary pointer keeps its widget pixel; the landing point follows."""
    press_shift(canvas, monkeypatch, (120, 180))
    send(canvas, QtCore.QEvent.Type.MouseMove, (150, 130))
    assert canvas._point_fit_pending_box == (150, 100, 200, 130)
    canvas.pan_offset += QtCore.QPointF(12, 0)
    canvas.update()
    preview = canvas._build_point_fit_preview()
    assert preview is not None
    assert preview.fixed_point == (200, 100)
    assert preview.candidate_box == (138, 100, 200, 130)


def test_outside_capture_follows_a_pan_of_the_image(canvas, monkeypatch):
    """A captured outside preview and release use the same landing point."""
    shape = canvas.shapes[0]
    press_shift(canvas, monkeypatch, (50, 250))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (50, 250))
    canvas.pan_offset += QtCore.QPointF(12, 0)
    preview = canvas._build_point_fit_preview()
    assert preview.candidate_box == (38, 100, 200, 250)
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (38, 250))
    assert coordinates(shape) == preview.candidate_box
    assert len(canvas.shapes_backups) == 2


def test_locked_preview_tracks_scroll_of_the_canvas(app, canvas, monkeypatch):
    """Scrolling moves the canvas beneath the stationary mouse pointer."""
    area = QtWidgets.QScrollArea()
    area.resize(220, 220)
    area.setWidget(canvas)
    area.show()
    try:
        app.processEvents()
        press_shift(canvas, monkeypatch, (120, 180))
        send(canvas, QtCore.QEvent.Type.MouseMove, (150, 130))
        area.horizontalScrollBar().setValue(18)
        app.processEvents()
        assert canvas._point_fit_pending_box == (168, 100, 200, 130)
        preview = canvas._build_point_fit_preview()
        assert preview.fixed_point == (200, 100)
        assert preview.candidate_box == (168, 100, 200, 130)
    finally:
        area.takeWidget()
        area.close()


def test_clipped_preview_does_not_request_another_paint(canvas, monkeypatch):
    """Repeated paints reuse the same landing point outside the image."""
    press_shift(canvas, monkeypatch, (120, 180))
    send(canvas, QtCore.QEvent.Type.MouseMove, (-25, 335))
    updates = []
    monkeypatch.setattr(canvas, "update", lambda: updates.append(True))
    for _ in range(2):
        preview = canvas._build_point_fit_preview()
        assert preview.pointer == (0, 300)
        assert preview.candidate_box == (0, 100, 200, 300)
    assert updates == []


def test_unchanged_candidate_never_steals_the_press(canvas, monkeypatch):
    """A candidate identical to the box draws no dash, so it is native."""
    press_shift(canvas, monkeypatch, (250, 250))
    assert canvas._point_fit_entry == "native"
    # Hovering the opposite corner reproduces the original box exactly.
    send(canvas, QtCore.QEvent.Type.MouseMove, (200, 100))
    assert canvas._point_fit_pending_box == BOX
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (200, 100))
    assert not canvas._point_fit_pressed


def test_locked_marker_ignores_the_crosshair_opacity(canvas, monkeypatch):
    """A transparent native crosshair must not dim the fit marker."""
    canvas.cross_line_show = True
    canvas.cross_line_opacity = 0
    press_shift(canvas, monkeypatch, (120, 180))
    send(canvas, QtCore.QEvent.Type.MouseMove, (200, 150))
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (200, 150))
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (200, 150))
    preview = canvas._build_point_fit_preview()
    assert preview is not None and preview.fixed_point == (200, 100)
    image = render(canvas)
    assert is_orange(image.pixelColor(200, 100))


def test_invalid_outside_release_keeps_the_inside_lock_eligibility(
    canvas, monkeypatch
):
    """An uncommitted outside click must not spend the inside-lock round."""
    press_shift(canvas, monkeypatch, (250, 250))
    assert canvas._point_fit_entry == "native"
    assert canvas._point_fit_anchor == (100, 100)
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (250, 250))
    # Releasing on the anchor's own vertical line leaves no image area.
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (100, 250))
    assert coordinates(canvas.shapes[0]) == BOX
    assert canvas._point_fit_round_locks
    send(canvas, QtCore.QEvent.Type.MouseMove, (120, 180))
    assert canvas._point_fit_entry == "lock"
    assert canvas._point_fit_locked_corner == "top_right"


def test_press_without_a_move_keeps_the_shown_anchor(canvas, monkeypatch):
    """A synthesised press must not re-pick the anchor the user saw.

    Without the intermediate move the new point sits in the opposite
    quadrant, which would infer the far corner instead of the shown one.
    """
    shape = canvas.shapes[0]
    # Outside the bottom-left: the shown anchor is the top-right corner.
    press_shift(canvas, monkeypatch, (50, 250))
    shown = canvas._build_point_fit_preview()
    assert shown is not None
    assert shown.fixed_point is None
    assert shown.candidate_box == (50, 100, 200, 250)
    # No move event: the press arrives in the top-right quadrant, which
    # would infer the bottom-left anchor. The shown top-right anchor wins.
    send(canvas, QtCore.QEvent.Type.MouseButtonPress, (280, 50))
    send(canvas, QtCore.QEvent.Type.MouseButtonRelease, (280, 50))
    assert coordinates(shape) == (200, 50, 280, 100)
