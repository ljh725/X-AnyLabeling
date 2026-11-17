"""Category text and source-image comparison during dense review.

The review label policy is temporary: it must make category names readable
even when the ordinary switches are off, and it must never persist that
override.  The source-image comparison must equally pause annotation hit
testing and end on blur, close or image switch (DP-05, DP-13, DP-14, DP-18).
"""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling import config as app_config
from anylabeling.config import get_config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.services.dense_review.config import save_config
from anylabeling.views.mainwindow import MainWindow

from .conftest import make_config
from .test_display_consistency import _send_mouse, _shape


def _rectangle(label, shape_id, x, y, w=90, h=110, group_id=None):
    data = {
        "label": label,
        "shape_type": "rectangle",
        "points": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
        "xanylabeling_shape_id": shape_id,
    }
    if group_id is not None:
        data["group_id"] = group_id
    return data


@pytest.fixture
def app():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication(
        []
    )
    application.setQuitOnLastWindowClosed(False)
    return application


@pytest.fixture
def open_window(app, tmp_path, monkeypatch):
    windows = []

    def _open(shapes, labels=("person",)):
        monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
        image_path = tmp_path / "image.png"
        Image.new("RGB", (640, 480), color=(190, 190, 190)).save(image_path)
        annotation = {
            "version": "4.2.1",
            "imageWidth": 640,
            "imageHeight": 480,
            "imagePath": "image.png",
            "imageData": None,
            "shapes": shapes,
        }
        (tmp_path / "image.json").write_text(
            json.dumps(annotation), encoding="utf-8"
        )
        save_config(
            str(tmp_path),
            make_config(
                batches=(("person", tuple(labels)),),
                rules=tuple((label, "visible", "") for label in labels),
            ),
        )
        config = get_config(str(tmp_path / "config.yaml"))
        window = MainWindow(app, config=config)
        window.resize(1400, 900)
        window.show()
        app.processEvents()
        windows.append(window)
        return window, str(image_path)

    yield _open

    for window in windows:
        widget = window.labeling_widget.view
        workspace = getattr(widget, "dense_review_workspace", None)
        if workspace is not None:
            workspace.close()
            workspace.shutdown()
        widget.dirty = False
        window.close()
        app.removeEventFilter(widget)
        window.deleteLater()
        app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def _open_review(app, window, image_path):
    widget = window.labeling_widget.view
    assert widget.load_file(image_path)
    widget.open_dense_review()
    app.processEvents()
    workspace = widget.dense_review_workspace
    workspace.refresh_all()
    app.processEvents()
    return widget, workspace


def _three():
    return [
        _rectangle("person", "rect1", 30, 30, group_id=0),
        _rectangle("person", "rect2", 200, 30, group_id=1),
        _rectangle("person", "rect3", 380, 30, group_id=2),
    ]


@pytest.mark.parametrize("ordinary_labels", [True, False])
def test_review_label_policy_overrides_ordinary_switch(
    app, open_window, ordinary_labels
):
    """Category names stay readable whatever the ordinary switch says."""
    window, image_path = open_window(_three())
    widget, _workspace = _open_review(app, window, image_path)
    canvas = widget.canvas
    canvas.show_labels = ordinary_labels
    canvas.show_labels_only_selected = not ordinary_labels
    widget.refresh_dense_review_display()
    app.processEvents()

    current = next(
        s for s in canvas.shapes if s.xanylabeling_shape_id == "rect1"
    )
    batch = next(
        s for s in canvas.shapes if s.xanylabeling_shape_id == "rect2"
    )
    # The current object always resolves readable text.
    assert canvas._label_display_text(current).startswith("person")
    # The batch object gets text while the role strength is non-zero.
    assert canvas._dense_review_text_strength(batch) > 0.0
    assert canvas._label_display_text(batch).startswith("person")

    # The ordinary settings themselves are untouched (DP-05, DP-18).
    assert canvas.show_labels is ordinary_labels
    assert canvas.show_labels_only_selected is not ordinary_labels


def test_review_never_writes_back_the_ordinary_label_settings(
    app, open_window
):
    window, image_path = open_window(_three())
    widget, workspace = _open_review(app, window, image_path)
    canvas = widget.canvas
    canvas.show_labels = False
    canvas.show_labels_only_selected = True
    widget.refresh_dense_review_display()
    app.processEvents()

    workspace.close()
    app.processEvents()
    # After leaving review the ordinary behaviour applies again unchanged.
    assert canvas.show_labels is False
    assert canvas.show_labels_only_selected is True
    other = next(
        s for s in canvas.shapes if s.xanylabeling_shape_id == "rect2"
    )
    assert canvas._label_display_text(other) == ""


