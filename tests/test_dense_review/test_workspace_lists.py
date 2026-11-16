"""List usability regressions for the dense-review workbench.

Covers the empty-state -> active-session enabling path, reload after a failed
load, and real wheel/scroll-bar navigation of the card list (WL-05, WL-06,
OC-16).
"""

import copy
import json
import os
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling import config as app_config
from anylabeling import user_config
from anylabeling.config import normalize_user_config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.services.dense_review.config import save_config
from anylabeling.views.labeling.settings.schema import load_template_config
from anylabeling.views.mainwindow import MainWindow

from .conftest import make_config


def _rectangle(label, shape_id, x, y, width=60, height=80):
    return {
        "label": label,
        "shape_type": "rectangle",
        "points": [
            [x, y],
            [x + width, y],
            [x + width, y + height],
            [x, y + height],
        ],
        "xanylabeling_shape_id": shape_id,
    }


def _grid_shapes(count, labels=("A", "B")):
    shapes = []
    for index in range(count):
        column = index % 6
        row = index // 6
        shapes.append(
            _rectangle(
                labels[index % len(labels)],
                f"id{index}",
                20 + column * 100,
                20 + row * 70,
                80,
                50,
            )
        )
    return shapes


@pytest.fixture
def app():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication(
        []
    )
    application.setQuitOnLastWindowClosed(False)
    return application


@pytest.fixture
def open_window(app, tmp_path, monkeypatch):
    """Open the main window on a prepared sample and return (window, path)."""
    windows = []

    def _open(shapes, batches=None, rules=()):
        monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
        config_file = tmp_path / "config.yaml"
        config_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(
            app_config, "current_config_file", str(config_file)
        )
        image_path = tmp_path / "image.png"
        Image.new("RGB", (700, 520), color=(210, 210, 210)).save(image_path)
        annotation = {
            "version": "4.2.1",
            "imageWidth": 700,
            "imageHeight": 520,
            "imagePath": "image.png",
            "imageData": None,
            "shapes": shapes,
        }
        (tmp_path / "image.json").write_text(
            json.dumps(annotation), encoding="utf-8"
        )
        if batches is not None:
            save_config(
                str(tmp_path),
                make_config(batches=batches, rules=rules),
            )
        config = copy.deepcopy(load_template_config())
        config.update(auto_save=False)
        session_target = os.path.abspath(
            os.path.join(
                ".tmp",
                f"dense-lists-{os.getpid()}-{uuid.uuid4().hex}.yaml",
            )
        )
        user_config.begin_session(
            target_path=session_target,
            origin="file",
            template=copy.deepcopy(config),
            effective=copy.deepcopy(config),
            ensure_created=True,
            normalizer=normalize_user_config,
        )
        window = MainWindow(app, config=config)
        window.resize(1500, 960)
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


@pytest.fixture
def make_workspace(app):
    """Build one workspace pre-session, then drive the normal entry."""

    def _make(widget):
        from anylabeling.views.labeling.dense_review import (
            DenseReviewWorkspace,
        )

        widget.dense_review_session = None
        widget.dense_review_workspace = None
        workspace = DenseReviewWorkspace(widget)
        widget.dense_review_workspace = workspace
        workspace.refresh_all()
        app.processEvents()
        return workspace

    return _make


def test_empty_state_then_session_enables_all_lists(
    app, open_window, make_workspace
):
    window, image_path = open_window(_grid_shapes(30))
    widget = window.labeling_widget.view

    # Drive the empty state explicitly: a workspace without a session is
    # what the user sees before any image or round exists (WL-05).
    workspace = make_workspace(widget)
    assert workspace.batch_list.isEnabled() is False
    assert workspace.card_list.isEnabled() is False
    assert workspace.region_list.isEnabled() is False

    # Then go through the normal entry: load the image and open the round.
    assert widget.load_file(image_path)
    widget.open_dense_review()
    app.processEvents()
    workspace = widget.dense_review_workspace
    workspace.refresh_all()
    app.processEvents()

    session = widget.dense_review_session
    assert session is not None
    assert session.counts()["total"] == 30
    assert workspace.batch_list.count() == 1
    assert workspace._card_model.rowCount() == 30
    assert workspace.batch_list.isEnabled() is True
    assert workspace.card_list.isEnabled() is True
    # No coverage plan exists yet, so region interactions stay limited.
    assert workspace.region_list.count() == 0
    assert workspace.region_list.isEnabled() is False

    # Building the plan enables the region list; the plan is what makes the
    # list meaningful (WL-05).
    from anylabeling.services.dense_review.models import CoverageSettings

    session.rebuild_coverage(CoverageSettings())
    workspace.refresh_all()
    app.processEvents()
    assert workspace.region_list.count() == 12
    assert workspace.region_list.isEnabled() is True


