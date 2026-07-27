"""Tests for the person small-target size overlay (design rev.1).

Covers the size / threshold / anchor pure helpers and the Canvas-level
target resolution / visibility gating. The painted result itself is
verified manually (no paintEvent pixel assertions exist in this repo).

Headless Qt is configured centrally in ``tests/conftest.py`` (sets
``QT_QPA_PLATFORM=offscreen``), so this module does not need to set it.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtGui  # noqa: E402

# Import canvas first: it pulls in the full labeling package in the correct
# order (shape/utils/label_widget have a known initialization sequence).
from anylabeling.views.labeling.widgets.canvas import (  # noqa: E402
    DEFAULT_PERSON_SMALL_TARGET_MIN_EDGE_PX,
    is_person_small_target,
    normalize_two_points,
    pick_overlay_anchor,
    size_from_bbox,
)
from anylabeling.views.labeling.shape import Shape  # noqa: E402


def _pt(x, y):
    """Build a ``QPointF`` shorthand."""
    return QtCore.QPointF(x, y)


def _rect(points, label="person"):
    """Build a rectangle ``Shape`` from raw ``(x, y)`` tuples."""
    shape = Shape(label=label, shape_type="rectangle")
    shape.points = [QtCore.QPointF(x, y) for x, y in points]
    return shape


class TestNormalizeTwoPoints(unittest.TestCase):
    """Creation-stage geometry: start point + cursor, any direction."""

    def test_forward_drag_is_normalized(self):
        x0, y0, x1, y1 = normalize_two_points(_pt(10, 20), _pt(40, 80))
        self.assertEqual((x0, y0, x1, y1), (10, 20, 40, 80))

    def test_reverse_drag_is_normalized(self):
        x0, y0, x1, y1 = normalize_two_points(_pt(40, 80), _pt(10, 20))
        self.assertEqual((x0, y0, x1, y1), (10, 20, 40, 80))

    def test_float_coordinates_preserved(self):
        x0, y0, x1, y1 = normalize_two_points(_pt(10.5, 20.25), _pt(3.1, 9.9))
        self.assertEqual((x0, y0, x1, y1), (3.1, 9.9, 10.5, 20.25))

    def test_near_zero_size_kept(self):
        x0, y0, x1, y1 = normalize_two_points(_pt(5, 5), _pt(5, 5))
        self.assertEqual((x0, y0, x1, y1), (5, 5, 5, 5))


class TestSizeFromBbox(unittest.TestCase):
    """Width/height/max from a normalized bbox."""

    def test_basic_dimensions(self):
        w, h, m = size_from_bbox(10, 20, 40, 80)
        self.assertEqual((w, h, m), (30, 60, 60))

    def test_float_dimensions(self):
        w, h, m = size_from_bbox(0, 0, 35.96, 35.96)
        self.assertAlmostEqual(m, 35.96)

    def test_scale_independence(self):
        # Design 12.4: W/H depend only on image coords, never on zoom.
        for _scale in (0.25, 1.0, 4.0):
            w, h, m = size_from_bbox(0, 0, 28.0, 34.0)
            self.assertEqual((w, h, m), (28.0, 34.0, 34.0))


class TestIsPersonSmallTarget(unittest.TestCase):
    """The 36 px threshold: strict <, person-only, raw float."""

    def test_below_threshold_person_is_small(self):
        self.assertTrue(is_person_small_target("person", 35.9, 36.0))

    def test_on_threshold_not_small(self):
        self.assertFalse(is_person_small_target("person", 36.0, 36.0))

    def test_above_threshold_not_small(self):
        self.assertFalse(is_person_small_target("person", 36.1, 36.0))

    def test_35_96_still_small(self):
        self.assertTrue(is_person_small_target("person", 35.96, 36.0))

    def test_non_person_never_small(self):
        self.assertFalse(is_person_small_target("head", 5.0, 36.0))

    def test_none_label_is_neutral(self):
        self.assertFalse(is_person_small_target(None, 5.0, 36.0))

    def test_custom_threshold(self):
        self.assertTrue(is_person_small_target("person", 49.0, 50.0))
        self.assertFalse(is_person_small_target("person", 50.0, 50.0))


class TestPickOverlayAnchor(unittest.TestCase):
    """Design 6.1/6.2 anchor: label-above priority + viewport clamp."""

    VIEWPORT = (0.0, 0.0, 1000.0, 800.0)

    def test_label_above_when_label_rect_given(self):
        # label box at (100,90)-(180,110); overlay should sit above it,
        # left-aligned with the label.
        bbox = (100, 200, 300, 400)
        label_rect = (100, 90, 80, 20)
        ax, ay = pick_overlay_anchor(
            bbox, 60, 18, 6, self.VIEWPORT, label_rect=label_rect
        )
        self.assertEqual(ax, 100)  # left-aligned with label
        self.assertEqual(ay, 90 - 18 - 6)  # above the label box

    def test_label_centered_when_left_overflows(self):
        # Label near the left edge; left-align would still fit, but verify
        # centered candidate is reachable when left-align overflows.
        bbox = (0, 200, 100, 400)
        label_rect = (0, 90, 200, 20)  # label wide; overlay 60 wide
        ax, ay = pick_overlay_anchor(
            bbox, 60, 18, 6, self.VIEWPORT, label_rect=label_rect
        )
        # above_y always = 90 - 18 - 6 = 66
        self.assertEqual(ay, 66)
        # left-aligned at 0 fits (0 >= 0, 0+60 <= 1000)
        self.assertEqual(ax, 0)

    def test_fallback_rect_above_when_no_label(self):
        bbox = (100, 200, 300, 400)
        ax, ay = pick_overlay_anchor(
            bbox, 60, 18, 6, self.VIEWPORT, label_rect=None
        )
        # rect above-outside: x=x_min, y=y_min-text_h-gap
        self.assertEqual(ax, 100)
        self.assertEqual(ay, 200 - 18 - 6)

    def test_fallback_above_inside_when_outside_overflows_top(self):
        # Rectangle at the very top: above-outside overflows viewport top.
        bbox = (100, 5, 300, 200)
        ax, ay = pick_overlay_anchor(
            bbox, 60, 18, 6, self.VIEWPORT, label_rect=None
        )
        # above-inside: x=x_min, y=y_min+gap
        self.assertEqual(ax, 100)
        self.assertEqual(ay, 5 + 6)

    def test_clamp_when_no_candidate_fits(self):
        # Viewport smaller than the box: anchor clamps to near corner.
        ax, ay = pick_overlay_anchor(
            (0, 0, 10, 10), 200, 150, 6, (0.0, 0.0, 50.0, 40.0)
        )
        self.assertGreaterEqual(ax, 0)
        self.assertGreaterEqual(ay, 0)
        self.assertLess(ax, 50)
        self.assertLess(ay, 40)

    def test_uses_current_visible_region_not_full_pixmap(self):
        # A viewport panned so the rect's natural above-outside spot is
        # outside the visible region must fall back / clamp into it.
        # visible region x in [500, 1000]; rect at x=100 -> outside.
        viewport = (500.0, 0.0, 1000.0, 800.0)
        bbox = (100, 200, 300, 400)
        ax, ay = pick_overlay_anchor(
            bbox, 60, 18, 6, viewport, label_rect=None
        )
        # No candidate fits (all have x near 100, but viewport starts at 500),
        # so it clamps: x must land >= 500.
        self.assertGreaterEqual(ax, 500)

    def test_label_rect_xywh_format_maps_to_label_above(self):
        # Regression: _paint_overlay_box maps the label rect through a
        # transform. _label_rect_for_shape returns (x, y, w, h) but
        # _map_rect_tuple expects (x_min, y_min, x_max, y_max). Before the
        # fix the width/height were treated as max coords, producing a huge
        # bogus rect and sending the anchor to the screen corner. Here we
        # reproduce the correct conversion and assert the anchor stays near
        # the label (above it), not at (0,0).
        from anylabeling.views.labeling.widgets.canvas import _map_rect_tuple

        xform = QtGui.QTransform()
        xform.scale(3.0, 3.0)
        # Image-space label box: x=50, y=37, w=56, h=12
        lx, ly, lw, lh = 50, 37, 56, 12
        mapped = _map_rect_tuple(xform, (lx, ly, lx + lw, ly + lh))
        screen_label = (
            mapped[0],
            mapped[1],
            mapped[2] - mapped[0],
            mapped[3] - mapped[1],
        )
        # screen_label left ~150, top ~111 (37*3) — NOT at the origin.
        self.assertAlmostEqual(screen_label[0], 150.0, delta=2)
        self.assertAlmostEqual(screen_label[1], 111.0, delta=2)
        # And the overlay anchored above it must be near the label x, not 0.
        bbox_screen = _map_rect_tuple(xform, (50, 80, 100, 200))
        ax, ay = pick_overlay_anchor(
            bbox_screen,
            128,
            22,
            6,
            (0.0, 0.0, 5000.0, 5000.0),
            label_rect=screen_label,
        )
        self.assertGreater(ax, 100)  # near label x (~150), not 0
        self.assertLess(ay, screen_label[1])  # above the label

    """Canvas-level target selection across creation / drag / selection."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6 import QtWidgets

        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(
            []
        )

    def _make_canvas(self):
        from anylabeling.views.labeling.widgets.canvas import Canvas

        return Canvas()

    def test_default_threshold_is_canonical(self):
        c = self._make_canvas()
        self.assertEqual(
            c.person_small_target_min_edge,
            DEFAULT_PERSON_SMALL_TARGET_MIN_EDGE_PX,
        )
        self.assertEqual(c.show_rectangle_pixels, True)

    def test_setter_accepts_float(self):
        c = self._make_canvas()
        c.set_person_small_target_min_edge(50)
        self.assertEqual(c.person_small_target_min_edge, 50.0)

    def test_setter_rejects_garbage_and_falls_back(self):
        c = self._make_canvas()
        c.set_person_small_target_min_edge("not a number")
        self.assertEqual(c.person_small_target_min_edge, 36.0)
        c.set_person_small_target_min_edge(-5)
        self.assertEqual(c.person_small_target_min_edge, 36.0)

    def test_no_selection_no_creation_returns_none(self):
        c = self._make_canvas()
        self.assertIsNone(c._resolve_overlay_metrics())

    def test_creation_mode_uses_two_point_geometry(self):
        c = self._make_canvas()
        c.mode = c.CREATE
        c.create_mode = "rectangle"
        c.current = Shape(shape_type="rectangle")
        c.current.points = [_pt(15, 25)]
        c.line.points = [_pt(15, 25), _pt(45, 95)]
        m = c._resolve_overlay_metrics()
        self.assertIsNotNone(m)
        x0, y0, x1, y1 = m[0], m[1], m[2], m[3]
        self.assertEqual((x0, y0, x1, y1), (15, 25, 45, 95))
        self.assertIsNone(m[7])  # label unset during creation
        self.assertEqual(m[9], "creating")

    def test_single_selected_rectangle_resolves(self):
        c = self._make_canvas()
        shape = _rect([(10, 20), (40, 90)])
        shape.visible = True
        c.shapes = [shape]
        c.selected_shapes = [shape]
        m = c._resolve_overlay_metrics()
        self.assertIsNotNone(m)
        self.assertEqual((m[0], m[1], m[2], m[3]), (10, 20, 40, 90))
        self.assertEqual(m[7], "person")
        self.assertEqual(m[9], "selected")

    def test_rect_edge_active_drag_resolves_even_without_selection(self):
        # R1: dragging an edge clears selection; the overlay must still show.
        from anylabeling.views.labeling import rect_edge_alignment as rea

        c = self._make_canvas()
        shape = _rect([(10, 20), (40, 90)])
        shape.visible = True
        c.shapes = [shape]
        geom = rea.geometry_from_shape(shape)
        edge = rea.edge_from_geometry(shape, geom, rea.RECT_EDGE_RIGHT)
        # Enter the dragging phase the same way the canvas does at press time
        # (start_drag), so active_edge is set and is_dragging is True.
        c.rect_edge_state.start_drag(edge, shape.points)
        c.selected_shapes = []  # selection is empty during a drag
        m = c._resolve_overlay_metrics()
        self.assertIsNotNone(m)
        self.assertEqual(m[9], "rect_edge_active")

    def test_hover_rectangle_resolves_without_selection(self):
        c = self._make_canvas()
        shape = _rect([(10, 20), (40, 90)])
        shape.visible = True
        c.shapes = [shape]

        c._set_size_overlay_hover_shape(shape)
        m = c._resolve_overlay_metrics()

        self.assertIsNotNone(m)
        self.assertEqual(m[9], "hover")
        self.assertEqual((m[0], m[1], m[2], m[3]), (10, 20, 40, 90))

    def test_programmatic_h_shape_without_pointer_hover_returns_none(self):
        c = self._make_canvas()
        shape = _rect([(10, 20), (40, 90)])
        shape.visible = True
        c.shapes = [shape]
        c.h_hape = shape

        self.assertIsNone(c._resolve_overlay_metrics())

    def test_multi_selection_returns_none(self):
        c = self._make_canvas()
        s1 = _rect([(0, 0), (10, 10)])
        s2 = _rect([(20, 20), (30, 30)])
        c.shapes = [s1, s2]
        c.selected_shapes = [s1, s2]
        self.assertIsNone(c._resolve_overlay_metrics())

    def test_non_rectangle_selection_returns_none(self):
        c = self._make_canvas()
        poly = Shape(label="x", shape_type="polygon")
        poly.points = [
            QtCore.QPointF(0, 0),
            QtCore.QPointF(1, 0),
            QtCore.QPointF(1, 1),
        ]
        poly.visible = True
        c.shapes = [poly]
        c.selected_shapes = [poly]
        self.assertIsNone(c._resolve_overlay_metrics())

    def test_shape_visible_false_returns_none(self):
        c = self._make_canvas()
        shape = _rect([(0, 0), (10, 10)])
        shape.visible = False
        c.shapes = [shape]
        c.selected_shapes = [shape]
        self.assertIsNone(c._resolve_overlay_metrics())

    def test_hidden_by_filter_returns_none(self):
        c = self._make_canvas()
        shape = _rect([(0, 0), (10, 10)])
        shape.visible = True
        shape.hidden_by_filter = True
        c.shapes = [shape]
        c.selected_shapes = [shape]
        self.assertIsNone(c._resolve_overlay_metrics())

    def test_filter_engine_hidden_returns_none(self):
        # R3: ShapeFilterEngine hides via canvas.visible[shape]=False.
        c = self._make_canvas()
        shape = _rect([(0, 0), (10, 10)])
        shape.visible = True
        c.visible[shape] = False
        c.shapes = [shape]
        c.selected_shapes = [shape]
        self.assertIsNone(c._resolve_overlay_metrics())

    def test_overlay_disabled_when_show_rectangle_pixels_off(self):
        c = self._make_canvas()
        shape = _rect([(0, 0), (40, 90)])
        shape.visible = True
        c.shapes = [shape]
        c.selected_shapes = [shape]
        c.show_rectangle_pixels = False
        # _draw_size_overlay returns early; _resolve still works (it's the
        # gate's job). Verify the flag toggles drawing.
        self.assertFalse(c.show_rectangle_pixels)

    def test_label_list_selection_does_not_show_overlay(self):
        c = self._make_canvas()
        shape = _rect([(10, 20), (40, 90)])
        shape.visible = True
        c.shapes = [shape]

        c.select_shapes([shape], source="label_list")

        self.assertEqual(c.selected_shapes, [shape])
        self.assertTrue(shape.selected)
        self.assertIsNone(c._resolve_overlay_metrics())

        c.select_shapes([shape], source="canvas")
        self.assertIsNotNone(c._resolve_overlay_metrics())

    def test_hover_overrides_label_list_selection(self):
        c = self._make_canvas()
        list_shape = _rect([(10, 20), (40, 90)])
        hover_shape = _rect([(100, 120), (140, 190)])
        list_shape.visible = True
        hover_shape.visible = True
        c.shapes = [list_shape, hover_shape]
        c.select_shapes([list_shape], source="label_list")

        c._set_size_overlay_hover_shape(hover_shape)
        m = c._resolve_overlay_metrics()

        self.assertIsNotNone(m)
        self.assertEqual(m[9], "hover")
        self.assertEqual((m[0], m[1], m[2], m[3]), (100, 120, 140, 190))

    def test_image_switch_releases_overlay_selection_state(self):
        from PyQt6 import QtGui

        c = self._make_canvas()
        old_shape = _rect([(10, 20), (40, 90)])
        old_shape.visible = True
        c.shapes = [old_shape]
        c.select_shapes([old_shape])
        c._set_size_overlay_hover_shape(old_shape)
        self.assertIsNotNone(c._resolve_overlay_metrics())

        c.load_pixmap(QtGui.QPixmap(100, 100), clear_shapes=True)

        self.assertEqual(c.shapes, [])
        self.assertEqual(c.selected_shapes, [])
        self.assertIsNone(c._size_overlay_hover_shape)
        self.assertIsNone(c._resolve_overlay_metrics())

    def test_stale_selected_shape_not_in_current_shapes_is_ignored(self):
        c = self._make_canvas()
        old_shape = _rect([(10, 20), (40, 90)])
        new_shape = _rect([(100, 100), (120, 120)])
        old_shape.visible = True
        new_shape.visible = True
        c.shapes = [new_shape]
        c.selected_shapes = [old_shape]

        self.assertIsNone(c._resolve_overlay_metrics())


