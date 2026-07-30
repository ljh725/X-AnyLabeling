"""Target contracts for the simplified three-box focus mode.

These tests record the agreed behaviour after replacing the transaction-era
workflow with a lightweight geometric focus controller:

* focused edits use the native dirty/save path;
* Ctrl+Z uses the native Canvas undo path;
* Esc clears focus without rolling back completed edits;
* successful image loads clear stale focus;
* cancelled navigation preserves the current focus.

The tests intentionally drive user-facing LabelingWidget and Canvas entry
points instead of controller internals.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import anylabeling.config as _cfgmod  # noqa: E402

_CFG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "anylabeling",
    "configs",
    "xanylabeling_config.yaml",
)
_cfgmod.current_config_file = _CFG_PATH

from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402

from anylabeling.views.labeling.label_wrapper import (  # noqa: E402
    LabelingWrapper,
)
from anylabeling.views.labeling.shape import Shape  # noqa: E402

pytest.importorskip("PIL")
from PIL import Image as _PIL_Image  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> Iterator[QtWidgets.QApplication]:
    """Provide one offscreen QApplication for this module."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def make_png(tmp_path: Path) -> Callable[[str, tuple[int, int, int]], str]:
    """Return a factory for small solid-colour test images."""

    def _make(
        name: str = "img.png",
        color: tuple[int, int, int] = (255, 255, 255),
    ) -> str:
        path = tmp_path / name
        _PIL_Image.new("RGB", (300, 300), color).save(path)
        return str(path)

    return _make


@pytest.fixture
def widget(
    qapp: QtWidgets.QApplication,
    make_png: Callable[[str, tuple[int, int, int]], str],
) -> Iterator[Any]:
    """Provide a real LabelingWidget with one image loaded."""
    del qapp
    main_window = QtWidgets.QMainWindow()
    wrapper = LabelingWrapper(main_window)
    labeling_widget = wrapper.view
    assert labeling_widget.load_file(make_png()) is True
    yield labeling_widget
    main_window.close()


def _rect(
    label: str,
    x: float,
    y: float,
    width: float,
    height: float,
) -> Shape:
    """Create one axis-aligned rectangle Shape."""
    shape = Shape(label=label, shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(x, y),
        QtCore.QPointF(x + width, y),
        QtCore.QPointF(x + width, y + height),
        QtCore.QPointF(x, y + height),
    ]
    return shape


def _enter_focus(widget: Any, person: Shape, head: Shape) -> None:
    """Enable the mode and establish a focus through public UI events."""
    widget.load_shapes([person, head], replace=True, store_backup=False)
    widget._toggle_rect_refine_mode(True)
    widget.canvas.select_shapes([person], source="canvas")
    assert widget.canvas._main_visibility_predicate is not None


def test_menu_uses_lightweight_focus_wording(widget: Any) -> None:
    """The menu describes focus instead of the removed refine transaction."""
    assert widget.actions.toggle_rect_refine_mode.text() == "三框聚焦模式"


def test_focused_shape_move_uses_native_dirty_and_save(
    widget: Any,
) -> None:
    """A focused edit should use the normal document dirty/save path."""
    person = _rect("person", 10, 10, 120, 220)
    head = _rect("head", 40, 20, 60, 60)
    _enter_focus(widget, person, head)
    widget._config["auto_save"] = False
    widget.set_clean()

    head.points[0] = QtCore.QPointF(41.0, 20.0)
    widget.canvas.shape_moved.emit()

    assert widget.dirty is True
    assert widget.actions.save.isEnabled() is True


def test_focused_undo_delegates_to_native_canvas(
    widget: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ctrl+Z should call the native Canvas restore path while focused."""
    person = _rect("person", 10, 10, 120, 220)
    head = _rect("head", 40, 20, 60, 60)
    _enter_focus(widget, person, head)
    restore_calls: list[bool] = []

    def _restore_shape() -> None:
        """Record one native undo delegation."""
        restore_calls.append(True)

    monkeypatch.setattr(widget.canvas, "restore_shape", _restore_shape)
    widget.undo_shape_edit()

    assert restore_calls == [True]
    assert widget.canvas._main_visibility_predicate is None
    assert widget._rect_refine_focus_controller.has_focus is False


def test_escape_clears_focus_without_reverting_completed_edit(
    widget: Any,
) -> None:
    """Esc should clear focus but keep edited points and native dirty state."""
    person = _rect("person", 10, 10, 120, 220)
    head = _rect("head", 40, 20, 60, 60)
    _enter_focus(widget, person, head)
    widget._config["auto_save"] = False
    widget.set_clean()

    edited = QtCore.QPointF(41.0, 20.0)
    head.points[0] = edited
    widget.canvas.shape_moved.emit()
    event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_Escape,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    widget.canvas.keyPressEvent(event)

    assert head.points[0] == edited
    assert widget.dirty is True
    assert widget.canvas._main_visibility_predicate is None


def test_successful_direct_load_clears_focus_but_keeps_mode(
    widget: Any,
    make_png: Callable[[str, tuple[int, int, int]], str],
) -> None:
    """A successful image load should centrally clear stale focus state."""
    person = _rect("person", 10, 10, 120, 220)
    head = _rect("head", 40, 20, 60, 60)
    _enter_focus(widget, person, head)

    second = make_png("second.png", (0, 255, 0))
    assert widget.load_file(second) is True

    assert widget.canvas._main_visibility_predicate is None
    assert widget.actions.toggle_rect_refine_mode.isChecked() is True


def test_cancelled_navigation_preserves_current_focus(
    widget: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected navigation request must not clear the current focus."""
    person = _rect("person", 10, 10, 120, 220)
    head = _rect("head", 40, 20, 60, 60)
    _enter_focus(widget, person, head)
    predicate_before = widget.canvas._main_visibility_predicate
    monkeypatch.setattr(widget, "may_continue", lambda: False)

    widget.open_next_image()

    assert widget.canvas._main_visibility_predicate is predicate_before
    assert widget.actions.toggle_rect_refine_mode.isChecked() is True
