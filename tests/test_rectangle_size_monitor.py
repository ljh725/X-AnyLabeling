"""Tests for the proactive rectangle-size runtime monitor."""

from __future__ import annotations

from PyQt6 import QtCore, QtTest

import pytest

from anylabeling.views.labeling.rectangle_size import (
    RectangleCandidate,
    RectangleSizeRule,
)
from anylabeling.views.labeling.widgets.rectangle_size_monitor import (
    RectangleSizeMonitor,
    build_rectangle_candidate,
)
from anylabeling.views.labeling.shape import Shape


def _rule(
    label: str = "person",
    *,
    width: float | None = 36.0,
    height: float | None = 36.0,
) -> RectangleSizeRule:
    """Return a simple any-dimension rule."""
    return RectangleSizeRule(
        label=label,
        min_width_px=width,
        min_height_px=height,
        trigger_mode="any",
    )


def _shape(
    label: str = "person",
    *,
    width: float = 20.0,
    height: float = 20.0,
) -> Shape:
    """Return one real rectangle shape with two diagonal points."""
    shape = Shape(label=label, shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(10.0, 15.0),
        QtCore.QPointF(10.0 + width, 15.0 + height),
    ]
    return shape


def _wait_for_timer(qapp, delay_ms: int = 30) -> None:
    """Allow a monitor's short single-shot timer to fire."""
    QtTest.QTest.qWait(delay_ms)
    qapp.processEvents()


def test_candidate_adapter_normalizes_real_shape_geometry() -> None:
    """The Qt adapter should preserve label/index and normalize the bbox."""
    shape = _shape(width=40.0, height=30.0)
    shape.points.reverse()

    candidate = build_rectangle_candidate(shape, 7, True)

    assert candidate == RectangleCandidate(
        candidate_id=id(shape),
        shape_index=7,
        label="person",
        shape_type="rectangle",
        bbox=(10.0, 15.0, 50.0, 45.0),
        interactive=True,
    )


def test_disabled_monitor_stores_shapes_and_enable_scans_immediately(
    qapp,
) -> None:
    """The default-off lifecycle must not require selection to find issues."""
    monitor = RectangleSizeMonitor([_rule()])
    shape = _shape()
    emissions = []
    monitor.issues_changed.connect(emissions.append)

    monitor.replace_shapes([shape])

    assert monitor.shapes == (shape,)
    assert monitor.issues == ()
    assert emissions == []

    monitor.set_enabled(True)

    assert len(monitor.issues) == 1
    assert monitor.issues[0].candidate_id == id(shape)
    assert emissions == [monitor.issues]


def test_full_scan_reports_multiple_labels_without_selection(qapp) -> None:
    """One proactive scan should retain issues from multiple categories."""
    person = _shape("person", width=20.0, height=50.0)
    head = _shape("head", width=12.0, height=12.0)
    person.selected = False
    head.selected = False
    monitor = RectangleSizeMonitor(
        [
            _rule("person", width=36.0, height=None),
            _rule("head", width=None, height=18.0),
        ],
        enabled=True,
    )

    monitor.replace_shapes([person, head])

    assert [issue.label for issue in monitor.issues] == ["person", "head"]
    assert [issue.violations[0].dimension for issue in monitor.issues] == [
        "width",
        "height",
    ]


@pytest.mark.parametrize(
    ("attribute", "value"),
    [("visible", False), ("hidden_by_filter", True)],
)
def test_default_interactivity_policy_skips_hidden_shapes(
    qapp,
    attribute,
    value,
) -> None:
    """The standalone fallback policy should exclude hidden shapes."""
    shape = _shape()
    setattr(shape, attribute, value)
    monitor = RectangleSizeMonitor([_rule()], enabled=True)

    monitor.replace_shapes([shape])

    assert monitor.issues == ()


def test_replacing_shapes_removes_stale_issues_and_associations(qapp) -> None:
    """Loading another image must not leave the prior image's issue state."""
    old_shape = _shape()
    new_shape = _shape(width=80.0, height=80.0)
    monitor = RectangleSizeMonitor([_rule()], enabled=True)
    monitor.replace_shapes([old_shape])
    candidate_id = monitor.issues[0].candidate_id

    monitor.replace_shapes([new_shape])

    assert monitor.issues == ()
    assert monitor.shape_for_candidate(candidate_id) is None
    assert monitor.shapes == (new_shape,)


def test_rule_replacement_is_atomic_on_invalid_input(qapp) -> None:
    """Invalid new rules must not corrupt the last working runtime state."""
    monitor = RectangleSizeMonitor([_rule()], enabled=True)
    monitor.replace_shapes([_shape()])
    old_rules = monitor.rules
    old_issues = monitor.issues

    with pytest.raises(ValueError):
        monitor.set_rules(
            [
                RectangleSizeRule(
                    label="person",
                    min_width_px=0.0,
                )
            ]
        )

    assert monitor.rules == old_rules
    assert monitor.issues == old_issues


