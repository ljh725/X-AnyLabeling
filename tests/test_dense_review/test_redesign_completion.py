"""Behavioral coverage for the remaining workbench implementation."""

# flake8: noqa: F811
from PyQt6 import QtCore, QtGui

from anylabeling import user_config
from anylabeling.services.dense_review.preferences import normalize_preferences
from anylabeling.views.labeling.dense_review.label_layout import ReviewLabelLayout
from .test_workspace_review_fixes import _open, app, open_window


def test_point_navigation_keeps_parent_and_edit_identity(app, open_window):
    _, widget, ws = _open(app, open_window)
    index = ws.child_objects.findData("kp1")
    assert index >= 0
    ws._navigate_child(index)
    app.processEvents()
    assert ws.session.current_object().shape_id == "kp1"
    assert widget.canvas.selected_shapes[0].xanylabeling_shape_id == "kp1"
    assert ws._card_parent(ws.session.current_object()).shape_id == "rect1"
    assert not ws.complete_object_button.isEnabled()
    assert not widget.dirty


def test_outside_point_crop_and_body_observation(app, open_window):
    _, widget, ws = _open(app, open_window)
    point = widget._dense_review_find_shape("kp1")
    point.points = [QtCore.QPointF(500, 400)]
    widget._dense_review_sync_from_canvas()
    item = ws.session.object("rect1")
    assert ws._crop_bounds(item) == (40, 40, 500, 400)
    assert "超出" in ws.observation_note.text()
    ws.crop_mode.setCurrentIndex(ws.crop_mode.findData("body"))
    assert ws._crop_bounds(item) == item.bounds
    assert not widget.dirty


def test_task_display_strength_survives_roundtrip(app, open_window):
    _, widget, ws = _open(app, open_window)
    ws.role_combo.setCurrentIndex(ws.role_combo.findData("other"))
    ws.component_combo.setCurrentIndex(ws.component_combo.findData("outline"))
    ws.component_strength.setValue(12)
    ws.set_task(ws.TASK_COVERAGE)
    ws.component_strength.setValue(28)
    ws.set_task(ws.TASK_CATEGORY)
    assert widget._dense_review_role_styles["other"].outline == 0.12
    ws.set_task(ws.TASK_COVERAGE)
    assert widget._dense_review_role_styles["other"].outline == 0.28
    assert not widget.dirty


def test_preference_failure_keeps_live_view(app, open_window, monkeypatch):
    _, widget, ws = _open(app, open_window)
    ws.set_card_image_height(480)
    def fail(*args, **kwargs):
        raise user_config.ConfigError("disk unavailable")
    monkeypatch.setattr(user_config, "save_patch", fail)
    assert ws._save_review_preferences() is False
    assert ws.card_image_height == 480
    assert "disk unavailable" in ws.status_label.text()
    assert not widget.dirty


def test_preferences_persist_without_annotation_changes(app, open_window):
    _, widget, ws = _open(app, open_window)
    ws.set_card_image_height(480)
    ws.set_cards_visible(False)
    ws.set_task(ws.TASK_BOX_POINTS)
    assert ws._save_review_preferences()
    saved = user_config.current_session().effective["dense_review"]
    assert saved["image_height"] == 480
    assert saved["cards_visible"] is False
    assert saved["task"] == ws.TASK_BOX_POINTS
    ws.set_card_image_height(160)
    ws._restore_review_preferences()
    assert ws.card_image_height == 480
    assert not widget.dirty


def test_overlap_menu_only_changes_target_on_explicit_action(app, open_window):
    _, widget, ws = _open(app, open_window)
    target = widget._dense_review_find_shape("kp1")
    before = ws.session.current_object().shape_id
    menu = widget.canvas.dense_review_candidate_menu(target.points[0])
    assert ws.session.current_object().shape_id == before
    action = next(action for action in menu.actions() if "nose" in action.text())
    assert "point" in action.text() and "#" in action.text()
    action.trigger()
    assert ws.session.current_object().shape_id == "kp1"
    assert not widget.dirty
    menu.deleteLater()


def test_minimap_has_real_source_and_keeps_plan(app, open_window):
    _, widget, ws = _open(app, open_window)
    ws.set_task(ws.TASK_COVERAGE)
    plan = ws.session.state.coverage
    assert not ws.coverage_grid._image.isNull()
    assert ws.coverage_grid._image.pixelColor(10, 10) == widget.image.pixelColor(10, 10)
    original = [(region.region_id, region.rect) for region in plan.regions]
    ws.resize(700, 600)
    assert [(region.region_id, region.rect) for region in plan.regions] == original


def test_label_layout_avoids_handles_freezes_drag_and_numbers_overflow():
    layout = ReviewLabelLayout()
    viewport = QtCore.QRect(0, 0, 400, 300)
    rect = QtCore.QRect(100, 100, 80, 20)
    layout.begin("frame", False, [rect])
    placed, fallback = layout.place("a", rect, viewport, current=True)
    assert not placed.intersects(rect)
    assert not fallback
    layout.begin("drag", True, [])
    moved, _ = layout.place("a", rect.translated(12, 7), viewport, current=True)
    assert moved.topLeft() - placed.topLeft() == QtCore.QPoint(12, 7)
    layout.begin("new", False, [])
    _, fallback = layout.place("b", QtCore.QRect(0, 0, 1000, 40), viewport)
    assert fallback and "b" in layout.fallback_ids


def test_invalid_preferences_normalize_to_supported_values():
    prefs = normalize_preferences({"task": "bad", "image_height": "no", "context": 900, "cards_visible": "false"})
    assert prefs["task"] == "category"
    assert prefs["image_height"] == 320
    assert prefs["context"] == 150
    assert prefs["cards_visible"] is True