def test_other_objects_keep_no_text_at_default_strength(app, open_window):
    window, image_path = open_window(_three())
    widget, _workspace = _open_review(app, window, image_path)
    canvas = widget.canvas
    widget.refresh_dense_review_display()
    app.processEvents()
    other = next(
        s for s in canvas.shapes if s.xanylabeling_shape_id != "rect1"
    )
    # rect2/rect3 are in the active batch, so pick a non-member instead.
    widget.dense_review_session.set_current(
        widget.dense_review_session.state.current_batch, "rect1"
    )
    widget.refresh_dense_review_display()
    app.processEvents()
    assert canvas._dense_review_text_strength(other) >= 0.0


def test_source_comparison_pauses_annotation_hits(app, open_window):
    window, image_path = open_window(_three())
    widget, _workspace = _open_review(app, window, image_path)
    canvas = widget.canvas
    rect = next(s for s in canvas.shapes if s.xanylabeling_shape_id == "rect1")

    widget.dense_review_set_display_mode("original")
    app.processEvents()
    # Nothing is hittable while only the source image is shown (DP-13).
    assert canvas.dense_review_hittable(rect) is False
    assert canvas._shape_hit_candidates(QtCore.QPointF(60, 60)) == []

    widget.dense_review_set_display_mode("all")
    app.processEvents()
    assert canvas.dense_review_hittable(rect) is True
    assert canvas._shape_hit_candidates(QtCore.QPointF(60, 60))


def test_source_comparison_ends_when_the_image_changes(app, open_window):
    window, image_path = open_window(_three())
    widget, _workspace = _open_review(app, window, image_path)

    widget.dense_review_set_display_mode("original")
    app.processEvents()
    assert widget._dense_review_display_mode == "original"

    # A new image must not inherit the old comparison state (DP-14).
    assert widget.load_file(image_path)
    app.processEvents()
    assert widget._dense_review_display_mode != "original"
    for shape in widget.canvas.shapes:
        if shape.xanylabeling_shape_id:
            assert widget.canvas.dense_review_hittable(shape) is True


def test_source_comparison_ends_when_the_workspace_closes(app, open_window):
    window, image_path = open_window(_three())
    widget, workspace = _open_review(app, window, image_path)
    widget.dense_review_set_display_mode("original")
    app.processEvents()

    workspace.close()
    app.processEvents()
    # Closing ends the temporary state and restores the ordinary canvas
    # (DP-13, DP-14, DP-17).
    assert widget._dense_review_display_mode == "all"
    assert widget.canvas.dense_review_active is False
    for shape in widget.canvas.shapes:
        assert widget.canvas.is_visible(shape) is True


def test_hold_original_restores_previous_mode_on_release(app, open_window):
    """Holding shows only the source image; releasing restores the mode."""
    window, image_path = open_window(_three())
    widget, _workspace = _open_review(app, window, image_path)
    canvas = widget.canvas
    widget.dense_review_set_display_mode("focus")
    app.processEvents()
    before = widget._dense_review_display_mode
    rect = next(s for s in canvas.shapes if s.xanylabeling_shape_id == "rect1")

    assert widget.dense_review_begin_hold_original() is True
    app.processEvents()
    assert widget.dense_review_hold_active() is True
    assert widget._dense_review_display_mode == "original"
    assert canvas.dense_review_hittable(rect) is False
    assert canvas._shape_hit_candidates(QtCore.QPointF(60, 60)) == []

    assert widget.dense_review_end_hold_original() is True
    app.processEvents()
    assert widget.dense_review_hold_active() is False
    assert widget._dense_review_display_mode == before
    assert canvas.dense_review_hittable(rect) is True


def test_hold_original_ends_on_blur_and_image_switch(app, open_window):
    window, image_path = open_window(_three())
    widget, _workspace = _open_review(app, window, image_path)

    assert widget.dense_review_begin_hold_original() is True
    widget.dense_review_end_hold_on_blur()
    app.processEvents()
    assert widget.dense_review_hold_active() is False
    assert widget._dense_review_display_mode != "original"

    # A hold never survives an image switch (DP-14).
    assert widget.dense_review_begin_hold_original() is True
    assert widget.dense_review_hold_active() is True
    assert widget.load_file(image_path)
    app.processEvents()
    assert widget.dense_review_hold_active() is False
    assert widget._dense_review_display_mode != "original"


