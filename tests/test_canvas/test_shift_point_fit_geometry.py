"""Behavior contract for rectangle point fitting in screen pixels."""

import pytest

from anylabeling.views.labeling.rect_edge_click import point_fit_decision


@pytest.mark.parametrize("scale", [0.5, 1.0, 2.0])
def test_inside_point_uses_one_screen_pixel_band(scale: float) -> None:
    """Inside points beyond one screen pixel can determine a corner."""
    box = (100.0, 100.0, 200.0, 200.0)
    point = (150.0 + 1.5 / scale, 120.0)
    assert point_fit_decision(box, point, scale).edge == "top_right"


@pytest.mark.parametrize("scale", [0.5, 1.0, 2.0])
def test_inside_point_at_or_within_band_is_ambiguous(scale: float) -> None:
    """Points at or within one screen pixel remain uncommittable."""
    box = (100.0, 100.0, 200.0, 200.0)
    for distance in (0.0, 0.5, 1.0):
        point = (150.0 + distance / scale, 120.0)
        assert point_fit_decision(box, point, scale).reason == "dead_zone"


def test_outside_point_preserves_old_eight_pixel_band() -> None:
    """Outside points still use the original eight-screen-pixel band."""
    box = (100.0, 100.0, 200.0, 200.0)
    assert point_fit_decision(box, (151.5, 90.0)).reason == "dead_zone"
    assert point_fit_decision(box, (159.0, 90.0)).edge == "top_right"


def test_rectangle_boundary_uses_inside_rule() -> None:
    """A point on the original edge belongs to the inside rule."""
    assert point_fit_decision((100, 100, 200, 200), (151.5, 100)).edge == (
        "top_right"
    )
