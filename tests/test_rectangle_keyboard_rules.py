"""Pure rectangle placement and method compatibility regressions."""

import pytest

from anylabeling.views.labeling.review_refinement.keyboard_fitting import (
    drawing_method,
    placement_error,
)


@pytest.mark.parametrize(
    "point,allowed",
    [
        ((25, 25), {"top", "left"}),
        ((75, 25), {"top", "right"}),
        ((25, 75), {"bottom", "left"}),
        ((75, 75), {"bottom", "right"}),
        ((50, 50), set()),
        ((50, 25), {"top"}),
        ((25, 50), {"left"}),
    ],
)
def test_half_planes(point: tuple, allowed: set) -> None:
    """Only the intended halves, including strict center lines, are allowed."""
    actual = {
        edge
        for edge in ("top", "right", "bottom", "left")
        if placement_error((20, 20, 80, 80), point, (100, 100), edge) is None
    }
    assert actual == allowed


def test_geometry_bounds_and_expansion() -> None:
    """Expansion is allowed inside the image without cropping invalid input."""
    assert (
        placement_error((20, 20, 80, 80), (0.25, 20), (100, 100), "left")
        is None
    )
    assert (
        placement_error((20, 20, 80, 80), (-1, 20), (100, 100), "left")
        == "pointer"
    )
    assert (
        placement_error(
            (20, 20, 80, 80), (float("nan"), 20), (100, 100), "left"
        )
        == "invalid"
    )
    assert (
        placement_error((0, 0, 1, 1), (0.4, 0), (100, 100), "left") == "size"
    )


def test_method_compatibility() -> None:
    """Old mappings retain two points and unknown methods do not silently run."""
    assert drawing_method({"mode": "rectangle"}) == "two_points"
    assert (
        drawing_method(
            {"mode": "rectangle", "drawing_method": "four_extremes"}
        )
        == "four_extremes"
    )
    with pytest.raises(ValueError):
        drawing_method({"mode": "rectangle", "drawing_method": "unknown"})
