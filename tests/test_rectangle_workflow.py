"""Real-widget regressions for independent creation and retired entry points."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import anylabeling.config as config_module  # noqa: E402
from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: E402
from anylabeling.views.labeling.label_wrapper import (
    LabelingWrapper,
)  # noqa: E402
from anylabeling.views.labeling.shape import Shape  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> Iterator[QtWidgets.QApplication]:
    """Provide the offscreen application."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def widget(
    qapp: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Any]:
    """Load a real image with isolated preferences and production widgets."""
    image = QtGui.QImage(300, 300, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor("white"))
    path = tmp_path / "image.png"
    assert image.save(str(path))
    main = QtWidgets.QMainWindow()
    template = (
        Path(__file__).parents[1]
        / "anylabeling/configs/xanylabeling_config.yaml"
    )
    config = yaml.safe_load(template.read_text(encoding="utf-8"))
    config["rectangle_workflow"]["enabled"] = True
    config["rectangle_review_refinement"]["enabled"] = True
    isolated = tmp_path / "preferences.yaml"
    isolated.write_text(
        yaml.safe_dump(config, allow_unicode=True), encoding="utf-8"
    )
    monkeypatch.setattr(config_module, "current_config_file", str(isolated))
    from anylabeling.services.auto_labeling import model_manager

    monkeypatch.setattr(model_manager, "get_config", lambda: config)
    wrapper = LabelingWrapper(main, config=config)
    main.setCentralWidget(wrapper)
    w = wrapper.view
    assert w.load_file(str(path))
    w._config["display_label_popup"] = True
    w._config["auto_use_last_label"] = False
    w._config["auto_use_last_gid"] = False
    w._config["auto_save"] = False
    main.resize(1400, 900)
    main.show()
    qapp.processEvents()
    yield w
    # Dispose each complete Qt tree before the next fixture creates a window.
    # Relying on cyclic Python GC can destroy live Qt timers out of order.
    for timer in w.findChildren(QtCore.QTimer):
        timer.stop()
    main.hide()
    main.deleteLater()
    QtWidgets.QApplication.sendPostedEvents(
        None, QtCore.QEvent.Type.DeferredDelete
    )
    qapp.processEvents()


def _rect(widget: Any) -> Shape:
    """Load and select a rectangle with a known undo baseline."""
    shape = Shape(label="person", shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(20, 30),
        QtCore.QPointF(100, 30),
        QtCore.QPointF(100, 120),
        QtCore.QPointF(20, 120),
    ]
    shape.close()
    widget.load_shapes([shape], replace=True)
    widget.canvas.select_shapes([shape])
    return shape


def _key(canvas: Any, key: Any, modifiers: Any = None) -> None:
    """Deliver a real Qt key event through the installed event filter."""
    if modifiers is None:
        modifiers = QtCore.Qt.KeyboardModifier.NoModifier
    event = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, key, modifiers)
    QtWidgets.QApplication.sendEvent(canvas, event)