def test_valid_rule_replacement_rescans_immediately(qapp) -> None:
    """A stricter active rule should update issues without a canvas event."""
    monitor = RectangleSizeMonitor(
        [_rule(width=10.0, height=None)],
        enabled=True,
    )
    monitor.replace_shapes([_shape(width=20.0)])
    assert monitor.issues == ()

    monitor.set_rules([_rule(width=20.0, height=None)])

    assert len(monitor.issues) == 1
    assert monitor.issues[0].width == 20.0


def test_disable_clears_and_reenable_rebuilds_issues(qapp) -> None:
    """Toggle transitions should never retain a hidden stale overlay."""
    shape = _shape()
    monitor = RectangleSizeMonitor([_rule()], enabled=True)
    monitor.replace_shapes([shape])
    assert len(monitor.issues) == 1

    monitor.set_enabled(False)

    assert monitor.issues == ()
    assert monitor.shape_for_candidate(id(shape)) is None

    monitor.set_enabled(True)

    assert len(monitor.issues) == 1
    assert monitor.shape_for_candidate(id(shape)) is shape


def test_incremental_invalidation_is_debounced_per_shape(qapp) -> None:
    """Repeated geometry events should evaluate only their one target once."""
    build_calls = []

    def build_candidate(shape, index, interactive):
        """Record adapter calls while delegating to the real adapter."""
        build_calls.append(id(shape))
        return build_rectangle_candidate(shape, index, interactive)

    first = _shape()
    second = _shape()
    monitor = RectangleSizeMonitor(
        [_rule()],
        enabled=True,
        debounce_ms=5,
        candidate_builder=build_candidate,
    )
    monitor.replace_shapes([first, second])
    build_calls.clear()
    first.points[1] = QtCore.QPointF(100.0, 100.0)

    monitor.invalidate_shape(first)
    monitor.invalidate_shape(first)

    assert monitor.scan_pending
    assert build_calls == []
    _wait_for_timer(qapp)

    assert build_calls == [id(first)]
    assert [issue.candidate_id for issue in monitor.issues] == [id(second)]


def test_full_invalidations_coalesce_and_override_incremental(qapp) -> None:
    """One pending full scan should subsume all lower-cost invalidations."""
    build_calls = []

    def build_candidate(shape, index, interactive):
        """Record adapter calls while delegating to the real adapter."""
        build_calls.append(id(shape))
        return build_rectangle_candidate(shape, index, interactive)

    first = _shape()
    second = _shape()
    monitor = RectangleSizeMonitor(
        [_rule()],
        enabled=True,
        debounce_ms=5,
        candidate_builder=build_candidate,
    )
    monitor.replace_shapes([first, second])
    build_calls.clear()

    monitor.invalidate_shape(first)
    monitor.invalidate_all()
    monitor.invalidate_all()
    monitor.invalidate_shape(second)
    _wait_for_timer(qapp)

    assert build_calls == [id(first), id(second)]


def test_unknown_shape_invalidation_is_ignored(qapp) -> None:
    """Signals for a stale image must not schedule or alter current work."""
    current = _shape()
    stale = _shape()
    monitor = RectangleSizeMonitor(
        [_rule()],
        enabled=True,
        debounce_ms=5,
    )
    monitor.replace_shapes([current])
    old_issues = monitor.issues

    monitor.invalidate_shape(stale)

    assert not monitor.scan_pending
    assert monitor.issues == old_issues


def test_clear_shapes_cancels_pending_work_and_drops_references(qapp) -> None:
    """Closing an image should synchronously empty every runtime snapshot."""
    shape = _shape()
    monitor = RectangleSizeMonitor(
        [_rule()],
        enabled=True,
        debounce_ms=5,
    )
    monitor.replace_shapes([shape])
    monitor.invalidate_all()
    assert monitor.scan_pending

    monitor.clear_shapes()

    assert not monitor.scan_pending
    assert monitor.shapes == ()
    assert monitor.issues == ()
    assert monitor.shape_for_candidate(id(shape)) is None
    _wait_for_timer(qapp)
    assert monitor.issues == ()


def test_injected_canvas_policy_is_authoritative(qapp) -> None:
    """Later Canvas integration can replace the standalone visibility policy."""
    shape = _shape()
    shape.visible = False
    monitor = RectangleSizeMonitor(
        [_rule()],
        enabled=True,
        is_shape_interactive=lambda _shape: True,
    )

    monitor.replace_shapes([shape])

    assert len(monitor.issues) == 1