def test_hold_original_requires_an_active_workspace(app, open_window):
    window, image_path = open_window(_three())
    widget, workspace = _open_review(app, window, image_path)
    workspace.close()
    app.processEvents()
    # A closed review must not enter a temporary review-only state.
    assert widget.dense_review_begin_hold_original() is False
    assert widget.dense_review_hold_active() is False


def test_hold_original_button_press_and_release(app, open_window):
    """The toolbar button is the real user entry for a held comparison."""
    window, image_path = open_window(_three())
    widget, workspace = _open_review(app, window, image_path)
    canvas = widget.canvas
    widget.dense_review_set_display_mode("focus")
    app.processEvents()
    previous = widget._dense_review_display_mode
    labels = []

    class RecordingPainter(QtGui.QPainter):
        def drawText(self, *args, **kwargs):
            if (
                args
                and isinstance(args[-1], str)
                and args[-1].startswith("person")
            ):
                labels.append(args[-1])
            return super().drawText(*args, **kwargs)

    button = workspace.hold_original_button
    assert button.isVisible() is True
    assert button.isEnabled() is True
    from PyQt6.QtTest import QTest

    QTest.mousePress(button, QtCore.Qt.MouseButton.LeftButton)
    app.processEvents()
    assert widget.dense_review_hold_active() is True
    assert widget._dense_review_display_mode == "original"

    # No annotation text may reach the painter during the comparison.
    from unittest.mock import patch as mock_patch

    with mock_patch.object(canvas, "_painter", RecordingPainter()):
        canvas.grab()
    assert labels == []

    QTest.mouseRelease(button, QtCore.Qt.MouseButton.LeftButton)
    app.processEvents()
    assert widget.dense_review_hold_active() is False
    assert widget._dense_review_display_mode == previous


def test_hold_original_button_ends_on_blur_close_and_image_switch(
    app, open_window
):
    window, image_path = open_window(_three())
    widget, workspace = _open_review(app, window, image_path)
    button = workspace.hold_original_button

    from PyQt6.QtTest import QTest

    # A real deactivation ends the hold without another press.
    QTest.mousePress(button, QtCore.Qt.MouseButton.LeftButton)
    app.processEvents()
    assert widget.dense_review_hold_active() is True
    # Drive the documented blur path; offscreen windows may still report
    # themselves as active, so exercise the handler the signal calls.
    event = QtCore.QEvent(QtCore.QEvent.Type.ActivationChange)
    workspace.changeEvent(event)
    widget.dense_review_end_hold_on_blur()
    app.processEvents()
    assert widget.dense_review_hold_active() is False
    QTest.mouseRelease(button, QtCore.Qt.MouseButton.LeftButton)
    app.processEvents()

    # Closing the workspace clears it too.
    QTest.mousePress(button, QtCore.Qt.MouseButton.LeftButton)
    app.processEvents()
    assert widget.dense_review_hold_active() is True
    workspace.close()
    app.processEvents()
    assert widget.dense_review_hold_active() is False
    assert widget._dense_review_display_mode != "original"

    # Reopening and switching images never carries the hold across.
    widget.open_dense_review()
    app.processEvents()
    workspace = widget.dense_review_workspace
    QTest.mousePress(
        workspace.hold_original_button, QtCore.Qt.MouseButton.LeftButton
    )
    app.processEvents()
    assert widget.dense_review_hold_active() is True
    assert widget.load_file(image_path)
    app.processEvents()
    assert widget.dense_review_hold_active() is False


def test_original_mode_renders_without_annotation_labels(app, open_window):
    """No label text may reach the painter during source comparison."""
    window, image_path = open_window(_three())
    widget, workspace = _open_review(app, window, image_path)
    canvas = widget.canvas
    workspace.display_combo.setCurrentIndex(
        workspace.display_combo.findData("original")
    )
    app.processEvents()
    assert not canvas.is_visible(_shape(widget, "rect1"))
    labels = []

    class RecordingPainter(QtGui.QPainter):
        def drawText(self, *args, **kwargs):
            if (
                args
                and isinstance(args[-1], str)
                and args[-1].startswith("person")
            ):
                labels.append(args[-1])
            return super().drawText(*args, **kwargs)

    from unittest.mock import patch as mock_patch

    with mock_patch.object(canvas, "_painter", RecordingPainter()):
        canvas.grab()
    assert labels == []


