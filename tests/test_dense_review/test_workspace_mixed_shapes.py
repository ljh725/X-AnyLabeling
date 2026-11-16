"""Mixed rectangle + keypoint samples through the real window.

These tests use the ordinary application entry (``MainWindow`` with an
isolated config session) because the contract under test is the split between
"observable and editable" and "inside the formal review range": keypoints and
other unsupported shapes must stay fully usable while only rectangles can be
confirmed (PC-03, OC-01, OC-02, OC-03, OC-15).
"""

import copy
import json
import os
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PyQt6 import QtCore, QtWidgets

from anylabeling import config as app_config
from anylabeling import user_config
from anylabeling.config import get_config
from anylabeling.resources import resources  # noqa: F401
from anylabeling.services.dense_review.config import save_config
from anylabeling.views.mainwindow import MainWindow

from .conftest import make_config


def _rectangle(label, shape_id, x, y, w=80, h=100, group_id=None):
    data = {
        "label": label,
        "shape_type": "rectangle",
        "points": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
        "xanylabeling_shape_id": shape_id,
    }
    if group_id is not None:
        data["group_id"] = group_id
    return data


def _point(label, shape_id, x, y, group_id=None):
    data = {
        "label": label,
        "shape_type": "point",
        "points": [[x, y]],
        "xanylabeling_shape_id": shape_id,
    }
    if group_id is not None:
        data["group_id"] = group_id
    return data


def _polygon(label, shape_id, points):
    return {
        "label": label,
        "shape_type": "polygon",
        "points": points,
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
def open_window(app, tmp_path, monkeypatch):
    windows = []

    def _open(shapes, batches=None, rules=()):
        monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
        image_path = tmp_path / "image.png"
        Image.new("RGB", (640, 480), color=(200, 200, 200)).save(image_path)
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


def _open_review(app, window, image_path):
    widget = window.labeling_widget.view
    assert widget.load_file(image_path)
    widget.open_dense_review()
    app.processEvents()
    workspace = widget.dense_review_workspace
    workspace.refresh_all()
    app.processEvents()
    return widget, workspace


def test_keypoints_remain_observable_and_editable(app, open_window):
    """Points stay drawable/hittable while review stays rectangle-only."""
    shapes = [
        _rectangle("person", "rect1", 40, 40, group_id=0),
        _point("nose", "kp1", 80, 80, group_id=0),
        _point("hand", "kp2", 110, 120, group_id=0),
        _point("stray", "kp3", 400, 300),
        _polygon("lane", "poly1", [[300, 40], [420, 40], [420, 160]]),
    ]
    window, image_path = open_window(
        shapes,
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, workspace = _open_review(app, window, image_path)
    session = widget.dense_review_session
    assert session is not None

    canvas = widget.canvas
    displays = widget._dense_review_displays
    # Every object keeps its own identity in the ledger.
    assert set(displays) == {"rect1", "kp1", "kp2", "kp3", "poly1"}

    # Points and the polygon are fully observable and hittable.
    for shape_id in ("kp1", "kp2", "kp3", "poly1"):
        display = displays[shape_id]
        assert display.drawable is True, shape_id
        assert display.hittable is True, shape_id
        assert display.reviewable is False, shape_id
        shape = next(
            item
            for item in canvas.shapes
            if item.xanylabeling_shape_id == shape_id
        )
        assert canvas.dense_review_drawable(shape) is True
        assert canvas.dense_review_hittable(shape) is True

    # Only the rectangle is inside the formal review range.
    assert displays["rect1"].reviewable is True
    assert session.object("rect1").supported is True
    assert session.object("kp1").supported is False
    assert session.object("poly1").supported is False


def test_group_zero_associates_points_with_its_only_rectangle(
    app, open_window
):
    """Group 0 is a valid group and drives the keypoint association."""
    shapes = [
        _rectangle("person", "rect1", 40, 40, group_id=0),
        _point("nose", "kp1", 80, 80, group_id=0),
        _rectangle("person", "rect2", 300, 40, group_id=1),
        _point("arm", "kp2", 340, 80, group_id=1),
    ]
    window, image_path = open_window(
        shapes,
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, _workspace = _open_review(app, window, image_path)
    session = widget.dense_review_session

    assert session.object("rect1").group_id == 0
    assert session.associated_ids("rect1") == ("kp1",)
    assert session.associated_ids("rect2") == ("kp2",)
    # A point is never its own anchor.
    assert session.associated_ids("kp1") == ()


def test_ambiguous_group_does_not_guess_an_owner(app, open_window):
    """Two rectangles in one group leave the association unresolved."""
    shapes = [
        _rectangle("person", "rect1", 40, 40, group_id=3),
        _rectangle("person", "rect2", 300, 40, group_id=3),
        _point("nose", "kp1", 80, 80, group_id=3),
    ]
    window, image_path = open_window(
        shapes,
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, _workspace = _open_review(app, window, image_path)
    session = widget.dense_review_session
    # Neither rectangle claims the point; the card view surfaces the choice.
    assert session.associated_ids("rect1") == ()
    assert session.associated_ids("rect2") == ()
    # The point itself is still reachable and stays unsupported.
    assert session.object("kp1").supported is False


def test_ungrouped_point_is_not_associated(app, open_window):
    shapes = [
        _rectangle("person", "rect1", 40, 40, group_id=2),
        _point("loose", "kp1", 80, 80),
    ]
    window, image_path = open_window(
        shapes,
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, _workspace = _open_review(app, window, image_path)
    session = widget.dense_review_session
    assert session.associated_ids("rect1") == ()
    assert session.object("kp1").group_id is None


def test_batch_confirmation_never_confirms_keypoints(app, open_window):
    """Confirming the rectangle batch leaves every point pending."""
    shapes = [
        _rectangle("person", "rect1", 40, 40, group_id=0),
        _point("nose", "kp1", 80, 80, group_id=0),
    ]
    window, image_path = open_window(
        shapes,
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, workspace = _open_review(app, window, image_path)
    session = widget.dense_review_session

    workspace._complete_batch()
    app.processEvents()
    assert session.object("rect1").confirmed_both() is True
    point = session.object("kp1")
    assert point.confirmed_both() is False
    assert point.supported is False
    # The mixed image therefore stays partially reviewed (PC-04).
    completion = session.completion_status()
    assert completion.complete is False


def test_keypoint_can_still_be_edited_through_existing_commands(
    app, open_window
):
    """A keypoint keeps the ordinary move command despite review mode."""
    shapes = [
        _rectangle("person", "rect1", 40, 40, group_id=0),
        _point("nose", "kp1", 200, 200, group_id=0),
    ]
    window, image_path = open_window(
        shapes,
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, _workspace = _open_review(app, window, image_path)
    canvas = widget.canvas
    keypoint = next(
        item for item in canvas.shapes if item.xanylabeling_shape_id == "kp1"
    )
    canvas.select_shapes([keypoint])
    app.processEvents()
    before = QtCore.QPointF(keypoint.points[0])
    assert canvas.bounded_move_shapes([keypoint], QtCore.QPointF(10, 6))
    canvas.update()
    app.processEvents()
    after = keypoint.points[0]
    assert after.x() == pytest.approx(before.x() + 10)
    assert after.y() == pytest.approx(before.y() + 6)
    # The edit is a real content change, not a review-only state change.
    assert widget.dense_review_session.object("kp1").supported is False
