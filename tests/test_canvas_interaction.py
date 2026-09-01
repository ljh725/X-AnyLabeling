import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6 import QtCore, QtGui, QtWidgets

    PYQT_AVAILABLE = True
except Exception:
    PYQT_AVAILABLE = False


class MockShape:
    def __init__(
        self,
        visible=True,
        group_id=None,
        label="person",
        shape_type="rectangle",
    ):
        self.visible = visible
        self.group_id = group_id
        self.label = label
        self.shape_type = shape_type


@unittest.skipUnless(PYQT_AVAILABLE, "PyQt6 is required")
class TestCanvasInteraction(unittest.TestCase):
    def setUp(self):
        self.app = QtWidgets.QApplication.instance()
        if self.app is None:
            self.app = QtWidgets.QApplication([])
        from anylabeling.views.labeling.widgets.canvas import Canvas

        self.canvas = Canvas()
        self.canvas.show_labels = True

    def test_is_shape_interactive_when_visible(self):
        shape = MockShape()
        self.canvas.visible = {shape: True}
        self.assertTrue(self.canvas.is_shape_interactive(shape))

    def test_is_shape_interactive_when_canvas_invisible(self):
        shape = MockShape()
        self.canvas.visible = {shape: False}
        self.assertFalse(self.canvas.is_shape_interactive(shape))

    def test_is_shape_interactive_when_shape_invisible(self):
        shape = MockShape(visible=False)
        self.canvas.visible = {shape: True}
        self.assertFalse(self.canvas.is_shape_interactive(shape))

    def test_should_draw_standard_label_when_pose_view_off(self):
        shape = MockShape()
        self.canvas.visible = {shape: True}
        self.canvas.pose_config.enabled = False
        self.canvas.show_labels = True
        self.assertTrue(self.canvas._should_draw_standard_label(shape))

    def test_should_draw_standard_label_hides_coco_keypoint_in_pose_view(self):
        shape = MockShape(label="nose", shape_type="point")
        self.canvas.visible = {shape: True}
        self.canvas.pose_config.enabled = True
        self.canvas.show_labels = True
        self.assertFalse(self.canvas._should_draw_standard_label(shape))

    def test_should_draw_standard_label_shows_non_coco_in_pose_view(self):
        shape = MockShape(label="person", shape_type="rectangle")
        self.canvas.visible = {shape: True}
        self.canvas.pose_config.enabled = True
        self.canvas.show_labels = True
        self.assertTrue(self.canvas._should_draw_standard_label(shape))

    def test_should_draw_standard_label_hides_when_show_labels_off(self):
        shape = MockShape()
        self.canvas.visible = {shape: True}
        self.canvas.pose_config.enabled = False
        self.canvas.show_labels = False
        self.assertFalse(self.canvas._should_draw_standard_label(shape))

    def test_should_draw_standard_label_hides_when_not_interactive(self):
        shape = MockShape(visible=False)
        self.canvas.visible = {shape: True}
        self.canvas.pose_config.enabled = False
        self.canvas.show_labels = True
        self.assertFalse(self.canvas._should_draw_standard_label(shape))

    def test_label_on_selection_hides_unselected_shape(self):
        """Focused label mode hides non-selected, non-hovered shapes."""
        shape = MockShape()
        shape.selected = False
        self.canvas.visible = {shape: True}
        self.canvas.label_on_selection = True
        self.canvas.h_hape = object()
        self.assertFalse(self.canvas._is_standard_label_visible(shape))

    def test_label_on_selection_keeps_selected_and_hovered_shapes(self):
        """Focused label mode preserves selected and hovered previews."""
        selected = MockShape()
        selected.selected = True
        hovered = MockShape()
        hovered.selected = False
        self.canvas.visible = {selected: True, hovered: True}
        self.canvas.label_on_selection = True
        self.canvas.h_hape = hovered
        self.assertTrue(self.canvas._is_standard_label_visible(selected))
        self.assertTrue(self.canvas._is_standard_label_visible(hovered))

    def test_isolation_keeps_selected_group_and_excludes_other_groups(self):
        """Transient isolation follows one selected group without mutating visibility."""
        selected = MockShape(group_id=8)
        related = MockShape(group_id=8)
        other = MockShape(group_id=9)
        self.canvas.shapes = [selected, related, other]
        self.canvas.visible = {selected: True, related: True, other: True}
        self.canvas._set_selected_shapes([selected])
        self.canvas.set_isolation_enabled(True)

        self.assertTrue(self.canvas.is_shape_interactive(selected))
        self.assertTrue(self.canvas.is_shape_interactive(related))
        self.assertFalse(self.canvas.is_shape_interactive(other))
        self.assertTrue(other.visible)

    def test_isolation_uses_selected_tokens_for_mixed_groups(self):
        """Mixed selections isolate only the formally selected shapes."""
        first = MockShape(group_id=8)
        second = MockShape(group_id=9)
        other = MockShape(group_id=10)
        self.canvas.shapes = [first, second, other]
        self.canvas.visible = {first: True, second: True, other: True}
        self.canvas._set_selected_shapes([first, second])
        self.canvas.set_isolation_enabled(True)

        self.assertTrue(self.canvas.is_shape_interactive(first))
        self.assertTrue(self.canvas.is_shape_interactive(second))
        self.assertFalse(self.canvas.is_shape_interactive(other))

    def test_zero_opacity_skips_shape_paint_and_label_layout(self):
        """Unrelated zero-opacity objects never enter the paint path."""
        from anylabeling.views.labeling.shape import Shape
        from anylabeling.views.labeling.widgets.appearance import (
            AppearanceSettings,
        )

        selected = Shape(label="person", shape_type="rectangle", group_id=1)
        selected.points = [QtCore.QPointF(5, 5), QtCore.QPointF(20, 20)]
        unrelated = Shape(label="person", shape_type="rectangle", group_id=2)
        unrelated.points = [QtCore.QPointF(45, 45), QtCore.QPointF(80, 80)]
        calls = []
        original_paint = unrelated.paint
        unrelated.paint = lambda *args, **kwargs: calls.append(True)
        try:
            self.canvas.resize(100, 100)
            self.canvas.pixmap = QtGui.QPixmap(100, 100)
            self.canvas.pixmap.fill(QtGui.QColor("white"))
            self.canvas.shapes = [selected, unrelated]
            self.canvas.visible = {selected: True, unrelated: True}
            self.canvas._set_selected_shapes([selected])
            self.canvas.set_appearance_settings(
                AppearanceSettings(unrelated_opacity=0.0)
            )
            self.canvas.paintEvent(None)
            self.assertEqual(calls, [])
            self.assertIsNone(self.canvas._label_text_for_shape(unrelated))
        finally:
            unrelated.paint = original_paint

    def test_zero_opacity_preserves_light_dark_and_textured_pixels(self):
        """Zero-opacity geometry leaves all representative backgrounds intact."""
        from anylabeling.views.labeling.shape import Shape
        from anylabeling.views.labeling.widgets.appearance import (
            AppearanceSettings,
        )

        selected = Shape(label="person", shape_type="rectangle", group_id=1)
        selected.points = [QtCore.QPointF(5, 5), QtCore.QPointF(20, 20)]
        unrelated = Shape(label="person", shape_type="rectangle", group_id=2)
        unrelated.points = [QtCore.QPointF(45, 45), QtCore.QPointF(80, 80)]
        self.canvas.resize(100, 100)
        self.canvas.shapes = [selected, unrelated]
        self.canvas.visible = {selected: True, unrelated: True}
        self.canvas._set_selected_shapes([selected])
        self.canvas.set_appearance_settings(
            AppearanceSettings(unrelated_opacity=0.0)
        )
        backgrounds = [
            (QtGui.QPixmap(100, 100), QtCore.QPoint(60, 60)),
            (QtGui.QPixmap(100, 100), QtCore.QPoint(60, 60)),
            (QtGui.QPixmap(100, 100), QtCore.QPoint(50, 50)),
        ]
        backgrounds[0][0].fill(QtGui.QColor("white"))
        backgrounds[1][0].fill(QtGui.QColor("#202020"))
        textured = backgrounds[2][0]
        textured.fill(QtGui.QColor("#303840"))
        texture_painter = QtGui.QPainter(textured)
        texture_painter.fillRect(40, 40, 20, 20, QtGui.QColor("#607080"))
        texture_painter.end()
        expected = [
            QtGui.QColor("white"),
            QtGui.QColor("#202020"),
            QtGui.QColor("#607080"),
        ]
        for (pixmap, point), expected_color in zip(backgrounds, expected):
            self.canvas.pixmap = pixmap
            self.canvas.paintEvent(None)
            self.assertEqual(
                pixmap.toImage().pixelColor(point).rgba(), expected_color.rgba()
            )