def _click(widget: Any, x: float, y: float) -> None:
    """Send one press/release pair at an original-image coordinate."""
    canvas = widget.canvas
    point = (QtCore.QPointF(x, y) + canvas.offset_to_center()) * canvas.scale
    move = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseMove,
        point,
        point,
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    QtWidgets.QApplication.sendEvent(canvas, move)
    for event_type, buttons in (
        (
            QtCore.QEvent.Type.MouseButtonPress,
            QtCore.Qt.MouseButton.LeftButton,
        ),
        (
            QtCore.QEvent.Type.MouseButtonRelease,
            QtCore.Qt.MouseButton.NoButton,
        ),
    ):
        event = QtGui.QMouseEvent(
            event_type,
            point,
            point,
            QtCore.Qt.MouseButton.LeftButton,
            buttons,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        QtWidgets.QApplication.sendEvent(canvas, event)


def _draw(widget: Any) -> Shape:
    """Create a rectangle using four input events and digit prefill."""
    widget.digit_to_label = "person"
    widget.rectangle_creation.start_extreme()
    for x, y in [(50, 10), (80, 40), (60, 90), (20, 45)]:
        _click(widget, x, y)
    assert len(widget.canvas.shapes) == 1
    return widget.canvas.shapes[0]


def test_four_clicks_commit_one_rectangle(widget: Any) -> None:
    """Each click advances once and commits one compatible selected shape."""
    assert widget.actions.rectangle_extreme.isEnabled()
    shape = _draw(widget)
    assert shape.label == "person"
    assert shape.shape_type == "rectangle"
    assert [v for p in shape.points for v in (p.x(), p.y())] == pytest.approx(
        [20, 10, 80, 10, 80, 90, 20, 90]
    )
    assert widget.canvas.selected_shapes == [shape]
    assert widget.rectangle_creation.draft is None
    assert widget.canvas.rect_edge_active_edge is None
    widget.undo_shape_edit()
    assert widget.canvas.shapes == []


def test_old_config_cannot_restore_workflow(widget: Any) -> None:
    """Preserve old stored preferences without registering retired actions."""
    assert widget._config["rectangle_workflow"]["enabled"]
    assert widget._config["rectangle_review_refinement"]["enabled"]
    assert not widget.canvas.rectangle_review_refinement_enabled
    assert not hasattr(widget, "rectangle_workflow")
    assert not hasattr(widget.rectangle_creation, "start_refinement")
    assert set(widget.rectangle_creation.commands) == {
        "rectangle_extreme",
        "rectangle_submit",
        "rectangle_back",
        "rectangle_continue",
    }
    for name in (
        "rectangle_refine",
        "rectangle_keyboard_fit",
        "rectangle_next",
    ):
        assert not hasattr(widget.actions, name)
    assert not any(
        child.metaObject().className() == "RectangleFitHud"
        for child in widget.findChildren(QtWidgets.QWidget)
    )


def test_draft_back_and_cancel_do_not_touch_history(widget: Any) -> None:
    """Draft shortcuts cannot undo previously committed annotations."""
    original = _rect(widget)
    wf = widget.rectangle_creation
    before = len(widget.canvas.shapes_backups)
    wf.start_extreme()
    _click(widget, 50, 10)
    _click(widget, 80, 40)
    widget.undo_shape_edit()
    assert len(wf.draft.points) == 1
    _key(widget.canvas, QtCore.Qt.Key.Key_Escape)
    assert wf.draft is None
    assert widget.canvas.shapes == [original]
    assert len(widget.canvas.shapes_backups) == before


def test_label_cancel_retains_draft(
    widget: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancelled label dialog leaves no unlabeled shape or undo record."""
    wf = widget.rectangle_creation
    widget.digit_to_label = None
    widget.unique_label_list.clearSelection()
    monkeypatch.setattr(
        widget.label_dialog,
        "pop_up",
        lambda *_a, **_k: (None, {}, None, "", False, []),
    )
    wf.start_extreme()
    before = len(widget.canvas.shapes_backups)
    for x, y in [(50, 10), (80, 40), (60, 90), (20, 45)]:
        _click(widget, x, y)
    assert wf.draft.complete
    assert widget.canvas.shapes == []
    assert len(widget.canvas.shapes_backups) == before
    assert not widget.dirty
    widget.digit_to_label = "person"
    wf.submit_draft()
    assert len(widget.canvas.shapes) == 1


def test_draft_zoom_preserves_original_coordinates(widget: Any) -> None:
    """Pointer-local zoom preserves accepted boundary coordinates."""
    wf = widget.rectangle_creation
    wf.start_extreme()
    _click(widget, 50, 10)
    _click(widget, 80, 40)
    points = list(wf.draft.points)
    widget.canvas.scale = 2.0
    widget.canvas.update()
    assert wf.draft.points == points
    assert not widget.dirty


def test_continue_draw_uses_same_label(widget: Any) -> None:
    """A new draft is explicit and reuses the last successful label."""
    _draw(widget)
    wf = widget.rectangle_creation
    wf.continue_drawing()
    assert wf.draft is not None and not wf.draft.points
    assert widget.digit_to_label == "person"
    assert len(widget.canvas.shapes) == 1


def test_save_reload_ordinary_rectangle(widget: Any, tmp_path: Path) -> None:
    """Saved output contains the final rectangle and no temporary points."""
    shape = _draw(widget)
    shape_id = shape.xanylabeling_shape_id
    widget.canvas.begin_rect_click_axis("x")
    _click(widget, 79, 40)
    path = tmp_path / "image.json"
    assert widget.save_labels(str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["shapes"]) == 1
    saved = data["shapes"][0]
    assert saved["shape_type"] == "rectangle"
    assert saved["xanylabeling_shape_id"] == shape_id
    assert max(p[0] for p in saved["points"]) == pytest.approx(79)
    assert widget.load_file(str(tmp_path / "image.png"))
    assert len(widget.canvas.shapes) == 1
    assert widget.canvas.shapes[0].xanylabeling_shape_id == shape_id


def test_menu_tools_preserve_normal_creation(widget: Any) -> None:
    """Ordinary drawing works without an enable checkbox or fitting state."""
    widget.digit_to_label = "person"
    widget.toggle_draw_mode(edit=False, create_mode="rectangle")
    _click(widget, 20, 10)
    _click(widget, 80, 90)
    assert len(widget.canvas.shapes) == 1
    assert widget.canvas.shapes[0].label == "person"


def test_digit_dialog_preserves_method(widget: Any) -> None:
    """Page serialization retains both valid and unknown drawing methods."""
    from anylabeling.views.labeling.widgets.label_dialog import (
        DigitShortcutDialog,
    )

    widget.drawing_digit_shortcuts = {
        1: {
            "mode": "rectangle",
            "label": "person",
            "drawing_method": "four_extremes",
        },
        2: {"mode": "rectangle", "label": "head", "drawing_method": "future"},
    }
    dialog = DigitShortcutDialog(widget)
    dialog.save_current_page_data()
    assert dialog.digit_shortcuts[1]["drawing_method"] == "four_extremes"
    assert dialog.digit_shortcuts[2]["drawing_method"] == "future"
    assert dialog.digit_shortcuts[1]["mode"] == "rectangle"
    dialog.deleteLater()


def test_bound_two_points_preserves_pending(widget: Any) -> None:
    """Ordinary digit creation retains label and atomic binding context."""
    source = _rect(widget)
    widget._config["digit_shortcut_mode"] = "bind_draw"
    widget.drawing_digit_shortcuts = {
        1: {"mode": "rectangle", "label": "head"}
    }
    widget.create_digit_mode(1)
    assert widget.digit_to_label == "head"
    assert widget.digit_bind_draw_manager.pending is not None
    _click(widget, 30, 20)
    _click(widget, 60, 50)
    assert len(widget.canvas.shapes) == 2
    target = widget.canvas.shapes[-1]
    assert target.label == "head" and target.group_id == source.group_id
    assert isinstance(source.group_id, int)
    assert widget.rectangle_creation.draft is None


def test_bound_four_extremes_cancel_and_commit(widget: Any) -> None:
    """Canceled drafts leave source gid untouched; success commits the group."""
    source = _rect(widget)
    widget._config["digit_shortcut_mode"] = "bind_draw"
    widget.drawing_digit_shortcuts = {
        1: {
            "mode": "rectangle",
            "label": "head",
            "drawing_method": "four_extremes",
        }
    }
    wf = widget.rectangle_creation
    original_gid = source.group_id
    widget.create_digit_mode(1)
    assert wf.draft is not None
    wf.cancel()
    assert source.group_id == original_gid
    assert len(widget.canvas.shapes) == 1
    widget.canvas.select_shapes([source])
    widget.create_digit_mode(1)
    for x, y in ((50, 10), (80, 40), (60, 90), (20, 45)):
        _click(widget, x, y)
    assert len(widget.canvas.shapes) == 2
    target = widget.canvas.shapes[-1]
    assert target.label == "head" and target.group_id == source.group_id
    assert isinstance(source.group_id, int)
    assert wf.draft is None
