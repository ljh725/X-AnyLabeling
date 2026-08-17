"""Unit tests for selection-set and gesture policy helpers."""


class _Point:
    """Minimal point double for the gesture state machine."""

    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __sub__(self, other):
        return _Point(self.x - other.x, self.y - other.y)

    def manhattanLength(self):
        return abs(self.x) + abs(self.y)


def test_toggle_shape_adds_and_removes_by_identity():
    """Ctrl-click toggles one object without changing other order."""
    from anylabeling.views.labeling.widgets.selection.policy import (
        toggle_shape,
    )

    first = object()
    second = object()
    assert toggle_shape([first], second) == [first, second]
    assert toggle_shape([first, second], first) == [second]


def test_selection_gesture_only_enters_box_after_threshold():
    """Small pointer jitter remains a click candidate."""
    from anylabeling.views.labeling.widgets.selection.gesture import (
        SelectionGesture,
    )

    gesture = SelectionGesture()
    gesture.begin(_Point(0, 0))
    assert gesture.update(_Point(2, 2), 5) is False
    assert gesture.rubber_band is False
    assert gesture.update(_Point(3, 2), 5) is True
    assert gesture.rubber_band is True
