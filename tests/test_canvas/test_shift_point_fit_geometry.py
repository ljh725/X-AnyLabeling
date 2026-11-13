"""Behavior contract for rectangle point fitting in screen pixels."""

import pytest

from anylabeling.views.labeling.rect_edge_click import (
    corner_point,
    point_fit_decision,
    point_fit_inside_box,
    point_fit_lock_decision,
    proposed_inward_point_fit_box,
    proposed_point_fit_box,
)


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


@pytest.mark.parametrize("scale", [0.3, 1, 2])
def test_crossing_boundary_has_no_band_jump(scale):
    box = (100, 100, 200, 200)
    for y in (100, 100 - 0.1 / scale):
        assert point_fit_decision(box, (150 + 1.5 / scale, y), scale).edge == (
            "top_right"
        )


@pytest.mark.parametrize("scale", [0.3, 1, 2])
def test_thin_box_keeps_left_and_right_quadrants(scale):
    width = 1.5 / scale
    box = (0, 0, width, 100 / scale)
    assert point_fit_decision(box, (width * 0.1, 10 / scale), scale).edge == "top_left"
    assert point_fit_decision(box, (width * 0.9, 10 / scale), scale).edge == "top_right"
    assert point_fit_decision(box, (width / 2, 10 / scale), scale).edge is None


BOX = (100.0, 100.0, 200.0, 200.0)


def area(box) -> float:
    """Return the rectangle area for candidate comparisons."""
    left, top, right, bottom = box
    return (right - left) * (bottom - top)


@pytest.mark.parametrize(
    ("point", "corner", "expected"),
    [
        ((120.0, 120.0), "top_left", (100.0, 100.0, 120.0, 120.0)),
        ((180.0, 120.0), "top_right", (180.0, 100.0, 200.0, 120.0)),
        ((120.0, 180.0), "bottom_left", (100.0, 180.0, 120.0, 200.0)),
        ((180.0, 180.0), "bottom_right", (180.0, 180.0, 200.0, 200.0)),
    ],
)
def test_inward_fit_keeps_the_corner_of_the_clicked_quadrant(
    point: tuple[float, float], corner: str, expected
) -> None:
    """An interior point can also shrink to the sub-box under the cursor."""
    assert point_fit_decision(BOX, point, 1.0).edge == corner
    assert proposed_inward_point_fit_box(BOX, corner, point) == expected


def test_inward_fit_returns_the_smaller_of_the_two_candidates() -> None:
    """The default proposal contains the centre; the inward one cannot."""
    points = ((120.0, 120.0), (180.0, 130.0), (130.0, 180.0), (190.0, 190.0))
    for point in points:
        decision = point_fit_decision(BOX, point, 1.0)
        assert decision.edge is not None
        default_box = proposed_point_fit_box(BOX, decision.edge, point)
        inward_box = proposed_inward_point_fit_box(BOX, decision.edge, point)
        assert 0 < area(inward_box) < area(default_box)


@pytest.mark.parametrize("scale", [0.5, 1.0, 2.0])
def test_inward_fit_stays_inside_the_original_box(scale: float) -> None:
    """Interior points always produce a sub-box of the source rectangle."""
    for offset in (5.0, 20.0, 45.0):
        point = (150.0 + offset, 150.0 + offset)
        decision = point_fit_decision(BOX, point, scale)
        assert decision.edge == "bottom_right"
        left, top, right, bottom = proposed_inward_point_fit_box(
            BOX, decision.edge, point
        )
        assert 100.0 <= left and 100.0 <= top
        assert right <= 200.0 and bottom <= 200.0


def test_inward_fit_anchors_the_quadrant_corner_outside_the_box() -> None:
    """Outside points keep the quadrant corner fixed, not the far one."""
    point = (250.0, 50.0)
    assert point_fit_decision(BOX, point, 1.0).edge == "top_right"
    assert proposed_inward_point_fit_box(BOX, "top_right", point) == (
        200.0,
        50.0,
        250.0,
        100.0,
    )


def test_inward_fit_never_inverts_the_box() -> None:
    """Every quadrant keeps right > left and bottom > top."""
    for x in (101.0, 120.0, 149.0, 151.0, 180.0, 199.0):
        for y in (101.0, 120.0, 149.0, 151.0, 180.0, 199.0):
            decision = point_fit_decision(BOX, (x, y), 1.0)
            if decision.edge is None:
                continue
            left, top, right, bottom = proposed_inward_point_fit_box(
                BOX, decision.edge, (x, y)
            )
            assert right > left and bottom > top


def test_corner_point_reports_each_named_corner() -> None:
    """Corner names map to the expected box vertex."""
    assert corner_point(BOX, "top_left") == (100.0, 100.0)
    assert corner_point(BOX, "top_right") == (200.0, 100.0)
    assert corner_point(BOX, "bottom_right") == (200.0, 200.0)
    assert corner_point(BOX, "bottom_left") == (100.0, 200.0)


