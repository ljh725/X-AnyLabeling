"""Tests for the rectangle-size application integration controller."""

from __future__ import annotations

import copy

from PyQt6 import QtCore, QtTest

import pytest

from anylabeling.views.labeling.rectangle_size.config_codec import (
    RectangleSizeConfigError,
)
from anylabeling.views.labeling.rectangle_size.models import RectangleSizeRule
from anylabeling.views.labeling.widgets.rectangle_size_controller import (
    RectangleSizeFeatureController,
)
from anylabeling.views.labeling.shape import Shape


class FakeCanvas(QtCore.QObject):
    """Minimal signal and issue adapter used by the feature controller."""

    shape_changed = QtCore.pyqtSignal(object)
    shapes_changed = QtCore.pyqtSignal(tuple)

    def __init__(self, shapes: tuple[object, ...] = ()) -> None:
        """Initialize a current-image shape snapshot."""
        super().__init__()
        self.shapes = list(shapes)
        self.show_rectangle_size_violations = False
        self.issues = ()
        self.issue_shapes = {}
        self.hidden_shapes = set()
        self.update_count = 0
        self.clear_count = 0

    def set_rectangle_size_issues(
        self,
        issues: tuple[object, ...],
        shape_lookup=None,
    ) -> None:
        """Store issues and resolve their live shapes."""
        self.issues = tuple(issues)
        self.issue_shapes = {
            issue.candidate_id: shape_lookup(issue.candidate_id)
            for issue in self.issues
        }

    def clear_rectangle_size_issues(self) -> None:
        """Clear stored issue state."""
        self.issues = ()
        self.issue_shapes = {}
        self.clear_count += 1

    def update(self) -> None:
        """Record one repaint request."""
        self.update_count += 1

    def is_shape_interactive(self, shape: object) -> bool:
        """Return the fake canvas visibility state for one shape."""
        return shape not in self.hidden_shapes

    def replace_shapes(self, shapes: tuple[object, ...]) -> None:
        """Replace the current image and emit the generic Canvas contract."""
        self.shapes = list(shapes)
        self.shapes_changed.emit(tuple(self.shapes))


def _shape(
    label: str = "person",
    *,
    width: float = 20.0,
    height: float = 20.0,
) -> Shape:
    """Return one rectangle with image-pixel geometry."""
    shape = Shape(label=label, shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(10.0, 15.0),
        QtCore.QPointF(10.0 + width, 15.0 + height),
    ]
    return shape


def _config(
    *,
    enabled: bool = True,
    label: str = "person",
    width: float | None = 36.0,
    height: float | None = 36.0,
    mode: str = "all",
) -> dict:
    """Return one persisted controller configuration."""
    return {
        "show_rectangle_size_violations": enabled,
        "rectangle_size_rules": [
            {
                "label": label,
                "min_width_px": width,
                "min_height_px": height,
                "trigger_mode": mode,
                "enabled": True,
            }
        ],
    }


def _controller(
    canvas: FakeCanvas,
    config: dict,
) -> tuple[RectangleSizeFeatureController, list[dict]]:
    """Build a controller and capture persisted snapshots."""
    persisted = []
    controller = RectangleSizeFeatureController(
        canvas,
        config,
        persist_config=lambda current: persisted.append(
            copy.deepcopy(current)
        ),
    )
    return controller, persisted


def test_startup_connects_config_monitor_and_canvas_without_writing(
    qapp,
) -> None:
    """An enabled startup config should immediately scan the current image."""
    shape = _shape()
    canvas = FakeCanvas((shape,))

    controller, persisted = _controller(canvas, _config())

    assert controller.enabled is True
    assert canvas.show_rectangle_size_violations is True
    assert len(canvas.issues) == 1
    assert canvas.issue_shapes[canvas.issues[0].candidate_id] is shape
    assert persisted == []


def test_shape_change_incrementally_refreshes_canvas_issues(qapp) -> None:
    """Generic per-shape changes should drive the debounced Monitor path."""
    shape = _shape()
    canvas = FakeCanvas((shape,))
    controller, _persisted = _controller(canvas, _config())
    shape.points[1] = QtCore.QPointF(80.0, 85.0)

    canvas.shape_changed.emit(shape)
    QtTest.QTest.qWait(80)
    qapp.processEvents()

    assert controller.monitor.scan_pending is False
    assert canvas.issues == ()


