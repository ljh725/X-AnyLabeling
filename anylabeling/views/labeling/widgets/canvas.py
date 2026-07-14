"""This module defines Canvas widget - the core component for drawing image labels"""

import math
import os
import time
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QWheelEvent

from anylabeling.services.auto_labeling.types import AutoLabelingMode
from anylabeling.views.labeling.utils.colormap import label_colormap
from anylabeling.views.labeling.utils.theme import get_theme
from anylabeling.views.labeling.widgets.pose_label import (
    COCO_KEYPOINT_SET,
    PoseDisplayConfig,
    PoseRenderer,
)

from .. import utils
from .. import rect_edge_alignment as rea
from ..logger import logger
from ..shape import Shape

PERF_LOG_ENABLED = os.getenv("XANYLABELING_PERF_LOG") == "1"


def _perf_log(message, *args):
    """Emit performance logs only when enabled by env var."""
    if PERF_LOG_ENABLED:
        logger.info(message, *args)


CURSOR_DEFAULT = QtCore.Qt.CursorShape.ArrowCursor
CURSOR_POINT = QtCore.Qt.CursorShape.PointingHandCursor
CURSOR_DRAW = QtCore.Qt.CursorShape.CrossCursor
CURSOR_MOVE = QtCore.Qt.CursorShape.ClosedHandCursor
CURSOR_GRAB = QtCore.Qt.CursorShape.OpenHandCursor
CURSOR_SIZE_ALL = QtCore.Qt.CursorShape.SizeAllCursor
CURSOR_SIZE_FDIAG = QtCore.Qt.CursorShape.SizeFDiagCursor

AUTO_DECODE_DELAY_MS = 100
MAX_AUTO_DECODE_MARKS = 42
AUTO_DECODE_MOVE_THRESHOLD = 5.0
MOVE_SPEED = 5.0
LARGE_ROTATION_INCREMENT = math.radians(1.0)
SMALL_ROTATION_INCREMENT = math.radians(0.1)
CUBOID_FRONT_EDGE_CENTER_INDICES = {
    Shape.CUBOID_FRONT_LEFT_EDGE_CENTER,
    Shape.CUBOID_FRONT_RIGHT_EDGE_CENTER,
    Shape.CUBOID_FRONT_TOP_EDGE_CENTER,
    Shape.CUBOID_FRONT_BOTTOM_EDGE_CENTER,
}
CUBOID_BACK_EDGE_CENTER_INDICES = {
    Shape.CUBOID_BACK_LEFT_EDGE_CENTER,
    Shape.CUBOID_BACK_RIGHT_EDGE_CENTER,
}
CUBOID_FACE_FRONT = "front"
CUBOID_FACE_RIGHT = "right"
CUBOID_FACE_LEFT = "left"
CUBOID_FACE_TOP = "top"
CUBOID_FACE_BOTTOM = "bottom"
CUBOID_FACE_BACK = "back"

LABEL_COLORMAP = label_colormap()