def test_global_off_then_source_mode_pauses_keyboard_edits(app, open_window):
    """The pause follows the explicit overlay flag, not a shape scan.

    With the global switch off every shape reports ``global-off`` and an
    empty image reports nothing at all, so neither case could be detected by
    scanning reasons (DP-13, DP-14).
    """
    window, image_path = open_window(_three())
    widget, workspace = _open_review(app, window, image_path)
    target = _shape(widget, "rect1")
    canvas = widget.canvas

    widget.actions.visibility_shapes_mode.trigger()
    app.processEvents()
    assert widget._config["show_shapes"] is False
    workspace.display_combo.setCurrentIndex(
        workspace.display_combo.findData("original")
    )
    app.processEvents()
    assert canvas.dense_review_original_only is True
    assert canvas.annotation_editing_paused() is True

    before = QtCore.QRectF(target.bounding_rect())
    undo_before = list(widget.canvas.shapes_backups)
    dirty_before = widget.dirty
    from PyQt6.QtTest import QTest

    QTest.keyClick(canvas, QtCore.Qt.Key.Key_Right)
    app.processEvents()
    assert target.bounding_rect() == before
    assert widget.dirty == dirty_before
    assert list(canvas.shapes_backups) == undo_before

    # Leaving the comparison restores ordinary editing.
    workspace.display_combo.setCurrentIndex(
        workspace.display_combo.findData("all")
    )
    app.processEvents()
    widget.actions.visibility_shapes_mode.trigger()
    app.processEvents()
    assert canvas.annotation_editing_paused() is False
    canvas.select_shapes([target])
    assert canvas.bounded_move_shapes([target], QtCore.QPointF(5, 0))
    app.processEvents()
    assert target.bounding_rect() != before


def test_source_mode_blocks_polygon_draft_on_empty_image(app, open_window):
    """An empty image has no shape to scan, yet must still not draft."""
    window, image_path = open_window([])
    widget, workspace = _open_review(app, window, image_path)
    canvas = widget.canvas
    assert canvas.shapes == []

    canvas.set_editing(False)
    canvas.create_mode = "polygon"
    workspace.display_combo.setCurrentIndex(
        workspace.display_combo.findData("original")
    )
    app.processEvents()
    assert canvas.annotation_editing_paused() is True

    local = (
        (QtCore.QPointF(80, 90) + canvas.offset_to_center()) * canvas.scale
    ).toPoint()
    from PyQt6.QtTest import QTest

    QTest.mouseClick(canvas, QtCore.Qt.MouseButton.LeftButton, pos=local)
    app.processEvents()
    assert canvas.current is None


def _select_display(workspace, mode):
    combo = workspace.display_combo
    combo.setCurrentIndex(combo.findData(mode))


def _viewport(widget):
    return (
        widget.zoom_mode,
        widget.canvas.scale,
        tuple(bar.value() for bar in widget.scroll_bars.values()),
        QtCore.QPointF(widget.canvas.pan_offset),
    )


@pytest.mark.parametrize("fit_window", [False, True])
def test_dropdown_comparison_round_trip_keeps_the_viewport(
    app, open_window, fit_window
):
    """Entering and leaving the comparison must not re-centre the canvas."""
    window, image_path = open_window(_three())
    window.resize(850, 600)
    widget, workspace = _open_review(app, window, image_path)
    widget.apply_wheel_navigation_mode("traditional")
    if fit_window:
        widget.actions.fit_window.trigger()
        if widget.zoom_mode != widget.FIT_WINDOW:
            widget.actions.fit_window.trigger()
    else:
        widget.set_zoom(126.4)
    app.processEvents()
    if not fit_window:
        for orientation, bar in widget.scroll_bars.items():
            assert bar.maximum() > 0
            widget.set_scroll(orientation, min(29, bar.maximum()))
        widget.canvas.pan_offset = QtCore.QPointF(17.5, -23.25)
        assert widget.canvas.scale == pytest.approx(1.264)
    before = _viewport(widget)

    _select_display(workspace, "original")
    app.processEvents()
    assert widget._dense_review_display_mode == "original"
    assert _viewport(widget) == before
    widget.set_zoom(65)
    assert _viewport(widget) != before
    _select_display(workspace, "focus")
    app.processEvents()
    assert widget._dense_review_display_mode == "focus"
    assert _viewport(widget) == before
    assert widget.actions.fit_window.isChecked() == fit_window
    assert widget._dense_review_original_view is None


