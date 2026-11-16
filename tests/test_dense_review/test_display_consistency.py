"""One display decision must drive paint, hit testing and the edit target.

These tests run the real window because the contract spans the panel, the
canvas overlay and the ordinary labelling state: a manual hide or filter must
survive the review, an explicit temporary show must lift only the exact
object's visibility without touching its confirmation eligibility, and
closing the review has to recompute from the user's latest settings instead of
a stale entry snapshot (DP-09..DP-12, DP-17, WL-12, PC-06).
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
from anylabeling.views.labeling.shape import Shape
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


def _shape(widget, shape_id):
    return next(
        item
        for item in widget.canvas.shapes
        if item.xanylabeling_shape_id == shape_id
    )


def _hide(widget, shape_id):
    """Hide one object through the ordinary object-list check box."""
    shape = _shape(widget, shape_id)
    for index, item in enumerate(widget.label_list):
        if item.shape() is shape:
            item.setCheckState(QtCore.Qt.CheckState.Unchecked)
            return
    raise AssertionError(f"{shape_id} is not in the object list")


def _three_rectangles():
    return [
        _rectangle("person", "rect1", 40, 40),
        _rectangle("person", "rect2", 200, 40),
        _rectangle("person", "rect3", 360, 40),
    ]


def test_manual_hide_excludes_paint_and_hit_but_explains_why(app, open_window):
    window, image_path = open_window(
        _three_rectangles(),
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, _workspace = _open_review(app, window, image_path)
    target = _shape(widget, "rect2")

    # The user hides it with the ordinary check box.
    _hide(widget, "rect2")
    app.processEvents()

    display = widget._dense_review_displays["rect2"]
    assert display.drawable is False
    assert display.hittable is False
    assert display.reason == "manual-hidden"
    assert "隐藏" in widget.dense_review_exclusion_reason("rect2")
    assert widget.canvas.dense_review_hittable(target) is False
    # Hidden by hand means outside the batch candidate set.
    manual, _filtered = widget.dense_review_exclusion_ids()
    assert "rect2" in manual


def test_temporary_show_lifts_visibility_not_eligibility(app, open_window):
    window, image_path = open_window(
        _three_rectangles(),
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, workspace = _open_review(app, window, image_path)
    target = _shape(widget, "rect2")
    _hide(widget, "rect2")
    app.processEvents()

    # An explicit "show anyway" lets the user look at it (DP-11).
    assert widget.dense_review_show_temporarily(["rect2"]) is True
    app.processEvents()
    display = widget._dense_review_displays["rect2"]
    assert display.drawable is True
    assert display.temporary is True
    assert display.reason == ""
    assert widget.canvas.dense_review_hittable(target) is True

    # Observing it does not restore confirmation eligibility (PC-06).
    manual, _filtered = widget.dense_review_exclusion_ids()
    assert "rect2" in manual
    scope = workspace._scope()
    assert "rect2" not in scope.candidate_ids
    session = widget.dense_review_session
    workspace._complete_batch()
    app.processEvents()
    assert session.object("rect1").confirmed_both() is True
    assert session.object("rect2").confirmed_both() is False


def test_temporary_show_ends_on_target_change(app, open_window):
    window, image_path = open_window(
        _three_rectangles(),
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, workspace = _open_review(app, window, image_path)
    _hide(widget, "rect2")
    app.processEvents()
    widget.dense_review_show_temporarily(["rect2"])
    app.processEvents()
    assert widget.dense_review_temporary_ids() == {"rect2"}

    # Navigating to another object clears the exception (DP-11).
    workspace._navigate_to(workspace._current_batch_id(), "rect3")
    app.processEvents()
    assert widget.dense_review_temporary_ids() == set()
    assert widget._dense_review_displays["rect2"].drawable is False


def test_temporary_show_does_not_survive_an_image_switch(app, open_window):
    window, image_path = open_window(
        _three_rectangles(),
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, _workspace = _open_review(app, window, image_path)
    _hide(widget, "rect2")
    app.processEvents()
    widget.dense_review_show_temporarily(["rect2"])
    app.processEvents()
    assert widget.dense_review_temporary_ids() == {"rect2"}

    # Re-loading the same file still counts as an image change (DP-14).
    assert widget.load_file(image_path)
    app.processEvents()
    assert widget.dense_review_temporary_ids() == set()


def test_original_mode_hides_overlay_and_hits(app, open_window):
    window, image_path = open_window(
        _three_rectangles(),
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, _workspace = _open_review(app, window, image_path)
    widget.dense_review_set_display_mode("original")
    app.processEvents()

    for shape_id in ("rect1", "rect2", "rect3"):
        display = widget._dense_review_displays[shape_id]
        assert display.drawable is False
        assert display.hittable is False
        assert display.reason == "original-only"
        assert (
            widget.canvas.dense_review_hittable(_shape(widget, shape_id))
            is False
        )

    # Returning to a normal mode restores the roles.
    widget.dense_review_set_display_mode("all")
    app.processEvents()
    assert widget._dense_review_displays["rect1"].drawable is True


def test_closing_review_restores_latest_user_settings(app, open_window):
    window, image_path = open_window(
        _three_rectangles(),
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, workspace = _open_review(app, window, image_path)
    target = _shape(widget, "rect3")

    # Change a normal setting *while* the review runs, then leave.
    _hide(widget, "rect3")
    app.processEvents()
    widget.dense_review_show_temporarily(["rect3"])
    app.processEvents()
    assert target.visible is False
    assert target in widget._manually_hidden_shapes

    workspace.close()
    app.processEvents()

    # The review overlay is gone and the user's own hide still applies
    # (DP-17, WL-12): the entry snapshot must not overwrite it.
    assert widget.canvas.dense_review_active is False
    assert target.visible is False
    assert _shape(widget, "rect1").visible is True
    assert widget.canvas.is_visible(target) is False
    assert widget.dense_review_temporary_ids() == set()


def test_current_object_edges_and_handles_win_over_a_keypoint(
    app, open_window
):
    shapes = [
        _rectangle("person", "rect1", 40, 40, w=120, h=120),
        _point("nose", "kp1", 100, 100),
    ]
    window, image_path = open_window(
        shapes,
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, _workspace = _open_review(app, window, image_path)
    canvas = widget.canvas
    rect = _shape(widget, "rect1")
    keypoint = _shape(widget, "kp1")
    canvas.select_shapes([rect])
    app.processEvents()

    # A hit on the rectangle edge belongs to the rectangle even though the
    # keypoint sits inside it (DP-07).
    edge_candidates = canvas._shape_hit_candidates(QtCore.QPointF(40, 80))
    assert edge_candidates
    assert edge_candidates[0] is rect
    assert keypoint not in edge_candidates
    # Inside the rectangle a plainly visible keypoint wins: the current
    # object's priority covers only actionable edges and handles, so an
    # interior hit must not swallow the point (DP-07, DP-09).
    inside_candidates = canvas._shape_hit_candidates(QtCore.QPointF(100, 100))
    assert inside_candidates
    assert inside_candidates[0] is keypoint
    assert canvas.dense_review_hittable(keypoint) is True


def test_dragging_keeps_its_start_target(app, open_window):
    shapes = [
        _rectangle("person", "rect1", 40, 40, w=120, h=120),
        _point("nose", "kp1", 100, 100),
    ]
    window, image_path = open_window(
        shapes,
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, _workspace = _open_review(app, window, image_path)
    canvas = widget.canvas
    rect = _shape(widget, "rect1")
    keypoint = _shape(widget, "kp1")
    canvas.select_shapes([rect])
    app.processEvents()

    before_point = QtCore.QPointF(keypoint.points[0])
    assert canvas.bounded_move_shapes([rect], QtCore.QPointF(12, 8))
    canvas.update()
    app.processEvents()
    # Only the explicit target moved (DP-10).
    assert keypoint.points[0] == before_point
    assert canvas.selected_shapes == [rect]


def test_painted_order_never_changes_saved_order(app, open_window):
    window, image_path = open_window(
        _three_rectangles(),
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, _workspace = _open_review(app, window, image_path)
    session = widget.dense_review_session
    before = [shape.xanylabeling_shape_id for shape in widget.canvas.shapes]
    # Switching role current<=>other only reorders the paint groups.
    session.set_current(session.state.current_batch, "rect3")
    widget.refresh_dense_review_display()
    app.processEvents()
    after = [shape.xanylabeling_shape_id for shape in widget.canvas.shapes]
    assert after == before
    assert widget._dense_review_displays["rect3"].role == "current"
    assert widget._dense_review_displays["rect1"].role == "batch"


# -- review audit regressions (2026-11-16 review of 6b0f1168) -------------


def test_closed_workspace_keeps_regular_canvas_after_visibility_edit(
    app, open_window
):
    """The overlay follows workspace activation, not session existence.

    The session deliberately survives a close so reopening resumes the round,
    but the overlay must not come back when the user only touches ordinary
    visibility or filters (DP-17, DP-18).
    """
    window, image_path = open_window(
        _three_rectangles(),
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, workspace = _open_review(app, window, image_path)
    session = widget.dense_review_session
    workspace.close()
    app.processEvents()
    assert widget.dense_review_active() is False
    assert widget.canvas.dense_review_active is False
    assert widget.dense_review_session is session

    # Ordinary hide and filter edits must not reinstall review styling.
    _hide(widget, "rect2")
    app.processEvents()
    assert widget.canvas.dense_review_active is False
    widget.set_invert_shape_filter(True)
    app.processEvents()
    assert widget.canvas.dense_review_active is False
    widget.set_invert_shape_filter(False)
    app.processEvents()
    assert widget.canvas.dense_review_active is False

    # Reopening restores the same round and its progress.
    widget.open_dense_review()
    app.processEvents()
    assert widget.dense_review_session is session
    assert widget.canvas.dense_review_active is True
    assert widget._dense_review_displays


def test_original_comparison_blocks_group_paint_and_hit(app, open_window):
    """Groups obey the effective display result, not raw shape.visible."""
    window, image_path = open_window(
        [_rectangle("person", "rect1", 40, 40, group_id=0)],
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, _workspace = _open_review(app, window, image_path)
    canvas = widget.canvas
    canvas.show_groups = True
    app.processEvents()
    assert canvas._grouped_shapes()
    assert canvas._group_at_point(QtCore.QPointF(70, 70)) is not None

    widget.dense_review_set_display_mode("original")
    app.processEvents()
    assert canvas._shape_hit_candidates(QtCore.QPointF(70, 70)) == []
    assert canvas._group_at_point(QtCore.QPointF(70, 70)) is None
    # Hidden members stay *counted* for the group label, but the geometry
    # used for hits and painting excludes them.
    assert canvas._grouped_shapes()
    assert canvas._group_visible_shapes(canvas._grouped_shapes()[0]) == []

    widget.dense_review_set_display_mode("all")
    app.processEvents()
    assert canvas._group_at_point(QtCore.QPointF(70, 70)) is not None


def test_original_comparison_disables_rotation_handles(app, open_window):
    window, image_path = open_window(
        [
            {
                "label": "person",
                "shape_type": "rotation",
                "points": [[40, 40], [160, 40], [160, 160], [40, 160]],
                "xanylabeling_shape_id": "rot1",
            }
        ],
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, _workspace = _open_review(app, window, image_path)
    canvas = widget.canvas
    shape = _shape(widget, "rot1")
    canvas.select_shapes([shape])
    app.processEvents()
    assert canvas._rotation_handle_shapes() == [shape]

    widget.dense_review_set_display_mode("original")
    app.processEvents()
    assert canvas._rotation_handle_shapes() == []

    widget.dense_review_set_display_mode("all")
    app.processEvents()
    assert canvas._rotation_handle_shapes() == [shape]


def test_temporary_show_reaches_paint_and_hit(app, open_window):
    """The exception must reach the real hit path, not just the table."""
    window, image_path = open_window(
        _three_rectangles(),
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, _workspace = _open_review(app, window, image_path)
    widget.dense_review_set_display_mode("all")
    _hide(widget, "rect2")
    app.processEvents()
    target = _shape(widget, "rect2")
    assert widget.canvas.is_visible(target) is False
    assert target not in widget.canvas._shape_hit_candidates(
        QtCore.QPointF(220, 70)
    )

    assert widget.dense_review_show_temporarily(["rect2"]) is True
    app.processEvents()
    assert widget.canvas.is_visible(target) is True
    assert widget.canvas.dense_review_hittable(target) is True
    assert target in widget.canvas._shape_hit_candidates(
        QtCore.QPointF(220, 70)
    )
    # Eligibility is untouched while the object is only being observed.
    manual, _filtered = widget.dense_review_exclusion_ids()
    assert "rect2" in manual

    # Ending the exception restores the manual hide.
    assert widget.dense_review_end_temporary(["rect2"]) is True
    app.processEvents()
    assert widget.canvas.is_visible(target) is False
    assert target not in widget.canvas._shape_hit_candidates(
        QtCore.QPointF(220, 70)
    )


def test_original_comparison_wins_over_temporary_show(app, open_window):
    window, image_path = open_window(
        _three_rectangles(),
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, _workspace = _open_review(app, window, image_path)
    widget.dense_review_set_display_mode("all")
    _hide(widget, "rect2")
    app.processEvents()
    widget.dense_review_show_temporarily(["rect2"])
    app.processEvents()
    target = _shape(widget, "rect2")
    assert widget.canvas.is_visible(target) is True

    # Source comparison outranks the exception (DP-12).
    widget.dense_review_set_display_mode("original")
    app.processEvents()
    assert widget.canvas.is_visible(target) is False
    assert widget.canvas.dense_review_hittable(target) is False

    widget.dense_review_set_display_mode("all")
    app.processEvents()
    assert widget.canvas.is_visible(target) is True


def test_focus_mode_paints_batch_members_and_associated_points(
    app, open_window, monkeypatch
):
    """Default focus must not swallow the batch or the associated points."""
    shapes = [
        _rectangle("person", "rect1", 40, 40, group_id=0),
        _point("nose", "kp1", 90, 90, group_id=0),
        _rectangle("person", "rect2", 260, 40, group_id=1),
    ]
    window, image_path = open_window(
        shapes,
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, workspace = _open_review(app, window, image_path)
    assert workspace.display_combo.currentData() == "focus"
    assert widget._dense_review_displays["rect2"].drawable is True
    assert widget._dense_review_displays["kp1"].role == "current"

    painted = []
    original = Shape.paint

    def record(shape, *args, **kwargs):
        painted.append(shape.xanylabeling_shape_id)
        return original(shape, *args, **kwargs)

    monkeypatch.setattr(Shape, "paint", record)
    widget.canvas.grab()
    # The batch member and the associated keypoint are really painted.
    assert "rect2" in painted
    assert "kp1" in painted


def test_current_object_paints_last_without_reordering_data(
    app, open_window, monkeypatch
):
    window, image_path = open_window(
        _three_rectangles(),
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, _workspace = _open_review(app, window, image_path)
    widget.dense_review_set_display_mode("all")
    before = [shape.xanylabeling_shape_id for shape in widget.canvas.shapes]
    assert widget.dense_review_display_entry("rect1").role == "current"

    painted = []
    original = Shape.paint

    def record(shape, *args, **kwargs):
        painted.append(shape.xanylabeling_shape_id)
        return original(shape, *args, **kwargs)

    monkeypatch.setattr(Shape, "paint", record)
    widget.canvas.grab()
    assert painted == ["rect2", "rect3", "rect1"]
    # The persisted order is untouched by the temporary paint order.
    after = [shape.xanylabeling_shape_id for shape in widget.canvas.shapes]
    assert after == before


def test_single_manual_hide_is_not_a_global_shutdown(app, open_window):
    """One hidden object must keep the "manual-hidden" reason (DP-11)."""
    window, image_path = open_window(
        [_rectangle("person", "rect1", 40, 40)],
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, _workspace = _open_review(app, window, image_path)
    _hide(widget, "rect1")
    app.processEvents()
    display = widget.dense_review_display_entry("rect1")
    assert display.reason == "manual-hidden"
    assert "隐藏" in widget.dense_review_exclusion_reason("rect1")
    # The exception works because the object is not globally switched off.
    assert widget.dense_review_show_temporarily(["rect1"]) is True
    app.processEvents()
    assert widget.canvas.is_visible(_shape(widget, "rect1")) is True
    # The manual record survives for the batch candidate set.
    manual, _filtered = widget.dense_review_exclusion_ids()
    assert "rect1" in manual
    assert _workspace._scope().excluded["rect1"] == "manual_hidden"


def test_hiding_every_object_by_hand_is_not_a_global_shutdown(
    app, open_window
):
    window, image_path = open_window(
        _three_rectangles(),
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, _workspace = _open_review(app, window, image_path)
    for shape_id in ("rect1", "rect2", "rect3"):
        _hide(widget, shape_id)
    app.processEvents()
    for shape_id in ("rect1", "rect2", "rect3"):
        assert (
            widget.dense_review_display_entry(shape_id).reason
            == "manual-hidden"
        )
    assert widget.dense_review_show_temporarily(["rect2"]) is True
    app.processEvents()
    assert widget.canvas.is_visible(_shape(widget, "rect2")) is True
    assert widget.canvas.is_visible(_shape(widget, "rect1")) is False


def test_real_global_switch_beats_temporary_show(app, open_window):
    window, image_path = open_window(
        [_rectangle("person", "rect1", 40, 40)],
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, _workspace = _open_review(app, window, image_path)
    _hide(widget, "rect1")
    app.processEvents()
    assert widget.dense_review_show_temporarily(["rect1"]) is True
    app.processEvents()
    assert widget.canvas.is_visible(_shape(widget, "rect1")) is True

    # The genuine global switch still wins over the exception (DP-12).
    widget.actions.visibility_shapes_mode.trigger()
    app.processEvents()
    widget.refresh_dense_review_display()
    app.processEvents()
    assert widget._config["show_shapes"] is False
    display = widget.dense_review_display_entry("rect1")
    assert display.reason == "global-off"
    assert widget.canvas.is_visible(_shape(widget, "rect1")) is False
    assert (
        widget.canvas.dense_review_hittable(_shape(widget, "rect1")) is False
    )


def test_original_mode_outranks_temporary_show_reason(app, open_window):
    window, image_path = open_window(
        [_rectangle("person", "rect1", 40, 40)],
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, _workspace = _open_review(app, window, image_path)
    _hide(widget, "rect1")
    app.processEvents()
    widget.dense_review_show_temporarily(["rect1"])
    app.processEvents()
    widget.dense_review_set_display_mode("original")
    app.processEvents()
    assert widget.dense_review_display_entry("rect1").reason == "original-only"
    assert widget.canvas.is_visible(_shape(widget, "rect1")) is False


def test_point_inside_current_rectangle_is_selectable(app, open_window):
    """Interior hits on the current rect must not swallow a visible point."""
    window, image_path = open_window(
        [
            _rectangle("person", "rect1", 40, 40, w=120, h=120),
            _point("nose", "kp1", 100, 100),
        ],
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, _workspace = _open_review(app, window, image_path)
    canvas = widget.canvas
    rect = _shape(widget, "rect1")
    keypoint = _shape(widget, "kp1")
    canvas.select_shapes([rect])
    app.processEvents()

    # Centre of the point: the keypoint wins.
    candidates = canvas._shape_hit_candidates(QtCore.QPointF(100, 100))
    assert candidates[0] is keypoint
    # On the rectangle border: the actionable edge still wins (DP-07).
    edge_candidates = canvas._shape_hit_candidates(QtCore.QPointF(40, 100))
    assert edge_candidates[0] is rect


def test_group_gesture_skips_hidden_and_locked_members(app, open_window):
    """Group selection, drag and nudge share one editable member set."""
    window, image_path = open_window(
        [
            _rectangle("person", "rect1", 40, 40, group_id=0),
            _rectangle("person", "rect2", 62, 62, group_id=0),
            _rectangle("person", "rect3", 200, 40, group_id=0),
        ],
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, _workspace = _open_review(app, window, image_path)
    canvas = widget.canvas
    canvas.show_groups = True
    _hide(widget, "rect2")
    locked = _shape(widget, "rect3")
    locked.locked = True
    app.processEvents()
    if canvas.dense_review_active:
        widget.refresh_dense_review_display()
    app.processEvents()

    hidden_before = _shape(widget, "rect2").bounding_rect()
    locked_before = _shape(widget, "rect3").bounding_rect()
    canvas._select_group(0, QtCore.QPointF(60, 60))
    app.processEvents()
    # The hidden member is excluded from selection; the locked member stays
    # selectable (visible and inspectable) but is never moved.
    assert [s.xanylabeling_shape_id for s in canvas.selected_shapes] == [
        "rect1",
        "rect3",
    ]
    visible_before = _shape(widget, "rect1").bounding_rect()
    canvas.move_by_keyboard(QtCore.QPointF(5.0, 0.0))
    app.processEvents()
    # A locked member still blocks the whole group move (existing rule).
    assert _shape(widget, "rect1").bounding_rect() == visible_before
    # The hidden member keeps its exact coordinates and stays unselected.
    assert _shape(widget, "rect2").bounding_rect() == hidden_before
    assert _shape(widget, "rect2") not in canvas.selected_shapes
    assert _shape(widget, "rect3").bounding_rect() == locked_before

    # After unlocking, the group moves as one - still without the hidden box.
    _shape(widget, "rect3").locked = False
    canvas._select_group(0, QtCore.QPointF(60, 60))
    app.processEvents()
    canvas.move_by_keyboard(QtCore.QPointF(5.0, 0.0))
    app.processEvents()
    assert (
        _shape(widget, "rect1").bounding_rect().x() == visible_before.x() + 5
    )
    assert _shape(widget, "rect2").bounding_rect() == hidden_before


def test_original_mode_pauses_geometry_edits(app, open_window):
    """Mouse, keyboard and preview entries pause during comparison."""
    window, image_path = open_window(
        [_rectangle("person", "rect1", 40, 40)],
        batches=(("person", ("person",)),),
        rules=(("person", "visible", ""),),
    )
    widget, _workspace = _open_review(app, window, image_path)
    canvas = widget.canvas
    target = _shape(widget, "rect1")
    canvas.select_shapes([target])
    app.processEvents()
    before = target.bounding_rect()

    widget.dense_review_set_display_mode("original")
    app.processEvents()
    assert canvas.annotation_editing_paused() is True
    # The shared geometry entry point refuses the move.
    assert canvas.bounded_move_shapes([target], QtCore.QPointF(9, 9)) is False
    canvas.move_by_keyboard(QtCore.QPointF(9.0, 0.0))
    canvas.rotate_by_keyboard(0.1)
    app.processEvents()
    assert target.bounding_rect() == before

    widget.dense_review_set_display_mode("all")
    app.processEvents()
    assert canvas.annotation_editing_paused() is False
    assert canvas.bounded_move_shapes([target], QtCore.QPointF(9, 9))
    app.processEvents()
    assert target.bounding_rect() != before
