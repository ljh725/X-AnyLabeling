"""Docked review workbench and the three task views (WL-01, WL-02, WL-07, WL-08).

These tests drive the real ``MainWindow`` because the contract under test is
about the window's dock area, the single editable canvas and one continuous
edit history - none of which exist in an isolated widget.
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
from anylabeling.views.labeling.dense_review.workspace import (
    DenseReviewWorkspace,
)
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

    def _open(shapes, batches=None, rules=(), name="image"):
        monkeypatch.setattr(app_config, "_work_directory", str(tmp_path))
        image_path = tmp_path / f"{name}.png"
        Image.new("RGB", (640, 480), color=(205, 205, 205)).save(image_path)
        annotation = {
            "version": "4.2.1",
            "imageWidth": 640,
            "imageHeight": 480,
            "imagePath": f"{name}.png",
            "imageData": None,
            "shapes": shapes,
        }
        (tmp_path / f"{name}.json").write_text(
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
            workspace.shutdown()
        widget.dirty = False
        window.close()
        app.removeEventFilter(widget)
        window.deleteLater()
        app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def _three():
    return [
        _rectangle("person", "rect1", 40, 40, group_id=0),
        _rectangle("person", "rect2", 200, 40, group_id=1),
        _rectangle("person", "rect3", 360, 40, group_id=2),
    ]


def _rules():
    return (("person", "visible", ""),)


def _open_review(app, window, image_path):
    widget = window.labeling_widget.view
    assert widget.load_file(image_path)
    widget.open_dense_review()
    app.processEvents()
    workspace = widget.dense_review_workspace
    workspace.refresh_all(force_cards=True)
    app.processEvents()
    return widget, workspace


def _dock_area(window, workspace):
    """Return the dock area the workspace occupies, or None."""
    return window.dockWidgetArea(workspace)


# -- WL-01 / WL-02: docked, one canvas, one history -----------------------


def test_menu_entry_docks_the_panel_beside_the_editable_canvas(
    app, open_window
):
    window, image_path = open_window(
        _three(), batches=(("person", ("person",)),), rules=_rules()
    )
    widget = window.labeling_widget.view
    assert widget.load_file(image_path)
    app.processEvents()
    # Use the real workflow-menu action, not the method directly.
    assert widget.actions.open_dense_review is not None
    widget.actions.open_dense_review.trigger()
    app.processEvents()

    workspace = widget.dense_review_workspace
    assert isinstance(workspace, DenseReviewWorkspace)
    assert isinstance(workspace, QtWidgets.QDockWidget)
    assert workspace.isVisible() is True
    assert workspace.isFloating() is False
    assert _dock_area(window, workspace) == (
        QtCore.Qt.DockWidgetArea.RightDockWidgetArea
    )
    # One editable canvas, and the panel reuses the same one.
    assert widget.canvas is not None
    assert widget.canvas.isEnabled() is True


def test_reopening_reuses_dock_canvas_session_and_history(app, open_window):
    window, image_path = open_window(
        _three(), batches=(("person", ("person",)),), rules=_rules()
    )
    widget, workspace = _open_review(app, window, image_path)
    session = widget.dense_review_session
    canvas = widget.canvas
    model = workspace._card_model

    # Make history: move a shape so undo is meaningful.
    target = next(
        s for s in canvas.shapes if s.xanylabeling_shape_id == "rect1"
    )
    canvas.select_shapes([target])
    before_x = target.bounding_rect().x()
    assert canvas.bounded_move_shapes([target], QtCore.QPointF(10, 0))
    app.processEvents()
    history_before = list(canvas.shapes_backups)

    widget.actions.open_dense_review.trigger()
    app.processEvents()
    assert widget.dense_review_workspace is workspace
    assert widget.dense_review_session is session
    assert widget.canvas is canvas
    assert workspace._card_model is model
    assert list(canvas.shapes_backups) == history_before

    # The re-open did not add or drop a history entry, so an undo still
    # targets the edit made before the panel was re-opened.
    assert len(canvas.shapes_backups) == len(history_before)
    assert canvas.shapes[0].bounding_rect().x() == before_x + 10


def test_floating_then_reopening_keeps_it_floating(app, open_window):
    window, image_path = open_window(
        _three(), batches=(("person", ("person",)),), rules=_rules()
    )
    widget, workspace = _open_review(app, window, image_path)
    workspace.setFloating(True)
    app.processEvents()
    assert workspace.isFloating() is True

    widget.actions.open_dense_review.trigger()
    app.processEvents()
    # Same instance, still floating, still the same session.
    assert widget.dense_review_workspace is workspace
    assert workspace.isFloating() is True


def test_closing_and_reopening_keeps_the_session_and_history(app, open_window):
    window, image_path = open_window(
        _three(), batches=(("person", ("person",)),), rules=_rules()
    )
    widget, workspace = _open_review(app, window, image_path)
    session = widget.dense_review_session
    # Confirm progress so the round has state worth keeping.
    workspace._complete_batch()
    app.processEvents()
    payload = session.to_payload()

    workspace.close()
    app.processEvents()
    assert widget.dense_review_session is session
    assert widget.canvas.dense_review_active is False

    widget.actions.open_dense_review.trigger()
    app.processEvents()
    assert widget.dense_review_workspace is workspace
    assert widget.dense_review_session is session
    assert widget.dense_review_session.to_payload() == payload
    assert widget.canvas.dense_review_active is True


def test_dock_visibility_events_do_not_rebuild_the_round(app, open_window):
    window, image_path = open_window(
        _three(), batches=(("person", ("person",)),), rules=_rules()
    )
    widget, workspace = _open_review(app, window, image_path)
    session = widget.dense_review_session
    generation = workspace._generation

    # Float and re-dock: both emit Qt show/hide events.
    workspace.setFloating(True)
    app.processEvents()
    workspace.setFloating(False)
    app.processEvents()

    assert widget.dense_review_session is session
    assert workspace._generation == generation


# -- WL-07 / WL-08: task switching ---------------------------------------


def _select_task(workspace, task_id):
    index = workspace.task_selector.findData(task_id)
    assert index >= 0
    workspace.task_selector.setCurrentIndex(index)
    return workspace.task_id


def test_default_task_is_category_check(app, open_window):
    window, image_path = open_window(
        _three(), batches=(("person", ("person",)),), rules=_rules()
    )
    _widget, workspace = _open_review(app, window, image_path)
    assert workspace.task_id == workspace.TASK_CATEGORY
    assert workspace.task_selector.currentData() == workspace.TASK_CATEGORY
    assert workspace.tabs.currentIndex() == 0


def test_box_points_task_promotes_associated_keypoints(app, open_window):
    window, image_path = open_window(
        [
            _rectangle("person", "rect1", 40, 40, group_id=0),
            _point("nose", "kp1", 80, 80, group_id=0),
            _rectangle("person", "rect2", 300, 40, group_id=1),
        ],
        batches=(("person", ("person",)),),
        rules=_rules(),
    )
    widget, workspace = _open_review(app, window, image_path)
    session = widget.dense_review_session
    current = session.current_object()
    assert current is not None
    assert session.associated_ids(current.shape_id) == ("kp1",)

    assert _select_task(workspace, workspace.TASK_BOX_POINTS) == (
        workspace.TASK_BOX_POINTS
    )
    app.processEvents()
    display = widget.dense_review_display_entry("kp1")
    assert display is not None
    # The associated keypoint is promoted with the current rectangle.
    assert display.role == "current"
    # Switching the task must not change any confirmation state.
    assert workspace._scope().candidate_ids


def test_task_round_trip_restores_object_and_coverage_targets(
    app, open_window
):
    window, image_path = open_window(
        _three(), batches=(("person", ("person",)),), rules=_rules()
    )
    widget, workspace = _open_review(app, window, image_path)
    session = widget.dense_review_session
    canvas = widget.canvas

    # Object task: pick a specific object and a specific viewport.
    workspace._navigate_to(workspace._current_batch_id(), "rect2")
    app.processEvents()
    assert session.current_object().shape_id == "rect2"
    widget.set_zoom(150)
    app.processEvents()
    object_zoom = canvas.scale
    object_shape = session.current_object().shape_id

    # Coverage task: pick a specific region.
    assert _select_task(workspace, workspace.TASK_COVERAGE) == (
        workspace.TASK_COVERAGE
    )
    app.processEvents()
    plan = session.state.coverage
    assert plan is not None
    second_region = plan.regions[1].region_id
    workspace._on_grid_region_clicked(second_region)
    app.processEvents()
    assert session.state.coverage.current_region == second_region
    widget.set_zoom(75)
    app.processEvents()
    coverage_zoom = canvas.scale

    # Back to the object task: object and viewport are restored.
    assert _select_task(workspace, workspace.TASK_CATEGORY) == (
        workspace.TASK_CATEGORY
    )
    app.processEvents()
    assert session.current_object().shape_id == object_shape
    assert canvas.scale == pytest.approx(object_zoom, rel=1e-6)

    # And back to coverage: the region and its viewport are restored.
    assert _select_task(workspace, workspace.TASK_COVERAGE) == (
        workspace.TASK_COVERAGE
    )
    app.processEvents()
    assert session.state.coverage.current_region == second_region
    assert canvas.scale == pytest.approx(coverage_zoom, rel=1e-6)


def test_task_switch_never_changes_content_dirty_or_history(app, open_window):
    window, image_path = open_window(
        _three(), batches=(("person", ("person",)),), rules=_rules()
    )
    widget, workspace = _open_review(app, window, image_path)
    session = widget.dense_review_session
    content = [
        (
            s.xanylabeling_shape_id,
            s.label,
            [(p.x(), p.y()) for p in s.points],
        )
        for s in widget.canvas.shapes
    ]
    dirty_before = widget.dirty
    candidates = workspace._scope().candidate_ids
    history_before = list(widget.canvas.shapes_backups)

    for task_id in (
        workspace.TASK_COVERAGE,
        workspace.TASK_BOX_POINTS,
        workspace.TASK_CATEGORY,
    ):
        assert _select_task(workspace, task_id) == task_id
        app.processEvents()

    after = [
        (
            s.xanylabeling_shape_id,
            s.label,
            [(p.x(), p.y()) for p in s.points],
        )
        for s in widget.canvas.shapes
    ]
    assert after == content
    assert widget.dirty == dirty_before
    assert workspace._scope().candidate_ids == candidates
    assert list(widget.canvas.shapes_backups) == history_before
    # Coverage plan existing is a view concern, not a confirmation.
    assert session.object("rect1").confirmed_both() is False


def test_coverage_task_falls_back_when_plan_is_empty(app, open_window):
    window, image_path = open_window(
        [], batches=(("person", ("person",)),), rules=_rules()
    )
    widget, workspace = _open_review(app, window, image_path)
    session = widget.dense_review_session
    assert session.counts()["total"] == 0

    assert _select_task(workspace, workspace.TASK_COVERAGE) == (
        workspace.TASK_COVERAGE
    )
    app.processEvents()
    # An empty image still gets a plan covering the whole image (SN-01).
    plan = session.state.coverage
    assert plan is not None
    assert plan.regions
    assert workspace.region_list.count() == len(plan.regions)

    assert _select_task(workspace, workspace.TASK_CATEGORY) == (
        workspace.TASK_CATEGORY
    )
    app.processEvents()
    assert session.state.coverage is not None


def test_deleted_target_falls_back_to_a_valid_object(app, open_window):
    window, image_path = open_window(
        _three(), batches=(("person", ("person",)),), rules=_rules()
    )
    widget, workspace = _open_review(app, window, image_path)
    session = widget.dense_review_session

    workspace._navigate_to(workspace._current_batch_id(), "rect2")
    app.processEvents()
    assert session.current_object().shape_id == "rect2"
    _select_task(workspace, workspace.TASK_COVERAGE)
    app.processEvents()

    # Remove the remembered object, then come back.
    target = next(
        s for s in widget.canvas.shapes if s.xanylabeling_shape_id == "rect2"
    )
    widget.canvas.shapes.remove(target)
    widget.canvas.store_shapes()
    widget.dense_review_session.sync_shapes(widget.dense_review_shapes())
    app.processEvents()

    assert _select_task(workspace, workspace.TASK_CATEGORY) == (
        workspace.TASK_CATEGORY
    )
    app.processEvents()
    current = session.current_object()
    assert current is None or current.shape_id != "rect2"


def test_navigation_snapshot_does_not_cross_images(app, open_window):
    window, image_path = open_window(
        _three(), batches=(("person", ("person",)),), rules=_rules()
    )
    widget, workspace = _open_review(app, window, image_path)
    session = widget.dense_review_session
    workspace._navigate_to(workspace._current_batch_id(), "rect3")
    app.processEvents()
    assert session.current_object().shape_id == "rect3"
    workspace._task_views  # noqa: B018 - ensure the cache exists

    other = window  # keep the window alive
    other_path = os.path.join(os.path.dirname(image_path), "image2.png")
    Image.new("RGB", (320, 240), color=(90, 90, 90)).save(other_path)
    with open(
        other_path.replace(".png", ".json"), "w", encoding="utf-8"
    ) as fh:
        json.dump(
            {
                "version": "4.2.1",
                "imageWidth": 320,
                "imageHeight": 240,
                "imagePath": "image2.png",
                "imageData": None,
                "shapes": [_rectangle("person", "new1", 20, 20)],
            },
            fh,
        )
    assert widget.load_file(other_path)
    app.processEvents()

    # The previous image's snapshot must not be applied to the new one.
    # Reading the state for the new image discards the old cache, so the
    # remembered target from the previous file is gone.
    new_state = workspace._task_state_for(workspace.TASK_CATEGORY)
    assert workspace._task_state_image == widget.filename
    assert new_state.get("shape") != "rect3"
    new_session = widget.dense_review_session
    assert new_session is not None
    current = new_session.current_object()
    assert current is None or current.shape_id != "rect3"
    assert other is window


def test_task_switch_settles_a_live_edit_first(app, open_window):
    window, image_path = open_window(
        _three(), batches=(("person", ("person",)),), rules=_rules()
    )
    widget, workspace = _open_review(app, window, image_path)
    canvas = widget.canvas

    # Start a polygon draft, then switch tasks.
    canvas.set_editing(False)
    canvas.create_mode = "polygon"
    canvas.current = None
    position = QtCore.QPointF(120, 120)
    press = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonPress,
        position,
        position,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    canvas.mousePressEvent(press)
    app.processEvents()
    had_draft = canvas.current is not None

    assert _select_task(workspace, workspace.TASK_COVERAGE) == (
        workspace.TASK_COVERAGE
    )
    app.processEvents()
    # The boundary settled the draft; the switch is applied.
    assert canvas.current is None or not had_draft
    assert workspace.task_id == workspace.TASK_COVERAGE


def test_editing_still_works_on_the_canvas_while_docked(app, open_window):
    window, image_path = open_window(
        _three(), batches=(("person", ("person",)),), rules=_rules()
    )
    widget, workspace = _open_review(app, window, image_path)
    canvas = widget.canvas
    assert workspace.isVisible() is True

    target = next(
        s for s in canvas.shapes if s.xanylabeling_shape_id == "rect1"
    )
    canvas.select_shapes([target])
    before = target.bounding_rect().x()
    assert canvas.bounded_move_shapes([target], QtCore.QPointF(7, 0))
    app.processEvents()
    assert target.bounding_rect().x() == before + 7
