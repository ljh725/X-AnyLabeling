"""Tests for Feature 4: local edge snapping scorer (task 7.11-7.13,
7.19, 7.22, 7.23).

Pure-Python unit tests for ``edge_snap.py``. Uses synthetic gradient
images with known strong edges to verify scoring, the dual-criterion
threshold (N3), and clamp/size guards.
"""

import numpy as np

from anylabeling.views.labeling.edge_snap import (
    DEFAULT_ABS_FLOOR,
    DEFAULT_K,
    EdgeSnapCache,
    best_snap_candidate,
    score_edge,
)


def _strong_vertical_edge(width=30, height=30, edge_x=15):
    """A grayscale image with a sharp vertical edge at ``edge_x``
    (dark left, bright right). Produces a strong x-gradient spike."""
    img = np.zeros((height, width), dtype=np.uint8)
    img[:, edge_x:] = 200
    return img


def _strong_horizontal_edge(width=30, height=30, edge_y=15):
    """A grayscale image with a sharp horizontal edge at ``edge_y``."""
    img = np.zeros((height, width), dtype=np.uint8)
    img[edge_y:, :] = 200
    return img


def _ensure(cache, gray):
    """Ensure the cache with a synthetic key derived from the array."""
    cache.ensure(gray, cache_key=id(gray))


# ----------------------------------------------------------------------
# task 7.11: strong edge -> snap to correct coord
# ----------------------------------------------------------------------
def test_7_11_snap_left_edge_to_strong_vertical():
    """A rectangle left edge at x=10 with a strong vertical edge at x=15
    must snap to the edge (x≈15, Sobel may peak at 14 or 15)."""
    gray = _strong_vertical_edge(edge_x=15)
    cache = EdgeSnapCache()
    _ensure(cache, gray)

    result = best_snap_candidate(
        cache,
        edge_name="left",
        current_coord=10.0,
        seg_lo=9,
        seg_hi=21,
        search_range=4,
    )
    assert result is not None, "must find the strong edge"
    coord, score = result
    # Sobel 3x3 peaks at the step boundary or one pixel before it.
    assert coord in (14, 15), f"must snap near x=15, got {coord}"
    assert score >= DEFAULT_ABS_FLOOR


def test_7_11b_snap_right_edge_to_strong_vertical():
    """Right edge at x=20 with strong vertical edge at x=16 -> snap ~16."""
    gray = _strong_vertical_edge(edge_x=16)
    cache = EdgeSnapCache()
    _ensure(cache, gray)

    result = best_snap_candidate(
        cache,
        edge_name="right",
        current_coord=20.0,
        seg_lo=9,
        seg_hi=21,
        search_range=4,
    )
    assert result is not None
    assert result[0] in (15, 16)


def test_7_11c_snap_top_edge_to_strong_horizontal():
    """Top edge at y=10 with strong horizontal edge at y=15 -> snap ~15."""
    gray = _strong_horizontal_edge(edge_y=15)
    cache = EdgeSnapCache()
    _ensure(cache, gray)

    result = best_snap_candidate(
        cache,
        edge_name="top",
        current_coord=10.0,
        seg_lo=9,
        seg_hi=21,
        search_range=4,
    )
    assert result is not None
    assert result[0] in (14, 15)


# ----------------------------------------------------------------------
# task 7.12: low response region -> no snap (None)
# ----------------------------------------------------------------------
def test_7_12_no_snap_in_low_response_region():
    """A flat (low-gradient) image must yield no accepted candidate."""
    gray = np.full((30, 30), 50, dtype=np.uint8)  # uniform, no gradient
    cache = EdgeSnapCache()
    _ensure(cache, gray)

    result = best_snap_candidate(
        cache,
        edge_name="left",
        current_coord=15.0,
        seg_lo=9,
        seg_hi=21,
        search_range=4,
    )
    assert result is None, "flat image must not snap"


def test_7_12b_edge_outside_search_range_not_found():
    """A strong edge beyond the ±4 search range yields no candidate."""
    gray = _strong_vertical_edge(edge_x=25)  # far from current=10
    cache = EdgeSnapCache()
    _ensure(cache, gray)

    result = best_snap_candidate(
        cache,
        edge_name="left",
        current_coord=10.0,
        seg_lo=9,
        seg_hi=21,
        search_range=4,  # only searches 6..14
    )
    assert result is None, "edge at x=25 is outside ±4 of x=10"


