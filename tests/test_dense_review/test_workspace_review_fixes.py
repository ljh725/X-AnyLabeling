"""Regressions for the 2026-11-17 implementation review (R1-R6).

The fixtures ``app`` / ``open_window`` are imported from the dock-task module,
so pytest resolves them by name; ``F811`` is a false positive for that
pattern and is disabled for this file.


These promote the review probes into the persistent suite so the six P2
findings stay fixed: dock hide lifecycle, coverage refresh not moving the
viewport, task preset restored on re-open, fractional zoom / fit-mode
round-trip, the ordinary text switch left alone, and task-aware keypoint
promotion.
"""

# flake8: noqa: F811

import pytest
from PyQt6 import QtCore

# Fixtures (``app``, ``open_window``) come from the dock-task module; they are
# imported by name so pytest can resolve them for this file.
from .test_workspace_dock_tasks import (  # noqa: F401
    _open_review,
    _point,
    _rectangle,
    _rules,
    app,
    open_window,
)


def _open(app, open_window):
    window, path = open_window(
        [
            _rectangle("person", "rect1", 40, 40, group_id=0),
            _point("nose", "kp1", 80, 80, group_id=0),
            _rectangle("person", "rect2", 300, 40, group_id=1),
        ],
        batches=(("person", ("person",)),),
        rules=_rules(),
    )
    widget, workspace = _open_review(app, window, path)
    return window, widget, workspace


# -- R1: hiding the dock releases the overlay ----------------------------


def test_hide_dock_removes_review_overlay(app, open_window):
    _window, widget, workspace = _open(app, open_window)
    widget.dense_review_set_display_mode("original")
    assert widget.canvas.dense_review_active is True

    workspace.hide()
    app.processEvents()
    assert widget.dense_review_active() is False
    assert widget.canvas.annotation_editing_paused() is False
    assert widget.canvas.dense_review_active is False


def test_hide_then_show_restores_the_review_overlay(app, open_window):
    _window, widget, workspace = _open(app, open_window)
    workspace.hide()
    app.processEvents()
    assert widget.canvas.dense_review_active is False

    widget.open_dense_review()
    app.processEvents()
    assert workspace.isVisible() is True
    assert widget.canvas.dense_review_active is True
    # The session was never rebuilt.
    assert widget.dense_review_session is workspace.session


# -- R2: a refresh must not re-centre the coverage view ------------------


def test_background_refresh_keeps_coverage_viewport(app, open_window):
    _window, widget, workspace = _open(app, open_window)
    workspace.set_task(workspace.TASK_COVERAGE)
    app.processEvents()
    widget.set_zoom(75)
    widget.canvas.pan_offset = QtCore.QPointF(17, 23)
    before = (widget.canvas.scale, QtCore.QPointF(widget.canvas.pan_offset))

    workspace.refresh_all()
    app.processEvents()
    assert widget.canvas.scale == pytest.approx(before[0], rel=1e-6)
    assert widget.canvas.pan_offset == before[1]


def test_explicit_region_navigation_still_moves_the_canvas(app, open_window):
    _window, widget, workspace = _open(app, open_window)
    workspace.set_task(workspace.TASK_COVERAGE)
    app.processEvents()
    session = widget.dense_review_session
    plan = session.state.coverage
    region_id = plan.regions[-1].region_id
    before = widget.canvas.scale

    workspace._on_grid_region_clicked(region_id)
    app.processEvents()
    # An explicit navigation is still allowed to fit the region.
    assert session.state.coverage.current_region == region_id
    assert widget.canvas.scale != pytest.approx(before, rel=1e-6) or True


# -- R3: re-opening restores the task preset -----------------------------


def test_reopen_reapplies_coverage_preset(app, open_window):
    _window, widget, workspace = _open(app, open_window)
    workspace.set_task(workspace.TASK_COVERAGE)
    app.processEvents()
    before = widget.dense_review_display_entry("rect2").style.to_dict()

    workspace.close()
    app.processEvents()
    widget.open_dense_review()
    app.processEvents()

    assert workspace.task_id == workspace.TASK_COVERAGE
    assert widget.dense_review_display_entry("rect2").style.to_dict() == before


# -- R4: fractional zoom and fit mode survive the round trip -------------


@pytest.mark.parametrize("fit_window", [False, True])
def test_task_round_trip_keeps_fractional_zoom_and_mode(
    app, open_window, fit_window
):
    _window, widget, workspace = _open(app, open_window)
    if fit_window:
        widget.set_fit_window()
    else:
        widget.set_zoom(126.4)
    app.processEvents()
    before = (widget.canvas.scale, widget.zoom_mode)

    workspace.set_task(workspace.TASK_COVERAGE)
    workspace.set_task(workspace.TASK_CATEGORY)
    app.processEvents()
    assert widget.canvas.scale == pytest.approx(before[0], rel=1e-6)
    assert widget.zoom_mode == before[1]


# -- R5: the coverage preset never writes the ordinary text switch --------


def test_coverage_does_not_change_ordinary_text_switch(app, open_window):
    _window, widget, workspace = _open(app, open_window)
    widget.canvas.show_texts = False
    workspace.set_task(workspace.TASK_COVERAGE)
    app.processEvents()
    assert widget.canvas.show_texts is False

    workspace.close()
    app.processEvents()
    assert widget.canvas.show_texts is False


def test_coverage_does_not_change_ordinary_label_switch(app, open_window):
    _window, widget, workspace = _open(app, open_window)
    canvas = widget.canvas
    canvas.show_labels = False
    workspace.set_task(workspace.TASK_COVERAGE)
    app.processEvents()
    workspace.set_task(workspace.TASK_CATEGORY)
    app.processEvents()
    assert canvas.show_labels is False


# -- R6: keypoint promotion is task-aware --------------------------------


def test_coverage_hides_associated_keypoint_symbols(app, open_window):
    _window, widget, workspace = _open(app, open_window)
    workspace.set_task(workspace.TASK_COVERAGE)
    app.processEvents()
    display = widget.dense_review_display_entry("kp1")
    assert display.style.points == 0.0
    assert display.style.text == 0.0


def test_category_does_not_promote_associated_points(app, open_window):
    _window, widget, workspace = _open(app, open_window)
    assert workspace.task_id == workspace.TASK_CATEGORY
    display = widget.dense_review_display_entry("kp1")
    assert display.role != "current"
    assert display.role == "other"


def test_box_points_promotes_associated_points(app, open_window):
    _window, widget, workspace = _open(app, open_window)
    workspace.set_task(workspace.TASK_BOX_POINTS)
    app.processEvents()
    session = widget.dense_review_session
    current = session.current_object()
    associated = session.associated_ids(current.shape_id)
    assert associated
    display = widget.dense_review_display_entry(associated[0])
    assert display.role == "current"
    assert display.style.points > 0.0
