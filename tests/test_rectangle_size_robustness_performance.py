"""Robustness and performance tests for rectangle-size validation."""

from __future__ import annotations

import logging
import time

from PyQt6 import QtCore, QtTest

from anylabeling.views.labeling.rectangle_size import (
    OverlayLayoutItem,
    RectangleCandidate,
    RectangleSizeEvaluator,
    RectangleSizeRule,
    layout_overlay_items,
)
from anylabeling.views.labeling.widgets.rectangle_size_monitor import (
    RectangleSizeMonitor,
)
from anylabeling.views.labeling.shape import Shape


def _rule(label: str = "person") -> RectangleSizeRule:
    """Return one width-only rule used by stress scenarios."""
    return RectangleSizeRule(
        label=label,
        min_width_px=36.0,
        min_height_px=None,
    )


def _shape(
    label: str = "person",
    *,
    width: float = 20.0,
    height: float = 20.0,
) -> Shape:
    """Return one real rectangle shape."""
    shape = Shape(label=label, shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(0.0, 0.0),
        QtCore.QPointF(width, height),
    ]
    return shape


def _wait(qapp, delay_ms: int = 30) -> None:
    """Dispatch one Monitor debounce interval."""
    QtTest.QTest.qWait(delay_ms)
    qapp.processEvents()


def test_monitor_isolates_visibility_failure_and_recovers(
    qapp,
    caplog,
) -> None:
    """One failing Canvas predicate must not suppress healthy candidates."""
    broken = _shape()
    healthy = _shape()
    state = {"fail": True}

    def is_interactive(shape: object) -> bool:
        """Raise only for the selected synthetic failure."""
        if shape is broken and state["fail"]:
            raise RuntimeError("visibility failed")
        return True

    monitor = RectangleSizeMonitor(
        [_rule()],
        enabled=True,
        debounce_ms=5,
        is_shape_interactive=is_interactive,
    )
    with caplog.at_level(
        logging.WARNING,
        logger=("anylabeling.views.labeling.widgets.rectangle_size_monitor"),
    ):
        monitor.replace_shapes([broken, healthy])
        monitor.invalidate_shape(broken)
        monitor.invalidate_shape(broken)
        _wait(qapp)

    assert [issue.candidate_id for issue in monitor.issues] == [id(healthy)]
    assert (
        caplog.messages.count(
            "Skipping rectangle-size candidate at index 0: visibility failed"
        )
        == 1
    )

    state["fail"] = False
    monitor.invalidate_shape(broken)
    _wait(qapp)

    assert [issue.candidate_id for issue in monitor.issues] == [
        id(broken),
        id(healthy),
    ]


def test_monitor_skips_invalid_builder_outputs_without_stale_state(
    qapp,
) -> None:
    """Extension failures and malformed candidates should be isolated."""
    shapes = [object(), object(), object(), object()]

    def build_candidate(
        shape: object,
        index: int,
        interactive: bool,
    ) -> object:
        """Return one failure mode per synthetic shape."""
        if index == 0:
            raise RuntimeError("adapter failed")
        if index == 1:
            return object()
        if index == 2:
            return RectangleCandidate(
                candidate_id=[],
                shape_index=index,
                label="person",
                shape_type="rectangle",
                bbox=(0.0, 0.0, 20.0, 20.0),
                interactive=interactive,
            )
        return RectangleCandidate(
            candidate_id=id(shape),
            shape_index=index,
            label="person",
            shape_type="rectangle",
            bbox=(0.0, 0.0, 20.0, 20.0),
            interactive=interactive,
        )

    monitor = RectangleSizeMonitor(
        [_rule()],
        enabled=True,
        candidate_builder=build_candidate,
    )

    monitor.replace_shapes(shapes)

    assert [issue.shape_index for issue in monitor.issues] == [3]
    assert monitor.shape_for_candidate(id(shapes[3])) is shapes[3]

    monitor.replace_shapes([shapes[0]])

    assert monitor.issues == ()
    assert monitor.shape_for_candidate(id(shapes[3])) is None


