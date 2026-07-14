"""Tests for Feature 3: precision control mode (task 7.9, 7.10, 7.17,
7.20, 7.21).

Tests focus on the pure logic: virtual-cursor delta scaling, keyboard
edge cycling, undo merge behavior, and N1 (hover clears keyboard edge).
Mouse-event-level integration is covered by manual verification (8.5).
"""

import os
import time
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtGui  # noqa: E402

from anylabeling.views.labeling.widgets.canvas import Canvas  # noqa: E402
from tests.conftest import MockShape  # noqa: E402


def _rect_shape(x=0, y=0, w=10, h=10, gid=None):
    """A rectangle shape with 4 canonical corners (TL, TR, BR, BL)."""
    from PyQt6 import QtCore as _QtCore

    s = MockShape(shape_type="rectangle", group_id=gid)
    s.points = [
        _QtCore.QPointF(x, y),
        _QtCore.QPointF(x + w, y),
        _QtCore.QPointF(x + w, y + h),
        _QtCore.QPointF(x, y + h),
    ]
    s._invalidate_cache = lambda: None
    return s


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


# ----------------------------------------------------------------------
# task 5.9-5.11: keyboard edge cycling
# ----------------------------------------------------------------------
def test_keyboard_edge_cycle_left_top_right_bottom(canvas):
    """Tab cycles L -> T -> R -> B -> L, on a single rectangle."""
    c = canvas
    c.rect_edge_align_enabled = False
    shape = _rect_shape()
    c.selected_shapes = [shape]

    c._cycle_keyboard_edge()
    assert c.rect_edge_keyboard_edge == "left"
    c._cycle_keyboard_edge()
    assert c.rect_edge_keyboard_edge == "top"
    c._cycle_keyboard_edge()
    assert c.rect_edge_keyboard_edge == "right"
    c._cycle_keyboard_edge()
    assert c.rect_edge_keyboard_edge == "bottom"
    c._cycle_keyboard_edge()
    assert c.rect_edge_keyboard_edge == "left"


def test_keyboard_edge_cycle_emits_selected_edge(canvas):
    """Cycling the keyboard edge emits the selected edge name."""
    c = canvas
    captured = []
    c.keyboard_edge_selected.connect(captured.append)
    c.selected_shapes = [_rect_shape()]

    c._cycle_keyboard_edge()
    c._cycle_keyboard_edge()

    assert captured == ["left", "top"]


def test_tab_event_selects_keyboard_edge(canvas):
    """Canvas.event consumes Tab so Qt focus traversal does not steal it."""
    c = canvas
    c.selected_shapes = [_rect_shape()]
    event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_Tab,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )

    handled = c.event(event)

    assert handled is True
    assert c.rect_edge_keyboard_edge == "left"


def test_keyboard_edge_requires_single_rectangle(canvas):
    """Tab with no/multi selection or non-rectangle does nothing."""
    c = canvas
    c.rect_edge_align_enabled = True

    c.selected_shapes = []
    c._cycle_keyboard_edge()
    assert c.rect_edge_keyboard_edge is None

    polygon = MockShape(shape_type="polygon")
    c.selected_shapes = [polygon]
    c._cycle_keyboard_edge()
    assert c.rect_edge_keyboard_edge is None


def test_keyboard_edge_does_not_require_align_enabled(canvas):
    """Tab works even when rect_edge_align_enabled is off."""
    c = canvas
    c.rect_edge_align_enabled = False
    c.selected_shapes = [_rect_shape()]
    c._cycle_keyboard_edge()
    assert c.rect_edge_keyboard_edge == "left"


# ----------------------------------------------------------------------
# task 7.20 / N1: hover clears keyboard edge
# ----------------------------------------------------------------------
def test_7_20_hover_clears_keyboard_edge(canvas):
    """When a keyboard edge is active, _clear_keyboard_edge (called by
    the hover path) resets it. Direct unit test of the N1 contract."""
    c = canvas
    c.rect_edge_align_enabled = True
    shape = _rect_shape()
    c.selected_shapes = [shape]
    c._cycle_keyboard_edge()
    assert c.rect_edge_keyboard_edge == "left"

    cleared = c._clear_keyboard_edge()
    assert cleared is True
    assert c.rect_edge_keyboard_edge is None
    assert c.rect_edge_keyboard_shape is None

    # Second call returns False (nothing to clear).
    assert c._clear_keyboard_edge() is False


# ----------------------------------------------------------------------
# task 7.21 / N2/D5: undo merge window
# ----------------------------------------------------------------------
def test_7_21_undo_merge_within_window_replaces_last(canvas):
    """store_shapes(merge_window=0.5) within the window replaces the
    last snapshot instead of appending; outside the window appends."""
    c = canvas
    c.num_backups = 10
    c.shapes_backups = []
    c._last_snapshot_ts = 0.0
    c.shapes = []

    # First push (no merge).
    c.store_shapes(merge_window=0.5)
    assert len(c.shapes_backups) == 1

    # Immediate second push within window -> replace, not append.
    c.store_shapes(merge_window=0.5)
    assert (
        len(c.shapes_backups) == 1
    ), "within-window push must replace, not append"

    # Simulate time passing beyond the window.
    c._last_snapshot_ts = time.monotonic() - 1.0
    c.store_shapes(merge_window=0.5)
    assert len(c.shapes_backups) == 2, "outside-window push must append"


def test_store_shapes_default_no_merge_preserves_legacy(canvas):
    """Default merge_window=0.0 always appends (legacy behavior)."""
    c = canvas
    c.num_backups = 10
    c.shapes_backups = []
    c._last_snapshot_ts = 0.0
    c.shapes = []

    c.store_shapes()
    c.store_shapes()
    c.store_shapes()
    assert len(c.shapes_backups) == 3