class Canvas(
    QtWidgets.QWidget
):  # pylint: disable=too-many-public-methods, too-many-instance-attributes
    """Canvas widget to handle label drawing"""

    zoom_request = QtCore.pyqtSignal(int, QtCore.QPoint)
    scroll_request = QtCore.pyqtSignal(float, object, int)
    # [Feature] support for automatically switching to editing mode
    # when the cursor moves over an object
    mode_changed = QtCore.pyqtSignal()
    new_shape = QtCore.pyqtSignal()
    show_shape = QtCore.pyqtSignal(int, int, QtCore.QPointF)
    selection_changed = QtCore.pyqtSignal(list)
    shape_moved = QtCore.pyqtSignal()
    shape_rotated = QtCore.pyqtSignal()
    drawing_polygon = QtCore.pyqtSignal(bool)
    vertex_selected = QtCore.pyqtSignal(bool)
    auto_labeling_marks_updated = QtCore.pyqtSignal(list)
    auto_decode_requested = QtCore.pyqtSignal(list)
    auto_decode_finish_requested = QtCore.pyqtSignal()
    shape_hover_changed = QtCore.pyqtSignal()
    split_position_changed = QtCore.pyqtSignal(float)
    edit_label_requested = QtCore.pyqtSignal()
    pose_occlusion_count_changed = QtCore.pyqtSignal(int)
    keyboard_edge_selected = QtCore.pyqtSignal(str)

    CREATE, EDIT = 0, 1

    # polygon, rectangle, rotation, line, or point
    _create_mode = "polygon"

    _fill_drawing = False

    def __init__(self, *args, **kwargs):
        self.epsilon = kwargs.pop("epsilon", 10.0)
        self.double_click = kwargs.pop("double_click", "close")
        if self.double_click not in [None, "close"]:
            raise ValueError(
                f"Unexpected value for double_click event: {self.double_click}"
            )
        self.double_click_edit_label = kwargs.pop(
            "double_click_edit_label", True
        )
        self.num_backups = kwargs.pop("num_backups", 10)
        self.wheel_rectangle_editing = kwargs.pop(
            "wheel_rectangle_editing", {}
        )
        self.enable_wheel_rectangle_editing = self.wheel_rectangle_editing.get(
            "enable", False
        )
        self.rect_adjust_step = self.wheel_rectangle_editing.get(
            "adjust_step", 2.0
        )
        self.rect_scale_step = self.wheel_rectangle_editing.get(
            "scale_step", 0.05
        )
        self.auto_highlight_shape = kwargs.pop("auto_highlight_shape", False)
        self.attributes_config = kwargs.pop("attributes", {})
        self.rotation_config = kwargs.pop("rotation", {})
        self.mask_config = kwargs.pop("mask", {})
        self.brush_config = kwargs.pop("brush", {})
        self.cuboid_config = kwargs.pop("cuboid", {})
        self.parent = kwargs.pop("parent", None)
        super().__init__(*args, **kwargs)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(
            QtGui.QPalette.ColorRole.Window,
            QtGui.QColor(get_theme()["background"]),
        )
        self.setPalette(palette)
        # Initialise local state.
        self.mode = self.EDIT
        self.is_auto_labeling = False
        self.is_move_editing = False
        self.auto_labeling_mode: AutoLabelingMode = None
        self.shapes = []
        self.shapes_backups = []
        self._pending_initial_backup = False
        self.current = None
        self.selected_shapes = []  # save the selected shapes here
        self.selected_shapes_copy = []
        # self.line represents:
        #   - create_mode == 'polygon': edge from last point to current
        #   - create_mode == 'rectangle': diagonal line of the rectangle
        #   - create_mode == 'line': the line
        #   - create_mode == 'point': the point
        self.line = Shape()
        self.prev_point = QtCore.QPointF()
        self.prev_pan_point = QtCore.QPointF()
        self.prev_move_point = QtCore.QPointF()
        self.offsets = QtCore.QPointF(), QtCore.QPointF()
        self.scale = 1.0
        self.pixmap = QtGui.QPixmap()
        self.visible = {}
        self._hide_backround = False
        self.hide_backround = False
        self.h_hape = None
        self.prev_h_shape = None
        self.h_vertex = None
        self.prev_h_vertex = None
        self.h_edge = None
        self.prev_h_edge = None
        self.h_cuboid_face = None
        self.prev_h_cuboid_face = None
        self.moving_shape = False
        self._pending_edge_point = None
        self.rotating_shape = False
        self.snapping = True
        self.h_shape_is_selected = False
        self.h_shape_is_hovered = None
        self.allowed_oop_shape_types = ["rotation", "quadrilateral", "cuboid"]
        default_cuboid_depth_vector = self.cuboid_config.get(
            "default_depth_vector", [24.0, -24.0]
        )
        if (
            not isinstance(default_cuboid_depth_vector, (list, tuple))
            or len(default_cuboid_depth_vector) != 2
        ):
            default_cuboid_depth_vector = [24.0, -24.0]
        self.cuboid_default_depth_vector = [
            float(default_cuboid_depth_vector[0]),
            float(default_cuboid_depth_vector[1]),
        ]
        self.cuboid_min_depth = float(self.cuboid_config.get("min_depth", 5.0))
        self._painter = QtGui.QPainter()
        self._cursor = CURSOR_DEFAULT
        # Menus:
        # 0: right-click without selection and dragging of shapes
        # 1: right-click with selection and dragging of shapes
        self.menus = (QtWidgets.QMenu(), QtWidgets.QMenu())
        # Set widget options.
        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.WheelFocus)
        self.show_groups = False
        self.show_masks = True
        self.show_texts = True
        self.show_labels = True
        self.label_display_mode = "label"
        self.show_scores = True
        self.show_degrees = False
        self.show_attributes = True
        self.show_linking = True
        self.label_on_selection = False
        # Keypoint label display options.
        # label_on_selection ON  = sparse: show labels only for
        #   hovered/selected shapes, or the hovered group when zoomed in.
        # label_on_selection OFF = show all labels on the canvas.
        self.label_zoom_threshold = 2.0

        # Pose view configuration (shared with sidebar panels).
        self.pose_config = PoseDisplayConfig()
        self._pose_renderer = PoseRenderer(self.pose_config)
        # Whether a shape filter is currently active (set by LabelingWidget
        # after _apply_combined_shape_filters). Pose overlay renders only
        # when pose view is on AND a filter is active (filtered display).
        self.pose_filter_active = False

        # Set cross line options.
        self.cross_line_show = True
        self.cross_line_width = 2.0
        self.cross_line_color = "#00FF00"
        self.cross_line_opacity = 0.5

        # Set attributes color options.
        self.attr_background_color = self.attributes_config.get(
            "background_color", [33, 33, 33, 255]
        )
        self.attr_border_color = self.attributes_config.get(
            "border_color", [66, 66, 66, 255]
        )
        self.attr_text_color = self.attributes_config.get(
            "text_color", [33, 150, 243, 255]
        )

        # Set rotation increment options.
        self.large_rotation_increment = math.radians(
            self.rotation_config.get("large_increment", 1.0)
        )
        self.small_rotation_increment = math.radians(
            self.rotation_config.get("small_increment", 0.1)
        )

        # Set mask opacity options.
        self.mask_opacity = self.mask_config.get("opacity", 80)

        self.is_loading = False
        self.loading_text = self.tr("Loading...")
        self.loading_angle = 0

        # Auto mask decode mode
        self.auto_decode_mode = False
        self.auto_decode_timer = QTimer()
        self.auto_decode_timer.timeout.connect(self.on_auto_decode_timeout)
        self.auto_decode_timer.setSingleShot(True)
        self.auto_decode_tracklet = []
        self.last_mouse_pos = None

        # Brush drawing mode for polygon
        self._brush_drawing = False
        self.brush_point_distance = self.brush_config.get(
            "point_distance", 25.0
        )

        # Compare view support
        self.compare_pixmap = None
        self.split_position = 0.5

        # Rectangle edge editing mode (see rect_edge_alignment.py).
        # All of these are purely transient in-memory state; none of them is
        # persisted to JSON. The active edge is an in-memory ``RectEdgeRef``
        # that is never written into ``Shape.other_data``.
        self.rect_edge_align_enabled = False
        self.rect_edge_hover_edge = None
        self.rect_edge_active_edge = None
        self.rect_edge_dragging = False
        self.rect_edge_drag_start_points = None

        # Keyboard-selected rectangle edge for single-edge nudge (Feature 3).
        # None means whole-shape move applies; otherwise Up/Down/Left/Right
        # nudge the named edge via rect_edge_alignment.apply_edge_coord.
        # Independent from the mouse edge-editing master switch. N1: any
        # mouse hover onto a rectangle edge clears this (hover takes over
        # the active-edge).
        self.rect_edge_keyboard_edge = None
        self.rect_edge_keyboard_shape = None

        # Precision drag mode (Feature 3). When active, mouse drag deltas
        # are scaled by 1/precision_factor using a virtual cursor that is
        # kept SEPARATE from self.prev_point (move_by_keyboard and press
        # resets depend on prev_point being the real cursor — D4).
        self.precision_mode_locked = False
        self._virtual_prev_point = None
        self._precision_raw_prev_point = None

        # Undo merge window (N2/D5): timestamp-based replace-in-place.
        # When store_shapes is called with merge_window > 0 and the last
        # snapshot was within the window, the last entry is replaced
        # instead of appending. Avoids QTimer and delayed persistence.
        self._last_snapshot_ts = 0.0

        # Stable refine preview (phase 1: DragLocked only). See
        # docs/稳定精修预览功能实现任务文档.md. Purely transient
        # in-memory state; nothing is persisted to JSON. The preview
        # only reacts to an already-committed ``rect_edge_drag`` — it
        # never participates in mouse-event arbitration.
        self.stable_preview_enabled = False
        self.stable_preview_scale = 4.0
        self.stable_preview_size = QtCore.QSize(360, 270)
        self.stable_preview_min_size = QtCore.QSize(240, 180)
        self.stable_preview_anchor = "bottom_right"
        self.stable_preview_margin = 12
        # The shape being edited (direct reference; no id mechanism).
        self.stable_preview_shape = None
        # Locked crop rect in IMAGE coordinates (frozen for the drag).
        self.stable_preview_locked_rect = None
        # Which edge is being dragged: left/right/top/bottom.
        self.stable_preview_active_edge_name = None

        # Phase 2: TargetPreview state. See
        # docs/稳定精修预览阶段二任务文档.md. ``stable_preview_shape``
        # is reused by both target and drag-locked modes (they always
        # refer to the same rectangle during a target->drag->target
        # cycle), so no separate target_shape field is kept.
        self.stable_preview_target_enabled = True
        self.stable_preview_drag_locked_enabled = True
        # "none" | "target" | "drag_locked"
        self.stable_preview_mode = "none"
        # Stable crop rect for TargetPreview (image coords). Unlike the
        # drag-locked rect it is only recomputed when the bbox leaves the
        # safe zone, so the background does not drift on small edits.
        self.stable_preview_target_rect = None
        self.stable_preview_target_padding_ratio = 0.4
        self.stable_preview_safe_ratio = 0.7
        # Phase 3: canvas-local preview window geometry. Moving the
        # window changes only this widget-coordinate rect; it never
        # changes the image-coordinate source rect.
        self.stable_preview_window_rect = None
        self.stable_preview_window_dragging = False
        self.stable_preview_window_resizing = False
        self.stable_preview_window_press_pos = None
        self.stable_preview_window_press_rect = None
        self.stable_preview_resize_handle_px = 16

        # Phase 2: subscribe to selection changes so TargetPreview
        # follows single-rectangle selection. One connect covers every
        # selection_changed.emit() site; the few code paths that mutate
        # selected_shapes without emitting are patched to emit too.
        self.selection_changed.connect(
            self._stable_preview_on_selection_changed
        )

    def set_loading(self, is_loading: bool, loading_text: str = None):
        """Set loading state"""
        self.is_loading = is_loading
        if loading_text:
            self.loading_text = loading_text
        self.update()

    def set_auto_labeling_mode(self, mode: AutoLabelingMode):
        """Set auto labeling mode"""
        if mode == AutoLabelingMode.NONE:
            self.is_auto_labeling = False
            self.auto_labeling_mode = mode
        else:
            self.is_auto_labeling = True
            self.auto_labeling_mode = mode
            self.create_mode = mode.shape_type
            self.parent.toggle_draw_mode(
                False, mode.shape_type, disable_auto_labeling=False
            )

    def set_auto_decode_mode(self, enabled: bool):
        """Set auto decode mode"""
        if self.auto_decode_mode and not enabled:
            self.reset_auto_decode_state()
        self.auto_decode_mode = enabled

    def reset_auto_decode_state(self):
        """Reset auto decode state"""
        if self.auto_decode_timer.isActive():
            self.auto_decode_timer.stop()
        self.auto_decode_tracklet.clear()
        self.last_mouse_pos = None

    def fill_drawing(self):
        """Get option to fill shapes by color"""
        return self._fill_drawing

    def set_fill_drawing(self, value):
        """Set shape filling option"""
        self._fill_drawing = value
        self.update()

    @property
    def create_mode(self):
        """Create mode for canvas - Modes: polygon, rectangle, rotation, circle,..."""
        return self._create_mode

    @create_mode.setter
    def create_mode(self, value):
        """Set create mode for canvas"""
        if value not in Shape.get_supported_shape():
            raise ValueError(f"Unsupported create_mode: {value}")
        self._create_mode = value

    def store_shapes(self, merge_window=0.0):
        """Store shapes for restoring later (Undo feature).

        Args:
            merge_window: When > 0 (seconds), enable timestamp-based
                replace-in-place merging (N2/D5). If the last snapshot
                was taken within this window, the last entry is replaced
                instead of appending. Used by keyboard nudge to avoid
                rapid key repeats flooding the bounded undo stack.
                Default 0.0 (always append) preserves legacy behavior
                for all existing callers.
        """
        import time

        if getattr(self, "_pending_initial_backup", False) and self.shapes:
            initial_backup = []
            for shape in self.shapes:
                initial_backup.append(shape.copy())
            self.shapes_backups.append(initial_backup)
            self._pending_initial_backup = False
        shapes_backup = []
        for shape in self.shapes:
            shapes_backup.append(shape.copy())
        if len(self.shapes_backups) > self.num_backups:
            self.shapes_backups = self.shapes_backups[-self.num_backups - 1 :]
        now = time.monotonic()
        if (
            merge_window > 0.0
            and self.shapes_backups
            and (now - self._last_snapshot_ts) < merge_window
        ):
            # Replace the last snapshot instead of appending: collapses
            # a burst of keyboard nudges into one undo step.
            self.shapes_backups[-1] = shapes_backup
        else:
            self.shapes_backups.append(shapes_backup)
        self._last_snapshot_ts = now

    def store_moving_shape(self):
        """Store a moving shape"""
        if self.moving_shape:
            moving_shapes = (
                [self.h_hape] + self.selected_shapes
                if self.h_hape and self.h_hape not in self.selected_shapes
                else self.selected_shapes.copy()
            )
            for shape in moving_shapes:
                if shape in self.shapes:
                    index = self.shapes.index(shape)
                    if (
                        len(self.shapes_backups) > 0
                        and index < len(self.shapes_backups[-1])
                        and self.shapes_backups[-1][index].points
                        != self.shapes[index].points
                    ):
                        self.store_shapes()
                        self.shape_moved.emit()
                        break

            self.moving_shape = False

    def clip_rectangle_to_pixmap(self, shape):
        """Clip rectangle shape to pixmap boundaries"""
        if self.pixmap is None or shape.shape_type != "rectangle":
            return True

        w, h = self.pixmap.width(), self.pixmap.height()
        points = shape.points

        if len(points) != 4:
            return True

        x_coords = [p.x() for p in points]
        y_coords = [p.y() for p in points]
        min_x, max_x = min(x_coords), max(x_coords)
        min_y, max_y = min(y_coords), max(y_coords)

        clipped_min_x = max(0, min_x)
        clipped_min_y = max(0, min_y)
        clipped_max_x = min(w - 1, max_x)
        clipped_max_y = min(h - 1, max_y)

        if clipped_max_x <= clipped_min_x or clipped_max_y <= clipped_min_y:
            return False

        shape.points = [
            QtCore.QPointF(clipped_min_x, clipped_min_y),
            QtCore.QPointF(clipped_max_x, clipped_min_y),
            QtCore.QPointF(clipped_max_x, clipped_max_y),
            QtCore.QPointF(clipped_min_x, clipped_max_y),
        ]
        return True

    def clip_rotation_to_pixmap(self, shape):
        """Clip an axis-aligned rotation shape's bounding box to pixmap boundaries.

        Only clamps shapes whose direction is zero, i.e. freshly drawn in
        manual mode before any rotation has been applied.

        Args:
            shape (Shape): The rotation shape to clip.

        Returns:
            bool: True if the resulting shape is valid, False if it degenerates
                to zero area and should be discarded.
        """
        if self.pixmap is None or shape.shape_type != "rotation":
            return True
        if shape.direction != 0:
            return True
        if len(shape.points) != 4:
            return True

        w, h = self.pixmap.width(), self.pixmap.height()
        x_coords = [p.x() for p in shape.points]
        y_coords = [p.y() for p in shape.points]
        min_x, max_x = min(x_coords), max(x_coords)
        min_y, max_y = min(y_coords), max(y_coords)

        clipped_min_x = max(0, min_x)
        clipped_min_y = max(0, min_y)
        clipped_max_x = min(w - 1, max_x)
        clipped_max_y = min(h - 1, max_y)

        if clipped_max_x <= clipped_min_x or clipped_max_y <= clipped_min_y:
            return False

        shape.points = [
            QtCore.QPointF(clipped_min_x, clipped_min_y),
            QtCore.QPointF(clipped_max_x, clipped_min_y),
            QtCore.QPointF(clipped_max_x, clipped_max_y),
            QtCore.QPointF(clipped_min_x, clipped_max_y),
        ]
        shape.center = QtCore.QPointF(
            (clipped_min_x + clipped_max_x) / 2,
            (clipped_min_y + clipped_max_y) / 2,
        )
        return True

    @property
    def is_shape_restorable(self):
        """Check if shape can be restored from backup"""
        # We save the state AFTER each edit (not before) so for an
        # edit to be undoable, we expect the CURRENT and the PREVIOUS state
        # to be in the undo stack.
        if len(self.shapes_backups) < 2:
            return False
        return True

    def restore_shape(self):
        """Restore/Undo a shape"""
        # This does _part_ of the job of restoring shapes.
        # The complete process is also done in app.py::undoShapeEdit
        # and app.py::load_shapes and our own Canvas::load_shapes function.
        if not self.is_shape_restorable:
            return
        self.shapes_backups.pop()  # latest

        # The application will eventually call Canvas.load_shapes which will
        # push this right back onto the stack.
        shapes_backup = self.shapes_backups.pop()
        self.shapes = shapes_backup
        self.selected_shapes = []
        for shape in self.shapes:
            shape.selected = False
        # Emit so selection-derived views (e.g. stable preview) sync;
        # restore_shape mutated selected_shapes without signalling.
        self.selection_changed.emit(self.selected_shapes)
        self.update()

    def enterEvent(self, _):
        """Mouse enter event"""
        self.override_cursor(self._cursor)

    def leaveEvent(self, _):
        """Mouse leave event"""
        self.store_moving_shape()
        self.un_highlight()
        self.restore_cursor()
        self.shape_hover_changed.emit()

    def focusOutEvent(self, _):
        """Window out of focus event"""
        self.restore_cursor()

    def is_visible(self, shape):
        """Check if a shape is visible"""
        return self.visible.get(shape, True)

    def is_shape_interactive(self, shape: Shape) -> bool:
        """Return whether a shape can be hovered, selected, or edited."""
        return (
            self.is_visible(shape)
            and getattr(shape, "visible", True)
            and not getattr(shape, "hidden_by_filter", False)
        )

    def _shape_hit_candidates(self, point):
        """Return shapes under a point in interaction priority order.

        [迁移自 beta.11 功能C] 取代旧的 ``reversed(shapes) + 首次命中即返回``
        选择策略。对所有候选 shape 计算一个 4 元组优先级并排序，最终返回
        按交互优先级从高到低排列的 ``[shape, ...]`` 列表，供悬停/点击/双击
        三处统一消费。

        优先级元组 ``priority = (级别, 距离, 面积, -stack_index)``，全部
        升序(越小越优先)：
            - 级别 0: 附近顶点(可抓取编辑点)——最高优先
            - 级别 1: 附近可编辑边(可双击加点)
            - 级别 2: 整体命中(contains_point)——兜底
            - 同级别下: 距离更近者优先；仍相同时面积更小者优先(嵌套场景下
              小对象优先于大对象)；最后后创建者(栈顶)优先。
        ``not shape.locked`` 守卫: beta.4 未实现锁定, shape.locked 恒为
        False, 故锁定 shape 与普通 shape 行为一致(守卫为 no-op)。
        """
        candidates = []
        epsilon = self.epsilon / self.scale
        for stack_index, shape in enumerate(self.shapes):
            if not self.is_shape_interactive(shape):
                continue

            rect = shape.bounding_rect()
            area = max(0.0, rect.width()) * max(0.0, rect.height())
            vertex_distance = None
            if not shape.locked:
                if shape.shape_type == "cuboid" and len(shape.points) == 8:
                    vertex_index = self.nearest_cuboid_control(
                        shape, point, epsilon
                    )
                    vertex = (
                        self.cuboid_control_point(shape, vertex_index)
                        if vertex_index is not None
                        else None
                    )
                else:
                    vertex_index = shape.nearest_vertex(point, epsilon)
                    vertex = (
                        shape.points[vertex_index]
                        if vertex_index is not None
                        else None
                    )
                if vertex is not None:
                    vertex_distance = utils.distance(vertex - point)

            if vertex_distance is not None:
                priority = (0, vertex_distance, area, -stack_index)
                candidates.append((priority, shape))
                continue

            if (
                not shape.locked
                and len(shape.points) > 1
                and shape.can_add_point()
                and shape.shape_type != "quadrilateral"
            ):
                edge_index = shape.nearest_edge(point, epsilon)
                if edge_index is not None:
                    line = [
                        shape.points[edge_index - 1],
                        shape.points[edge_index],
                    ]
                    edge_distance = utils.distance_to_line(point, line)
                    priority = (1, edge_distance, area, -stack_index)
                    candidates.append((priority, shape))
                    continue

            if shape.shape_type in ["point", "line", "linestrip"]:
                vertex_index = shape.nearest_vertex(point, epsilon * 3)
                if vertex_index is None:
                    continue
                distance = utils.distance(shape.points[vertex_index] - point)
                priority = (1, distance, area, -stack_index)
                candidates.append((priority, shape))
                continue

            if shape.shape_type == "cuboid" and len(shape.points) == 8:
                front_path = self.cuboid_face_path(shape, CUBOID_FACE_FRONT)
                hit = (
                    front_path is not None and front_path.contains(point)
                ) or self.cuboid_face_hit_test(shape, point) is not None
            else:
                hit = len(shape.points) > 1 and shape.contains_point(point)
            if hit:
                priority = (2, area, 0.0, -stack_index)
                candidates.append((priority, shape))

        candidates.sort(key=lambda item: item[0])
        return [shape for _, shape in candidates]

    def _should_draw_standard_label(self, shape: Shape) -> bool:
        """Return whether the standard Canvas label should be drawn."""
        if not self.show_labels:
            return False
        # Pose View takes over only COCO keypoint labels; other shapes
        # (rectangles, polygons, ...) keep their native labels. (decouple)
        if self.pose_config.enabled and shape.label in COCO_KEYPOINT_SET:
            return False
        if not self.is_shape_interactive(shape):
            return False
        return True

    def drawing(self):
        """Check if user is drawing (mode==CREATE)"""
        return self.mode == self.CREATE

    def editing(self):
        """Check if user is editing (mode==EDIT)"""
        return self.mode == self.EDIT

    def set_auto_labeling(self, value=True):
        """Set auto labeling mode"""
        self.is_auto_labeling = value
        if self.auto_labeling_mode is None:
            self.auto_labeling_mode = AutoLabelingMode.NONE
            self.parent.toggle_draw_mode(
                True, "rectangle", disable_auto_labeling=True
            )

    def get_mode(self):
        """Get current mode"""
        if (
            self.is_auto_labeling
            and self.auto_labeling_mode != AutoLabelingMode.NONE
        ):
            return self.tr("Auto Labeling")
        if self.mode == self.CREATE:
            return self.tr("Drawing")
        elif self.mode == self.EDIT:
            return self.tr("Editing")
        else:
            return self.tr("Unknown")

    def set_editing(self, value=True):
        """Set editing mode. Editing is set to False, user is drawing"""
        if not value:  # Create
            # Edge editing stays enabled as a user preference, but its
            # transient interaction cannot cross into create mode. Restore
            # any live geometry before dropping the active edge reference.
            if not self.cancel_rect_edge_drag():
                self.clear_rect_edge_alignment()
        self.mode = self.EDIT if value else self.CREATE
        if not value:  # Create
            self.un_highlight()
            self.deselect_shape()
            self._clear_keyboard_edge()
            self.is_move_editing = False
            # Leaving edit mode must drop any in-progress preview so it
            # never lingers into a draw/create context.
            self._stable_preview_clear_all()
            self.shape_hover_changed.emit()

    def un_highlight(self):
        """Unhighlight shape/vertex/edge"""
        if self.h_hape:
            self.h_hape.highlight_clear()
            self.update()
        self.prev_h_shape = self.h_hape
        self.prev_h_vertex = self.h_vertex
        self.prev_h_edge = self.h_edge
        self.prev_h_cuboid_face = self.h_cuboid_face
        self.h_hape = self.h_vertex = self.h_edge = self.h_cuboid_face = None

    def selected_vertex(self):
        """Check if selected a vertex"""
        return self.h_vertex is not None

    def selected_edge(self):
        """Check if selected an edge"""
        return self.h_edge is not None

    def selected_cuboid_face(self):
        return self.h_cuboid_face is not None

    @staticmethod
    def _snap_line_pos(anchor, pos):
        """Snap line endpoint to horizontal or vertical direction."""
        dx = abs(pos.x() - anchor.x())
        dy = abs(pos.y() - anchor.y())
        if dx >= dy:
            return QtCore.QPointF(pos.x(), anchor.y())
        return QtCore.QPointF(anchor.x(), pos.y())

    def _should_trigger_auto_decode(self, pos):
        """Check if mouse movement exceeds threshold to trigger auto decode"""
        if not self.auto_decode_tracklet:
            return True

        last_point = self.auto_decode_tracklet[-1]["data"]
        distance = (
            (pos.x() - last_point[0]) ** 2 + (pos.y() - last_point[1]) ** 2
        ) ** 0.5
        return distance >= AUTO_DECODE_MOVE_THRESHOLD

    # QT Overload
    def mouseMoveEvent(self, ev):  # noqa: C901
        """Update line with last point and current coordinates"""
        if self.is_loading:
            return
        if self._stable_preview_window_interaction_active():
            self._stable_preview_update_window_interaction(ev.position())
            return
        try:
            pos = self.transform_pos(ev.position())
        except AttributeError:
            return

        prev_hover_shape = self.h_hape
        self.prev_move_point = pos
        self.repaint()

        preview_hover = (
            ev.buttons() == QtCore.Qt.MouseButton.NoButton
            and self._stable_preview_update_window_hover(ev.position())
        )
        if preview_hover:
            self.un_highlight()
            self.show_shape.emit(-1, -1, pos)
            self.update()
            return

        # Handle auto decode mode
        if (
            self.auto_decode_mode
            and self.is_auto_labeling
            and self.auto_decode_tracklet
        ):
            if self._should_trigger_auto_decode(pos):
                self.last_mouse_pos = pos
                if not self.auto_decode_timer.isActive():
                    self.auto_decode_timer.start(AUTO_DECODE_DELAY_MS)

        # Polygon drawing.
        if self.drawing():
            line_color = utils.hex_to_rgb(self.cross_line_color)
            self.line.line_color = QtGui.QColor(*line_color)
            self.line.shape_type = self.create_mode
            if self.create_mode == "cuboid":
                self.line.shape_type = "rectangle"

            if not self.current:
                self.override_cursor(CURSOR_DRAW)
                return

            if self.create_mode in ["rectangle", "cuboid"]:
                shape_width = int(abs(self.current[0].x() - pos.x()))
                shape_height = int(abs(self.current[0].y() - pos.y()))
                self.show_shape.emit(shape_height, shape_width, pos)

            color = QtGui.QColor(0, 0, 255)
            if self.out_off_pixmap(pos) and self.create_mode not in [
                "rectangle",
                "rotation",
                "quadrilateral",
                "cuboid",
            ]:
                pos = self.intersection_point(self.current[-1], pos)
            elif (
                self.snapping
                and len(self.current) > 1
                and self.create_mode == "polygon"
                and self.close_enough(pos, self.current[0])
            ):
                # Attract line to starting point and
                # colorise to alert the user.
                pos = self.current[0]
                self.override_cursor(CURSOR_POINT)
                self.current.highlight_vertex(0, Shape.NEAR_VERTEX)
            elif (
                self.create_mode == "rotation"
                and len(self.current) > 0
                and self.close_enough(pos, self.current[0])
            ):
                pos = self.current[0]
                color = self.current.line_color
                self.override_cursor(CURSOR_POINT)
                self.current.highlight_vertex(0, Shape.NEAR_VERTEX)
            elif (
                self.create_mode == "quadrilateral"
                and len(self.current) >= 3
                and self.close_enough(pos, self.current[0])
            ):
                pos = self.current[0]
                self.override_cursor(CURSOR_POINT)
                self.current.highlight_vertex(0, Shape.NEAR_VERTEX)
            else:
                self.override_cursor(CURSOR_DRAW)
            if (
                self.create_mode in ["line", "linestrip"]
                and ev.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier
            ):
                pos = self._snap_line_pos(self.current[-1], pos)
            if self.create_mode in ["polygon", "linestrip", "quadrilateral"]:
                self.line[0] = self.current[-1]
                self.line[1] = pos
            elif self.create_mode == "rectangle":
                self.line.points = [self.current[0], pos]
                self.line.close()
            elif self.create_mode == "rotation":
                self.line[1] = pos
                self.line.line_color = color
            elif self.create_mode == "circle":
                self.line.points = [self.current[0], pos]
                self.line.shape_type = "circle"
            elif self.create_mode == "line":
                self.line.points = [self.current[0], pos]
                self.line.close()
            elif self.create_mode == "point":
                self.line.points = [self.current[0]]
                self.line.close()
            elif self.create_mode == "cuboid":
                self.line.points = [self.current[0], pos]
                self.line.close()
            if self._brush_drawing and self.create_mode == "polygon":
                if (
                    self.snapping
                    and len(self.current) > 2
                    and self.close_enough(pos, self.current[0])
                ):
                    self.current.highlight_clear()
                    self.finalise()
                    return
                point_dist = utils.distance(pos - self.current[-1])
                if point_dist * self.scale >= self.brush_point_distance:
                    self.current.add_point(pos)
                    self.line[0] = self.current[-1]
            self.repaint()
            self.current.highlight_clear()
            return

        # Polygon copy moving.
        if QtCore.Qt.MouseButton.RightButton & ev.buttons():
            if self.selected_shapes_copy and self.prev_point:
                self.override_cursor(CURSOR_MOVE)
                eff = self._effective_drag_pos(pos, ev)
                self.bounded_move_shapes(self.selected_shapes_copy, eff)
                self.repaint()
            elif self.selected_shapes:
                self.selected_shapes_copy = [
                    s.copy() for s in self.selected_shapes
                ]
                self.repaint()
            return

        # Rectangle edge drag has the highest priority while the left
        # button is held: consume the move here so it never reaches the
        # normal left-button pan/scroll block below (which would emit
        # scroll_request and swallow the live preview).
        if (
            self.rect_edge_align_enabled
            and self.rect_edge_dragging
            and self.rect_edge_active_edge is not None
        ):
            eff = self._effective_drag_pos(pos, ev)
            self._rect_edge_drag_update(eff)
            # While actively dragging an edge, show the closed-hand
            # (grab) cursor to reflect the held interaction; this branch
            # returns early and otherwise skips the default hover loop.
            self.override_cursor(CURSOR_MOVE)
            return

        # Polygon/Vertex moving.
        if QtCore.Qt.MouseButton.LeftButton & ev.buttons():
            if self.selected_vertex():
                self.h_cuboid_face = None
                self.is_move_editing = False
                try:
                    eff = self._effective_drag_pos(pos, ev)
                    self.bounded_move_vertex(eff)
                    self.repaint()
                    self.moving_shape = True
                except IndexError:
                    return
                if self.h_hape.shape_type == "rectangle":
                    p1 = self.h_hape[0]
                    p2 = self.h_hape[2]
                    shape_width = int(abs(p2.x() - p1.x()))
                    shape_height = int(abs(p2.y() - p1.y()))
                    self.show_shape.emit(shape_height, shape_width, pos)
                elif (
                    self.h_hape.shape_type == "cuboid"
                    and len(self.h_hape) >= 4
                ):
                    p1 = self.h_hape[0]
                    p2 = self.h_hape[2]
                    shape_width = int(abs(p2.x() - p1.x()))
                    shape_height = int(abs(p2.y() - p1.y()))
                    self.show_shape.emit(shape_height, shape_width, pos)
            elif (
                self.selected_cuboid_face()
                and self.h_hape is not None
                and self.h_hape.shape_type == "cuboid"
                and self.prev_point is not None
            ):
                self.is_move_editing = False
                offset = pos - self.prev_point
                self.move_cuboid_face_by(
                    self.h_hape, self.h_cuboid_face, offset
                )
                self.prev_point = pos
                self.repaint()
                self.moving_shape = True
                p1 = self.h_hape[0]
                p2 = self.h_hape[2]
                shape_width = int(abs(p2.x() - p1.x()))
                shape_height = int(abs(p2.y() - p1.y()))
                self.show_shape.emit(shape_height, shape_width, pos)
            elif self.selected_shapes and self.prev_point:
                self.h_cuboid_face = None
                self.override_cursor(CURSOR_MOVE)
                eff = self._effective_drag_pos(pos, ev)
                self.bounded_move_shapes(self.selected_shapes, eff)
                self.repaint()
                self.moving_shape = True
                if self.selected_shapes[-1].shape_type == "rectangle":
                    p1 = self.selected_shapes[-1][0]
                    p2 = self.selected_shapes[-1][2]
                    shape_width = int(abs(p2.x() - p1.x()))
                    shape_height = int(abs(p2.y() - p1.y()))
                    self.show_shape.emit(shape_height, shape_width, pos)
                elif (
                    self.selected_shapes[-1].shape_type == "cuboid"
                    and len(self.selected_shapes[-1]) >= 4
                ):
                    p1 = self.selected_shapes[-1][0]
                    p2 = self.selected_shapes[-1][2]
                    shape_width = int(abs(p2.x() - p1.x()))
                    shape_height = int(abs(p2.y() - p1.y()))
                    self.show_shape.emit(shape_height, shape_width, pos)
            else:
                if (
                    self.pixmap
                    and self.pixmap.width()
                    and self.pixmap.height()
                ):
                    self.override_cursor(CURSOR_MOVE)
                    delta = ev.position() - self.prev_pan_point
                    self.scroll_request.emit(
                        delta.x() / (self.pixmap.width() * self.scale),
                        Qt.Orientation.Horizontal,
                        1,
                    )
                    self.scroll_request.emit(
                        delta.y() / (self.pixmap.height() * self.scale),
                        Qt.Orientation.Vertical,
                        1,
                    )
                    self.repaint()
            return

        if self.editing() and self.is_move_editing:
            self.override_cursor(CURSOR_MOVE)
            if self.selected_vertex():
                self.h_cuboid_face = None
                try:
                    self.bounded_move_vertex(pos)
                    self.repaint()
                    self.moving_shape = True
                except IndexError:
                    return
                if self.h_hape.shape_type == "rectangle":
                    p1 = self.h_hape[0]
                    p2 = self.h_hape[2]
                    shape_width = int(abs(p2.x() - p1.x()))
                    shape_height = int(abs(p2.y() - p1.y()))
                    self.show_shape.emit(shape_height, shape_width, pos)
                elif (
                    self.h_hape.shape_type == "cuboid"
                    and len(self.h_hape) >= 4
                ):
                    p1 = self.h_hape[0]
                    p2 = self.h_hape[2]
                    shape_width = int(abs(p2.x() - p1.x()))
                    shape_height = int(abs(p2.y() - p1.y()))
                    self.show_shape.emit(shape_height, shape_width, pos)
            elif (
                self.selected_cuboid_face()
                and self.h_hape is not None
                and self.h_hape.shape_type == "cuboid"
                and self.prev_point is not None
            ):
                offset = pos - self.prev_point
                self.move_cuboid_face_by(
                    self.h_hape, self.h_cuboid_face, offset
                )
                self.prev_point = pos
                self.repaint()
                self.moving_shape = True
                p1 = self.h_hape[0]
                p2 = self.h_hape[2]
                shape_width = int(abs(p2.x() - p1.x()))
                shape_height = int(abs(p2.y() - p1.y()))
                self.show_shape.emit(shape_height, shape_width, pos)
            else:
                self.is_move_editing = False

            return

        # --------------------------------------------------------------
        # Rectangle edge editing.
        # The live drag update has been hoisted to the top of
        # ``mouseMoveEvent`` (highest-priority guard above) so that, while
        # the left button is held, the move event is consumed before the
        # normal left-button pan/scroll block can emit ``scroll_request``.
        # What remains here is only the hover candidate computation (run
        # while no drag is in progress). No-op when the mode is off.
        # --------------------------------------------------------------
        if self.rect_edge_align_enabled:
            # Hover candidate computation. ``rect_edge_dragging`` is always
            # False here because an active drag was already handled by the
            # top-of-handler guard; the guard is kept for clarity.
            if not self.rect_edge_dragging:
                prev_hover = self.rect_edge_hover_edge
                candidate = self._rect_edge_hit_candidate(pos)
                if (
                    candidate is None
                    or prev_hover is None
                    or candidate.shape is not prev_hover.shape
                    or candidate.edge_name != prev_hover.edge_name
                ):
                    self.rect_edge_hover_edge = candidate
                    self.update()
                # Still fall through to the normal hover loop below so that
                # vertex hover keeps working when no edge is hovered.
                if candidate is not None:
                    # N1: mouse hover onto any rectangle edge hands the
                    # active-edge control back to the mouse — exit the
                    # keyboard-edge mode to avoid two active edges at once.
                    if self._clear_keyboard_edge():
                        self.update()
                    # Edge hovered: clear any stale shape/vertex/edge/cuboid
                    # hover state left over from a previous frame so the old
                    # highlight does not bleed through, then suppress the
                    # default hover loop (which would draw a whole-shape
                    # fill and clobber the edge highlight).
                    self.un_highlight()
                    self.show_shape.emit(-1, -1, pos)
                    # This branch returns early, so the default hover loop
                    # below (which normally sets the cursor) never runs;
                    # set the pointing-hand cursor explicitly to signal
                    # that the edge is selectable/grabbable.
                    self.override_cursor(CURSOR_POINT)
                    return

        self.show_shape.emit(-1, -1, pos)

        # Just hovering over the canvas, 2 possibilities:
        # - Highlight shapes
        # - Highlight vertex
        # Update shape/vertex fill and tooltip value accordingly.
        # self.setToolTip(self.tr("Image"))
        # [迁移自 beta.11 功能C] 用优先级排序候选列表取代 reversed+首次命中,
        # 使重叠/嵌套场景下优先高亮最近的顶点/边/小面积对象。
        for shape in self._shape_hit_candidates(pos):
            if shape.shape_type == "cuboid" and len(shape.points) == 8:
                index = self.nearest_cuboid_control(
                    shape, pos, self.epsilon / self.scale
                )
                if index is not None:
                    if self.selected_vertex():
                        self.h_hape.highlight_clear()
                    self.prev_h_vertex = self.h_vertex
                    self.h_vertex = index
                    self.prev_h_shape = self.h_hape = shape
                    self.prev_h_edge = self.h_edge
                    self.h_edge = None
                    self.prev_h_cuboid_face = self.h_cuboid_face
                    self.h_cuboid_face = None
                    shape.highlight_vertex(index, shape.MOVE_VERTEX)
                    self.override_cursor(CURSOR_POINT)
                    if index in CUBOID_BACK_EDGE_CENTER_INDICES:
                        self.setToolTip(
                            self.tr(
                                "Click & drag to adjust cuboid depth of shape '%s'"
                            )
                            % shape.label
                        )
                    elif index in [4, 5, 6, 7]:
                        self.setToolTip(
                            self.tr(
                                "Click & drag to adjust rear edge of cuboid shape '%s'"
                            )
                            % shape.label
                        )
                    else:
                        self.setToolTip(
                            self.tr("Click & drag to move point of shape '%s'")
                            % shape.label
                        )
                    self.setStatusTip(self.toolTip())
                    self.update()
                    break
                front_path = self.cuboid_face_path(shape, CUBOID_FACE_FRONT)
                if front_path is not None and front_path.contains(pos):
                    if self.selected_vertex():
                        self.h_hape.highlight_clear()
                    self.prev_h_vertex = self.h_vertex
                    self.h_vertex = None
                    self.prev_h_shape = self.h_hape = shape
                    self.prev_h_edge = self.h_edge
                    self.h_edge = None
                    self.prev_h_cuboid_face = self.h_cuboid_face
                    self.h_cuboid_face = None
                    self.setToolTip(
                        self.tr("Click & drag to move shape '%s'")
                        % shape.label
                    )
                    self.setStatusTip(self.toolTip())
                    self.override_cursor(CURSOR_GRAB)
                    self.update()
                    break
                face_name = self.cuboid_face_hit_test(shape, pos)
                if face_name and face_name != CUBOID_FACE_FRONT:
                    if self.selected_vertex():
                        self.h_hape.highlight_clear()
                    self.prev_h_vertex = self.h_vertex
                    self.h_vertex = None
                    self.prev_h_shape = self.h_hape = shape
                    self.prev_h_edge = self.h_edge
                    self.h_edge = None
                    self.prev_h_cuboid_face = self.h_cuboid_face
                    self.h_cuboid_face = face_name
                    self.override_cursor(CURSOR_POINT)
                    self.setToolTip(
                        self.tr(
                            "Click & drag to adjust cuboid %s face of shape '%s'"
                        )
                        % (face_name, shape.label)
                    )
                    self.setStatusTip(self.toolTip())
                    self.update()
                    break
            # Look for a nearby vertex to highlight. If that fails,
            # check if we happen to be inside a shape.
            index = shape.nearest_vertex(pos, self.epsilon / self.scale)
            index_edge = shape.nearest_edge(pos, self.epsilon / self.scale)
            if index is not None:
                if self.selected_vertex():
                    self.h_hape.highlight_clear()
                self.prev_h_vertex = self.h_vertex = index
                self.prev_h_shape = self.h_hape = shape
                self.prev_h_edge = self.h_edge
                self.h_edge = None
                self.prev_h_cuboid_face = self.h_cuboid_face
                self.h_cuboid_face = None
                shape.highlight_vertex(index, shape.MOVE_VERTEX)
                self.override_cursor(CURSOR_POINT)
                self.setToolTip(
                    self.tr("Click & drag to move point of shape '%s'")
                    % shape.label
                )
                self.setStatusTip(self.toolTip())
                self.update()
                break
            if (
                index_edge is not None
                and shape.can_add_point()
                and shape.shape_type != "quadrilateral"
            ):
                if self.selected_vertex():
                    self.h_hape.highlight_clear()
                self.prev_h_vertex = self.h_vertex
                self.h_vertex = None
                self.prev_h_shape = self.h_hape = shape
                self.prev_h_edge = self.h_edge = index_edge
                self.prev_h_cuboid_face = self.h_cuboid_face
                self.h_cuboid_face = None
                self.override_cursor(CURSOR_POINT)
                self.setToolTip(
                    self.tr("Click to create point of shape '%s'")
                    % shape.label
                )
                self.setStatusTip(self.toolTip())
                self.update()
                break
            shape_hit = False
            if shape.shape_type in ["point", "line", "linestrip"]:
                nearest_index = shape.nearest_vertex(
                    pos, self.epsilon * 3 / self.scale
                )
                if nearest_index is not None:
                    shape_hit = True
            elif shape.shape_type == "cuboid" and len(shape.points) == 8:
                front_path = self.cuboid_face_path(shape, CUBOID_FACE_FRONT)
                shape_hit = front_path is not None and front_path.contains(pos)
            elif len(shape.points) > 1 and shape.contains_point(pos):
                shape_hit = True

            if shape_hit:
                if self.selected_vertex():
                    self.h_hape.highlight_clear()
                self.prev_h_vertex = self.h_vertex
                self.h_vertex = None
                self.prev_h_shape = self.h_hape = shape
                self.prev_h_edge = self.h_edge
                self.h_edge = None
                self.prev_h_cuboid_face = self.h_cuboid_face
                self.h_cuboid_face = None
                if shape.group_id and shape.shape_type == "rectangle":
                    tooltip_text = "Click & drag to move shape '{label} {group_id}'".format(
                        label=shape.label, group_id=shape.group_id
                    )
                    self.setToolTip(self.tr(tooltip_text))
                else:
                    self.setToolTip(
                        self.tr("Click & drag to move shape '%s'")
                        % shape.label
                    )
                self.setStatusTip(self.toolTip())
                self.override_cursor(CURSOR_GRAB)
                # [Feature] Automatically highlight shape when the mouse is moved inside it
                if self.h_shape_is_hovered:
                    group_mode = (
                        ev.modifiers()
                        == QtCore.Qt.KeyboardModifier.ControlModifier
                    )
                    self.select_shape_point(
                        pos, multiple_selection_mode=group_mode
                    )
                self.update()

                if shape.shape_type == "rectangle":
                    p1 = self.h_hape[0]
                    p2 = self.h_hape[2]
                    shape_width = int(abs(p2.x() - p1.x()))
                    shape_height = int(abs(p2.y() - p1.y()))
                    self.show_shape.emit(shape_height, shape_width, pos)
                elif shape.shape_type == "cuboid" and len(self.h_hape) >= 4:
                    p1 = self.h_hape[0]
                    p2 = self.h_hape[2]
                    shape_width = int(abs(p2.x() - p1.x()))
                    shape_height = int(abs(p2.y() - p1.y()))
                    self.show_shape.emit(shape_height, shape_width, pos)
                break
        else:  # Nothing found, clear highlights, reset state.
            self.un_highlight()
            self.override_cursor(CURSOR_DEFAULT)
            self.setToolTip("")
            self.setStatusTip("")
        self.vertex_selected.emit(self.h_vertex is not None)

        if prev_hover_shape != self.h_hape:
            self.shape_hover_changed.emit()

    def add_point_to_edge(self):
        """Add a point to current shape"""
        shape = self.prev_h_shape
        index = self.prev_h_edge
        point = self.prev_move_point
        if shape is None or index is None or point is None:
            return
        shape.insert_point(index, point)
        shape.highlight_vertex(index, shape.MOVE_VERTEX)
        self.h_hape = shape
        self.h_vertex = index
        self.h_edge = None
        self.moving_shape = True
        self._pending_edge_point = (shape, index)

    def _undo_pending_edge_point(self):
        """Undo the edge point inserted by the preceding mousePressEvent"""
        if self._pending_edge_point is None:
            return
        shape, index = self._pending_edge_point
        self._pending_edge_point = None
        shape.remove_point(index)
        shape.highlight_clear()
        if len(self.shapes_backups) >= 2 and shape in self.shapes:
            self.shapes_backups.pop()

    def remove_selected_point(self):
        """Remove a point from current shape"""
        shape = self.prev_h_shape
        index = self.prev_h_vertex
        if shape is None or index is None:
            return
        shape.remove_point(index)
        shape.highlight_clear()
        self.h_hape = shape
        self.prev_h_vertex = None
        self.moving_shape = True  # Save changes

    def on_auto_decode_timeout(self):
        """Handle auto decode timeout"""
        if (
            not self.auto_decode_mode
            or self.auto_labeling_mode.shape_type != AutoLabelingMode.POINT
        ):
            return

        flag = -1
        if self.auto_labeling_mode.edit_mode == AutoLabelingMode.ADD:
            flag = 1
        elif self.auto_labeling_mode.edit_mode == AutoLabelingMode.REMOVE:
            flag = 0
        if flag == -1:
            return

        if self.auto_decode_mode and self.last_mouse_pos:
            if len(self.auto_decode_tracklet) >= MAX_AUTO_DECODE_MARKS:
                self.auto_decode_tracklet.pop(0)

            marks = {
                "type": "point",
                "data": [
                    int(self.last_mouse_pos.x()),
                    int(self.last_mouse_pos.y()),
                ],
                "label": flag,
            }
            self.auto_decode_tracklet.append(marks)
            self.auto_decode_requested.emit(self.auto_decode_tracklet)

    # QT Overload
    def mousePressEvent(self, ev):  # noqa: C901
        """Mouse press event"""
        if self.is_loading:
            return
        self._pending_edge_point = None

        if ev.button() == QtCore.Qt.MouseButton.LeftButton:
            if self._stable_preview_begin_window_interaction(ev.position()):
                return

        pos = self.transform_pos(ev.position())
        # Reset the precision-mode virtual cursor at every press so the
        # first drag delta is computed from the real press position.
        self._reset_virtual_cursor()

        if ev.button() == QtCore.Qt.MouseButton.LeftButton:
            # ----------------------------------------------------------
            # Rectangle edge editing.
            # Revalidate the edge at press time so a stale hover reference
            # cannot edit a rectangle that is no longer selected. Loading
            # and draw paths are unaffected because the hit test also checks
            # the capability and current canvas mode.
            # ----------------------------------------------------------
            hover = self._rect_edge_hit_candidate(pos)
            self.rect_edge_hover_edge = hover
            if hover is not None:
                self.prev_point = pos
                self.rect_edge_active_edge = hover
                self.rect_edge_dragging = True
                self.rect_edge_drag_start_points = list(hover.shape.points)
                if self.stable_preview_enabled:
                    self._stable_preview_begin_drag_locked(
                        pos, hover.edge_name
                    )
                # Pressing on a hovered edge starts a drag: switch to the
                # closed-hand cursor immediately so feedback is instant.
                self.override_cursor(CURSOR_MOVE)
                self.update()
                return
            if self.drawing():
                if self.current:
                    # Add point to existing shape.
                    if self.create_mode == "polygon":
                        self.current.add_point(self.line[1])
                        self.line[0] = self.current[-1]
                        if self.current.is_closed():
                            self.finalise()
                    elif self.create_mode in ["circle", "line"]:
                        assert len(self.current.points) == 1
                        self.current.points = self.line.points
                        self.finalise()
                    elif self.create_mode == "rectangle":
                        if self.current.reach_max_points() is False:
                            init_pos = self.current[0]
                            min_x = init_pos.x()
                            min_y = init_pos.y()
                            target_pos = self.line[1]
                            max_x = target_pos.x()
                            max_y = target_pos.y()
                            self.current.add_point(
                                QtCore.QPointF(max_x, min_y)
                            )
                            self.current.add_point(target_pos)
                            self.current.add_point(
                                QtCore.QPointF(min_x, max_y)
                            )
                            self.finalise()
                    elif self.create_mode == "cuboid":
                        if len(self.current.points) == 1:
                            init_pos = self.current[0]
                            target_pos = self.line[1]
                            front_points = self.make_rectangle_points(
                                init_pos, target_pos
                            )
                            if (
                                abs(front_points[2].x() - front_points[0].x())
                                < 1
                                or abs(
                                    front_points[2].y() - front_points[0].y()
                                )
                                < 1
                            ):
                                return
                            depth_vector = QtCore.QPointF(
                                self.cuboid_default_depth_vector[0],
                                self.cuboid_default_depth_vector[1],
                            )
                            self.set_cuboid_points(
                                self.current, front_points, depth_vector
                            )
                            self.finalise()
                    elif self.create_mode == "rotation":
                        initPos = self.current[0]
                        minX = initPos.x()
                        minY = initPos.y()
                        targetPos = self.line[1]
                        maxX = targetPos.x()
                        maxY = targetPos.y()
                        self.current.add_point(QtCore.QPointF(maxX, minY))
                        self.current.add_point(targetPos)
                        self.current.add_point(QtCore.QPointF(minX, maxY))
                        self.current.add_point(initPos)
                        self.line[0] = self.current[-1]
                        if self.current.is_closed():
                            self.finalise()
                    elif self.create_mode == "quadrilateral":
                        self.current.add_point(self.line[1])
                        self.line[0] = self.current[-1]
                        if self.current.is_closed():
                            self.finalise()
                    elif self.create_mode == "linestrip":
                        self.current.add_point(self.line[1])
                        self.line[0] = self.current[-1]
                        if (
                            ev.modifiers()
                            == QtCore.Qt.KeyboardModifier.ControlModifier
                        ):
                            self.finalise()
                    # [Feature] support for automatically switching to editing mode
                    # when the cursor moves over an object
                    if (
                        self.create_mode
                        in [
                            "rectangle",
                            "rotation",
                            "quadrilateral",
                            "cuboid",
                            "circle",
                            "line",
                            "point",
                        ]
                        and not self.is_auto_labeling
                        and not self.current
                    ):
                        self.prev_pan_point = ev.position()
                        self.mode_changed.emit()
                elif not self.out_off_pixmap(pos):
                    # Handle auto decode mode first click
                    if self.auto_decode_mode and self.is_auto_labeling:
                        if (
                            self.auto_labeling_mode.shape_type
                            == AutoLabelingMode.POINT
                        ):
                            self.last_mouse_pos = pos
                            self.on_auto_decode_timeout()
                            return

                    # Create new shape.
                    self.current = Shape(shape_type=self.create_mode)
                    self.current.add_point(pos)
                    if self.create_mode == "point":
                        self.finalise()
                    else:
                        if self.create_mode == "circle":
                            self.current.shape_type = "circle"
                        self.line.points = [pos, pos]
                        self.set_hiding()
                        self.drawing_polygon.emit(True)
                        self.update()
                elif (
                    self.out_off_pixmap(pos)
                    and self.create_mode == "linestrip"
                ):
                    w = self.pixmap.width()
                    h = self.pixmap.height()
                    if w > 0 and h > 0:
                        pos = QtCore.QPointF(
                            min(max(pos.x(), 0), w - 1),
                            min(max(pos.y(), 0), h - 1),
                        )
                        self.current = Shape(shape_type=self.create_mode)
                        self.current.add_point(pos)
                        self.line.points = [pos, pos]
                        self.set_hiding()
                        self.drawing_polygon.emit(True)
                        self.update()
                elif self.out_off_pixmap(pos) and self.create_mode in [
                    "rectangle",
                    "rotation",
                    "quadrilateral",
                    "cuboid",
                ]:
                    # Create new shape.
                    self.current = Shape(shape_type=self.create_mode)
                    self.current.add_point(pos)
                    self.line.points = [pos, pos]
                    self.set_hiding()
                    self.drawing_polygon.emit(True)
                    self.update()
            elif self.editing():
                if self.selected_edge():
                    self.add_point_to_edge()
                elif (
                    self.selected_vertex()
                    and ev.modifiers()
                    == QtCore.Qt.KeyboardModifier.ShiftModifier
                    and self.h_hape.shape_type
                    not in [
                        "rectangle",
                        "rotation",
                        "quadrilateral",
                        "line",
                        "cuboid",
                    ]
                ):
                    # Delete point if: left-click + SHIFT on a point
                    # (quadrilateral must keep exactly 4 points)
                    self.remove_selected_point()

                if (
                    self.selected_vertex()
                    and ev.modifiers()
                    != QtCore.Qt.KeyboardModifier.ShiftModifier
                ):
                    self.is_move_editing = not self.is_move_editing
                    if self.is_move_editing:
                        self.override_cursor(CURSOR_MOVE)
                    else:
                        self.override_cursor(CURSOR_POINT)

                group_mode = (
                    ev.modifiers()
                    == QtCore.Qt.KeyboardModifier.ControlModifier
                )
                if getattr(self, "_pending_initial_backup", False):
                    self.store_shapes()
                self.select_shape_point(
                    pos, multiple_selection_mode=group_mode
                )
                self.prev_point = pos
                self.prev_pan_point = ev.position()
                self.repaint()
                self.repaint()
        elif (
            ev.button() == QtCore.Qt.MouseButton.RightButton and self.editing()
        ):
            group_mode = (
                ev.modifiers() == QtCore.Qt.KeyboardModifier.ControlModifier
            )
            if not self.selected_shapes or (
                self.h_hape is not None
                and self.h_hape not in self.selected_shapes
            ):
                self.select_shape_point(
                    pos, multiple_selection_mode=group_mode
                )
                self.repaint()
            self.prev_point = pos

    # QT Overload
    def mouseReleaseEvent(self, ev):
        """Mouse release event"""
        if self.is_loading:
            return

        if (
            ev.button() == QtCore.Qt.MouseButton.LeftButton
            and self._stable_preview_window_interaction_active()
        ):
            self._stable_preview_end_window_interaction()
            return

        if ev.button() == QtCore.Qt.MouseButton.RightButton:
            menu = self.menus[len(self.selected_shapes_copy) > 0]
            self.restore_cursor()
            if (
                not menu.exec(self.mapToGlobal(ev.position().toPoint()))
                and self.selected_shapes_copy
            ):
                # Cancel the move by deleting the shadow copy.
                self.selected_shapes_copy = []
                self.repaint()
        elif ev.button() == QtCore.Qt.MouseButton.LeftButton:
            # ----------------------------------------------------------
            # Rectangle edge editing: commit on release.
            # One release forms exactly one undo granularity and only
            # stores/emits when the geometry actually changed.
            # ----------------------------------------------------------
            if self.rect_edge_dragging:
                active = self.rect_edge_active_edge
                start_points = self.rect_edge_drag_start_points
                changed = False
                if active is not None and start_points is not None:
                    current = active.shape.points
                    if len(current) != len(start_points):
                        changed = True
                    else:
                        for cur_pt, old_pt in zip(current, start_points):
                            if (
                                cur_pt.x() != old_pt.x()
                                or cur_pt.y() != old_pt.y()
                            ):
                                changed = True
                                break
                if changed:
                    self.store_shapes()
                    self.shape_moved.emit()
                self.clear_rect_edge_alignment()
                # Phase 2: a rect-edge release falls back to TargetPreview
                # if a single rectangle is still selected.
                self._stable_preview_enter_target_if_valid()
                self.update()
                return
            if self.editing():
                if (
                    self.h_hape is not None
                    and self.h_shape_is_selected
                    and not self.moving_shape
                ):
                    # 点击已选中对象，取消选中
                    self.selection_changed.emit(
                        [x for x in self.selected_shapes if x != self.h_hape]
                    )

        self.store_moving_shape()

    def end_move(self, copy):
        """End of move"""
        assert self.selected_shapes and self.selected_shapes_copy
        assert len(self.selected_shapes_copy) == len(self.selected_shapes)
        if copy:
            for i, shape in enumerate(self.selected_shapes_copy):
                self.shapes.append(shape)
                self.selected_shapes[i].selected = False
                self.selected_shapes[i] = shape
        else:
            for i, shape in enumerate(self.selected_shapes_copy):
                self.selected_shapes[i].points = shape.points
        self.selected_shapes_copy = []
        self.repaint()
        self.store_shapes()
        # Emit so selection-derived views refresh: a copy replaced the
        # selected shape references, and a move changed points/bbox (the
        # stable preview should re-evaluate its target rect).
        self.selection_changed.emit(self.selected_shapes)
        return True

    def hide_background_shapes(self, value):
        """Set hide background - hide other shapes when some shapes are selected"""
        self.hide_backround = value
        if self.selected_shapes:
            # Only hide other shapes if there is a current selection.
            # Otherwise the user will not be able to select a shape.
            self.set_hiding(True)
            self.update()

    def set_hiding(self, enable=True):
        """Set background hiding"""
        self._hide_backround = self.hide_backround if enable else False

    def can_close_shape(self):
        """Check if a shape can be closed (number of points > 2)"""
        return self.drawing() and self.current and len(self.current) > 2

    # QT Overload
    def mouseDoubleClickEvent(self, ev):
        """Mouse double click event"""
        if self.is_loading:
            return

        # Handle auto decode mode double click to finish
        if (
            self.auto_decode_mode
            and self.is_auto_labeling
            and self.auto_decode_tracklet
        ):
            self.auto_decode_finish_requested.emit()
            return

        if self.editing() and self.double_click_edit_label:
            pos = self.transform_pos(ev.position())
            # [迁移自 beta.11 功能C] 用优先级排序候选列表取代 reversed+首次命中,
            # 使双击嵌套对象时优先编辑内层(小面积)对象。
            for shape in self._shape_hit_candidates(pos):
                self._undo_pending_edge_point()
                if shape not in self.selected_shapes:
                    self.selection_changed.emit([shape])
                self.h_shape_is_selected = False
                self.edit_label_requested.emit()
                return

        # For polygon/quadrilateral the mousePress handler adds a spurious
        # duplicate point before this handler fires, so we pop it first.
        # For linestrip the press-added point IS the intended final point,
        # so we keep it and finalize directly.
        if self.double_click == "close" and self.can_close_shape():
            if self.create_mode == "linestrip":
                self.finalise()
            elif len(self.current) > 3:
                self.current.pop_point()
                self.finalise()

    def select_shapes(self, shapes):
        """Select some shapes"""
        shapes = shapes or []
        interactive_shapes = [
            s for s in shapes if self.is_shape_interactive(s)
        ]
        if (
            self.rect_edge_keyboard_shape is not None
            and (
                len(interactive_shapes) != 1
                or interactive_shapes[0] is not self.rect_edge_keyboard_shape
            )
        ):
            self._clear_keyboard_edge()
        self.set_hiding()
        self.selection_changed.emit(interactive_shapes)
        self.update()

    def select_shape_point(self, point, multiple_selection_mode):
        """Select the first shape created which contains this point."""
        if self.selected_vertex():  # A vertex is marked for selection.
            index, shape = self.h_vertex, self.h_hape
            if shape.shape_type == "cuboid":
                self.set_hiding()
                if shape not in self.selected_shapes:
                    if multiple_selection_mode:
                        self.selection_changed.emit(
                            self.selected_shapes + [shape]
                        )
                    else:
                        self.selection_changed.emit([shape])
                    self.h_shape_is_selected = False
                else:
                    self.h_shape_is_selected = True
                self.calculate_offsets(point)
                return
            shape.highlight_vertex(index, shape.MOVE_VERTEX)
            # [修复] 统一处理所有类型的顶点选择
            # 包括 point、rectangle、polygon、rotation 等
            self.set_hiding()
            if shape not in self.selected_shapes:
                if multiple_selection_mode:
                    self.selection_changed.emit(self.selected_shapes + [shape])
                else:
                    self.selection_changed.emit([shape])
                self.h_shape_is_selected = False
            else:
                # 重复点击已选中对象，取消选中
                self.h_shape_is_selected = True
            self.calculate_offsets(point)
            return
        elif self.selected_cuboid_face():
            # [修复] 处理立方体面选择
            shape = self.h_hape
            self.set_hiding()
            if shape not in self.selected_shapes:
                if multiple_selection_mode:
                    self.selection_changed.emit(self.selected_shapes + [shape])
                else:
                    self.selection_changed.emit([shape])
                self.h_shape_is_selected = False
            else:
                self.h_shape_is_selected = True
            self.calculate_offsets(point)
            return
        else:
            # [迁移自 beta.11 功能C] 普通形状选择逻辑
            # 用 _shape_hit_candidates 的优先级排序取代 reversed+首次contains命中,
            # 使重叠/嵌套场景下优先选中最近的顶点/边/小面积对象。
            for shape in self._shape_hit_candidates(point):
                self.set_hiding()
                if shape not in self.selected_shapes:
                    if multiple_selection_mode:
                        self.selection_changed.emit(
                            self.selected_shapes + [shape]
                        )
                    else:
                        self.selection_changed.emit([shape])
                    self.h_shape_is_selected = False
                else:
                    if getattr(self, "label_on_selection", False):
                        self.h_shape_is_selected = False
                    else:
                        self.h_shape_is_selected = True
                self.calculate_offsets(point)
                return
        self.deselect_shape()

    def calculate_offsets(self, point):
        """Calculate offsets of a point to pixmap borders"""
        left = self.pixmap.width() - 1
        right = 0
        top = self.pixmap.height() - 1
        bottom = 0
        for s in self.selected_shapes:
            rect = s.bounding_rect()
            if rect.left() < left:
                left = rect.left()
            if rect.right() > right:
                right = rect.right()
            if rect.top() < top:
                top = rect.top()
            if rect.bottom() > bottom:
                bottom = rect.bottom()

        x1 = left - point.x()
        y1 = top - point.y()
        x2 = right - point.x()
        y2 = bottom - point.y()
        self.offsets = QtCore.QPointF(x1, y1), QtCore.QPointF(x2, y2)

    def get_adjoint_points(self, theta, p3, p1, index):
        a1 = math.tan(theta)
        if a1 == 0:
            if index % 2 == 0:
                p2 = QtCore.QPointF(p3.x(), p1.y())
                p4 = QtCore.QPointF(p1.x(), p3.y())
            else:
                p4 = QtCore.QPointF(p3.x(), p1.y())
                p2 = QtCore.QPointF(p1.x(), p3.y())
        else:
            a3 = a1
            a2 = -1 / a1
            a4 = -1 / a1
            b1 = p1.y() - a1 * p1.x()
            b2 = p1.y() - a2 * p1.x()
            b3 = p3.y() - a1 * p3.x()
            b4 = p3.y() - a2 * p3.x()

            if index % 2 == 0:
                p2 = self.get_cross_point(a1, b1, a4, b4)
                p4 = self.get_cross_point(a2, b2, a3, b3)
            else:
                p4 = self.get_cross_point(a1, b1, a4, b4)
                p2 = self.get_cross_point(a2, b2, a3, b3)

        return p2, p3, p4

    @staticmethod
    def get_cross_point(a1, b1, a2, b2):
        x = (b2 - b1) / (a1 - a2)
        y = (a1 * b2 - a2 * b1) / (a1 - a2)
        return QtCore.QPointF(x, y)

    @staticmethod
    def make_rectangle_points(pt1, pt2):
        min_x = min(pt1.x(), pt2.x())
        min_y = min(pt1.y(), pt2.y())
        max_x = max(pt1.x(), pt2.x())
        max_y = max(pt1.y(), pt2.y())
        return [
            QtCore.QPointF(min_x, min_y),
            QtCore.QPointF(max_x, min_y),
            QtCore.QPointF(max_x, max_y),
            QtCore.QPointF(min_x, max_y),
        ]

    def get_cuboid_depth_vector(self, shape):
        depth_vector = shape.get_cuboid_depth_vector()
        return QtCore.QPointF(depth_vector[0], depth_vector[1])

    def cuboid_constraint_margin(self):
        return max(2.0, self.cuboid_min_depth * 0.2)

    def normalize_cuboid_depth(self, depth_vector):
        depth = math.hypot(depth_vector.x(), depth_vector.y())
        if depth >= self.cuboid_min_depth:
            return depth_vector
        if depth <= 1e-6:
            default_depth = QtCore.QPointF(
                self.cuboid_default_depth_vector[0],
                self.cuboid_default_depth_vector[1],
            )
            default_len = math.hypot(default_depth.x(), default_depth.y())
            if default_len <= 1e-6:
                return QtCore.QPointF(self.cuboid_min_depth, 0.0)
            scale = self.cuboid_min_depth / default_len
            return QtCore.QPointF(
                default_depth.x() * scale,
                default_depth.y() * scale,
            )
        scale = self.cuboid_min_depth / depth
        return QtCore.QPointF(
            depth_vector.x() * scale, depth_vector.y() * scale
        )

    def make_cuboid_points(self, front_points, depth_vector):
        depth_vector = self.normalize_cuboid_depth(depth_vector)
        back_points = [p + depth_vector for p in front_points]
        return list(front_points) + back_points

    def set_cuboid_points(
        self, shape, front_points, depth_vector, source="manual"
    ):
        shape.points = self.make_cuboid_points(front_points, depth_vector)
        shape.set_cuboid_depth_vector(
            [depth_vector.x(), depth_vector.y()],
            mode="from_rectangle",
            source=source,
        )

    def set_cuboid_raw_points(self, shape, points):
        shape.points = [QtCore.QPointF(p) for p in points]
        shape.sync_cuboid_depth_vector()

    @staticmethod
    def get_cuboid_back_offsets(shape):
        if shape.shape_type != "cuboid" or len(shape.points) != 8:
            return []
        return [shape.points[i + 4] - shape.points[i] for i in range(4)]

    def set_cuboid_front_with_offsets(self, shape, front_points, offsets):
        if len(front_points) != 4 or len(offsets) != 4:
            return
        points = [QtCore.QPointF(p) for p in front_points]
        points.extend([front_points[i] + offsets[i] for i in range(4)])
        self.set_cuboid_raw_points(shape, points)

    @staticmethod
    def _vector_dot(v1, v2):
        return v1.x() * v2.x() + v1.y() * v2.y()

    @staticmethod
    def _vector_length(v):
        return math.hypot(v.x(), v.y())

    @staticmethod
    def _vector_scale(v, s):
        return QtCore.QPointF(v.x() * s, v.y() * s)

    @staticmethod
    def _solve_vector_basis(target, basis_u, basis_v):
        det = basis_u.x() * basis_v.y() - basis_u.y() * basis_v.x()
        if abs(det) <= 1e-6:
            return None
        coeff_u = (target.x() * basis_v.y() - target.y() * basis_v.x()) / det
        coeff_v = (basis_u.x() * target.y() - basis_u.y() * target.x()) / det
        return coeff_u, coeff_v

    @staticmethod
    def get_mid_point(p1, p2):
        return QtCore.QPointF(
            (p1.x() + p2.x()) / 2.0,
            (p1.y() + p2.y()) / 2.0,
        )

    def cuboid_control_point(self, shape, index):
        if shape.shape_type != "cuboid" or len(shape.points) != 8:
            return None
        return shape.get_cuboid_control_point(index)

    def cuboid_visible_control_indices(self, shape):
        if shape.shape_type != "cuboid" or len(shape.points) != 8:
            return []
        return shape.get_cuboid_visible_control_indices()

    def nearest_cuboid_control(self, shape, pos, epsilon):
        min_distance = float("inf")
        nearest_index = None
        for index in self.cuboid_visible_control_indices(shape):
            control_point = self.cuboid_control_point(shape, index)
            if control_point is None:
                continue
            dist = utils.distance(control_point - pos)
            if dist <= epsilon and dist < min_distance:
                min_distance = dist
                nearest_index = index
        return nearest_index

    @staticmethod
    def cuboid_face_vertex_indices(face_name):
        mapping = {
            CUBOID_FACE_FRONT: [0, 1, 2, 3],
            CUBOID_FACE_RIGHT: [1, 2, 6, 5],
            CUBOID_FACE_LEFT: [0, 4, 7, 3],
            CUBOID_FACE_TOP: [0, 1, 5, 4],
            CUBOID_FACE_BOTTOM: [3, 2, 6, 7],
            CUBOID_FACE_BACK: [4, 5, 6, 7],
        }
        return mapping.get(face_name, [])

    def cuboid_face_path(self, shape, face_name):
        face_indices = self.cuboid_face_vertex_indices(face_name)
        if shape.shape_type != "cuboid" or len(shape.points) != 8:
            return None
        if len(face_indices) != 4:
            return None
        path = QtGui.QPainterPath()
        points = [shape.points[i] for i in face_indices]
        path.moveTo(points[0])
        for point in points[1:]:
            path.lineTo(point)
        path.closeSubpath()
        return path

    def cuboid_face_hit_test(self, shape, pos):
        if shape.shape_type != "cuboid" or len(shape.points) != 8:
            return None
        depth_vector = self.get_cuboid_depth_vector(shape)
        horizontal_faces = [CUBOID_FACE_RIGHT, CUBOID_FACE_LEFT]
        if depth_vector.x() < 0:
            horizontal_faces = [CUBOID_FACE_LEFT, CUBOID_FACE_RIGHT]
        face_order = horizontal_faces + [CUBOID_FACE_BACK]
        for face_name in face_order:
            face_path = self.cuboid_face_path(shape, face_name)
            if face_path is not None and face_path.contains(pos):
                return face_name
        return None

    def adjust_cuboid_visible_back_vertex(self, shape, index, pos):
        if shape.shape_type != "cuboid" or len(shape.points) != 8:
            return
        visible_rear = shape.get_cuboid_visible_rear_edge_indices()
        if len(visible_rear) != 2 or index not in visible_rear:
            return
        top_index, bottom_index = visible_rear
        points = [QtCore.QPointF(p) for p in shape.points]
        margin = self.cuboid_constraint_margin()
        top_indices = [0, 1, 4, 5]
        bottom_indices = [2, 3, 6, 7]
        if index == top_index:
            dy = pos.y() - points[top_index].y()
            max_dy = min(
                points[bottom_i].y() - margin - points[top_i].y()
                for top_i, bottom_i in zip(top_indices, bottom_indices)
            )
            dy = min(dy, max_dy)
            for top_i in top_indices:
                points[top_i].setY(points[top_i].y() + dy)
        else:
            dy = pos.y() - points[bottom_index].y()
            min_dy = max(
                points[top_i].y() + margin - points[bottom_i].y()
                for top_i, bottom_i in zip(top_indices, bottom_indices)
            )
            dy = max(dy, min_dy)
            for bottom_i in bottom_indices:
                points[bottom_i].setY(points[bottom_i].y() + dy)
        self.set_cuboid_raw_points(shape, points)

    def adjust_cuboid_front_vertex(self, shape, index, pos):
        if shape.shape_type != "cuboid" or len(shape.points) != 8:
            return
        if index not in [0, 1, 2, 3]:
            return
        front_points = [QtCore.QPointF(p) for p in shape.points[:4]]
        offsets = self.get_cuboid_back_offsets(shape)
        min_size = self.cuboid_constraint_margin()
        order = [index, (index + 1) % 4, (index + 2) % 4, (index + 3) % 4]
        p0 = QtCore.QPointF(front_points[order[0]])
        p1 = QtCore.QPointF(front_points[order[1]])
        p2 = QtCore.QPointF(front_points[order[2]])
        p3 = QtCore.QPointF(front_points[order[3]])
        basis_u = p1 - p0
        basis_v = p3 - p0
        len_u = self._vector_length(basis_u)
        len_v = self._vector_length(basis_v)
        if len_u <= 1e-6 or len_v <= 1e-6:
            return
        unit_u = self._vector_scale(basis_u, 1.0 / len_u)
        unit_v = self._vector_scale(basis_v, 1.0 / len_v)
        target = p2 - pos
        solved = self._solve_vector_basis(target, unit_u, unit_v)
        if solved is None:
            return
        coeff_u, coeff_v = solved
        coeff_u = max(coeff_u, min_size)
        coeff_v = max(coeff_v, min_size)
        new_p0 = (
            p2
            - self._vector_scale(unit_u, coeff_u)
            - self._vector_scale(unit_v, coeff_v)
        )
        new_p1 = p2 - self._vector_scale(unit_v, coeff_v)
        new_p3 = p2 - self._vector_scale(unit_u, coeff_u)
        front_points[order[0]] = new_p0
        front_points[order[1]] = new_p1
        front_points[order[3]] = new_p3
        front_points[order[2]] = p2
        self.set_cuboid_front_with_offsets(shape, front_points, offsets)

    def adjust_cuboid_front_edge(self, shape, index, pos):
        if shape.shape_type != "cuboid" or len(shape.points) != 8:
            return
        front_points = [QtCore.QPointF(p) for p in shape.points[:4]]
        offsets = self.get_cuboid_back_offsets(shape)
        min_size = self.cuboid_constraint_margin()
        edge_map = {
            Shape.CUBOID_FRONT_LEFT_EDGE_CENTER: (0, 3, 1, 2),
            Shape.CUBOID_FRONT_RIGHT_EDGE_CENTER: (1, 2, 0, 3),
            Shape.CUBOID_FRONT_TOP_EDGE_CENTER: (0, 1, 3, 2),
            Shape.CUBOID_FRONT_BOTTOM_EDGE_CENTER: (3, 2, 0, 1),
        }
        if index not in edge_map:
            return
        edge_a, edge_b, opposite_a, opposite_b = edge_map[index]
        dragged_center = self.get_mid_point(
            front_points[edge_a], front_points[edge_b]
        )
        edge_vector = front_points[edge_b] - front_points[edge_a]
        edge_length = self._vector_length(edge_vector)
        if edge_length <= 1e-6:
            return
        normal = QtCore.QPointF(
            -edge_vector.y() / edge_length,
            edge_vector.x() / edge_length,
        )
        edge_distance = self._vector_dot(
            front_points[opposite_a] - front_points[edge_a], normal
        )
        if edge_distance < 0:
            normal = self._vector_scale(normal, -1.0)
            edge_distance = -edge_distance
        shift = self._vector_dot(pos - dragged_center, normal)
        max_shift = edge_distance - min_size
        if shift > max_shift:
            shift = max_shift
        shift_vector = self._vector_scale(normal, shift)
        front_points[edge_a] = front_points[edge_a] + shift_vector
        front_points[edge_b] = front_points[edge_b] + shift_vector
        self.set_cuboid_front_with_offsets(shape, front_points, offsets)

    def adjust_cuboid_back_edge_center(self, shape, index, pos):
        if shape.shape_type != "cuboid" or len(shape.points) != 8:
            return
        visible_center_index = shape.get_cuboid_visible_rear_center_index()
        if index != visible_center_index:
            return
        points = [QtCore.QPointF(p) for p in shape.points]
        center = shape.get_cuboid_control_point(index)
        if center is None:
            return
        margin = self.cuboid_constraint_margin()
        front_right = max(points[1].x(), points[2].x())
        front_left = min(points[0].x(), points[3].x())
        target_x = pos.x()
        front_center_index = Shape.CUBOID_FRONT_RIGHT_EDGE_CENTER
        if index == Shape.CUBOID_BACK_RIGHT_EDGE_CENTER:
            target_x = max(target_x, front_right + margin)
        else:
            target_x = min(target_x, front_left - margin)
            front_center_index = Shape.CUBOID_FRONT_LEFT_EDGE_CENTER
        dx = target_x - center.x()
        front_center = shape.get_cuboid_control_point(front_center_index)
        dy = 0.0
        if front_center is not None:
            dir_x = center.x() - front_center.x()
            if abs(dir_x) > 1e-6:
                dir_y = center.y() - front_center.y()
                dy = dx * dir_y / dir_x
        for i in range(4, 8):
            points[i].setX(points[i].x() + dx)
            points[i].setY(points[i].y() + dy)
        self.set_cuboid_raw_points(shape, points)

    def move_cuboid_control(self, shape, index, pos):
        if shape.shape_type != "cuboid" or len(shape.points) != 8:
            return
        if index in [0, 1, 2, 3]:
            self.adjust_cuboid_front_vertex(shape, index, pos)
            return
        if index in [4, 5, 6, 7]:
            self.adjust_cuboid_visible_back_vertex(shape, index, pos)
            return
        if index in CUBOID_FRONT_EDGE_CENTER_INDICES:
            self.adjust_cuboid_front_edge(shape, index, pos)
            return
        if index in CUBOID_BACK_EDGE_CENTER_INDICES:
            self.adjust_cuboid_back_edge_center(shape, index, pos)

    def move_cuboid_face_by(self, shape, face_name, offset):
        if shape.shape_type != "cuboid" or len(shape.points) != 8:
            return
        min_size = self.cuboid_constraint_margin()
        if face_name == CUBOID_FACE_LEFT:
            points = [QtCore.QPointF(p) for p in shape.points]
            front_right_mid = (points[1].x() + points[2].x()) / 2.0
            back_right_mid = (points[5].x() + points[6].x()) / 2.0
            right_top, right_bottom = (1, 2)
            if back_right_mid > front_right_mid:
                right_top, right_bottom = (5, 6)
            right_candidates = [
                points[right_top].x(),
                (points[right_top].x() + points[right_bottom].x()) / 2.0,
                points[right_bottom].x(),
            ]
            right_limit_x = min(right_candidates) - min_size
            left_indices = [0, 3, 4, 7]
            left_max_x = max(points[i].x() for i in left_indices)
            dx = offset.x()
            if dx > 0:
                dx = min(dx, right_limit_x - left_max_x)
            dy = offset.y()
            for i in left_indices:
                points[i].setX(points[i].x() + dx)
                points[i].setY(points[i].y() + dy)
            self.set_cuboid_raw_points(shape, points)
        elif face_name == CUBOID_FACE_RIGHT:
            points = [QtCore.QPointF(p) for p in shape.points]
            front_left_mid = (points[0].x() + points[3].x()) / 2.0
            back_left_mid = (points[4].x() + points[7].x()) / 2.0
            left_top, left_bottom = (0, 3)
            if back_left_mid < front_left_mid:
                left_top, left_bottom = (4, 7)
            left_candidates = [
                points[left_top].x(),
                (points[left_top].x() + points[left_bottom].x()) / 2.0,
                points[left_bottom].x(),
            ]
            left_limit_x = max(left_candidates) + min_size
            right_indices = [1, 2, 5, 6]
            right_min_x = min(points[i].x() for i in right_indices)
            dx = offset.x()
            if dx < 0:
                dx = max(dx, left_limit_x - right_min_x)
            dy = offset.y()
            for i in right_indices:
                points[i].setX(points[i].x() + dx)
                points[i].setY(points[i].y() + dy)
            self.set_cuboid_raw_points(shape, points)
        elif face_name == CUBOID_FACE_BACK:
            points = [QtCore.QPointF(p) for p in shape.points]
            next_back_points = [QtCore.QPointF(points[i]) for i in range(4, 8)]
            for p in next_back_points:
                p.setX(p.x() + offset.x())
                p.setY(p.y() + offset.y())
            for i, p in enumerate(next_back_points, start=4):
                points[i] = p
            self.set_cuboid_raw_points(shape, points)
        else:
            return

    def bounded_move_vertex(self, pos):
        """Move a vertex. Adjust position to be bounded by pixmap border"""
        index, shape = self.h_vertex, self.h_hape
        if shape.shape_type == "cuboid":
            self.move_cuboid_control(shape, index, pos)
            return
        point = shape[index]
        if (
            self.out_off_pixmap(pos)
            and shape.shape_type not in self.allowed_oop_shape_types
        ):
            pos = self.intersection_point(point, pos)

        if shape.shape_type == "rotation":
            sindex = (index + 2) % 4
            # Get the other 3 points after transformed
            p2, p3, p4 = self.get_adjoint_points(
                shape.direction, shape[sindex], pos, index
            )
            # if (
            #     self.out_off_pixmap(p2)
            #     or self.out_off_pixmap(p3)
            #     or self.out_off_pixmap(p4)
            # ):
            #     # No need to move if one pixal out of map
            #     return
            # Move 4 pixal one by one
            shape.move_vertex_by(index, pos - point)
            lindex = (index + 1) % 4
            rindex = (index + 3) % 4
            shape[lindex] = p2
            shape[rindex] = p4
            shape.close()
        elif shape.shape_type == "rectangle":
            shift_pos = pos - point
            shape.move_vertex_by(index, shift_pos)
            left_index = (index + 1) % 4
            right_index = (index + 3) % 4
            left_shift = None
            right_shift = None
            if index % 2 == 0:
                right_shift = QtCore.QPointF(shift_pos.x(), 0)
                left_shift = QtCore.QPointF(0, shift_pos.y())
            else:
                left_shift = QtCore.QPointF(shift_pos.x(), 0)
                right_shift = QtCore.QPointF(0, shift_pos.y())
            shape.move_vertex_by(right_index, right_shift)
            shape.move_vertex_by(left_index, left_shift)
        else:
            shape.move_vertex_by(index, pos - point)

    def bounded_move_shapes(self, shapes, pos):
        """Move shapes. Adjust position to be bounded by pixmap border"""
        shape_types = []
        for shape in shapes:
            if shape.shape_type in self.allowed_oop_shape_types:
                shape_types.append(shape.shape_type)

        if self.out_off_pixmap(pos) and len(shape_types) == 0:
            return False  # No need to move
        if len(shape_types) > 0 and len(shapes) != len(shape_types):
            return False

        if len(shape_types) == 0:
            o1 = pos + self.offsets[0]
            if self.out_off_pixmap(o1):
                pos -= QtCore.QPointF(min(0, int(o1.x())), min(0, int(o1.y())))
            o2 = pos + self.offsets[1]
            if self.out_off_pixmap(o2):
                pos += QtCore.QPointF(
                    min(0, int(self.pixmap.width() - o2.x())),
                    min(0, int(self.pixmap.height() - o2.y())),
                )
        # XXX: The next line tracks the new position of the cursor
        # relative to the shape, but also results in making it
        # a bit "shaky" when nearing the border and allows it to
        # go outside of the shape's area for some reason.
        # self.calculateOffsets(self.selectedShapes, pos)
        dp = pos - self.prev_point
        if dp:
            for shape in shapes:
                shape.move_by(dp)
            self.prev_point = pos
            return True
        return False

    def rotate_point(self, p, center, theta):
        order = p - center
        cosTheta = math.cos(theta)
        sinTheta = math.sin(theta)
        pResx = cosTheta * order.x() + sinTheta * order.y()
        pResy = -sinTheta * order.x() + cosTheta * order.y()
        pRes = QtCore.QPointF(center.x() + pResx, center.y() + pResy)
        return pRes

    def bounded_rotate_shapes(self, i, shape, theta):
        """Rotate shapes. Adjust position to be bounded by pixmap border"""
        if len(shape.points) == 2:
            p0 = shape.points[0]
            p1 = shape.points[1]
            shape.points = [
                p0,
                QtCore.QPointF(
                    (p0.x() + p1.x()) / 2,
                    p0.y(),
                ),
                p1,
                QtCore.QPointF(p1.x(), (p0.y() + p1.y()) / 2),
            ]
        center = QtCore.QPointF(
            (shape.points[0].x() + shape.points[2].x()) / 2,
            (shape.points[0].y() + shape.points[2].y()) / 2,
        )
        for j, p in enumerate(shape.points):
            pos = self.rotate_point(p, center, theta)
            # TODO: Reserved for now
            # if self.out_off_pixmap(pos):
            #     return False  # No need to rotate
            shape.points[j] = pos
        shape.direction = (shape.direction - theta) % (2 * math.pi)
        return True

    def deselect_shape(self):
        """Deselect all shapes"""
        if self.selected_shapes:
            self._clear_keyboard_edge()
            self.set_hiding(False)
            self.selection_changed.emit([])
            self.h_shape_is_selected = False
            self.h_cuboid_face = None
            self.update()

    def delete_selected(self):
        """Remove selected shapes"""
        deleted_shapes = []
        if self.selected_shapes:
            self._clear_keyboard_edge()
            for shape in self.selected_shapes:
                self.shapes.remove(shape)
                deleted_shapes.append(shape)
            self.store_shapes()
            self.selected_shapes = []
            # Emit so selection-derived views drop the deleted shape;
            # delete_selected mutated selected_shapes without signalling.
            self.selection_changed.emit(self.selected_shapes)
            self.update()
        return deleted_shapes

    def delete_shape(self, shape):
        """Remove a specific shape"""
        was_selected = shape in self.selected_shapes
        if was_selected:
            self.selected_shapes.remove(shape)
            self._clear_keyboard_edge()
        if shape in self.shapes:
            self.shapes.remove(shape)
        self.store_shapes()
        # Emit only when the deleted shape was part of the selection, so
        # selection-derived views drop it; delete_shape mutated
        # selected_shapes without signalling.
        if was_selected:
            self.selection_changed.emit(self.selected_shapes)
        self.update()

    def duplicate_selected_shapes(self):
        """Duplicate selected shapes"""
        if self.selected_shapes:
            self.selected_shapes_copy = [
                s.copy() for s in self.selected_shapes
            ]
            self.bounded_shift_shapes(self.selected_shapes_copy)
            self.end_move(copy=True)
        return self.selected_shapes

    def bounded_shift_shapes(self, shapes):
        """
        Shift shapes by an offset. Adjust positions to be bounded
        by pixmap borders
        """
        # Try to move in one direction, and if it fails in another.
        # Give up if both fail.
        point = shapes[0][0]
        offset = QtCore.QPointF(2.0, 2.0)
        self.offsets = QtCore.QPointF(), QtCore.QPointF()
        self.prev_point = point
        if not self.bounded_move_shapes(shapes, point - offset):
            self.bounded_move_shapes(shapes, point + offset)

    # QT Overload
    def paintEvent(self, event):  # noqa: C901
        """Paint event for canvas"""
        _t0 = time.perf_counter()
        if (
            self.pixmap is None
            or self.pixmap.width() == 0
            or self.pixmap.height() == 0
        ):
            super().paintEvent(event)
            return

        p = self._painter
        p.begin(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        offset = self.offset_to_center()
        p.scale(self.scale, self.scale)
        p.translate(offset)

        # Compute scene viewport for culling
        viewport_rect = QtCore.QRectF(
            -offset.x(),
            -offset.y(),
            self.width() / self.scale,
            self.height() / self.scale,
        )

        p.drawPixmap(0, 0, self.pixmap)

        # Draw compare view: left side shows compare image, right side shows original
        # split_position: 0 = all original, 1 = all compare
        if (
            self.compare_pixmap is not None
            and not self.compare_pixmap.isNull()
        ):
            split_x = int(self.split_position * self.pixmap.width())
            if split_x > 0:
                p.drawPixmap(
                    0,
                    0,
                    self.compare_pixmap,
                    0,
                    0,
                    split_x,
                    self.pixmap.height(),
                )

        Shape.scale = self.scale

        # Draw loading/waiting screen
        if self.is_loading:
            # Draw a semi-transparent rectangle
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(0, 0, 0, 20))
            p.drawRect(self.pixmap.rect())

            # Draw a spinning wheel
            p.setPen(QtGui.QColor(255, 255, 255))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.save()
            p.translate(self.pixmap.width() / 2, self.pixmap.height() / 2 - 50)
            p.rotate(self.loading_angle)
            p.drawEllipse(-20, -20, 40, 40)
            p.drawLine(0, 0, 0, -20)
            p.restore()
            self.loading_angle += 30
            if self.loading_angle >= 360:
                self.loading_angle = 0

            # Draw the loading text
            p.setPen(QtGui.QColor(255, 255, 255))
            p.setFont(QtGui.QFont("Arial", 20))
            p.drawText(
                self.pixmap.rect(),
                Qt.AlignmentFlag.AlignCenter,
                self.loading_text,
            )
            p.end()
            self.update()
            return

        # Draw groups
        if self.show_groups:
            pen = QtGui.QPen(QtGui.QColor("#AAAAAA"), 2, Qt.PenStyle.SolidLine)
            p.setPen(pen)
            grouped_shapes = {}
            for shape in self.shapes:
                if not shape.visible or getattr(
                    shape, "hidden_by_filter", False
                ):
                    continue
                if shape.group_id is None:
                    continue
                if shape.group_id not in grouped_shapes:
                    grouped_shapes[shape.group_id] = []
                grouped_shapes[shape.group_id].append(shape)

            for group_id in grouped_shapes:
                shapes = grouped_shapes[group_id]
                min_x = float("inf")
                min_y = float("inf")
                max_x = 0
                max_y = 0
                for shape in shapes:
                    rect = shape.bounding_rect()
                    if shape.shape_type == "point":
                        points = shape.points[0]
                        min_x = min(min_x, points.x())
                        min_y = min(min_y, points.y())
                        max_x = max(max_x, points.x())
                        max_y = max(max_y, points.y())
                    else:
                        min_x = min(min_x, rect.x())
                        min_y = min(min_y, rect.y())
                        max_x = max(max_x, rect.x() + rect.width())
                        max_y = max(max_y, rect.y() + rect.height())
                    group_color = LABEL_COLORMAP[
                        int(group_id) % len(LABEL_COLORMAP)
                    ]
                    pen.setStyle(Qt.PenStyle.SolidLine)
                    pen.setWidth(max(1, int(round(4.0 / Shape.scale))))
                    pen.setColor(QtGui.QColor(*group_color))
                    p.setPen(pen)

                    # Calculate the center point of the bounding rectangle
                    cx = rect.x() + rect.width() / 2
                    cy = rect.y() + rect.height() / 2
                    triangle_radius = max(1, int(round(3.0 / Shape.scale)))

                    # Define the points of the triangle
                    triangle_points = [
                        QtCore.QPointF(cx, cy - triangle_radius),
                        QtCore.QPointF(
                            cx - triangle_radius, cy + triangle_radius
                        ),
                        QtCore.QPointF(
                            cx + triangle_radius, cy + triangle_radius
                        ),
                    ]

                    # Draw the triangle
                    p.drawPolygon(triangle_points)

                pen.setStyle(Qt.PenStyle.DashLine)
                pen.setWidth(max(1, int(round(1.0 / Shape.scale))))
                pen.setColor(QtGui.QColor("#EEEEEE"))
                p.setPen(pen)
                wrap_rect = QtCore.QRectF(
                    min_x, min_y, max_x - min_x, max_y - min_y
                )
                p.drawRect(wrap_rect)

        # Draw KIE linking
        if self.show_linking:
            pen = QtGui.QPen(QtGui.QColor("#AAAAAA"), 2, Qt.PenStyle.SolidLine)
            p.setPen(pen)
            gid2point = {}
            linking_pairs = []
            group_color = (255, 128, 0)
            for shape in self.shapes:
                if not shape.visible or getattr(
                    shape, "hidden_by_filter", False
                ):
                    continue

                try:
                    linking_pairs += shape.kie_linking
                except Exception:
                    pass

                if shape.group_id is None or shape.shape_type not in [
                    "rectangle",
                    "polygon",
                    "rotation",
                    "quadrilateral",
                    "cuboid",
                ]:
                    continue
                rect = shape.bounding_rect()
                cx = rect.x() + (rect.width() / 2.0)
                cy = rect.y() + (rect.height() / 2.0)
                gid2point[shape.group_id] = (cx, cy)

            for linking in linking_pairs:
                pen.setStyle(Qt.PenStyle.SolidLine)
                pen.setWidth(max(1, int(round(4.0 / Shape.scale))))
                pen.setColor(QtGui.QColor(*group_color))
                p.setPen(pen)
                key, value = linking
                # Adapt to the 'ungroup_selected_shapes' operation
                if key not in gid2point or value not in gid2point:
                    continue
                kp, vp = gid2point[key], gid2point[value]
                # Draw a link from key point to value point
                p.drawLine(QtCore.QPointF(*kp), QtCore.QPointF(*vp))
                # Draw the triangle arrowhead
                arrow_size = max(
                    1, int(round(10.0 / Shape.scale))
                )  # Size of the arrowhead
                angle = math.atan2(
                    vp[1] - kp[1], vp[0] - kp[0]
                )  # Angle towards the value point
                arrow_points = [
                    QtCore.QPointF(vp[0], vp[1]),
                    QtCore.QPointF(
                        vp[0] - arrow_size * math.cos(angle - math.pi / 6),
                        vp[1] - arrow_size * math.sin(angle - math.pi / 6),
                    ),
                    QtCore.QPointF(
                        vp[0] - arrow_size * math.cos(angle + math.pi / 6),
                        vp[1] - arrow_size * math.sin(angle + math.pi / 6),
                    ),
                ]
                p.drawPolygon(arrow_points)

        # Draw shape masks
        if self.show_masks:
            for shape in self.shapes:
                if not shape.visible or getattr(
                    shape, "hidden_by_filter", False
                ):
                    continue
                if shape.shape_type not in [
                    "polygon",
                    "rectangle",
                    "rotation",
                    "quadrilateral",
                    "circle",
                ]:
                    continue
                if shape.shape_type == "polygon" and len(shape.points) < 3:
                    continue
                if shape.shape_type == "rectangle" and len(shape.points) < 2:
                    continue
                if shape.shape_type == "rotation" and len(shape.points) < 2:
                    continue
                if (
                    shape.shape_type == "quadrilateral"
                    and len(shape.points) < 4
                ):
                    continue
                if shape.shape_type == "circle" and len(shape.points) < 2:
                    continue
                if not (
                    (shape.selected or not self._hide_backround)
                    and self.is_visible(shape)
                ):
                    continue

                mask_path = QtGui.QPainterPath()
                if shape.shape_type == "polygon":
                    mask_path.moveTo(shape.points[0])
                    for point in shape.points[1:]:
                        mask_path.lineTo(point)
                    if shape.is_closed() or len(shape.points) >= 3:
                        mask_path.closeSubpath()
                elif shape.shape_type == "rectangle":
                    if len(shape.points) == 2:
                        rectangle = shape.get_rect_from_line(*shape.points)
                        mask_path.addRect(rectangle)
                    elif len(shape.points) == 4:
                        mask_path.moveTo(shape.points[0])
                        for point in shape.points[1:]:
                            mask_path.lineTo(point)
                        mask_path.closeSubpath()
                elif shape.shape_type == "rotation":
                    if len(shape.points) == 2:
                        rectangle = shape.get_rect_from_line(*shape.points)
                        mask_path.addRect(rectangle)
                    elif len(shape.points) == 4:
                        mask_path.moveTo(shape.points[0])
                        for point in shape.points[1:]:
                            mask_path.lineTo(point)
                        mask_path.closeSubpath()
                elif shape.shape_type == "quadrilateral":
                    if len(shape.points) == 4:
                        mask_path.moveTo(shape.points[0])
                        for point in shape.points[1:]:
                            mask_path.lineTo(point)
                        mask_path.closeSubpath()
                elif shape.shape_type == "circle":
                    if len(shape.points) == 2:
                        rectangle = shape.get_circle_rect_from_line(
                            shape.points
                        )
                        mask_path.addEllipse(rectangle)

                fill_color = (
                    shape.select_line_color
                    if shape.selected
                    else shape.line_color
                )
                fill_color_alpha = QtGui.QColor(
                    fill_color.red(),
                    fill_color.green(),
                    fill_color.blue(),
                    self.mask_opacity,
                )
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(fill_color_alpha)
                p.drawPath(mask_path)

                outline_color = (
                    shape.select_line_color
                    if shape.selected
                    else shape.line_color
                )
                pen = QtGui.QPen(outline_color)
                pen.setWidth(
                    max(1, int(round(shape.line_width / Shape.scale)))
                )
                if shape.difficult:
                    pen.setStyle(Qt.PenStyle.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(mask_path)

        # Draw degrees
        for shape in self.shapes:
            if not shape.visible or getattr(shape, "hidden_by_filter", False):
                continue
            if not viewport_rect.intersects(shape.bounding_rect()):
                continue
            if (
                shape.selected or not self._hide_backround
            ) and self.is_visible(shape):
                shape.hovered = shape == self.h_hape
                shape.fill = (
                    self._fill_drawing
                    and (shape.selected or shape == self.h_hape)
                    and not (self.selected_vertex() and self.moving_shape)
                )
                shape.paint(p)

            if (
                shape.shape_type == "rotation"
                and len(shape.points) == 4
                and self.is_visible(shape)
            ):
                d = shape.point_size / shape.scale
                center = QtCore.QPointF(
                    (shape.points[0].x() + shape.points[2].x()) / 2,
                    (shape.points[0].y() + shape.points[2].y()) / 2,
                )
                if self.show_degrees:
                    degrees = math.degrees(shape.direction)
                    if abs(degrees - 360.0) < 0.1:
                        degrees = 0.0
                    degrees = f"{degrees:.2f}°"
                    p.setFont(
                        QtGui.QFont(
                            "Arial",
                            int(max(6.0, int(round(8.0 / Shape.scale)))),
                        )
                    )
                    pen = QtGui.QPen(
                        QtGui.QColor("#FF9900"),
                        8,
                        QtCore.Qt.PenStyle.SolidLine,
                    )
                    p.setPen(pen)
                    fm = QtGui.QFontMetrics(p.font())
                    rect = fm.boundingRect(degrees)
                    p.fillRect(
                        int(rect.x() + center.x() - d),
                        int(rect.y() + center.y() + d),
                        int(rect.width()),
                        int(rect.height()),
                        QtGui.QColor("#FF9900"),
                    )
                    pen = QtGui.QPen(
                        QtGui.QColor("#FFFFFF"),
                        7,
                        QtCore.Qt.PenStyle.SolidLine,
                    )
                    p.setPen(pen)
                    p.drawText(
                        int(center.x() - d),
                        int(center.y() + d),
                        degrees,
                    )
                else:
                    cp = QtGui.QPainterPath()
                    cp.addRect(
                        int(center.x() - d / 2),
                        int(center.y() - d / 2),
                        int(d),
                        int(d),
                    )
                    p.drawPath(cp)
                    p.fillPath(cp, QtGui.QColor(255, 153, 0, 255))

        if self.current:
            self.current.paint(p)
            self.line.paint(p)

            if (
                self.create_mode == "quadrilateral"
                and len(self.current.points) == 3
                and len(self.line.points) >= 2
            ):
                color = (
                    self.current.select_line_color
                    if self.current.selected
                    else self.current.line_color
                )
                pen = QtGui.QPen(color)
                pen.setWidth(
                    max(1, int(round(self.current.line_width / Shape.scale)))
                )
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawLine(QtCore.QLineF(self.line[1], self.current.points[0]))
        if self.selected_shapes_copy:
            for s in self.selected_shapes_copy:
                s.paint(p)

        if (
            self.fill_drawing()
            and self.create_mode == "polygon"
            and self.current is not None
            and len(self.current.points) >= 2
        ):
            drawing_shape = self.current.copy()
            drawing_shape.add_point(self.line[1])
            drawing_shape.fill = True
            drawing_shape.paint(p)
        if (
            self.fill_drawing()
            and self.create_mode == "quadrilateral"
            and self.current is not None
            and len(self.current.points) == 3
            and len(self.line.points) >= 2
        ):
            drawing_shape = self.current.copy()
            drawing_shape.points = list(self.current.points) + [
                QtCore.QPointF(self.line[1].x(), self.line[1].y())
            ]
            drawing_shape.fill = True
            drawing_shape._closed = True
            drawing_shape.paint(p)

        autolabel_names = {
            "AUTOLABEL_OBJECT",
            "AUTOLABEL_ADD",
            "AUTOLABEL_REMOVE",
        }

        def should_merge_rectangle_text(shape):
            return (
                self.show_labels
                and shape.shape_type == "rectangle"
                and not (self.label_on_selection and not shape.selected)
                and shape.label not in autolabel_names
            )

        # Draw texts
        if self.show_texts:
            text_color = "#FFFFFF"
            background_color = "#007BFF"
            p.setFont(
                QtGui.QFont(
                    "Arial", int(max(6.0, int(round(8.0 / Shape.scale))))
                )
            )
            pen = QtGui.QPen(
                QtGui.QColor(background_color), 8, Qt.PenStyle.SolidLine
            )
            p.setPen(pen)
            for shape in self.shapes:
                if not shape.visible or getattr(
                    shape, "hidden_by_filter", False
                ):
                    continue
                if should_merge_rectangle_text(shape):
                    continue
                description = shape.description
                if description:
                    bbox = shape.bounding_rect()
                    fm = QtGui.QFontMetrics(p.font())
                    text_rect = fm.tightBoundingRect(description)

                    padding_x = 4
                    padding_y = 2
                    rect_width = text_rect.width() + 2 * padding_x
                    rect_height = fm.height() + 2 * padding_y

                    bg_x = int(bbox.x())
                    bg_y = int(bbox.y() - rect_height)

                    p.fillRect(
                        bg_x,
                        bg_y,
                        rect_width,
                        rect_height,
                        QtGui.QColor(background_color),
                    )

            pen = QtGui.QPen(
                QtGui.QColor(text_color), 8, Qt.PenStyle.SolidLine
            )
            p.setPen(pen)
            for shape in self.shapes:
                if not shape.visible or getattr(
                    shape, "hidden_by_filter", False
                ):
                    continue
                if should_merge_rectangle_text(shape):
                    continue
                description = shape.description
                if description:
                    bbox = shape.bounding_rect()
                    fm = QtGui.QFontMetrics(p.font())

                    padding_x = 4
                    padding_y = 2

                    text_x = int(bbox.x() + padding_x)
                    text_y = int(bbox.y() - padding_y - fm.descent())

                    p.drawText(
                        text_x,
                        text_y,
                        description,
                    )

        # Compute hover context once for the unified label gate.
        hovered_shape = self.h_hape
        mp = self.prev_move_point
        if hovered_shape is None:
            for s in self.shapes:
                if (
                    s.shape_type == "point"
                    and s.points
                    and self.is_shape_interactive(s)
                ):
                    if (
                        math.hypot(
                            mp.x() - s.points[0].x(),
                            mp.y() - s.points[0].y(),
                        )
                        * self.scale
                        <= 10
                    ):
                        hovered_shape = s
                        break

        # Draw labels
        if self.show_labels:
            p.setFont(
                QtGui.QFont(
                    "Arial", int(max(6.0, int(round(8.0 / Shape.scale))))
                )
            )
            labels = []
            for shape in self.shapes:
                if not self._should_draw_standard_label(shape):
                    continue
                d_react = shape.point_size / shape.scale
                if not shape.visible or getattr(
                    shape, "hidden_by_filter", False
                ):
                    continue
                if shape.label in [
                    "AUTOLABEL_OBJECT",
                    "AUTOLABEL_ADD",
                    "AUTOLABEL_REMOVE",
                ]:
                    continue
                display_mode = self.label_display_mode
                if display_mode == "none":
                    continue
                elif display_mode == "label":
                    label_text = shape.label
                elif display_mode == "id":
                    label_text = (
                        str(shape.group_id)
                        if shape.group_id is not None
                        else ""
                    )
                elif display_mode == "both":
                    if shape.group_id is not None:
                        label_text = f"{shape.label} #{shape.group_id}"
                    else:
                        label_text = shape.label
                else:
                    label_text = shape.label
                if not label_text:
                    continue
                if shape.score is not None and self.show_scores:
                    label_text += f" {float(shape.score):.2f}"
                if shape.shape_type == "rectangle":
                    extra_texts = []
                    if self.show_texts and shape.description:
                        extra_texts.append(str(shape.description))
                    if self.show_attributes and getattr(
                        shape, "attributes", None
                    ):
                        extra_texts.extend(
                            f"{key}: {value}"
                            for key, value in shape.attributes.items()
                        )
                    if extra_texts:
                        label_text = " | ".join([label_text] + extra_texts)
                if not label_text:
                    continue
                fm = QtGui.QFontMetrics(p.font())
                text_rect = fm.tightBoundingRect(label_text)
                padding_x = 4
                padding_y = 2
                rect_width = text_rect.width() + 2 * padding_x
                rect_height = fm.height() + 2 * padding_y

                if shape.shape_type == "rectangle":
                    try:
                        bbox = shape.bounding_rect()
                    except IndexError:
                        continue

                    rect_x = int(bbox.x())
                    max_x = self.pixmap.width() - rect_width
                    if max_x >= 0:
                        rect_x = min(max(rect_x, 0), max_x)
                    else:
                        rect_x = 0

                    rect_y = int(bbox.y() - rect_height - 1)
                    if rect_y < 0:
                        rect_y = int(bbox.y())
                    max_y = self.pixmap.height() - rect_height
                    if max_y >= 0:
                        rect_y = min(max(rect_y, 0), max_y)
                    else:
                        rect_y = 0

                    rect = QtCore.QRect(
                        rect_x,
                        rect_y,
                        rect_width,
                        rect_height,
                    )
                    text_pos = QtCore.QPoint(
                        rect_x + padding_x,
                        rect_y + rect_height - padding_y - fm.descent(),
                    )
                elif shape.shape_type in [
                    "polygon",
                    "rotation",
                    "quadrilateral",
                    "cuboid",
                ]:
                    try:
                        bbox = shape.bounding_rect()
                    except IndexError:
                        continue
                    rect = QtCore.QRect(
                        int(bbox.x()),
                        int(bbox.y()),
                        rect_width,
                        rect_height,
                    )
                    text_pos = QtCore.QPoint(
                        int(bbox.x() + padding_x),
                        int(bbox.y() + rect_height - padding_y - fm.descent()),
                    )
                elif shape.shape_type == "circle":
                    points = shape.points
                    if not points:
                        continue
                    point = points[0]
                    rect = QtCore.QRect(
                        int(point.x() - rect_width / 2),
                        int(point.y() - rect_height / 2),
                        rect_width,
                        rect_height,
                    )
                    text_pos = QtCore.QPoint(
                        int(point.x() - rect_width / 2 + padding_x),
                        int(
                            point.y()
                            + rect_height / 2
                            - padding_y
                            - fm.descent()
                        ),
                    )
                elif shape.shape_type in [
                    "line",
                    "linestrip",
                    "point",
                ]:
                    points = shape.points
                    if not points:
                        continue
                    point = points[0]
                    rect = QtCore.QRect(
                        int(point.x() + d_react),
                        int(point.y() - 15),
                        rect_width,
                        rect_height,
                    )
                    text_pos = QtCore.QPoint(
                        int(point.x() + d_react + padding_x),
                        int(
                            point.y()
                            - 15
                            + rect_height
                            - padding_y
                            - fm.descent()
                        ),
                    )
                else:
                    continue

                # --- Unified label visibility gate ---
                # label_on_selection ON  = sparse: show only the label of
                #   the hovered/selected shape itself (NOT its whole group).
                # label_on_selection OFF = show all labels.
                if self.label_on_selection:
                    is_hovered = shape == hovered_shape
                    show = shape.selected or is_hovered
                    if not show:
                        continue

                labels.append((shape, rect, text_pos, label_text))

            p.setPen(Qt.PenStyle.NoPen)
            for shape, rect, _, _ in labels:
                if not shape.visible or getattr(
                    shape, "hidden_by_filter", False
                ):
                    continue
                bg_color = QtGui.QColor(shape.line_color)
                bg_color.setAlphaF(0.85)
                p.setBrush(bg_color)
                p.drawRoundedRect(rect, 3, 3)

            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QtGui.QColor("#ffffff"))
            for shape, _, text_pos, label_text in labels:
                if not shape.visible or getattr(
                    shape, "hidden_by_filter", False
                ):
                    continue
                p.drawText(text_pos, label_text)

        # Pose View overlay (after standard labels).
        # Only render when pose view is on AND a filter is active (the
        # "filtered pose display" — shows skeleton/keypoints/labels for
        # the visible group). Without a filter, native display is used.
        if (
            self.pose_config.enabled
            and getattr(self, "pose_filter_active", False)
            and self.pixmap is not None
            and self._has_pose_shapes()
        ):
            count = self._pose_renderer.render(
                p,
                self.shapes,
                self.pixmap.size(),
                self.scale,
                show_labels=True,
                label_on_selection=False,
                hovered_group_id=None,
                zoom_reveals=False,
                label_display_mode=self.label_display_mode,
            )
            if count != self.pose_config.occlusion_count:
                self.pose_config.occlusion_count = count
                self.pose_occlusion_count_changed.emit(count)

        # Rectangle edge editing overlay. Drawn after the main
        # shape pass so the status colour covers the underlying rectangle
        # edge. Shape.scale is already set and the painter is in pixmap
        # space, matching the convention used by the cross-line below.
        if self.rect_edge_align_enabled or self.rect_edge_keyboard_edge:
            self._draw_rect_edge_alignment_overlay(p)

        # Stable refine preview overlay (phase 2: target + drag-locked).
        # Drawn as an independent top-most layer in widget (screen)
        # coordinates — it must NOT inherit the painter's pixmap-space
        # scale/translate, so the window stays pinned to the bottom-right
        # regardless of the main canvas zoom/pan. The mode selects the
        # crop rect inside the draw call.
        if (
            self.stable_preview_enabled
            and self.stable_preview_mode != "none"
            and self.pixmap is not None
            and not self.pixmap.isNull()
        ):
            self._draw_stable_preview_overlay(p)

        # Draw mouse coordinates
        if self.cross_line_show:
            pen = QtGui.QPen(
                QtGui.QColor(self.cross_line_color),
                max(1, int(round(self.cross_line_width / Shape.scale))),
                Qt.PenStyle.DashLine,
            )
            p.setPen(pen)
            p.setOpacity(self.cross_line_opacity)
            p.drawLine(
                QtCore.QPointF(self.prev_move_point.x(), 0),
                QtCore.QPointF(self.prev_move_point.x(), self.pixmap.height()),
            )
            p.drawLine(
                QtCore.QPointF(0, self.prev_move_point.y()),
                QtCore.QPointF(self.pixmap.width(), self.prev_move_point.y()),
            )

        # Draw attributes
        if self.show_attributes:
            font_size = int(max(8.0, int(round(10.0 / Shape.scale))))
            font = QtGui.QFont("Arial", font_size, QtGui.QFont.Weight.Bold)
            p.setFont(font)
            attributes_list = []

            for shape in self.shapes:
                if not shape.visible or getattr(
                    shape, "hidden_by_filter", False
                ):
                    continue
                if should_merge_rectangle_text(shape):
                    continue
                if not hasattr(shape, "attributes") or not shape.attributes:
                    continue
                if shape.label in [
                    "AUTOLABEL_OBJECT",
                    "AUTOLABEL_ADD",
                    "AUTOLABEL_REMOVE",
                ]:
                    continue

                attrs_text = []
                for key, value in shape.attributes.items():
                    attrs_text.append(f"{key}: {value}")
                if not attrs_text:
                    continue

                max_attrs_per_line = 1
                attribute_lines = []
                for i in range(0, len(attrs_text), max_attrs_per_line):
                    line_attrs = attrs_text[i : i + max_attrs_per_line]
                    attribute_lines.append(" | ".join(line_attrs))

                fm = QtGui.QFontMetrics(font)
                max_width = 0
                line_heights = []
                for line in attribute_lines:
                    line_rect = fm.tightBoundingRect(line)
                    max_width = max(max_width, line_rect.width())
                    line_heights.append(fm.height())
                total_height = sum(line_heights)

                padding_x = 8
                padding_y = 2
                rect_width = max_width + 2 * padding_x
                rect_height = total_height + 2 * padding_y
                d_react = shape.point_size / shape.scale

                if shape.shape_type in [
                    "rectangle",
                    "polygon",
                    "rotation",
                    "quadrilateral",
                    "cuboid",
                ]:
                    try:
                        bbox = shape.bounding_rect()
                    except IndexError:
                        continue

                    rect = QtCore.QRect(
                        int(bbox.x()),
                        int(bbox.y() + bbox.height() + 1),
                        rect_width,
                        rect_height,
                    )

                    text_positions = []
                    y_offset = 0
                    for i, line_height in enumerate(line_heights):
                        text_pos = QtCore.QPoint(
                            int(bbox.x() + padding_x),
                            int(
                                bbox.y()
                                + bbox.height()
                                + 1
                                + padding_y
                                + y_offset
                                + fm.ascent()
                            ),
                        )
                        text_positions.append(text_pos)
                        y_offset += line_height

                elif shape.shape_type in [
                    "circle",
                    "line",
                    "linestrip",
                    "point",
                ]:
                    points = shape.points
                    if not points:
                        continue
                    point = points[0]

                    rect = QtCore.QRect(
                        int(point.x() + d_react),
                        int(point.y() + 1),
                        rect_width,
                        rect_height,
                    )

                    text_positions = []
                    y_offset = 0
                    for i, line_height in enumerate(line_heights):
                        text_pos = QtCore.QPoint(
                            int(point.x() + d_react + padding_x),
                            int(
                                point.y()
                                + 1
                                + padding_y
                                + y_offset
                                + fm.ascent()
                            ),
                        )
                        text_positions.append(text_pos)
                        y_offset += line_height
                else:
                    continue

                attributes_list.append(
                    (shape, rect, text_positions, attribute_lines)
                )

            for shape, rect, _, _ in attributes_list:
                if not shape.visible or getattr(
                    shape, "hidden_by_filter", False
                ):
                    continue

                background_color = QtGui.QColor(*self.attr_background_color)
                p.fillRect(rect, background_color)

                pen = QtGui.QPen(
                    QtGui.QColor(*self.attr_border_color),
                    1,
                    Qt.PenStyle.SolidLine,
                )
                p.setPen(pen)
                p.drawRect(rect)

            pen = QtGui.QPen(
                QtGui.QColor(*self.attr_text_color), 1, Qt.PenStyle.SolidLine
            )
            p.setPen(pen)
            p.setFont(font)

            for _, _, text_positions, attribute_lines in attributes_list:
                for i, (text_pos, line_text) in enumerate(
                    zip(text_positions, attribute_lines)
                ):
                    p.drawText(text_pos, line_text)

        # Draw compare view split line
        if (
            self.compare_pixmap is not None
            and not self.compare_pixmap.isNull()
        ):
            split_x = int(self.split_position * self.pixmap.width())
            img_h = self.pixmap.height()
            if 0 < split_x < self.pixmap.width():
                p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
                line_pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 180), 1.5)
                line_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(line_pen)
                p.drawLine(split_x, 0, split_x, img_h)
                handle_radius = 16
                handle_y = img_h // 2
                gradient = QtGui.QRadialGradient(
                    split_x, handle_y, handle_radius
                )
                gradient.setColorAt(0, QtGui.QColor(255, 255, 255, 200))
                gradient.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(gradient)
                p.drawEllipse(
                    split_x - handle_radius,
                    handle_y - handle_radius,
                    handle_radius * 2,
                    handle_radius * 2,
                )
                p.setBrush(QtGui.QColor(255, 255, 255, 200))
                p.drawEllipse(split_x - 8, handle_y - 8, 16, 16)
                arrow_pen = QtGui.QPen(QtGui.QColor(100, 100, 100, 180), 1.5)
                arrow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                arrow_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                p.setPen(arrow_pen)
                arrow_size = 4
                p.drawLine(
                    split_x - arrow_size, handle_y, split_x - 1, handle_y
                )
                p.drawLine(
                    split_x - arrow_size,
                    handle_y,
                    split_x - arrow_size + 2,
                    handle_y - 2,
                )
                p.drawLine(
                    split_x - arrow_size,
                    handle_y,
                    split_x - arrow_size + 2,
                    handle_y + 2,
                )
                p.drawLine(
                    split_x + 1, handle_y, split_x + arrow_size, handle_y
                )
                p.drawLine(
                    split_x + arrow_size,
                    handle_y,
                    split_x + arrow_size - 2,
                    handle_y - 2,
                )
                p.drawLine(
                    split_x + arrow_size,
                    handle_y,
                    split_x + arrow_size - 2,
                    handle_y + 2,
                )
                p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)

        p.end()
        _dt = time.perf_counter() - _t0
        if _dt > 0.05:
            _perf_log(
                "Canvas.paintEvent slow: %.3fs, shapes=%d",
                _dt,
                len(self.shapes),
            )

    def render_visualization(
        self,
        pixmap,
        shapes,
        show_labels=True,
        show_scores=True,
        show_groups=False,
        show_texts=True,
        show_masks=True,
    ):
        old_shape_scale = Shape.scale
        scratch = type(self)(parent=self.parent)
        scratch.resize(pixmap.size())
        scratch.pixmap = pixmap
        scratch.shapes = list(shapes)
        scratch.scale = 1.0
        scratch.current = None
        scratch.selected_shapes = []
        scratch.selected_shapes_copy = []
        scratch.h_hape = None
        scratch.h_vertex = None
        scratch.h_edge = None
        scratch.h_cuboid_face = None
        scratch.compare_pixmap = None
        scratch.cross_line_show = False
        scratch.show_labels = show_labels
        scratch.label_display_mode = self.label_display_mode
        scratch.show_scores = show_scores
        scratch.show_groups = show_groups
        scratch.show_texts = show_texts
        scratch.show_masks = show_masks
        scratch.show_degrees = self.show_degrees
        scratch.show_attributes = self.show_attributes
        scratch.show_linking = self.show_linking
        scratch.mask_opacity = self.mask_opacity
        scratch.attr_background_color = self.attr_background_color
        scratch.attr_border_color = self.attr_border_color
        scratch.attr_text_color = self.attr_text_color
        scratch.visible = {shape: shape.visible for shape in scratch.shapes}

        image = QtGui.QImage(pixmap.size(), QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtCore.Qt.GlobalColor.transparent)

        painter = QtGui.QPainter(image)
        try:
            scratch.render(painter)
        finally:
            painter.end()
            Shape.scale = old_shape_scale
            scratch.deleteLater()

        return image

    def transform_pos(self, point):
        """Convert from widget-logical coordinates to painter-logical ones."""
        return point / self.scale - self.offset_to_center()

    # ------------------------------------------------------------------
    # Precision drag mode (Feature 3, task 5.1-5.6)
    # ------------------------------------------------------------------
    @property
    def precision_factor(self):
        """Slowdown factor for precision drag (from config, default 4)."""
        mode = getattr(self, "_precision_mode_cfg", "fixed")
        if mode == "zoom":
            scale_factor = max(
                1.0, float(getattr(self, "scale", 1.0) or 1.0)
            )
            max_factor = max(
                1.0, float(getattr(self, "_precision_max_factor_cfg", 2.0))
            )
            return min(scale_factor, max_factor)
        cfg = getattr(self, "_precision_factor_cfg", None)
        if cfg is None:
            # Lazy-read once; canvas has no direct config handle, so the
            # label_widget pushes the value via set_precision_factor.
            return 4
        return cfg

    def set_precision_mode(self, value):
        """Set precision slowdown mode: fixed or zoom."""
        self._precision_mode_cfg = (
            value if value in ("fixed", "zoom") else "fixed"
        )

    def set_precision_max_factor(self, value):
        """Set the max slowdown factor for zoom precision mode."""
        self._precision_max_factor_cfg = max(1.0, float(value))

    def set_precision_factor(self, value):
        """Allow label_widget to push the config value at zoom changes."""
        self._precision_factor_cfg = max(1, int(value))

    def _precision_active(self, ev=None):
        """Return True if precision drag is active (D6: Ctrl held or locked)."""
        if self.precision_mode_locked:
            return True
        if ev is not None:
            return bool(
                ev.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier
            )
        return False

    def _reset_virtual_cursor(self):
        """Reset the virtual cursor (call on mouse press / mode exit)."""
        self._virtual_prev_point = None
        self._precision_raw_prev_point = None

    def _effective_drag_pos(self, pos, ev):
        """Return the image-coord pos to feed drag handlers.

        In precision mode, scales the delta by 1/precision_factor using
        a virtual cursor that is KEPT SEPARATE from self.prev_point (D4).
        Hit-test, epsilon, and transform_pos are unaffected: they still
        use the raw ``pos``.
        """
        if not self._precision_active(ev):
            self._reset_virtual_cursor()
            return pos
        if self._virtual_prev_point is None:
            self._virtual_prev_point = QtCore.QPointF(self.prev_point)
            self._precision_raw_prev_point = QtCore.QPointF(self.prev_point)
        factor = self.precision_factor
        delta = pos - self._precision_raw_prev_point
        scaled = QtCore.QPointF(delta.x() / factor, delta.y() / factor)
        eff = self._virtual_prev_point + scaled
        self._virtual_prev_point = eff
        self._precision_raw_prev_point = QtCore.QPointF(pos)
        return eff

    def offset_to_center(self):
        """Calculate offset to the center"""
        if self.pixmap is None:
            return QtCore.QPointF()
        s = self.scale
        area = super().size()
        w, h = self.pixmap.width() * s, self.pixmap.height() * s
        area_width, area_height = area.width(), area.height()
        x = (area_width - w) / (2 * s) if area_width > w else 0
        y = (area_height - h) / (2 * s) if area_height > h else 0
        return QtCore.QPointF(x, y)

    def out_off_pixmap(self, p):
        """Check if a position is out of pixmap"""
        if self.pixmap is None:
            return True
        w, h = self.pixmap.width(), self.pixmap.height()
        return not (0 <= p.x() <= w - 1 and 0 <= p.y() <= h - 1)

    def finalise(self):
        """Finish drawing for a shape"""
        assert self.current
        self._brush_drawing = False
        if (
            self.is_auto_labeling
            and self.auto_labeling_mode != AutoLabelingMode.NONE
        ):
            self.current.label = self.auto_labeling_mode.edit_mode
        if self.current.label is None:
            self.current.label = ""
        self.current.close()
        if self.current.shape_type == "rectangle":
            if not self.clip_rectangle_to_pixmap(self.current):
                self.current = None
                self.set_hiding(False)
                self.drawing_polygon.emit(False)
                self.update()
                return
        elif self.current.shape_type == "rotation":
            if not self.clip_rotation_to_pixmap(self.current):
                self.current = None
                self.set_hiding(False)
                self.drawing_polygon.emit(False)
                self.update()
                return
        elif self.current.shape_type == "cuboid":
            self.current.sync_cuboid_depth_vector()

        self.shapes.append(self.current)
        self.store_shapes()
        self.current = None
        self.set_hiding(False)
        self.new_shape.emit()
        self.update()
        if self.is_auto_labeling:
            self.update_auto_labeling_marks()

    def update_auto_labeling_marks(self):
        """Update the auto labeling marks"""
        marks = []
        for shape in self.shapes:
            if shape.label == AutoLabelingMode.ADD:
                if shape.shape_type == AutoLabelingMode.POINT:
                    marks.append(
                        {
                            "type": "point",
                            "data": [
                                int(shape.points[0].x()),
                                int(shape.points[0].y()),
                            ],
                            "label": 1,
                        }
                    )
                elif shape.shape_type == AutoLabelingMode.RECTANGLE:
                    marks.append(
                        {
                            "type": "rectangle",
                            "data": [
                                int(shape.points[0].x()),
                                int(shape.points[0].y()),
                                int(shape.points[2].x()),
                                int(shape.points[2].y()),
                            ],
                            "label": 1,
                        }
                    )
            elif shape.label == AutoLabelingMode.REMOVE:
                if shape.shape_type == AutoLabelingMode.POINT:
                    marks.append(
                        {
                            "type": "point",
                            "data": [
                                int(shape.points[0].x()),
                                int(shape.points[0].y()),
                            ],
                            "label": 0,
                        }
                    )
                elif shape.shape_type == AutoLabelingMode.RECTANGLE:
                    marks.append(
                        {
                            "type": "rectangle",
                            "data": [
                                int(shape.points[0].x()),
                                int(shape.points[0].y()),
                                int(shape.points[2].x()),
                                int(shape.points[2].y()),
                            ],
                            "label": 0,
                        }
                    )

        self.auto_labeling_marks_updated.emit(marks)

    def close_enough(self, p1, p2):
        """Check if 2 points are close enough (by an threshold epsilon)"""
        # d = distance(p1 - p2)
        # m = (p1-p2).manhattanLength()
        # print "d %.2f, m %d, %.2f" % (d, m, d - m)
        # divide by scale to allow more precision when zoomed in
        return utils.distance(p1 - p2) < (self.epsilon / self.scale)

    def intersection_point(self, p1, p2):
        """Cycle through each image edge in clockwise fashion,
        and find the one intersecting the current line segment.
        """
        size = self.pixmap.size()
        points = [
            (0, 0),
            (size.width() - 1, 0),
            (size.width() - 1, size.height() - 1),
            (0, size.height() - 1),
        ]
        # x1, y1 should be in the pixmap, x2, y2 should be out of the pixmap
        x1 = min(max(p1.x(), 0), size.width() - 1)
        y1 = min(max(p1.y(), 0), size.height() - 1)
        x2, y2 = p2.x(), p2.y()
        _, i, (x, y) = min(self.intersecting_edges((x1, y1), (x2, y2), points))
        x3, y3 = points[i]
        x4, y4 = points[(i + 1) % 4]
        x1, y1 = int(x1), int(y1)
        x2, y2 = int(x2), int(y2)
        x3, y3 = int(x3), int(y3)
        x4, y4 = int(x4), int(y4)
        if (x, y) == (x1, y1):
            # Handle cases where previous point is on one of the edges.
            if x3 == x4:
                return QtCore.QPointF(x3, min(max(0, y2), max(y3, y4)))
            # y3 == y4
            return QtCore.QPointF(min(max(0, x2), max(x3, x4)), y3)
        return QtCore.QPointF(int(x), int(y))

    def intersecting_edges(self, point1, point2, points):
        """Find intersecting edges.

        For each edge formed by `points', yield the intersection
        with the line segment `(x1,y1) - (x2,y2)`, if it exists.
        Also return the distance of `(x2,y2)' to the middle of the
        edge along with its index, so that the one closest can be chosen.
        """
        x1, y1 = point1
        x2, y2 = point2
        for i in range(4):
            x3, y3 = points[i]
            x4, y4 = points[(i + 1) % 4]
            denom = (y4 - y3) * (x2 - x1) - (x4 - x3) * (y2 - y1)
            nua = (x4 - x3) * (y1 - y3) - (y4 - y3) * (x1 - x3)
            nub = (x2 - x1) * (y1 - y3) - (y2 - y1) * (x1 - x3)
            if denom == 0:
                # This covers two cases:
                #   nua == nub == 0: Coincident
                #   otherwise: Parallel
                continue
            ua, ub = nua / denom, nub / denom
            if 0 <= ua <= 1 and 0 <= ub <= 1:
                x = x1 + ua * (x2 - x1)
                y = y1 + ua * (y2 - y1)
                m = QtCore.QPointF((x3 + x4) / 2, (y3 + y4) / 2)
                d = utils.distance(m - QtCore.QPointF(x2, y2))
                yield d, i, (x, y)

    # These two, along with a call to adjustSize are required for the
    # scroll area.
    # QT Overload
    def sizeHint(self):
        """Get size hint"""
        return self.minimumSizeHint()

    # QT Overload
    def minimumSizeHint(self):
        """Get minimum size hint"""
        if self.pixmap:
            return self.scale * self.pixmap.size()
        return super().minimumSizeHint()

    # QT Overload
    def wheelEvent(self, ev: QWheelEvent):
        """Mouse wheel event"""
        mods = ev.modifiers()
        delta = ev.angleDelta()

        if (
            self.editing()
            and self.enable_wheel_rectangle_editing
            and not self.auto_highlight_shape
            and len(self.selected_shapes) == 1
            and self.selected_shapes[0].shape_type == "rectangle"
            and not (mods & QtCore.Qt.KeyboardModifier.ControlModifier)
        ):
            try:
                pos = self.transform_pos(ev.position())
            except AttributeError:
                pos = self.transform_pos(ev.position())

            shape = self.selected_shapes[0]
            wheel_up = delta.y() > 0

            if shape.contains_point(pos):
                self._scale_rectangle(shape, wheel_up)
            else:
                self._adjust_rectangle_edge(shape, pos, wheel_up)

            self.store_shapes()
            self.shape_moved.emit()
            self.update()
            ev.accept()
            return

        # Shift+wheel: adjust compare view split position
        if (
            mods == QtCore.Qt.KeyboardModifier.ShiftModifier
            and self.compare_pixmap is not None
            and not self.compare_pixmap.isNull()
        ):
            step = 0.02 if delta.y() > 0 else -0.02
            self.split_position = max(
                0.0, min(1.0, self.split_position + step)
            )
            self.split_position_changed.emit(self.split_position)
            self.update()
            ev.accept()
            return

        if mods & QtCore.Qt.KeyboardModifier.ControlModifier:
            # with Ctrl/Command key
            # zoom
            self.zoom_request.emit(delta.y(), ev.position().toPoint())
        else:
            # scroll
            self.scroll_request.emit(
                delta.x(), QtCore.Qt.Orientation.Horizontal, 0
            )
            self.scroll_request.emit(
                delta.y(), QtCore.Qt.Orientation.Vertical, 0
            )
        ev.accept()

    def _scale_rectangle(self, shape, scale_up):
        """Scale rectangle from center while keeping within image boundaries"""
        if len(shape.points) < 4:
            return

        if self.pixmap is None:
            return
        img_width = self.pixmap.width()
        img_height = self.pixmap.height()

        x_coords = [p.x() for p in shape.points]
        y_coords = [p.y() for p in shape.points]
        center_x = sum(x_coords) / 4
        center_y = sum(y_coords) / 4
        center = QtCore.QPointF(center_x, center_y)

        scale_factor = (
            1.0 + self.rect_scale_step
            if scale_up
            else 1.0 - self.rect_scale_step
        )
        scale_factor = max(0.1, scale_factor)

        new_points = []
        for i in range(len(shape.points)):
            point = shape.points[i]
            offset = point - center
            scaled_offset = offset * scale_factor
            new_point = center + scaled_offset

            if (
                new_point.x() < 0
                or new_point.x() >= img_width
                or new_point.y() < 0
                or new_point.y() >= img_height
            ):
                return

            new_points.append(new_point)

        for i, new_point in enumerate(new_points):
            shape.points[i] = new_point

    def _adjust_rectangle_edge(self, shape, cursor_pos, move_outward):
        """Adjust the rectangle edge closest to cursor position within image boundaries"""
        if len(shape.points) < 4:
            return

        rect = shape.bounding_rect()
        min_x, max_x = rect.left(), rect.right()
        min_y, max_y = rect.top(), rect.bottom()

        distances = {}

        if cursor_pos.x() < min_x:
            distances["left"] = min_x - cursor_pos.x()
        elif cursor_pos.x() > max_x:
            distances["right"] = cursor_pos.x() - max_x
        else:
            distances["left"] = abs(cursor_pos.x() - min_x)
            distances["right"] = abs(cursor_pos.x() - max_x)

        if cursor_pos.y() < min_y:
            distances["top"] = min_y - cursor_pos.y()
        elif cursor_pos.y() > max_y:
            distances["bottom"] = cursor_pos.y() - max_y
        else:
            distances["top"] = abs(cursor_pos.y() - min_y)
            distances["bottom"] = abs(cursor_pos.y() - max_y)

        if (
            cursor_pos.x() < min_x
            and cursor_pos.y() >= min_y
            and cursor_pos.y() <= max_y
        ):
            closest_edge = "left"
        elif (
            cursor_pos.x() > max_x
            and cursor_pos.y() >= min_y
            and cursor_pos.y() <= max_y
        ):
            closest_edge = "right"
        elif (
            cursor_pos.y() < min_y
            and cursor_pos.x() >= min_x
            and cursor_pos.x() <= max_x
        ):
            closest_edge = "top"
        elif (
            cursor_pos.y() > max_y
            and cursor_pos.x() >= min_x
            and cursor_pos.x() <= max_x
        ):
            closest_edge = "bottom"
        else:
            closest_edge = min(distances, key=distances.get)

        step = (
            self.rect_adjust_step if move_outward else -self.rect_adjust_step
        )

        if self.pixmap is None:
            return
        img_width = self.pixmap.width()
        img_height = self.pixmap.height()

        for i, point in enumerate(shape.points):
            new_point = None

            if closest_edge == "left" and abs(point.x() - min_x) < 1e-6:
                new_x = max(0, point.x() - step)
                new_point = QtCore.QPointF(new_x, point.y())
            elif closest_edge == "right" and abs(point.x() - max_x) < 1e-6:
                new_x = min(img_width - 1, point.x() + step)
                new_point = QtCore.QPointF(new_x, point.y())
            elif closest_edge == "top" and abs(point.y() - min_y) < 1e-6:
                new_y = max(0, point.y() - step)
                new_point = QtCore.QPointF(point.x(), new_y)
            elif closest_edge == "bottom" and abs(point.y() - max_y) < 1e-6:
                new_y = min(img_height - 1, point.y() + step)
                new_point = QtCore.QPointF(point.x(), new_y)

            if new_point is not None:
                shape.points[i] = new_point

    # ------------------------------------------------------------------
    # Rectangle edge editing mode.
    # See docs/矩形边对齐功能实现任务文档.md and rect_edge_alignment.py.
    # All logic here is guarded by ``self.rect_edge_align_enabled`` so the
    # default editing experience is unchanged when the mode is off.
    # ------------------------------------------------------------------

    def set_rect_edge_align_enabled(self, enabled):
        """Enable or disable the rectangle edge editing mode.

        When disabling, an active drag is cancelled and all transient edge
        state is cleared. Enabling does not pick any edge or create a shape.

        Args:
            enabled: Whether the mode should be active.
        """
        enabled = bool(enabled)
        if not enabled and self.rect_edge_dragging:
            self.cancel_rect_edge_drag()
        self.rect_edge_align_enabled = enabled
        if not self.rect_edge_align_enabled:
            self.clear_rect_edge_alignment()
            # Turning rect-edge editing off is a full teardown: wipe the
            # stable preview entirely (drag-locked + target).
            self._stable_preview_clear_all()
        self.update()

    def _rect_edge_drag_update(self, pos):
        """Live-update the target edge during a rect-edge drag.

        The selected edge actively follows the cursor on its own axis:
        left/right edges use the cursor x coordinate, while top/bottom edges
        use the cursor y coordinate. The geometry helper clamps the result so
        the rectangle cannot flip or collapse below the minimum size.

        Args:
            pos: Current cursor position in image coordinates.
        """
        active = self.rect_edge_active_edge
        if active is None:
            return

        if active.axis == rea.RECT_EDGE_AXIS_X:
            coord = pos.x()
        else:
            coord = pos.y()

        # Live edit: mutate the target shape in place. The drag start
        # points are preserved so Esc can restore them.
        rea.apply_edge_coord(active.shape, active.edge_name, coord)
        # Refresh the active edge from the just-mutated geometry so the
        # overlay follows the live position instead of the original edge.
        updated_geom = rea.geometry_from_shape(active.shape)
        if updated_geom is not None:
            self.rect_edge_active_edge = rea.edge_from_geometry(
                active.shape, updated_geom, active.edge_name
            )
        self.update()

    # ------------------------------------------------------------------
    # Stable refine preview (phase 1: DragLocked only).
    # ------------------------------------------------------------------

    def set_stable_preview_enabled(self, enabled: bool) -> None:
        """Toggle the stable refine preview master switch.

        Enabling immediately syncs with the current selection so an
        already-selected rectangle enters TargetPreview without requiring
        a second click. Disabling clears every preview state so no stale
        overlay survives the toggle.
        """
        self.stable_preview_enabled = enabled
        if enabled:
            self._stable_preview_enter_target_if_valid()
        else:
            self._stable_preview_clear_all()
        self.update()

    def _stable_preview_current_window_rect(self) -> QtCore.QRectF:
        """Return the preview window rect in widget coordinates."""
        if self.stable_preview_window_rect is None:
            size = self.stable_preview_size
            margin = self.stable_preview_margin
            rect = QtCore.QRectF(
                float(self.width() - margin - size.width()),
                float(self.height() - margin - size.height()),
                float(size.width()),
                float(size.height()),
            )
            self.stable_preview_window_rect = (
                self._stable_preview_clamp_window_rect(rect)
            )
        else:
            self.stable_preview_window_rect = (
                self._stable_preview_clamp_window_rect(
                    self.stable_preview_window_rect
                )
            )
        return QtCore.QRectF(self.stable_preview_window_rect)

    def _stable_preview_clamp_window_rect(
        self, rect: QtCore.QRectF
    ) -> QtCore.QRectF:
        """Clamp preview window geometry to the canvas."""
        min_w = float(self.stable_preview_min_size.width())
        min_h = float(self.stable_preview_min_size.height())
        canvas_w = max(1.0, float(self.width()))
        canvas_h = max(1.0, float(self.height()))
        max_w = max(min_w, canvas_w)
        max_h = max(min_h, canvas_h)
        width = min(max(rect.width(), min_w), max_w)
        height = min(max(rect.height(), min_h), max_h)
        left = min(max(rect.left(), 0.0), max(0.0, canvas_w - width))
        top = min(max(rect.top(), 0.0), max(0.0, canvas_h - height))
        return QtCore.QRectF(left, top, width, height)

    def _stable_preview_source_size(self, shape=None):
        """Return source image size for the current window at fixed scale."""
        window = self._stable_preview_current_window_rect()
        source_w = window.width() / self.stable_preview_scale
        source_h = window.height() / self.stable_preview_scale
        aspect = window.width() / max(1.0, window.height())
        if shape is None:
            return source_w, source_h
        geom = rea.geometry_from_shape(shape)
        if geom is None:
            return source_w, source_h
        pad = self.stable_preview_target_padding_ratio
        padded_w = geom.width * (1.0 + 2.0 * pad)
        padded_h = geom.height * (1.0 + 2.0 * pad)
        source_w = max(source_w, padded_w)
        source_h = max(source_h, padded_h)
        if source_w / max(1.0, source_h) > aspect:
            source_h = source_w / aspect
        else:
            source_w = source_h * aspect
        return source_w, source_h

    def _stable_preview_resize_source_to_window(
        self, source: QtCore.QRectF, shape=None
    ) -> QtCore.QRectF:
        """Resize a source rect for the window while keeping content stable."""
        source_w, source_h = self._stable_preview_source_size(shape)
        center = source.center()
        rect = QtCore.QRectF(
            center.x() - source_w / 2.0,
            center.y() - source_h / 2.0,
            source_w,
            source_h,
        )
        rect = self._clamp_rectf_to_image(rect)
        geom = rea.geometry_from_shape(shape) if shape is not None else None
        if geom is None:
            return rect
        target = QtCore.QRectF(
            geom.x_min,
            geom.y_min,
            geom.width,
            geom.height,
        )
        if rect.contains(target):
            return rect
        return self._stable_preview_compute_target_rect(shape)

    def _stable_preview_sync_source_to_window(self) -> None:
        """Sync the active image source rect to the current window size."""
        shape = self.stable_preview_shape
        if self.stable_preview_mode == "target":
            source = self.stable_preview_target_rect
            if source is not None:
                self.stable_preview_target_rect = (
                    self._stable_preview_resize_source_to_window(source, shape)
                )
        elif self.stable_preview_mode == "drag_locked":
            source = self.stable_preview_locked_rect
            if source is not None:
                self.stable_preview_locked_rect = (
                    self._stable_preview_resize_source_to_window(source)
                )

    def _stable_preview_visible(self) -> bool:
        """Return whether the preview overlay is currently visible."""
        return (
            self.stable_preview_enabled
            and self.stable_preview_mode != "none"
            and self.pixmap is not None
            and not self.pixmap.isNull()
        )

    def _stable_preview_window_hit_test(self, pos) -> str:
        """Hit-test the preview window in widget coordinates."""
        if not self._stable_preview_visible():
            return "none"
        rect = self._stable_preview_current_window_rect()
        if not rect.contains(pos):
            return "none"
        handle = float(self.stable_preview_resize_handle_px)
        resize_rect = QtCore.QRectF(
            rect.right() - handle,
            rect.bottom() - handle,
            handle,
            handle,
        )
        if resize_rect.contains(pos):
            return "resize"
        return "move"

    def _stable_preview_begin_window_interaction(self, pos) -> bool:
        """Start moving or resizing the preview window if it was hit."""
        hit = self._stable_preview_window_hit_test(pos)
        if hit == "none":
            return False
        self.stable_preview_window_press_pos = QtCore.QPointF(pos)
        self.stable_preview_window_press_rect = (
            self._stable_preview_current_window_rect()
        )
        self.stable_preview_window_dragging = hit == "move"
        self.stable_preview_window_resizing = hit == "resize"
        if hit == "resize":
            self.override_cursor(CURSOR_SIZE_FDIAG)
        else:
            self.override_cursor(CURSOR_SIZE_ALL)
        return True

    def _stable_preview_window_interaction_active(self) -> bool:
        """Return whether the preview window is being moved/resized."""
        return (
            self.stable_preview_window_dragging
            or self.stable_preview_window_resizing
        )

    def _stable_preview_update_window_interaction(self, pos) -> None:
        """Move or resize the preview window in widget coordinates."""
        press_pos = self.stable_preview_window_press_pos
        press_rect = self.stable_preview_window_press_rect
        if press_pos is None or press_rect is None:
            self._stable_preview_end_window_interaction()
            return
        delta = QtCore.QPointF(pos) - press_pos
        if self.stable_preview_window_dragging:
            rect = QtCore.QRectF(press_rect)
            rect.translate(delta)
            self.stable_preview_window_rect = (
                self._stable_preview_clamp_window_rect(rect)
            )
        elif self.stable_preview_window_resizing:
            rect = QtCore.QRectF(
                press_rect.left(),
                press_rect.top(),
                press_rect.width() + delta.x(),
                press_rect.height() + delta.y(),
            )
            self.stable_preview_window_rect = (
                self._stable_preview_clamp_window_rect(rect)
            )
            self._stable_preview_sync_source_to_window()
        self.update()

    def _stable_preview_end_window_interaction(self) -> None:
        """End preview window move/resize interaction."""
        self.stable_preview_window_dragging = False
        self.stable_preview_window_resizing = False
        self.stable_preview_window_press_pos = None
        self.stable_preview_window_press_rect = None
        self.update()

    def _stable_preview_update_window_hover(self, pos) -> bool:
        """Update cursor when hovering the preview window."""
        hit = self._stable_preview_window_hit_test(pos)
        if hit == "resize":
            self.override_cursor(CURSOR_SIZE_FDIAG)
            return True
        if hit == "move":
            self.override_cursor(CURSOR_SIZE_ALL)
            return True
        return False

    def _stable_preview_begin_drag_locked(
        self, press_pos, edge_name: str
    ) -> None:
        """Lock a local crop rect at the drag start position.

        Called from the rect-edge mouse-press branch, **after** the drag
        has already been committed (``rect_edge_dragging`` is True). The
        crop rect is frozen for the whole drag — only the frame is
        repainted afterwards. The existing TargetPreview crop rect is
        left untouched so release can fall back to it.

        Does nothing when the drag-locked sub-switch is off (the drag
        then continues under whatever target preview was already shown).

        Args:
            press_pos: Image-coordinate press position (QPointF).
            edge_name: The edge being dragged (left/right/top/bottom).
        """
        if not self.stable_preview_drag_locked_enabled:
            return
        if self.pixmap is None or self.pixmap.isNull():
            return
        active = self.rect_edge_active_edge
        if active is None:
            return
        view_w, view_h = self._stable_preview_source_size()
        rect = QtCore.QRectF(
            press_pos.x() - view_w / 2.0,
            press_pos.y() - view_h / 2.0,
            view_w,
            view_h,
        )
        self.stable_preview_shape = active.shape
        self.stable_preview_active_edge_name = edge_name
        self.stable_preview_locked_rect = self._clamp_rectf_to_image(rect)
        self.stable_preview_mode = "drag_locked"

    def _stable_preview_clear_drag_locked(self) -> None:
        """Clear only the drag-locked state, keeping TargetPreview.

        Used by ``clear_rect_edge_alignment`` so that a rect-edge
        release/escape can fall back to TargetPreview instead of wiping
        everything (phase 2 split — never use a single catch-all clear).
        """
        self.stable_preview_locked_rect = None
        self.stable_preview_active_edge_name = None
        if self.stable_preview_mode == "drag_locked":
            self.stable_preview_mode = "none"

    def _stable_preview_clear_target(self) -> None:
        """Clear only the target state, keeping drag-locked."""
        self.stable_preview_target_rect = None
        if self.stable_preview_mode == "target":
            self.stable_preview_mode = "none"

    def _stable_preview_clear_all(self) -> None:
        """Clear everything: shape, drag-locked, target, mode.

        Used by image-swap/reset paths (load_pixmap, load_shapes,
        reset_state, set_editing(False)) where no preview may survive.
        """
        self.stable_preview_shape = None
        self.stable_preview_locked_rect = None
        self.stable_preview_target_rect = None
        self.stable_preview_active_edge_name = None
        self.stable_preview_mode = "none"

    def _stable_preview_enter_target_if_valid(self) -> None:
        """Re-enter TargetPreview after a drag if the selection allows it.

        This is the ONLY place the safe-zone anti-drift check runs
        (phase 2 design): it fires when a drag-locked preview ends and
        the same rectangle is still selected, deciding whether to keep
        the existing target_rect or recompute it. It is never hooked into
        mouseMoveEvent.
        """
        if (
            not self.stable_preview_enabled
            or not self.stable_preview_target_enabled
        ):
            self._stable_preview_clear_all()
            return
        sel = self.selected_shapes
        if len(sel) == 1 and sel[0].shape_type == "rectangle":
            self.stable_preview_shape = sel[0]
            self._stable_preview_update_target_rect_by_safezone()
            self.stable_preview_mode = "target"
        else:
            self._stable_preview_clear_all()

    def _stable_preview_compute_target_rect(self, shape):
        """Compute a fresh TargetPreview crop rect (image coords).

        Algorithm (task doc §7.1): bbox center centered crop whose size is
        ``max(base view size, padded bbox size)``, clamped to the image.
        """
        if self.pixmap is None or self.pixmap.isNull():
            return None
        geom = rea.geometry_from_shape(shape)
        if geom is None:
            return None
        # Source size keeps the preview window aspect ratio, so the image
        # crop and overlay geometry share one affine mapping.
        crop_w, crop_h = self._stable_preview_source_size(shape)
        cx = (geom.x_min + geom.x_max) / 2.0
        cy = (geom.y_min + geom.y_max) / 2.0
        rect = QtCore.QRectF(
            cx - crop_w / 2.0, cy - crop_h / 2.0, crop_w, crop_h
        )
        return self._clamp_rectf_to_image(rect)

    def _stable_preview_update_target_rect_by_safezone(self) -> None:
        """Keep or recompute the target rect by the safe-zone rule.

        If the current bbox still falls inside the central safe region of
        the existing target_rect, the rect is kept (background stable).
        Otherwise it is recomputed. Edges already clamped to the image
        border relax the safe boundary on that side (task doc §8.2),
        using a tolerance of 1.0px instead of exact ``== 0``.
        """
        shape = self.stable_preview_shape
        if shape is None:
            self._stable_preview_clear_target()
            return
        geom = rea.geometry_from_shape(shape)
        if geom is None:
            self._stable_preview_clear_target()
            return
        cur = self.stable_preview_target_rect
        if cur is None or self.pixmap is None or self.pixmap.isNull():
            self.stable_preview_target_rect = (
                self._stable_preview_compute_target_rect(shape)
            )
            return
        # Safe region = central ratio of the current target rect.
        sr = self.stable_preview_safe_ratio
        inset_x = cur.width() * (1.0 - sr) / 2.0
        inset_y = cur.height() * (1.0 - sr) / 2.0
        safe_left = cur.left() + inset_x
        safe_right = cur.right() - inset_x
        safe_top = cur.top() + inset_y
        safe_bottom = cur.bottom() - inset_y
        # Edge relaxation: a side clamped to the image border has no room
        # to keep centering, so relax that side's safe boundary outward.
        tol = 1.0
        iw = float(self.pixmap.width())
        ih = float(self.pixmap.height())
        if cur.left() < tol:
            safe_left = cur.left()
        if cur.top() < tol:
            safe_top = cur.top()
        if cur.right() > iw - tol:
            safe_right = cur.right()
        if cur.bottom() > ih - tol:
            safe_bottom = cur.bottom()
        inside = (
            geom.x_min >= safe_left
            and geom.x_max <= safe_right
            and geom.y_min >= safe_top
            and geom.y_max <= safe_bottom
        )
        if not inside:
            self.stable_preview_target_rect = (
                self._stable_preview_compute_target_rect(shape)
            )

    def _stable_preview_on_selection_changed(self, selected_shapes) -> None:
        """Slot for ``selection_changed``: drive TargetPreview.

        A drag-locked preview always takes priority, so selection changes
        are ignored while dragging. Single-rectangle selection enters
        TargetPreview; anything else clears it.
        """
        if self.stable_preview_mode == "drag_locked":
            return
        if (
            not self.stable_preview_enabled
            or not self.stable_preview_target_enabled
        ):
            self._stable_preview_clear_all()
            return
        if (
            len(selected_shapes) == 1
            and selected_shapes[0].shape_type == "rectangle"
        ):
            self.stable_preview_shape = selected_shapes[0]
            self.stable_preview_target_rect = (
                self._stable_preview_compute_target_rect(selected_shapes[0])
            )
            self.stable_preview_mode = "target"
        else:
            self._stable_preview_clear_all()

    def _clamp_rectf_to_image(self, rect: QtCore.QRectF) -> QtCore.QRectF:
        """Clamp a rect (image coords) to the current pixmap bounds."""
        if self.pixmap is None or self.pixmap.isNull():
            return rect
        iw = float(self.pixmap.width())
        ih = float(self.pixmap.height())
        width = min(rect.width(), iw)
        height = min(rect.height(), ih)
        left = max(0.0, min(rect.left(), iw - width))
        top = max(0.0, min(rect.top(), ih - height))
        return QtCore.QRectF(left, top, width, height)

    def clear_rect_edge_alignment(self):
        """Clear transient edge-editing interaction state."""
        self.rect_edge_hover_edge = None
        self.rect_edge_active_edge = None
        self.rect_edge_dragging = False
        self.rect_edge_drag_start_points = None
        # Phase 2 split: only drop the drag-locked preview here, NOT the
        # target preview. This single call site covers mouse-release, Esc
        # cancel, cancel_rect_edge_drag, and load_shapes. Release/escape
        # then call _stable_preview_enter_target_if_valid() to fall back
        # to TargetPreview; the image-swap paths (load_pixmap /
        # load_shapes / reset_state) additionally call
        # _stable_preview_clear_all() to wipe the target too.
        self._stable_preview_clear_drag_locked()

    def cancel_rect_edge_drag(self):
        """Cancel an in-progress edge drag and restore the pre-drag points.

        Returns:
            True if a drag was cancelled, False when no drag was active.
        """
        if not self.rect_edge_dragging:
            return False

        active = self.rect_edge_active_edge
        start_points = self.rect_edge_drag_start_points
        if active is not None and start_points is not None:
            # Restore the target shape's points exactly as they were before
            # the drag preview mutated them in place.
            active.shape.points = list(start_points)
            active.shape._invalidate_cache()

        self.clear_rect_edge_alignment()
        # Phase 2: cancelling a drag falls back to TargetPreview if a
        # single rectangle is still selected.
        self._stable_preview_enter_target_if_valid()
        self.update()
        return True

    def _handle_rect_edge_escape(self):
        """Handle Esc while the edge editing mode is active.

        Cancels an in-progress drag. Esc never toggles the mode itself nor
        the View-menu action.

        Returns:
            True when the key event was consumed, False to let the caller
            fall through to the default Esc behaviour.
        """
        if self.rect_edge_dragging:
            self.cancel_rect_edge_drag()
            return True
        return False

    def _rect_edge_hit_candidate(self, point):
        """Return an edge candidate on the single selected rectangle.

        Only runs while the mode is enabled and the canvas is in editing
        mode. An unselected rectangle keeps the normal whole-shape selection
        semantics. Vertex hits take priority over edge hits.

        Args:
            point: Mouse position in image coordinates.

        Returns:
            The best ``RectEdgeRef`` or ``None``.
        """
        if not self.rect_edge_align_enabled or not self.editing():
            return None
        if len(self.selected_shapes) != 1:
            return None

        epsilon = self.epsilon / self.scale
        shape = self.selected_shapes[0]
        if (
            shape not in self.shapes
            or not self.is_shape_interactive(shape)
            or shape.shape_type != "rectangle"
        ):
            return None
        # Vertex priority: defer to the normal vertex interaction instead of
        # offering an edge control handle at a rectangle corner.
        if shape.nearest_vertex(point, epsilon) is not None:
            return None
        result = rea.nearest_edge(shape, point, epsilon)
        return result[0] if result is not None else None

    def _draw_rect_edge_alignment_overlay(self, painter):
        """Draw the rectangle edge editing status overlay.

        Status colours only cover the specific edge each interaction is
        about; non-participating rectangles keep their original colour:

        ===========  =============  =======
        state        colour         style
        ===========  =============  =======
        hover        white          thin solid
        active       white          medium solid
        ===========  =============  =======

        Line widths are scaled by ``Shape.scale`` so they stay visually
        stable across zoom levels and never grow thick when zoomed in.

        Args:
            painter: The active :class:`QPainter` (already scaled to pixmap
                space by ``paintEvent``).
        """
        active = self.rect_edge_active_edge
        keyboard_active = None
        if (
            self.rect_edge_keyboard_shape is not None
            and self.rect_edge_keyboard_edge is not None
        ):
            import anylabeling.views.labeling.rect_edge_alignment as rea

            geom = rea.geometry_from_shape(self.rect_edge_keyboard_shape)
            if geom is not None:
                keyboard_active = rea.edge_from_geometry(
                    self.rect_edge_keyboard_shape,
                    geom,
                    self.rect_edge_keyboard_edge,
                )

        if keyboard_active is not None:
            active = keyboard_active
        if active is not None:
            self._draw_edge(
                painter, active, QtGui.QColor(255, 255, 255), width=2.0
            )

        hover = self.rect_edge_hover_edge
        # Don't repaint the hover edge if it coincides with a higher-priority
        # active state (avoids colour flicker).
        if hover is not None:
            if active is not None and hover.shape is active.shape:
                pass
            else:
                self._draw_edge(
                    painter, hover, QtGui.QColor(255, 255, 255), width=1.5
                )

    @staticmethod
    def _draw_edge(painter, edge, color, width=2.0, dash=False):
        """Draw a single edge segment with a screen-stable pen.

        Args:
            painter: The active :class:`QPainter`.
            edge: The :class:`RectEdgeRef` to draw.
            color: The :class:`QtGui.QColor` for the edge.
            width: Base line width (divided by ``Shape.scale``).
            dash: When True, use a dashed style.
        """
        style = Qt.PenStyle.DashLine if dash else Qt.PenStyle.SolidLine
        pen = QtGui.QPen(
            color,
            max(1, int(round(width / Shape.scale))),
            style,
        )
        painter.setPen(pen)
        painter.setOpacity(1.0)
        painter.drawLine(edge.p1, edge.p2)

    # ------------------------------------------------------------------
    # Stable refine preview — overlay drawing (phase 1).
    # ------------------------------------------------------------------

    @staticmethod
    def _img_to_preview_xy(img_x, img_y, target, src):
        """Map an image point to preview-window coordinates.

        Args:
            img_x, img_y: Point in image (pixel) coordinates.
            target: The preview window rect in widget coordinates.
            src: The actually drawn crop rect in image coordinates.

        Returns:
            ``(x, y)`` in widget coordinates.
        """
        scale_x = target.width() / max(1.0, src.width())
        scale_y = target.height() / max(1.0, src.height())
        return (
            target.left() + (img_x - src.left()) * scale_x,
            target.top() + (img_y - src.top()) * scale_y,
        )

    def _draw_stable_preview_overlay(self, painter):
        """Draw the magnified preview (bottom-right pin).

        The painter is currently in pixmap space (scaled + translated by
        ``paintEvent``). This method saves/restores and resets the
        transform so the whole overlay is laid out in **widget
        coordinates** — the window stays pinned to the bottom-right and
        is unaffected by the main canvas zoom/pan.

        The crop rect is selected by ``stable_preview_mode``: the
        drag-locked rect (frozen for the drag) or the target rect (kept
        stable by the safe-zone rule). Either way the background does not
        drift; only the frame (and, in drag-locked mode, the active-edge
        highlight) is repainted from live shape points.
        """
        mode = self.stable_preview_mode
        self._stable_preview_sync_source_to_window()
        if mode == "drag_locked":
            src = self.stable_preview_locked_rect
        elif mode == "target":
            src = self.stable_preview_target_rect
        else:
            return
        shape = self.stable_preview_shape
        if src is None or shape is None:
            return
        geom = rea.geometry_from_shape(shape)
        if geom is None:
            return

        scale = self.stable_preview_scale
        target = QtCore.QRectF(
            self._stable_preview_current_window_rect().toAlignedRect()
        )
        src = QtCore.QRectF(src.toAlignedRect())

        painter.save()
        painter.resetTransform()
        painter.setOpacity(1.0)

        # --- Background frame ------------------------------------------
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 200), 1.0))
        painter.setBrush(QtGui.QColor(0, 0, 0, 180))
        painter.drawRect(target)

        # --- Cropped & magnified image (one shot, no cache) -----------
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QBrush())
        painter.drawPixmap(
            target.toAlignedRect(),
            self.pixmap,
            src.toAlignedRect(),
        )

        # --- Context rectangles inside the preview crop ----------------
        # Other visible rectangles provide alignment references while the
        # current target remains visually dominant.
        painter.save()
        painter.setClipRect(target)
        context_pen = QtGui.QPen(QtGui.QColor(80, 170, 255, 170), 1.2)
        painter.setPen(context_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for other_shape in self.shapes:
            if other_shape is shape:
                continue
            if other_shape.shape_type != "rectangle":
                continue
            if not self.is_shape_interactive(other_shape):
                continue
            other_geom = rea.geometry_from_shape(other_shape)
            if other_geom is None or not other_geom.is_valid():
                continue
            other_rect = QtCore.QRectF(
                other_geom.x_min,
                other_geom.y_min,
                other_geom.width,
                other_geom.height,
            )
            if not other_rect.intersects(src):
                continue
            other_tl = self._img_to_preview_xy(
                other_geom.x_min, other_geom.y_min, target, src
            )
            other_tr = self._img_to_preview_xy(
                other_geom.x_max, other_geom.y_min, target, src
            )
            other_br = self._img_to_preview_xy(
                other_geom.x_max, other_geom.y_max, target, src
            )
            other_bl = self._img_to_preview_xy(
                other_geom.x_min, other_geom.y_max, target, src
            )
            painter.drawPolygon(
                QtGui.QPolygonF(
                    [
                        QtCore.QPointF(*other_tl),
                        QtCore.QPointF(*other_tr),
                        QtCore.QPointF(*other_br),
                        QtCore.QPointF(*other_bl),
                    ]
                )
            )
        painter.restore()

        # --- Current rectangle frame (live geometry) ------------------
        tl = self._img_to_preview_xy(geom.x_min, geom.y_min, target, src)
        tr = self._img_to_preview_xy(geom.x_max, geom.y_min, target, src)
        br = self._img_to_preview_xy(geom.x_max, geom.y_max, target, src)
        bl = self._img_to_preview_xy(geom.x_min, geom.y_max, target, src)
        poly = QtGui.QPolygonF(
            [
                QtCore.QPointF(*tl),
                QtCore.QPointF(*tr),
                QtCore.QPointF(*br),
                QtCore.QPointF(*bl),
            ]
        )
        painter.setPen(QtGui.QPen(QtGui.QColor(80, 220, 120), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(poly)

        # --- Active edge highlight (drag-locked only) ------------------
        # TargetPreview is for observing overall fit, so it deliberately
        # shows no edge highlight; that stays on the main canvas overlay.
        edge_name = self.stable_preview_active_edge_name
        if mode == "drag_locked" and edge_name in (
            "left",
            "right",
            "top",
            "bottom",
        ):
            corners = {"tl": tl, "tr": tr, "br": br, "bl": bl}
            pairs = {
                "left": ("tl", "bl"),
                "right": ("tr", "br"),
                "top": ("tl", "tr"),
                "bottom": ("bl", "br"),
            }
            a, b = pairs[edge_name]
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 235, 60), 2.5))
            painter.drawLine(
                QtCore.QPointF(*corners[a]),
                QtCore.QPointF(*corners[b]),
            )

        # --- Magnification label ---------------------------------------
        label = f"{int(round(scale))}x"
        painter.setPen(QtGui.QColor(255, 255, 255))
        painter.fillRect(
            QtCore.QRectF(target.left() + 4, target.top() + 4, 78, 16),
            QtGui.QColor(0, 0, 0, 160),
        )
        painter.drawText(
            QtCore.QRectF(target.left() + 4, target.top() + 4, 78, 16),
            Qt.AlignmentFlag.AlignCenter,
            f"{label}  drag",
        )

        # --- Resize affordance -----------------------------------------
        handle = float(self.stable_preview_resize_handle_px)
        handle_rect = QtCore.QRectF(
            target.right() - handle,
            target.bottom() - handle,
            handle,
            handle,
        )
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 180), 1.0))
        for i in range(3):
            offset = 4.0 + i * 4.0
            painter.drawLine(
                QtCore.QPointF(handle_rect.right() - offset, target.bottom()),
                QtCore.QPointF(target.right(), handle_rect.bottom() - offset),
            )

        painter.restore()

    def move_by_keyboard(self, offset):
        """Move selected shapes by an offset (using keyboard)"""
        if self.selected_shapes:
            self.bounded_move_shapes(
                self.selected_shapes, self.prev_point + offset
            )
            self.repaint()
            self.moving_shape = True

    # ------------------------------------------------------------------
    # Keyboard edge selection (Feature 3, task 5.9-5.13)
    # ------------------------------------------------------------------
    _KEYBOARD_EDGE_CYCLE = ("left", "top", "right", "bottom")

    def _keyboard_edge_active(self):
        """Return True if a keyboard-selected edge is currently active."""
        return (
            self.rect_edge_keyboard_edge is not None
            and self.rect_edge_keyboard_shape is not None
        )

    def _clear_keyboard_edge(self):
        """Clear the keyboard-selected edge. Return True if it was active."""
        if self.rect_edge_keyboard_edge is not None:
            self.rect_edge_keyboard_edge = None
            self.rect_edge_keyboard_shape = None
            return True
        return False

    def _cycle_keyboard_edge(self):
        """Advance/clear the keyboard-selected rectangle edge (task 5.9-5.11).

        Requires exactly one selected rectangle. Cycles left -> top ->
        right -> bottom -> left.
        """
        if (
            len(self.selected_shapes) != 1
            or getattr(self.selected_shapes[0], "shape_type", None)
            != "rectangle"
        ):
            self._clear_keyboard_edge()
            self.keyboard_edge_selected.emit("")
            return

        shape = self.selected_shapes[0]
        current = self.rect_edge_keyboard_edge
        if self.rect_edge_keyboard_shape is not shape or current is None:
            self.rect_edge_keyboard_shape = shape
            self.rect_edge_keyboard_edge = self._KEYBOARD_EDGE_CYCLE[0]
        else:
            idx = self._KEYBOARD_EDGE_CYCLE.index(current)
            nxt = (idx + 1) % len(self._KEYBOARD_EDGE_CYCLE)
            self.rect_edge_keyboard_edge = self._KEYBOARD_EDGE_CYCLE[nxt]
        self.keyboard_edge_selected.emit(self.rect_edge_keyboard_edge)
        self.update()

    def _nudge_keyboard_edge(self, key, step, modifiers):
        """Nudge the keyboard-selected edge by ±step image pixels.

        For left/top edges, Up/Left move inward (negative), Down/Right
        outward; for right/bottom the opposite. Uses
        rect_edge_alignment.apply_edge_coord which clamps to min_size
        (task 5.13/5.14, anti-flip via 5.16).
        """
        import anylabeling.views.labeling.rect_edge_alignment as rea

        shape = self.rect_edge_keyboard_shape
        edge = self.rect_edge_keyboard_edge
        if shape is None or edge is None:
            return
        geom = rea.geometry_from_shape(shape)
        if geom is None:
            return
        if edge in ("left", "right"):
            coord = geom.x_min if edge == "left" else geom.x_max
            if key == QtCore.Qt.Key.Key_Left:
                coord -= step
            elif key == QtCore.Qt.Key.Key_Right:
                coord += step
            else:
                # Up/Down do not apply to vertical edges.
                return
        else:  # top / bottom
            coord = geom.y_min if edge == "top" else geom.y_max
            if key == QtCore.Qt.Key.Key_Up:
                coord -= step
            elif key == QtCore.Qt.Key.Key_Down:
                coord += step
            else:
                return
        rea.apply_edge_coord(shape, edge, coord, min_size=1.0)
        shape._invalidate_cache()
        # Commit immediately with a 500ms merge window so rapid key
        # repeats collapse into one undo step (task 5.15, N2/D5).
        self.store_shapes(merge_window=0.5)
        self.shape_moved.emit()
        self.update()

    # ------------------------------------------------------------------
    # Local edge snapping (Feature 4, task 6.1-6.14)
    # ------------------------------------------------------------------
    def _ensure_edge_snap_cache(self):
        """Lazily build/refresh the edge-snap gradient cache from the
        current pixmap (task 6.1). Keyed on pixmap.cacheKey() so image
        switches invalidate it."""
        from anylabeling.views.labeling.edge_snap import EdgeSnapCache

        if not hasattr(self, "_edge_snap_cache"):
            self._edge_snap_cache = EdgeSnapCache()
        if self.pixmap is None or self.pixmap.isNull():
            return None
        key = self.pixmap.cacheKey()
        # Convert pixmap to a known 4-channel QImage format before exposing
        # its memory to numpy; QPixmap.toImage() may otherwise return a
        # format with a different bytes-per-pixel or padded scanlines.
        qimg = self.pixmap.toImage().convertToFormat(
            QtGui.QImage.Format.Format_RGBA8888
        )
        w, h = qimg.width(), qimg.height()
        if w <= 0 or h <= 0:
            return None
        ptr = qimg.bits()
        bytes_per_line = qimg.bytesPerLine()
        ptr.setsize(h * bytes_per_line)
        import numpy as np

        raw = np.frombuffer(ptr, dtype=np.uint8).reshape(h, bytes_per_line)
        arr = raw[:, : w * 4].reshape(h, w, 4)
        gray = arr[:, :, :3].mean(axis=2).astype(np.uint8)
        self._edge_snap_cache.ensure(gray, key)
        return self._edge_snap_cache

    def snap_active_edge(self, search_range=4):
        """Snap the keyboard-selected edge to the strongest nearby
        image edge (task 6.11). Keypress-triggered (not realtime).

        Validates before applying (Q11): if the candidate would trigger
        a clamp in apply_edge_coord (anti-flip/min-size), the snap is
        treated as a failure and the edge stays put.
        """
        if not self._keyboard_edge_active():
            return {"status": "inactive"}
        import anylabeling.views.labeling.rect_edge_alignment as rea
        from anylabeling.views.labeling.edge_snap import (
            best_snap_candidate,
        )

        cache = self._ensure_edge_snap_cache()
        shape = self.rect_edge_keyboard_shape
        edge = self.rect_edge_keyboard_edge
        if shape is None or edge is None or cache is None:
            return {"status": "failed", "reason": "no_cache"}
        geom = rea.geometry_from_shape(shape)
        if geom is None:
            return {"status": "failed", "reason": "invalid_geometry"}

        search_range = max(1, int(search_range))
        if edge in ("left", "right"):
            coord = geom.x_min if edge == "left" else geom.x_max
            seg_lo, seg_hi = geom.y_min, geom.y_max
        else:
            coord = geom.y_min if edge == "top" else geom.y_max
            seg_lo, seg_hi = geom.x_min, geom.x_max

        result = best_snap_candidate(
            cache,
            edge_name=edge,
            current_coord=coord,
            seg_lo=seg_lo,
            seg_hi=seg_hi,
            search_range=search_range,
        )
        if result is None:
            return {"status": "failed", "reason": "unreliable_edge"}
        cand, _score = result

        # Q11 validate-before-apply: if the candidate would be clamped
        # by geometry_with_edge_coord, treat as failure (keep current).
        test_geom = rea.geometry_with_edge_coord(
            geom, edge, cand, min_size=1.0
        )
        clamped_coord = {
            "left": test_geom.x_min,
            "right": test_geom.x_max,
            "top": test_geom.y_min,
            "bottom": test_geom.y_max,
        }[edge]
        if clamped_coord != cand:
            # Would have triggered clamp -> fail, keep current.
            return {"status": "failed", "reason": "clamped"}

        rea.apply_edge_coord(shape, edge, cand, min_size=1.0)
        shape._invalidate_cache()
        self.store_shapes()
        self.shape_moved.emit()
        self.update()
        return {
            "status": "success",
            "edge": edge,
            "old_coord": coord,
            "new_coord": cand,
            "delta": cand - coord,
        }

    def rotate_by_keyboard(self, theta):
        """Rotate selected shapes by an theta (using keyboard)"""
        if self.selected_shapes:
            rotating_shape = False
            for i, shape in enumerate(self.selected_shapes):
                if shape._shape_type == "rotation":
                    self.bounded_rotate_shapes(i, shape, theta)
                    rotating_shape = True
            if rotating_shape:
                self.repaint()
                self.rotating_shape = True

    # QT Overload
    def event(self, ev):
        """Handle Tab before Qt consumes it for focus traversal."""
        if (
            ev.type() == QtCore.QEvent.Type.KeyPress
            and ev.key() == QtCore.Qt.Key.Key_Tab
            and self.editing()
        ):
            if self._editing_special_key(ev.key()):
                ev.accept()
                return True
        return super(Canvas, self).event(ev)

    def keyPressEvent(self, ev):
        """Key press event"""
        key = ev.key()
        # Rectangle edge editing: Esc cancels the current drag but never
        # toggles the mode or the View-menu action. The
        # default key handling lives in ``_dispatch_default_key_press`` so
        # this dispatcher stays under the McCabe complexity cap.
        if key == QtCore.Qt.Key.Key_Escape and self.rect_edge_align_enabled:
            if self._handle_rect_edge_escape():
                return
        self._dispatch_default_key_press(ev)

    def _dispatch_default_key_press(self, ev):
        """Dispatch the default key handling for non-edge-editing shortcuts.

        Args:
            ev: The original :class:`QKeyEvent`.
        """
        modifiers = ev.modifiers()
        key = ev.key()
        if self.drawing():
            if key == QtCore.Qt.Key.Key_Escape and self.current:
                self.current = None
                self._brush_drawing = False
                self.drawing_polygon.emit(False)
                self.update()
            elif key == QtCore.Qt.Key.Key_Backspace and self.current:
                if self.create_mode in ["polygon", "linestrip"]:
                    if len(self.current.points) > 1:
                        self.current.points.pop()
                        self.line[0] = self.current[-1]
                        self.update()
                    elif len(self.current.points) == 1:
                        self.current = None
                        self._brush_drawing = False
                        self.drawing_polygon.emit(False)
                        self.update()
            elif key == QtCore.Qt.Key.Key_Return and self.can_close_shape():
                self.finalise()
            elif modifiers == QtCore.Qt.KeyboardModifier.AltModifier:
                self.snapping = False
        elif self.editing():
            if self._editing_special_key(key):
                return
            if self._editing_arrow_dispatch(key, modifiers):
                return
            if key == QtCore.Qt.Key.Key_Z:
                self.rotate_by_keyboard(self.large_rotation_increment)
            elif key == QtCore.Qt.Key.Key_X:
                self.rotate_by_keyboard(self.small_rotation_increment)
            elif key == QtCore.Qt.Key.Key_C:
                self.rotate_by_keyboard(-self.small_rotation_increment)
            elif key == QtCore.Qt.Key.Key_V:
                self.rotate_by_keyboard(-self.large_rotation_increment)
            else:
                super(Canvas, self).keyPressEvent(ev)
                return
        else:
            super(Canvas, self).keyPressEvent(ev)
            return

    def _editing_special_key(self, key):
        """Handle Tab/Esc in editing mode (Feature 3 keyboard edge).

        Returns True when the key was consumed.
        """
        if key == QtCore.Qt.Key.Key_Tab:
            self._cycle_keyboard_edge()
            return True
        if key == QtCore.Qt.Key.Key_Escape:
            if self._clear_keyboard_edge():
                self.update()
                return True
        return False

    def _editing_arrow_dispatch(self, key, modifiers):
        """Dispatch arrow keys to whole-shape or single-edge nudge.

        Returns True when the key was an arrow and was consumed.
        Default step is 1px; Shift scales to MOVE_SPEED (5px) (task 5.7/
        5.8). When a keyboard edge is active, arrows nudge that edge
        instead (task 5.13/5.14).
        """
        if key not in (
            QtCore.Qt.Key.Key_Up,
            QtCore.Qt.Key.Key_Down,
            QtCore.Qt.Key.Key_Left,
            QtCore.Qt.Key.Key_Right,
        ):
            return False
        step = (
            MOVE_SPEED
            if modifiers & QtCore.Qt.KeyboardModifier.ShiftModifier
            else 1.0
        )
        if self._keyboard_edge_active():
            self._nudge_keyboard_edge(key, step, modifiers)
            return True
        if key == QtCore.Qt.Key.Key_Up:
            self.move_by_keyboard(QtCore.QPointF(0.0, -step))
        elif key == QtCore.Qt.Key.Key_Down:
            self.move_by_keyboard(QtCore.QPointF(0.0, step))
        elif key == QtCore.Qt.Key.Key_Left:
            self.move_by_keyboard(QtCore.QPointF(-step, 0.0))
        elif key == QtCore.Qt.Key.Key_Right:
            self.move_by_keyboard(QtCore.QPointF(step, 0.0))
        return True

    # QT Overload
    def keyReleaseEvent(self, ev):
        """Key release event"""
        modifiers = ev.modifiers()
        if self.drawing():
            if modifiers == QtCore.Qt.KeyboardModifier.NoModifier:
                self.snapping = True
        elif self.editing():
            # NOTE: Temporary fix to avoid ValueError
            # when the selected shape is not in the shapes list
            if (
                (self.moving_shape or self.rotating_shape)
                and self.selected_shapes
                and self.selected_shapes[0] in self.shapes
            ):
                index = self.shapes.index(self.selected_shapes[0])
                if (
                    self.shapes_backups[-1][index].points
                    != self.shapes[index].points
                ):
                    self.store_shapes()
                    if self.moving_shape:
                        self.shape_moved.emit()
                    if self.rotating_shape:
                        self.shape_rotated.emit()

                if self.moving_shape:
                    self.moving_shape = False
                if self.rotating_shape:
                    self.rotating_shape = False

    def set_last_label(self, text, flags, group_id):
        """Set label and flags for last shape"""
        assert text
        if self.is_auto_labeling:
            self.shapes[-1].label = self.auto_labeling_mode.edit_mode
        else:
            self.shapes[-1].label = text
        self.shapes[-1].flags = flags
        self.shapes[-1].group_id = group_id
        self.shapes_backups.pop()
        self.store_shapes()
        return self.shapes[-1]

    def undo_last_line(self):
        """Undo last line"""
        assert self.shapes
        self.current = self.shapes.pop()
        self.current.set_open()
        if self.create_mode in ["polygon", "linestrip", "quadrilateral"]:
            self.line.points = [self.current[-1], self.current[0]]
        elif self.create_mode in [
            "rectangle",
            "line",
            "circle",
            "rotation",
            "cuboid",
        ]:
            self.current.points = self.current.points[0:1]
        elif self.create_mode == "point":
            self.current = None
        self.drawing_polygon.emit(True)

    def undo_last_point(self):
        """Undo last point"""
        if not self.current or self.current.is_closed():
            return
        self.current.pop_point()
        if len(self.current) > 0:
            self.line[0] = self.current[-1]
        else:
            self.current = None
            self._brush_drawing = False
            self.drawing_polygon.emit(False)
        self.update()

    def load_pixmap(self, pixmap, clear_shapes=True):
        """Load pixmap"""
        self.pixmap = pixmap
        if clear_shapes:
            self.shapes = []
        # Image swap: wipe the whole preview (drag-locked AND target) so
        # a stale crop referencing the old pixmap is never rendered over
        # the new image.
        self._stable_preview_clear_all()
        self.update()

    def _has_pose_shapes(self):
        """Return True if any COCO keypoint point shape exists."""
        if not self.shapes:
            return False
        return any(
            s.shape_type == "point" and s.label in COCO_KEYPOINT_SET
            for s in self.shapes
        )

    def load_shapes(self, shapes, replace=True, store_backup=True):
        """Load shapes"""
        _t0 = time.perf_counter()
        if replace:
            self.shapes = list(shapes)
        else:
            self.shapes.extend(shapes)
        _t_before_store = time.perf_counter()
        if store_backup:
            self.store_shapes()
            self._pending_initial_backup = False
        else:
            self._pending_initial_backup = True
        _t_after_store = time.perf_counter()
        self.current = None
        self._brush_drawing = False
        self.h_hape = None
        self.h_vertex = None
        self.h_edge = None
        self.h_cuboid_face = None
        # Drop any in-progress rectangle edge edit so transient state never
        # leaks across images. clear_rect_edge_alignment only clears the
        # drag-locked preview, so wipe the target preview too.
        self.clear_rect_edge_alignment()
        self._stable_preview_clear_all()
        self.update()
        _t_total = time.perf_counter()
        total_time = _t_total - _t0
        if total_time > 0.1:
            _perf_log(
                "Canvas.load_shapes slow: store_shapes=%.3fs, total=%.3fs, "
                "count=%d",
                _t_after_store - _t_before_store,
                total_time,
                len(self.shapes),
            )

    def set_shape_visible(self, shape, value):
        """Set visibility for a shape"""
        self.visible[shape] = value
        self.update()

    def current_cursor(self):
        """Current cursor"""
        cursor = QtWidgets.QApplication.overrideCursor()
        cursor = cursor.shape() if cursor else None

        return cursor

    def override_cursor(self, cursor):
        """Override cursor"""
        current_cursor = self.current_cursor()
        if current_cursor != cursor:
            self._cursor = cursor
            if current_cursor is None:
                QtWidgets.QApplication.setOverrideCursor(cursor)
            else:
                QtWidgets.QApplication.changeOverrideCursor(cursor)

    def restore_cursor(self):
        """Restore override cursor"""
        QtWidgets.QApplication.restoreOverrideCursor()

    def reset_state(self):
        """Clear shapes and pixmap"""
        self.restore_cursor()
        self.pixmap = None
        self.shapes_backups = []
        self.is_move_editing = False
        self.compare_pixmap = None
        # Reset every transient interaction state. reset_state() is the
        # hard-reset path and did not previously clear rect-edge state,
        # so clear it explicitly here. clear_rect_edge_alignment only
        # clears the drag-locked preview, so wipe the target preview too.
        self.clear_rect_edge_alignment()
        self._stable_preview_clear_all()
        self.update()

    def set_cross_line(self, show, width, color, opacity):
        """Set cross line options"""
        self.cross_line_show = show
        self.cross_line_width = width
        self.cross_line_color = color
        self.cross_line_opacity = opacity
        self.update()

    def gen_new_group_id(self):
        """Generate new shape's group_id based on current shapes"""
        max_group_id = 0
        for shape in self.shapes:
            if shape.group_id is not None:
                max_group_id = max(max_group_id, shape.group_id)
        return max_group_id + 1

    def merge_group_ids(self, group_ids, new_group_id):
        """Merge multiple shapes' group_id into a new one"""
        for shape in self.shapes:
            if shape.group_id in group_ids:
                shape.group_id = new_group_id

    def group_selected_shapes(self):
        """Group selected shapes"""
        if len(self.selected_shapes) == 0:
            return

        # List all group ids for selected shapes
        group_ids = set()
        has_non_group_shape = False
        for shape in self.selected_shapes:
            if shape.group_id is not None:
                group_ids.add(shape.group_id)
            else:
                has_non_group_shape = True

        # If there is at least 1 shape having a group id,
        # use that id as the new group id. Otherwise, generate a new group_id
        new_group_id = None
        if len(group_ids) > 0:
            new_group_id = min(group_ids)
        else:
            new_group_id = self.gen_new_group_id()

        # Merge group ids
        if len(group_ids) > 1:
            self.merge_group_ids(
                group_ids=group_ids, new_group_id=new_group_id
            )
        # Assign new_group_id to non-group shapes
        if has_non_group_shape:
            for shape in self.selected_shapes:
                if shape.group_id is None:
                    shape.group_id = new_group_id

        self.update()

    def ungroup_selected_shapes(self):
        """Ungroup selected shapes"""
        if len(self.selected_shapes) == 0:
            return

        # List all group ids for selected shapes
        group_ids = set()
        for shape in self.selected_shapes:
            if shape.group_id is not None:
                group_ids.add(shape.group_id)

        for group_id in group_ids:
            for shape in self.shapes:
                if shape.group_id == group_id:
                    shape.group_id = None

        self.update()
