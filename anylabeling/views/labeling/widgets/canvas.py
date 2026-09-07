"""This module defines Canvas widget - the core component for drawing image labels"""

import math
import os
import time
from collections.abc import Iterable, Mapping
from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QWheelEvent

from anylabeling.services.auto_labeling.types import AutoLabelingMode
from anylabeling.views.labeling.person_instance import is_valid_group_id
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
from ..rect_edge_interaction import RectEdgeInteractionController
from ..rectangle_size import RectangleSizeIssue, pick_overlay_anchor
from ..review_refinement.gain import (
    DEFAULT_TARGET_GAIN,
    effective_gain,
    image_delta_multiplier,
    resolve_target_gain,
)
from ..review_refinement.feedback import (
    ReviewFeedbackSnapshot,
    make_feedback_snapshot,
)
from ..review_refinement.assistance import (
    CandidatePreviewController,
    EdgeCandidate,
    EdgeCandidateService,
    build_loupe_roi,
)
from ..review_refinement.nudge import (
    NudgeBurstTracker,
    WheelAccumulator,
    valid_edge_nudge,
)
from ..shape import Shape
from ..shape_identity import (
    MISSING_SHAPE_ID,
    describe_shape_identity_diagnostics,
    normalize_shape_identities,
)
from .appearance import (
    AppearanceSettings,
    ColorMode,
    GroupFocusController,
    IsolationState,
    ShapeVisualContext,
    VisualStyle,
    resolve_base_color,
    derive_isolation_state,
    resolve_render_decision,
)
from .rectangle_size_overlay import (
    RectangleSizeOverlayRenderer,
    RectangleSizeOverlayRequest,
    map_rect_tuple as _map_rect_tuple,
    merge_overlay_requests,
    overlay_request_from_issue,
)
from .selection.geometry import (
    normalize_selection_rect,
    shapes_intersecting_rect,
)
from .selection.gesture import SelectionGesture
from .selection.policy import add_shapes, toggle_shape
from .selection.rubber_band_renderer import RubberBandRenderer

PERF_LOG_ENABLED = os.getenv("XANYLABELING_PERF_LOG") == "1"

# Person small-target fallback threshold (image-pixel space).
# The authoritative value lives in
# ``configs/quality/l1_l2_threshold_profile_v0.yaml`` under
# ``person_small_target.min_edge_px``; this constant is only a fallback used
# when the profile cannot be loaded, so that canvas stays unit-testable
# without a YAML dependency. See
# ``docs/小目标Person矩形实时尺寸显示功能设计.md``.
DEFAULT_PERSON_SMALL_TARGET_MIN_EDGE_PX = 36.0