def test_canvas_visibility_is_authoritative_for_monitoring(qapp) -> None:
    """Canvas-only visibility state should suppress and restore one issue."""
    shape = _shape()
    canvas = FakeCanvas((shape,))
    controller, _persisted = _controller(canvas, _config())

    canvas.hidden_shapes.add(shape)
    canvas.shape_changed.emit(shape)
    QtTest.QTest.qWait(80)
    qapp.processEvents()

    assert canvas.issues == ()

    canvas.hidden_shapes.remove(shape)
    canvas.shape_changed.emit(shape)
    QtTest.QTest.qWait(80)
    qapp.processEvents()

    assert len(canvas.issues) == 1
    assert controller.monitor.shape_for_candidate(id(shape)) is shape


def test_shape_list_change_replaces_current_image_without_stale_issues(
    qapp,
) -> None:
    """Image/list replacement should synchronously drop old associations."""
    old_shape = _shape()
    new_shape = _shape("face")
    canvas = FakeCanvas((old_shape,))
    controller, _persisted = _controller(canvas, _config())

    canvas.replace_shapes((new_shape,))

    assert controller.monitor.shapes == (new_shape,)
    assert canvas.issues == ()
    assert controller.monitor.shape_for_candidate(id(old_shape)) is None


def test_toggle_updates_monitor_canvas_and_persisted_config(qapp) -> None:
    """The independent feature toggle should persist and clear immediately."""
    canvas = FakeCanvas((_shape(),))
    config = _config(enabled=False)
    controller, persisted = _controller(canvas, config)

    controller.set_enabled(True)

    assert len(canvas.issues) == 1
    assert config["show_rectangle_size_violations"] is True
    assert persisted[-1]["show_rectangle_size_violations"] is True

    controller.set_enabled(False)

    assert canvas.issues == ()
    assert canvas.clear_count == 1
    assert config["show_rectangle_size_violations"] is False
    assert persisted[-1]["show_rectangle_size_violations"] is False


def test_rule_apply_rescans_and_persists_one_normalized_snapshot(qapp) -> None:
    """Accepted rules should immediately replace runtime and persisted state."""
    canvas = FakeCanvas((_shape("face", width=10.0, height=50.0),))
    config = _config()
    controller, persisted = _controller(canvas, config)
    rules = (
        RectangleSizeRule(
            label="face",
            min_width_px=12.0,
            min_height_px=None,
            trigger_mode="any",
        ),
    )

    controller.set_rules(rules)

    assert controller.rules == rules
    assert len(canvas.issues) == 1
    assert config["rectangle_size_rules"] == [
        {
            "label": "face",
            "min_width_px": 12.0,
            "min_height_px": None,
            "trigger_mode": "any",
            "enabled": True,
        }
    ]
    assert (
        persisted[-1]["rectangle_size_rules"] == config["rectangle_size_rules"]
    )


def test_invalid_startup_rules_fall_back_without_startup_write(qapp) -> None:
    """Malformed persisted rows should not prevent the application from loading."""
    canvas = FakeCanvas((_shape(),))
    config = _config(width=0)

    controller, persisted = _controller(canvas, config)

    assert controller.startup_config_error is not None
    assert controller.rules == (
        RectangleSizeRule(
            label="person",
            min_width_px=36.0,
            min_height_px=36.0,
            trigger_mode="all",
        ),
    )
    assert len(canvas.issues) == 1
    assert persisted == []


def test_invalid_rule_apply_is_atomic(qapp) -> None:
    """A bad programmatic update must not alter runtime or persisted state."""
    canvas = FakeCanvas((_shape(),))
    config = _config()
    controller, persisted = _controller(canvas, config)
    original_rules = controller.rules
    original_config = copy.deepcopy(config)

    with pytest.raises(RectangleSizeConfigError):
        controller.set_rules(
            [
                RectangleSizeRule(
                    label="person",
                    min_width_px=0,
                )
            ]
        )

    assert controller.rules == original_rules
    assert config == original_config
    assert persisted == []


def test_malformed_toggle_normalizes_to_safe_disabled_state(qapp) -> None:
    """Only real booleans may activate proactive scanning at startup."""
    canvas = FakeCanvas((_shape(),))
    config = _config()
    config["show_rectangle_size_violations"] = "yes"

    controller, persisted = _controller(canvas, config)

    assert controller.enabled is False
    assert config["show_rectangle_size_violations"] is False
    assert canvas.issues == ()
    assert persisted == []
