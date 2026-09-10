"""Verify finite four-region geometry independently of Qt."""

import math
import random

import pytest

from anylabeling.views.labeling import rect_edge_click as rec


@pytest.mark.parametrize(
    ("point", "edge"),
    [
        ((120, 200), "left"),
        ((80, 200), "left"),
        ((180, 200), "right"),
        ((220, 200), "right"),
        ((150, 130), "top"),
        ((120, 20), "top"),
        ((150, 270), "bottom"),
        ((150, 380), "bottom"),
        ((50, 200), "left"),
        ((250, 200), "right"),
        ((150, 0), "top"),
        ((150, 400), "bottom"),
    ],
)
def test_regions_inside_outside_and_outer_boundary(
    point: rec.Point, edge: str
) -> None:
    """Map each side, including the old nearest-line counterexample."""
    assert rec.classify((100, 100, 200, 300), point).edge == edge


@pytest.mark.parametrize("box", [(0, 0, 100, 100), (0, 0, 30, 400)])
@pytest.mark.parametrize("factor", [-2, -1, -0.3, 0, 0.3, 1, 2])
def test_diagonals_and_finite_extensions(box: rec.Box, factor: float) -> None:
    """Reject both diagonal lines, including their outer endpoints."""
    left, top, right, bottom = box
    a, b = (right - left) / 2, (bottom - top) / 2
    for sign in (-1, 1):
        point = (left + a + factor * a, top + b + sign * factor * b)
        assert rec.classify(box, point).reason == rec.REASON_DEAD_ZONE


def test_range_precedes_infinite_line_rejection() -> None:
    """A diagonal beyond the finite range is no longer a dead zone."""
    box = (100, 100, 200, 300)
    assert rec.effective_box(box) == (50, 0, 250, 400)
    for point in ((49.9, 200), (250.1, 200), (0, -100)):
        assert rec.classify(box, point).reason == rec.REASON_OUT_OF_RANGE


def test_band_scale_cap_and_closed_boundary() -> None:
    """Keep band widths predictable with zoom and include the exact edge."""
    assert rec.dead_band_half_width((0, 0, 20, 100), 1) == 1
    box = (0, 0, 600, 800)
    assert rec.dead_band_half_width(box, 1) == 6
    assert rec.dead_band_half_width(box, 2) == 3
    assert rec.dead_band_half_width(box, 0) == 6
    # A 3-4-5 diagonal: at (300, 410), the perpendicular distance is 6.
    assert rec.classify(box, (300, 410)).reason == rec.REASON_DEAD_ZONE
    assert rec.classify(box, (300, 410.01)).edge == "bottom"


@pytest.mark.parametrize(
    "box", [(0, 0, 0, 10), (0, 0, 10, 0), (10, 0, 0, 20), (0, 0, math.nan, 10)]
)
def test_invalid_boxes(box: rec.Box) -> None:
    """Reject degenerate and nonfinite input before dividing."""
    assert rec.classify(box, (1, 1)).reason == rec.REASON_INVALID_BOX


def test_region_geometry_properties() -> None:
    """Keep three sides, contain the old center, and expand only outside."""
    randomizer = random.Random(904)
    for width, height in ((20, 400), (400, 20), (100, 100)):
        box = (100, 100, 100 + width, 100 + height)
        cx, cy = 100 + width / 2, 100 + height / 2
        for _ in range(500):
            point = (
                cx + randomizer.uniform(-width, width),
                cy + randomizer.uniform(-height, height),
            )
            decision = rec.classify(box, point)
            if decision.edge is None:
                continue
            new = rec.proposed_box(box, decision.edge, point)
            assert sum(a != b for a, b in zip(box, new)) == 1
            assert new[0] < cx < new[2] and new[1] < cy < new[3]
            outside = not (
                box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]
            )
            expanded = (
                new[0] < box[0]
                or new[1] < box[1]
                or new[2] > box[2]
                or new[3] > box[3]
            )
            assert expanded == outside