# ----------------------------------------------------------------------
# task 7.22 / 7.23: dual criterion (N3)
# ----------------------------------------------------------------------
def test_7_22_below_abs_floor_rejected_even_if_adaptive_passes():
    """When best_score >= k*local_max but < abs_floor: reject.

    Construct an image with a weak vertical edge (small step) whose
    Sobel response is below abs_floor. Adaptive passes (best ==
    local_max trivially) but abs_floor fails."""
    # Weak edge: gray 50 -> 52 at x=15. Sobel 3x3 response ~ 4*2 = 8,
    # below abs_floor=10.
    gray = np.full((30, 30), 50, dtype=np.uint8)
    gray[:, 15:] = 52
    cache = EdgeSnapCache()
    _ensure(cache, gray)

    result = best_snap_candidate(
        cache,
        edge_name="left",
        current_coord=10.0,
        seg_lo=9,
        seg_hi=21,
        search_range=4,
        k=DEFAULT_K,
        abs_floor=DEFAULT_ABS_FLOOR,
    )
    assert (
        result is None
    ), "weak edge (below abs_floor) must be rejected by dual criterion"


def test_7_23_below_adaptive_rejected_when_stronger_neighbor_in_window():
    """A weaker neighbor above abs_floor is rejected when the current
    edge is much stronger, proving the adaptive criterion is not vacuous."""

    class FakeCache:
        def __init__(self):
            self._grad_x = np.zeros((20, 20), dtype=np.float32)
            self._grad_x[:, 10] = 100.0  # current edge response
            self._grad_x[:, 13] = 40.0  # weaker neighbor above abs_floor
            self._grad_y = np.zeros((20, 20), dtype=np.float32)

        @property
        def grad_x(self):
            return self._grad_x

        @property
        def grad_y(self):
            return self._grad_y

    result = best_snap_candidate(
        FakeCache(),
        edge_name="left",
        current_coord=10.0,
        seg_lo=3,
        seg_hi=17,
        search_range=4,
        k=0.6,
        abs_floor=10.0,
    )
    assert result is None


def test_score_edge_returns_zero_out_of_bounds():
    """score_edge returns 0.0 for out-of-bounds coordinates."""
    gray = _strong_vertical_edge(edge_x=15)
    cache = EdgeSnapCache()
    _ensure(cache, gray)

    assert score_edge(cache, "left", coord=-5, seg_lo=5, seg_hi=20) == 0.0
    assert score_edge(cache, "left", coord=999, seg_lo=5, seg_hi=20) == 0.0


def test_score_edge_empty_segment_returns_zero():
    """An empty/inverted segment returns 0.0."""
    gray = _strong_vertical_edge(edge_x=15)
    cache = EdgeSnapCache()
    _ensure(cache, gray)

    assert score_edge(cache, "left", coord=15, seg_lo=20, seg_hi=5) == 0.0


# ----------------------------------------------------------------------
# cache invalidation (task 6.1)
# ----------------------------------------------------------------------
def test_cache_rebuilds_on_key_change():
    """ensure() rebuilds gradients when cache_key changes."""
    gray1 = _strong_vertical_edge(edge_x=15)
    gray2 = _strong_vertical_edge(edge_x=20)
    cache = EdgeSnapCache()
    _ensure(cache, gray1)
    g1 = cache.grad_x

    cache.ensure(gray2, cache_key="different_key")
    g2 = cache.grad_x
    # Rebuilt: different object (or at least reflects new image).
    assert g1 is not g2 or not np.array_equal(g1, g2)


def test_cache_reuses_on_same_key():
    """ensure() reuses gradients when cache_key is unchanged."""
    gray = _strong_vertical_edge(edge_x=15)
    cache = EdgeSnapCache()
    cache.ensure(gray, cache_key="k1")
    g1 = cache.grad_x
    cache.ensure(gray, cache_key="k1")
    g2 = cache.grad_x
    assert g1 is g2
