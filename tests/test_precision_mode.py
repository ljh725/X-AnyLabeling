"""Tests for mouse precision control mode."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore  # noqa: E402

from anylabeling.views.labeling.widgets.canvas import Canvas  # noqa: E402


# ----------------------------------------------------------------------
# task 7.9: precision drag scales delta by 1/precision_factor
# ----------------------------------------------------------------------
def test_7_9_precision_scales_delta_by_factor(canvas):
    """In precision mode, a raw delta of 8px becomes 2px with factor=4."""
    c = canvas
    c.set_precision_factor(4)
    c.precision_mode_locked = True
    c.prev_point = QtCore.QPointF(100, 100)
    c._virtual_prev_point = None

    # Raw pos 8px away in x.
    raw = QtCore.QPointF(108, 100)
    eff = c._effective_drag_pos(raw, ev=None)

    # First call seeds virtual_prev_point from prev_point, then
    # eff = virtual + (raw - virtual)/4 = 100 + 8/4 = 102.
    assert eff.x() == 102.0, (
        "precision delta must be raw/4 = 2, got %s" % eff.x()
    )
    assert eff.y() == 100.0


def test_zoom_precision_mode_uses_canvas_scale_under_cap(canvas):
    """Zoom precision mode uses canvas scale while under the max factor."""
    c = canvas
    c.set_precision_mode("zoom")
    c.set_precision_max_factor(2.0)
    c.scale = 1.5
    c.precision_mode_locked = True
    c.prev_point = QtCore.QPointF(100, 100)
    c._virtual_prev_point = None

    raw = QtCore.QPointF(106, 100)
    eff = c._effective_drag_pos(raw, ev=None)

    assert c.precision_factor == 1.5
    assert eff.x() == 104.0
    assert eff.y() == 100.0


def test_zoom_precision_mode_caps_at_max_factor(canvas):
    """Zoom precision mode caps high zoom slowdown at max factor."""
    c = canvas
    c.set_precision_mode("zoom")
    c.set_precision_max_factor(2.0)
    c.scale = 4.0
    c.precision_mode_locked = True
    c.prev_point = QtCore.QPointF(100, 100)
    c._virtual_prev_point = None

    raw = QtCore.QPointF(108, 100)
    eff = c._effective_drag_pos(raw, ev=None)

    assert c.precision_factor == 2.0
    assert eff.x() == 104.0
    assert eff.y() == 100.0


def test_zoom_precision_mode_does_not_slow_below_100_percent(canvas):
    """Zoom precision mode clamps factors below 100% to 1."""
    c = canvas
    c.set_precision_mode("zoom")
    c.scale = 0.5

    assert c.precision_factor == 1.0


def test_7_9b_precision_off_passes_pos_through(canvas):
    """With precision off, _effective_drag_pos returns pos unchanged."""
    c = canvas
    c.precision_mode_locked = False
    raw = QtCore.QPointF(50, 60)
    eff = c._effective_drag_pos(raw, ev=None)
    assert eff.x() == 50 and eff.y() == 60
    assert c._virtual_prev_point is None


# ----------------------------------------------------------------------
# task 7.17: continuous precision drag accumulates without drift
# ----------------------------------------------------------------------
def test_7_17_continuous_precision_drag_no_drift(canvas):
    """Simulate a sequence of mouse moves: the virtual cursor tracks the
    scaled deltas, so the TOTAL image displacement equals total_raw/factor.
    No prev_point drift (D4 isolation)."""
    c = canvas
    c.set_precision_factor(4)
    c.precision_mode_locked = True
    c.prev_point = QtCore.QPointF(0, 0)
    c._virtual_prev_point = None

    # Feed real raw mouse positions: 4, 8, 12, ... 40. Each raw delta
    # contributes +1px to the virtual cursor. After 10 moves the virtual
    # cursor should be at x=10.
    for i in range(1, 11):
        raw = QtCore.QPointF(i * 4, 0)
        c._effective_drag_pos(raw, ev=None)

    assert c._virtual_prev_point.x() == 10.0, (
        "virtual cursor must accumulate 10*4/4 = 10, got %s"
        % c._virtual_prev_point.x()
    )
    # prev_point must be untouched (D4 isolation).
    assert c.prev_point.x() == 0.0
