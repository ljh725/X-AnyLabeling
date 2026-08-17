"""Tests for viewport reset state semantics."""

from types import SimpleNamespace

import pytest
from PyQt6 import QtCore

from anylabeling.views.labeling.label_widget import LabelingWidget
from anylabeling.views.labeling.widgets.viewport_controller import (
    ViewportController,
    ViewportState,
)


class _FakeImage:
    """Minimal non-null image stand-in for default viewport tests."""

    def isNull(self):
        return False


class _FakeAction:
    """Checkable action stand-in."""

    def __init__(self):
        self.checked = False

    def setChecked(self, value):
        self.checked = value


class _FakeScrollBar:
    """Scroll bar stand-in exposing minimum and value updates."""

    def __init__(self):
        self.value = 8

    def minimum(self):
        return 0

    def setValue(self, value):
        self.value = value


def test_reset_states_deduplicates_targets_and_marks_default() -> None:
    """Reset targets are unique and bypass inherited state once."""
    controller = ViewportController()
    controller.record_state("a.png", ViewportState(2, 250, 10.0, 20.0))

    result = controller.reset_states(["a.png", "a.png", None, ""])

    assert result.filenames == (controller.normalize_filename("a.png"),)
    assert result.cleared_state_count == 1
    assert result.marked_default_count == 1
    assert not controller.has_state("a.png")
    assert controller.consume_force_default("a.png") is True
    assert controller.consume_force_default("a.png") is False


def test_reset_marks_file_without_existing_history() -> None:
    """A reset remains meaningful even when no cache entry existed."""
    controller = ViewportController()

    result = controller.reset_states(["future.png"])

    assert result.filenames == (controller.normalize_filename("future.png"),)
    assert result.cleared_state_count == 0
    assert result.marked_default_count == 1
    assert controller.consume_force_default("future.png") is True


def test_clear_state_removes_pending_default_marker() -> None:
    """Lifecycle cleanup removes both cached and pending state."""
    controller = ViewportController()
    controller.reset_states(["a.png"])

    assert controller.clear_state("a.png") is True
    assert controller.consume_force_default("a.png") is False


def test_clear_removes_pending_defaults_and_history() -> None:
    """Clearing a viewport session removes all per-file state."""
    controller = ViewportController()
    controller.record_state("a.png", ViewportState(0, 100, 0.0, 0.0))
    controller.reset_states(["b.png"])

    controller.clear()

    assert controller.states == {}
    assert controller.force_default_on_next_load == set()


def test_label_widget_reset_clears_state_machine_targets() -> None:
    """The LabelWidget adapter delegates reset to the state machine."""
    controller = ViewportController()
    controller.record_state("a.png", ViewportState(2, 250, 10.0, 20.0))
    widget = SimpleNamespace(viewport_controller=controller)

    result = LabelingWidget._clear_view_state_for_files(widget, ["a.png"])

    assert result.filenames == (controller.normalize_filename("a.png"),)
    assert controller.states == {}


def test_label_widget_session_clear_drops_all_dataset_viewport_state() -> None:
    """Dataset replacement clears exact and pending state."""
    controller = ViewportController()
    controller.record_state("old.png", ViewportState(0, 100, 0.0, 0.0))
    controller.reset_states(["future.png"])
    widget = SimpleNamespace(viewport_controller=controller)

    LabelingWidget._clear_viewport_session(widget)

    assert controller.states == {}
    assert controller.force_default_on_next_load == set()


def test_label_widget_reset_restores_state_after_transaction_failure() -> None:
    """A failed state-machine reset does not leave a partial state."""
    controller = ViewportController()
    state = ViewportState(2, 250, 10.0, 20.0)
    controller.record_state("a.png", state)
    with pytest.raises(RuntimeError, match="injected reset failure"):
        controller.reset_states_with_rollback(
            ["a.png"],
            after_reset=lambda _result: (_ for _ in ()).throw(
                RuntimeError("injected reset failure")
            ),
        )

    assert controller.state_for("a.png") == state
    assert controller.consume_force_default("a.png") is False


def test_current_reset_applies_default_view_and_reports_target_count() -> None:
    """Current reset updates UI state even when no cache existed."""
    controller = ViewportController()
    messages = []
    widget = SimpleNamespace(
        viewport_controller=controller,
        filename="a.png",
        image=_FakeImage(),
        FIT_WINDOW=0,
        zoom_mode=2,
        actions=SimpleNamespace(
            fit_window=_FakeAction(), fit_width=_FakeAction()
        ),
        scroll_bars={
            QtCore.Qt.Orientation.Horizontal: _FakeScrollBar(),
            QtCore.Qt.Orientation.Vertical: _FakeScrollBar(),
        },
        tr=lambda text: text,
        status=lambda message, delay: messages.append((message, delay)),
    )
    widget.adjust_scale = lambda initial=False: setattr(
        widget, "scale_applied", initial
    )
    widget.paint_canvas = lambda: setattr(widget, "painted", True)
    widget._apply_default_image_view = lambda: (
        LabelingWidget._apply_default_image_view(widget)
    )
    widget._clear_view_state_for_files = (
        lambda filenames: LabelingWidget._clear_view_state_for_files(
            widget, filenames
        )
    )

    LabelingWidget._reset_image_views_for_files(
        widget, ["a.png"], "the current image"
    )

    assert widget.zoom_mode == 0
    assert widget.actions.fit_window.checked is True
    assert widget.actions.fit_width.checked is False
    assert widget.scroll_bars[QtCore.Qt.Orientation.Horizontal].value == 0
    assert widget.scroll_bars[QtCore.Qt.Orientation.Vertical].value == 0
    assert messages[-1][0] == "Reset 1 image view(s) in the current image"


def test_reset_states_handles_thousands_of_targets() -> None:
    """Batch reset remains a simple linear in-memory operation."""
    controller = ViewportController()
    filenames = [f"image_{index}.png" for index in range(5000)]

    result = controller.reset_states(filenames)

    assert len(result.filenames) == 5000
    assert result.cleared_state_count == 0
    assert len(controller.force_default_on_next_load) == 5000


def test_reset_non_current_view_does_not_touch_shape_or_dirty_state() -> None:
    """Viewport invalidation remains separate from annotation mutations."""
    messages = []
    widget = SimpleNamespace(
        filename="current.png",
        image=_FakeImage(),
        shapes=["shape"],
        dirty=True,
        viewport_controller=SimpleNamespace(
            normalize_filename=lambda value: value,
        ),
        _clear_view_state_for_files=lambda filenames: SimpleNamespace(
            filenames=tuple(filenames)
        ),
        tr=lambda text: text,
        status=lambda message, delay: messages.append((message, delay)),
    )

    LabelingWidget._reset_image_views_for_files(
        widget, ["other.png"], "other image"
    )

    assert widget.shapes == ["shape"]
    assert widget.dirty is True
    assert messages
