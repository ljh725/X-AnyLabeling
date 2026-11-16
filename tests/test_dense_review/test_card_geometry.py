"""Adjustable card image size and DPR-aware thumbnails.

The card image area has to be a user choice, not a constant: height is
controlled independently from the crop context, widening the panel only
changes the column count, and the crop target follows the device pixel ratio
(OC-07, OC-08, OC-09, OC-17, OC-18).
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


def _rectangle(label, shape_id, x, y, w=80, h=100):
    return {
        "label": label,
        "shape_type": "rectangle",
        "points": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
        "xanylabeling_shape_id": shape_id,
    }


@pytest.fixture
def app():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication(
        []
    )
    application.setQuitOnLastWindowClosed(False)
    return application


@pytest.fixture
def open_workspace(app, tmp_path, monkeypatch):
    windows = []

    def _open(count=12):
        monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
        image_path = tmp_path / "image.png"
        Image.new("RGB", (800, 600), color=(210, 210, 210)).save(image_path)
        shapes = [
            _rectangle(
                "person",
                f"id{index}",
                20 + (index % 4) * 180,
                20 + (index // 4) * 140,
            )
            for index in range(count)
        ]
        annotation = {
            "version": "4.2.1",
            "imageWidth": 800,
            "imageHeight": 600,
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
                batches=(("person", ("person",)),),
                rules=(("person", "visible", ""),),
            ),
        )
        config = get_config(str(tmp_path / "config.yaml"))
        window = MainWindow(app, config=config)
        window.resize(1600, 1000)
        window.show()
        app.processEvents()
        widget = window.labeling_widget.view
        assert widget.load_file(str(image_path))
        widget.open_dense_review()
        app.processEvents()
        workspace = widget.dense_review_workspace
        workspace.refresh_all()
        app.processEvents()
        windows.append(window)
        return widget, workspace

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


def test_card_image_height_defaults_to_320(app, open_workspace):
    _widget, workspace = open_workspace()
    assert workspace.DEFAULT_IMAGE_HEIGHT == 320
    assert workspace.card_image_height == 320
    assert workspace.image_height_slider.value() == 320
    # The cell is the image area plus the text band, not the old 176.
    cell = workspace.card_list.gridSize()
    assert cell.height() == 320 + workspace.CARD_TEXT_HEIGHT
    assert cell.height() != 176


@pytest.mark.parametrize("height", [160, 480, 640])
def test_card_image_height_is_adjustable(app, open_workspace, height):
    _widget, workspace = open_workspace()
    before_columns = _columns(workspace)
    workspace.image_height_slider.setValue(height)
    _events()
    assert workspace.card_image_height == height
    assert workspace.card_list.gridSize().height() == (
        height + workspace.CARD_TEXT_HEIGHT
    )
    # Growing the image area must not change how many cards fit per row.
    assert _columns(workspace) == before_columns


def test_card_image_height_is_clamped(app, open_workspace):
    _widget, workspace = open_workspace()
    workspace.set_card_image_height(10)
    assert workspace.card_image_height == workspace.MIN_IMAGE_HEIGHT
    workspace.set_card_image_height(5000)
    assert workspace.card_image_height == workspace.MAX_IMAGE_HEIGHT


def test_widening_changes_columns_but_keeps_height(app, open_workspace):
    _widget, workspace = open_workspace(count=24)
    workspace.set_card_image_height(480)
    height = workspace.card_image_height
    narrow = _columns(workspace)

    workspace.cards_panel.setMinimumWidth(1100)
    workspace.resize(1900, 1000)
    _events()
    workspace._relayout_cards()
    _events()

    assert workspace.card_image_height == height
    assert _columns(workspace) >= narrow


def test_context_change_keeps_the_selected_height(app, open_workspace):
    _widget, workspace = open_workspace()
    workspace.set_card_image_height(400)
    workspace.context_spin.setValue(80)
    workspace._on_context_changed()
    _events()
    # Context controls the crop, not the card size (OC-08).
    assert workspace.card_image_height == 400
    assert workspace.card_list.gridSize().height() == (
        400 + workspace.CARD_TEXT_HEIGHT
    )


def test_thumbnail_target_follows_size_and_dpr(app, open_workspace):
    _widget, workspace = open_workspace()
    workspace.set_card_image_height(320)
    base = workspace._thumbnail_target_pixels()
    assert base[1] == int(round(320 * workspace.devicePixelRatioF()))

    workspace.set_card_image_height(640)
    taller = workspace._thumbnail_target_pixels()
    assert taller[1] > base[1]

    # A 2x screen must request roughly twice the pixels, not the same crop.
    real_ratio = workspace.devicePixelRatioF
    try:
        workspace.devicePixelRatioF = lambda: 2.0
        doubled = workspace._thumbnail_target_pixels()
    finally:
        workspace.devicePixelRatioF = real_ratio
    assert doubled[1] == pytest.approx(640 * 2.0, abs=1)
    assert doubled[1] > taller[1]


def test_height_change_invalidates_cached_crops(app, open_workspace):
    _widget, workspace = open_workspace()
    workspace.set_card_image_height(320)
    first = workspace._thumbnail_target_pixels()
    key_a = workspace.thumbnails.request_key(
        "id0", 1, (0, 0, 10, 10), 0.35, first, "v1"
    )
    workspace.set_card_image_height(480)
    second = workspace._thumbnail_target_pixels()
    key_b = workspace.thumbnails.request_key(
        "id0", 1, (0, 0, 10, 10), 0.35, second, "v1"
    )
    # Size is part of the cache key, so a stale crop is never reused
    # (OC-17, OC-18).
    assert key_a != key_b


def _events():
    application = QtWidgets.QApplication.instance()
    if application is not None:
        application.processEvents()


def _columns(workspace) -> int:
    width = workspace.card_list.gridSize().width()
    viewport = workspace.card_list.viewport().width()
    if width <= 0:
        return 0
    return max(1, viewport // width)
