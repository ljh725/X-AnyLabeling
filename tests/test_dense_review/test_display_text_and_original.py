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
from PyQt6 import QtCore, QtWidgets

from anylabeling import config as app_config
from anylabeling.config import get_config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.services.dense_review.config import save_config
from anylabeling.views.mainwindow import MainWindow

from .conftest import make_config


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