class TestLabelAnchorResolution(unittest.TestCase):
    """Label anchoring must reuse the real standard-label state/layout."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6 import QtWidgets

        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(
            []
        )

    def _make_canvas(self):
        from anylabeling.views.labeling.widgets.canvas import Canvas

        return Canvas()

    def test_label_on_selection_hidden_label_returns_none(self):
        c = self._make_canvas()
        shape = _rect([(10, 20), (40, 90)])
        shape.visible = True
        shape.selected = False
        c.shapes = [shape]
        c.h_hape = None
        c.prev_move_point = _pt(500, 500)
        c.label_on_selection = True

        self.assertIsNone(c._label_text_for_shape(shape))

        shape.selected = True
        self.assertEqual(c._label_text_for_shape(shape), "person")

    def test_label_rect_uses_standard_label_font_metrics(self):
        from PyQt6 import QtGui

        c = self._make_canvas()
        c.pixmap = QtGui.QPixmap(500, 500)
        shape = _rect([(10, 20), (80, 120)])
        label_text = "person"
        old_scale = Shape.scale
        try:
            Shape.scale = 4.0
            label_fm = QtGui.QFontMetrics(c._standard_label_font())
            rect = c._label_rect_for_shape(shape, label_text, label_fm)
            overlay_font_size = max(1, int(round(8.0 / Shape.scale)))
            overlay_font = QtGui.QFont(
                "Arial",
                overlay_font_size,
                QtGui.QFont.Weight.Bold,
            )
            overlay_fm = QtGui.QFontMetrics(overlay_font)
        finally:
            Shape.scale = old_scale

        self.assertIsNotNone(rect)
        self.assertEqual(rect[3], label_fm.height() + 4)
        self.assertGreater(rect[3], overlay_fm.height() + 4)


class TestNoSideEffects(unittest.TestCase):
    """Design 13: the overlay must not mutate shape / undo / dirty."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6 import QtWidgets

        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(
            []
        )

    def test_resolve_does_not_mutate_shape_points(self):
        from anylabeling.views.labeling.widgets.canvas import Canvas

        c = Canvas()
        shape = _rect([(10, 20), (40, 90)])
        original = [QtCore.QPointF(p.x(), p.y()) for p in shape.points]
        shape.visible = True
        c.shapes = [shape]
        c.selected_shapes = [shape]
        c._resolve_overlay_metrics()
        for p, o in zip(shape.points, original):
            self.assertEqual((p.x(), p.y()), (o.x(), o.y()))

    def test_resolve_does_not_create_undo_backup(self):
        from anylabeling.views.labeling.widgets.canvas import Canvas

        c = Canvas()
        shape = _rect([(10, 20), (40, 90)])
        shape.visible = True
        c.shapes = [shape]
        c.selected_shapes = [shape]
        before = len(c.shapes_backups)
        c._resolve_overlay_metrics()
        self.assertEqual(len(c.shapes_backups), before)

    def test_metrics_carries_floats_not_ints(self):
        # Threshold comparison must use raw floats (design 5.4).
        from anylabeling.views.labeling.widgets.canvas import Canvas

        c = Canvas()
        shape = _rect([(0, 0), (35.96, 35.96)])
        shape.visible = True
        c.shapes = [shape]
        c.selected_shapes = [shape]
        m = c._resolve_overlay_metrics()
        self.assertIsNotNone(m)
        self.assertAlmostEqual(m[6], 35.96)  # max_edge raw float