def test_monitor_keeps_first_candidate_when_extension_duplicates_identity(
    qapp,
) -> None:
    """A broken adapter cannot let one duplicate identity abort the scan."""
    first = object()
    second = object()

    def build_candidate(
        _shape: object,
        index: int,
        interactive: bool,
    ) -> RectangleCandidate:
        """Deliberately return one duplicate extension identity."""
        return RectangleCandidate(
            candidate_id="duplicate",
            shape_index=index,
            label="person",
            shape_type="rectangle",
            bbox=(0.0, 0.0, 20.0, 20.0),
            interactive=interactive,
        )

    monitor = RectangleSizeMonitor(
        [_rule()],
        enabled=True,
        candidate_builder=build_candidate,
    )

    monitor.replace_shapes([first, second])

    assert [issue.shape_index for issue in monitor.issues] == [0]
    assert monitor.shape_for_candidate("duplicate") is first


def test_image_switch_cancels_old_debounced_refresh(qapp) -> None:
    """A pending edit from the old image cannot republish a stale issue."""
    old_shape = _shape()
    new_shape = _shape(width=80.0)
    monitor = RectangleSizeMonitor(
        [_rule()],
        enabled=True,
        debounce_ms=5,
    )
    monitor.replace_shapes([old_shape])
    old_shape.points[1] = QtCore.QPointF(80.0, 80.0)
    monitor.invalidate_shape(old_shape)
    assert monitor.scan_pending

    monitor.replace_shapes([new_shape])

    assert not monitor.scan_pending
    assert monitor.issues == ()
    _wait(qapp)
    assert monitor.issues == ()
    assert monitor.shape_for_candidate(id(old_shape)) is None


def test_high_frequency_notifications_coalesce_at_large_shape_count(
    qapp,
) -> None:
    """Thousands of repeated drag events should rebuild one candidate once."""
    shapes = [object() for _index in range(2000)]
    build_calls = []

    def build_candidate(
        shape: object,
        index: int,
        interactive: bool,
    ) -> RectangleCandidate:
        """Build a lightweight candidate while recording adapter work."""
        build_calls.append(index)
        return RectangleCandidate(
            candidate_id=id(shape),
            shape_index=index,
            label="person",
            shape_type="rectangle",
            bbox=(0.0, 0.0, 20.0, 20.0),
            interactive=interactive,
        )

    monitor = RectangleSizeMonitor(
        [_rule()],
        enabled=True,
        debounce_ms=5,
        candidate_builder=build_candidate,
    )
    monitor.replace_shapes(shapes)
    assert len(build_calls) == len(shapes)
    assert len(monitor.issues) == len(shapes)
    build_calls.clear()

    for _event_index in range(5000):
        monitor.invalidate_shape(shapes[1000])
    _wait(qapp)

    assert build_calls == [1000]
    assert len(monitor.issues) == len(shapes)


def test_evaluator_handles_twenty_thousand_candidates_with_label_lookup() -> (
    None
):
    """Compiled label lookup should keep a large pure scan comfortably bounded."""
    rules = tuple(_rule(f"label_{index}") for index in range(100))
    evaluator = RectangleSizeEvaluator(rules)
    candidates = tuple(
        RectangleCandidate(
            candidate_id=index,
            shape_index=index,
            label=f"label_{index % len(rules)}",
            shape_type="rectangle",
            bbox=(0.0, 0.0, 20.0, 20.0),
        )
        for index in range(20000)
    )

    started = time.perf_counter()
    issues = evaluator.evaluate(candidates)
    elapsed = time.perf_counter() - started

    assert len(issues) == len(candidates)
    assert elapsed < 2.0


def test_dense_five_hundred_overlay_layout_stays_interactive() -> None:
    """Spatial collision lookup should bound the dense overlay paint hot path."""
    items = tuple(
        OverlayLayoutItem(
            candidate_id=index,
            bbox=(
                float(index % 20),
                float(index // 20),
                float(index % 20 + 10),
                float(index // 20 + 10),
            ),
            box_width=80.0,
            box_height=36.0,
        )
        for index in range(500)
    )

    started = time.perf_counter()
    placements = layout_overlay_items(
        items,
        (0.0, 0.0, 1920.0, 1080.0),
    )
    elapsed = time.perf_counter() - started

    assert len(placements) == len(items)
    assert [item.candidate_id for item in placements] == list(range(500))
    assert elapsed < 2.5
