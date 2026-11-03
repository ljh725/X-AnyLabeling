"""Contracts for four-extreme rectangle creation in the 4.2.1 line."""

from collections.abc import Iterator

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.views.labeling.utils.qt import Struct
from anylabeling.views.labeling.widgets.canvas import Canvas
from anylabeling.views.labeling.widgets.rectangle_creation import (
    RectangleCreation,
)
from anylabeling.views.labeling.widgets.rectangle_extreme import ExtremeDraft


class FakeOwner(QtWidgets.QWidget):
    """Provide only the host surface the creation controller depends on."""

    def __init__(self, canvas: Canvas) -> None:
        """Attach menus, actions and config to a real canvas."""
        super().__init__()
        self.canvas = canvas
        self.menus = Struct(tool=QtWidgets.QMenu(self))
        self.actions = Struct()
        self._config = {"shortcuts": {}}
        self.digit_to_label = None
        self.messages: list[str] = []

    def status(self, message, delay=5000):
        """Record user-visible status messages."""
        self.messages.append(message)

    def toggle_draw_mode(self, edit=True, create_mode="rectangle", **kwargs):
        """Mirror the real tool switch without touching application state."""
        self.canvas.set_editing(edit)
        self.canvas.create_mode = create_mode


@pytest.fixture(scope="module")
def app() -> QtWidgets.QApplication:
    """Provide an offscreen Qt application."""
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def canvas(app: QtWidgets.QApplication) -> Iterator[Canvas]:
    """Prepare a blank canvas with a 200x200 image."""
    widget = Canvas(parent=None)
    widget.pixmap = QtGui.QPixmap(200, 200)
    widget.resize(200, 200)
    yield widget
    widget.close()
    widget.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


@pytest.fixture
def creation(canvas: Canvas) -> Iterator[RectangleCreation]:
    """Attach the creation controller and label every committed shape."""
    owner = FakeOwner(canvas)
    controller = RectangleCreation(owner)

    def _apply_label() -> None:
        if canvas.shapes:
            canvas.shapes[-1].label = "cat"

    canvas.new_shape.connect(_apply_label)
    yield controller
    controller.deleteLater()
    owner.deleteLater()


def _complete_draft(controller: RectangleCreation) -> None:
    """Fill the draft with four boundaries inside the image."""
    for point in [(1, 10.5), (150, 1), (1, 90.75), (20.5, 150)]:
        assert controller.draft.accept(*point)


def test_extremes_ignore_unrelated_axes_and_keep_floats() -> None:
    """Boundary coordinates are assigned by role, never generic extrema."""
    draft = ExtremeDraft(300, 300)
    for point in [(1, 10.5), (80.25, 1), (299, 90.75), (20.5, 299)]:
        assert draft.accept(*point)
    assert draft.bbox() == (20.5, 10.5, 80.25, 90.75)


@pytest.mark.parametrize("point", [(10, -1), (300, 10), (float("nan"), 1)])
def test_invalid_points_leave_draft_unchanged(point: tuple) -> None:
    """Nonfinite or out-of-image inputs cannot advance the draft."""
    draft = ExtremeDraft(300, 300)
    assert not draft.accept(*point)
    assert draft.points == []


def test_reversed_boundary_is_rejected() -> None:
    """Invalid lower boundaries remain editable rather than swapping roles."""
    draft = ExtremeDraft(300, 300)
    assert draft.accept(50, 30)
    assert draft.accept(80, 40)
    assert not draft.accept(20, 29)
    assert draft.edge == "bottom"
    assert draft.accept(50, 90)
    assert not draft.accept(81, 50)
    draft.back()
    assert draft.edge == "bottom"


def test_same_position_can_express_adjacent_extremes() -> None:
    """A top-right corner can contribute both its y and its x."""
    draft = ExtremeDraft(300, 300)
    assert draft.accept(80, 10)
    assert draft.accept(80, 10)
    assert draft.accept(20, 90)
    assert draft.accept(20, 90)
    assert draft.bbox() == (20, 10, 80, 90)


