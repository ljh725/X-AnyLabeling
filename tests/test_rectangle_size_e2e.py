"""End-to-end acceptance tests for proactive rectangle-size validation."""

from __future__ import annotations

import copy
from typing import Any

from PyQt6 import QtCore, QtTest, QtWidgets

import pytest

from anylabeling.config import get_default_config
from anylabeling.services.auto_labeling import model_manager
from anylabeling.views.labeling import label_widget as label_widget_module
from anylabeling.views.labeling.rectangle_size.models import RectangleSizeRule
from anylabeling.views.labeling.shape import Shape


def _rectangle(
    label: str,
    width: float,
    height: float,
    *,
    x: float = 10.0,
    y: float = 10.0,
) -> Shape:
    """Build one live rectangle in image-pixel coordinates."""
    shape = Shape(label=label, shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(x, y),
        QtCore.QPointF(x + width, y + height),
    ]
    return shape


def _build_widget(
    config: dict[str, Any],
    persisted: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    label_widget_module.LabelingWidget,
    QtWidgets.QWidget,
    QtWidgets.QMainWindow,
]:
    """Build a real labeling widget with isolated configuration persistence."""
    monkeypatch.setattr(
        label_widget_module,
        "save_config",
        lambda current: persisted.append(copy.deepcopy(current)),
    )
    monkeypatch.setattr(model_manager, "get_config", lambda: config)
    main_window = QtWidgets.QMainWindow()
    wrapper = QtWidgets.QWidget()
    wrapper.parent = main_window
    widget = label_widget_module.LabelingWidget(
        parent=wrapper,
        config=config,
    )
    return widget, wrapper, main_window


def _dispose_widget(
    widget: label_widget_module.LabelingWidget,
    wrapper: QtWidgets.QWidget,
    main_window: QtWidgets.QMainWindow,
    qapp: QtWidgets.QApplication,
) -> None:
    """Release one real widget harness without leaving Monitor timers alive."""
    widget.rectangle_size_controller.monitor.clear_shapes()
    widget.close()
    widget.deleteLater()
    wrapper.deleteLater()
    main_window.deleteLater()
    qapp.processEvents()


def _flush_monitor(qapp: QtWidgets.QApplication) -> None:
    """Wait for the Monitor debounce and dispatch queued Qt signals."""
    QtTest.QTest.qWait(80)
    qapp.processEvents()


def _issue_labels(
    widget: label_widget_module.LabelingWidget,
) -> list[str]:
    """Return issue labels in current canvas order."""
    return [issue.label for issue in widget.canvas.rectangle_size_issues]


def _backup_snapshot(
    widget: label_widget_module.LabelingWidget,
) -> list[list[dict[str, Any]]]:
    """Serialize the Canvas undo snapshots for side-effect comparison."""
    return [
        [shape.to_dict() for shape in backup]
        for backup in widget.canvas.shapes_backups
    ]