@pytest.mark.parametrize(
    "proposal", [proposed_point_fit_box, proposed_inward_point_fit_box]
)
def test_unknown_corner_is_rejected(proposal) -> None:
    """Both proposals keep the original ValueError contract."""
    with pytest.raises(ValueError):
        proposal(BOX, "center", (150.0, 150.0))


@pytest.mark.parametrize("scale", [0.3, 0.5, 1, 2, 4])
def test_hover_corner_survives_jitter_but_can_switch_both_axes(scale):
    box = (100, 100, 100 + 12 / scale, 100 + 12 / scale)
    cx, cy = 100 + 6 / scale, 100 + 6 / scale
    corner = "top_right"
    for dx, dy in ((2, -2), (-2, 2), (0, 0), (2, 2)):
        corner = point_fit_decision(
            box, (cx + dx / scale, cy + dy / scale), scale,
            previous_corner=corner,
        ).edge
        assert corner == "top_right"
    assert point_fit_decision(
        box, (cx - 4 / scale, cy + 4 / scale), scale,
        previous_corner=corner,
    ).edge == "bottom_left"


def test_tiny_box_caps_hover_buffer_to_keep_opposite_corner_reachable():
    box = (0, 0, 1.5, 1.5)
    assert point_fit_decision(
        box, (0.15, 1.35), previous_corner="top_right",
    ).edge == "bottom_left"


def test_strict_inside_excludes_the_original_outline() -> None:
    """A lock entry needs a point strictly inside the rectangle."""
    assert point_fit_inside_box(BOX, (150.0, 150.0))
    assert point_fit_inside_box(BOX, (100.5, 199.5))
    for point in (
        (100.0, 150.0),
        (200.0, 150.0),
        (150.0, 100.0),
        (150.0, 200.0),
        (100.0, 100.0),
        (200.0, 200.0),
        (99.0, 150.0),
        (250.0, 150.0),
    ):
        assert not point_fit_inside_box(BOX, point)


def test_inside_box_rejects_unusable_rectangles() -> None:
    """Degenerate and non-finite geometry never starts a lock."""
    assert not point_fit_inside_box((100, 100, 100, 200), (100, 150))
    assert not point_fit_inside_box((100, 200, 200, 100), (150, 150))
    assert not point_fit_inside_box(BOX, (float("nan"), 150))
    assert not point_fit_inside_box(BOX, (float("inf"), 150))
    assert not point_fit_inside_box(
        (float("nan"), 100, 200, 200), (150, 150)
    )


@pytest.mark.parametrize("scale", [0.5, 1.0, 2.0])
def test_lock_decision_waits_in_the_centre_buffer(scale: float) -> None:
    """The first lock decision reuses the existing screen buffer."""
    point = (150.0 + 1.5 / scale, 120.0)
    assert point_fit_lock_decision(BOX, point, scale).edge == "top_right"
    for distance in (0.0, 0.5, 1.0):
        waiting = point_fit_lock_decision(
            BOX, (150.0 + distance / scale, 120.0), scale
        )
        assert waiting.edge is None
        assert waiting.reason == "dead_zone"


def test_lock_decision_rejects_edge_and_outside_starts() -> None:
    """Only a strictly inside press may lock an original corner."""
    for point in (
        (100.0, 120.0),
        (200.0, 120.0),
        (120.0, 100.0),
        (120.0, 200.0),
        (250.0, 120.0),
        (150.0, 320.0),
    ):
        decision = point_fit_lock_decision(BOX, point, 1.0)
        assert decision.edge is None
        assert decision.reason == "outside"


@pytest.mark.parametrize("scale", [0.3, 1.0, 2.0])
def test_small_box_lock_zones_survive_zoom(scale: float) -> None:
    """Each of the four zones stays reachable in a 12-screen-pixel box."""
    left, top = 100.0, 100.0
    right = left + 12 / scale
    bottom = top + 12 / scale
    box = (left, top, right, bottom)
    for fraction, corner in (
        ((0.1, 0.1), "top_left"),
        ((0.9, 0.1), "top_right"),
        ((0.1, 0.9), "bottom_left"),
        ((0.9, 0.9), "bottom_right"),
    ):
        point = (
            left + (right - left) * fraction[0],
            top + (bottom - top) * fraction[1],
        )
        assert point_fit_lock_decision(box, point, scale).edge == corner


@pytest.mark.parametrize(
    ("point", "expected"),
    [
        ((120.0, 120.0), (120.0, 100.0, 200.0, 120.0)),
        ((50.0, 50.0), (50.0, 50.0, 200.0, 100.0)),
        ((250.0, 50.0), (200.0, 50.0, 250.0, 100.0)),
        ((50.0, 250.0), (50.0, 100.0, 200.0, 250.0)),
        ((250.0, 250.0), (200.0, 100.0, 250.0, 250.0)),
    ],
)
def test_locked_corner_can_cross_its_own_axes(point, expected) -> None:
    """The fixed top-right corner stays put and becomes another corner."""
    assert proposed_inward_point_fit_box(BOX, "top_right", point) == expected
