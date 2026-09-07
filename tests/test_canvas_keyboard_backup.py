"""Regression tests for keyboard edits following programmatic selection."""

import pytest
from PyQt6 import QtCore, QtGui

from anylabeling.views.labeling.widgets.canvas import Shape


def prepare(canvas, kind: str = "rectangle") -> Shape:
    """Load a selected object without a mouse click or initial backup."""
    shape = Shape(label="person", shape_type=kind)
    shape.points = [
        QtCore.QPointF(x, y)
        for x, y in [(20, 20), (40, 20), (40, 50), (20, 50)]
    ]
    shape.close()
    canvas.load_pixmap(QtGui.QPixmap(200, 200))
    canvas.load_shapes([shape], store_backup=False)
    canvas.set_editing(True)
    canvas.select_shapes([shape])
    canvas.prev_point = QtCore.QPointF(25, 25)
    return shape


def release(canvas) -> None:
    """Deliver a release directly so Python exceptions fail the test."""
    canvas.keyReleaseEvent(
        QtGui.QKeyEvent(
            QtCore.QEvent.Type.KeyRelease,
            QtCore.Qt.Key.Key_Right,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
    )


@pytest.mark.parametrize("kind", ["rectangle", "rotation"])
def test_programmatic_keyboard_edit_is_one_undo(canvas, kind: str) -> None:
    """Initial snapshot precedes movement and repeated presses coalesce."""
    shape = prepare(canvas, kind)
    before = list(shape.points)
    changes = []
    canvas.shape_moved.connect(lambda: changes.append("move"))
    canvas.shape_rotated.connect(lambda: changes.append("rotate"))
    for _ in range(3):
        if kind == "rectangle":
            canvas.move_by_keyboard(QtCore.QPointF(1, 0))
        else:
            canvas.rotate_by_keyboard(0.01)
    release(canvas)
    assert shape.points != before
    assert len(changes) == 1
    assert len(canvas.shapes_backups) == 2
    assert not canvas.moving_shape and not canvas.rotating_shape
    canvas.restore_shape()
    assert canvas.shapes[0].points == before


@pytest.mark.parametrize("damage", ["empty", "short", "deleted", "reset"])
def test_release_handles_changed_context(canvas, damage: str) -> None:
    """A missing snapshot or disappearing object cannot crash release."""
    prepare(canvas)
    canvas.move_by_keyboard(QtCore.QPointF(1, 0))
    if damage == "empty":
        canvas.shapes_backups = []
    elif damage == "short":
        canvas.shapes_backups = [[]]
    elif damage == "deleted":
        canvas.shapes.clear()
    else:
        canvas.reset_state()
    release(canvas)
    assert not canvas.moving_shape and not canvas.rotating_shape


def test_zero_offset_does_not_create_undo(canvas) -> None:
    """An unchanged object does not create a restorable operation."""
    prepare(canvas)
    canvas.move_by_keyboard(QtCore.QPointF())
    release(canvas)
    assert not canvas.is_shape_restorable


def test_reorder_and_auto_repeat_release(canvas) -> None:
    """Release compares the edited live identity, not its old array index."""
    shape = prepare(canvas)
    other = shape.copy()
    canvas.load_shapes([other], replace=False, store_backup=False)
    canvas.move_by_keyboard(QtCore.QPointF(1, 0))
    canvas.shapes.reverse()
    event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyRelease,
        QtCore.Qt.Key.Key_Right,
        QtCore.Qt.KeyboardModifier.NoModifier,
        "",
        True,
    )
    canvas.keyReleaseEvent(event)
    assert canvas.moving_shape
    release(canvas)
    assert not canvas.moving_shape
    assert len(canvas.shapes_backups) == 2


def test_focus_loss_finishes_gesture_once(canvas) -> None:
    """Switching windows during a key gesture cannot leave dirty state lost."""
    prepare(canvas)
    changes = []
    canvas.shape_moved.connect(lambda: changes.append(True))
    canvas.move_by_keyboard(QtCore.QPointF(1, 0))
    canvas.focusOutEvent(QtGui.QFocusEvent(QtCore.QEvent.Type.FocusOut))
    release(canvas)
    assert changes == [True]
    assert len(canvas.shapes_backups) == 2
