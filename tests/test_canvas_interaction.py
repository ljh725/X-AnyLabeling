import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6 import QtWidgets

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