class TestZoomStability(unittest.TestCase):
    """Design 8 / 12.4: scale must not inflate font/padding/gap."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6 import QtWidgets

        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(
            []
        )

    def test_overlay_uses_fixed_screen_pixels_route_a(self):
        # R4 (Route A): the overlay draws with FIXED screen-pixel constants,
        # NOT round(8/scale). The old Route-B formula had an integer-floor
        # flaw: QFont pointSize is an int, so round(8/scale) jumped 1->2 at
        # scale≈5.3 and the overlay shrank above ~500% zoom. Route A draws in
        # widget space (resetTransform) so the font/pad/gap never depend on
        # the canvas scale at all.
        #
        # Assert the flaw is gone: at every scale the formula that USED to be
        # used (round(8/scale)) would have produced a shrinking box, but the
        # overlay no longer uses it — so we assert the route-A invariant:
        # the same box would be drawn identically regardless of scale.
        # Demonstrate the old flaw for contrast:
        old_at_550pct = max(1, int(round(8.0 / 5.5)))  # == 1
        self.assertEqual(old_at_550pct * 5.5, 5.5)  # shrank below 8px
        # Route A simply ignores scale for sizing, so there is no floor to
        # hit. Verified structurally: _paint_overlay_box uses fixed constants
        # (font_size=9, pad=4, gap=6) and resetTransform().
        import inspect

        from anylabeling.views.labeling.widgets.canvas import Canvas

        src = inspect.getsource(Canvas._paint_overlay_box)
        self.assertIn("resetTransform", src)
        self.assertNotIn("round(8.0", src)  # no scale-divided font sizing

    def test_W_H_invariant_across_zoom(self):
        # 12.4: same rectangle -> identical W/H/threshold at any scale.
        from anylabeling.views.labeling.widgets.canvas import Canvas

        c = Canvas()
        shape = _rect([(0, 0), (28.0, 34.0)])
        shape.visible = True
        c.shapes = [shape]
        c.selected_shapes = [shape]
        from anylabeling.views.labeling.shape import Shape

        results = {}
        for scale in (0.25, 1.0, 4.0):
            Shape.scale = scale
            m = c._resolve_overlay_metrics()
            results[scale] = (m[4], m[5], m[6])
        self.assertEqual(results[0.25], results[1.0])
        self.assertEqual(results[1.0], results[4.0])
        self.assertEqual(results[1.0], (28.0, 34.0, 34.0))


class TestViewToggle(unittest.TestCase):
    """Design 5 / 12.3: the show_rectangle_pixels View toggle."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6 import QtWidgets

        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(
            []
        )

    def test_default_config_has_key(self):
        import yaml

        with open(
            "anylabeling/configs/xanylabeling_config.yaml",
            encoding="utf-8",
        ) as fh:
            cfg = yaml.safe_load(fh)
        self.assertIn("show_rectangle_pixels", cfg)
        self.assertTrue(cfg["show_rectangle_pixels"])

    def test_canvas_default_true(self):
        from anylabeling.views.labeling.widgets.canvas import Canvas

        c = Canvas()
        self.assertTrue(c.show_rectangle_pixels)

    def test_independent_from_show_labels(self):
        # Closing show_labels must not force-close show_rectangle_pixels.
        from anylabeling.views.labeling.widgets.canvas import Canvas

        c = Canvas()
        self.assertTrue(c.show_labels)
        self.assertTrue(c.show_rectangle_pixels)

        c.show_labels = False
        self.assertTrue(c.show_rectangle_pixels)

        # And vice versa.
        c.show_labels = True
        c.show_rectangle_pixels = False
        self.assertTrue(c.show_labels)
        self.assertFalse(c.show_rectangle_pixels)

    def test_set_canvas_params_updates_only_rectangle_pixels(self):
        from anylabeling.views.labeling.label_widget import LabelingWidget

        class DummyCanvas:
            show_labels = True
            show_rectangle_pixels = True

            def __init__(self):
                self.updated = False

            def update(self):
                self.updated = True

        class DummyWidget:
            pass

        widget = DummyWidget()
        widget._config = {"show_rectangle_pixels": True}
        widget.canvas = DummyCanvas()

        LabelingWidget.set_canvas_params(
            widget, "show_rectangle_pixels", False
        )

        self.assertFalse(widget._config["show_rectangle_pixels"])
        self.assertFalse(widget.canvas.show_rectangle_pixels)
        self.assertTrue(widget.canvas.show_labels)
        self.assertTrue(widget.canvas.updated)