def test_start_enters_creation_and_announces_first_boundary(
    creation: RectangleCreation, canvas: Canvas
) -> None:
    """Starting a draft switches the canvas to rectangle creation."""
    creation.start_extreme()
    assert isinstance(creation.draft, ExtremeDraft)
    assert canvas.drawing()
    assert canvas.create_mode == "rectangle"
    assert creation.commands["rectangle_submit"].isEnabled() is False
    assert creation.commands["rectangle_back"].isEnabled() is False
    assert "1/4" in creation.owner.messages[-1]


def test_boundaries_update_actions_and_back_reverts_one(
    creation: RectangleCreation,
) -> None:
    """Each accepted boundary refreshes the draft actions; back reverts one."""
    creation.start_extreme()
    assert creation.draft.accept(10, 20)
    creation.refresh()
    assert creation.commands["rectangle_back"].isEnabled()
    assert len(creation.draft.points) == 1
    creation.back()
    assert len(creation.draft.points) == 0
    assert creation.commands["rectangle_back"].isEnabled() is False


def test_submit_commits_one_shape_in_one_undo_step(
    creation: RectangleCreation, canvas: Canvas
) -> None:
    """A complete draft becomes a normal, undoable labelled rectangle."""
    creation.start_extreme()
    _complete_draft(creation)
    assert creation.draft.complete
    backups_before = len(canvas.shapes_backups)
    creation.submit_draft()
    assert creation.draft is None
    assert len(canvas.shapes) == 1
    shape = canvas.shapes[0]
    assert shape.shape_type == "rectangle"
    assert shape.label == "cat"
    xs = [point.x() for point in shape.points]
    ys = [point.y() for point in shape.points]
    assert (min(xs), min(ys), max(xs), max(ys)) == (20.5, 10.5, 150, 90.75)
    assert len(canvas.shapes_backups) == backups_before + 2
    canvas.restore_shape()
    assert canvas.shapes == []
    assert not canvas.drawing()


def test_submit_without_label_keeps_draft_and_discards_shape(
    creation: RectangleCreation, canvas: Canvas
) -> None:
    """A rejected label leaves no committed shape and no extra history."""
    canvas.new_shape.disconnect()
    creation.start_extreme()
    _complete_draft(creation)
    backups_before = list(canvas.shapes_backups)
    creation.submit_draft()
    assert canvas.shapes == []
    assert creation.draft is not None
    assert canvas.shapes_backups == backups_before
    assert canvas.drawing()


def test_escape_cancels_and_returns_to_editing(
    creation: RectangleCreation, canvas: Canvas
) -> None:
    """Escape drops the draft without touching committed annotations."""
    creation.start_extreme()
    assert creation.draft.accept(10, 20)
    event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_Escape,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    assert creation.eventFilter(canvas, event)
    assert creation.draft is None
    assert canvas.editing()
    assert canvas.shapes == []


def test_external_tool_change_cancels_pending_draft(
    creation: RectangleCreation, canvas: Canvas
) -> None:
    """Switching tools clears an uncommitted draft."""
    creation.start_extreme()
    assert creation.draft.accept(10, 20)
    creation.before_tool_change(True, "rectangle")
    assert creation.draft is None
    assert canvas.shapes == []


def test_paint_draft_draws_one_line_per_confirmed_boundary(
    creation: RectangleCreation, canvas: Canvas
) -> None:
    """Confirmed boundaries draw axis lines without leaking painter state."""
    from unittest.mock import MagicMock

    creation.start_extreme()
    assert creation.draft.accept(10, 20)
    assert creation.draft.accept(100, 20)
    painter = MagicMock()
    creation.paint_draft(painter)
    assert painter.drawLine.call_count == 2
    assert painter.drawEllipse.call_count == 2
    assert painter.restore.called