def test_e2e_multi_category_optional_dimensions_and_boundaries(
    qapp: QtWidgets.QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multiple label rules should proactively honor any/all and equality."""
    config = copy.deepcopy(get_default_config())
    persisted: list[dict[str, Any]] = []
    widget, wrapper, main_window = _build_widget(
        config,
        persisted,
        monkeypatch,
    )
    try:
        person = _rectangle("person", 20.0, 100.0)
        face = _rectangle("face", 10.0, 20.0, x=40.0)
        head = _rectangle("head", 100.0, 12.0, x=80.0)
        widget.canvas.load_shapes([person, face, head], replace=True)
        widget.rectangle_size_controller.set_rules(
            (
                RectangleSizeRule(
                    label="person",
                    min_width_px=20.0,
                    min_height_px=None,
                    trigger_mode="any",
                ),
                RectangleSizeRule(
                    label="face",
                    min_width_px=15.0,
                    min_height_px=15.0,
                    trigger_mode="all",
                ),
                RectangleSizeRule(
                    label="head",
                    min_width_px=None,
                    min_height_px=12.0,
                    trigger_mode="any",
                ),
            )
        )

        widget.actions.show_rectangle_size_violations.trigger()
        qapp.processEvents()

        assert _issue_labels(widget) == ["person", "head"]
        assert widget.canvas.selected_shapes == []
        assert {
            violation.dimension
            for violation in widget.canvas.rectangle_size_issues[0].violations
        } == {"width"}

        face.points[1] = QtCore.QPointF(55.0, 25.0)
        widget.canvas.notify_shape_changed(face)
        _flush_monitor(qapp)

        assert _issue_labels(widget) == ["person", "face", "head"]
        face_issue = widget.canvas.rectangle_size_issues[1]
        assert {item.dimension for item in face_issue.violations} == {
            "width",
            "height",
        }
        assert face_issue.width == 15.0
        assert face_issue.height == 15.0
    finally:
        _dispose_widget(widget, wrapper, main_window, qapp)


def test_e2e_shape_lifecycle_visibility_and_image_switch(
    qapp: QtWidgets.QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edits, visibility, deletion, and image replacement should not go stale."""
    config = copy.deepcopy(get_default_config())
    persisted: list[dict[str, Any]] = []
    widget, wrapper, main_window = _build_widget(
        config,
        persisted,
        monkeypatch,
    )
    try:
        controller = widget.rectangle_size_controller
        controller.set_rules(
            (
                RectangleSizeRule(
                    label="person",
                    min_width_px=36.0,
                    min_height_px=36.0,
                    trigger_mode="any",
                ),
            )
        )
        widget.actions.show_rectangle_size_violations.trigger()

        shape = _rectangle("person", 20.0, 20.0)
        widget.canvas.shapes.append(shape)
        widget.canvas.notify_shapes_changed()
        assert _issue_labels(widget) == ["person"]

        shape.points[1] = QtCore.QPointF(70.0, 70.0)
        widget.canvas.notify_shape_changed(shape)
        assert controller.monitor.scan_pending is True
        _flush_monitor(qapp)
        assert controller.monitor.scan_pending is False
        assert widget.canvas.rectangle_size_issues == ()

        shape.points[1] = QtCore.QPointF(46.0, 90.0)
        widget.canvas.notify_shape_changed(shape)
        _flush_monitor(qapp)
        assert _issue_labels(widget) == ["person"]

        shape.label = "face"
        widget.canvas.notify_shape_changed(shape)
        _flush_monitor(qapp)
        assert widget.canvas.rectangle_size_issues == ()

        shape.label = "person"
        widget.canvas.notify_shape_changed(shape)
        _flush_monitor(qapp)
        assert _issue_labels(widget) == ["person"]

        widget.canvas.set_shape_visible(shape, False)
        _flush_monitor(qapp)
        assert widget.canvas.rectangle_size_issues == ()

        widget.canvas.set_shape_visible(shape, True)
        _flush_monitor(qapp)
        assert _issue_labels(widget) == ["person"]

        widget.canvas.set_main_visibility_predicate(lambda _shape: False)
        assert widget.canvas.rectangle_size_issues == ()
        widget.canvas.clear_main_visibility_predicate()
        assert _issue_labels(widget) == ["person"]

        old_candidate_id = id(shape)
        widget.canvas.delete_shape(shape)
        assert widget.canvas.rectangle_size_issues == ()
        assert controller.monitor.shape_for_candidate(old_candidate_id) is None

        image_a_shape = _rectangle("person", 10.0, 10.0)
        widget.canvas.load_shapes([image_a_shape], replace=True)
        assert _issue_labels(widget) == ["person"]
        image_b_shape = _rectangle("person", 80.0, 80.0)
        widget.canvas.load_shapes([image_b_shape], replace=True)

        assert widget.canvas.rectangle_size_issues == ()
        assert controller.monitor.shapes == (image_b_shape,)
        assert (
            controller.monitor.shape_for_candidate(id(image_a_shape)) is None
        )
    finally:
        _dispose_widget(widget, wrapper, main_window, qapp)


def test_e2e_feature_changes_only_config_and_transient_overlay_state(
    qapp: QtWidgets.QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Toggle and rule changes must not mutate labels, undo, or dirty state."""
    config = copy.deepcopy(get_default_config())
    persisted: list[dict[str, Any]] = []
    widget, wrapper, main_window = _build_widget(
        config,
        persisted,
        monkeypatch,
    )
    try:
        shape = _rectangle("person", 20.0, 20.0)
        widget.canvas.load_shapes([shape], replace=True)
        shape_snapshot = copy.deepcopy(shape.to_dict())
        backup_snapshot = copy.deepcopy(_backup_snapshot(widget))
        assert widget.label_file is None
        assert widget.dirty is False

        widget.actions.show_rectangle_size_violations.trigger()
        widget.rectangle_size_controller.set_rules(
            (
                RectangleSizeRule(
                    label="person",
                    min_width_px=25.0,
                    min_height_px=None,
                ),
                RectangleSizeRule(
                    label="face",
                    min_width_px=12.0,
                    min_height_px=12.0,
                    trigger_mode="all",
                ),
            )
        )
        widget.canvas.scale = 2.0
        widget.canvas.update()
        qapp.processEvents()

        assert shape.to_dict() == shape_snapshot
        assert _backup_snapshot(widget) == backup_snapshot
        assert widget.dirty is False
        assert widget.label_file is None
        assert widget.canvas.selected_shapes == []
        assert _issue_labels(widget) == ["person"]
        assert len(persisted) == 2
        assert persisted[-1]["show_rectangle_size_violations"] is True
        assert len(persisted[-1]["rectangle_size_rules"]) == 2
    finally:
        _dispose_widget(widget, wrapper, main_window, qapp)


def test_e2e_persisted_rules_and_toggle_restore_after_restart(
    qapp: QtWidgets.QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new LabelingWidget should restore explicit settings without writing."""
    config = copy.deepcopy(get_default_config())
    first_persisted: list[dict[str, Any]] = []
    first, first_wrapper, first_main = _build_widget(
        config,
        first_persisted,
        monkeypatch,
    )
    try:
        first.rectangle_size_controller.set_rules(
            (
                RectangleSizeRule(
                    label="face",
                    min_width_px=12.0,
                    min_height_px=None,
                ),
            )
        )
        first.actions.show_rectangle_size_violations.trigger()
        restart_config = copy.deepcopy(first_persisted[-1])
    finally:
        _dispose_widget(first, first_wrapper, first_main, qapp)

    restart_persisted: list[dict[str, Any]] = []
    restarted, restart_wrapper, restart_main = _build_widget(
        restart_config,
        restart_persisted,
        monkeypatch,
    )
    try:
        assert restarted.rectangle_size_controller.enabled is True
        assert restarted.actions.show_rectangle_size_violations.isChecked()
        assert restarted.rectangle_size_controller.rules == (
            RectangleSizeRule(
                label="face",
                min_width_px=12.0,
                min_height_px=None,
            ),
        )

        restarted.canvas.load_shapes(
            [_rectangle("face", 12.0, 50.0)],
            replace=True,
        )

        assert _issue_labels(restarted) == ["face"]
        assert restart_persisted == []
        assert restarted.dirty is False
    finally:
        _dispose_widget(
            restarted,
            restart_wrapper,
            restart_main,
            qapp,
        )
