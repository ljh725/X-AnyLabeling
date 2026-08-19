"""Tests for discrete rectangle-edge nudge helpers."""

from anylabeling.views.labeling.review_refinement.nudge import (
    NudgeBurstTracker,
    WheelAccumulator,
    nudge_delta,
    valid_edge_nudge,
)


def test_nudge_burst_groups_same_key_for_undo() -> None:
    """Only the first compatible nudge starts an undo unit."""
    tracker = NudgeBurstTracker()
    assert tracker.begin(("target", "left", 1, "wheel"), 0.0)
    assert not tracker.begin(("target", "left", 1, "wheel"), 0.4)
    assert tracker.begin(("target", "left", -1, "wheel"), 0.4)
    assert tracker.begin(("target", "left", -1, "wheel"), 1.0)


def test_wheel_accumulator_handles_angle_and_pixel_delta() -> None:
    """Only complete wheel notches should create commands."""
    wheel = WheelAccumulator()
    assert wheel.add(angle_delta=60) == 0
    assert wheel.add(angle_delta=60) == 1
    assert wheel.add(pixel_delta=60) == 0
    assert wheel.add(pixel_delta=60) == 1


def test_nudge_direction_is_axis_aligned() -> None:
    """Each edge maps to one image axis."""
    assert nudge_delta("left", -1, 5) == (-5.0, 0.0)
    assert nudge_delta("bottom", 1, 1) == (0.0, 1.0)


def test_invalid_nudge_is_rejected_without_implicit_clamp() -> None:
    """Bounds and minimum size reject unsafe candidates."""
    bbox = (0.0, 2.0, 10.0, 10.0)
    assert not valid_edge_nudge(bbox, "left", -1, 1, (20, 20))
    assert valid_edge_nudge(bbox, "right", 1, 1, (20, 20))