def _safe_positive_int(value: object, fallback: int) -> int:
    """Return a positive integer setting or a safe fallback."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(1, number)


def validate_shape_references(
    shapes: Iterable[Shape],
    *,
    replace: bool,
    existing_shapes: Iterable[Shape] = (),
) -> list[Shape]:
    """Materialize and validate live object identities before shape loading.

    Args:
        shapes: Incoming Shape objects in requested Canvas order.
        replace: Whether the incoming snapshot replaces current membership.
        existing_shapes: Current Canvas objects reserved during append.

    Returns:
        The materialized incoming Shape list.

    Raises:
        ValueError: If the incoming list repeats an object, or an append
            contains an object already owned by the current Canvas.
    """
    incoming = list(shapes)
    incoming_identities: set[int] = set()
    for shape in incoming:
        identity = id(shape)
        if identity in incoming_identities:
            raise ValueError(
                "Incoming shape snapshot contains duplicate objects"
            )
        incoming_identities.add(identity)

    if not replace:
        existing_identities = {id(shape) for shape in existing_shapes}
        if incoming_identities.intersection(existing_identities):
            raise ValueError(
                "Incoming shape object is already owned by the current Canvas"
            )
    return incoming


# ---------------------------------------------------------------------------
# Size-overlay pure helpers (no QPainter dependency -> unit-testable)
# ---------------------------------------------------------------------------
# All size/threshold/anchor logic lives here so the drawing method only has
# to translate results into QPainter calls. Geometry is in image-pixel space
# (never screen pixels, never scaled by Shape.scale), matching the design
# contract in ``docs/小目标Person矩形实时尺寸显示功能设计.md`` section 2.


def normalize_two_points(p0, p1):
    """Return ``(x_min, y_min, x_max, y_max)`` for two corner points.

    Works for any drag direction (forward / reverse) and float coordinates,
    matching the rectangle-creation geometry in ``mouseMoveEvent`` where the
    in-progress rectangle is the pair ``(self.current[0], cursor)``.

    Args:
        p0: First point; must expose ``.x()`` and ``.y()``.
        p1: Second point; must expose ``.x()`` and ``.y()``.

    Returns:
        A 4-tuple of floats ``(x_min, y_min, x_max, y_max)``.
    """
    x_min = min(p0.x(), p1.x())
    x_max = max(p0.x(), p1.x())
    y_min = min(p0.y(), p1.y())
    y_max = max(p0.y(), p1.y())
    return (x_min, y_min, x_max, y_max)


def size_from_bbox(x_min, y_min, x_max, y_max):
    """Return raw float ``(width, height, max_edge)`` of a bbox.

    Threshold comparison MUST use these raw floats, never rounded or
    formatted values (e.g. 35.96 is still < 36 even if it shows as "36").

    Args:
        x_min, y_min, x_max, y_max: Normalized bounding box in image px.

    Returns:
        ``(width, height, max_edge)`` where ``max_edge = max(width, height)``.
    """
    width = abs(x_max - x_min)
    height = abs(y_max - y_min)
    return (width, height, max(width, height))


def is_person_small_target(label, max_edge, threshold):
    """Return whether a person rectangle is below the small-target bar.

    Only ``person`` rectangles can be "small"; any other label is always
    neutral. The comparison is strict (``<``), so a value exactly on the
    threshold (e.g. 36.0 vs 36.0) passes without warning.

    Args:
        label: The shape label string (or None during creation).
        max_edge: ``max(width, height)`` as a raw float in image px.
        threshold: The ``min_edge_px`` threshold in image px.

    Returns:
        True iff the label is ``person`` and ``max_edge < threshold``.
    """
    if label != "person":
        return False
    try:
        return float(max_edge) < float(threshold)
    except (TypeError, ValueError):
        return False


def _perf_log(message, *args):
    """Emit performance logs only when enabled by env var."""
    if PERF_LOG_ENABLED:
        logger.info(message, *args)


def _state_property(state_name: str, attribute_name: str) -> property:
    """Create a temporary compatibility property for nested UI state."""

    def getter(instance):
        """Read a value from the nested state object."""
        return getattr(getattr(instance, state_name), attribute_name)

    def setter(instance, value):
        """Write a value to the nested state object."""
        setattr(getattr(instance, state_name), attribute_name, value)

    return property(getter, setter)


CURSOR_DEFAULT = QtCore.Qt.CursorShape.ArrowCursor
CURSOR_POINT = QtCore.Qt.CursorShape.PointingHandCursor
CURSOR_DRAW = QtCore.Qt.CursorShape.CrossCursor
CURSOR_MOVE = QtCore.Qt.CursorShape.ClosedHandCursor
CURSOR_GRAB = QtCore.Qt.CursorShape.OpenHandCursor
CURSOR_SIZE_ALL = QtCore.Qt.CursorShape.SizeAllCursor
CURSOR_SIZE_HOR = QtCore.Qt.CursorShape.SizeHorCursor
CURSOR_SIZE_VER = QtCore.Qt.CursorShape.SizeVerCursor
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
    shape_edit_started = QtCore.pyqtSignal(str)
    shape_edit_finished = QtCore.pyqtSignal(str, bool)
    shape_rotated = QtCore.pyqtSignal()
    shape_changed = QtCore.pyqtSignal(object)
    shapes_changed = QtCore.pyqtSignal(tuple)
    input_burst_requested = QtCore.pyqtSignal(str, str)
    semantic_burst_requested = QtCore.pyqtSignal(
        str, object, str, str, object, object
    )
    rectangle_review_edge_drag_started = QtCore.pyqtSignal(str)
    rectangle_review_edge_drag_delta = QtCore.pyqtSignal(float)
    rectangle_review_edge_drag_finished = QtCore.pyqtSignal(bool)
    rectangle_review_feedback_changed = QtCore.pyqtSignal(object)
    rectangle_review_candidate_changed = QtCore.pyqtSignal(object)
    drawing_polygon = QtCore.pyqtSignal(bool)
    drawing_canceled = QtCore.pyqtSignal()
    vertex_selected = QtCore.pyqtSignal(bool)
    auto_labeling_marks_updated = QtCore.pyqtSignal(list)
    auto_decode_requested = QtCore.pyqtSignal(list)
    auto_decode_finish_requested = QtCore.pyqtSignal()
    shape_hover_changed = QtCore.pyqtSignal()
    split_position_changed = QtCore.pyqtSignal(float)
    edit_label_requested = QtCore.pyqtSignal()
    pose_occlusion_count_changed = QtCore.pyqtSignal(int)
    escape_pressed = QtCore.pyqtSignal()
    # Cross-image object marking: emitted only for a plain click on one
    # shape; the session store (outside the canvas) owns the mark set.
    batch_mark_toggle_requested = QtCore.pyqtSignal(object)

    CREATE, EDIT = 0, 1

    # polygon, rectangle, rotation, line, or point
    _create_mode = "polygon"

    _fill_drawing = False

    # Compatibility names keep integrations stable while all transient
    # values are owned by two explicit state objects.
    rect_edge_hover_edge = _state_property("rect_edge_state", "hover_edge")
    rect_edge_active_edge = _state_property("rect_edge_state", "active_edge")
    rect_edge_drag_start_points = _state_property(
        "rect_edge_state", "drag_start_points"
    )
    rect_edge_pending_edge = _state_property("rect_edge_state", "pending_edge")
    rect_edge_pending_press_pos = _state_property(
        "rect_edge_state", "pending_press_pos"
    )
    rect_edge_pending_image_pos = _state_property(
        "rect_edge_state", "pending_image_pos"
    )

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
        self._selected_shapes_source = "none"
        self.selected_shapes_copy = []
        self._selection_gesture = SelectionGesture()
        self._selection_box_rect = None
        self._selection_box_preview = []
        self._rubber_band_renderer = RubberBandRenderer()
        # Cross-image object marking gesture state. The canvas only
        # recognizes the gesture and paints the current image overlay;
        # the cross-image mark set lives in the labeling widget session.
        self.batch_mark_mode = False
        self.marked_shape_ids: set[str] = set()
        self._batch_mark_press = None
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
        # Optional focus layer composed with the existing base visibility.
        # ``_main_visibility_predicate`` is an optional Callable[[Shape], bool]
        # consulted by ``main_visible``. None means no focus filter.
        self._main_visibility_predicate = None
        # Temporary virtual-review focus. Unlike ``hidden_by_filter`` this is
        # a session-only layer and must never change base visibility state.
        self._virtual_review_visibility_predicate = None
        self.appearance_settings = AppearanceSettings()
        self.appearance_label_colors = {}
        self.appearance_image_token = ""
        self.group_focus_controller = GroupFocusController()
        self._appearance_base_color_cache = {}
        self._isolation_enabled = False
        self._isolation_group_id = None
        self._isolation_shape_tokens = ()
        self._isolation_state = IsolationState()
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
        self._size_overlay_hover_shape = None
        self.moving_shape = False
        self._behavior_edit_target = None
        self._pending_edge_point = None
        self.rotating_shape = False
        self.snapping = True
        self.h_shape_is_selected = False
        self._pressed_ctrl_selection = False
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
        # Independent toggle for the rectangle pixel-size overlay (design
        # rev.1 §5). Mirrors show_labels' wiring: View menu checkable action
        # -> set_canvas_params -> canvas.update(). Defaults to True.
        self.show_rectangle_pixels = True
        self.show_rectangle_size_violations = False
        self._rectangle_size_overlay_renderer = RectangleSizeOverlayRenderer()
        self._rectangle_size_issues: tuple[RectangleSizeIssue, ...] = ()
        self._rectangle_size_issue_shapes: dict[object, Shape] = {}
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
        self._crosshair_cursor_active = False

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

        # Selected-rectangle single-edge adjustment (see rect_edge_alignment.py).
        # All of these are purely transient in-memory state; none of them is
        # persisted to JSON. The active edge is an in-memory ``RectEdgeRef``
        # that is never written into ``Shape.other_data``.
        self.rect_edge_align_enabled = False
        self.rect_edge_state = RectEdgeInteractionController()
        # A selected rectangle edge becomes pending on press and is promoted
        # to an edit target after a screen-space drag threshold.

        # Person small-target overlay threshold (image px). Read-only during
        # paint; injected by label_widget from the quality profile YAML at
        # startup. The overlay is pure transient drawing state (never enters
        # Shape data, the undo stack, dirty flag, or JSON).
        self.person_small_target_min_edge = (
            DEFAULT_PERSON_SMALL_TARGET_MIN_EDGE_PX
        )

        # Precision drag mode (Feature 3). When active, mouse drag deltas
        # are scaled by 1/precision_factor using a virtual cursor that is
        # kept SEPARATE from self.prev_point (move_by_keyboard and press
        # resets depend on prev_point being the real cursor — D4).
        self.precision_mode_locked = False
        self._virtual_prev_point = None
        self._precision_raw_prev_point = None

        # Low-fatigue rectangle review refinement. These values are inert
        # until the explicit rollout flag is enabled by settings.
        self.rectangle_review_refinement_enabled = False
        self.rectangle_review_target_gain = DEFAULT_TARGET_GAIN
        self.rectangle_review_edge_precision_default = True
        self.rectangle_review_migration_needed = False
        self.rectangle_review_nudge_step_px = 1
        self.rectangle_review_coarse_step_px = 5
        self.rectangle_review_feedback_enabled = True
        self.rectangle_review_persist_across_images = True
        self.rectangle_review_loupe_enabled = False
        self.rectangle_review_candidate_enabled = False
        self.rectangle_review_telemetry_enabled = False
        self.rectangle_review_telemetry_config = {}
        self._rectangle_review_wheel = WheelAccumulator()
        self._rectangle_review_nudge_burst = NudgeBurstTracker()
        self._rectangle_review_candidate_service = EdgeCandidateService()
        self._rectangle_review_candidate_preview = CandidatePreviewController()
        self.rectangle_review_feedback_snapshot: (
            ReviewFeedbackSnapshot | None
        ) = None

    @property
    def rect_edge_dragging(self) -> bool:
        """Return whether rectangle-edge state is in dragging phase."""
        return self.rect_edge_state.is_dragging

    @rect_edge_dragging.setter
    def rect_edge_dragging(self, value: bool) -> None:
        """Support legacy state setup while deriving the real phase."""
        if not value:
            self.rect_edge_state.active_edge = None
            self.rect_edge_state.drag_start_points = None

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

    def store_shapes(self):
        """Store shapes for restoring later (Undo feature)."""
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
        self.shapes_backups.append(shapes_backup)

    def store_moving_shape(self):
        """Store a moving shape"""
        if getattr(self, "_keyboard_edit_before", None) is not None:
            self._finish_keyboard_edit()
            return
        if self.moving_shape:
            changed = False
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
                        changed = True
                        break
            if self._behavior_edit_target is not None:
                self.shape_edit_finished.emit(
                    self._behavior_edit_target, changed
                )
                self._behavior_edit_target = None
            self.moving_shape = False
        elif self._behavior_edit_target is not None:
            self.shape_edit_finished.emit(self._behavior_edit_target, False)
            self._behavior_edit_target = None

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
        self._set_selected_shapes([], source="none")
        self._reset_rectangle_size_issue_state()
        self.notify_shapes_changed()
        self.update()

    def enterEvent(self, _):
        """Mouse enter event"""
        self.override_cursor(self._cursor)

    def leaveEvent(self, _):
        """Mouse leave event"""
        self._clear_crosshair_cursor()
        self.store_moving_shape()
        self.un_highlight()
        self.restore_cursor()
        self.shape_hover_changed.emit()

    def focusOutEvent(self, _):
        """Window out of focus event"""
        if getattr(self, "_keyboard_edit_before", None) is not None:
            self._finish_keyboard_edit()
        self._cancel_rect_edge_interaction()
        self.restore_cursor()

    def is_visible(self, shape):
        """Check if a shape is visible (canvas-level dict only).

        Note: this is the *base-layer* canvas dict accessor.  For the unified
        main-canvas effective visibility (used by paint + interaction gates)
        use :meth:`main_visible`; for the navigator/restore base layer use
        :meth:`base_visible`.
        """
        return self.visible.get(shape, True)

    def base_visible(self, shape) -> bool:
        """User base-layer visibility (navigator + restore semantics).

        Combines the canvas dict, the per-shape ``visible`` flag and the
        filter ``hidden_by_filter`` flag.
        """
        return (
            self.visible.get(shape, True)
            and getattr(shape, "visible", True)
            and not getattr(shape, "hidden_by_filter", False)
        )

    def main_visible(self, shape) -> bool:
        """Return base visibility composed with the optional focus predicate.

        When no predicate is installed this is identical to
        :meth:`base_visible`. On predicate error the method fails closed.
        """
        if not self.base_visible(shape):
            return False
        predicate = self._main_visibility_predicate
        if predicate is not None:
            try:
                if not bool(predicate(shape)):
                    return False
            except Exception:  # noqa: BLE001 - fail closed
                return False
        predicate = self._virtual_review_visibility_predicate
        if predicate is not None:
            try:
                if not bool(predicate(shape)):
                    return False
            except Exception:  # noqa: BLE001 - fail closed
                return False
        if self._isolation_enabled and not self._isolation_allows(shape):
            return False
        return True

    def _virtual_review_context_visible(self, shape) -> bool:
        """Return whether a shape belongs to the dim virtual context pass."""
        if not self.base_visible(shape):
            return False
        if self._isolation_enabled and not self._isolation_allows(shape):
            return False
        predicate = self._main_visibility_predicate
        if predicate is not None:
            try:
                if not bool(predicate(shape)):
                    return False
            except Exception:  # noqa: BLE001 - fail closed
                return False
        predicate = self._virtual_review_visibility_predicate
        if predicate is None:
            return False
        try:
            return not bool(predicate(shape))
        except Exception:  # noqa: BLE001 - fail closed
            return False

    def iter_main_visible_shapes(self):
        """Yield Shapes visible through the composed main-canvas filter."""
        for shape in self.shapes:
            if self.main_visible(shape):
                yield shape

    def set_main_visibility_predicate(self, predicate) -> None:
        """Install the optional main-canvas focus predicate.

        ``predicate(shape) -> bool``; pass ``None`` to clear.  Triggers a
        repaint so the main canvas reflects the new layer immediately.
        """
        self._main_visibility_predicate = predicate
        self.notify_shapes_changed()
        self.update()

    def clear_main_visibility_predicate(self) -> None:
        self.set_main_visibility_predicate(None)

    def set_virtual_review_visibility_predicate(self, predicate) -> None:
        """Install a repaint-only virtual review focus predicate.

        The predicate is deliberately separate from the base visibility and
        existing three-box focus layers. Installing it never publishes a
        shape-change notification, because changing review pages is not a
        geometry or data mutation.
        """
        self._virtual_review_visibility_predicate = predicate
        self.update()

    def clear_virtual_review_visibility_predicate(self) -> None:
        """Clear the temporary virtual review focus layer."""
        self.set_virtual_review_visibility_predicate(None)

    def is_shape_interactive(self, shape: Shape) -> bool:
        """Return whether a shape can be hovered, selected, or edited.

        Routes through :meth:`main_visible` so focus gates every interaction
        path in one place.
        """
        return self.main_visible(shape)

    def notify_shape_changed(self, shape: Shape) -> None:
        """Publish an advisory incremental change for one current shape.

        This method does not mutate the shape, create an undo snapshot, mark
        annotation data dirty, or schedule a repaint. External shape editors
        should call it after committing an in-place geometry or metadata
        change.

        Args:
            shape: Live shape reference that may belong to this canvas.
        """
        if any(current is shape for current in self.shapes):
            self.shape_changed.emit(shape)

    def notify_shapes_changed(self) -> None:
        """Publish an immutable full snapshot for general observers.

        The full notification is used when membership, order, shape
        references, or a canvas-wide visibility policy changes.
        """
        self.shapes_changed.emit(tuple(self.shapes))

    def _set_size_overlay_hover_shape(self, shape) -> None:
        """Set the rectangle currently hovered by the real canvas pointer."""
        if (
            shape is None
            or shape not in self.shapes
            or shape.shape_type != "rectangle"
            or not self.is_shape_interactive(shape)
        ):
            shape = None
        if self._size_overlay_hover_shape is shape:
            return
        self._size_overlay_hover_shape = shape
        self.update()

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

    def _standard_label_font(self):
        """Return the font used by the standard label paint pass."""
        return QtGui.QFont(
            "Arial", int(max(6.0, int(round(8.0 / Shape.scale))))
        )

    def _standard_label_hovered_shape(self):
        """Return the shape treated as hovered by the label paint pass."""
        hovered_shape = self.h_hape
        mp = self.prev_move_point
        if hovered_shape is None:
            for shape in self.shapes:
                if (
                    shape.shape_type == "point"
                    and shape.points
                    and self.is_shape_interactive(shape)
                ):
                    if (
                        math.hypot(
                            mp.x() - shape.points[0].x(),
                            mp.y() - shape.points[0].y(),
                        )
                        * self.scale
                        <= 10
                    ):
                        hovered_shape = shape
                        break
        return hovered_shape

    def _is_standard_label_visible(self, shape, hovered_shape=None):
        """Return whether the standard label is visible for ``shape``."""
        if not self._should_draw_standard_label(shape):
            return False
        if not self.main_visible(shape):
            return False
        if self.label_on_selection:
            if hovered_shape is None:
                hovered_shape = self._standard_label_hovered_shape()
            if not (shape.selected or shape == hovered_shape):
                return False
        return True

    def _selection_drag_threshold(self) -> float:
        """Return the current image-space Ctrl-drag threshold."""
        return max(
            2.0,
            float(QtWidgets.QApplication.startDragDistance())
            / max(float(self.scale), 1e-6),
        )

    def _clear_selection_gesture(self) -> None:
        """Clear transient Ctrl-selection state and repaint if needed."""
        was_visible = self._selection_box_rect is not None
        self._selection_gesture.reset()
        self._selection_box_rect = None
        self._selection_box_preview = []
        self._pressed_ctrl_selection = False
        if was_visible:
            self.update()

    def _finish_selection_gesture(self) -> bool:
        """Commit or cancel a pending Ctrl-selection gesture on release."""
        if not self._selection_gesture.active:
            return False
        if self._selection_gesture.rubber_band:
            selected = add_shapes(
                self.selected_shapes, self._selection_box_preview
            )
            self._set_selected_shapes(selected, source="canvas")
        self._clear_selection_gesture()
        self.update()
        return True

    def _standard_label_text_for_shape(self, shape):
        """Return the standard label text, independent of visibility gates."""
        if shape.label in [
            "AUTOLABEL_OBJECT",
            "AUTOLABEL_ADD",
            "AUTOLABEL_REMOVE",
        ]:
            return None
        if not self.show_labels or not self.appearance_settings.show_labels:
            return None
        display_mode = self.label_display_mode
        if display_mode == "none":
            return None
        elif display_mode == "label":
            label_text = shape.label
        elif display_mode == "id":
            label_text = (
                str(shape.group_id) if shape.group_id is not None else ""
            )
        elif display_mode == "both":
            if shape.group_id is not None:
                label_text = f"{shape.label} #{shape.group_id}"
            else:
                label_text = shape.label
        else:
            label_text = shape.label
        if not label_text:
            return None
        if (
            self.appearance_settings.show_gid != "never"
            and isinstance(shape.group_id, int)
            and not isinstance(shape.group_id, bool)
            and (
                self.appearance_settings.show_gid == "always"
                or self.group_focus_controller.state.active
            )
            and f"#{shape.group_id}" not in label_text
        ):
            label_text = f"{label_text} #{shape.group_id}"
        if shape.score is not None and self.show_scores:
            label_text += f" {float(shape.score):.2f}"
        if shape.shape_type == "rectangle":
            extra_texts = []
            if self.show_texts and shape.description:
                extra_texts.append(str(shape.description))
            if self.show_attributes and getattr(shape, "attributes", None):
                extra_texts.extend(
                    f"{key}: {value}"
                    for key, value in shape.attributes.items()
                )
            if extra_texts:
                label_text = " | ".join([label_text] + extra_texts)
        return label_text or None

    def _rectangle_label_rect_for_shape(self, shape, label_text, fm):
        """Return the exact rectangle-label background rect."""
        if (
            self.pixmap is None
            or not label_text
            or shape.shape_type != "rectangle"
        ):
            return None
        padding_x = 4
        padding_y = 2
        rect_width = fm.tightBoundingRect(label_text).width() + 2 * padding_x
        rect_height = fm.height() + 2 * padding_y
        try:
            bbox = shape.bounding_rect()
        except IndexError:
            return None

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

        return QtCore.QRect(rect_x, rect_y, rect_width, rect_height)

    def _standard_label_layout_for_shape(self, shape, label_text, fm):
        """Return ``(background_rect, text_pos)`` for standard labels."""
        padding_x = 4
        padding_y = 2
        text_rect = fm.tightBoundingRect(label_text)
        rect_width = text_rect.width() + 2 * padding_x
        rect_height = fm.height() + 2 * padding_y

        if shape.shape_type == "rectangle":
            rect = self._rectangle_label_rect_for_shape(shape, label_text, fm)
            if rect is None:
                return None
            text_pos = QtCore.QPoint(
                rect.x() + padding_x,
                rect.y() + rect.height() - padding_y - fm.descent(),
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
                return None
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
                return None
            point = points[0]
            rect = QtCore.QRect(
                int(point.x() - rect_width / 2),
                int(point.y() - rect_height / 2),
                rect_width,
                rect_height,
            )
            text_pos = QtCore.QPoint(
                int(point.x() - rect_width / 2 + padding_x),
                int(point.y() + rect_height / 2 - padding_y - fm.descent()),
            )
        elif shape.shape_type in [
            "line",
            "linestrip",
            "point",
        ]:
            points = shape.points
            if not points:
                return None
            point = points[0]
            d_react = shape.point_size / shape.scale
            rect = QtCore.QRect(
                int(point.x() + d_react),
                int(point.y() - 15),
                rect_width,
                rect_height,
            )
            text_pos = QtCore.QPoint(
                int(point.x() + d_react + padding_x),
                int(point.y() - 15 + rect_height - padding_y - fm.descent()),
            )
        else:
            return None
        return (rect, text_pos)

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
            self.is_move_editing = False
            self.shape_hover_changed.emit()

    def un_highlight(self):
        """Unhighlight shape/vertex/edge"""
        self._set_size_overlay_hover_shape(None)
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

    def _should_defer_drag_overlays(self):
        """Return whether live dragging should use lighter painting."""
        if self.rect_edge_dragging:
            return True
        return self.moving_shape and bool(self.selected_shapes)

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

    def _point_in_pixmap(self, pos: QtCore.QPointF) -> bool:
        """Return whether an image-space point is inside the current pixmap."""
        return (
            self.pixmap is not None
            and not self.pixmap.isNull()
            and 0.0 <= pos.x() < self.pixmap.width()
            and 0.0 <= pos.y() < self.pixmap.height()
        )

    def _update_crosshair_cursor(self, pos: QtCore.QPointF) -> None:
        """Store the cursor position and schedule a crosshair repaint."""
        previous_pos = self.prev_move_point
        was_active = self._crosshair_cursor_active
        is_active = self._point_in_pixmap(pos)

        self.prev_move_point = pos
        self._crosshair_cursor_active = is_active

        cursor_changed = previous_pos != pos or was_active != is_active
        if (
            self.cross_line_show
            and cursor_changed
            and (was_active or is_active)
        ):
            self.update()

    def _clear_crosshair_cursor(self) -> None:
        """Hide the crosshair and repaint when it was previously visible."""
        was_active = self._crosshair_cursor_active
        self._crosshair_cursor_active = False
        if self.cross_line_show and was_active:
            self.update()

    # QT Overload
    def mouseMoveEvent(self, ev):  # noqa: C901
        """Update line with last point and current coordinates"""
        if self.is_loading:
            return
        try:
            pos = self.transform_pos(ev.position())
        except AttributeError:
            return

        if self._selection_gesture.active:
            if self._selection_gesture.update(
                pos, self._selection_drag_threshold()
            ):
                self._selection_box_rect = normalize_selection_rect(
                    self._selection_gesture.origin, pos
                )
                self._selection_box_preview = shapes_intersecting_rect(
                    self.shapes,
                    self._selection_box_rect,
                    self.is_shape_interactive,
                    tolerance=max(1.0, 2.0 / max(self.scale, 1e-6)),
                )
            self.update()
            return

        prev_hover_shape = self.h_hape
        self._update_crosshair_cursor(pos)

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

            if self.create_mode == "rectangle":
                self._emit_show_shape_from_points(self.current[0], pos, pos)
            elif self.create_mode == "cuboid":
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
                if self.bounded_move_shapes(self.selected_shapes_copy, eff):
                    self.update()
            elif self.selected_shapes:
                self.selected_shapes_copy = self._normalize_incoming_shape_ids(
                    [s.copy_for_new_object() for s in self.selected_shapes],
                    replace=False,
                )
                self.update()
            return

        # A press on the current selected rectangle edge is initially pending.
        # The first non-zero screen-space movement starts the edge drag
        # directly; formal object selection remains owned by the normal
        # selection path.
        if (
            QtCore.Qt.MouseButton.LeftButton & ev.buttons()
            and self.rect_edge_pending_edge is not None
        ):
            pending = self.rect_edge_pending_edge
            if not self._rect_edge_pending_is_valid():
                self._clear_rect_edge_pending()
                self.rect_edge_state.set_hover(None)
                self.update()
                return
            if not self._rect_edge_pending_has_moved(ev.position()):
                self.override_cursor(self._rect_edge_cursor(pending))
                return

            press_pos = QtCore.QPointF(self.rect_edge_pending_image_pos)
            self._start_rect_edge_drag(pending, press_pos)
            eff = self._effective_drag_pos(pos, ev)
            self._rect_edge_drag_update(eff)
            self.override_cursor(self._rect_edge_cursor(pending))
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
            if not (QtCore.Qt.MouseButton.LeftButton & ev.buttons()):
                self.cancel_rect_edge_drag()
                return
            eff = self._effective_drag_pos(pos, ev)
            self._rect_edge_drag_update(eff)
            self.override_cursor(
                self._rect_edge_cursor(self.rect_edge_active_edge)
            )
            return

        # Polygon/Vertex moving.
        if QtCore.Qt.MouseButton.LeftButton & ev.buttons():
            if self.selected_vertex():
                self.h_cuboid_face = None
                self.is_move_editing = False
                try:
                    eff = self._effective_drag_pos(pos, ev)
                    self.bounded_move_vertex(eff)
                    self.moving_shape = True
                    self.repaint()
                except IndexError:
                    return
                if self.h_hape.shape_type == "rectangle":
                    self._emit_show_shape_from_shape(self.h_hape, pos)
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
                self.moving_shape = True
                self.repaint()
                p1 = self.h_hape[0]
                p2 = self.h_hape[2]
                shape_width = int(abs(p2.x() - p1.x()))
                shape_height = int(abs(p2.y() - p1.y()))
                self.show_shape.emit(shape_height, shape_width, pos)
            elif self.selected_shapes and self.prev_point:
                self.h_cuboid_face = None
                self.override_cursor(CURSOR_MOVE)
                eff = self._effective_drag_pos(pos, ev)
                if not self.bounded_move_shapes(self.selected_shapes, eff):
                    return
                self.update()
                self.moving_shape = True
                if self.selected_shapes[-1].shape_type == "rectangle":
                    self._emit_show_shape_from_shape(
                        self.selected_shapes[-1], pos
                    )
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
                    self.moving_shape = True
                    self.repaint()
                except IndexError:
                    return
                if self.h_hape.shape_type == "rectangle":
                    self._emit_show_shape_from_shape(self.h_hape, pos)
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
                self.moving_shape = True
                self.repaint()
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
                hover_changed = (candidate is None) != (
                    prev_hover is None
                ) or (
                    candidate is not None
                    and prev_hover is not None
                    and (
                        candidate.shape is not prev_hover.shape
                        or candidate.edge_name != prev_hover.edge_name
                    )
                )
                self.rect_edge_state.set_hover(candidate)
                if hover_changed:
                    self.update()
                # Still fall through to the normal hover loop below so that
                # vertex hover keeps working when no edge is hovered.
                if candidate is not None:
                    # Edge hovered: clear any stale shape/vertex/edge/cuboid
                    # hover state left over from a previous frame so the old
                    # highlight does not bleed through, then suppress the
                    # default hover loop (which would draw a whole-shape
                    # fill and clobber the edge highlight).
                    self.un_highlight()
                    self._set_size_overlay_hover_shape(candidate.shape)
                    self.show_shape.emit(-1, -1, pos)
                    self.override_cursor(self._rect_edge_cursor(candidate))
                    return

        self.show_shape.emit(-1, -1, pos)
        self._set_size_overlay_hover_shape(None)

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
                self._set_size_overlay_hover_shape(shape)
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
                self._set_size_overlay_hover_shape(shape)
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
                self._set_size_overlay_hover_shape(shape)
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
                if self.h_shape_is_hovered and not (
                    ev.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier
                ):
                    group_mode = False
                    self.select_shape_point(
                        pos, multiple_selection_mode=group_mode
                    )
                self.update()

                if shape.shape_type == "rectangle":
                    self._emit_show_shape_from_shape(self.h_hape, pos)
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

        pos = self.transform_pos(ev.position())
        # Reset the precision-mode virtual cursor at every press so the
        # first drag delta is computed from the real press position.
        self._reset_virtual_cursor()

        if ev.button() == QtCore.Qt.MouseButton.LeftButton:
            self._pressed_ctrl_selection = bool(
                ev.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier
            )
            # ----------------------------------------------------------
            # Rectangle edge editing.
            # Revalidate at press time so a stale hover reference cannot
            # target a removed, hidden or deselected shape. A valid edge press
            # keeps the current rectangle formally selected.
            # ----------------------------------------------------------
            hover = self._rect_edge_press_candidate(pos)
            self.rect_edge_state.set_hover(hover)
            if hover is not None:
                if self.rect_edge_active_edge is not None:
                    self.rectangle_review_edge_drag_finished.emit(False)
                    self.clear_rect_edge_alignment()
                    self.rect_edge_state.set_hover(hover)
                self.prev_point = pos
                self.prev_pan_point = ev.position()
                self.rect_edge_state.begin_pending(hover, ev.position(), pos)
                self.override_cursor(self._rect_edge_cursor(hover))
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
                if ev.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier:
                    if not self._shape_hit_candidates(pos):
                        self._selection_gesture.begin(pos)
                        self._selection_box_rect = QtCore.QRectF(pos, pos)
                        self._selection_box_preview = []
                        self.prev_point = pos
                        self.prev_pan_point = ev.position()
                        self.update()
                        return
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

                group_mode = bool(
                    ev.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier
                )
                if getattr(self, "_pending_initial_backup", False):
                    self.store_shapes()
                if self.selected_vertex():
                    self._behavior_edit_target = "vertex"
                elif self.selected_edge():
                    self._behavior_edit_target = "edge"
                elif self.selected_shapes:
                    self._behavior_edit_target = "move"
                if self._behavior_edit_target is not None:
                    self.shape_edit_started.emit(self._behavior_edit_target)
                if self.batch_mark_mode:
                    self._batch_mark_press = self._batch_mark_capture_press(
                        pos
                    )
                else:
                    self._batch_mark_press = None
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
            group_mode = bool(
                ev.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier
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
    def mouseReleaseEvent(self, ev):  # noqa: C901
        """Mouse release event"""
        if self.is_loading:
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
            if self._finish_selection_gesture():
                return
            # ----------------------------------------------------------
            # Rectangle edge editing: commit on release.
            # One release forms exactly one undo granularity and only
            # stores/emits when the geometry actually changed.
            # ----------------------------------------------------------
            if self.rect_edge_dragging:
                active = self.rect_edge_active_edge
                start_points = self.rect_edge_drag_start_points
                release_pos = self.transform_pos(ev.position())
                confirmed = self._rect_edge_specific_hit(active, release_pos)
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
                if active is not None:
                    original_coord = (
                        self.rectangle_review_feedback_snapshot.original_coord
                        if self.rectangle_review_feedback_snapshot is not None
                        else active.coord
                    )
                    self._set_rectangle_review_feedback(
                        active,
                        "committed" if changed else "canceled",
                        original_coord,
                    )
                self.rectangle_review_edge_drag_finished.emit(changed)
                self.clear_rect_edge_alignment()
                hover = (
                    confirmed[0]
                    if confirmed is not None
                    else self._rect_edge_hit_candidate(release_pos)
                )
                self.rect_edge_state.set_hover(hover)
                if self.rect_edge_hover_edge is not None:
                    self.override_cursor(
                        self._rect_edge_cursor(self.rect_edge_hover_edge)
                    )
                else:
                    self.override_cursor(CURSOR_DEFAULT)
                self.update()
                return
            if self.rect_edge_pending_edge is not None:
                pending = self.rect_edge_pending_edge
                valid = self._rect_edge_pending_is_valid()
                release_pos = self.transform_pos(ev.position())
                moved = self._rect_edge_pending_has_moved(ev.position())
                confirmed = (
                    self._rect_edge_specific_hit(pending, release_pos)
                    if valid
                    else None
                )
                self._clear_rect_edge_pending()
                if confirmed is not None:
                    hover = confirmed[0]
                    if not moved and self.rectangle_review_refinement_enabled:
                        self._activate_rect_edge_for_nudge(hover)
                else:
                    hover = self._rect_edge_hit_candidate(release_pos)
                self.rect_edge_state.set_hover(hover)
                if self.rect_edge_hover_edge is not None:
                    self.override_cursor(
                        self._rect_edge_cursor(self.rect_edge_hover_edge)
                    )
                else:
                    self.override_cursor(CURSOR_DEFAULT)
                self.update()
                return
            if self.editing():
                if (
                    self.h_hape is not None
                    and self.h_shape_is_selected
                    and not self.moving_shape
                    and self._pressed_ctrl_selection
                ):
                    # Ctrl-clicking an already selected object toggles it off.
                    self._set_selected_shapes(
                        toggle_shape(self.selected_shapes, self.h_hape)
                    )
                if self.batch_mark_mode:
                    self._emit_batch_mark_toggle_if_click(ev)

        self._pressed_ctrl_selection = False
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
        if copy:
            self.notify_shapes_changed()
        else:
            for shape in self.selected_shapes:
                self.notify_shape_changed(shape)
        # Emit so selection-derived views refresh: a copy replaced the
        # selected shape references, and a move changed points/bbox (the
        # stable preview should re-evaluate its target rect).
        self._set_selected_shapes(self.selected_shapes)
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
                    self._set_selected_shapes([shape])
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

    def select_shapes(self, shapes, source="canvas"):
        """Select some shapes"""
        self._set_selected_shapes(shapes, source=source)
        self.set_hiding()
        self.update()

    def _set_selected_shapes(self, shapes, source="canvas") -> None:
        """Commit formal selection before notifying observers.

        Canvas owns both the selected-shape list and each shape's visual
        flag. Slots connected to ``selection_changed`` are observers and
        therefore always see an already-consistent state.

        Args:
            shapes: Candidate shapes in desired selection order.
        """
        selected = []
        seen = set()
        for shape in shapes or []:
            identity = id(shape)
            if identity in seen or not self.base_visible(shape):
                continue
            if not self.is_shape_interactive(shape) and source not in {
                "label_list",
                "inspector",
            }:
                continue
            seen.add(identity)
            selected.append(shape)

        old_ids = tuple(id(shape) for shape in self.selected_shapes)
        new_ids = tuple(id(shape) for shape in selected)
        if old_ids != new_ids and hasattr(self, "rect_edge_state"):
            self._cancel_rect_edge_interaction()

        for shape in self.selected_shapes:
            shape.selected = False
        self.selected_shapes = selected
        self._selected_shapes_source = source if selected else "none"
        for shape in self.selected_shapes:
            shape.selected = True
        self.set_hiding(bool(selected))
        self.group_focus_controller.update(
            self.appearance_image_token,
            self.selected_shapes,
            self.appearance_settings.color_mode.value,
        )
        if self._isolation_enabled:
            self._refresh_isolation_target()

        self.selection_changed.emit(list(self.selected_shapes))

    def select_shape_point(self, point, multiple_selection_mode):
        """Select the first shape created which contains this point."""
        self._selected_shapes_source = "canvas"
        if self.selected_vertex():  # A vertex is marked for selection.
            index, shape = self.h_vertex, self.h_hape
            self.h_hape = shape
            if shape.shape_type == "cuboid":
                self.set_hiding()
                if shape not in self.selected_shapes:
                    if multiple_selection_mode:
                        self._set_selected_shapes(
                            self.selected_shapes + [shape]
                        )
                    else:
                        self._set_selected_shapes([shape])
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
                    self._set_selected_shapes(self.selected_shapes + [shape])
                else:
                    self._set_selected_shapes([shape])
                self.h_shape_is_selected = False
            else:
                # 重复点击已选中对象，取消选中
                self.h_shape_is_selected = True
            self.calculate_offsets(point)
            return
        elif self.selected_cuboid_face():
            # [修复] 处理立方体面选择
            shape = self.h_hape
            self.h_hape = shape
            self.set_hiding()
            if shape not in self.selected_shapes:
                if multiple_selection_mode:
                    self._set_selected_shapes(self.selected_shapes + [shape])
                else:
                    self._set_selected_shapes([shape])
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
                self.h_hape = shape
                self.set_hiding()
                if shape not in self.selected_shapes:
                    if multiple_selection_mode:
                        self._set_selected_shapes(
                            self.selected_shapes + [shape]
                        )
                    else:
                        self._set_selected_shapes([shape])
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
            self.notify_shape_changed(shape)
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
        self.notify_shape_changed(shape)

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
                self.notify_shape_changed(shape)
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
        self.notify_shape_changed(shape)
        return True

    def deselect_shape(self):
        """Deselect all shapes"""
        if self.selected_shapes:
            self.set_hiding(False)
            self._set_selected_shapes([])
            self.h_shape_is_selected = False
            self.h_cuboid_face = None
            self.update()

    def delete_selected(self):
        """Remove selected shapes"""
        deleted_shapes = []
        if self.selected_shapes:
            for shape in self.selected_shapes:
                self.shapes.remove(shape)
                deleted_shapes.append(shape)
            self.store_shapes()
            self._set_selected_shapes([])
            self.notify_shapes_changed()
            self.update()
        return deleted_shapes

    def delete_shape(self, shape):
        """Remove a specific shape"""
        was_selected = shape in self.selected_shapes
        remaining_selection = [
            selected
            for selected in self.selected_shapes
            if selected is not shape
        ]
        removed = shape in self.shapes
        if removed:
            self.shapes.remove(shape)
        self.store_shapes()
        if was_selected:
            self._set_selected_shapes(remaining_selection)
        if removed:
            self.notify_shapes_changed()
        self.update()

    def duplicate_selected_shapes(self):
        """Duplicate selected shapes"""
        if self.selected_shapes:
            self.selected_shapes_copy = self._normalize_incoming_shape_ids(
                [s.copy_for_new_object() for s in self.selected_shapes],
                replace=False,
            )
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
    def set_appearance_settings(self, settings: AppearanceSettings) -> None:
        """Apply display-only appearance settings and repaint once."""
        self.appearance_settings = settings
        if (
            settings.color_mode is not ColorMode.FOCUS
            and self._isolation_enabled
        ):
            self._isolation_enabled = False
            self._isolation_group_id = None
            self._isolation_shape_tokens = ()
            self._isolation_state = IsolationState(
                image_token=self.appearance_image_token
            )
        self._appearance_base_color_cache.clear()
        self.group_focus_controller.update(
            self.appearance_image_token,
            self.selected_shapes,
            settings.color_mode.value,
        )
        self.update()

    def set_appearance_label_colors(self, label_colors: Mapping) -> None:
        """Replace the project palette used by label appearance resolution."""
        self.appearance_label_colors = dict(label_colors)
        self._appearance_base_color_cache.clear()
        self.update()

    def set_appearance_image_token(self, image_token: str) -> None:
        """Reset transient group focus when the displayed image changes."""
        self.appearance_image_token = str(image_token)
        self.group_focus_controller.reset_image(self.appearance_image_token)
        self._isolation_enabled = False
        self._isolation_group_id = None
        self._isolation_shape_tokens = ()
        self._isolation_state = IsolationState(
            image_token=self.appearance_image_token
        )
        self.update()

    @property
    def isolation_enabled(self) -> bool:
        """Return whether transient selection isolation is active."""
        return self._isolation_enabled

    def _refresh_isolation_target(self) -> None:
        """Derive the transient isolation target from formal selection."""
        self._isolation_state = derive_isolation_state(
            self.appearance_image_token,
            self.selected_shapes,
            enabled=self._isolation_enabled,
        )
        self._isolation_enabled = self._isolation_state.enabled
        self._isolation_group_id = self._isolation_state.focused_group_id
        self._isolation_shape_tokens = (
            self._isolation_state.selected_shape_tokens
        )

    def _isolation_allows(self, shape: Shape) -> bool:
        """Return whether ``shape`` belongs to the active isolation target."""
        if not self._isolation_enabled:
            return True
        return self._isolation_state.allows(shape)

    def set_isolation_enabled(self, enabled: bool) -> None:
        """Enable or disable transient selection/group isolation."""
        self._isolation_enabled = bool(enabled) and bool(self.selected_shapes)
        if self._isolation_enabled:
            self._refresh_isolation_target()
        else:
            self._isolation_group_id = None
            self._isolation_shape_tokens = ()
            self._isolation_state = IsolationState(
                image_token=self.appearance_image_token
            )
        self.update()

    def toggle_isolation(self) -> bool:
        """Toggle transient isolation and return its resulting state."""
        self.set_isolation_enabled(not self._isolation_enabled)
        return self._isolation_enabled

    def _visual_style_for_shape(self, shape: Shape) -> VisualStyle:
        """Resolve toolkit-neutral style after existing visibility gates."""
        settings = self.appearance_settings
        mode = settings.color_mode
        shape_token = str(id(shape))
        cache_key = (
            mode.value,
            shape.label or "",
            repr(shape.group_id),
            shape_token if mode is ColorMode.INSTANCE else "",
        )
        base_color = self._appearance_base_color_cache.get(cache_key)
        if base_color is None:
            base_color = resolve_base_color(
                mode,
                shape.label or "",
                shape.group_id,
                shape_token,
                self.appearance_label_colors,
            )
            self._appearance_base_color_cache[cache_key] = base_color
        opacity = self.group_focus_controller.emphasis(
            shape, settings.unrelated_opacity
        )
        fill_opacity = (
            settings.selected_fill_opacity
            if shape.selected
            else (
                settings.hover_fill_opacity
                if shape.hovered
                else settings.normal_fill_opacity
            )
        )
        gid_badge = None
        if settings.show_gid == "always" or (
            settings.show_gid == "focus"
            and self.group_focus_controller.state.active
        ):
            if shape.group_id is not None:
                gid_badge = str(shape.group_id)
        return VisualStyle(
            base_color=base_color,
            outer_color=(
                (18, 18, 18) if settings.high_contrast_outline else base_color
            ),
            outline_width=settings.outline_width,
            semantic_width=settings.semantic_width,
            fill_opacity=fill_opacity,
            object_opacity=opacity,
            label_badge=shape.label if settings.show_labels else None,
            gid_badge=gid_badge,
            selected=shape.selected,
            hovered=shape.hovered,
            editing=self._is_shape_under_edge_edit(shape),
        )

    def _should_draw_geometry(self, shape: Shape) -> bool:
        """Return whether ordinary geometry should enter the paint path."""
        if not self.main_visible(shape):
            return False
        return self._visual_style_for_shape(shape).object_opacity > 0.0

    def _render_decision_for_shape(self, shape: Shape, hovered: bool = False):
        """Resolve the shared toolkit-neutral output gates for ``shape``."""
        focus_state = self.group_focus_controller.state
        context = ShapeVisualContext(
            shape_token=str(id(shape)),
            label=str(getattr(shape, "label", "") or ""),
            group_id=getattr(shape, "group_id", None),
            visible=self.main_visible(shape),
            base_visible=self.base_visible(shape),
            selected=bool(getattr(shape, "selected", False)),
            hovered=bool(getattr(shape, "hovered", False) or hovered),
            editing=self._is_shape_under_edge_edit(shape),
            focused=(
                not focus_state.active
                or getattr(shape, "group_id", None)
                == focus_state.focused_group_id
            ),
            image_token=self.appearance_image_token,
        )
        return resolve_render_decision(
            context,
            focus_active=focus_state.active,
            unrelated_opacity=self.appearance_settings.unrelated_opacity,
            isolation_enabled=self._isolation_enabled,
            isolation_group_id=self._isolation_group_id,
            isolation_shape_tokens=self._isolation_shape_tokens,
            show_labels=(
                self.show_labels and self.appearance_settings.show_labels
            ),
            label_on_selection=self.label_on_selection,
            show_gid=self.appearance_settings.show_gid,
        )

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
        defer_drag_overlays = self._should_defer_drag_overlays()

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

        # Virtual review keeps unrelated base-visible shapes as dim context.
        # The normal shape pass below is restricted by ``main_visible`` to the
        # current task, while hit-testing uses the same effective predicate.
        if self._virtual_review_visibility_predicate is not None:
            p.save()
            p.setOpacity(0.22)
            for shape in self.shapes:
                if not self._virtual_review_context_visible(shape):
                    continue
                if not viewport_rect.intersects(shape.bounding_rect()):
                    continue
                shape.paint(p, force_unselected=True)
            p.restore()

        # Draw groups
        if self.show_groups and not defer_drag_overlays:
            pen = QtGui.QPen(QtGui.QColor("#AAAAAA"), 2, Qt.PenStyle.SolidLine)
            p.setPen(pen)
            grouped_shapes = {}
            for shape in self.shapes:
                if not self._should_draw_geometry(shape):
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
                    group_color = resolve_base_color(
                        ColorMode.GROUP, "", group_id
                    )
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
        if self.show_linking and not defer_drag_overlays:
            pen = QtGui.QPen(QtGui.QColor("#AAAAAA"), 2, Qt.PenStyle.SolidLine)
            p.setPen(pen)
            gid2point = {}
            linking_pairs = []
            group_color = (255, 128, 0)
            for shape in self.shapes:
                if not self._should_draw_geometry(shape):
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
        if self.show_masks and not defer_drag_overlays:
            for shape in self.shapes:
                if not self._should_draw_geometry(shape):
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

                # 与主绘制通道一致：边操作下被操作矩形的轮廓/填充色
                # 回退到标签色，使 overlay 白色高亮可区分。mask 通道不
                # 经过 shape.paint，故用局部变量而非实例标志。
                edge_editing = self._is_shape_under_edge_edit(shape)
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
                    if shape.selected and not edge_editing
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
                    if shape.selected and not edge_editing
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
            if not self._should_draw_geometry(shape):
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
                edge_editing = self._is_shape_under_edge_edit(shape)
                decision = self._render_decision_for_shape(shape)
                if not decision.draw_geometry:
                    continue
                style = self._visual_style_for_shape(shape)
                if style.object_opacity <= 0.0:
                    continue
                shape.paint(
                    p,
                    force_unselected=edge_editing,
                    visual_style=style,
                )

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
                and not defer_drag_overlays
                and shape.shape_type == "rectangle"
                and not (self.label_on_selection and not shape.selected)
                and shape.label not in autolabel_names
                and self._should_draw_geometry(shape)
            )

        # Draw texts
        if self.show_texts and not defer_drag_overlays:
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
                if not self.main_visible(shape):
                    continue
                if not self._should_draw_geometry(shape):
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
                if not self.main_visible(shape):
                    continue
                if not self._should_draw_geometry(shape):
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

        # Draw labels
        if self.show_labels and not defer_drag_overlays:
            # Compute hover context only when labels are actually painted.
            hovered_shape = self._standard_label_hovered_shape()
            p.setFont(self._standard_label_font())
            labels = []
            for shape in self.shapes:
                label_text = self._label_text_for_shape(shape, hovered_shape)
                if not label_text:
                    continue
                fm = QtGui.QFontMetrics(p.font())
                layout = self._standard_label_layout_for_shape(
                    shape, label_text, fm
                )
                if layout is None:
                    continue
                rect, text_pos = layout

                labels.append((shape, rect, text_pos, label_text))

            p.setPen(Qt.PenStyle.NoPen)
            for shape, rect, _, _ in labels:
                if not self.main_visible(shape):
                    continue
                bg_color = QtGui.QColor(shape.line_color)
                bg_color.setAlphaF(0.85)
                p.setBrush(bg_color)
                p.drawRoundedRect(rect, 3, 3)

            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QtGui.QColor("#ffffff"))
            for shape, _, text_pos, label_text in labels:
                if not self.main_visible(shape):
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
                # Feed only main-visible Shapes so focus also gates the pose
                # overlay. Without a predicate this remains the full base-
                # visible set.
                [
                    shape
                    for shape in self.iter_main_visible_shapes()
                    if self._should_draw_geometry(shape)
                ],
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
        if self.rect_edge_align_enabled:
            self._draw_rect_edge_alignment_overlay(p)
        self._draw_rectangle_review_feedback_hud(p)
        self._draw_rectangle_review_loupe(p)

        # Live W/H size overlay for the in-progress or single-selected
        # rectangle (person small-target warning). Pure transient drawing;
        # never mutates Shape data, undo stack, dirty, or JSON.
        self._draw_size_overlay(p)

        self._draw_crosshair(p)

        # Cross-image object marking overlay. Independent of selected,
        # hover, active-edge, and QA states; never mutates Shape data.
        self._draw_batch_mark_overlay(p)
        self._draw_isolation_badge(p)

        # Draw attributes
        if self.show_attributes and not defer_drag_overlays:
            font_size = int(max(8.0, int(round(10.0 / Shape.scale))))
            font = QtGui.QFont("Arial", font_size, QtGui.QFont.Weight.Bold)
            p.setFont(font)
            attributes_list = []

            for shape in self.shapes:
                if not self.main_visible(shape):
                    continue
                if not self._should_draw_geometry(shape):
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
                if not self.main_visible(shape):
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

            for shape, _, text_positions, attribute_lines in attributes_list:
                if not self._should_draw_geometry(shape):
                    continue
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

        self._rubber_band_renderer.draw(p, self._selection_box_rect)

        p.end()
        _dt = time.perf_counter() - _t0
        if _dt > 0.05:
            _perf_log(
                "Canvas.paintEvent slow: %.3fs, shapes=%d",
                _dt,
                len(self.shapes),
            )

    def _draw_isolation_badge(self, painter: QtGui.QPainter) -> None:
        """Draw a non-persistent corner badge while isolation is active."""
        if not self._isolation_enabled:
            return
        painter.save()
        painter.resetTransform()
        if self._isolation_group_id is not None:
            text = self.tr("ISOLATED · Group %s") % self._isolation_group_id
        else:
            count = len(self._isolation_shape_tokens)
            text = self.tr("ISOLATED · %d object(s)") % count
        font = QtGui.QFont("Arial", 10, QtGui.QFont.Weight.Bold)
        painter.setFont(font)
        fm = QtGui.QFontMetrics(font)
        rect = QtCore.QRectF(10, 10, fm.horizontalAdvance(text) + 18, 28)
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 220), 1))
        painter.setBrush(QtGui.QColor(25, 70, 120, 220))
        painter.drawRoundedRect(rect, 5, 5)
        painter.setPen(QtGui.QColor(255, 255, 255))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

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
            scale_factor = max(1.0, float(getattr(self, "scale", 1.0) or 1.0))
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

    def set_rectangle_review_refinement_config(
        self, config, legacy_config=None
    ):
        """Apply low-fatigue rectangle review refinement settings.

        Args:
            config: Nested rectangle-review refinement settings.
            legacy_config: Optional root settings mapping used for migration
                when the nested target gain is absent.
        """
        config = config if isinstance(config, dict) else {}
        self.rectangle_review_refinement_enabled = bool(
            config.get("enabled", False)
        )
        target_gain, migrated = resolve_target_gain(config, legacy_config)
        self.rectangle_review_target_gain = target_gain
        self.rectangle_review_migration_needed = migrated
        self.rectangle_review_edge_precision_default = bool(
            config.get("edge_drag_precision_default", True)
        )
        self.rectangle_review_nudge_step_px = _safe_positive_int(
            config.get("nudge_step_px", 1), 1
        )
        self.rectangle_review_coarse_step_px = _safe_positive_int(
            config.get("coarse_step_px", 5), 5
        )
        self.rectangle_review_feedback_enabled = bool(
            config.get("feedback_enabled", True)
        )
        self.rectangle_review_persist_across_images = bool(
            config.get("persist_across_images", True)
        )
        assistance = config.get("assistance", {})
        assistance = assistance if isinstance(assistance, dict) else {}
        self.rectangle_review_loupe_enabled = bool(
            assistance.get("loupe_enabled", False)
        )
        self.rectangle_review_candidate_enabled = bool(
            assistance.get("candidate_enabled", False)
        )
        telemetry = config.get("telemetry", {})
        telemetry = telemetry if isinstance(telemetry, dict) else {}
        self.rectangle_review_telemetry_enabled = bool(
            telemetry.get("enabled", False)
        )
        self.rectangle_review_telemetry_config = dict(telemetry)

    def _rectangle_review_precision_active(self, ev=None):
        """Return whether an active edge should use target-gain precision."""
        if not (
            self.rectangle_review_refinement_enabled
            and self.rectangle_review_edge_precision_default
            and self.rect_edge_dragging
        ):
            return False
        if ev is not None and (
            ev.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier
        ):
            return False
        return True

    def _effective_drag_gain(self, ev=None):
        """Return image-pixel gain for the current drag context."""
        if self._rectangle_review_precision_active(ev):
            return effective_gain(
                self.scale, self.rectangle_review_target_gain
            )
        return 1.0 / max(float(self.precision_factor), 1.0)

    def _precision_active(self, ev=None):
        """Return True if precision drag is active (D6: Ctrl held or locked)."""
        # The new review workflow owns active-edge gain selection, including
        # Shift coarse mode. Do not let the legacy lock override that choice.
        if (
            self.rect_edge_dragging
            and self.rectangle_review_refinement_enabled
            and self.rectangle_review_edge_precision_default
        ):
            return False
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
        precision_active = self._precision_active(ev)
        edge_precision = self._rectangle_review_precision_active(ev)
        if not precision_active and not edge_precision:
            self._reset_virtual_cursor()
            return pos
        if self._virtual_prev_point is None:
            self._virtual_prev_point = QtCore.QPointF(self.prev_point)
            self._precision_raw_prev_point = QtCore.QPointF(self.prev_point)
        delta = pos - self._precision_raw_prev_point
        gain = self._effective_drag_gain(ev)
        if edge_precision:
            gain = image_delta_multiplier(
                self.scale, self.rectangle_review_target_gain
            )
        scaled = QtCore.QPointF(delta.x() * gain, delta.y() * gain)
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
                self.drawing_canceled.emit()
                self.update()
                return
        elif self.current.shape_type == "rotation":
            if not self.clip_rotation_to_pixmap(self.current):
                self.current = None
                self.set_hiding(False)
                self.drawing_polygon.emit(False)
                self.drawing_canceled.emit()
                self.update()
                return
        elif self.current.shape_type == "cuboid":
            self.current.sync_cuboid_depth_vector()

        self.shapes.append(self.current)
        self.store_shapes()
        self.current = None
        self.set_hiding(False)
        self.notify_shapes_changed()
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

        if self._rectangle_review_nudge_wheel(ev):
            return

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
                edit_target = "scale"
            else:
                edit_target = self._adjust_rectangle_edge(shape, pos, wheel_up)

            # Status bar from the same metrics as the overlay (rev.1 §3.2):
            # wheel scaling / edge-adjust previously skipped show_shape.
            self._emit_show_shape_from_shape(shape, pos)
            self.store_shapes()
            self.notify_shape_changed(shape)
            self.shape_moved.emit()
            self.semantic_burst_requested.emit(
                "rectangle_adjust",
                shape,
                edit_target or "edge",
                "wheel",
                {"input_kind": "wheel"},
                {"changed": True},
            )
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

    def _rectangle_review_nudge_wheel(self, ev: QWheelEvent) -> bool:
        """Apply a discrete wheel nudge to the active rectangle edge."""
        if not (
            self.rectangle_review_refinement_enabled
            and self.rect_edge_active_edge is not None
            and not (
                ev.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier
            )
        ):
            return False
        angle_y = ev.angleDelta().y()
        pixel_y = ev.pixelDelta().y()
        notches = self._rectangle_review_wheel.add(angle_y, pixel_y)
        if notches == 0:
            ev.accept()
            return True
        active = self.rect_edge_active_edge
        geometry = rea.geometry_from_shape(active.shape)
        if geometry is None or self.pixmap is None:
            return False
        step = (
            self.rectangle_review_coarse_step_px
            if ev.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier
            else self.rectangle_review_nudge_step_px
        )
        direction = 1 if notches > 0 else -1
        candidate = active.coord + direction * step * abs(notches)
        valid = valid_edge_nudge(
            (
                geometry.x_min,
                geometry.y_min,
                geometry.x_max,
                geometry.y_max,
            ),
            active.edge_name,
            direction,
            step * abs(notches),
            (self.pixmap.width(), self.pixmap.height()),
        )
        if valid and rea.apply_edge_coord(
            active.shape, active.edge_name, candidate
        ):
            refreshed = rea.geometry_from_shape(active.shape)
            if refreshed is not None:
                refreshed_edge = rea.edge_from_geometry(
                    active.shape, refreshed, active.edge_name
                )
                self.rect_edge_state.refresh_active(refreshed_edge)
                original_coord = (
                    self.rectangle_review_feedback_snapshot.original_coord
                    if self.rectangle_review_feedback_snapshot is not None
                    else refreshed_edge.coord
                )
                self._set_rectangle_review_feedback(
                    refreshed_edge, "nudge", original_coord
                )
            if self._rectangle_review_nudge_burst.begin(
                (id(active.shape), active.edge_name, direction, "wheel"),
                time.monotonic(),
            ):
                self.store_shapes()
            self.notify_shape_changed(active.shape)
            self.shape_moved.emit()
            self.semantic_burst_requested.emit(
                "rectangle_adjust",
                active.shape,
                active.edge_name,
                "wheel",
                {"input_kind": "wheel"},
                {"changed": True},
            )
            self.update()
        elif self.rectangle_review_feedback_snapshot is not None:
            self._set_rectangle_review_feedback(
                active,
                "rejected",
                self.rectangle_review_feedback_snapshot.original_coord,
                "boundary_or_min_size",
            )
        ev.accept()
        return True

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
        return closest_edge

    # ------------------------------------------------------------------
    # Rectangle edge editing mode.
    # See docs/cls3-010_task_矩形边对齐功能实现任务文档.md and rect_edge_alignment.py.
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
        self.update()

    def set_person_small_target_min_edge(self, min_edge):
        """Set the person small-target threshold in image-pixel space.

        The overlay compares ``max(W, H)`` (image-pixel, raw float) against
        this threshold; ``size < min_edge`` triggers the warning style. A
        value equal to the threshold (e.g. 36.0 vs 36.0) is treated as
        passing, so no warning is shown on the boundary.

        Args:
            min_edge: Minimum edge length in image pixels. Coerced to
                ``float``; non-finite values fall back to the default.
        """
        try:
            value = float(min_edge)
        except (TypeError, ValueError):
            value = DEFAULT_PERSON_SMALL_TARGET_MIN_EDGE_PX
        if not math.isfinite(value) or value <= 0:
            value = DEFAULT_PERSON_SMALL_TARGET_MIN_EDGE_PX
        self.person_small_target_min_edge = value

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
        coord = self._rect_edge_clamp_coord_to_image(active.axis, coord)

        # Live edit: mutate the target shape in place. The drag start
        # points are preserved so Esc can restore them.
        changed = rea.apply_edge_coord(active.shape, active.edge_name, coord)
        if not changed:
            if self.rectangle_review_feedback_snapshot is not None:
                self._set_rectangle_review_feedback(
                    active,
                    "rejected",
                    self.rectangle_review_feedback_snapshot.original_coord,
                    "boundary_or_min_size",
                )
            return
        previous_coord = active.coord
        self.notify_shape_changed(active.shape)
        # Refresh the active edge from the just-mutated geometry so the
        # overlay follows the live position instead of the original edge.
        updated_geom = rea.geometry_from_shape(active.shape)
        if updated_geom is not None:
            refreshed = rea.edge_from_geometry(
                active.shape, updated_geom, active.edge_name
            )
            self.rect_edge_state.refresh_active(refreshed)
            self.rectangle_review_edge_drag_delta.emit(
                float(refreshed.coord - previous_coord)
            )
            original_coord = previous_coord
            if self.rectangle_review_feedback_snapshot is not None:
                original_coord = (
                    self.rectangle_review_feedback_snapshot.original_coord
                )
            self._set_rectangle_review_feedback(
                refreshed, "dragging", original_coord
            )
        # Drive the status bar from the SAME metrics as the overlay (design
        # rev.1 §3.2): previously this path only called update(), leaving the
        # status bar H/W stale during an edge drag.
        self._emit_show_shape_from_shape(active.shape, pos)
        # Geometry drags need one visible frame per accepted mouse position.
        # ``update()`` may coalesce adjacent events and make the edge appear to
        # jump; the drag-only lightweight paint path keeps repaint affordable.
        self.repaint()

    def _rect_edge_clamp_coord_to_image(self, axis, coord):
        """Clamp one edge coordinate to the current image bounds.

        Args:
            axis: Rectangle-edge axis (``"x"`` or ``"y"``).
            coord: Candidate coordinate in image space.

        Returns:
            The bounded coordinate. When no image is loaded, returns the
            original coordinate so headless geometry use remains available.
        """
        if self.pixmap is None or self.pixmap.isNull():
            return coord
        if axis == rea.RECT_EDGE_AXIS_X:
            upper = max(0.0, float(self.pixmap.width() - 1))
        else:
            upper = max(0.0, float(self.pixmap.height() - 1))
        return max(0.0, min(float(coord), upper))

    def _start_rect_edge_drag(
        self, edge: rea.RectEdgeRef, press_pos: QtCore.QPointF
    ) -> None:
        """Promote an edge reference to the active drag target.

        Args:
            edge: Rectangle edge reference to edit.
            press_pos: Original press position in image coordinates.
        """
        self.prev_point = QtCore.QPointF(press_pos)
        self.rect_edge_state.start_drag(edge, edge.shape.points)
        self._rectangle_review_nudge_burst.reset()
        self.rectangle_review_edge_drag_started.emit(edge.edge_name)
        self._set_rectangle_review_feedback(edge, "dragging", edge.coord)
        self.override_cursor(CURSOR_MOVE)

    def _is_shape_under_edge_edit(self, shape):
        """矩形是否当前正被矩形边操作（hover 或拖拽）影响。

        用于让被操作矩形的轮廓色回退到 line_color，使边操作 overlay
        的白色高亮能从整框白色中区分出来。键盘选中的边不触发——键盘
        微调时整框保持选中高亮态。

        Args:
            shape: 待查询的 :class:`Shape`。

        Returns:
            bool: 该 shape 正被鼠标 hover 或拖拽某条边。
        """
        if not self.rect_edge_align_enabled:
            return False
        active = self.rect_edge_active_edge
        hover = self.rect_edge_hover_edge
        if active is not None and active.shape is shape:
            return True
        if hover is not None and hover.shape is shape:
            return True
        return False

    def clear_rect_edge_alignment(self):
        """Clear transient edge-editing interaction state."""
        self.rect_edge_state.clear_mouse()
        self.rectangle_review_feedback_snapshot = None
        self._rectangle_review_nudge_burst.reset()
        self.rectangle_review_feedback_changed.emit(None)

    def cancel_rect_edge_drag(self):
        """Cancel an in-progress edge drag and restore the pre-drag points.

        Returns:
            True if a drag was cancelled, False when no drag was active.
        """
        if not self.rect_edge_dragging:
            return False

        active_edge_name = self.rect_edge_active_edge.edge_name
        restore = self.rect_edge_state.cancel_drag()
        if restore is not None:
            shape, start_points = restore
            # Restore the target shape's points exactly as they were before
            # the drag preview mutated them in place.
            shape.points = list(start_points)
            shape._invalidate_cache()
            self.notify_shape_changed(shape)
            restored_geometry = rea.geometry_from_shape(shape)
            restored_edge = (
                rea.edge_from_geometry(
                    shape, restored_geometry, active_edge_name
                )
                if restored_geometry is not None
                else None
            )
            if restored_edge is not None:
                original_coord = (
                    self.rectangle_review_feedback_snapshot.original_coord
                    if self.rectangle_review_feedback_snapshot is not None
                    else restored_edge.coord
                )
                self._set_rectangle_review_feedback(
                    restored_edge, "canceled", original_coord
                )

        self.rectangle_review_edge_drag_finished.emit(False)
        self.rectangle_review_feedback_snapshot = None
        self.rectangle_review_feedback_changed.emit(None)
        self.override_cursor(CURSOR_DEFAULT)
        self.update()
        return True

    def _cancel_rect_edge_interaction(self):
        """Cancel any pending or active direct edge interaction.

        Active drags restore their start geometry. Pending and hover-only
        interactions have no geometry to restore, so their transient state is
        simply cleared.

        Returns:
            True when any rectangle-edge state was cleared, otherwise False.
        """
        if self.rect_edge_dragging:
            return self.cancel_rect_edge_drag()

        had_state = any(
            state is not None
            for state in (
                self.rect_edge_hover_edge,
                self.rect_edge_active_edge,
                self.rect_edge_pending_edge,
            )
        )
        if not had_state:
            return False

        self.clear_rect_edge_alignment()
        self.override_cursor(CURSOR_DEFAULT)
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
        if self.rect_edge_pending_edge is not None:
            self.clear_rect_edge_alignment()
            self.update()
            return True
        return False

    def _clear_rect_edge_pending(self) -> None:
        """Clear the press-before-drag rectangle-edge state."""
        self.rect_edge_state.clear_pending()

    def _rect_edge_pending_is_valid(self) -> bool:
        """Return whether the pending edge still targets an editable shape."""
        pending = self.rect_edge_pending_edge
        selected = self._selected_rect_edge_shape()
        return bool(
            self.rect_edge_align_enabled
            and self.editing()
            and pending is not None
            and self.rect_edge_pending_press_pos is not None
            and self.rect_edge_pending_image_pos is not None
            and selected is pending.shape
            and pending.shape in self.shapes
            and self.is_shape_interactive(pending.shape)
            and pending.shape.shape_type == "rectangle"
        )

    def _rect_edge_pending_has_moved(self, widget_pos: QtCore.QPointF) -> bool:
        """Return whether a pending press has a non-zero movement delta."""
        press_pos = self.rect_edge_pending_press_pos
        if press_pos is None:
            return False
        return QtCore.QLineF(press_pos, widget_pos).length() > 0.0

    def _rect_edge_vertex_has_priority(
        self, shape: Shape, point: QtCore.QPointF, epsilon: float
    ) -> bool:
        """Return whether the selected rectangle vertex owns the point."""
        return shape.nearest_vertex(point, epsilon) is not None

    def _selected_rect_edge_shape(self) -> Shape | None:
        """Return the only selected rectangle eligible for mouse edge edits."""
        if (
            not self.rect_edge_align_enabled
            or not self.editing()
            or len(self.selected_shapes) != 1
        ):
            return None
        shape = self.selected_shapes[0]
        if (
            shape not in self.shapes
            or not self.is_shape_interactive(shape)
            or shape.shape_type != "rectangle"
        ):
            return None
        return shape

    def _rect_edge_cursor(self, edge: rea.RectEdgeRef | None):
        """Return the resize cursor matching one rectangle edge axis."""
        if edge is None:
            return CURSOR_DEFAULT
        if edge.axis == rea.RECT_EDGE_AXIS_X:
            return CURSOR_SIZE_HOR
        return CURSOR_SIZE_VER

    def _rect_edge_hit_on_edge(
        self,
        edge: rea.RectEdgeRef,
        point: QtCore.QPointF,
        epsilon: float,
        geometry: rea.RectGeometry,
    ) -> tuple[rea.RectEdgeRef, float] | None:
        """Hit-test one finite edge with the selected-rectangle strategy."""
        x = point.x()
        y = point.y()
        small_threshold = 3.0 * float(self.epsilon)
        screen_width = geometry.width * float(self.scale)
        screen_height = geometry.height * float(self.scale)
        is_small = min(screen_width, screen_height) < small_threshold

        if edge.edge_name == rea.RECT_EDGE_LEFT:
            if y < geometry.y_min or y > geometry.y_max:
                return None
            if is_small and x > geometry.x_min:
                return None
            distance = abs(x - geometry.x_min)
        elif edge.edge_name == rea.RECT_EDGE_RIGHT:
            if y < geometry.y_min or y > geometry.y_max:
                return None
            if is_small and x < geometry.x_max:
                return None
            distance = abs(x - geometry.x_max)
        elif edge.edge_name == rea.RECT_EDGE_TOP:
            if x < geometry.x_min or x > geometry.x_max:
                return None
            if is_small and y > geometry.y_min:
                return None
            distance = abs(y - geometry.y_min)
        elif edge.edge_name == rea.RECT_EDGE_BOTTOM:
            if x < geometry.x_min or x > geometry.x_max:
                return None
            if is_small and y < geometry.y_max:
                return None
            distance = abs(y - geometry.y_max)
        else:
            return None

        if distance > epsilon:
            return None
        return edge, distance

    def _rect_edge_specific_hit(
        self, edge: rea.RectEdgeRef | None, point: QtCore.QPointF
    ) -> tuple[rea.RectEdgeRef, float] | None:
        """Refresh and hit-test one exact edge without global reranking."""
        selected = self._selected_rect_edge_shape()
        if (
            not self.rect_edge_align_enabled
            or not self.editing()
            or edge is None
            or selected is not edge.shape
            or edge.shape not in self.shapes
            or not self.is_shape_interactive(edge.shape)
            or edge.shape.shape_type != "rectangle"
        ):
            return None

        epsilon = self.epsilon / self.scale
        if self._rect_edge_vertex_has_priority(edge.shape, point, epsilon):
            return None

        geometry = rea.geometry_from_shape(edge.shape)
        if geometry is None or not geometry.is_valid():
            return None
        refreshed = rea.edge_from_geometry(
            edge.shape, geometry, edge.edge_name
        )
        return self._rect_edge_hit_on_edge(refreshed, point, epsilon, geometry)

    def _rect_edge_press_candidate(
        self, point: QtCore.QPointF
    ) -> rea.RectEdgeRef | None:
        """Confirm the visible selected-rectangle edge before hit testing."""
        preferred = self._rect_edge_specific_hit(
            self.rect_edge_hover_edge, point
        )
        if preferred is not None:
            return preferred[0]
        return self._rect_edge_hit_candidate(point)

    def _rect_edge_hit_candidate(
        self, point: QtCore.QPointF
    ) -> rea.RectEdgeRef | None:
        """Return the nearest editable rectangle edge under a point.

        Only runs while the mode is enabled, the canvas is in editing mode and
        exactly one selected shape is an interactive rectangle. The selected
        rectangle's native vertex handles have priority; the remaining edge
        candidates are ranked only within that rectangle.

        Args:
            point: Mouse position in image coordinates.

        Returns:
            The best ``RectEdgeRef`` or ``None``.
        """
        shape = self._selected_rect_edge_shape()
        if shape is None:
            return None

        epsilon = self.epsilon / self.scale
        if self._rect_edge_vertex_has_priority(shape, point, epsilon):
            return None

        geometry = rea.geometry_from_shape(shape)
        if geometry is None or not geometry.is_valid():
            return None

        best: tuple[float, rea.RectEdgeRef] | None = None
        for edge in rea.iter_edges(shape):
            result = self._rect_edge_hit_on_edge(
                edge, point, epsilon, geometry
            )
            if result is None:
                continue
            edge, distance = result
            candidate = (distance, edge)
            if best is None or candidate[0] < best[0]:
                best = candidate

        if best is None:
            return None
        return best[1]

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

    def _draw_rectangle_review_feedback_hud(
        self, painter: QtGui.QPainter
    ) -> None:
        """Draw a transient, fixed-screen-size edge refinement HUD."""
        snapshot = self.rectangle_review_feedback_snapshot
        active = self.rect_edge_active_edge
        if snapshot is None or active is None:
            return
        if not (
            self.rectangle_review_refinement_enabled
            and self.rectangle_review_feedback_enabled
        ):
            return
        geometry = rea.geometry_from_shape(active.shape)
        if geometry is None:
            return
        painter.save()
        try:
            start_points = self.rect_edge_drag_start_points or []
            if len(start_points) >= 2:
                start_x = [point.x() for point in start_points]
                start_y = [point.y() for point in start_points]
                original_pen = QtGui.QPen(QtGui.QColor(255, 220, 80))
                original_pen.setStyle(QtCore.Qt.PenStyle.DashLine)
                original_pen.setWidthF(1.0 / max(self.scale, 1e-6))
                painter.setPen(original_pen)
                if active.axis == rea.RECT_EDGE_AXIS_X:
                    original_x = (
                        min(start_x)
                        if active.edge_name == rea.RECT_EDGE_LEFT
                        else max(start_x)
                    )
                    painter.drawLine(
                        QtCore.QPointF(original_x, min(start_y)),
                        QtCore.QPointF(original_x, max(start_y)),
                    )
                else:
                    original_y = (
                        min(start_y)
                        if active.edge_name == rea.RECT_EDGE_TOP
                        else max(start_y)
                    )
                    painter.drawLine(
                        QtCore.QPointF(min(start_x), original_y),
                        QtCore.QPointF(max(start_x), original_y),
                    )
            font_size = max(8, int(round(12.0 / max(self.scale, 1e-6))))
            font = QtGui.QFont("Arial", font_size)
            painter.setFont(font)
            metrics = QtGui.QFontMetricsF(font)
            line = (
                f"{snapshot.phase}  Δ {snapshot.signed_delta:+.1f}px  "
                f"W×H {snapshot.width:.1f}×{snapshot.height:.1f}"
            )
            padding = 5.0 / max(self.scale, 1e-6)
            text_width = metrics.horizontalAdvance(line)
            text_height = metrics.height()
            x = geometry.x_min
            y = geometry.y_min - text_height - padding * 2.0
            if y < 0:
                y = geometry.y_max + padding
            if x + text_width + padding * 2.0 > self.pixmap.width():
                x = max(0.0, self.pixmap.width() - text_width - padding * 2.0)
            rect = QtCore.QRectF(
                x,
                y,
                text_width + padding * 2.0,
                text_height + padding * 2.0,
            )
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255)))
            painter.setBrush(QtGui.QColor(0, 0, 0, 180))
            painter.drawRoundedRect(rect, 3.0 / max(self.scale, 1e-6), 3.0)
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255)))
            painter.drawText(
                rect.adjusted(padding, padding, -padding, -padding),
                QtCore.Qt.AlignmentFlag.AlignLeft
                | QtCore.Qt.AlignmentFlag.AlignVCenter,
                line,
            )
        finally:
            painter.restore()

    def _draw_rectangle_review_loupe(self, painter: QtGui.QPainter) -> None:
        """Draw an optional read-only, fixed-screen-size edge loupe."""
        if not (
            self.rectangle_review_refinement_enabled
            and self.rectangle_review_loupe_enabled
            and self.rect_edge_active_edge is not None
            and self.pixmap is not None
        ):
            return
        active = self.rect_edge_active_edge
        geometry = rea.geometry_from_shape(active.shape)
        if geometry is None:
            return
        if active.axis == rea.RECT_EDGE_AXIS_X:
            center = (active.coord, (geometry.y_min + geometry.y_max) / 2.0)
        else:
            center = ((geometry.x_min + geometry.x_max) / 2.0, active.coord)
        roi = build_loupe_roi(
            center,
            (self.pixmap.width(), self.pixmap.height()),
            radius_px=16,
        )
        roi_pixmap = self.pixmap.copy(roi.x, roi.y, roi.width, roi.height)
        screen_width = 160.0
        screen_height = 120.0
        image_width = screen_width / max(self.scale, 1e-6)
        image_height = screen_height / max(self.scale, 1e-6)
        gap = 8.0 / max(self.scale, 1e-6)
        x = geometry.x_max + gap
        if x + image_width > self.pixmap.width():
            x = geometry.x_min - gap - image_width
        x = max(0.0, min(x, self.pixmap.width() - image_width))
        y = center[1] - image_height / 2.0
        y = max(0.0, min(y, self.pixmap.height() - image_height))
        target = QtCore.QRectF(x, y, image_width, image_height)
        painter.save()
        try:
            painter.setOpacity(0.96)
            painter.drawPixmap(
                target,
                roi_pixmap,
                QtCore.QRectF(0, 0, roi.width, roi.height),
            )
            painter.setOpacity(1.0)
            pen = QtGui.QPen(QtGui.QColor(255, 255, 255))
            pen.setWidthF(2.0 / max(self.scale, 1e-6))
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRect(target)
        finally:
            painter.restore()

    def request_rectangle_review_candidate(
        self, samples: list[float]
    ) -> EdgeCandidate | None:
        """Explicitly request an edge candidate without mutating geometry."""
        if not (
            self.rectangle_review_refinement_enabled
            and self.rectangle_review_candidate_enabled
            and self.rect_edge_active_edge is not None
        ):
            return None
        active = self.rect_edge_active_edge
        candidate = self._rectangle_review_candidate_service.request(
            active.edge_name, samples, active.coord
        )
        if candidate is not None:
            self._rectangle_review_candidate_preview.show(candidate)
            self.rectangle_review_candidate_changed.emit(candidate)
            self.update()
        return candidate

    def reject_rectangle_review_candidate(self) -> None:
        """Discard a candidate preview without changing the active shape."""
        self._rectangle_review_candidate_preview.reject()
        self.rectangle_review_candidate_changed.emit(None)
        self.update()

    def accept_rectangle_review_candidate(self) -> bool:
        """Validate and commit the current candidate as one undo unit."""
        candidate = self._rectangle_review_candidate_preview.preview
        active = self.rect_edge_active_edge
        if candidate is None or active is None:
            return False
        if candidate.edge != active.edge_name:
            self.reject_rectangle_review_candidate()
            return False
        proposed = active.shape.copy()
        if not rea.apply_edge_coord(
            proposed, candidate.edge, candidate.coordinate
        ):
            self.reject_rectangle_review_candidate()
            return False
        geometry = rea.geometry_from_shape(proposed)
        if geometry is None or not geometry.is_valid():
            self.reject_rectangle_review_candidate()
            return False
        if self.pixmap is not None and (
            geometry.x_min < 0
            or geometry.y_min < 0
            or geometry.x_max >= self.pixmap.width()
            or geometry.y_max >= self.pixmap.height()
        ):
            self.reject_rectangle_review_candidate()
            return False
        if not rea.apply_edge_coord(
            active.shape, candidate.edge, candidate.coordinate
        ):
            self.reject_rectangle_review_candidate()
            return False
        self.store_shapes()
        refreshed = rea.geometry_from_shape(active.shape)
        if refreshed is not None:
            self.rect_edge_state.refresh_active(
                rea.edge_from_geometry(
                    active.shape, refreshed, active.edge_name
                )
            )
        self.notify_shape_changed(active.shape)
        self.shape_moved.emit()
        self._rectangle_review_candidate_preview.reject()
        self.rectangle_review_candidate_changed.emit(None)
        self.update()
        return True

    def _set_rectangle_review_feedback(
        self,
        edge: rea.RectEdgeRef,
        phase: str,
        original_coord: float,
        rejection_reason: str | None = None,
    ) -> None:
        """Update the shared feedback model from current edge geometry."""
        if not (
            self.rectangle_review_refinement_enabled
            and self.rectangle_review_feedback_enabled
        ):
            return
        geometry = rea.geometry_from_shape(edge.shape)
        if geometry is None:
            return
        self.rectangle_review_feedback_snapshot = make_feedback_snapshot(
            edge.edge_name,
            phase,
            original_coord,
            edge.coord,
            geometry.width,
            geometry.height,
            rejection_reason,
        )
        self.rectangle_review_feedback_changed.emit(
            self.rectangle_review_feedback_snapshot
        )

    def _rectangle_metrics(self, shape=None, p0=None, p1=None, source=""):
        """Build a unified RectangleMetrics tuple from image-space geometry.

        Both the status bar (int H/W) and the size overlay (float W/H) consume
        this single source of truth, so they can never disagree (design
        rev.1 §3.1). All values are raw floats in image px.

        Args:
            shape: A finished rectangle Shape (4/2 points). Mutually exclusive
                with ``p0``/``p1``.
            p0, p1: Two corner points (creation stage). Mutually exclusive
                with ``shape``.
            source: A label for the metric origin (creating / selected /
                rect_edge_active / ...).

        Returns:
            ``(x_min, y_min, x_max, y_max, width, height, max_edge,
            label, shape_or_none, source)`` or ``None`` when geometry is
            unusable.
        """
        if shape is not None:
            geom = rea.geometry_from_shape(shape)
            if geom is None:
                return None
            x_min, y_min, x_max, y_max = (
                geom.x_min,
                geom.y_min,
                geom.x_max,
                geom.y_max,
            )
            label = shape.label
        elif p0 is not None and p1 is not None:
            x_min, y_min, x_max, y_max = normalize_two_points(p0, p1)
            label = None
        else:
            return None
        width, height, max_edge = size_from_bbox(x_min, y_min, x_max, y_max)
        return (
            x_min,
            y_min,
            x_max,
            y_max,
            width,
            height,
            max_edge,
            label,
            shape,
            source,
        )

    def _emit_show_shape_from_shape(self, shape, pos):
        """Emit show_shape with int H/W from the unified metrics (rev.1 §3.2).

        Keeps the ``show_shape(int_height, int_width, QPointF)`` signature
        unchanged while routing the status bar through the same metrics the
        overlay uses, so the two never disagree. Degenerate rectangles are
        skipped (the slot hides H/W when height/width <= 0).

        Args:
            shape: The rectangle shape just edited.
            pos: Current cursor position in image coordinates.
        """
        metrics = self._rectangle_metrics(shape=shape, source="rect_edit")
        if metrics is None:
            return
        # width=4, height=5, max_edge=6 in the metrics tuple.
        width = metrics[4]
        height = metrics[5]
        if width <= 0 or height <= 0:
            return
        self.show_shape.emit(int(height), int(width), pos)

    def _emit_show_shape_from_points(self, p0, p1, pos):
        """Emit show_shape for an in-progress rectangle from unified metrics."""
        metrics = self._rectangle_metrics(p0=p0, p1=p1, source="creating")
        if metrics is None:
            return
        width = metrics[4]
        height = metrics[5]
        if width <= 0 or height <= 0:
            return
        self.show_shape.emit(int(height), int(width), pos)

    def _resolve_overlay_metrics(self):
        """Pick the rectangle the overlay describes and build its metrics.

        Resolution priority (design rev.1 §3.4):

        1. Creating a rectangle: ``self.current[0]`` + ``self.line[1]``.
        2. Active rect-edge drag: ``rect_edge_active_edge.shape``.
        3. Rectangle currently hovered by the real canvas pointer.
        4. Single selected rectangle as a fallback.

        Every candidate passes ``is_shape_interactive`` so filtered / hidden /
        non-interactive shapes never show an overlay (R3).

        Returns:
            The metrics tuple from :meth:`_rectangle_metrics`, or ``None``.
        """
        # 1. Creation stage.
        if self.drawing() and self.create_mode == "rectangle":
            if not self.current or len(self.current) < 1:
                return None
            if len(self.line.points) < 2:
                return None
            return self._rectangle_metrics(
                p0=self.current[0],
                p1=self.line.points[1],
                source="creating",
            )

        # 2. Active rect-edge drag: read the edited shape from the locked edge.
        active = self.rect_edge_active_edge
        if active is not None and active.shape is not None:
            shape = active.shape
            if (
                shape in self.shapes
                and shape.shape_type == "rectangle"
                and self.is_shape_interactive(shape)
            ):
                return self._rectangle_metrics(
                    shape=shape, source="rect_edge_active"
                )

        # 3. Real canvas hover. This is separate from h_hape because h_hape
        #    can be set by non-pointer flows such as label-loop navigation.
        hover_shape = self._size_overlay_hover_shape
        if hover_shape is not None:
            if (
                hover_shape in self.shapes
                and hover_shape.shape_type == "rectangle"
                and self.is_shape_interactive(hover_shape)
            ):
                return self._rectangle_metrics(
                    shape=hover_shape, source="hover"
                )

        # 4. Single selected rectangle.
        if (
            len(self.selected_shapes) == 1
            and self._selected_shapes_source != "label_list"
        ):
            shape = self.selected_shapes[0]
            if (
                shape in self.shapes
                and shape.shape_type == "rectangle"
                and self.is_shape_interactive(shape)
            ):
                return self._rectangle_metrics(shape=shape, source="selected")
        return None

    def _draw_crosshair(self, painter: QtGui.QPainter) -> None:
        """Draw cursor-aligned guides without leaking painter state."""
        if (
            not self.cross_line_show
            or not self._crosshair_cursor_active
            or self.pixmap is None
            or self.pixmap.isNull()
        ):
            return

        scale = max(float(self.scale), 1e-12)
        pen = QtGui.QPen(
            QtGui.QColor(self.cross_line_color),
            max(1, int(round(self.cross_line_width / scale))),
            Qt.PenStyle.DashLine,
        )
        painter.save()
        try:
            painter.setPen(pen)
            painter.setOpacity(self.cross_line_opacity)
            painter.drawLine(
                QtCore.QPointF(self.prev_move_point.x(), 0),
                QtCore.QPointF(self.prev_move_point.x(), self.pixmap.height()),
            )
            painter.drawLine(
                QtCore.QPointF(0, self.prev_move_point.y()),
                QtCore.QPointF(self.pixmap.width(), self.prev_move_point.y()),
            )
        finally:
            painter.restore()

    @property
    def rectangle_size_issues(self) -> tuple[RectangleSizeIssue, ...]:
        """Return the proactive issue snapshot currently exposed to paint."""
        return self._rectangle_size_issues

    def set_rectangle_size_issues(
        self,
        issues: Iterable[RectangleSizeIssue],
        shape_lookup: Optional[object] = None,
    ) -> None:
        """Atomically replace proactive issues and reconnect live shapes.

        ``shape_lookup`` may be a mapping or callable accepting candidate_id.
        When omitted, the default Monitor identity contract ``id(shape)`` is
        resolved from the current Canvas snapshot.

        Args:
            issues: Current immutable Monitor issue snapshot.
            shape_lookup: Optional mapping/callable for custom candidate IDs.

        Raises:
            TypeError: If an issue or lookup object has an invalid type.
            ValueError: If issue candidate identities are duplicated.
        """
        issue_tuple = tuple(issues)
        issue_ids = set()
        for issue in issue_tuple:
            if not isinstance(issue, RectangleSizeIssue):
                raise TypeError(
                    "rectangle-size issues must be RectangleSizeIssue objects"
                )
            if issue.candidate_id in issue_ids:
                raise ValueError(
                    "rectangle-size issues need unique candidate_id values"
                )
            issue_ids.add(issue.candidate_id)

        if (
            shape_lookup is not None
            and not callable(shape_lookup)
            and not isinstance(shape_lookup, Mapping)
        ):
            raise TypeError("shape_lookup must be a mapping or callable")

        current_by_identity = {id(shape): shape for shape in self.shapes}
        issue_shapes = {}
        for issue in issue_tuple:
            if callable(shape_lookup):
                shape = shape_lookup(issue.candidate_id)
            elif isinstance(shape_lookup, Mapping):
                shape = shape_lookup.get(issue.candidate_id)
            else:
                shape = current_by_identity.get(issue.candidate_id)
            if shape is not None and any(
                current is shape for current in self.shapes
            ):
                issue_shapes[issue.candidate_id] = shape

        self._rectangle_size_issues = issue_tuple
        self._rectangle_size_issue_shapes = issue_shapes
        self.update()

    def clear_rectangle_size_issues(self) -> None:
        """Clear proactive issue state and schedule removal from the canvas."""
        if (
            not self._rectangle_size_issues
            and not self._rectangle_size_issue_shapes
        ):
            return
        self._reset_rectangle_size_issue_state()
        self.update()

    def _reset_rectangle_size_issue_state(self) -> None:
        """Clear issue state without independently scheduling a repaint."""
        self._rectangle_size_issues = ()
        self._rectangle_size_issue_shapes.clear()

    def _overlay_label_rect_for_shape(
        self,
        shape: Optional[Shape],
    ) -> Optional[tuple[float, float, float, float]]:
        """Return the current standard label rect for overlay anchoring."""
        if shape is None:
            return None
        label_text = self._label_text_for_shape(shape)
        if not label_text:
            return None
        label_metrics = QtGui.QFontMetrics(self._standard_label_font())
        return self._label_rect_for_shape(shape, label_text, label_metrics)

    def _overlay_candidate_id_for_shape(self, shape: Shape) -> object:
        """Return a Monitor candidate ID when available for one live shape."""
        for (
            candidate_id,
            issue_shape,
        ) in self._rectangle_size_issue_shapes.items():
            if issue_shape is shape:
                return candidate_id
        return id(shape)

    def _normal_size_overlay_request(
        self,
    ) -> Optional[RectangleSizeOverlayRequest]:
        """Build the ordinary hover/selection/creation request when visible."""
        if not self.show_rectangle_pixels:
            return None
        metrics = self._resolve_overlay_metrics()
        if metrics is None:
            return None
        (
            x_min,
            y_min,
            x_max,
            y_max,
            width,
            height,
            max_edge,
            label,
            _shape,
            _source,
        ) = metrics
        if (
            _shape is not None
            and not self._render_decision_for_shape(_shape).draw_size_overlay
        ):
            return None
        if max_edge < 1e-6:
            return None

        threshold = self.person_small_target_min_edge
        legacy_warning = (
            not self.show_rectangle_size_violations
            and is_person_small_target(label, max_edge, threshold)
        )
        lines = [self.tr("W %.1f px  H %.1f px") % (width, height)]
        if legacy_warning:
            lines.append(
                self.tr("Max edge %.1f px < %g px") % (max_edge, threshold)
            )
        candidate_id = (
            self._overlay_candidate_id_for_shape(_shape)
            if _shape is not None
            else "ordinary-rectangle-creation"
        )
        return RectangleSizeOverlayRequest(
            candidate_id=candidate_id,
            lines=tuple(lines),
            bbox=(x_min, y_min, x_max, y_max),
            label_rect=self._overlay_label_rect_for_shape(_shape),
            warning=legacy_warning,
        )

    def _violation_overlay_requests(
        self,
    ) -> tuple[RectangleSizeOverlayRequest, ...]:
        """Build paint requests for current visible proactive issues."""
        if not self.show_rectangle_size_violations:
            return ()
        requests = []
        for issue in self._rectangle_size_issues:
            shape = self._rectangle_size_issue_shapes.get(issue.candidate_id)
            if (
                shape is None
                or not any(current is shape for current in self.shapes)
                or not self.main_visible(shape)
                or not self._should_draw_geometry(shape)
            ):
                continue
            requests.append(
                overlay_request_from_issue(
                    issue,
                    label_rect=self._overlay_label_rect_for_shape(shape),
                )
            )
        return tuple(requests)

    def _combined_size_overlay_requests(
        self,
    ) -> tuple[RectangleSizeOverlayRequest, ...]:
        """Return one deduplicated sequence for the shared layout pass."""
        return merge_overlay_requests(
            self._normal_size_overlay_request(),
            self._violation_overlay_requests(),
        )

    def _draw_size_overlay(self, painter: QtGui.QPainter) -> None:
        """Draw ordinary and proactive rectangle overlays in one layout pass.

        The overlay remains transient UI state: no Shape, JSON, undo, or dirty
        state is changed.

        Args:
            painter: Active painter already transformed into image space.
        """
        requests = self._combined_size_overlay_requests()
        if not requests:
            return
        self._rectangle_size_overlay_renderer.render(
            painter,
            requests,
            self._visible_overlay_rect(),
        )

    def _label_text_for_shape(self, shape, hovered_shape=None):
        """Return the label text rendered for a shape, or ``None`` to skip.

        Mirrors the standard label pass (paintEvent) so the overlay anchors to
        the SAME label box the user sees (design rev.1 §6.3: no parallel
        approximation). Honours label_display_mode / show_scores /
        show_texts / show_attributes exactly as the paint loop does.

        Args:
            shape: The shape whose label text to compute.

        Returns:
            The label string, or ``None`` when no label should be drawn.
        """
        if not self._is_standard_label_visible(shape, hovered_shape):
            return None
        if not self._render_decision_for_shape(
            shape, hovered=shape is hovered_shape
        ).draw_text:
            return None
        return self._standard_label_text_for_shape(shape)

    def _label_rect_for_shape(self, shape, label_text, fm):
        """Return the label background rect for a rectangle shape.

        Mirrors the rectangle branch of the standard label pass. ``fm`` must
        be built from :meth:`_standard_label_font`, not from the overlay font,
        so the anchor uses the same label box the user sees.

        Args:
            shape: The rectangle shape.
            label_text: The label string (from _label_text_for_shape).
            fm: A :class:`QFontMetrics` for the label font.

        Returns:
            A ``(x, y, w, h)`` tuple in image px, or ``None`` on failure.
        """
        rect = self._rectangle_label_rect_for_shape(shape, label_text, fm)
        if rect is None:
            return None
        return (rect.x(), rect.y(), rect.width(), rect.height())

    def _visible_overlay_rect(self):
        """Return the current visible canvas region in image px.

        Matches the paintEvent culling viewport (design rev.1 §7). Falls back
        to the full pixmap when the widget has no size yet.
        """
        offset = self.offset_to_center()
        vx_min = -offset.x()
        vy_min = -offset.y()
        vw = self.width() / self.scale if self.scale else 0.0
        vh = self.height() / self.scale if self.scale else 0.0
        if self.pixmap is not None and vw > 0 and vh > 0:
            # Intersect with the pixmap bounds.
            return (
                max(0.0, vx_min),
                max(0.0, vy_min),
                min(float(self.pixmap.width()), vx_min + vw),
                min(float(self.pixmap.height()), vy_min + vh),
            )
        if self.pixmap is not None:
            return (
                0.0,
                0.0,
                float(self.pixmap.width()),
                float(self.pixmap.height()),
            )
        return (0.0, 0.0, 1.0, 1.0)

    def _paint_overlay_box(self, painter, lines, bbox, shape, warning):
        """Delegate one legacy prompt to the reusable multi-box renderer.

        The renderer maps image geometry to widget pixels and uses
        ``resetTransform()`` internally, preserving the existing fixed-size
        appearance at every Canvas zoom level.

        Args:
            painter: The active :class:`QPainter` (scaled to pixmap space by
                ``paintEvent``).
            lines: Tuple of text lines to render (1 or 2).
            bbox: ``(x_min, y_min, x_max, y_max)`` of the target rectangle,
                in image px.
            shape: The target Shape (for label-rect anchoring) or None.
            warning: When True, render in the warning colour and border.
        """
        request = RectangleSizeOverlayRequest(
            candidate_id=id(shape) if shape is not None else "legacy-overlay",
            lines=tuple(lines),
            bbox=bbox,
            label_rect=self._overlay_label_rect_for_shape(shape),
            warning=warning,
        )
        self._rectangle_size_overlay_renderer.render(
            painter,
            (request,),
            self._visible_overlay_rect(),
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

    def move_by_keyboard(self, offset):
        """Move selected shapes by an offset (using keyboard)"""
        if self.selected_shapes:
            self._prepare_keyboard_edit()
            self.bounded_move_shapes(
                self.selected_shapes, self.prev_point + offset
            )
            self.repaint()
            self.moving_shape = True

    def rotate_by_keyboard(self, theta):
        """Rotate selected shapes by an theta (using keyboard)"""
        if self.selected_shapes:
            self._prepare_keyboard_edit()
            rotating_shape = False
            for i, shape in enumerate(self.selected_shapes):
                if shape._shape_type == "rotation":
                    self.bounded_rotate_shapes(i, shape, theta)
                    rotating_shape = True
            if rotating_shape:
                self.repaint()
                self.rotating_shape = True

    def _prepare_keyboard_edit(self) -> None:
        """Capture geometry before a keyboard gesture, including lazy loads."""
        if getattr(self, "_keyboard_edit_before", None) is not None:
            return
        self._keyboard_edit_before = [
            (shape, list(shape.points)) for shape in self.shapes
        ]
        if self._pending_initial_backup or not self.shapes_backups:
            self.shapes_backups.append([s.copy() for s in self.shapes])
            self._pending_initial_backup = False

    def _finish_keyboard_edit(self) -> None:
        """Commit changed live objects and always clear gesture state."""
        before = getattr(self, "_keyboard_edit_before", None)
        self._keyboard_edit_before = None
        try:
            if before is None:
                return
            current_ids = {id(shape) for shape in self.shapes}
            changed = any(
                id(shape) in current_ids and shape.points != points
                for shape, points in before
            )
            if changed:
                self.store_shapes()
                if self.moving_shape:
                    self.shape_moved.emit()
                if self.rotating_shape:
                    self.shape_rotated.emit()
        finally:
            self.moving_shape = False
            self.rotating_shape = False

    # QT Overload
    def event(self, ev):
        """Cancel active rectangle-edge edits on input interruption."""
        if ev.type() in (
            QtCore.QEvent.Type.UngrabMouse,
            QtCore.QEvent.Type.WindowDeactivate,
        ) and hasattr(self, "rect_edge_dragging"):
            if self._cancel_rect_edge_interaction():
                self.restore_cursor()
        return super(Canvas, self).event(ev)

    def keyPressEvent(self, ev):
        """Key press event"""
        key = ev.key()
        if key == QtCore.Qt.Key.Key_Tab and self._cycle_rect_edge(
            bool(ev.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier)
        ):
            ev.accept()
            return
        # Rectangle-edge interaction consumes Esc first. Otherwise notify
        # observers, then continue through the native Canvas key handling.
        if key == QtCore.Qt.Key.Key_Escape:
            if self._selection_gesture.active:
                self._clear_selection_gesture()
                return
            if (
                self.rect_edge_align_enabled
                and self._handle_rect_edge_escape()
            ):
                return
            self.escape_pressed.emit()
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
                self.drawing_canceled.emit()
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
                        self.drawing_canceled.emit()
                        self.update()
            elif key == QtCore.Qt.Key.Key_Return and self.can_close_shape():
                self.finalise()
            elif modifiers == QtCore.Qt.KeyboardModifier.AltModifier:
                self.snapping = False
        elif self.editing():
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

    def _editing_arrow_dispatch(self, key, modifiers):
        """Dispatch arrow keys to whole-shape movement.

        Returns True when the key was an arrow and was consumed.
        Default step is 1px; Shift scales to MOVE_SPEED (5px).
        """
        if key not in (
            QtCore.Qt.Key.Key_Up,
            QtCore.Qt.Key.Key_Down,
            QtCore.Qt.Key.Key_Left,
            QtCore.Qt.Key.Key_Right,
        ):
            return False
        if self._rectangle_review_nudge_key(key, modifiers):
            return True
        step = (
            MOVE_SPEED
            if modifiers & QtCore.Qt.KeyboardModifier.ShiftModifier
            else 1.0
        )
        if key == QtCore.Qt.Key.Key_Up:
            self.move_by_keyboard(QtCore.QPointF(0.0, -step))
        elif key == QtCore.Qt.Key.Key_Down:
            self.move_by_keyboard(QtCore.QPointF(0.0, step))
        elif key == QtCore.Qt.Key.Key_Left:
            self.move_by_keyboard(QtCore.QPointF(-step, 0.0))
        elif key == QtCore.Qt.Key.Key_Right:
            self.move_by_keyboard(QtCore.QPointF(step, 0.0))
        self.input_burst_requested.emit("micro_adjust", "keyboard")
        return True

    def _activate_rect_edge_for_nudge(self, edge: rea.RectEdgeRef) -> None:
        """Promote a clicked edge to the keyboard/wheel nudge target."""
        self._rectangle_review_nudge_burst.reset()
        self.rect_edge_state.active_edge = edge
        self.rect_edge_state.drag_start_points = [
            QtCore.QPointF(point) for point in edge.shape.points
        ]
        self.rect_edge_state.set_hover(edge)
        self.rectangle_review_edge_drag_started.emit(edge.edge_name)
        self._set_rectangle_review_feedback(edge, "nudge", edge.coord)
        self.override_cursor(self._rect_edge_cursor(edge))

    def _cycle_rect_edge(self, reverse: bool = False) -> bool:
        """Cycle the active edge for Tab/Shift+Tab keyboard handoff."""
        if not (
            self.rectangle_review_refinement_enabled
            and self.rect_edge_align_enabled
        ):
            return False
        shape = self._selected_rect_edge_shape()
        if shape is None:
            return False
        geometry = rea.geometry_from_shape(shape)
        if geometry is None:
            return False
        edge_names = [
            rea.RECT_EDGE_TOP,
            rea.RECT_EDGE_RIGHT,
            rea.RECT_EDGE_BOTTOM,
            rea.RECT_EDGE_LEFT,
        ]
        current = self.rect_edge_active_edge or self.rect_edge_hover_edge
        current_name = current.edge_name if current is not None else None
        index = (
            edge_names.index(current_name)
            if current_name in edge_names
            else -1
        )
        step = -1 if reverse else 1
        edge_name = edge_names[(index + step) % len(edge_names)]
        if current is not None:
            self.clear_rect_edge_alignment()
        edge = rea.edge_from_geometry(shape, geometry, edge_name)
        self._activate_rect_edge_for_nudge(edge)
        self.update()
        return True

    def _rectangle_review_nudge_key(
        self, key: int, modifiers: QtCore.Qt.KeyboardModifier
    ) -> bool:
        """Apply one keyboard nudge when a rectangle edge is active/hovered."""
        if not (
            self.rectangle_review_refinement_enabled
            and self.rect_edge_align_enabled
            and self.pixmap is not None
        ):
            return False
        active = self.rect_edge_active_edge or self.rect_edge_hover_edge
        if active is None or active.shape not in self.selected_shapes:
            return False
        if self.rect_edge_active_edge is None:
            self.rect_edge_state.active_edge = active
            self.rect_edge_state.drag_start_points = [
                QtCore.QPointF(point) for point in active.shape.points
            ]
            self.rectangle_review_edge_drag_started.emit(active.edge_name)
            self._set_rectangle_review_feedback(active, "nudge", active.coord)
        direction = 1
        if key in (QtCore.Qt.Key.Key_Left, QtCore.Qt.Key.Key_Up):
            direction = -1
        step = (
            self.rectangle_review_coarse_step_px
            if modifiers & QtCore.Qt.KeyboardModifier.ShiftModifier
            else self.rectangle_review_nudge_step_px
        )
        geometry = rea.geometry_from_shape(active.shape)
        if geometry is None:
            return True
        candidate = active.coord + direction * step
        if not valid_edge_nudge(
            (
                geometry.x_min,
                geometry.y_min,
                geometry.x_max,
                geometry.y_max,
            ),
            active.edge_name,
            direction,
            step,
            (self.pixmap.width(), self.pixmap.height()),
        ):
            self._set_rectangle_review_feedback(
                active,
                "rejected",
                (
                    self.rectangle_review_feedback_snapshot.original_coord
                    if self.rectangle_review_feedback_snapshot is not None
                    else active.coord
                ),
                "boundary_or_min_size",
            )
            return True
        if not rea.apply_edge_coord(active.shape, active.edge_name, candidate):
            return True
        refreshed = rea.geometry_from_shape(active.shape)
        if refreshed is not None:
            refreshed_edge = rea.edge_from_geometry(
                active.shape, refreshed, active.edge_name
            )
            self.rect_edge_state.refresh_active(refreshed_edge)
            self._set_rectangle_review_feedback(
                refreshed_edge,
                "nudge",
                (
                    self.rectangle_review_feedback_snapshot.original_coord
                    if self.rectangle_review_feedback_snapshot is not None
                    else refreshed_edge.coord
                ),
            )
        if self._rectangle_review_nudge_burst.begin(
            (id(active.shape), active.edge_name, direction, "keyboard"),
            time.monotonic(),
        ):
            self.store_shapes()
        self.notify_shape_changed(active.shape)
        self.shape_moved.emit()
        self.update()
        return True

    # QT Overload
    def keyReleaseEvent(self, ev):
        """Key release event"""
        if ev.isAutoRepeat():
            return
        modifiers = ev.modifiers()
        if self.drawing():
            if modifiers == QtCore.Qt.KeyboardModifier.NoModifier:
                self.snapping = True
        elif self.editing():
            self._finish_keyboard_edit()

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
        self.notify_shape_changed(self.shapes[-1])
        return self.shapes[-1]

    def undo_last_line(self):
        """Undo last line"""
        assert self.shapes
        self.current = self.shapes.pop()
        self.notify_shapes_changed()
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

    def discard_last_shape(self) -> None:
        """Discard the provisional shape created by a rejected commit."""
        removed = False
        if self.shapes:
            self.shapes.pop()
            removed = True
        if self.shapes_backups:
            self.shapes_backups.pop()
        self.current = None
        self._brush_drawing = False
        self.set_hiding(False)
        self.drawing_polygon.emit(False)
        if removed:
            self.notify_shapes_changed()
        self.update()

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
            self.drawing_canceled.emit()
        self.update()

    def load_pixmap(self, pixmap, clear_shapes=True):
        """Load pixmap"""
        self._keyboard_edit_before = None
        self.moving_shape = False
        self.rotating_shape = False
        self._crosshair_cursor_active = False
        self._set_size_overlay_hover_shape(None)
        self._set_selected_shapes([], source="none")
        self.selected_shapes_copy = []
        self.h_hape = None
        self.h_vertex = None
        self.h_edge = None
        self.h_cuboid_face = None
        self.clear_rect_edge_alignment()
        self.pixmap = pixmap
        if clear_shapes:
            self.shapes = []
            self._reset_rectangle_size_issue_state()
            self.notify_shapes_changed()
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
        shapes = validate_shape_references(
            shapes,
            replace=replace,
            existing_shapes=self.shapes,
        )
        self._reset_rectangle_size_issue_state()
        shapes = self._normalize_incoming_shape_ids(shapes, replace=replace)
        if replace:
            self._keyboard_edit_before = None
            self.moving_shape = False
            self.rotating_shape = False
            self._set_size_overlay_hover_shape(None)
            self._set_selected_shapes([], source="none")
            self.selected_shapes_copy = []
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
        self._set_size_overlay_hover_shape(None)
        self.h_hape = None
        self.h_vertex = None
        self.h_edge = None
        self.h_cuboid_face = None
        self._batch_mark_press = None

        # Drop any in-progress rectangle edge edit so transient state never
        # leaks across images.
        self.clear_rect_edge_alignment()
        self.notify_shapes_changed()
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

    def _normalize_incoming_shape_ids(
        self, shapes: Iterable[Shape], *, replace: bool
    ) -> list[Shape]:
        """Claim unique persistent identities for Shapes entering the Canvas."""
        incoming = list(shapes)
        reserved_ids = (
            ()
            if replace
            else (
                getattr(shape, "xanylabeling_shape_id", MISSING_SHAPE_ID)
                for shape in self.shapes
            )
        )
        identity_result = normalize_shape_identities(
            (
                getattr(shape, "xanylabeling_shape_id", MISSING_SHAPE_ID)
                for shape in incoming
            ),
            reserved_ids=reserved_ids,
        )
        for shape, shape_id in zip(incoming, identity_result.identities):
            shape.xanylabeling_shape_id = shape_id
        if identity_result.diagnostics:
            logger.warning(
                "Repaired %d incoming Canvas Shape identities: %s",
                identity_result.repaired_count,
                describe_shape_identity_diagnostics(
                    identity_result.diagnostics
                ),
            )
        return incoming

    def set_shape_visible(self, shape, value):
        """Set visibility for a shape"""
        self.visible[shape] = value
        self.notify_shape_changed(shape)
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
        self._keyboard_edit_before = None
        self.moving_shape = False
        self.rotating_shape = False
        self.restore_cursor()
        self._crosshair_cursor_active = False
        self._set_size_overlay_hover_shape(None)
        self._set_selected_shapes([], source="none")
        self.selected_shapes_copy = []
        self.current = None
        self._brush_drawing = False
        self.h_hape = None
        self.h_vertex = None
        self.h_edge = None
        self.h_cuboid_face = None
        self.pixmap = None
        self.shapes = []
        self._reset_rectangle_size_issue_state()
        self.shapes_backups = []
        self.is_move_editing = False
        self.compare_pixmap = None
        # Reset every transient rectangle-edge interaction state.
        self.clear_rect_edge_alignment()
        self.notify_shapes_changed()
        self.update()

    def set_cross_line(self, show, width, color, opacity):
        """Set cross line options"""
        self.cross_line_show = show
        self.cross_line_width = width
        self.cross_line_color = color
        self.cross_line_opacity = opacity
        self.update()

    def set_batch_mark_mode(self, enabled):
        """Enable or pause cross-image marking gesture recognition.

        Pausing keeps the active mark set (owned elsewhere) untouched.
        """
        self.batch_mark_mode = bool(enabled)
        self._batch_mark_press = None
        self.update()

    def set_marked_shape_ids(self, shape_ids):
        """Set marked identities for the current image and repaint."""
        self.marked_shape_ids = {str(shape_id) for shape_id in shape_ids}
        self.update()

    def _batch_mark_capture_press(self, pos):
        """Record the press candidate for a possible mark toggle.

        Vertex, active-edge, and blank presses never qualify; dragging
        and geometric edits are filtered out again at release time.
        """
        if self.selected_vertex() or self.selected_edge():
            return None
        shape = self.h_hape
        if shape is None or shape not in self.shapes:
            return None
        return (shape, pos)

    def _emit_batch_mark_toggle_if_click(self, ev):
        """Emit one toggle request when press-release forms a plain click."""
        press = self._batch_mark_press
        self._batch_mark_press = None
        if press is None:
            return
        shape, press_pos = press
        if shape not in self.shapes or self.moving_shape:
            return
        release_pos = self.transform_pos(ev.position())
        if (
            QtCore.QLineF(press_pos, release_pos).length()
            > self._selection_drag_threshold()
        ):
            return
        self.batch_mark_toggle_requested.emit(shape)

    def _draw_batch_mark_overlay(self, painter):
        """Draw orange outer strokes around the marked current-image shapes."""
        if not self.marked_shape_ids:
            return
        pen_width = max(1.0, 2.0 / max(self.scale, 1e-6))
        pad = 2.0 * pen_width
        painter.save()
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor(255, 140, 0),
                pen_width,
                QtCore.Qt.PenStyle.DashLine,
            )
        )
        for shape in self.shapes:
            if shape.xanylabeling_shape_id not in self.marked_shape_ids:
                continue
            if not self.is_visible(shape):
                continue
            rect = shape.bounding_rect().adjusted(-pad, -pad, pad, pad)
            painter.drawRect(rect)
        painter.restore()

    def gen_new_group_id(self):
        """Generate new shape's group_id based on current shapes"""
        max_group_id = 0
        for shape in self.shapes:
            if is_valid_group_id(shape.group_id):
                max_group_id = max(max_group_id, shape.group_id)
        return max_group_id + 1

    def merge_group_ids(self, group_ids, new_group_id):
        """Merge multiple shapes' group_id into a new one"""
        for shape in self.shapes:
            if shape.group_id in group_ids:
                shape.group_id = new_group_id
                self.notify_shape_changed(shape)

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
                    self.notify_shape_changed(shape)

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
                    self.notify_shape_changed(shape)

        self.update()
