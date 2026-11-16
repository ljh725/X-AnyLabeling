"""A group-only edit must reach the ledger immediately.

``ObjectReviewState.group_id`` feeds the keypoint-to-rectangle association, and
a pure regrouping changes neither the category nor the geometry signature.
These regressions pin the change detection so the association and the display
role follow the live data (OC-06, PC-11).
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
from anylabeling.views.labeling.shape import Shape  # noqa: F401
from anylabeling.views.mainwindow import MainWindow

from .conftest import make_config
from .test_display_consistency import (
    _open_review,
    _point,
    _rectangle,
    _shape,
)


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

    def _open(shapes, batches=None, rules=()):
        monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
        image_path = tmp_path / "image.png"
        Image.new("RGB", (640, 480), color=(205, 205, 205)).save(image_path)
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
        if batches is not None:
            save_config(
                str(tmp_path), make_config(batches=batches, rules=rules)
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


def test_pure_group_edit_updates_association_immediately(app, open_window):
    """A group-only change has to reach the ledger (OC-06, PC-11)."""
    window, image_path = open_window(
        [
            _rectangle("person", "rect1", 40, 40, group_id=0),
            _point("nose", "kp1", 55, 55, group_id=0),
        ],
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, _workspace = _open_review(app, window, image_path)
    session = widget.dense_review_session
    assert session.associated_ids("rect1") == ("kp1",)

    widget._apply_field_patch(
        [_shape(widget, "kp1")], {"group_id": 1}, {"group_id"}
    )
    app.processEvents()
    assert _shape(widget, "kp1").group_id == 1
    # Group 0 stays valid for the rectangle, but it no longer owns the point.
    assert session.associated_ids("rect1") == ()
    assert session.object("kp1").group_id == 1

    # Removing the group detaches it as well.
    widget._apply_field_patch(
        [_shape(widget, "kp1")], {"group_id": None}, {"group_id"}
    )
    app.processEvents()
    assert session.object("kp1").group_id is None
    assert session.associated_ids("rect1") == ()