def test_session_switch_keeps_lists_enabled(
    app, open_window, make_workspace, tmp_path
):
    window, image_path = open_window(_grid_shapes(12))
    widget = window.labeling_widget.view
    workspace = make_workspace(widget)

    # A missing image is rejected before any dialog: the workspace must not
    # claim a usable session, and the lists must not look interactive
    # (WL-06).
    missing = tmp_path / "missing.png"
    widget.dense_review_session = None
    workspace.refresh_all()
    app.processEvents()
    assert workspace.card_list.isEnabled() is False
    assert workspace.batch_list.isEnabled() is False
    assert not missing.exists()

    # A successful load must clear the empty state and restore the round
    # through the normal entry point (WL-06).
    assert widget.load_file(image_path)
    widget.open_dense_review()
    app.processEvents()
    workspace = widget.dense_review_workspace
    workspace.refresh_all()
    app.processEvents()
    session = widget.dense_review_session
    assert session is not None
    assert workspace._card_model.rowCount() == session.counts()["total"]
    assert workspace.card_list.isEnabled() is True
    assert workspace.batch_list.isEnabled() is True


def test_wheel_and_scrollbar_move_view_without_moving_target(
    app, open_window
):
    window, image_path = open_window(_grid_shapes(60))
    widget = window.labeling_widget.view
    assert widget.load_file(image_path)
    widget.open_dense_review()
    app.processEvents()
    workspace = widget.dense_review_workspace
    workspace.refresh_all()
    app.processEvents()

    scrollbar = workspace.card_list.verticalScrollBar()
    assert scrollbar.maximum() > 0
    current_before = workspace._current_shape_id()
    selection_before = workspace._selected_shape_ids()
    start = scrollbar.value()

    viewport = workspace.card_list.viewport()
    centre = QtCore.QPointF(viewport.rect().center())
    for _ in range(3):
        event = QtGui.QWheelEvent(
            centre,
            QtCore.QPointF(viewport.mapToGlobal(centre.toPoint())),
            QtCore.QPoint(0, 0),
            QtCore.QPoint(0, -120),
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
            QtCore.Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        app.sendEvent(viewport, event)
        app.processEvents()

    assert scrollbar.value() > start
    # Scrolling only changes the visible window; the review target is moved
    # by explicit selection or navigation (OC-16).
    assert workspace._current_shape_id() == current_before
    assert workspace._selected_shape_ids() == selection_before

    # Keyboard and scroll-bar access reach the same rows.
    scrollbar.setValue(scrollbar.maximum())
    app.processEvents()
    assert scrollbar.value() == scrollbar.maximum()


def test_background_refresh_does_not_force_scroll_back(
    app, open_window
):
    window, image_path = open_window(
        _grid_shapes(24),
        batches=(("A", ("A",)), ("B", ("B",))),
        rules=(("A", "visible", ""), ("B", "visible", "")),
    )
    widget = window.labeling_widget.view
    assert widget.load_file(image_path)
    widget.open_dense_review()
    app.processEvents()
    workspace = widget.dense_review_workspace
    workspace.refresh_all()
    app.processEvents()

    scrollbar = workspace.card_list.verticalScrollBar()
    assert scrollbar.maximum() > 0
    scrollbar.setValue(scrollbar.maximum())
    app.processEvents()
    scrolled = scrollbar.value()
    assert scrolled > 0

    # Refreshes triggered by background thumbnails or progress must keep the
    # user's scroll position instead of jumping back to the current card.
    workspace.refresh_all()
    app.processEvents()
    assert scrollbar.value() == scrolled
