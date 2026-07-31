"""Tests for pure multi-box rectangle-size overlay layout."""

from __future__ import annotations

import pytest

from anylabeling.views.labeling.rectangle_size import (
    OverlayLayoutItem,
    layout_overlay_items,
    pick_overlay_anchor,
)

VIEWPORT = (0.0, 0.0, 500.0, 400.0)


def _item(
    candidate_id,
    *,
    bbox=(100.0, 150.0, 220.0, 300.0),
    width=120.0,
    height=40.0,
    label_rect=None,
) -> OverlayLayoutItem:
    """Build one measured overlay layout item."""
    return OverlayLayoutItem(
        candidate_id=candidate_id,
        bbox=bbox,
        box_width=width,
        box_height=height,
        label_rect=label_rect,
    )


def _collides(first, second, gap=4.0) -> bool:
    """Return whether two placement rects overlap or violate their gap."""
    first_x, first_y, first_width, first_height = first
    second_x, second_y, second_width, second_height = second
    return not (
        first_x + first_width + gap <= second_x
        or second_x + second_width + gap <= first_x
        or first_y + first_height + gap <= second_y
        or second_y + second_height + gap <= first_y
    )


def test_single_item_preserves_legacy_anchor() -> None:
    """Extraction must not move the existing single rectangle prompt."""
    item = _item("one", label_rect=(100.0, 120.0, 90.0, 20.0))

    placement = layout_overlay_items([item], VIEWPORT)[0]
    expected = pick_overlay_anchor(
        item.bbox,
        item.box_width,
        item.box_height,
        6.0,
        VIEWPORT,
        label_rect=item.label_rect,
    )

    assert placement.rect[:2] == expected


def test_overlapping_targets_receive_distinct_noncolliding_boxes() -> None:
    """Two coincident shapes should retain two independently visible prompts."""
    placements = layout_overlay_items(
        [_item("first"), _item("second")],
        VIEWPORT,
    )

    assert [placement.candidate_id for placement in placements] == [
        "first",
        "second",
    ]
    assert not _collides(placements[0].rect, placements[1].rect)


def test_dense_cluster_preserves_all_items_and_stable_order() -> None:
    """Layout should never silently discard a multi-category issue."""
    items = [_item(index, width=85.0, height=28.0) for index in range(6)]

    first_run = layout_overlay_items(items, VIEWPORT)
    second_run = layout_overlay_items(items, VIEWPORT)

    assert len(first_run) == len(items)
    assert [placement.candidate_id for placement in first_run] == list(
        range(6)
    )
    assert first_run == second_run


def test_layout_clamps_boxes_to_panned_viewport() -> None:
    """Targets outside the visible region should still anchor inside it."""
    viewport = (500.0, 300.0, 900.0, 700.0)
    placement = layout_overlay_items(
        [_item("offscreen", bbox=(10.0, 10.0, 20.0, 20.0))],
        viewport,
    )[0]
    x, y, width, height = placement.rect

    assert x >= viewport[0]
    assert y >= viewport[1]
    assert x + width <= viewport[2]
    assert y + height <= viewport[3]


def test_impossibly_dense_viewport_keeps_every_placement() -> None:
    """Overlap fallback should preserve warnings even when no packing exists."""
    tiny_viewport = (0.0, 0.0, 80.0, 50.0)
    placements = layout_overlay_items(
        [
            _item("a", width=75.0, height=45.0),
            _item("b", width=75.0, height=45.0),
            _item("c", width=75.0, height=45.0),
        ],
        tiny_viewport,
    )

    assert [placement.candidate_id for placement in placements] == [
        "a",
        "b",
        "c",
    ]
    assert len(placements) == 3


@pytest.mark.parametrize(
    "items",
    [
        [_item("same"), _item("same")],
        [_item("bad-width", width=0.0)],
        [_item("bad-height", height=float("nan"))],
    ],
)
def test_invalid_layout_contract_fails_before_partial_output(items) -> None:
    """Invalid identities or dimensions should fail deterministically."""
    with pytest.raises(ValueError):
        layout_overlay_items(items, VIEWPORT)