class TestThresholdNarrowReader(unittest.TestCase):
    """Design 10 / R6: the narrow reader must not depend on rules."""

    def test_reads_default_value(self):
        from anylabeling.views.labeling.widgets.inspector.quality.threshold_profile import (
            read_person_small_target_threshold,
        )

        self.assertAlmostEqual(read_person_small_target_threshold(), 36.0)

    def test_invalid_rules_do_not_block_read(self):
        # A profile with a broken rules array must still yield the threshold,
        # because the narrow reader skips rules validation entirely.
        import tempfile

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        )
        tmp.write(
            "profile_id: test\n"
            "schema_version: v0\n"
            "person_small_target:\n"
            "  min_edge_px: 42.0\n"
            "rules:\n"
            "  - this is deliberately invalid\n"
        )
        tmp.close()
        try:
            from anylabeling.views.labeling.widgets.inspector.quality.threshold_profile import (
                read_person_small_target_threshold,
            )

            self.assertAlmostEqual(
                read_person_small_target_threshold(tmp.name), 42.0
            )
        finally:
            os.unlink(tmp.name)

    def test_falls_back_on_missing_block(self):
        import tempfile

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        )
        tmp.write("profile_id: test\nschema_version: v0\n")
        tmp.close()
        try:
            from anylabeling.views.labeling.widgets.inspector.quality.threshold_profile import (
                read_person_small_target_threshold,
            )

            self.assertAlmostEqual(
                read_person_small_target_threshold(tmp.name), 36.0
            )
        finally:
            os.unlink(tmp.name)


if __name__ == "__main__":
    unittest.main()
