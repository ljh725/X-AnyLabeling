"""Pure tests for extreme-boundary geometry and viewport planning."""

import pytest

from anylabeling.views.labeling.review_refinement.extreme import (
    ExtremeDraft,
    observation_view,
)


def test_extremes_ignore_unrelated_axes_and_keep_floats() -> None:
    """Boundary coordinates are assigned by role, never generic extrema."""
    draft = ExtremeDraft(300, 300)
    for point in [(1, 10.5), (80.25, 1), (299, 90.75), (20.5, 299)]:
        assert draft.accept(*point)
    assert draft.bbox() == (20.5, 10.5, 80.25, 90.75)


@pytest.mark.parametrize("point", [(10, -1), (300, 10), (float("nan"), 1)])
def test_invalid_points_leave_draft_unchanged(point: tuple) -> None:
    """Nonfinite or out-of-image inputs cannot advance the draft."""
    draft = ExtremeDraft(300, 300)
    assert not draft.accept(*point)
    assert draft.points == []


def test_reversed_boundary_is_rejected() -> None:
    """Invalid lower boundaries remain editable rather than swapping roles."""
    draft = ExtremeDraft(300, 300)
    assert draft.accept(50, 30)
    assert draft.accept(80, 40)
    assert not draft.accept(20, 29)
    assert draft.edge == "bottom"
    assert draft.accept(50, 90)
    assert not draft.accept(81, 50)
    draft.back()
    assert draft.edge == "bottom"


def test_same_position_can_express_adjacent_extremes() -> None:
    """A top-right corner can contribute both its y and its x."""
    draft = ExtremeDraft(300, 300)
    assert draft.accept(80, 10)
    assert draft.accept(80, 10)
    assert draft.accept(20, 90)
    assert draft.accept(20, 90)
    assert draft.bbox() == (20, 10, 80, 90)


@pytest.mark.parametrize(
    "bbox",
    [
        (0, 0, 1, 1),
        (20, 20, 90, 100),
        (0, 0, 1919, 1079),
        (1849, 999, 1919, 1079),
    ],
)
def test_observation_respects_scale_and_context(bbox: tuple) -> None:
    """Small, full-image and corner objects get valid bounded view plans."""
    zoom, x, y = observation_view(bbox, (1920, 1080), (900, 600))
    assert 1 <= zoom <= 800
    assert 0 <= x <= 1920 and 0 <= y <= 1080
    left, top, right, bottom = bbox
    padding_x = max((right - left) * 0.25, 16)
    padding_y = max((bottom - top) * 0.25, 16)
    roi_w = min(1920, right + padding_x) - max(0, left - padding_x)
    roi_h = min(1080, bottom + padding_y) - max(0, top - padding_y)
    assert roi_w * zoom / 100 <= 900
    assert roi_h * zoom / 100 <= 600
