"""Tests for shared person-instance invariants."""

from PyQt6 import QtCore, QtGui

from anylabeling.views.labeling.person_instance import is_valid_group_id
from tests.conftest import MockShape


def test_group_id_validation_rejects_bool_and_non_integer() -> None:
    """Only non-negative integers are legal group IDs."""
    assert is_valid_group_id(0)
    assert is_valid_group_id(8)
    assert not is_valid_group_id(True)
    assert not is_valid_group_id(-1)
    assert not is_valid_group_id("8")


def test_group_id_generation_ignores_malformed_values(canvas) -> None:
    """Malformed persisted IDs must not crash fresh ID allocation."""
    canvas.shapes = [
        MockShape(group_id="bad"),
        MockShape(group_id=True),
        MockShape(group_id=-1),
        MockShape(group_id=4),
    ]

    assert canvas.gen_new_group_id() == 5


def test_escape_drawing_emits_cancellation_signal(canvas) -> None:
    """Esc cancellation must notify transient bind-state owners."""
    from anylabeling.views.labeling.widgets.canvas import Shape

    canvas.set_editing(False)
    canvas.current = Shape(shape_type="rectangle")
    canvas.current.add_point(QtCore.QPointF(1.0, 1.0))
    canceled = []
    canvas.drawing_canceled.connect(lambda: canceled.append(True))
    event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_Escape,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )

    canvas._dispatch_default_key_press(event)

    assert canceled == [True]
    assert canvas.current is None