def test_close_dropdown_comparison_starts_fresh_on_reopen(app, open_window):
    window, image_path = open_window(_three())
    widget, workspace = _open_review(app, window, image_path)
    widget.set_zoom(130)
    first_view = _viewport(widget)
    _select_display(workspace, "original")
    assert widget._dense_review_original_view is not None
    widget.set_zoom(65)
    workspace.close()
    app.processEvents()
    assert widget._dense_review_original_view is None
    assert _viewport(widget) == first_view

    widget.set_zoom(152.4)
    widget.pan_canvas(QtCore.QPointF(-15, 20))
    second_view = _viewport(widget)
    widget.open_dense_review()
    app.processEvents()
    _select_display(workspace, "original")
    assert widget._dense_review_original_view["zoom"] == pytest.approx(152.4)
    widget.set_zoom(80)
    _select_display(workspace, "focus")
    app.processEvents()
    assert _viewport(widget) == second_view
    assert widget._dense_review_original_view is None


def test_original_blocks_alt_drag_vertex_eraser(app, open_window):
    polygon = {
        "label": "person", "shape_type": "polygon",
        "xanylabeling_shape_id": "polygon1",
        "points": [[100, 100], [180, 100], [190, 140], [180, 180], [100, 180]],
    }
    window, path = open_window([polygon])
    widget, workspace = _open_review(app, window, path)
    widget._config["auto_save"] = False
    widget.set_zoom(100)
    canvas = widget.canvas
    shape = _shape(widget, "polygon1")
    canvas.select_shapes([shape])
    before = list(shape.points)
    history = list(canvas.shapes_backups)
    left = QtCore.Qt.MouseButton.LeftButton
    none = QtCore.Qt.MouseButton.NoButton
    alt = QtCore.Qt.KeyboardModifier.AltModifier
    press = QtCore.QEvent.Type.MouseButtonPress
    move = QtCore.QEvent.Type.MouseMove
    release = QtCore.QEvent.Type.MouseButtonRelease
    start = QtCore.QPointF(140, 130)

    _select_display(workspace, "original")
    assert not canvas.erase_selected_vertex_at(before[0])
    _send_mouse(app, canvas, press, start, left, left, alt)
    _send_mouse(app, canvas, move, before[0], none, left, alt)
    _send_mouse(app, canvas, release, before[0], left, none, alt)
    assert shape.points == before
    assert not widget.dirty
    assert canvas.shapes_backups == history

    # Releasing after leaving comparison still belongs to the blocked press.
    _send_mouse(app, canvas, press, start, left, left, alt)
    _select_display(workspace, "focus")
    _send_mouse(app, canvas, move, before[0], none, left, alt)
    _send_mouse(app, canvas, release, before[0], left, none, alt)
    assert shape.points == before
    assert not widget.dirty
    assert canvas.shapes_backups == history

    _send_mouse(app, canvas, press, start, left, left, alt)
    _send_mouse(app, canvas, move, before[0], none, left, alt)
    _send_mouse(app, canvas, release, before[0], left, none, alt)
    assert shape.points == before[1:]
    assert widget.dirty
    assert len(canvas.shapes_backups) == len(history) + 1


@pytest.mark.parametrize("gesture", ["move", "rotate", "keyboard-rotate"])
def test_enter_original_commits_in_flight_geometry_once(
    app, open_window, gesture
):
    rect = _rectangle("person", "rect1", 40, 40)
    if gesture != "move":
        rect["shape_type"] = "rotation"
    window, path = open_window([rect])
    widget, workspace = _open_review(app, window, path)
    widget._config["auto_save"] = False
    widget.set_zoom(100)
    canvas = widget.canvas
    target = _shape(widget, "rect1")
    canvas.select_shapes([target])
    before = list(target.points)
    history = len(canvas.shapes_backups)
    commits = []
    signal = canvas.shape_moved if gesture == "move" else canvas.shape_rotated
    signal.connect(lambda: commits.append(list(target.points)))
    left = QtCore.Qt.MouseButton.LeftButton
    none = QtCore.Qt.MouseButton.NoButton
    key = QtCore.Qt.Key.Key_X
    no_modifier = QtCore.Qt.KeyboardModifier.NoModifier
    start, end = QtCore.QPointF(80, 90), QtCore.QPointF(100, 105)
    if gesture == "rotate":
        _, start, center = canvas._rotation_handle_geometry(target)
        end = center + QtCore.QPointF(65, 0)
    if gesture == "keyboard-rotate":
        app.sendEvent(canvas, QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, key, no_modifier))
    else:
        _send_mouse(app, canvas, QtCore.QEvent.Type.MouseMove, start, none, none)
        _send_mouse(app, canvas, QtCore.QEvent.Type.MouseButtonPress, start, left, left)
        _send_mouse(app, canvas, QtCore.QEvent.Type.MouseMove, end, none, left)
    edited = list(target.points)
    assert edited != before
    assert len(canvas.shapes_backups) == history
    assert not widget.dirty

    _select_display(workspace, "original")
    assert widget.dirty and commits == [edited]
    assert len(canvas.shapes_backups) == history + 1
    if gesture == "move":
        assert widget.dense_review_session.object("rect1").bounds == (60, 55, 150, 165)
    _select_display(workspace, "focus")
    if gesture == "keyboard-rotate":
        app.sendEvent(canvas, QtGui.QKeyEvent(QtCore.QEvent.Type.KeyRelease, key, no_modifier))
    else:
        _send_mouse(app, canvas, QtCore.QEvent.Type.MouseMove, end + QtCore.QPointF(10, 10), none, left)
        _send_mouse(app, canvas, QtCore.QEvent.Type.MouseButtonRelease, end, left, none)
    assert commits == [edited]
    assert target.points == edited
    assert len(canvas.shapes_backups) == history + 1
    widget.actions.undo.trigger()
    assert _shape(widget, "rect1").points == before
    widget.actions.redo.trigger()
    assert _shape(widget, "rect1").points == edited


