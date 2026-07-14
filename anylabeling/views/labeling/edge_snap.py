"""Local edge snapping scorer (Feature 4).

Pure Python (no PyQt6 dependency) so it can be unit-tested in isolation.
Given a grayscale image and a rectangle edge, this module finds the
strongest nearby edge coordinate along the edge's normal direction,
scored by median Sobel-gradient response aggregated over the edge's
middle segment.

The reliability threshold uses a dual criterion (N3):
  accept iff best_score >= k * local_max_response
           and best_score >= abs_floor

``local_max_response`` is the max candidate score within the search
window (adaptive, keeps behavior consistent across contrast levels);
``abs_floor`` prevents sparse-texture images from snapping to weak
responses.

All public functions accept plain numpy arrays / Python scalars, so the
module is fully testable without Qt.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

# Default dual-criterion thresholds (task 6.8: v0 internal, config hook).
DEFAULT_K = 0.6  # adaptive: score must reach 60% of local window max
DEFAULT_ABS_FLOOR = 10.0  # absolute gradient-strength floor

# Fraction of the edge length sampled at the middle (avoid corner noise).
# Samples the central 60% of the edge (drop 20% at each end).
DEFAULT_MIDDLE_FRACTION = 0.6


class EdgeSnapCache:
    """Lazy grayscale + gradient cache, keyed by image identity.

    Built on first ``ensure()``; invalidated when ``cache_key`` changes
    (e.g. pixmap cacheKey() on image switch — task 6.1).
    """

    def __init__(self) -> None:
        self._key: object = None
        self._gray: Optional[np.ndarray] = None
        self._grad_x: Optional[np.ndarray] = None
        self._grad_y: Optional[np.ndarray] = None

    def ensure(self, gray: np.ndarray, cache_key: object) -> None:
        """Build/refresh the gradient cache if ``cache_key`` changed.

        Args:
            gray: 2D uint8/float grayscale image (HxW).
            cache_key: Identity token (e.g. pixmap cacheKey). A change
                triggers a rebuild.
        """
        if (
            self._key == cache_key
            and self._gray is not None
            and self._gray.shape == gray.shape
        ):
            return
        self._gray = gray.astype(np.float32)
        # Sobel filters for x/y gradients. cv2 is available in the repo
        # (label_widget.py imports it); import lazily to keep this module
        # importable in environments without cv2 for non-snap paths.
        import cv2

        self._grad_x = cv2.Sobel(self._gray, cv2.CV_32F, 1, 0, ksize=3)
        self._grad_y = cv2.Sobel(self._gray, cv2.CV_32F, 0, 1, ksize=3)
        self._key = cache_key

    @property
    def grad_x(self) -> np.ndarray:
        if self._grad_x is None:
            raise RuntimeError("EdgeSnapCache.ensure() not called")
        return self._grad_x

    @property
    def grad_y(self) -> np.ndarray:
        if self._grad_y is None:
            raise RuntimeError("EdgeSnapCache.ensure() not called")
        return self._grad_y


def _edge_axis(edge_name: str) -> str:
    """Return the search axis ('x' or 'y') for an edge name."""
    if edge_name in ("left", "right"):
        return "x"
    if edge_name in ("top", "bottom"):
        return "y"
    raise ValueError(f"Unknown edge name: {edge_name}")


def _middle_segment(
    p1_y: float, p2_y: float, fraction: float = DEFAULT_MIDDLE_FRACTION
) -> Tuple[float, float]:
    """Return the (start, end) of the central segment along the edge."""
    lo, hi = min(p1_y, p2_y), max(p1_y, p2_y)
    span = hi - lo
    margin = span * (1.0 - fraction) / 2.0
    return lo + margin, hi - margin


def score_edge(
    cache: EdgeSnapCache,
    edge_name: str,
    coord: float,
    seg_lo: float,
    seg_hi: float,
) -> float:
    """Score a candidate edge coordinate by median normal-direction
    gradient magnitude along the middle segment.

    Args:
        cache: Gradient cache (must be ensured).
        edge_name: One of left/right/top/bottom.
        coord: Candidate coordinate along the search axis.
        seg_lo, seg_hi: Middle-segment bounds along the edge direction.

    Returns:
        Median gradient magnitude (float). 0.0 if the segment is empty.
    """
    axis = _edge_axis(edge_name)
    grad = cache.grad_x if axis == "x" else cache.grad_y

    # Sample rows (or columns) along the middle segment, clamped to image.
    ci = int(round(coord))
    if axis == "x":
        h, w = grad.shape
        if ci < 1 or ci >= w - 1:
            return 0.0
        lo_i = max(1, int(round(seg_lo)))
        hi_i = min(h - 1, int(round(seg_hi)))
        if hi_i <= lo_i:
            return 0.0
        col = np.abs(grad[lo_i:hi_i, ci])
    else:
        h, w = grad.shape
        ri = int(round(coord))
        if ri < 1 or ri >= h - 1:
            return 0.0
        lo_i = max(1, int(round(seg_lo)))
        hi_i = min(w - 1, int(round(seg_hi)))
        if hi_i <= lo_i:
            return 0.0
        col = np.abs(grad[ri, lo_i:hi_i])

    if col.size == 0:
        return 0.0
    return float(np.median(col))


def best_snap_candidate(
    cache: EdgeSnapCache,
    edge_name: str,
    current_coord: float,
    seg_lo: float,
    seg_hi: float,
    search_range: int = 4,
    k: float = DEFAULT_K,
    abs_floor: float = DEFAULT_ABS_FLOOR,
) -> Optional[Tuple[float, float]]:
    """Find the best snap candidate near ``current_coord``.

    Searches integer coordinates in ``[current_coord - search_range,
    current_coord + search_range]``. The current coord participates in
    the local reliability baseline, but snap candidates exclude it so a
    no-op is reported as failure.

    Args:
        cache: Gradient cache (ensured).
        edge_name: One of left/right/top/bottom.
        current_coord: The edge's current coordinate along its axis.
        seg_lo, seg_hi: Middle-segment bounds along the edge direction.
        search_range: Half-window size in image pixels (default 4).
        k: Adaptive threshold factor (default 0.6).
        abs_floor: Absolute gradient-strength floor (default 10.0).

    Returns:
        ``(coord, score)`` of the best accepted neighbor, or ``None`` if
        no neighbor passes the dual criterion. The current coord is used
        only for the adaptive baseline; snapping to the same place is a
        no-op and reported as failure.
    """
    base = int(round(current_coord))
    window: List[int] = list(
        range(base - search_range, base + search_range + 1)
    )

    window_scored = [
        (c, score_edge(cache, edge_name, c, seg_lo, seg_hi))
        for c in window
    ]
    window_scored = [(c, s) for c, s in window_scored if s > 0.0]
    if not window_scored:
        return None

    # Include the current coord in the adaptive baseline. This makes the
    # relative threshold meaningful: a weaker neighbor will not be chosen
    # when the current edge already has a stronger local response.
    local_max = max(s for _, s in window_scored)
    scored = [(c, s) for c, s in window_scored if c != base]
    if not scored:
        return None
    best_coord, best_score = max(scored, key=lambda cs: cs[1])

    # Dual criterion (N3): adaptive + absolute floor, both required.
    if best_score >= k * local_max and best_score >= abs_floor:
        return best_coord, best_score
    return None