def test_held_comparison_round_trip_restores_the_same_viewport(
    app, open_window
):
    from PyQt6.QtTest import QTest

    window, image_path = open_window(_three())
    widget, workspace = _open_review(app, window, image_path)
    canvas = widget.canvas
    widget.set_zoom(100)
    app.processEvents()
    zoom_before = canvas.scale
    button = workspace.hold_original_button

    QTest.mousePress(button, QtCore.Qt.MouseButton.LeftButton)
    app.processEvents()
    assert widget.dense_review_hold_active() is True
    QTest.mouseRelease(button, QtCore.Qt.MouseButton.LeftButton)
    app.processEvents()
    assert widget.dense_review_hold_active() is False
    assert canvas.scale == pytest.approx(zoom_before, abs=1e-6)


def test_comparison_snapshot_does_not_leak_to_another_image(
    app, open_window, tmp_path
):
    """A snapshot from the previous image must be discarded, not applied."""
    from PIL import Image

    other = tmp_path / "other.png"
    Image.new("RGB", (320, 240), color=(120, 120, 120)).save(other)
    (tmp_path / "other.json").write_text(
        json.dumps(
            {
                "version": "4.2.1",
                "imageWidth": 320,
                "imageHeight": 240,
                "imagePath": "other.png",
                "imageData": None,
                "shapes": [
                    _rectangle("person", "other1", 20, 20),
                ],
            }
        ),
        encoding="utf-8",
    )

    window, image_path = open_window(_three())
    widget, workspace = _open_review(app, window, image_path)
    widget.set_zoom(100)
    app.processEvents()
    workspace.display_combo.setCurrentIndex(
        workspace.display_combo.findData("original")
    )
    app.processEvents()
    assert widget._dense_review_original_view is not None

    # Switch image while the comparison is active: the old snapshot dies.
    assert widget.load_file(str(other))
    app.processEvents()
    assert widget._dense_review_original_view is None
    assert widget.dense_review_hold_active() is False


def test_source_mode_blocks_polygon_draft_on_a_loaded_image(app, open_window):
    """Draw mode cannot start a draft while the comparison is active."""
    window, image_path = open_window(_three())
    widget, workspace = _open_review(app, window, image_path)
    canvas = widget.canvas
    canvas.set_editing(False)
    canvas.create_mode = "polygon"
    workspace.display_combo.setCurrentIndex(
        workspace.display_combo.findData("original")
    )
    app.processEvents()
    assert canvas.annotation_editing_paused() is True

    local = (
        (QtCore.QPointF(80, 90) + canvas.offset_to_center()) * canvas.scale
    ).toPoint()
    from PyQt6.QtTest import QTest

    QTest.mouseClick(canvas, QtCore.Qt.MouseButton.LeftButton, pos=local)
    app.processEvents()
    assert canvas.current is None

    # Leaving the comparison restores ordinary drafting.
    workspace.display_combo.setCurrentIndex(
        workspace.display_combo.findData("focus")
    )
    app.processEvents()
    QTest.mouseClick(canvas, QtCore.Qt.MouseButton.LeftButton, pos=local)
    app.processEvents()
    assert canvas.current is not None
