import functools
import html
import json
import math
import os
import os.path as osp
import re
import shutil
import time
from typing import Optional, Set

import cv2
import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QFontMetrics, QIntValidator, QShortcut
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QLineEdit,
)

from anylabeling.services.auto_labeling.types import AutoLabelingMode
from anylabeling.services.auto_labeling import _THUMBNAIL_RENDER_MODELS
from anylabeling.views.training import UltralyticsDialog

from ...app_info import (
    __appname__,
    __version__,
    __preferred_device__,
)
from . import utils
from .utils.style import (
    get_cancel_btn_style,
    get_checkbox_indicator_style,
    get_dialog_style,
    get_dock_style,
    get_ok_btn_style,
    get_panel_style,
    get_plain_text_edit_style,
    get_settings_button_style,
)
from ...config import get_config, save_config
from .label_file import LabelFile, LabelFileError
from .logger import logger
from .filter_state import FilterState
from .filter_engine import ShapeFilterEngine
from .filter_navigation_engine import FilterNavigationEngine
from .dataset_filter_index import (
    DatasetFilterIndex,
    make_db_path,
)
from .dataset_filter_index_worker import DatasetIndexWorker
from .settings import SettingsController, SettingsDialog
from .settings.runtime_applier import SettingsRuntimeApplier
from .shape import Shape
from .utils.file_search import (
    parse_search_pattern,
    matches_filename,
    matches_label_attribute,
)
from .utils.qt import new_icon_path
from .widgets import (
    AboutDialog,
    AutoLabelingWidget,
    BrightnessContrastDialog,
    Canvas,
    ChatbotDialog,
    ClassifierDialog,
    CompareViewManager,
    CompareViewSlider,
    VQADialog,
    CrosshairSettingsDialog,
    FileDialogPreview,
    PPOCRDialog,
    ShapeModifyDialog,
    GroupIDFilterComboBox,
    LabelDialog,
    LabelFilterComboBox,
    ShapeTypeFilterComboBox,
    LabelListWidget,
    LabelListWidgetItem,
    DigitRenameManager,
    DigitRenameShortcutDialog,
    DigitShortcutDialog,
    DigitShortcutPageManager,
    LabelModifyDialog,
    GroupIDModifyDialog,
    OverviewDialog,
    Popup,
    SearchBar,
    ToolBar,
    UniqueLabelQListWidget,
    ViewportController,
    ZoomWidget,
    NavigatorDialog,
    KeypointFillMode,
    KeypointToolWindow,
    InspectorPanel,
)
from .widgets.pose_label import (
    PoseViewPanel,
)

PERF_LOG_ENABLED = os.getenv("XANYLABELING_PERF_LOG") == "1"


def _perf_log(message, *args):
    """Emit performance logs only when enabled by env var."""
    if PERF_LOG_ENABLED:
        logger.info(message, *args)


LABEL_COLORMAP = utils.label_colormap()
LABEL_OPACITY = 128
CHECKED_FIELD = "checked"
FILE_CHECKED_COLOR = "#22A06B"
FILE_UNCHECKED_COLOR = "#8C98A4"
CHECKED_FIELD_PATTERN = re.compile(r'"checked"\s*:\s*(true|false)')


def _measure_text_width(font_metrics, text):
    if hasattr(font_metrics, "horizontalAdvance"):
        return font_metrics.horizontalAdvance(text)
    return font_metrics.width(text)


def _create_file_status_icon(color):
    pixmap = QtGui.QPixmap(12, 12)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.setBrush(QtGui.QColor(color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, 8, 8)
    painter.end()
    return QtGui.QIcon(pixmap)


class LabelCheckWorker(QtCore.QThread):
    """Background worker that checks label files in batches."""

    progress = QtCore.pyqtSignal(int, int)
    batch_ready = QtCore.pyqtSignal(list)
    labels_found = QtCore.pyqtSignal(list)
    finished = QtCore.pyqtSignal()

    def __init__(self, image_files, output_dir=None, batch_size=500):
        super().__init__()
        self.image_files = image_files
        self.output_dir = output_dir
        self.batch_size = batch_size
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        total = len(self.image_files)
        batch = []
        label_paths = []
        for i, img_path in enumerate(self.image_files):
            if self._cancelled:
                break
            label_file = osp.splitext(img_path)[0] + ".json"
            if self.output_dir:
                label_file = self.output_dir + "/" + osp.basename(label_file)
            has_label = QtCore.QFile.exists(
                label_file
            ) and LabelFile.is_label_file(label_file)
            if has_label:
                label_paths.append(label_file)
            batch.append((img_path, has_label))
            if len(batch) >= self.batch_size:
                self.batch_ready.emit(batch)
                batch = []
            step = max(total // 100, 1)
            if i % step == 0 or i == total - 1:
                self.progress.emit(i + 1, total)
        if batch:
            self.batch_ready.emit(batch)
        self.labels_found.emit(label_paths)
        self.finished.emit()


class LabelingWidget(LabelDialog):
    """The main widget for labeling images"""

    FIT_WINDOW, FIT_WIDTH, MANUAL_ZOOM = 0, 1, 2
    next_files_changed = QtCore.pyqtSignal(list)

    def __init__(  # noqa: C901
        self,
        parent=None,
        config=None,
        filename=None,
        output=None,
        output_file=None,
        output_dir=None,
    ):
        self.parent = parent
        if output is not None:
            logger.warning(
                "argument output is deprecated, use output_file instead"
            )
            if output_file is None:
                output_file = output

        self.filename = None
        self.image_path = None
        self.image_data = None
        self.label_file = None
        self.other_data = {}
        self.classes_file = None
        self.attributes = {}
        self.attribute_widget_types = {}
        self.current_category = None
        self.selected_polygon_stack = []
        self.supported_shape = Shape.get_supported_shape()
        self.label_info = {}
        self.image_flags = []
        self.fn_to_index = {}
        self.cache_auto_label = None
        self.cache_auto_label_group_id = None

        # see configs/anylabeling_config.yaml for valid configuration
        if config is None:
            config = get_config()
        self._config = config
        self.label_flags = self._config["label_flags"]
        self.label_loop_count = -1
        self.select_loop_count = -1
        self.digit_to_label = None
        self.drawing_digit_shortcuts = self._config.get("digit_shortcuts", {})
        self.digit_rename_manager = DigitRenameManager(self)
        self._runtime_shape_color_shift = int(
            self._config.get("shift_auto_shape_color", 0)
        )

        # Initialize Digit Shortcut Page Manager
        self.digit_page_manager = DigitShortcutPageManager(
            config=self._config,
            shortcuts=self.drawing_digit_shortcuts,
            status_callback=self.status,
            tr_callback=self.tr,
        )

        # Initialize Keypoint Fill Mode
        self.keypoint_fill_mode = KeypointFillMode(
            shapes_getter=lambda: self.canvas.shapes,
            status_callback=self.status,
            tr_callback=self.tr,
        )
        self.keypoint_tool_window = None
        self.inspector_panel = InspectorPanel()
        self.inspector_panel.issue_navigate_requested.connect(
            self._on_inspector_navigate
        )
        self.inspector_panel.shape_edit_requested.connect(
            self._on_inspector_shape_edit
        )
        # Feed the initial label config to the shared label set
        labels_from_config = self._config.get("labels", [])
        if labels_from_config:
            self.inspector_panel.set_allowed_labels(set(labels_from_config))
        self._settings_controller = None
        self._settings_dialog = None
        self._label_modify_dialog = None
        self._settings_runtime_applier = SettingsRuntimeApplier(self)
        self._auto_switch_signal_connected = False

        # set default shape colors
        Shape.line_color = QtGui.QColor(*self._config["shape"]["line_color"])
        Shape.fill_color = QtGui.QColor(*self._config["shape"]["fill_color"])
        Shape.select_line_color = QtGui.QColor(
            *self._config["shape"]["select_line_color"]
        )
        Shape.select_fill_color = QtGui.QColor(
            *self._config["shape"]["select_fill_color"]
        )
        Shape.vertex_fill_color = QtGui.QColor(
            *self._config["shape"]["vertex_fill_color"]
        )
        Shape.hvertex_fill_color = QtGui.QColor(
            *self._config["shape"]["hvertex_fill_color"]
        )

        # Set point size from config file
        Shape.point_size = self._config["shape"]["point_size"]
        # Set line width from config file
        Shape.line_width = self._config["shape"]["line_width"]

        super(LabelDialog, self).__init__()

        # Inspector table refresh timer (debounced)
        self._inspector_table_refresh_timer = QtCore.QTimer(self)
        self._inspector_table_refresh_timer.setSingleShot(True)
        self._inspector_table_refresh_timer.setInterval(150)
        self._inspector_table_refresh_timer.timeout.connect(
            self._refresh_inspector_table
        )

        # Whether we need to save or not.
        self.dirty = False

        self._no_selection_slot = False
        self._copied_shapes = None
        self._batch_edit_warning_shown = False

        self.brightness_contrast_dialog = BrightnessContrastDialog(
            self.on_new_brightness_contrast, parent=self
        )

        # Main widgets and related state.
        self.label_dialog = LabelDialog(
            parent=self,
            labels=self._config["labels"],
            sort_labels=self._config["sort_labels"],
            show_text_field=self._config["show_label_text_field"],
            completion=self._config["label_completion"],
            fit_to_content=self._config["fit_to_content"],
            flags=self.label_flags,
        )

        self.label_list = LabelListWidget()
        self.label_list.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.last_open_dir = None

        self.flag_dock = self.flag_widget = None
        self.flag_dock = QtWidgets.QDockWidget(self.tr("Flags"), self)
        self.flag_dock.setObjectName("Flags")
        self.flag_widget = QtWidgets.QListWidget()
        if config["flags"]:
            self.image_flags = config["flags"]
            self.load_flags({k: False for k in self.image_flags})
        else:
            self.flag_dock.hide()
        self.flag_dock.setWidget(self.flag_widget)
        self.flag_widget.itemChanged.connect(self.set_dirty)
        self.flag_dock.setStyleSheet(get_dock_style())

        self.label_filter_combobox = LabelFilterComboBox(self)
        self.gid_filter_combobox = GroupIDFilterComboBox(self)
        self.shape_type_filter_combobox = ShapeTypeFilterComboBox(self)
        self.label_filter_combobox.hide()
        self.gid_filter_combobox.hide()
        self.shape_type_filter_combobox.hide()
        self._global_filter_keep_enabled = True  # default ON
        self._pending_filter_restore: Optional[FilterState] = None
        self._filter_state = (
            FilterState()
        )  # replaces _sticky_filter_state dict
        self._filter_index = None

        # Dataset filter index (SQLite derived cache)
        self._dataset_filter_index: Optional[DatasetFilterIndex] = None
        self._dataset_index_worker: Optional[DatasetIndexWorker] = None
        self._dataset_index_timer: Optional[QtCore.QTimer] = None
        self._pending_dataset_index_refresh_files: Set[str] = set()

        # Filter result navigation state
        self._filter_navigation_engine = FilterNavigationEngine()
        self._filter_navigation_active = False
        self._filter_navigation_files = []
        self._filter_navigation_initial_count = 0
        self._filter_navigation_state = None
        self.select_toggle_action = None

        self.label_list.item_selection_changed.connect(
            self.label_selection_changed
        )
        self.label_list.item_double_clicked.connect(self.edit_label)
        self.label_list.item_changed.connect(self.label_item_changed)
        self.label_list.item_dropped.connect(self.label_order_changed)
        self.shape_dock = QtWidgets.QDockWidget(self.tr("Objects"), self)
        self.shape_dock.setWidget(self.label_list)
        self.shape_dock.setStyleSheet(get_dock_style())

        self.unique_label_list = UniqueLabelQListWidget()
        self.unique_label_list.setToolTip(
            self.tr(
                "Select label to start annotating for it. "
                "Press 'Esc' to deselect."
            )
        )
        self.load_labels(self._config["labels"])
        self.label_dock = QtWidgets.QDockWidget(self.tr("Labels"), self)
        self.label_dock.setObjectName("Labels")
        self.label_dock.setWidget(self.unique_label_list)
        self.label_dock.setStyleSheet(get_dock_style())
        self.unique_label_list.setStyleSheet(
            "QListWidget::item { padding: 0; }"
        )

        self.shape_text_label = QLabel("Object Text")
        self.shape_text_edit = QPlainTextEdit()
        self.shape_text_edit.setStyleSheet(get_plain_text_edit_style())
        self.description_checkbox = QCheckBox()
        self.description_checkbox.setChecked(
            self._config["description_dock"]["show"]
        )
        self.description_checkbox.setStyleSheet(get_checkbox_indicator_style())
        self.description_checkbox.toggled.connect(
            self.toggle_description_visibility
        )
        self.description_dock = QtWidgets.QDockWidget(
            self.tr("Description"), self
        )
        self.description_dock.setObjectName("Description")
        self.description_dock.setWidget(self.shape_text_edit)
        self.description_dock.setStyleSheet(get_dock_style())

        self.file_search = SearchBar()
        self.file_search.setPlaceholderText(self.tr("Search files..."))
        self.file_search.setToolTip(
            self.tr(
                "Supported search modes:\n"
                "- Text: plain text search\n"
                "- Index: #N (e.g., #1, #10)\n"
                "- Regex: <pattern> (e.g., <\\.png$>)\n"
                "- Attributes: difficult::1, gid::0, shape::1, label::xxx, type::xxx\n"
                "- Score range: score::[0,0.5], score::(0,0.6], score::[0,0.6), score::(0,0.6)\n"
                "- Description: description::1, description::true, description::yes\n"
                "Press Enter to search."
            )
        )
        self.file_search.returnPressed.connect(self.file_search_changed)
        self.file_search.returnPressed.connect(self.file_search.setFocus)
        self.settings_button = QPushButton(self)
        self.settings_button.setFixedSize(32, 32)
        self.settings_button.setCursor(
            QtCore.Qt.CursorShape.PointingHandCursor
        )
        self.settings_button.setToolTip(self.tr("Settings"))
        self.settings_button.setIcon(utils.new_icon("settings", "svg"))
        self.settings_button.setIconSize(QtCore.QSize(28, 28))
        self.settings_button.setStyleSheet(get_settings_button_style())
        self.settings_button.clicked.connect(self.open_settings_dialog)
        self.file_list_widget = QtWidgets.QListWidget()
        self.file_status_icons = {
            True: _create_file_status_icon(FILE_CHECKED_COLOR),
            False: _create_file_status_icon(FILE_UNCHECKED_COLOR),
        }
        self.file_list_widget.itemSelectionChanged.connect(
            self.file_selection_changed
        )
        self.file_list_widget.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.file_list_widget.customContextMenuRequested.connect(
            self.pop_file_list_menu
        )
        self.file_list_widget.viewport().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.file_list_widget.viewport().customContextMenuRequested.connect(
            self.pop_file_list_menu
        )
        file_list_layout = QtWidgets.QVBoxLayout()
        file_list_layout.setContentsMargins(0, 0, 0, 0)
        file_list_layout.setSpacing(0)
        file_list_layout.addWidget(self.file_list_widget)
        self.file_dock = QtWidgets.QDockWidget("", self)
        self.file_dock.setObjectName("Files")
        self.file_dock.setTitleBarWidget(QtWidgets.QWidget(self))
        file_list_widget = QtWidgets.QWidget()
        file_list_widget.setLayout(file_list_layout)
        self.file_dock.setWidget(file_list_widget)
        self.file_dock.setStyleSheet(get_dock_style())

        self.zoom_widget = ZoomWidget()

        self.navigator_dialog = NavigatorDialog(self)
        self.navigator_dialog.navigator.navigation_requested.connect(
            self.on_navigator_request
        )
        self.navigator_dialog.closeEvent = self._navigator_close_event
        self.navigator_dialog.zoom_changed[int].connect(
            lambda zoom: self.on_navigator_zoom_changed(zoom, None)
        )
        self.navigator_dialog.zoom_changed[int, QtCore.QPoint].connect(
            self.on_navigator_zoom_changed
        )
        self.navigator_dialog.viewport_update_requested.connect(
            self.on_navigator_viewport_update_requested
        )
        self.async_exif_scanner = utils.AsyncExifScanner(self)
        self.async_exif_scanner.exif_detected.connect(self.on_exif_detected)

        self.setAcceptDrops(True)

        self.canvas = self.label_list.canvas = Canvas(
            parent=self,
            epsilon=self._config["canvas"]["epsilon"],
            double_click=self._config["canvas"]["double_click"],
            num_backups=self._config["canvas"]["num_backups"],
            wheel_rectangle_editing=self._config["canvas"][
                "wheel_rectangle_editing"
            ],
            auto_highlight_shape=self._config.get(
                "auto_highlight_shape", False
            ),
            attributes=self._config["canvas"].get("attributes", {}),
            rotation=self._config["canvas"].get("rotation", {}),
            mask=self._config["canvas"].get("mask", {}),
            brush=self._config["canvas"].get("brush", {}),
            cuboid=self._config["canvas"].get("cuboid", {}),
            double_click_edit_label=self._config["canvas"].get(
                "double_click_edit_label", True
            ),
        )
        self.canvas.zoom_request.connect(self.zoom_request)

        # Compare view support
        self.compare_view_manager = CompareViewManager(self.canvas, self)
        self.compare_view_manager.status_message.connect(self.status)
        self.compare_view_slider = CompareViewSlider(self)
        self.compare_view_slider.position_changed.connect(
            self.compare_view_manager.set_split_position
        )
        self.compare_view_slider.close_requested.connect(
            self.close_compare_view
        )
        self.compare_view_manager.compare_closed.connect(
            self.compare_view_slider.hide_slider
        )
        self.canvas.split_position_changed.connect(
            self.compare_view_slider.set_position
        )

        # Instance visibility shortcuts
        self._setup_instance_visibility_shortcuts()

        scroll_area = QScrollArea()
        scroll_area.setWidget(self.canvas)
        scroll_area.setWidgetResizable(True)
        self.scroll_bars = {
            Qt.Orientation.Vertical: scroll_area.verticalScrollBar(),
            Qt.Orientation.Horizontal: scroll_area.horizontalScrollBar(),
        }
        self.scroll_bars[Qt.Orientation.Vertical].valueChanged.connect(
            lambda: self.update_navigator_viewport()
        )
        self.scroll_bars[Qt.Orientation.Horizontal].valueChanged.connect(
            lambda: self.update_navigator_viewport()
        )
        self.canvas.scroll_request.connect(self.scroll_request)
        self.canvas.new_shape.connect(self.new_shape)
        self.canvas.show_shape.connect(self.show_shape)
        self.canvas.shape_moved.connect(self.set_dirty)
        self.canvas.shape_rotated.connect(self.set_dirty)
        self.canvas.selection_changed.connect(self.shape_selection_changed)
        # Inspector table refresh (debounced)
        self.canvas.new_shape.connect(self._schedule_inspector_table_refresh)
        self.canvas.shape_moved.connect(self._schedule_inspector_table_refresh)
        self.canvas.selection_changed.connect(
            self._schedule_inspector_table_refresh
        )
        self.canvas.drawing_polygon.connect(self.toggle_drawing_sensitive)
        self.canvas.edit_label_requested.connect(self.edit_label)
        # [Feature] support for automatically switching to editing mode
        # when the cursor moves over an object
        self.canvas.h_shape_is_hovered = self._config.get(
            "auto_highlight_shape", False
        )
        self._settings_runtime_applier.set_auto_switch_to_edit_mode(
            self._config["auto_switch_to_edit_mode"]
        )

        # Crosshair
        self.crosshair_settings = self._config["canvas"]["crosshair"]
        self.canvas.set_cross_line(**self.crosshair_settings)

        # Filter execution engine (computes matches & applies visibility)
        self._filter_engine = ShapeFilterEngine(
            label_list=self.label_list,
            canvas=self.canvas,
            get_label_info=lambda: self.label_info,
            update_select_toggle_tooltip=self._update_select_toggle_button_tooltip,
        )

        self._central_widget = scroll_area

        features = QtWidgets.QDockWidget.DockWidgetFeature(0)
        for dock in [
            "flag_dock",
            "label_dock",
            "shape_dock",
            "description_dock",
            "file_dock",
        ]:
            if self._config[dock]["closable"]:
                features = (
                    features
                    | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetClosable
                )
            if self._config[dock]["floatable"]:
                features = (
                    features
                    | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetFloatable
                )
            if self._config[dock]["movable"]:
                features = (
                    features
                    | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable
                )
            getattr(self, dock).setFeatures(features)
            if self._config[dock]["show"] is False:
                getattr(self, dock).setVisible(False)

        # Actions
        action = functools.partial(utils.new_action, self)
        shortcuts = self._config["shortcuts"]

        open_ = action(
            self.tr("Open File"),
            self.open_file,
            shortcuts["open"],
            "file",
            self.tr("Open image or label file"),
        )
        openvideo = action(
            self.tr("Open Video"),
            lambda: utils.open_video_file(self),
            shortcuts["open_video"],
            "video",
            self.tr("Open video file"),
        )
        opendir = action(
            self.tr("Open Dir"),
            self.open_folder_dialog,
            shortcuts["open_dir"],
            "open",
            self.tr("Open Dir"),
        )
        open_next_image = action(
            self.tr("Next Image"),
            self.open_next_image,
            shortcuts["open_next"],
            "next",
            self.tr("Open next image"),
            enabled=False,
        )
        open_prev_image = action(
            self.tr("Prev Image"),
            self.open_prev_image,
            shortcuts["open_prev"],
            "prev",
            self.tr("Open prev image"),
            enabled=False,
        )
        open_next_unchecked_image = action(
            self.tr("Next Unchecked Image"),
            self.open_next_unchecked_image,
            shortcuts["open_next_unchecked"],
            "next",
            self.tr("Open next unchecked image"),
            enabled=False,
        )
        open_prev_unchecked_image = action(
            self.tr("Prev Unchecked Image"),
            self.open_prev_unchecked_image,
            shortcuts["open_prev_unchecked"],
            "prev",
            self.tr("Open previous unchecked image"),
            enabled=False,
        )
        save = action(
            self.tr("Save"),
            self.save_file,
            shortcuts["save"],
            "save",
            self.tr("Save labels to file"),
            enabled=False,
        )
        save_as = action(
            self.tr("Save As"),
            self.save_file_as,
            shortcuts["save_as"],
            "save-as",
            self.tr("Save labels to a different file"),
            enabled=False,
        )
        run_all_images = action(
            self.tr("Auto Run"),
            lambda: utils.run_all_images(self),
            shortcuts["auto_run"],
            "auto-run",
            self.tr("Auto run all images at once"),
            enabled=False,
        )
        delete_file = action(
            self.tr("Delete File"),
            self.delete_file,
            shortcuts["delete_file"],
            "delete",
            self.tr("Delete current label file"),
            enabled=False,
        )
        delete_image_file = action(
            self.tr("Delete Image File"),
            self.delete_image_file,
            shortcuts["delete_image_file"],
            "delete",
            self.tr("Delete current image file"),
            enabled=True,
        )
        toggle_annotation_checked = action(
            self.tr("Mark as Checked"),
            self.set_annotation_checked,
            shortcuts.get("toggle_annotation_checked"),
            None,
            self.tr("Mark current annotation as checked"),
            checkable=True,
            enabled=False,
        )

        toggle_compare_view = action(
            self.tr("Compare View"),
            self.toggle_compare_view,
            shortcuts.get("toggle_compare_view"),
            "compare",
            self.tr("Toggle split-screen compare view"),
            enabled=True,
        )

        change_output_dir = action(
            self.tr("Change Output Dir"),
            slot=self.change_output_dir_dialog,
            shortcut=shortcuts["save_to"],
            icon="open",
            tip=self.tr("Change where annotations are loaded/saved"),
        )

        save_auto = action(
            text=self.tr("Save Automatically"),
            slot=lambda x: self._config.update({"auto_save": x}),
            icon=None,
            tip=self.tr("Save automatically"),
            checkable=True,
            enabled=True,
            checked=self._config["auto_save"],
        )

        save_with_image_data = action(
            text=self.tr("Save With Image Data"),
            slot=lambda x: self._config.update({"store_data": x}),
            icon=None,
            tip=self.tr("Save image data in label file"),
            checkable=True,
            checked=self._config["store_data"],
        )

        close = action(
            self.tr("Close"),
            self.close_file,
            shortcuts["close"],
            "cancel",
            self.tr("Close current file"),
        )

        keep_prev_mode = action(
            self.tr("Keep Previous Annotation"),
            lambda x: self._config.update({"keep_prev": x}),
            shortcuts["toggle_keep_prev_mode"],
            None,
            self.tr('Toggle "Keep Previous Annotation" mode'),
            checkable=True,
            checked=self._config["keep_prev"],
        )

        auto_use_last_label_mode = action(
            self.tr("Auto Use Last Label"),
            lambda x: self._config.update({"auto_use_last_label": x}),
            shortcuts["toggle_auto_use_last_label"],
            None,
            self.tr('Toggle "Auto Use Last Label" mode'),
            checkable=True,
            checked=self._config["auto_use_last_label"],
        )

        auto_use_last_gid_mode = action(
            self.tr("Auto Use Last Group ID"),
            lambda x: self._config.update({"auto_use_last_gid": x}),
            shortcuts["toggle_auto_use_last_gid"],
            None,
            self.tr('Toggle "Auto Use Last Group ID" mode'),
            checkable=True,
            checked=self._config["auto_use_last_gid"],
        )

        use_system_clipboard = action(
            self.tr("Use System Clipboard"),
            self.toggle_system_clipboard,
            tip=self.tr("Use system clipboard for copy and paste"),
            checkable=True,
            checked=self._config["system_clipboard"],
            enabled=True,
        )

        visibility_shapes_mode = action(
            self.tr("Visibility Shapes"),
            self.toggle_visibility_shapes,
            shortcuts["toggle_visibility_shapes"],
            None,
            self.tr('Toggle "Visibility Shapes" mode'),
            checkable=True,
            checked=self._config["show_shapes"],
        )

        create_mode = action(
            self.tr("Create Polygons"),
            lambda: self.toggle_draw_mode(False, create_mode="polygon"),
            shortcuts["create_polygon"],
            "polygon",
            self.tr("Start drawing polygons"),
            enabled=False,
        )
        create_brush_polygon_mode = action(
            self.tr("Create Brush Polygons"),
            self.toggle_brush_polygon_mode,
            shortcuts["create_brush_polygon"],
            "brush_polygon",
            self.tr("Toggle brush mode for drawing polygons"),
            enabled=False,
        )
        create_rectangle_mode = action(
            self.tr("Create Rectangle"),
            lambda: self.toggle_draw_mode(False, create_mode="rectangle"),
            shortcuts["create_rectangle"],
            "rectangle",
            self.tr("Start drawing rectangles"),
            enabled=False,
        )
        create_rotation_mode = action(
            self.tr("Create Rotation"),
            lambda: self.toggle_draw_mode(False, create_mode="rotation"),
            shortcuts["create_rotation"],
            "rotation",
            self.tr("Start drawing rotations"),
            enabled=False,
        )
        create_quadrilateral_mode = action(
            self.tr("Create Quadrilateral"),
            lambda: self.toggle_draw_mode(False, create_mode="quadrilateral"),
            shortcuts["create_quadrilateral"],
            "quadrilateral",
            self.tr("Start drawing quadrilaterals (4 points, auto-closed)"),
            enabled=False,
        )
        create_circle_mode = action(
            self.tr("Create Circle"),
            lambda: self.toggle_draw_mode(False, create_mode="circle"),
            shortcuts["create_circle"],
            "circle",
            self.tr("Start drawing circles"),
            enabled=False,
        )
        create_line_mode = action(
            self.tr("Create Line"),
            lambda: self.toggle_draw_mode(False, create_mode="line"),
            shortcuts["create_line"],
            "line",
            self.tr("Start drawing lines"),
            enabled=False,
        )
        create_point_mode = action(
            self.tr("Create Point"),
            lambda: self.toggle_draw_mode(False, create_mode="point"),
            shortcuts["create_point"],
            "point",
            self.tr("Start drawing points"),
            enabled=False,
        )
        create_line_strip_mode = action(
            self.tr("Create LineStrip"),
            lambda: self.toggle_draw_mode(False, create_mode="linestrip"),
            shortcuts["create_linestrip"],
            "line-strip",
            self.tr("Start drawing linestrip. Ctrl+LeftClick ends creation."),
            enabled=False,
        )
        create_cuboid_mode = action(
            self.tr("Create Cuboid"),
            lambda: self.toggle_draw_mode(False, create_mode="cuboid"),
            shortcuts.get("create_cuboid"),
            "cuboid",
            self.tr("Start drawing cuboids from rectangle"),
            enabled=False,
        )
        digit_shortcut_0 = action(
            self.tr("Digit Shortcut 0"),
            lambda: self.create_digit_mode(0),
            "0",
            "digit0",
            enabled=False,
        )
        digit_shortcut_1 = action(
            self.tr("Digit Shortcut 1"),
            lambda: self.create_digit_mode(1),
            "1",
            "digit1",
            enabled=False,
        )
        digit_shortcut_2 = action(
            self.tr("Digit Shortcut 2"),
            lambda: self.create_digit_mode(2),
            "2",
            "digit2",
            enabled=False,
        )
        digit_shortcut_3 = action(
            self.tr("Digit Shortcut 3"),
            lambda: self.create_digit_mode(3),
            "3",
            "digit3",
            enabled=False,
        )
        digit_shortcut_4 = action(
            self.tr("Digit Shortcut 4"),
            lambda: self.create_digit_mode(4),
            "4",
            "digit4",
            enabled=False,
        )
        digit_shortcut_5 = action(
            self.tr("Digit Shortcut 5"),
            lambda: self.create_digit_mode(5),
            "5",
            "digit5",
            enabled=False,
        )
        digit_shortcut_6 = action(
            self.tr("Digit Shortcut 6"),
            lambda: self.create_digit_mode(6),
            "6",
            "digit6",
            enabled=False,
        )
        digit_shortcut_7 = action(
            self.tr("Digit Shortcut 7"),
            lambda: self.create_digit_mode(7),
            "7",
            "digit7",
            enabled=False,
        )
        digit_shortcut_8 = action(
            self.tr("Digit Shortcut 8"),
            lambda: self.create_digit_mode(8),
            "8",
            "digit8",
            enabled=False,
        )
        digit_shortcut_9 = action(
            self.tr("Digit Shortcut 9"),
            lambda: self.create_digit_mode(9),
            "9",
            "digit9",
            enabled=False,
        )
        enter_keypoint_fill_mode = action(
            self.tr("Enter Keypoint Fill Mode"),
            self.enter_keypoint_fill_mode,
            shortcuts.get("enter_keypoint_fill_mode", "K"),
            None,
            self.tr("Fill missing keypoints for selected person"),
            enabled=True,
        )
        toggle_keypoint_tool_window = action(
            self.tr("Toggle Keypoint Tool Window"),
            self.toggle_keypoint_tool_window,
            shortcuts.get("toggle_keypoint_tool_window", "Ctrl+K"),
            None,
            self.tr("Open keypoint fill tool window"),
            enabled=True,
        )
        switch_to_prev_person = action(
            self.tr("Switch to Previous Person"),
            self.switch_to_prev_person,
            shortcuts.get("switch_to_prev_person", "Ctrl+Shift+["),
            None,
            self.tr("Switch to previous person in keypoint tool"),
            enabled=True,
        )
        switch_to_next_person = action(
            self.tr("Switch to Next Person"),
            self.switch_to_next_person,
            shortcuts.get("switch_to_next_person", "Ctrl+Shift+]"),
            None,
            self.tr("Switch to next person in keypoint tool"),
            enabled=True,
        )
        edit_mode = action(
            self.tr("Edit Object"),
            self.set_edit_mode,
            shortcuts["edit_polygon"],
            "edit",
            self.tr("Move and edit the selected polygons"),
            enabled=False,
        )
        group_selected_shapes = action(
            self.tr("Group Selected Shapes"),
            self.group_selected_shapes,
            shortcuts["group_selected_shapes"],
            None,
            self.tr("Group shapes by assigning a same group_id"),
            enabled=True,
        )
        ungroup_selected_shapes = action(
            self.tr("Ungroup Selected Shapes"),
            self.ungroup_selected_shapes,
            shortcuts["ungroup_selected_shapes"],
            None,
            self.tr("Ungroup shapes"),
            enabled=True,
        )

        delete = action(
            self.tr("Delete"),
            self.delete_selected_shape,
            shortcuts["delete_polygon"],
            "cancel",
            self.tr("Delete the selected polygons"),
            enabled=False,
        )
        duplicate = action(
            self.tr("Duplicate Polygons"),
            self.duplicate_selected_shape,
            shortcuts["duplicate_polygon"],
            "copy",
            self.tr("Create a duplicate of the selected polygons"),
            enabled=False,
        )
        copy = action(
            self.tr("Copy Object"),
            self.copy_selected_shape,
            shortcuts["copy_polygon"],
            "copy",
            self.tr("Copy selected polygons to clipboard"),
            enabled=False,
        )
        paste = action(
            self.tr("Paste Object"),
            self.paste_selected_shape,
            shortcuts["paste_polygon"],
            "paste",
            self.tr("Paste copied polygons"),
            enabled=self._config["system_clipboard"],
        )
        undo_last_point = action(
            self.tr("Undo last point"),
            self.canvas.undo_last_point,
            shortcuts["undo_last_point"],
            "undo",
            self.tr("Undo last drawn point"),
            enabled=False,
        )
        remove_point = action(
            text=self.tr("Remove Selected Point"),
            slot=self.remove_selected_point,
            shortcut=shortcuts["remove_selected_point"],
            icon="edit",
            tip=self.tr("Remove selected point from polygon"),
            enabled=False,
        )

        undo = action(
            self.tr("Undo"),
            self.undo_shape_edit,
            shortcuts["undo"],
            "undo",
            self.tr("Undo last add and edit of shape"),
            enabled=False,
        )
        hide_selected_polygons = action(
            self.tr("Hide Selected Polygons"),
            self.hide_selected_polygons,
            shortcuts["hide_selected_polygons"],
            None,
            self.tr("Hide selected polygons"),
            enabled=True,
        )
        show_hidden_polygons = action(
            self.tr("Show Hidden Polygons"),
            self.show_hidden_polygons,
            shortcuts["show_hidden_polygons"],
            None,
            self.tr("Show hidden polygons"),
            enabled=True,
        )

        overview = action(
            self.tr("Overview"),
            self.overview,
            shortcuts["show_overview"],
            icon="overview",
            tip=self.tr("Show annotations statistics"),
        )
        save_crop = action(
            self.tr("Save Cropped Image"),
            lambda: utils.save_crop(self),
            icon="crop",
            tip=self.tr(
                "Save cropped image. (Support rectangle/rotation/polygon shape_type)"
            ),
        )
        save_visualization_image = action(
            self.tr("Save Visualization Image"),
            lambda: utils.save_visualization(self, export_type="image"),
            icon="file",
            tip=self.tr("Save visualization image"),
        )
        save_visualization_video = action(
            self.tr("Save Visualization Video"),
            lambda: utils.save_visualization(self, export_type="video"),
            icon="video",
            tip=self.tr("Save visualization video"),
        )
        digit_shortcut_manager = action(
            self.tr("Digit Shortcut Manager"),
            self.digit_shortcut_manager,
            shortcuts["edit_digit_shortcut"],
            icon="edit",
            tip=self.tr(
                "Manage Digit Shortcuts: Assign Drawing Modes and Labels to Number Keys"
            ),
        )
        digit_relabel_manager = action(
            self.tr("Digit Relabel Manager"),
            self.digit_rename_shortcut_manager,
            shortcuts.get("edit_digit_relabel", "Alt+R"),
            icon="edit",
            tip=self.tr(
                "Manage Digit Relabel Shortcuts: Assign Labels to Number Keys for Edit Mode"
            ),
        )
        switch_digit_page = action(
            self.tr("Switch Digit Shortcut Page"),
            self.switch_digit_shortcut_page,
            shortcuts["switch_digit_page"],
            tip=self.tr("Switch to the next digit shortcut page"),
        )
        label_manager = action(
            self.tr("Label Manager"),
            self.label_manager,
            shortcuts["edit_labels"],
            icon="edit",
            tip=self.tr(
                "Manage Labels: Rename, Delete, Hide/Show, Adjust Color"
            ),
        )
        gid_manager = action(
            self.tr("Group ID Manager"),
            self.gid_manager,
            shortcuts["edit_group_id"],
            icon="edit",
            tip=self.tr("Manage Group ID"),
        )
        shape_manager = action(
            self.tr("Shape Manager"),
            self.shape_manager,
            shortcuts["edit_shapes"],
            icon="edit",
            tip=self.tr("Manage Shapes: Add, Delete, Remove"),
            enabled=False,
        )
        copy_coordinates = action(
            self.tr("Copy Coordinates"),
            self.copy_shape_coordinates,
            icon="copy",
            tip=self.tr("Copy shape coordinates to clipboard"),
            enabled=False,
        )
        union_selection = action(
            self.tr("Union Selection"),
            self.union_selection,
            shortcuts["union_selected_shapes"],
            icon="union",
            tip=self.tr("Union multiple selected rectangle shapes"),
            enabled=False,
        )
        shape_converter = action(
            self.tr("Shape Converter"),
            lambda: utils.open_shape_converter(self),
            icon="convert",
            tip=self.tr("Open shape converter"),
        )
        open_chatbot = action(
            self.tr("ChatBot"),
            self.open_chatbot,
            shortcuts["open_chatbot"],
            icon="psyduck",
            tip=self.tr("Open chatbot dialog"),
        )
        open_vqa = action(
            self.tr("VQA"),
            self.open_vqa,
            shortcuts["open_vqa"],
            icon="husky",
            tip=self.tr("Open VQA dialog"),
        )
        open_classifier = action(
            self.tr("Classifier"),
            self.open_classifier,
            shortcuts["open_classifier"],
            icon="ragdoll",
            tip=self.tr("Open classifier dialog"),
        )
        open_paddleocr = action(
            self.tr("PaddleOCR"),
            self.open_paddleocr,
            shortcuts["open_paddleocr"],
            icon="paddlepaddle",
            tip=self.tr("Open PaddleOCR dialog"),
        )
        documentation = action(
            self.tr("Documentation"),
            self.documentation,
            icon="docs",
            tip=self.tr("Show documentation"),
        )
        about = action(
            self.tr("About"),
            self.about,
            icon="help",
            tip=self.tr("Open about dialog"),
        )

        loop_thru_labels = action(
            self.tr("Loop Through Labels"),
            self.loop_thru_labels,
            shortcut=shortcuts["loop_thru_labels"],
            icon="loop",
            tip=self.tr("Loop through labels"),
            enabled=False,
        )
        loop_select_labels = action(
            self.tr("Loop Select Labels"),
            self.loop_select_labels,
            shortcut=shortcuts["loop_select_labels"],
            icon="circle-selection",
            tip=self.tr("Loop select labels"),
            enabled=False,
        )
        select_toggle_shapes = action(
            self.tr("Toggle Shapes Visibility"),
            self.toggle_select_all,
            icon="eye",
            tip=self.tr("Hide all shapes"),
            enabled=False,
        )
        self.select_toggle_action = select_toggle_shapes

        ultralytics_train = action(
            "Ultralytics",
            lambda: self.start_training("ultralytics"),
            icon="ultralytics",
        )

        zoom = QtWidgets.QWidgetAction(self)
        zoom.setDefaultWidget(self.zoom_widget)
        self.zoom_widget.setWhatsThis(
            str(
                self.tr(
                    "Zoom in or out of the image. Also accessible with "
                    "{} and {} from the canvas."
                )
            ).format(
                utils.fmt_shortcut(
                    f"{shortcuts['zoom_in']},{shortcuts['zoom_out']}"
                ),
                utils.fmt_shortcut(self.tr("Ctrl+Wheel")),
            )
        )
        self.zoom_widget.setEnabled(False)

        zoom_in = action(
            self.tr("Zoom In"),
            functools.partial(self.add_zoom, 1.1),
            shortcuts["zoom_in"],
            "zoom-in",
            self.tr("Increase zoom level"),
            enabled=False,
        )
        zoom_out = action(
            self.tr("Zoom Out"),
            functools.partial(self.add_zoom, 0.9),
            shortcuts["zoom_out"],
            "zoom-out",
            self.tr("Decrease zoom level"),
            enabled=False,
        )
        zoom_org = action(
            self.tr("Original Size"),
            functools.partial(self.set_zoom, 100),
            shortcuts["zoom_to_original"],
            "zoom",
            self.tr("Zoom to original size"),
            enabled=False,
        )
        keep_prev_scale = action(
            self.tr("Keep Previous Scale"),
            lambda x: self._config.update({"keep_prev_scale": x}),
            tip=self.tr("Keep previous zoom scale"),
            checkable=True,
            checked=self._config["keep_prev_scale"],
            enabled=True,
        )
        keep_prev_viewport = action(
            self.tr("Keep Previous Viewport"),
            lambda x: self._config.update({"keep_prev_viewport": x}),
            tip=self.tr(
                "Keep previous zoom scale and view position when switching images"
            ),
            checkable=True,
            checked=self._config.get("keep_prev_viewport", False),
            enabled=True,
        )
        reset_current_image_view = action(
            self.tr("重置当前图像视图"),
            self.reset_current_image_view,
            tip=self.tr("重置当前图像的视口状态"),
            enabled=True,
        )
        reset_views_from_current_to_end = action(
            self.tr("重置从当前到末尾图像视图"),
            self.reset_views_from_current_to_end,
            tip=self.tr("重置当前图像及其后续图像的视口状态"),
            enabled=True,
        )
        reset_all_image_views = action(
            self.tr("重置所有图像视图"),
            self.reset_all_image_views,
            tip=self.tr("重置所有图像的视口状态"),
            enabled=True,
        )
        keep_prev_brightness = action(
            self.tr("Keep Previous Brightness"),
            lambda x: self._config.update({"keep_prev_brightness": x}),
            tip=self.tr("Keep previous brightness"),
            checkable=True,
            checked=self._config["keep_prev_brightness"],
            enabled=True,
        )
        keep_prev_contrast = action(
            self.tr("Keep Previous Contrast"),
            lambda x: self._config.update({"keep_prev_contrast": x}),
            tip=self.tr("Keep previous contrast"),
            checkable=True,
            checked=self._config["keep_prev_contrast"],
            enabled=True,
        )
        fit_window = action(
            self.tr("Fit Window"),
            self.set_fit_window,
            shortcuts["fit_window"],
            "fit-window",
            self.tr("Zoom follows window size"),
            checkable=True,
            enabled=False,
        )
        fit_width = action(
            self.tr("Fit Width"),
            self.set_fit_width,
            shortcuts["fit_width"],
            "fit-width",
            self.tr("Zoom follows window width"),
            checkable=True,
            enabled=False,
        )
        brightness_contrast = action(
            self.tr("Set Brightness Contrast"),
            self.brightness_contrast,
            None,
            "color",
            "Adjust brightness and contrast",
            enabled=False,
        )
        set_cross_line = action(
            self.tr("Set Cross Line"),
            self.set_cross_line,
            tip=self.tr("Adjust cross line for mouse position"),
            icon="cartesian",
        )
        show_groups = action(
            self.tr("Show Groups"),
            lambda x: self.set_canvas_params("show_groups", x),
            tip=self.tr("Show shape groups"),
            icon=None,
            checkable=True,
            checked=self._config["show_groups"],
            enabled=True,
            auto_trigger=True,
        )
        show_masks = action(
            self.tr("Show Masks"),
            lambda x: self.set_canvas_params("show_masks", x),
            shortcut=shortcuts["show_masks"],
            tip=self.tr("Show semi-transparent masks for shapes"),
            icon=None,
            checkable=True,
            checked=self._config["show_masks"],
            enabled=True,
            auto_trigger=True,
        )
        show_texts = action(
            self.tr("Show Texts"),
            lambda x: self.set_canvas_params("show_texts", x),
            shortcut=shortcuts["show_texts"],
            tip=self.tr("Show text above shapes"),
            icon=None,
            checkable=True,
            checked=self._config["show_texts"],
            enabled=True,
            auto_trigger=True,
        )
        show_labels = action(
            self.tr("Show Labels"),
            lambda x: self.set_canvas_params("show_labels", x),
            shortcut=shortcuts["show_labels"],
            tip=self.tr("Show label inside shapes"),
            icon=None,
            checkable=True,
            checked=self._config["show_labels"],
            enabled=True,
            auto_trigger=True,
        )
        show_scores = action(
            self.tr("Show Scores"),
            lambda x: self.set_canvas_params("show_scores", x),
            tip=self.tr("Show score inside shapes"),
            icon=None,
            checkable=True,
            checked=self._config["show_scores"],
            enabled=True,
            auto_trigger=True,
        )
        show_attributes = action(
            self.tr("Show Attributes"),
            lambda x: self.set_canvas_params("show_attributes", x),
            shortcut=shortcuts["show_attributes"],
            tip=self.tr("Show attribute inside shapes"),
            icon=None,
            checkable=True,
            checked=self._config["show_attributes"],
            enabled=True,
            auto_trigger=True,
        )
        show_degrees = action(
            self.tr("Show Degress"),
            lambda x: self.set_canvas_params("show_degrees", x),
            tip=self.tr("Show degrees above rotated shapes"),
            icon=None,
            checkable=True,
            checked=self._config["show_degrees"],
            enabled=True,
            auto_trigger=True,
        )
        show_linking = action(
            self.tr("Show KIE Linking"),
            lambda x: self.set_canvas_params("show_linking", x),
            shortcut=shortcuts["show_linking"],
            tip=self.tr("Show KIE linking between key and value"),
            icon=None,
            checkable=True,
            checked=self._config["show_linking"],
            enabled=True,
            auto_trigger=True,
        )
        label_on_selection = action(
            self.tr("Label on Selection"),
            lambda x: self.set_canvas_params("label_on_selection", x),
            tip=self.tr("Show labels only for selected shapes"),
            icon=None,
            checkable=True,
            checked=self._config.get("label_on_selection", False),
            enabled=True,
            auto_trigger=True,
        )
        pose_view = action(
            self.tr("Pose View"),
            self.toggle_pose_view,
            tip=self.tr(
                "Toggle pose keypoint label rendering (colored boxes,"
                " skeleton, anti-occlusion layout)"
            ),
            icon=None,
            checkable=True,
            checked=self._config.get("pose_view", {}).get("enabled", False),
            enabled=True,
        )

        # Languages
        select_lang_en = action(
            "English",
            functools.partial(self.set_language, "en_US"),
            icon="us",
            checkable=True,
            checked=self._config["language"] == "en_US",
            enabled=self._config["language"] != "en_US",
        )
        select_lang_zh = action(
            "中文",
            functools.partial(self.set_language, "zh_CN"),
            icon="cn",
            checkable=True,
            checked=self._config["language"] == "zh_CN",
            enabled=self._config["language"] != "zh_CN",
        )

        select_lang_jp = action(
            "日本語",
            functools.partial(self.set_language, "ja_JP"),
            icon="ja",
            checkable=True,
            checked=self._config["language"] == "ja_JP",
            enabled=self._config["language"] != "ja_JP",
        )
        select_lang_ko = action(
            "한국어",
            functools.partial(self.set_language, "ko_KR"),
            icon="ko",
            checkable=True,
            checked=self._config["language"] == "ko_KR",
            enabled=self._config["language"] != "ko_KR",
        )

        # Theme menu options (System / Light / Dark)
        theme_mode_actions = []
        theme_group = QtGui.QActionGroup(self)
        theme_group.setExclusive(True)
        self._theme_actions = {}
        current_appearance = self._config.get("theme", "auto")
        for _mode, _label in (
            ("auto", self.tr("System")),
            ("light", self.tr("Light")),
            ("dark", self.tr("Dark")),
        ):
            _act = QtGui.QAction(_label, theme_group)
            _act.setCheckable(True)
            _act.setChecked(current_appearance == _mode)
            _act.setData(_mode)
            _act.triggered.connect(
                functools.partial(self._on_theme_changed, _mode)
            )
            theme_mode_actions.append(_act)
            self._theme_actions[_mode] = _act

        # Upload
        upload_export_icon = "label"
        upload_image_flags_file = action(
            self.tr("Image Flags"),
            lambda: utils.upload_image_flags_file(self),
            None,
            icon=upload_export_icon,
            tip=self.tr("Upload Custom Image Flags File"),
        )
        upload_label_flags_file = action(
            self.tr("Label Flags"),
            lambda: utils.upload_label_flags_file(self, LABEL_OPACITY),
            None,
            icon=upload_export_icon,
            tip=self.tr("Upload Custom Label Flags File"),
        )
        upload_shape_attrs_file = action(
            self.tr("Attributes"),
            lambda: utils.upload_shape_attrs_file(self, LABEL_OPACITY),
            None,
            icon=upload_export_icon,
            tip=self.tr("Upload Custom Attributes File"),
        )
        upload_label_classes_file = action(
            self.tr("Label Classes"),
            lambda: utils.upload_label_classes_file(self),
            None,
            icon=upload_export_icon,
            tip=self.tr("Upload Custom Label Classes File"),
        )
        upload_yolo_hbb_annotation = action(
            self.tr("YOLO HBB"),
            lambda: utils.upload_yolo_annotation(self, "hbb", LABEL_OPACITY),
            None,
            icon=upload_export_icon,
            tip=self.tr(
                "Upload Custom YOLO Horizontal Bounding Boxes Annotations"
            ),
        )
        upload_yolo_obb_annotation = action(
            self.tr("YOLO OBB"),
            lambda: utils.upload_yolo_annotation(self, "obb", LABEL_OPACITY),
            None,
            icon=upload_export_icon,
            tip=self.tr(
                "Upload Custom YOLO Oriented Bounding Boxes Annotations"
            ),
        )
        upload_yolo_seg_annotation = action(
            self.tr("YOLO Seg"),
            lambda: utils.upload_yolo_annotation(self, "seg", LABEL_OPACITY),
            None,
            icon=upload_export_icon,
            tip=self.tr("Upload Custom YOLO Segmentation Annotations"),
        )
        upload_yolo_pose_annotation = action(
            self.tr("YOLO Pose"),
            lambda: utils.upload_yolo_annotation(self, "pose", LABEL_OPACITY),
            None,
            icon=upload_export_icon,
            tip=self.tr("Upload Custom YOLO Pose Annotations"),
        )
        upload_voc_det_annotation = action(
            self.tr("VOC Detection"),
            lambda: utils.upload_voc_annotation(self, "rectangle"),
            None,
            icon=upload_export_icon,
            tip=self.tr("Upload Custom Pascal VOC Detection Annotations"),
        )
        upload_voc_seg_annotation = action(
            self.tr("VOC Segmentation"),
            lambda: utils.upload_voc_annotation(self, "polygon"),
            None,
            icon=upload_export_icon,
            tip=self.tr("Upload Custom Pascal VOC Segmentation Annotations"),
        )
        upload_coco_det_annotation = action(
            self.tr("COCO Detection"),
            lambda: utils.upload_coco_annotation(self, "rectangle"),
            None,
            icon=upload_export_icon,
            tip=self.tr("Upload Custom COCO Detection Annotations"),
        )
        upload_coco_seg_annotation = action(
            self.tr("COCO Segmentation"),
            lambda: utils.upload_coco_annotation(self, "polygon"),
            None,
            icon=upload_export_icon,
            tip=self.tr(
                "Upload Custom COCO Instance Segmentation Annotations"
            ),
        )
        upload_coco_pose_annotation = action(
            self.tr("COCO Keypoints"),
            lambda: utils.upload_coco_annotation(self, "pose"),
            None,
            icon=upload_export_icon,
            tip=self.tr("Upload Custom COCO Keypoint Annotations"),
        )
        upload_dota_annotation = action(
            self.tr("DOTA"),
            lambda: utils.upload_dota_annotation(self),
            None,
            icon=upload_export_icon,
            tip=self.tr("Upload Custom DOTA Annotations"),
        )
        upload_mask_annotation = action(
            self.tr("MASK"),
            lambda: utils.upload_mask_annotation(self, LABEL_OPACITY),
            None,
            icon=upload_export_icon,
            tip=self.tr("Upload Custom MASK Annotations"),
        )
        upload_mot_annotation = action(
            self.tr("MOT"),
            lambda: utils.upload_mot_annotation(self, LABEL_OPACITY),
            None,
            icon=upload_export_icon,
            tip=self.tr("Upload Custom Multi-Object-Tracking Annotations"),
        )
        upload_odvg_annotation = action(
            self.tr("ODVG"),
            lambda: utils.upload_odvg_annotation(self),
            None,
            icon=upload_export_icon,
            tip=self.tr(
                "Upload Custom Object Detection Visual Grounding Annotations"
            ),
        )
        upload_mmgd_annotation = action(
            self.tr("MM-Grounding-DINO"),
            lambda: utils.upload_mmgd_annotation(self, LABEL_OPACITY),
            None,
            icon=upload_export_icon,
            tip=self.tr("Upload Custom MM-Grounding-DINO Annotations"),
        )
        upload_ppocr_rec_annotation = action(
            self.tr("PPOCR Rec"),
            lambda: utils.upload_ppocr_annotation(self, "rec"),
            None,
            icon=upload_export_icon,
            tip=self.tr("Upload Custom PPOCR Recognition Annotations"),
        )
        upload_ppocr_kie_annotation = action(
            self.tr("PPOCR KIE"),
            lambda: utils.upload_ppocr_annotation(self, "kie"),
            None,
            icon=upload_export_icon,
            tip=self.tr(
                "Upload Custom PPOCR Key Information Extraction (KIE - Semantic Entity Recognition & Relation Extraction) Annotations"
            ),
        )
        upload_vlm_r1_ovd_annotation = action(
            self.tr("VLM-R1 OVD"),
            lambda: utils.upload_vlm_r1_ovd_annotation(self),
            None,
            icon=upload_export_icon,
            tip=self.tr("Upload Custom VLM-R1 OVD Annotations"),
        )

        # Export
        export_yolo_hbb_annotation = action(
            self.tr("YOLO HBB"),
            lambda: utils.export_yolo_annotation(self, "hbb"),
            None,
            icon=upload_export_icon,
            tip=self.tr(
                "Export Custom YOLO Horizontal Bounding Boxes Annotations"
            ),
        )
        export_yolo_obb_annotation = action(
            self.tr("YOLO OBB"),
            lambda: utils.export_yolo_annotation(self, "obb"),
            None,
            icon=upload_export_icon,
            tip=self.tr(
                "Export Custom YOLO Oriented Bounding Boxes Annotations"
            ),
        )
        export_yolo_seg_annotation = action(
            self.tr("YOLO Seg"),
            lambda: utils.export_yolo_annotation(self, "seg"),
            None,
            icon=upload_export_icon,
            tip=self.tr("Export Custom YOLO Segmentation Annotations"),
        )
        export_yolo_pose_annotation = action(
            self.tr("YOLO Pose"),
            lambda: utils.export_yolo_annotation(self, "pose"),
            None,
            icon=upload_export_icon,
            tip=self.tr("Export Custom YOLO Pose Annotations"),
        )
        export_voc_det_annotation = action(
            self.tr("VOC Detection"),
            lambda: utils.export_voc_annotation(self, "rectangle"),
            None,
            icon=upload_export_icon,
            tip=self.tr("Export Custom PASCAL VOC Detection Annotations"),
        )
        export_voc_seg_annotation = action(
            self.tr("VOC Segmentation"),
            lambda: utils.export_voc_annotation(self, "polygon"),
            None,
            icon=upload_export_icon,
            tip=self.tr("Export Custom PASCAL VOC Segmentation Annotations"),
        )
        export_coco_det_annotation = action(
            self.tr("COCO Detection"),
            lambda: utils.export_coco_annotation(self, "rectangle"),
            None,
            icon=upload_export_icon,
            tip=self.tr("Export Custom COCO Rectangle Annotations"),
        )
        export_coco_seg_annotation = action(
            self.tr("COCO Segmentation"),
            lambda: utils.export_coco_annotation(self, "polygon"),
            None,
            icon=upload_export_icon,
            tip=self.tr(
                "Export Custom COCO Instance Segmentation Annotations"
            ),
        )
        export_coco_pose_annotation = action(
            self.tr("COCO Keypoints"),
            lambda: utils.export_coco_annotation(self, "pose"),
            None,
            icon=upload_export_icon,
            tip=self.tr("Export Custom COCO Keypoint Annotations"),
        )
        export_dota_annotation = action(
            self.tr("DOTA"),
            lambda: utils.export_dota_annotation(self),
            None,
            icon=upload_export_icon,
            tip=self.tr("Export Custom DOTA Annotations"),
        )
        export_mask_annotation = action(
            self.tr("MASK"),
            lambda: utils.export_mask_annotation(self),
            None,
            icon=upload_export_icon,
            tip=self.tr("Export Custom MASK Annotations - RGB/Gray"),
        )
        export_mot_annotation = action(
            self.tr("MOT"),
            lambda: utils.export_mot_annotation(self, "mot"),
            None,
            icon=upload_export_icon,
            tip=self.tr("Export Custom Multi-Object-Tracking Annotations"),
        )
        export_mots_annotation = action(
            self.tr("MOTS"),
            lambda: utils.export_mot_annotation(self, "mots"),
            None,
            icon=upload_export_icon,
            tip=self.tr(
                "Export Custom Multi-Object-Tracking-Segmentation Annotations"
            ),
        )
        export_odvg_annotation = action(
            self.tr("ODVG"),
            lambda: utils.export_odvg_annotation(self),
            None,
            icon=upload_export_icon,
            tip=self.tr(
                "Export Custom Object Detection Visual Grounding Annotations"
            ),
        )
        export_pporc_rec_annotation = action(
            self.tr("PPOCR Rec"),
            lambda: utils.export_pporc_annotation(self, "rec"),
            None,
            icon=upload_export_icon,
            tip=self.tr("Export Custom PPOCR Recognition Annotations"),
        )
        export_pporc_kie_annotation = action(
            self.tr("PPOCR KIE"),
            lambda: utils.export_pporc_annotation(self, "kie"),
            None,
            icon=upload_export_icon,
            tip=self.tr(
                "Export Custom PPOCR Key Information Extraction (KIE - Semantic Entity Recognition & Relation Extraction) Annotations"
            ),
        )
        export_vlm_r1_ovd_annotation = action(
            self.tr("VLM-R1 OVD"),
            lambda: utils.export_vlm_r1_ovd_annotation(self),
            None,
            icon=upload_export_icon,
            tip=self.tr("Export Custom VLM-R1 OVD Annotations"),
        )

        # Group zoom controls into a list for easier toggling.
        zoom_actions = (
            self.zoom_widget,
            zoom_in,
            zoom_out,
            zoom_org,
            fit_window,
            fit_width,
        )
        self.zoom_mode = self.FIT_WINDOW
        fit_window.setChecked(True)
        self.scalers = {
            self.FIT_WINDOW: self.scale_fit_window,
            self.FIT_WIDTH: self.scale_fit_width,
            # Set to one to scale to 100% when loading files.
            self.MANUAL_ZOOM: lambda: 1,
        }

        edit = action(
            self.tr("Edit Label"),
            self.edit_label,
            shortcuts["edit_label"],
            "edit",
            self.tr("Modify the label of the selected polygon"),
            enabled=False,
        )

        fill_drawing = action(
            self.tr("Fill Drawing Polygon"),
            self.canvas.set_fill_drawing,
            None,
            "color",
            self.tr("Fill polygon while drawing"),
            checkable=True,
            enabled=True,
        )
        fill_drawing.trigger()

        show_navigator = action(
            self.tr("Navigator"),
            self.toggle_navigator,
            shortcuts["show_navigator"],
            "navigator",
            self.tr("Show/hide the navigator window"),
            checkable=True,
            enabled=True,
        )

        toggle_inspector = action(
            self.tr("Data Inspector"),
            self.toggle_inspector_panel,
            None,
            "eye",
            self.tr("Show/hide the data inspector panel"),
            checkable=True,
            enabled=True,
        )

        toggle_global_filter_keep = action(
            self.tr("Enable Global Filter"),
            self.toggle_global_filter_keep,
            None,
            None,
            self.tr("When enabled, filter values persist across images"),
            checkable=True,
            checked=True,
            enabled=True,
        )

        toggle_filter_navigation = action(
            self.tr("Filter Result Navigation"),
            self.toggle_filter_navigation,
            None,
            "eye",
            self.tr("Enable/disable filter result navigation"),
            checkable=True,
            checked=False,
            enabled=True,
        )
        refresh_filter_navigation = action(
            self.tr("Refresh Filter Result Navigation"),
            self.refresh_filter_navigation,
            None,
            None,
            self.tr("Refresh files matched by the current filter"),
            enabled=True,
        )
        refresh_dataset_index = action(
            self.tr("Refresh Dataset Index"),
            self.refresh_dataset_index,
            None,
            None,
            self.tr("Incremental refresh of the dataset filter index"),
            enabled=True,
        )
        rebuild_dataset_index = action(
            self.tr("Rebuild Dataset Index"),
            self.rebuild_dataset_index,
            None,
            None,
            self.tr("Rebuild the dataset filter index from scratch"),
            enabled=True,
        )
        cancel_dataset_index = action(
            self.tr("Cancel Dataset Index Build"),
            self.cancel_dataset_index_build,
            None,
            None,
            self.tr("Cancel the running dataset index task"),
            enabled=False,
        )
        scan_exif_orientation = action(
            self.tr("Scan EXIF Orientation"),
            self.scan_exif_orientation,
            None,
            None,
            self.tr("Scan EXIF orientation for all images in the list"),
            enabled=True,
        )

        # AI Actions
        toggle_auto_labeling_widget = action(
            self.tr("Auto Labeling"),
            self.toggle_auto_labeling_widget,
            shortcuts["auto_label"],
            "brain",
            self.tr("Auto Labeling"),
        )

        # Label list context menu.
        label_menu = QtWidgets.QMenu()
        utils.add_actions(
            label_menu, (edit, delete, copy_coordinates, union_selection)
        )
        self.label_list.viewport().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.label_list.viewport().customContextMenuRequested.connect(
            self.pop_label_list_menu
        )

        # Store actions for further handling.
        self.actions = utils.Struct(
            save_auto=save_auto,
            save_with_image_data=save_with_image_data,
            change_output_dir=change_output_dir,
            save=save,
            save_as=save_as,
            open=open_,
            open_video=openvideo,
            open_dir=opendir,
            close=close,
            toggle_compare_view=toggle_compare_view,
            delete_file=delete_file,
            delete_image_file=delete_image_file,
            toggle_annotation_checked=toggle_annotation_checked,
            keep_prev_mode=keep_prev_mode,
            auto_use_last_label_mode=auto_use_last_label_mode,
            auto_use_last_gid_mode=auto_use_last_gid_mode,
            use_system_clipboard=use_system_clipboard,
            visibility_shapes_mode=visibility_shapes_mode,
            run_all_images=run_all_images,
            union_selection=union_selection,
            delete=delete,
            edit=edit,
            duplicate=duplicate,
            copy=copy,
            copy_coordinates=copy_coordinates,
            paste=paste,
            overview=overview,
            save_visualization_image=save_visualization_image,
            save_visualization_video=save_visualization_video,
            undo_last_point=undo_last_point,
            undo=undo,
            remove_point=remove_point,
            create_mode=create_mode,
            create_brush_polygon_mode=create_brush_polygon_mode,
            edit_mode=edit_mode,
            create_rectangle_mode=create_rectangle_mode,
            create_cuboid_mode=create_cuboid_mode,
            create_rotation_mode=create_rotation_mode,
            create_quadrilateral_mode=create_quadrilateral_mode,
            create_circle_mode=create_circle_mode,
            create_line_mode=create_line_mode,
            create_point_mode=create_point_mode,
            create_line_strip_mode=create_line_strip_mode,
            digit_shortcut_0=digit_shortcut_0,
            digit_shortcut_1=digit_shortcut_1,
            digit_shortcut_2=digit_shortcut_2,
            digit_shortcut_3=digit_shortcut_3,
            digit_shortcut_4=digit_shortcut_4,
            digit_shortcut_5=digit_shortcut_5,
            digit_shortcut_6=digit_shortcut_6,
            digit_shortcut_7=digit_shortcut_7,
            digit_shortcut_8=digit_shortcut_8,
            digit_shortcut_9=digit_shortcut_9,
            enter_keypoint_fill_mode=enter_keypoint_fill_mode,
            toggle_keypoint_tool_window=toggle_keypoint_tool_window,
            switch_to_prev_person=switch_to_prev_person,
            switch_to_next_person=switch_to_next_person,
            upload_image_flags_file=upload_image_flags_file,
            upload_label_flags_file=upload_label_flags_file,
            upload_shape_attrs_file=upload_shape_attrs_file,
            upload_label_classes_file=upload_label_classes_file,
            upload_yolo_hbb_annotation=upload_yolo_hbb_annotation,
            upload_yolo_obb_annotation=upload_yolo_obb_annotation,
            upload_yolo_seg_annotation=upload_yolo_seg_annotation,
            upload_yolo_pose_annotation=upload_yolo_pose_annotation,
            upload_voc_det_annotation=upload_voc_det_annotation,
            upload_voc_seg_annotation=upload_voc_seg_annotation,
            upload_coco_det_annotation=upload_coco_det_annotation,
            upload_coco_seg_annotation=upload_coco_seg_annotation,
            upload_coco_pose_annotation=upload_coco_pose_annotation,
            upload_dota_annotation=upload_dota_annotation,
            upload_mask_annotation=upload_mask_annotation,
            upload_mot_annotation=upload_mot_annotation,
            upload_odvg_annotation=upload_odvg_annotation,
            upload_mmgd_annotation=upload_mmgd_annotation,
            upload_ppocr_rec_annotation=upload_ppocr_rec_annotation,
            upload_ppocr_kie_annotation=upload_ppocr_kie_annotation,
            upload_vlm_r1_ovd_annotation=upload_vlm_r1_ovd_annotation,
            export_yolo_hbb_annotation=export_yolo_hbb_annotation,
            export_yolo_obb_annotation=export_yolo_obb_annotation,
            export_yolo_seg_annotation=export_yolo_seg_annotation,
            export_yolo_pose_annotation=export_yolo_pose_annotation,
            export_voc_det_annotation=export_voc_det_annotation,
            export_voc_seg_annotation=export_voc_seg_annotation,
            export_coco_det_annotation=export_coco_det_annotation,
            export_coco_seg_annotation=export_coco_seg_annotation,
            export_coco_pose_annotation=export_coco_pose_annotation,
            export_dota_annotation=export_dota_annotation,
            export_mask_annotation=export_mask_annotation,
            export_mot_annotation=export_mot_annotation,
            export_mots_annotation=export_mots_annotation,
            export_odvg_annotation=export_odvg_annotation,
            export_pporc_rec_annotation=export_pporc_rec_annotation,
            export_pporc_kie_annotation=export_pporc_kie_annotation,
            export_vlm_r1_ovd_annotation=export_vlm_r1_ovd_annotation,
            zoom=zoom,
            zoom_in=zoom_in,
            zoom_out=zoom_out,
            zoom_org=zoom_org,
            keep_prev_scale=keep_prev_scale,
            keep_prev_brightness=keep_prev_brightness,
            keep_prev_contrast=keep_prev_contrast,
            fit_window=fit_window,
            fit_width=fit_width,
            brightness_contrast=brightness_contrast,
            set_cross_line=set_cross_line,
            show_groups=show_groups,
            show_masks=show_masks,
            show_texts=show_texts,
            show_labels=show_labels,
            show_scores=show_scores,
            show_degrees=show_degrees,
            show_attributes=show_attributes,
            show_linking=show_linking,
            label_on_selection=label_on_selection,
            show_navigator=show_navigator,
            toggle_inspector=toggle_inspector,
            toggle_global_filter_keep=toggle_global_filter_keep,
            toggle_filter_navigation=toggle_filter_navigation,
            refresh_filter_navigation=refresh_filter_navigation,
            refresh_dataset_index=refresh_dataset_index,
            rebuild_dataset_index=rebuild_dataset_index,
            cancel_dataset_index=cancel_dataset_index,
            scan_exif_orientation=scan_exif_orientation,
            zoom_actions=zoom_actions,
            open_next_image=open_next_image,
            open_prev_image=open_prev_image,
            open_next_unchecked_image=open_next_unchecked_image,
            open_prev_unchecked_image=open_prev_unchecked_image,
            open_chatbot=open_chatbot,
            open_vqa=open_vqa,
            open_classifier=open_classifier,
            open_paddleocr=open_paddleocr,
            toggle_auto_labeling_widget=toggle_auto_labeling_widget,
            digit_shortcut_manager=digit_shortcut_manager,
            digit_relabel_manager=digit_relabel_manager,
            switch_digit_page=switch_digit_page,
            label_manager=label_manager,
            gid_manager=gid_manager,
            shape_manager=shape_manager,
            loop_thru_labels=loop_thru_labels,
            loop_select_labels=loop_select_labels,
            select_toggle_shapes=select_toggle_shapes,
            file_menu_actions=(
                open_,
                openvideo,
                opendir,
                save,
                save_as,
                close,
            ),
            tool=(),
            # XXX: need to add some actions here to activate the shortcut
            editMenu=(
                edit,
                duplicate,
                delete,
                copy,
                paste,
                None,
                undo,
                undo_last_point,
                None,
                copy_coordinates,
                remove_point,
                union_selection,
                None,
                keep_prev_mode,
                auto_use_last_label_mode,
                auto_use_last_gid_mode,
                use_system_clipboard,
                visibility_shapes_mode,
            ),
            # menu shown at right click
            menu=(
                create_mode,
                create_brush_polygon_mode,
                create_rectangle_mode,
                create_cuboid_mode,
                create_rotation_mode,
                create_quadrilateral_mode,
                create_circle_mode,
                create_line_mode,
                create_point_mode,
                create_line_strip_mode,
                None,
                edit_mode,
                edit,
                None,
                copy_coordinates,
                union_selection,
                duplicate,
                copy,
                paste,
                None,
                delete,
                undo,
                undo_last_point,
                remove_point,
            ),
            on_load_active=(
                close,
                create_mode,
                create_brush_polygon_mode,
                create_rectangle_mode,
                create_cuboid_mode,
                create_rotation_mode,
                create_quadrilateral_mode,
                create_circle_mode,
                create_line_mode,
                create_point_mode,
                create_line_strip_mode,
                digit_shortcut_0,
                digit_shortcut_1,
                digit_shortcut_2,
                digit_shortcut_3,
                digit_shortcut_4,
                digit_shortcut_5,
                digit_shortcut_6,
                digit_shortcut_7,
                digit_shortcut_8,
                digit_shortcut_9,
                enter_keypoint_fill_mode,
                toggle_keypoint_tool_window,
                edit_mode,
                brightness_contrast,
                toggle_annotation_checked,
                shape_manager,
                loop_thru_labels,
                loop_select_labels,
                select_toggle_shapes,
            ),
            on_shapes_present=(save_as, delete),
            hide_selected_polygons=hide_selected_polygons,
            show_hidden_polygons=show_hidden_polygons,
            group_selected_shapes=group_selected_shapes,
            ungroup_selected_shapes=ungroup_selected_shapes,
        )

        for digit_action in (
            self.actions.digit_shortcut_0,
            self.actions.digit_shortcut_1,
            self.actions.digit_shortcut_2,
            self.actions.digit_shortcut_3,
            self.actions.digit_shortcut_4,
            self.actions.digit_shortcut_5,
            self.actions.digit_shortcut_6,
            self.actions.digit_shortcut_7,
            self.actions.digit_shortcut_8,
            self.actions.digit_shortcut_9,
        ):
            self.addAction(digit_action)
        self.addAction(self.actions.switch_digit_page)
        self.addAction(self.actions.enter_keypoint_fill_mode)
        self.addAction(self.actions.toggle_keypoint_tool_window)
        self.addAction(self.actions.switch_to_prev_person)
        self.addAction(self.actions.switch_to_next_person)
        self.addAction(self.actions.toggle_annotation_checked)

        self.canvas.vertex_selected.connect(
            self.actions.remove_point.setEnabled
        )

        self.menus = utils.Struct(
            file=self.menu(self.tr("File")),
            edit=self.menu(self.tr("Edit")),
            view=self.menu(self.tr("View")),
            theme=self.menu(self.tr("Theme")),
            language=self.menu(self.tr("Language")),
            upload=self.menu(self.tr("Upload")),
            export=self.menu(self.tr("Export")),
            tool=self.menu(self.tr("Tool")),
            train=self.menu(self.tr("Train")),
            help=self.menu(self.tr("Help")),
            recent_files=QtWidgets.QMenu(self.tr("Open Recent")),
            label_list=label_menu,
        )
        self.menus.recent_files.aboutToShow.connect(self.update_file_menu)
        (
            self.label_filter_menu,
            self.gid_filter_menu,
            self.shape_type_filter_menu,
        ) = self._append_filter_submenus(self.menus.label_list, prepend=True)
        self.canvas_label_filter_menu_0 = None
        self.canvas_gid_filter_menu_0 = None
        self.canvas_shape_type_filter_menu_0 = None
        self.canvas_label_filter_menu_1 = None
        self.canvas_gid_filter_menu_1 = None
        self.canvas_shape_type_filter_menu_1 = None

        utils.add_actions(
            self.menus.file,
            (
                open_,
                open_next_image,
                open_prev_image,
                open_next_unchecked_image,
                open_prev_unchecked_image,
                opendir,
                openvideo,
                toggle_compare_view,
                self.menus.recent_files,
                save,
                save_as,
                save_auto,
                change_output_dir,
                save_with_image_data,
                close,
                delete_file,
                delete_image_file,
                None,
            ),
        )
        utils.add_actions(self.menus.train, (ultralytics_train,))
        utils.add_actions(
            self.menus.tool,
            (
                overview,
                None,
                save_crop,
                save_visualization_image,
                save_visualization_video,
                None,
                digit_shortcut_manager,
                digit_relabel_manager,
                enter_keypoint_fill_mode,
                toggle_keypoint_tool_window,
                switch_to_prev_person,
                switch_to_next_person,
                label_manager,
                gid_manager,
                shape_manager,
                None,
                shape_converter,
            ),
        )
        utils.add_actions(
            self.menus.help,
            (
                documentation,
                None,
                about,
            ),
        )
        utils.add_actions(
            self.menus.language,
            (
                select_lang_en,
                select_lang_zh,
                select_lang_jp,
                select_lang_ko,
            ),
        )
        utils.add_actions(self.menus.theme, theme_mode_actions)
        utils.add_actions(
            self.menus.upload,
            (
                upload_image_flags_file,
                upload_label_flags_file,
                upload_shape_attrs_file,
                upload_label_classes_file,
                None,
                upload_yolo_hbb_annotation,
                upload_yolo_obb_annotation,
                upload_yolo_seg_annotation,
                upload_yolo_pose_annotation,
                None,
                upload_voc_det_annotation,
                upload_voc_seg_annotation,
                None,
                upload_coco_det_annotation,
                upload_coco_seg_annotation,
                upload_coco_pose_annotation,
                None,
                upload_dota_annotation,
                upload_mask_annotation,
                upload_mot_annotation,
                upload_odvg_annotation,
                upload_mmgd_annotation,
                None,
                upload_ppocr_rec_annotation,
                upload_ppocr_kie_annotation,
                None,
                upload_vlm_r1_ovd_annotation,
            ),
        )
        utils.add_actions(
            self.menus.export,
            (
                export_yolo_hbb_annotation,
                export_yolo_obb_annotation,
                export_yolo_seg_annotation,
                export_yolo_pose_annotation,
                None,
                export_voc_det_annotation,
                export_voc_seg_annotation,
                None,
                export_coco_det_annotation,
                export_coco_seg_annotation,
                export_coco_pose_annotation,
                None,
                export_dota_annotation,
                export_mask_annotation,
                export_odvg_annotation,
                None,
                export_mot_annotation,
                export_mots_annotation,
                None,
                export_pporc_rec_annotation,
                export_pporc_kie_annotation,
                None,
                export_vlm_r1_ovd_annotation,
            ),
        )
        reset_image_views_menu = QtWidgets.QMenu(
            self.tr("重置图像视图"), self.menus.view
        )
        utils.add_actions(
            reset_image_views_menu,
            (
                reset_current_image_view,
                reset_views_from_current_to_end,
                reset_all_image_views,
            ),
        )
        utils.add_actions(
            self.menus.view,
            (
                show_navigator,
                toggle_inspector,
                toggle_global_filter_keep,
                toggle_filter_navigation,
                refresh_filter_navigation,
                refresh_dataset_index,
                rebuild_dataset_index,
                cancel_dataset_index,
                scan_exif_orientation,
                fill_drawing,
                loop_thru_labels,
                loop_select_labels,
                None,
                zoom_in,
                zoom_out,
                zoom_org,
                None,
                keep_prev_scale,
                keep_prev_viewport,
                keep_prev_brightness,
                keep_prev_contrast,
                None,
                fit_window,
                fit_width,
                None,
                brightness_contrast,
                set_cross_line,
                None,
                show_masks,
                show_texts,
                show_labels,
                show_scores,
                show_degrees,
                show_attributes,
                show_linking,
                label_on_selection,
                pose_view,
                show_groups,
                hide_selected_polygons,
                show_hidden_polygons,
                group_selected_shapes,
                ungroup_selected_shapes,
                None,
                reset_image_views_menu,
            ),
        )

        self._view_menu_filter = utils.StayOpenMenuFilter(self.menus.view)
        self.menus.view.installEventFilter(self._view_menu_filter)

        self.menus.file.aboutToShow.connect(self.update_file_menu)

        # Custom context menu for the canvas widget:
        utils.add_actions(self.canvas.menus[0], self.actions.menu)
        utils.add_actions(
            self.canvas.menus[1],
            (
                action("&Copy here", self.copy_shape),
                action("&Move here", self.move_shape),
            ),
        )
        self.canvas.menus[0].addSeparator()
        utils.add_actions(
            self.canvas.menus[0],
            (
                reset_current_image_view,
                reset_views_from_current_to_end,
                reset_all_image_views,
            ),
        )
        self.canvas.menus[1].addSeparator()
        utils.add_actions(
            self.canvas.menus[1],
            (
                reset_current_image_view,
                reset_views_from_current_to_end,
                reset_all_image_views,
            ),
        )
        (
            self.canvas_label_filter_menu_0,
            self.canvas_gid_filter_menu_0,
            self.canvas_shape_type_filter_menu_0,
        ) = self._append_filter_submenus(
            self.canvas.menus[0],
            prepend=True,
            after_filter_actions=(self.actions.toggle_annotation_checked,),
        )
        self.canvas.menus[0].aboutToShow.connect(self.refresh_filter_menus)

        self.tools = self.toolbar("Tools")
        # Menu buttons on Left
        self.actions.tool = (
            # open_,
            opendir,
            open_next_image,
            open_prev_image,
            save,
            delete_file,
            None,
            create_mode,
            self.actions.create_brush_polygon_mode,
            self.actions.create_rectangle_mode,
            self.actions.create_cuboid_mode,
            self.actions.create_rotation_mode,
            self.actions.create_quadrilateral_mode,
            self.actions.create_circle_mode,
            self.actions.create_line_mode,
            self.actions.create_point_mode,
            self.actions.create_line_strip_mode,
            None,
            edit_mode,
            delete,
            undo,
            loop_thru_labels,
            loop_select_labels,
            toggle_filter_navigation,
            refresh_dataset_index,
            rebuild_dataset_index,
            cancel_dataset_index,
            scan_exif_orientation,
            select_toggle_shapes,
            run_all_images,
            toggle_auto_labeling_widget,
            None,
            open_chatbot,
            open_vqa,
            open_classifier,
            open_paddleocr,
            None,
            fit_width,
            zoom,
        )

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(self.tools)
        central_layout = QVBoxLayout()
        central_layout.setContentsMargins(0, 0, 0, 0)
        self.label_instruction = QLabel(self.get_labeling_instruction())
        self.label_instruction.setContentsMargins(0, 0, 0, 0)
        self.auto_labeling_widget = AutoLabelingWidget(self)
        self.auto_labeling_widget.auto_segmentation_requested.connect(
            self.on_auto_segmentation_requested
        )
        self.auto_labeling_widget.auto_segmentation_disabled.connect(
            self.on_auto_segmentation_disabled
        )
        self.canvas.auto_labeling_marks_updated.connect(
            self.auto_labeling_widget.on_new_marks
        )
        self.auto_labeling_widget.auto_labeling_mode_changed.connect(
            self.canvas.set_auto_labeling_mode
        )
        self.auto_labeling_widget.auto_decode_mode_changed.connect(
            self.canvas.set_auto_decode_mode
        )
        self.auto_labeling_widget.cropping_mode_changed.connect(
            self.auto_labeling_widget.model_manager.set_cropping_mode
        )
        self.auto_labeling_widget.clear_auto_decode_requested.connect(
            self.canvas.reset_auto_decode_state
        )
        self.canvas.auto_decode_requested.connect(
            self.on_auto_decode_requested
        )
        self.canvas.auto_decode_finish_requested.connect(
            self.auto_labeling_widget.on_finish_clicked
        )
        self.canvas.shape_hover_changed.connect(
            lambda: (
                self.update_navigator_shapes()
                if (
                    hasattr(self, "navigator_dialog")
                    and self.navigator_dialog.isVisible()
                )
                else None
            )
        )
        self.auto_labeling_widget.clear_auto_labeling_action_requested.connect(
            self.clear_auto_labeling_marks
        )
        self.auto_labeling_widget.finish_auto_labeling_object_action_requested.connect(
            self.finish_auto_labeling_object
        )
        self.auto_labeling_widget.cache_auto_label_changed.connect(
            self.set_cache_auto_label
        )
        self.auto_labeling_widget.model_manager.prediction_started.connect(
            lambda: self.canvas.set_loading(True, self.tr("Please wait..."))
        )
        self.auto_labeling_widget.model_manager.prediction_finished.connect(
            lambda: self.canvas.set_loading(False)
        )
        self.auto_labeling_widget.model_manager.prediction_finished.connect(
            self.update_thumbnail_display
        )
        self.auto_labeling_widget.model_manager.model_loaded.connect(
            self.update_thumbnail_display
        )
        self.next_files_changed.connect(
            self.auto_labeling_widget.model_manager.on_next_files_changed
        )
        # NOTE(jack): this is not needed for now
        # self.auto_labeling_widget.model_manager.request_next_files_requested.connect(
        #     lambda: self.inform_next_files(self.filename)
        # )
        self.auto_labeling_widget.hide()  # Hide by default
        central_layout.addWidget(self.label_instruction)
        central_layout.addSpacing(5)
        central_layout.addWidget(self.auto_labeling_widget)
        central_layout.addWidget(scroll_area)
        central_layout.addWidget(self.compare_view_slider)
        layout.addLayout(central_layout)

        # Save central area for resize
        self._central_widget = scroll_area

        # Stretch central area (image view)
        layout.setStretch(1, 1)

        right_sidebar_layout = QVBoxLayout()
        right_sidebar_layout.setContentsMargins(0, 0, 0, 0)
        right_sidebar_layout.setSpacing(4)

        # Thumbnail image display
        self.thumbnail_pixmap = None
        self.thumbnail_container = QWidget()
        thumbnail_image_layout = QVBoxLayout()
        thumbnail_image_layout.setContentsMargins(2, 2, 2, 2)
        self.thumbnail_image_label = QLabel()
        self.thumbnail_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_image_label.mousePressEvent = utils.on_thumbnail_click(
            self
        )
        thumbnail_image_layout.addWidget(self.thumbnail_image_label)
        self.thumbnail_container.setLayout(thumbnail_image_layout)
        self.thumbnail_container.hide()
        right_sidebar_layout.addWidget(self.thumbnail_container)

        # Label display mode buttons
        display_mode_panel = QFrame()
        display_mode_panel.setObjectName("sidebarPanel")
        display_mode_panel.setStyleSheet(get_panel_style())
        display_mode_layout = QVBoxLayout(display_mode_panel)
        display_mode_layout.setContentsMargins(4, 4, 4, 4)
        display_mode_layout.setSpacing(4)

        display_mode_header = QLabel(self.tr("标签显示"))
        display_mode_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        display_mode_header.setStyleSheet(
            "font-weight: bold; font-size: 11px;"
        )
        display_mode_layout.addWidget(display_mode_header)

        display_mode_btn_row = QHBoxLayout()
        display_mode_btn_row.setSpacing(3)

        self._display_mode_buttons = {}
        current_mode = self._config.get("label_display_mode", "label")
        for mode_key, mode_label in [
            ("label", self.tr("标签")),
            ("id", self.tr("编号")),
            ("both", self.tr("名称+编号")),
            ("none", self.tr("隐藏")),
        ]:
            btn = QtWidgets.QPushButton(mode_label)
            btn.setCheckable(True)
            btn.setFixedHeight(24)
            btn.setStyleSheet(
                "QPushButton { border: 1px solid #555; border-radius: 3px;"
                " font-size: 11px; padding: 2px 4px; }"
                "QPushButton:checked { background: #e94560;"
                " color: white; border-color: #e94560; }"
            )
            btn.clicked.connect(
                lambda checked, m=mode_key: self._set_label_display_mode(m)
            )
            if mode_key == current_mode:
                btn.setChecked(True)
            display_mode_btn_row.addWidget(btn)
            self._display_mode_buttons[mode_key] = btn

        display_mode_layout.addLayout(display_mode_btn_row)

        self._display_score_cb = QtWidgets.QCheckBox(self.tr("显示置信度"))
        self._display_score_cb.setChecked(
            self._config.get("show_scores", True)
        )
        self._display_score_cb.setStyleSheet("font-size: 11px;")
        self._display_score_cb.toggled.connect(self._toggle_display_score)
        display_mode_layout.addWidget(self._display_score_cb)

        right_sidebar_layout.addWidget(display_mode_panel)

        # Pose View panel (QDockWidget, like Inspector — hidden by default)
        pose_pv_cfg = self._config.get("pose_view", {})
        if isinstance(pose_pv_cfg, dict) and pose_pv_cfg:
            _tmp = type(self.canvas.pose_config).from_dict(pose_pv_cfg)
            self.canvas.pose_config.__dict__.update(_tmp.__dict__)
        self.pose_view_panel = PoseViewPanel(
            self.canvas.pose_config,
            on_change=self._on_pose_panel_changed,
            parent=self,
        )
        self.pose_view_panel.setVisible(self.canvas.pose_config.enabled)
        pose_panel_frame = QFrame()
        pose_panel_frame.setObjectName("sidebarPanel")
        pose_panel_frame.setStyleSheet(get_panel_style())
        pose_frame_layout = QVBoxLayout(pose_panel_frame)
        pose_frame_layout.setContentsMargins(0, 0, 0, 0)
        pose_frame_layout.setSpacing(0)
        pose_frame_layout.addWidget(self.pose_view_panel)
        right_sidebar_layout.addWidget(pose_panel_frame)

        # Shape attributes / info panel
        self.shape_attributes = QLabel(self.tr("对象属性"))
        self.grid_layout = QGridLayout()
        self.scroll_area = QScrollArea()
        self.scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll_area.setWidgetResizable(True)
        self.grid_layout_container = QWidget()
        self.grid_layout_container.setLayout(self.grid_layout)
        self.scroll_area.setWidget(self.grid_layout_container)
        self._building_attributes_panel = False
        self.scroll_area.setMaximumHeight(200)
        right_sidebar_layout.addWidget(
            self.shape_attributes, 0, Qt.AlignmentFlag.AlignCenter
        )
        right_sidebar_layout.addWidget(self.scroll_area)

        description_header_layout = QHBoxLayout()
        description_header_layout.setContentsMargins(0, 2, 0, 2)
        description_header_layout.addStretch()
        description_header_layout.addWidget(self.shape_text_label)
        description_header_layout.addStretch()
        description_header_layout.addWidget(self.description_checkbox)
        description_header_widget = QWidget()
        description_header_widget.setLayout(description_header_layout)

        description_empty_widget = QWidget()
        description_empty_widget.setFixedHeight(0)
        self.description_dock.setTitleBarWidget(description_empty_widget)

        desc_panel = QFrame()
        desc_panel.setObjectName("sidebarPanel")
        desc_panel.setStyleSheet(get_panel_style())
        desc_panel_layout = QVBoxLayout(desc_panel)
        desc_panel_layout.setContentsMargins(0, 0, 0, 0)
        desc_panel_layout.setSpacing(0)
        desc_panel_layout.addWidget(description_header_widget)
        desc_panel_layout.addWidget(self.description_dock)
        right_sidebar_layout.addWidget(desc_panel)

        right_sidebar_layout.addWidget(self.flag_dock)

        # Labels with checkbox
        self.labels_checkbox = QCheckBox()
        self.labels_checkbox.setChecked(True)
        self.labels_checkbox.setStyleSheet(get_checkbox_indicator_style())
        self.labels_checkbox.toggled.connect(self.toggle_labels_visibility)

        labels_header_layout = QHBoxLayout()
        labels_header_layout.setContentsMargins(0, 2, 0, 2)
        labels_header_layout.addStretch()
        labels_title = QLabel(self.tr("Labels"))
        labels_header_layout.addWidget(labels_title)
        labels_header_layout.addStretch()
        labels_header_layout.addWidget(self.labels_checkbox)
        labels_header_widget = QWidget()
        labels_header_widget.setLayout(labels_header_layout)

        # Hide the original dock title bar
        empty_widget = QWidget()
        empty_widget.setFixedHeight(0)
        self.label_dock.setTitleBarWidget(empty_widget)

        labels_panel = QFrame()
        labels_panel.setObjectName("sidebarPanel")
        labels_panel.setStyleSheet(get_panel_style())
        labels_panel_layout = QVBoxLayout(labels_panel)
        labels_panel_layout.setContentsMargins(0, 0, 0, 0)
        labels_panel_layout.setSpacing(0)
        labels_panel_layout.addWidget(labels_header_widget)
        labels_panel_layout.addWidget(self.label_dock)
        right_sidebar_layout.addWidget(labels_panel)

        self.shapes_checkbox = QCheckBox()
        self.shapes_checkbox.setChecked(True)
        self.shapes_checkbox.setStyleSheet(get_checkbox_indicator_style())
        self.shapes_checkbox.toggled.connect(self.toggle_shapes_visibility)

        shapes_header_layout = QHBoxLayout()
        shapes_header_layout.setContentsMargins(0, 2, 0, 2)
        shapes_header_layout.addStretch()
        shapes_title = QLabel(self.tr("Shapes"))
        shapes_header_layout.addWidget(shapes_title)
        shapes_header_layout.addStretch()
        shapes_header_layout.addWidget(self.shapes_checkbox)
        shapes_header_widget = QWidget()
        shapes_header_widget.setLayout(shapes_header_layout)

        shape_empty_widget = QWidget()
        shape_empty_widget.setFixedHeight(0)
        self.shape_dock.setTitleBarWidget(shape_empty_widget)

        objects_panel = QFrame()
        objects_panel.setObjectName("sidebarPanel")
        objects_panel.setStyleSheet(get_panel_style())
        objects_panel_layout = QVBoxLayout(objects_panel)
        objects_panel_layout.setContentsMargins(0, 0, 0, 0)
        objects_panel_layout.setSpacing(0)
        objects_panel_layout.addWidget(shapes_header_widget)
        objects_panel_layout.addWidget(self.shape_dock)
        right_sidebar_layout.addWidget(objects_panel)

        file_search_row_layout = QHBoxLayout()
        file_search_row_layout.setContentsMargins(0, 0, 0, 0)
        file_search_row_layout.setSpacing(6)
        file_search_row_layout.addWidget(self.file_search, 1)
        file_search_row_layout.addWidget(self.settings_button, 0)
        right_sidebar_layout.addLayout(file_search_row_layout)

        files_panel = QFrame()
        files_panel.setObjectName("sidebarPanel")
        files_panel.setStyleSheet(get_panel_style())
        files_panel_layout = QVBoxLayout(files_panel)
        files_panel_layout.setContentsMargins(0, 0, 0, 0)
        files_panel_layout.setSpacing(0)
        files_panel_layout.addWidget(self.file_dock)
        right_sidebar_layout.addWidget(files_panel)
        self.file_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        dock_features = (
            ~QDockWidget.DockWidgetFeature.DockWidgetMovable
            | ~QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | ~QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        rev_dock_features = ~dock_features
        self.label_dock.setFeatures(
            self.label_dock.features() & rev_dock_features
        )
        self.file_dock.setFeatures(
            self.file_dock.features() & rev_dock_features
        )
        self.flag_dock.setFeatures(
            self.flag_dock.features() & rev_dock_features
        )
        self.shape_dock.setFeatures(
            self.shape_dock.features() & rev_dock_features
        )
        self.description_dock.setFeatures(
            self.description_dock.features() & rev_dock_features
        )

        # Inspector panel (Data Inspector)
        self.inspector_panel.setVisible(False)  # Hidden by default
        insp_panel = QFrame()
        insp_panel.setObjectName("sidebarPanel")
        insp_panel.setStyleSheet(get_panel_style())
        insp_panel_layout = QVBoxLayout(insp_panel)
        insp_panel_layout.setContentsMargins(0, 0, 0, 0)
        insp_panel_layout.setSpacing(0)
        insp_panel_layout.addWidget(self.inspector_panel)
        right_sidebar_layout.addWidget(insp_panel)

        self.shape_text_edit.textChanged.connect(self.shape_text_changed)

        layout.addLayout(right_sidebar_layout)
        self.setLayout(layout)

        if output_file is not None and self._config["auto_save"]:
            logger.warning(
                "If `auto_save` argument is True, `output_file` argument "
                "is ignored and output filename is automatically "
                "set as IMAGE_BASENAME.json."
            )
        self.output_file = output_file
        self.output_dir = output_dir

        # Application state.
        self.image = QtGui.QImage()
        self.image_path = None
        self.recent_files = []
        self.max_recent = 7
        self.other_data = {}
        self.zoom_level = 100
        self.fit_window = False
        self.zoom_values = {}  # key=filename, value=(zoom_mode, zoom_value)
        self.brightness_contrast_values = {}
        self.scroll_values = {
            Qt.Orientation.Horizontal: {},
            Qt.Orientation.Vertical: {},
        }  # key=filename, value=scroll_value
        self.viewport_controller = ViewportController()

        if filename is not None and osp.isdir(filename):
            self.import_image_folder(filename, load=False)
        else:
            self.filename = filename

        if config["file_search"]:
            self.file_search.setText(config["file_search"])
            self.file_search_changed()

        # XXX: Could be completely declarative.
        # Restore application settings.
        self.settings = QtCore.QSettings("anylabeling", "anylabeling")
        self.recent_files = self.settings.value("recent_files", []) or []
        self.last_open_dir = self.settings.value("last_open_dir", None) or None

        # Restore global filter keep setting
        self._global_filter_keep_enabled = self.settings.value(
            "filter/global_keep_enabled", True, type=bool
        )

        # Populate the File menu dynamically.
        self.update_file_menu()

        # Since loading the file may take some time,
        # make sure it runs in the background.
        if self.filename is not None:
            self.queue_event(functools.partial(self.load_file, self.filename))

        # Callbacks:
        self.zoom_widget.valueChanged.connect(self.paint_canvas)

        self.populate_mode_actions()
        self.actions.toggle_global_filter_keep.setChecked(
            self._global_filter_keep_enabled
        )
        self._settings_controller = SettingsController(
            config=self._config,
            apply_callback=self._settings_runtime_applier.apply_change,
            parent=self,
            defer_runtime_apply=True,
        )
        self._settings_runtime_applier.build_shortcut_action_map()

        self.set_text_editing(False)

        QtCore.QTimer.singleShot(100, self.restore_navigator_state)

    def restore_navigator_state(self) -> None:
        try:
            navigator_visible: bool = self.settings.value(
                "navigator/visible", False, type=bool
            )

            if navigator_visible:
                self.navigator_dialog.show()

                if hasattr(self, "image") and not self.image.isNull():
                    self.navigator_dialog.set_image(
                        QtGui.QPixmap.fromImage(self.image)
                    )
                    self.update_navigator_viewport()
                else:
                    self._should_restore_navigator = True

                # Restore geometry information
                geometry = self.settings.value("navigator/geometry")
                if geometry:
                    self.navigator_dialog.restoreGeometry(geometry)
                else:
                    # Fallback: restore position and size separately
                    saved_size = self.settings.value("navigator/size")
                    saved_position = self.settings.value("navigator/position")

                    if saved_size:
                        self.navigator_dialog.resize(saved_size)
                    if saved_position:
                        self.navigator_dialog.move(saved_position)

                if hasattr(self, "actions") and hasattr(
                    self.actions, "show_navigator"
                ):
                    self.actions.show_navigator.setChecked(True)

        except Exception as e:
            print(f"Error restoring navigator state: {e}")

    def _navigator_close_event(self, event: QtGui.QCloseEvent) -> None:
        if hasattr(self, "actions") and hasattr(
            self.actions, "show_navigator"
        ):
            self.actions.show_navigator.setChecked(False)

        self.settings.setValue("navigator/visible", False)

        NavigatorDialog.closeEvent(self.navigator_dialog, event)

    def set_language(self, language):
        if self._config["language"] == language:
            return
        self._config["language"] = language

        # Show dialog to restart application
        msg_box = QMessageBox()
        msg_box.setText(
            self.tr("Please restart the application to apply changes.")
        )
        msg_box.exec()
        self.parent.parent.close()

    def _on_theme_changed(self, mode: str) -> None:
        """Handle Theme menu selection (System / Light / Dark)."""
        prev_mode = self._config.get("theme", "auto")
        if prev_mode == mode:
            return

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(self.tr("Theme"))
        dialog.setFixedWidth(360)
        dialog.setWindowFlags(
            dialog.windowFlags()
            & ~QtCore.Qt.WindowType.WindowContextHelpButtonHint
        )
        dialog.setStyleSheet(get_dialog_style())

        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        label = QLabel(
            self.tr(
                "The new theme will take effect after restarting the application. Apply this setting now?"
            )
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.setSpacing(8)
        cancel_btn = QtWidgets.QPushButton(self.tr("Cancel"))
        cancel_btn.setFixedWidth(100)
        cancel_btn.setStyleSheet(get_cancel_btn_style())
        cancel_btn.clicked.connect(dialog.reject)
        ok_btn = QtWidgets.QPushButton(self.tr("OK"))
        ok_btn.setFixedWidth(100)
        ok_btn.setStyleSheet(get_ok_btn_style())
        ok_btn.clicked.connect(dialog.accept)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self._config["theme"] = mode
            save_config(self._config)
            popup = Popup(
                text=self.tr(
                    "Please restart the application to apply changes."
                ),
                parent=self,
            )
            popup.show_popup(self, position="center")
        else:
            # Revert the checkmark to the previously active mode
            prev_act = self._theme_actions.get(prev_mode)
            if prev_act:
                prev_act.setChecked(True)

    def get_labeling_instruction(self):
        text_mode = self.tr("Mode:")
        text_shortcuts = self.tr("Shortcuts:")
        text_settings = self.tr("Settings")
        text_previous = self.tr("Previous")
        text_next = self.tr("Next")
        text_rectangle = self.tr("Rectangle")
        text_polygon = self.tr("Polygon")
        text_rotation = self.tr("Rotation")
        text_quadrilateral = self.tr("Quadrilateral")
        shortcuts = self._config.get("shortcuts", {})
        return (
            f"<b>{text_mode}</b> {self.canvas.get_mode()} | "
            f"<b>{text_shortcuts}</b>"
            f" {text_previous}({self._format_instruction_shortcut(shortcuts.get('open_prev'))}),"
            f" {text_next}({self._format_instruction_shortcut(shortcuts.get('open_next'))}),"
            f" {text_rectangle}({self._format_instruction_shortcut(shortcuts.get('create_rectangle'))}),"
            f" {text_polygon}({self._format_instruction_shortcut(shortcuts.get('create_polygon'))}),"
            f" {text_rotation}({self._format_instruction_shortcut(shortcuts.get('create_rotation'))}),"
            f" {text_quadrilateral}({self._format_instruction_shortcut(shortcuts.get('create_quadrilateral'))}),"
            f" {text_settings}({self._format_instruction_shortcut(shortcuts.get('open_settings'))})"
        )

    def _format_instruction_shortcut(self, value):
        text = self._settings_runtime_applier.shortcut_value_to_text(
            value
        ).strip()
        if not text:
            return "<b>-</b>"
        sequences = [
            chunk.strip() for chunk in text.split(",") if chunk.strip()
        ]
        if not sequences:
            return "<b>-</b>"
        formatted = []
        for sequence in sequences:
            keys = [
                part.strip() for part in sequence.split("+") if part.strip()
            ]
            if not keys:
                continue
            formatted.append(
                "+".join(f"<b>{html.escape(key)}</b>" for key in keys)
            )
        if not formatted:
            return "<b>-</b>"
        return ", ".join(formatted)

    @pyqtSlot()
    def on_auto_segmentation_requested(self):
        self.canvas.set_auto_labeling(True)
        self.label_instruction.setText(self.get_labeling_instruction())

    @pyqtSlot()
    def on_auto_segmentation_disabled(self):
        self.canvas.set_auto_labeling(False)
        self.label_instruction.setText(self.get_labeling_instruction())

    @pyqtSlot(list)
    def on_exif_detected(self, exif_files):
        if utils.ExifProcessingDialog.show_detection_dialog(
            self, len(exif_files)
        ):
            logger.info("Start processing EXIF orientation")
            utils.ExifProcessingDialog.process_exif_files_with_progress(
                self, exif_files
            )

    @pyqtSlot(list)
    def on_auto_decode_requested(self, marks):
        """Handle auto decode request"""
        self.auto_labeling_widget.model_manager.set_auto_labeling_marks(marks)
        self.auto_labeling_widget.run_prediction()

    def menu(self, title, actions=None):
        menu = self.parent.parent.menuBar().addMenu(title)
        if actions:
            utils.add_actions(menu, actions)
        return menu

    def central_widget(self):
        return self._central_widget

    def toolbar(self, title, actions=None):
        toolbar = ToolBar(title)
        toolbar.setObjectName(f"{title}ToolBar")
        toolbar.setOrientation(Qt.Orientation.Vertical)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        toolbar.setIconSize(QtCore.QSize(24, 24))
        toolbar.setMaximumWidth(40)
        if actions:
            utils.add_actions(toolbar, actions)
        return toolbar

    def statusBar(self):
        return self.parent.parent.statusBar()

    def no_shape(self):
        return len(self.label_list) == 0

    def populate_mode_actions(self):
        tool = self.actions.tool
        menu = self.actions.menu
        self.tools.clear()
        utils.add_actions(self.tools, tool)

        self.canvas.menus[0].clear()
        utils.add_actions(self.canvas.menus[0], menu)
        (
            self.canvas_label_filter_menu_0,
            self.canvas_gid_filter_menu_0,
            self.canvas_shape_type_filter_menu_0,
        ) = self._append_filter_submenus(
            self.canvas.menus[0],
            prepend=True,
            after_filter_actions=(self.actions.toggle_annotation_checked,),
        )
        self.menus.edit.clear()
        actions = (
            self.actions.create_mode,
            self.actions.create_brush_polygon_mode,
            self.actions.create_rectangle_mode,
            self.actions.create_cuboid_mode,
            self.actions.create_rotation_mode,
            self.actions.create_quadrilateral_mode,
            self.actions.create_circle_mode,
            self.actions.create_line_mode,
            self.actions.create_point_mode,
            self.actions.create_line_strip_mode,
            None,
            self.actions.edit_mode,
        )
        utils.add_actions(self.menus.edit, actions + self.actions.editMenu)

    def set_dirty(self):
        # Even if we autosave the file, we keep the ability to undo
        self.actions.undo.setEnabled(self.canvas.is_shape_restorable)

        if self._config["auto_save"]:
            label_file = osp.splitext(self.image_path)[0] + ".json"
            if self.output_dir:
                label_file_without_path = osp.basename(label_file)
                label_file = self.output_dir + "/" + label_file_without_path
            self.save_labels(label_file)
            if (
                hasattr(self, "navigator_dialog")
                and self.navigator_dialog.isVisible()
            ):
                self.update_navigator_shapes()
            return
        self.dirty = True
        self.actions.save.setEnabled(True)
        if (
            hasattr(self, "navigator_dialog")
            and self.navigator_dialog.isVisible()
        ):
            self.update_navigator_shapes()
        self.update_progress_title()

    def _window_title(self):
        title = __appname__
        if self.filename is not None:
            current_index, total_count = self.get_image_progress_info()
            basename = osp.basename(str(self.filename))
            dirty_marker = "*" if self.dirty else ""
            image_size = ""
            if hasattr(self, "image") and not self.image.isNull():
                image_size = f" [{self.image.width()}x{self.image.height()}]"
            title = (
                f"{title} - {basename}{dirty_marker}{image_size} "
                f"[{current_index}/{total_count}]"
            )
        return title

    def update_progress_title(self):
        self.parent.parent.setWindowTitle(self._window_title())

    def set_clean(self):
        self.dirty = False
        self.actions.save.setEnabled(False)
        self.actions.union_selection.setEnabled(False)
        self.actions.create_mode.setEnabled(True)
        self.actions.create_brush_polygon_mode.setEnabled(True)
        self.actions.create_rectangle_mode.setEnabled(True)
        self.actions.create_cuboid_mode.setEnabled(True)
        self.actions.create_rotation_mode.setEnabled(True)
        self.actions.create_quadrilateral_mode.setEnabled(True)
        self.actions.create_circle_mode.setEnabled(True)
        self.actions.create_line_mode.setEnabled(True)
        self.actions.create_point_mode.setEnabled(True)
        self.actions.create_line_strip_mode.setEnabled(True)
        self.actions.digit_shortcut_0.setEnabled(True)
        self.actions.digit_shortcut_1.setEnabled(True)
        self.actions.digit_shortcut_2.setEnabled(True)
        self.actions.digit_shortcut_3.setEnabled(True)
        self.actions.digit_shortcut_4.setEnabled(True)
        self.actions.digit_shortcut_5.setEnabled(True)
        self.actions.digit_shortcut_6.setEnabled(True)
        self.actions.digit_shortcut_7.setEnabled(True)
        self.actions.digit_shortcut_8.setEnabled(True)
        self.actions.digit_shortcut_9.setEnabled(True)

        self.update_progress_title()

        if self.has_label_file():
            self.actions.delete_file.setEnabled(True)
        else:
            self.actions.delete_file.setEnabled(False)

    def get_image_progress_info(self):
        if self.filename and self.filename in self.fn_to_index:
            current_index = self.fn_to_index[str(self.filename)]
            total_count = self.file_list_widget.count()
            return current_index + 1, total_count
        return 1, 1

    def toggle_actions(self, value=True):
        """Enable/Disable widgets which depend on an opened image."""
        for action in self.actions.zoom_actions:
            action.setEnabled(value)
        for action in self.actions.on_load_active:
            action.setEnabled(value)

        if value and self.file_list_widget.count() > 0:
            self.actions.shape_manager.setEnabled(True)
        else:
            self.actions.shape_manager.setEnabled(False)

    def queue_event(self, function):
        QtCore.QTimer.singleShot(0, function)

    def status(self, message, delay=5000):
        self.statusBar().showMessage(message, delay)

    def reset_state(self):
        self.label_list.clear()
        self._filter_index = None  # invalidate stale item references
        self.filename = None
        self.image_path = None
        self.image_data = None
        self.label_file = None
        self.other_data = {}
        self.canvas.reset_state()
        self.compare_view_manager.reset()
        # Block signals to avoid triggering filter callbacks during reset
        lbl_blocker = QtCore.QSignalBlocker(
            self.label_filter_combobox.text_box
        )
        gid_blocker = QtCore.QSignalBlocker(self.gid_filter_combobox.gid_box)
        type_blocker = QtCore.QSignalBlocker(
            self.shape_type_filter_combobox.type_box
        )
        self.label_filter_combobox.text_box.clear()
        self.gid_filter_combobox.gid_box.clear()
        self.shape_type_filter_combobox.type_box.clear()
        self._update_select_toggle_button_tooltip()

    def toggle_select_all(self):
        if self.select_toggle_action is None:
            return
        if self._has_active_shape_filter():
            self._update_select_toggle_button_tooltip()
            return
        if not self.canvas.shapes:
            self._update_select_toggle_button_tooltip()
            return

        all_visible = self._are_all_shapes_visible()
        self._set_all_objects_visibility(not all_visible)
        self._update_select_toggle_button_tooltip()

    def _has_active_shape_filter(self):
        selected_labels = self._filter_state.labels
        current_gid = self._filter_state.gid
        current_type = self._filter_state.shape_type
        return (
            bool(selected_labels)
            or current_gid not in ["", "-1"]
            or bool(current_type)
        )

    def _update_select_toggle_button_tooltip(self):
        if self.select_toggle_action is None:
            return
        if self._has_active_shape_filter():
            tooltip = self.tr(
                "Toggle shapes visibility is unavailable while a label or group filter is active"
            )
            self.select_toggle_action.setEnabled(False)
            self.select_toggle_action.setToolTip(tooltip)
            self.select_toggle_action.setStatusTip(tooltip)
            return
        self.select_toggle_action.setEnabled(bool(self.canvas.shapes))
        if self._are_all_shapes_visible():
            tooltip = self.tr("Hide all shapes")
            icon = utils.new_icon("eye")
        else:
            tooltip = self.tr("Show all shapes")
            icon = utils.new_icon("hidden")
        self.select_toggle_action.setIcon(icon)
        self.select_toggle_action.setToolTip(tooltip)
        self.select_toggle_action.setStatusTip(tooltip)

    def _are_all_shapes_visible(self):
        if len(self.label_list) == 0:
            return True
        for item in self.label_list:
            if item.checkState() != Qt.CheckState.Checked:
                return False
            shape = item.shape()
            if shape is not None and not shape.visible:
                return False
        return True

    def _set_all_objects_visibility(self, visible):
        """Set all Objects panel checkboxes and shape visibility to visible (True/False)."""
        for item in self.label_list:
            label = item.shape().label
            if label in self.label_info:
                self.label_info[label]["visible"] = visible
        self._filter_engine.sync_label_list_visibility(lambda _item: visible)

    def reset_attribute(self, text, shape):
        # Skip validation for auto-labeling special constants
        if text in [
            AutoLabelingMode.OBJECT,
            AutoLabelingMode.ADD,
            AutoLabelingMode.REMOVE,
        ]:
            return text

        valid_labels = list(self.attributes.keys())
        if text not in valid_labels:
            most_similar_label = utils.find_most_similar_label(
                text, valid_labels
            )
            self.error_message(
                self.tr("Invalid label"),
                self.tr(
                    "Invalid label '{}' with validation type: {}!\n"
                    "Reset the label as {}."
                ).format(text, valid_labels, most_similar_label),
            )
            text = most_similar_label

        new_attributes = {
            attrs_key: attrs_val[0]
            for attrs_key, attrs_val in self.attributes[text].items()
        }
        shape.attributes = new_attributes
        return text

    def current_item(self):
        items = self.label_list.selected_items()
        if items:
            return items[0]
        return None

    def add_recent_file(self, filename):
        if filename in self.recent_files:
            self.recent_files.remove(filename)
        elif len(self.recent_files) >= self.max_recent:
            self.recent_files.pop()
        self.recent_files.insert(0, filename)

    # Callbacks
    def undo_shape_edit(self):
        self.canvas.restore_shape()
        self.label_list.clear()
        self.load_shapes(self.canvas.shapes, update_last_label=False)
        self.actions.undo.setEnabled(self.canvas.is_shape_restorable)
        self.set_dirty()
        # Refresh keypoint fill mode after undo
        if (
            hasattr(self, "keypoint_fill_mode")
            and self.keypoint_fill_mode.is_active
        ):
            self.keypoint_fill_mode.refresh()

    def get_label_file_list(self):
        label_file_list = []
        if not self.image_list and self.filename:
            dir_path, filename = osp.split(self.filename)
            label_file = osp.join(
                dir_path, osp.splitext(filename)[0] + ".json"
            )
            if osp.exists(label_file):
                label_file_list = [label_file]
        elif self.image_list and not self.output_dir and self.filename:
            file_list = os.listdir(osp.dirname(self.filename))
            for file_name in file_list:
                if not file_name.endswith(".json"):
                    continue
                label_file_list.append(
                    osp.join(osp.dirname(self.filename), file_name)
                )
        if self.output_dir:
            for file_name in os.listdir(self.output_dir):
                if not file_name.endswith(".json"):
                    continue
                label_file_list.append(osp.join(self.output_dir, file_name))
        return label_file_list

    def copy_shape_coordinates(self):
        item = self.current_item()
        if item is None:
            return
        shape = item.shape()
        if shape is None:
            return

        points = shape.points
        if shape.shape_type == "rectangle":
            if len(points) >= 2:
                x1, y1 = points[0].x(), points[0].y()
                x2, y2 = points[2].x(), points[2].y()
                coordinates = [x1, y1, x2, y2]
                coordinates = list(map(int, coordinates))
            else:
                return
        else:
            coordinates = []
            for point in points:
                coordinates.extend([point.x(), point.y()])

        coordinates_str = str(coordinates)
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(coordinates_str)

    def union_selection(self):
        rectangle_shapes, polygon_shapes = [], []
        for shape in self.canvas.selected_shapes:
            points = shape.points
            if shape.shape_type == "rectangle":
                xmin, ymin = (points[0].x(), points[0].y())
                xmax, ymax = (points[2].x(), points[2].y())
                rectangle_shapes.append([xmin, ymin, xmax, ymax])
            else:
                polygon_shapes.append([(p.x(), p.y()) for p in points])

        union_shape = shape.copy()

        if len(rectangle_shapes) > 0:
            min_x = min([bbox[0] for bbox in rectangle_shapes])
            min_y = min([bbox[1] for bbox in rectangle_shapes])
            max_x = max([bbox[2] for bbox in rectangle_shapes])
            max_y = max([bbox[3] for bbox in rectangle_shapes])

            union_shape.points[0].setX(min_x)
            union_shape.points[0].setY(min_y)
            union_shape.points[1].setX(max_x)
            union_shape.points[1].setY(min_y)
            union_shape.points[2].setX(max_x)
            union_shape.points[2].setY(max_y)
            union_shape.points[3].setX(min_x)
            union_shape.points[3].setY(max_y)
        else:
            # Create a blank mask
            min_x = min([min(p[0] for p in poly) for poly in polygon_shapes])
            min_y = min([min(p[1] for p in poly) for poly in polygon_shapes])
            max_x = max([max(p[0] for p in poly) for poly in polygon_shapes])
            max_y = max([max(p[1] for p in poly) for poly in polygon_shapes])

            width = int(max_x - min_x + 10)
            height = int(max_y - min_y + 10)
            mask = np.zeros((height, width), dtype=np.uint8)

            # Draw all polygons on the mask
            for polygon in polygon_shapes:
                contour = np.array(polygon, dtype=np.int32)
                shifted_contour = contour - np.array(
                    [min_x - 5, min_y - 5], dtype=np.int32
                )
                shifted_contour = shifted_contour.reshape((-1, 1, 2))
                cv2.fillPoly(mask, [shifted_contour], 255)

            # Find contours of the merged shape
            merged_contours, _ = cv2.findContours(
                mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            if merged_contours:
                largest_contour = max(merged_contours, key=cv2.contourArea)
                epsilon = 0.001 * cv2.arcLength(largest_contour, True)
                approx_contour = cv2.approxPolyDP(
                    largest_contour, epsilon, True
                )
                approx_contour = approx_contour.reshape(-1, 2) + np.array(
                    [min_x - 5, min_y - 5], dtype=np.int32
                )
                union_shape.points = [
                    QtCore.QPointF(float(x), float(y))
                    for x, y in approx_contour
                ]

        # Append merged shape and remove selected shapes
        self.add_label(union_shape)
        self.remove_labels(self.canvas.delete_selected())
        self.set_dirty()

        # Update UI state
        if self.no_shape():
            for action in self.actions.on_shapes_present:
                action.setEnabled(False)

    # Trainer
    def start_training(self, mode):
        if mode == "ultralytics":
            dialog = UltralyticsDialog(self)
        else:
            return

        try:
            _ = dialog.exec()
        except Exception as e:
            self.error_message(
                "Start Error", f"Failed to start training dialog: {str(e)}"
            )

    # Tools
    def overview(self):
        if self.filename:
            OverviewDialog(parent=self)

    def digit_shortcut_manager(self):
        digit_shortcut_dialog = DigitShortcutDialog(parent=self)
        result = digit_shortcut_dialog.exec()
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            self._config["digit_shortcuts"] = self.drawing_digit_shortcuts
            self.digit_page_manager.update_shortcuts(
                self.drawing_digit_shortcuts
            )
            save_config(self._config)

    def digit_rename_shortcut_manager(self):
        digit_rename_dialog = DigitRenameShortcutDialog(parent=self)
        result = digit_rename_dialog.exec()
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            save_config(self._config)

    def label_manager(self):
        if self._label_modify_dialog is not None:
            self._label_modify_dialog.raise_()
            self._label_modify_dialog.activateWindow()
            return

        modify_label_dialog = LabelModifyDialog(
            parent=self, opacity=LABEL_OPACITY
        )
        self._label_modify_dialog = modify_label_dialog
        action = getattr(getattr(self, "actions", None), "label_manager", None)
        was_enabled = action.isEnabled() if action is not None else None
        if action is not None:
            action.setEnabled(False)
        try:
            result = modify_label_dialog.exec()
        finally:
            self._label_modify_dialog = None
            if action is not None:
                action.setEnabled(was_enabled)
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            if self.filename:
                self.load_file(self.filename)

    def gid_manager(self):
        modify_gid_dialog = GroupIDModifyDialog(parent=self)
        result = modify_gid_dialog.exec()
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            self.load_file(self.filename)

    def shape_manager(self):
        modify_shape_dialog = ShapeModifyDialog(parent=self)
        result = modify_shape_dialog.exec()
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            if modify_shape_dialog.need_reload and self.filename:
                self.load_file(self.filename)

    def open_chatbot(self):
        dialog = ChatbotDialog(self)
        _ = dialog.exec()

    def open_vqa(self):
        if not self.image_list:
            self.error_message(
                self.tr("No images loaded"),
                self.tr(
                    "Please load an image folder before opening the VQA dialog."
                ),
            )
            return

        if not hasattr(self, "vqa_window") or self.vqa_window is None:
            self.vqa_window = VQADialog(self)
            self.vqa_window.setAttribute(
                Qt.WidgetAttribute.WA_DeleteOnClose, False
            )
        if self.vqa_window.isVisible():
            self.vqa_window.raise_()
            self.vqa_window.activateWindow()
        else:
            self.vqa_window.show()

    def open_paddleocr(self):
        if not hasattr(self, "ppocr_window") or self.ppocr_window is None:
            self.ppocr_window = PPOCRDialog(self)
            self.ppocr_window.setAttribute(
                Qt.WidgetAttribute.WA_DeleteOnClose, False
            )
        if self.ppocr_window.isVisible():
            self.ppocr_window.raise_()
            self.ppocr_window.activateWindow()
        else:
            self.ppocr_window.show()

    def open_classifier(self):
        if not self.image_list:
            self.error_message(
                self.tr("No images loaded"),
                self.tr(
                    "Please load an image folder before opening the Classification dialog."
                ),
            )
            return

        main_window = self
        while True:
            try:
                parent = main_window.parent()
            except TypeError:
                parent = getattr(main_window, "parent", None)
            if parent is None:
                break
            main_window = parent
        main_window.hide()

        dialog = ClassifierDialog(self)
        dialog.exec()

    # Help
    def documentation(self):
        url = (
            "https://github.com/CVHub520/X-AnyLabeling/tree/main/docs"  # NOQA
        )
        utils.general.open_url(url)

    def about(self):
        about_dialog = AboutDialog(self)
        _ = about_dialog.exec()

    def loop_thru_labels(self):
        self.label_loop_count += 1
        if len(self.label_list) == 0 or self.label_loop_count >= len(
            self.label_list
        ):
            # If we go through all the things go back to 100%
            self.label_loop_count = -1
            self.set_zoom(int(100 * self.scale_fit_window()))
            return

        width = self.central_widget().width() - 2.0
        height = self.central_widget().height() - 2.0

        im_width = self.canvas.pixmap.width()
        im_height = self.canvas.pixmap.height()

        zoom_scale = 4

        item = self.label_list[self.label_loop_count]
        xs = []
        ys = []
        # loop through all points on this label
        for point in item.shape().points:
            xs.append(point.x())
            ys.append(point.y())

        # Set minimum label width to 30px this should handle point
        # lables and very tiny labels gracefully
        label_width = max(int(max(xs) - min(xs)), 30)
        x = (max(xs) + min(xs)) / 2
        y = (max(ys) + min(ys)) / 2

        zoom = int(100 * width / (zoom_scale * label_width))
        # Don't go past the max zoom which is 1000
        zoom = min(1000, zoom)

        self.set_zoom(zoom)

        x_range = self.scroll_bars[Qt.Orientation.Horizontal].maximum()
        x_step = self.scroll_bars[Qt.Orientation.Horizontal].pageStep()

        y_range = self.scroll_bars[Qt.Orientation.Vertical].maximum()
        # QT docs says Document length = maximum() - minimum() + pageStep().
        # so there's a weird pageStep thing we gotta add
        y_step = self.scroll_bars[Qt.Orientation.Vertical].pageStep()
        screen_width = width / (zoom / 100)
        # add half a screen to this
        x_scroll = int((x - screen_width / 2) / im_width * (x_range + x_step))
        x_scroll = min(max(0, x_scroll), x_range)

        screen_height = height / (zoom / 100)

        y_scroll = int(
            (y - screen_height / 2) / (im_height) * (y_range + y_step)
        )
        y_scroll = min(max(0, y_scroll), y_range)

        self.set_scroll(Qt.Orientation.Horizontal, x_scroll)
        self.set_scroll(Qt.Orientation.Vertical, y_scroll)
        for shape in self.canvas.selected_shapes:
            shape.selected = False
        self.canvas.prev_h_shape = self.canvas.h_hape = item.shape()
        self.canvas.update()

    def loop_select_labels(self):
        self.select_loop_count += 1
        if len(self.label_list) == 0 or self.select_loop_count >= len(
            self.label_list
        ):
            self.select_loop_count = -1
            self.canvas.deselect_shape()
            return

        item = self.label_list[self.select_loop_count]
        shape = item.shape()
        self.canvas.select_shapes([shape])

    def copy_to_clipboard(self, text):
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(text)
        QMessageBox.information(
            self,
            self.tr("Copied"),
            self.tr("The information has been copied to the clipboard."),
        )

    # General
    def toggle_drawing_sensitive(self, drawing=True):
        """Toggle drawing sensitive.

        In the middle of drawing, toggling between modes should be disabled.
        """
        self.actions.edit_mode.setEnabled(not drawing)
        self.actions.undo_last_point.setEnabled(drawing)
        self.actions.undo.setEnabled(not drawing)
        self.actions.delete.setEnabled(not drawing)
        self.actions.union_selection.setEnabled(not drawing)

    def create_digit_mode(self, digit_num):
        if self.digit_rename_manager.is_rename_mode_active():
            self.digit_rename_manager.trigger_rename(digit_num)
            return

        if self.drawing_digit_shortcuts is None:
            return

        actual_index = self.digit_page_manager.get_actual_index(digit_num)
        data = self.drawing_digit_shortcuts.get(actual_index, None)
        if not data:
            return

        label = data.get("label", "object")
        create_mode = data.get("mode", None)

        if create_mode not in Shape.get_supported_shape():
            return

        self.digit_to_label = label
        self.toggle_draw_mode(edit=False, create_mode=create_mode)

    def switch_digit_shortcut_page(self):
        """Switch to the next digit shortcut page."""
        self.digit_page_manager.switch_page()
        self.digit_page_manager.show_page_switch_status(
            self._config["shortcuts"].get("switch_digit_page", "F1")
        )

    def enter_keypoint_fill_mode(self):
        """Enter keypoint fill mode.

        If a person rectangle with group_id is selected, enter single-person mode.
        Otherwise, open the tool window (batch mode).
        """
        selected = getattr(self.canvas, "selected_shapes", [])
        person_shape = None
        for shape in selected:
            if (
                getattr(shape, "label", None) == "person"
                and getattr(shape, "group_id", None) is not None
                and getattr(shape, "shape_type", None) == "rectangle"
            ):
                person_shape = shape
                break

        if person_shape:
            # Single mode: fill for selected person directly
            if self.keypoint_fill_mode.activate(person_shape.group_id):
                if (
                    hasattr(self, "gid_filter_combobox")
                    and self.gid_filter_combobox
                ):
                    combo = self.gid_filter_combobox.gid_box
                    gid_text = str(person_shape.group_id)
                    target_index = 0
                    for i in range(combo.count()):
                        if combo.itemText(i) == gid_text:
                            target_index = i
                            break
                    combo.blockSignals(True)
                    combo.setCurrentIndex(target_index)
                    combo.blockSignals(False)
                    self.gid_selection_changed(target_index)
                self.toggle_draw_mode(edit=False, create_mode="point")
        else:
            # Batch mode: open tool window
            if self.keypoint_tool_window is None:
                self.keypoint_tool_window = KeypointToolWindow(
                    fill_mode=self.keypoint_fill_mode,
                    label_widget=self,
                    parent=self,
                )
                self.canvas.new_shape.connect(
                    self.keypoint_tool_window.refresh_all
                )

            self.keypoint_tool_window.refresh_all()
            person_data = (
                self.keypoint_tool_window.content_widget._get_person_data()
            )
            if not person_data:
                self.status(
                    self.tr("No objects with group_id found in the image"),
                    2000,
                )
                return

            incomplete_gids = [
                gid
                for gid, data in person_data.items()
                if data["completed"] < data["total"]
            ]
            if incomplete_gids:
                self.keypoint_tool_window.content_widget.switch_to_person(
                    min(incomplete_gids)
                )
            else:
                first_gid = min(person_data.keys())
                self.keypoint_tool_window.content_widget.switch_to_person(
                    first_gid
                )

            self.keypoint_tool_window.show()
            self.keypoint_tool_window.raise_()

    def exit_keypoint_fill_mode(self):
        """Exit keypoint fill mode and restore full visibility."""
        if self.keypoint_fill_mode.is_active:
            self.keypoint_fill_mode.deactivate()

            if (
                hasattr(self, "gid_filter_combobox")
                and self.gid_filter_combobox
            ):
                combo = self.gid_filter_combobox.gid_box
                combo.blockSignals(True)
                combo.setCurrentIndex(0)
                combo.blockSignals(False)
                self.gid_selection_changed(0)

            self.set_edit_mode()

    def _check_auto_activate_keypoint_fill(self) -> None:
        """Check and auto-activate keypoint fill mode if enabled."""
        if not self._config.get("auto_activate_keypoint_fill", False):
            return

        # Ensure tool window exists
        if self.keypoint_tool_window is None:
            self.keypoint_tool_window = KeypointToolWindow(
                fill_mode=self.keypoint_fill_mode,
                label_widget=self,
                parent=self,
            )
            self.canvas.new_shape.connect(
                self.keypoint_tool_window.refresh_all
            )

        # Force refresh to get latest data for the new image
        self.keypoint_tool_window.refresh_all()
        person_data = (
            self.keypoint_tool_window.content_widget._get_person_data()
        )

        # If exactly one group_id is present, auto-activate
        if len(person_data) == 1:
            gid = list(person_data.keys())[0]
            logger.info(f"Auto-activating keypoint fill mode for gid: {gid}")
            self.keypoint_tool_window.content_widget.switch_to_person(gid)
            if not self.keypoint_tool_window.isVisible():
                self.keypoint_tool_window.show()
                self.keypoint_tool_window.raise_()

    def toggle_keypoint_tool_window(self):
        """Toggle the keypoint tool window visibility."""
        if self.keypoint_tool_window is None:
            self.keypoint_tool_window = KeypointToolWindow(
                fill_mode=self.keypoint_fill_mode,
                label_widget=self,
                parent=self,
            )
            self.canvas.new_shape.connect(
                self.keypoint_tool_window.refresh_all
            )

        if self.keypoint_tool_window.isVisible():
            self.keypoint_tool_window.hide()
        else:
            self.keypoint_tool_window.show()
            self.keypoint_tool_window.raise_()
            self.keypoint_tool_window.refresh_all()

    def switch_to_prev_person(self):
        """Switch to previous person in batch mode."""
        if self.keypoint_tool_window:
            self.keypoint_tool_window.content_widget.switch_to_prev_person()

    def switch_to_next_person(self):
        """Switch to next person in batch mode."""
        if self.keypoint_tool_window:
            self.keypoint_tool_window.content_widget.switch_to_next_person()

    def toggle_draw_mode(
        self, edit=True, create_mode="rectangle", disable_auto_labeling=True
    ):
        # Exit keypoint fill mode if switching away from point mode
        if (
            hasattr(self, "keypoint_fill_mode")
            and self.keypoint_fill_mode.is_active
        ):
            if edit or create_mode != "point":
                self.exit_keypoint_fill_mode()

        # Disable auto labeling if needed
        if (
            disable_auto_labeling
            and self.auto_labeling_widget.auto_labeling_mode
            != AutoLabelingMode.NONE
        ):
            self.clear_auto_labeling_marks()
            self.auto_labeling_widget.set_auto_labeling_mode(None)

        if not edit:
            self.set_text_editing(False)

        self.canvas.set_editing(edit)
        self.canvas.create_mode = create_mode
        self.canvas._brush_drawing = False
        if edit:
            self.actions.create_mode.setEnabled(True)
            self.actions.create_brush_polygon_mode.setEnabled(True)
            self.actions.create_rectangle_mode.setEnabled(True)
            self.actions.create_cuboid_mode.setEnabled(True)
            self.actions.create_rotation_mode.setEnabled(True)
            self.actions.create_quadrilateral_mode.setEnabled(True)
            self.actions.create_circle_mode.setEnabled(True)
            self.actions.create_line_mode.setEnabled(True)
            self.actions.create_point_mode.setEnabled(True)
            self.actions.create_line_strip_mode.setEnabled(True)
            self.actions.digit_shortcut_0.setEnabled(True)
            self.actions.digit_shortcut_1.setEnabled(True)
            self.actions.digit_shortcut_2.setEnabled(True)
            self.actions.digit_shortcut_3.setEnabled(True)
            self.actions.digit_shortcut_4.setEnabled(True)
            self.actions.digit_shortcut_5.setEnabled(True)
            self.actions.digit_shortcut_6.setEnabled(True)
            self.actions.digit_shortcut_7.setEnabled(True)
            self.actions.digit_shortcut_8.setEnabled(True)
            self.actions.digit_shortcut_9.setEnabled(True)
        else:
            self.hide_attributes_panel()
            self.actions.union_selection.setEnabled(False)
            create_actions = {
                "polygon": self.actions.create_mode,
                "rectangle": self.actions.create_rectangle_mode,
                "cuboid": self.actions.create_cuboid_mode,
                "line": self.actions.create_line_mode,
                "point": self.actions.create_point_mode,
                "circle": self.actions.create_circle_mode,
                "linestrip": self.actions.create_line_strip_mode,
                "rotation": self.actions.create_rotation_mode,
                "quadrilateral": self.actions.create_quadrilateral_mode,
            }
            if create_mode not in create_actions:
                raise ValueError(f"Unsupported create_mode: {create_mode}")
            self.actions.create_mode.setEnabled(True)
            self.actions.create_brush_polygon_mode.setEnabled(True)
            self.actions.create_rectangle_mode.setEnabled(True)
            self.actions.create_cuboid_mode.setEnabled(True)
            self.actions.create_rotation_mode.setEnabled(True)
            self.actions.create_quadrilateral_mode.setEnabled(True)
            self.actions.create_circle_mode.setEnabled(True)
            self.actions.create_line_mode.setEnabled(True)
            self.actions.create_point_mode.setEnabled(True)
            self.actions.create_line_strip_mode.setEnabled(True)
            create_actions[create_mode].setEnabled(False)
        self.actions.edit_mode.setEnabled(not edit)
        self.label_instruction.setText(self.get_labeling_instruction())

    def toggle_brush_polygon_mode(self):
        """Toggle brush drawing mode for polygons."""
        if (
            self.canvas.drawing()
            and self.canvas.create_mode == "polygon"
            and self.canvas._brush_drawing
        ):
            self.toggle_draw_mode(True)
            return
        self.toggle_draw_mode(False, create_mode="polygon")
        self.canvas._brush_drawing = True
        self.actions.create_mode.setEnabled(True)
        self.actions.create_brush_polygon_mode.setEnabled(False)

    def set_edit_mode(self):
        # Disable auto labeling
        self.clear_auto_labeling_marks()
        self.auto_labeling_widget.set_auto_labeling_mode(None)

        self.toggle_draw_mode(True)
        self.set_text_editing(True)
        self.label_instruction.setText(self.get_labeling_instruction())

    def update_file_menu(self):
        current = self.filename

        def exists(filename):
            return osp.exists(str(filename))

        menu = self.menus.recent_files
        menu.clear()
        files = [f for f in self.recent_files if f != current and exists(f)]
        if self.last_open_dir and osp.isdir(self.last_open_dir):
            dir_name = (
                QtCore.QFileInfo(self.last_open_dir).fileName()
                or self.last_open_dir
            )
            action = QtGui.QAction(
                utils.new_icon("folder", "svg"),
                self.tr("Open Last Dir: %s") % dir_name,
                self,
            )
            action.triggered.connect(
                functools.partial(self.load_recent_dir, self.last_open_dir)
            )
            menu.addAction(action)
            if files:
                menu.addSeparator()
        for i, f in enumerate(files):
            icon = utils.new_icon("labels")
            action = QtGui.QAction(
                icon, "&%d %s" % (i + 1, QtCore.QFileInfo(f).fileName()), self
            )
            action.triggered.connect(functools.partial(self.load_recent, f))
            menu.addAction(action)

    def pop_label_list_menu(self, point):
        self.refresh_filter_menus()
        global_pos = self.label_list.viewport().mapToGlobal(point)
        self.menus.label_list.exec(global_pos)

    def pop_file_list_menu(self, point):
        item = self.file_list_widget.itemAt(point)
        if item is None:
            return

        menu = QtWidgets.QMenu(self.file_list_widget)
        copy_name_action = menu.addAction(
            utils.new_icon("copy", "svg"), self.tr("Copy File Name")
        )
        copy_path_action = menu.addAction(
            utils.new_icon("copy", "svg"), self.tr("Copy File Path")
        )
        menu.addSeparator()
        reset_this_image_view = menu.addAction(self.tr("重置该图像视图"))
        reset_from_this_to_end = menu.addAction(
            self.tr("重置从该图像到末尾的视图")
        )
        reset_all_views = menu.addAction(self.tr("重置所有图像视图"))
        action = menu.exec(self.file_list_widget.viewport().mapToGlobal(point))
        if action == copy_name_action:
            self.copy_file_path(osp.basename(item.text()))
        elif action == copy_path_action:
            self.copy_file_path(item.text())
        elif action == reset_this_image_view:
            self._reset_image_views_for_files([item.text()], self.tr("该图像"))
        elif action == reset_from_this_to_end:
            target_file = item.text()
            filenames = self._get_files_from_target_to_end(target_file)
            self._reset_image_views_for_files(
                filenames, self.tr("该图像到末尾")
            )
        elif action == reset_all_views:
            self.reset_all_image_views()

    def copy_file_path(self, file_path):
        popup = Popup(
            self.tr("Copy Successful"),
            parent=self,
            icon=new_icon_path("copy-green", "svg"),
        )
        popup.show_popup(self, copy_msg=file_path, position="default")

    def _label_file_checked(self, label_file):
        _t0 = time.perf_counter()
        if not QtCore.QFile.exists(label_file):
            return False
        try:
            buffer = ""
            with open(label_file, "r", encoding="utf-8") as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    buffer = buffer[-32:] + chunk
                    match = CHECKED_FIELD_PATTERN.search(buffer)
                    if match:
                        _dt = time.perf_counter() - _t0
                        if _dt > 0.05:
                            _perf_log(
                                "_label_file_checked slow: %.3fs for %s",
                                _dt,
                                label_file,
                            )
                        return match.group(1) == "true"
        except Exception:
            return False
        _dt = time.perf_counter() - _t0
        if _dt > 0.05:
            _perf_log(
                "_label_file_checked slow: %.3fs for %s",
                _dt,
                label_file,
            )
        return False

    def _set_file_item_checked(self, item, checked):
        if item.data(Qt.ItemDataRole.UserRole) is checked:
            return
        item.setIcon(self.file_status_icons[checked])
        item.setData(Qt.ItemDataRole.UserRole, checked)

    def _file_item_annotation_checked(self, item):
        return item.data(Qt.ItemDataRole.UserRole) is True

    def _create_file_list_item(
        self, file, label_file, load_checked=False, check_label=True
    ):
        item = QtWidgets.QListWidgetItem(file)
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if self._config.get("file_list_checkbox_editable", False):
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        item.setFlags(flags)
        if check_label:
            if QtCore.QFile.exists(label_file) and LabelFile.is_label_file(
                label_file
            ):
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
            if load_checked:
                self._set_file_item_checked(
                    item, self._label_file_checked(label_file)
                )
            else:
                self._set_file_item_checked(item, False)
        else:
            item.setCheckState(Qt.CheckState.Unchecked)
            self._set_file_item_checked(item, False)
        return item

    def _current_file_item(self):
        if str(self.filename) not in self.fn_to_index:
            return None
        return self.file_list_widget.item(self.fn_to_index[str(self.filename)])

    def _sync_file_list_current_row(self, filename):
        """Sync file list selection without re-entering load_file."""
        filename = str(filename)
        if filename not in self.fn_to_index:
            return
        row = self.fn_to_index[filename]
        if self.file_list_widget.currentRow() == row:
            return
        blocker = QtCore.QSignalBlocker(self.file_list_widget)
        self.file_list_widget.setCurrentRow(row)
        del blocker

    def _annotation_checked(self):
        return self.other_data.get(CHECKED_FIELD, False) is True

    def _update_annotation_checked_action(self):
        if not hasattr(self, "actions"):
            return
        action = self.actions.toggle_annotation_checked
        checked = self._annotation_checked()
        if action.isChecked() != checked:
            action.setChecked(checked)
        if checked:
            action.setText(self.tr("Mark as Unchecked"))
            tip = self.tr("Mark current annotation as unchecked")
        else:
            action.setText(self.tr("Mark as Checked"))
            tip = self.tr("Mark current annotation as checked")
        action.setToolTip(tip)
        action.setStatusTip(tip)

    def _update_current_file_checked_item(self):
        item = self._current_file_item()
        if item is not None:
            self._set_file_item_checked(item, self._annotation_checked())

    def _sync_annotation_checked_state(self):
        self._update_annotation_checked_action()
        self._update_current_file_checked_item()

    def set_annotation_checked(self, checked):
        if self.filename is None or self.image.isNull():
            return
        self.other_data[CHECKED_FIELD] = bool(checked)
        self._sync_annotation_checked_state()
        label_file = self.get_label_file()
        if self.save_labels(label_file):
            self.set_clean()

    def _append_filter_submenus(
        self, parent_menu, prepend=False, after_filter_actions=None
    ):
        label_menu = QtWidgets.QMenu(self.tr("Filter by Label"), parent_menu)
        gid_menu = QtWidgets.QMenu(self.tr("Filter by Group ID"), parent_menu)
        type_menu = QtWidgets.QMenu(
            self.tr("Filter by Shape Type"), parent_menu
        )
        if prepend and parent_menu.actions():
            first_action = parent_menu.actions()[0]
            parent_menu.insertMenu(first_action, label_menu)
            parent_menu.insertMenu(first_action, gid_menu)
            parent_menu.insertMenu(first_action, type_menu)
            parent_menu.insertSeparator(first_action)
            if after_filter_actions:
                for action in after_filter_actions:
                    parent_menu.insertAction(first_action, action)
                parent_menu.insertSeparator(first_action)
        else:
            parent_menu.addSeparator()
            parent_menu.addMenu(label_menu)
            parent_menu.addMenu(gid_menu)
            parent_menu.addMenu(type_menu)
            if after_filter_actions:
                parent_menu.addSeparator()
                utils.add_actions(parent_menu, after_filter_actions)
        return label_menu, gid_menu, type_menu

    def _populate_label_filter_menu(self, menu):
        menu.clear()
        selected_labels = self._filter_state.labels

        # "All Labels" action — clears the selection
        all_action = menu.addAction(self.tr("All Labels"))
        all_action.setCheckable(True)
        all_action.setChecked(not bool(selected_labels))
        all_action.triggered.connect(
            functools.partial(self._set_selected_labels, [])
        )

        # Separator
        menu.addSeparator()

        # Current-image labels merged with already-selected labels
        current_labels = set(self.label_filter_combobox.items)
        current_labels.discard("")
        display_labels = sorted(selected_labels | current_labels)

        for label in display_labels:
            text = label if label else self.tr("All Labels")
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(label in selected_labels)
            action.triggered.connect(
                functools.partial(self._toggle_selected_label, label)
            )

    def _populate_gid_filter_menu(self, menu):
        menu.clear()
        action_group = QtGui.QActionGroup(menu)
        action_group.setExclusive(True)
        current_gid = self.gid_filter_combobox.gid_box.currentText()
        for gid in self.gid_filter_combobox.items:
            text = self.tr("All Group IDs") if gid == "-1" else gid
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(gid == current_gid)
            action.triggered.connect(
                functools.partial(self.set_gid_filter_value, gid)
            )
            action_group.addAction(action)

    def refresh_filter_menus(self):
        self.update_combo_box(block_signal=True)
        self.update_gid_box(block_signal=True)
        self.update_shape_type_box(block_signal=True)

        menus = [
            (
                self.label_filter_menu,
                self.gid_filter_menu,
                self.shape_type_filter_menu,
            ),
            (
                self.canvas_label_filter_menu_0,
                self.canvas_gid_filter_menu_0,
                self.canvas_shape_type_filter_menu_0,
            ),
            (
                self.canvas_label_filter_menu_1,
                self.canvas_gid_filter_menu_1,
                self.canvas_shape_type_filter_menu_1,
            ),
        ]
        for label_menu, gid_menu, type_menu in menus:
            if label_menu is not None:
                self._populate_label_filter_menu(label_menu)
            if gid_menu is not None:
                self._populate_gid_filter_menu(gid_menu)
            if type_menu is not None:
                self._populate_shape_type_filter_menu(type_menu)

    def _copy_filter_state(self):
        """Return a safe copy of the current FilterState."""
        return self._filter_state.copy()

    # ------------------------------------------------------------------
    # Filter result navigation
    # ------------------------------------------------------------------

    def enable_filter_navigation(self, status_prefix=None):
        if not self._filter_state.has_active_filter():
            self.status(
                self.tr("No active filter for result navigation"), 3000
            )
            self._set_filter_navigation_action_checked(False)
            return False

        state = self._copy_filter_state()
        if (
            self._dataset_filter_index is not None
            and self._dataset_filter_index.is_ready()
        ):
            # Fast path: query derived SQLite index
            all_matched = self._dataset_filter_index.query(state)
            image_set = set(self.image_list)
            matched = [p for p in all_matched if p in image_set]
        else:
            # If index is not ready, prompt user instead of full JSON scan
            self.status(
                self.tr(
                    "Dataset index not ready. Please wait or rebuild index."
                ),
                5000,
            )
            self._set_filter_navigation_action_checked(False)
            return False
        self._filter_navigation_files = matched
        self._filter_navigation_initial_count = len(matched)
        self._filter_navigation_state = state
        self._filter_navigation_active = bool(matched)

        if not matched:
            self.status(self.tr("No files match the current filter"), 3000)
            self._set_filter_navigation_action_checked(False)
            return False
        self._show_filter_navigation_status(
            status_prefix or self.tr("Filter result navigation enabled")
        )
        self._set_filter_navigation_action_checked(True)
        return True

    def clear_filter_navigation(self):
        self._filter_navigation_active = False
        self._filter_navigation_files = []
        self._filter_navigation_initial_count = 0
        self._filter_navigation_state = None
        self._set_filter_navigation_action_checked(False)
        self.status(self.tr("Filter result navigation cleared"), 2000)

    def toggle_filter_navigation(self, enabled):
        if enabled:
            if not self.enable_filter_navigation():
                self._set_filter_navigation_action_checked(False)
        else:
            self.clear_filter_navigation()

    def refresh_filter_navigation(self):
        self.enable_filter_navigation(
            status_prefix=self.tr("Filter result navigation refreshed")
        )

    def refresh_dataset_index(self):
        self._start_dataset_index_worker(
            "refresh", list(self.image_list), self.output_dir
        )

    def rebuild_dataset_index(self):
        self._start_dataset_index_worker(
            "rebuild", list(self.image_list), self.output_dir
        )

    def cancel_dataset_index_build(self):
        if self._dataset_index_worker is not None:
            self._dataset_index_worker.cancel()
            self.status(self.tr("Cancelling dataset index build..."), 3000)

    def scan_exif_orientation(self):
        """Manually trigger EXIF orientation scan for all images."""
        image_files = list(self.image_list)
        if not image_files:
            self.status(
                self.tr("No images to scan. Open a directory first."), 3000
            )
            return
        self.async_exif_scanner.start_scan(image_files)
        self.status(
            self.tr("Scanning EXIF orientation for %d images...")
            % len(image_files),
            3000,
        )

    def _start_dataset_index_worker(self, mode, image_files, output_dir=None):
        if self._dataset_index_worker is not None:
            self.status(self.tr("Dataset index task is already running"), 3000)
            return
        if not image_files:
            self.status(
                self.tr("No images to index. Open a directory first."),
                3000,
            )
            return
        if self._dataset_filter_index is not None:
            self._dataset_filter_index.close()
            self._dataset_filter_index = None
        db_path = make_db_path(self.last_open_dir or self.current_path())
        self._dataset_index_worker = DatasetIndexWorker(
            mode, db_path, image_files, output_dir, self
        )
        self._dataset_index_worker.progress_changed.connect(
            self._on_dataset_index_progress
        )
        self._dataset_index_worker.finished.connect(
            self._on_dataset_index_finished
        )
        self._dataset_index_worker.cancelled.connect(
            self._on_dataset_index_cancelled
        )
        self._dataset_index_worker.failed.connect(
            self._on_dataset_index_failed
        )
        self.actions.refresh_dataset_index.setEnabled(False)
        self.actions.rebuild_dataset_index.setEnabled(False)
        self.actions.cancel_dataset_index.setEnabled(True)
        self.status(self.tr("Building dataset index..."), 3000)
        self._dataset_index_worker.start()

    def _finish_dataset_index_worker(self):
        if self._dataset_index_worker is not None:
            self._dataset_index_worker.deleteLater()
            self._dataset_index_worker = None
        self.actions.refresh_dataset_index.setEnabled(True)
        self.actions.rebuild_dataset_index.setEnabled(True)
        self.actions.cancel_dataset_index.setEnabled(False)

    def _on_dataset_index_progress(self, current, total, filename):
        self.status(
            self.tr(
                "Building dataset index: {current}/{total} {filename}"
            ).format(current=current, total=total, filename=filename),
            1000,
        )

    def _on_dataset_index_finished(self, result):
        if self._dataset_filter_index is not None:
            self._dataset_filter_index.close()
        db_path = make_db_path(self.last_open_dir or self.current_path())
        self._dataset_filter_index = DatasetFilterIndex(db_path)
        if self._dataset_filter_index.open():
            for image_path in sorted(
                self._pending_dataset_index_refresh_files
            ):
                self._dataset_filter_index.refresh_file(
                    image_path, self.output_dir
                )
        self._pending_dataset_index_refresh_files.clear()
        self.status(
            self.tr(
                "Dataset index ready: inserted={inserted}, "
                "updated={updated}, removed={removed}, failed={failed}"
            ).format(
                inserted=result.inserted,
                updated=result.updated,
                removed=result.removed,
                failed=result.failed,
            ),
            5000,
        )
        self._finish_dataset_index_worker()

    def _on_dataset_index_cancelled(self, result):
        self.status(self.tr("Dataset index build cancelled"), 3000)
        self._finish_dataset_index_worker()

    def _on_dataset_index_failed(self, message):
        self.status(
            self.tr("Dataset index build failed: {message}").format(
                message=message
            ),
            5000,
        )
        self._finish_dataset_index_worker()

    def _set_filter_navigation_action_checked(self, checked):
        if not hasattr(self, "actions"):
            return
        action = getattr(self.actions, "toggle_filter_navigation", None)
        if action is None or action.isChecked() == checked:
            return
        blocker = QtCore.QSignalBlocker(action)
        action.setChecked(checked)
        del blocker

    def _show_filter_navigation_status(self, prefix=None):
        message = self.tr("Remaining {remaining} / initial {initial}").format(
            remaining=len(self._filter_navigation_files),
            initial=self._filter_navigation_initial_count,
        )
        if prefix:
            message = f"{prefix}: {message}"
        self.status(message, 3000)

    def _settle_current_filter_navigation_file(self):
        if not self._filter_navigation_active:
            return
        if not self.filename or self._filter_navigation_state is None:
            return

        filename = str(self.filename)
        if filename not in self._filter_navigation_files:
            return

        shapes = getattr(self.canvas, "shapes", None)
        if shapes is not None:
            still_matches = self._filter_navigation_engine.shapes_match_filter(
                shapes, self._filter_navigation_state
            )
        else:
            still_matches = self._filter_navigation_engine.file_matches_filter(
                filename,
                self._filter_navigation_state,
                self.output_dir,
            )

        if still_matches:
            return

        self._filter_navigation_files.remove(filename)
        if not self._filter_navigation_files:
            self.clear_filter_navigation()
            self.status(self.tr("Filter result navigation completed"), 3000)
            return

        self._show_filter_navigation_status(self.tr("Current file completed"))

    def _current_image_index(self):
        files = self.image_list
        if not self.filename or str(self.filename) not in files:
            return -1
        return files.index(str(self.filename))

    def _next_filter_navigation_file(self, anchor=None):
        files = self.image_list
        if anchor and anchor in files:
            current_index = files.index(anchor)
        else:
            current_index = self._current_image_index()
        start = current_index + 1 if current_index >= 0 else 0
        remaining = set(self._filter_navigation_files)
        for filename in files[start:]:
            if filename in remaining:
                return filename
        return None

    def _prev_filter_navigation_file(self, anchor=None):
        files = self.image_list
        if anchor and anchor in files:
            current_index = files.index(anchor)
        else:
            current_index = self._current_image_index()
        if current_index < 0:
            return None
        remaining = set(self._filter_navigation_files)
        for filename in reversed(files[:current_index]):
            if filename in remaining:
                return filename
        return None

    def _open_next_filter_navigation_image(self, load=True):
        anchor = str(self.filename) if self.filename else None
        self._settle_current_filter_navigation_file()
        if not self._filter_navigation_active:
            return True

        filename = self._next_filter_navigation_file(anchor)
        if filename is None:
            self.status(self.tr("Already at the last filter result"), 2000)
            return True

        if load:
            self.load_file(filename)
        return True

    def _open_prev_filter_navigation_image(self):
        anchor = str(self.filename) if self.filename else None
        self._settle_current_filter_navigation_file()
        if not self._filter_navigation_active:
            return True

        filename = self._prev_filter_navigation_file(anchor)
        if filename is None:
            self.status(self.tr("Already at the first filter result"), 2000)
            return True

        self.load_file(filename)
        return True

    def _set_selected_labels(self, labels, apply_filter=True):
        """Replace the selected labels set and optionally apply filter."""
        self._filter_state.set_labels(labels)
        # Update combobox text as a visual summary indicator
        if labels:
            summary = ", ".join(sorted(labels))
        else:
            summary = ""
        idx = self.label_filter_combobox.text_box.findText(summary)
        if idx < 0:
            idx = self.label_filter_combobox.text_box.findText("")
        if idx >= 0:
            blocker = QtCore.QSignalBlocker(
                self.label_filter_combobox.text_box
            )
            self.label_filter_combobox.text_box.setCurrentIndex(idx)
            del blocker
        if apply_filter:
            self._apply_combined_shape_filters()

    def _toggle_selected_label(self, label, checked):
        """Add or remove a single label from the selected set."""
        if checked:
            self._filter_state.labels.add(str(label))
        else:
            self._filter_state.labels.discard(str(label))
        self._update_combo_box_label_summary()
        self._apply_combined_shape_filters()

    def _update_combo_box_label_summary(self):
        """Update label filter combobox text to reflect multi-label state."""
        labels = self._filter_state.labels
        if labels:
            summary = ", ".join(sorted(labels))
        else:
            summary = ""
        idx = self.label_filter_combobox.text_box.findText(summary)
        if idx < 0:
            idx = self.label_filter_combobox.text_box.findText("")
        if idx >= 0:
            blocker = QtCore.QSignalBlocker(
                self.label_filter_combobox.text_box
            )
            self.label_filter_combobox.text_box.setCurrentIndex(idx)
            del blocker

    def set_label_filter_value(
        self, label, _checked=False, block_signal=False
    ):
        """Compatibility wrapper: single label → set-based multi-label."""
        if label in ("", None):
            self._filter_state.set_labels(set())
        else:
            self._filter_state.set_labels({str(label)})
        if not block_signal:
            self._update_combo_box_label_summary()
            self._apply_combined_shape_filters()

    def set_gid_filter_value(self, gid, _checked=False, block_signal=False):
        self._filter_state.set_gid(gid)
        index = self.gid_filter_combobox.gid_box.findText(str(gid))
        if index < 0:
            index = self.gid_filter_combobox.gid_box.findText("-1")
        if index >= 0:
            blocker = None
            if block_signal:
                blocker = QtCore.QSignalBlocker(
                    self.gid_filter_combobox.gid_box
                )
            self.gid_filter_combobox.gid_box.setCurrentIndex(index)
            del blocker

    def set_shape_type_filter_value(
        self, shape_type, _checked=False, block_signal=False
    ):
        self._filter_state.set_shape_type(shape_type)
        index = self.shape_type_filter_combobox.type_box.findText(
            str(shape_type)
        )
        if index < 0:
            index = self.shape_type_filter_combobox.type_box.findText("")
        if index >= 0:
            blocker = None
            if block_signal:
                blocker = QtCore.QSignalBlocker(
                    self.shape_type_filter_combobox.type_box
                )
            self.shape_type_filter_combobox.type_box.setCurrentIndex(index)
            del blocker

    def _populate_shape_type_filter_menu(self, menu):
        menu.clear()
        action_group = QtGui.QActionGroup(menu)
        action_group.setExclusive(True)
        current_type = self.shape_type_filter_combobox.type_box.currentText()
        for stype in self.shape_type_filter_combobox.items:
            text = self.tr("All Types") if stype == "" else stype
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(stype == current_type)
            action.triggered.connect(
                functools.partial(self.set_shape_type_filter_value, stype)
            )
            action_group.addAction(action)

    def update_shape_type_box(self, block_signal=False, precomputed=None):
        # Use filter state as the authoritative current filter value
        filter_type = self._filter_state.shape_type
        current_type = (
            filter_type
            if filter_type != ""
            else self.shape_type_filter_combobox.type_box.currentText()
        )

        unique_type_list = list(precomputed) if precomputed is not None else []
        if precomputed is None:
            for item in self.label_list:
                stype = item.shape().shape_type
                if stype:
                    unique_type_list.append(str(stype))
            unique_type_list = list(set(unique_type_list))

        # Add a null row for showing all types
        unique_type_list.append("")
        # Ensure filter value is in the list (for cross-page persistence)
        if current_type and current_type not in unique_type_list:
            unique_type_list.append(current_type)
        unique_type_list.sort()
        blocker = None
        if block_signal:
            blocker = QtCore.QSignalBlocker(
                self.shape_type_filter_combobox.type_box
            )
        self.shape_type_filter_combobox.update_items(unique_type_list)
        self.set_shape_type_filter_value(
            current_type, block_signal=block_signal
        )
        del blocker

    def shape_type_selection_changed(self, index):
        self._filter_state.set_shape_type(
            self.shape_type_filter_combobox.type_box.currentText()
        )
        self._apply_combined_shape_filters()

    def _apply_combined_shape_filters(self):
        has_active_filter = self._filter_state.has_active_filter()

        if not has_active_filter:
            if getattr(self, "_filter_navigation_active", False):
                self.clear_filter_navigation()
            # Restore full visibility respecting per-label toggles
            changed = self._filter_engine.apply_label_visibility()
            if changed:
                self.canvas.update()
                if (
                    hasattr(self, "navigator_dialog")
                    and self.navigator_dialog.isVisible()
                ):
                    self.update_navigator_shapes()
            self.status("")
            return

        matched_items = self._filter_engine.compute_matches(
            self._filter_state, self._filter_index
        )

        def is_visible(item):
            return item in matched_items

        visible_count, changed = (
            self._filter_engine.sync_label_list_visibility(is_visible)
        )

        if changed:
            self.canvas.update()
            if (
                hasattr(self, "navigator_dialog")
                and self.navigator_dialog.isVisible()
            ):
                self.update_navigator_shapes()

        if visible_count == 0:
            self.status(self.tr("No items match the filter criteria"))
        else:
            self.status("")

    def _rebuild_filter_index(self):
        """Build current-image index: label/gid/shape_type → list of items."""
        idx = {"label": {}, "gid": {}, "shape_type": {}, "all": []}
        for item in self.label_list:
            shape = item.shape()
            idx["all"].append(item)
            lbl = str(shape.label)
            idx["label"].setdefault(lbl, []).append(item)
            if shape.group_id is not None:
                gid_str = str(shape.group_id)
                idx["gid"].setdefault(gid_str, []).append(item)
            if shape.shape_type:
                idx["shape_type"].setdefault(str(shape.shape_type), []).append(
                    item
                )
        self._filter_index = idx

    def toggle_global_filter_keep(self, enabled):
        self._global_filter_keep_enabled = enabled
        self.settings.setValue("filter/global_keep_enabled", enabled)
        if not enabled:
            # Clear filter state and reset comboboxes
            self._filter_state.reset()
            self.set_label_filter_value("", block_signal=True)
            self.set_gid_filter_value("-1", block_signal=True)
            self.set_shape_type_filter_value("", block_signal=True)
            self._apply_combined_shape_filters()

    def validate_label(self, label):
        # no validation
        if self._config["validate_label"] is None:
            return True

        for i in range(self.unique_label_list.count()):
            label_i = self.unique_label_list.item(i).data(
                Qt.ItemDataRole.UserRole
            )
            if self._config["validate_label"] in ["exact"]:
                if label_i == label:
                    return True
        return False

    def batch_edit_labels(self, shapes):
        if not self._batch_edit_warning_shown:
            reply = QtWidgets.QMessageBox.question(
                self,
                self.tr("Batch Edit"),
                self.tr(
                    "You are about to edit multiple shapes in batch mode. "
                    "This operation cannot be undone.\n\n"
                    "This warning will only be shown once. Do you want to continue?"
                ),
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )

            if reply != QtWidgets.QMessageBox.StandardButton.Yes:
                return

            self._batch_edit_warning_shown = True

        first_shape = shapes[0]
        result = self.label_dialog.pop_up(
            text=first_shape.label,
            flags=first_shape.flags,
            group_id=first_shape.group_id,
            description=first_shape.description,
            difficult=first_shape.difficult,
            kie_linking=first_shape.kie_linking,
            move_mode="center",
        )

        if result[0] is None:
            return

        text, flags, group_id, description, difficult, kie_linking = result

        if not self.validate_label(text):
            self.error_message(
                self.tr("Invalid label"),
                self.tr("Invalid label '{}' with validation type '{}'").format(
                    text, self._config["validate_label"]
                ),
            )
            return

        for shape in shapes:
            if self.attributes and text:
                text = self.reset_attribute(text, shape)

            shape.label = text
            shape.flags = flags
            shape.group_id = group_id
            shape.description = description
            shape.difficult = difficult
            shape.kie_linking = kie_linking

            self._update_shape_color(shape)

            item = self.label_list.find_item_by_shape(shape)
            if item is not None:
                if shape.group_id is None:
                    color = shape.fill_color.getRgb()[:3]
                    item.setText("{}".format(html.escape(shape.label)))
                    item.setBackground(QtGui.QColor(*color, LABEL_OPACITY))
                else:
                    item.setText(f"{shape.label} ({shape.group_id})")

        self.label_dialog.add_label_history(text)

        if not self.unique_label_list.find_items_by_label(text):
            unique_label_item = self.unique_label_list.create_item_from_label(
                text
            )
            self.unique_label_list.addItem(unique_label_item)
            rgb = self._get_rgb_by_label(text)
            self.unique_label_list.set_item_label(
                unique_label_item, text, rgb, LABEL_OPACITY
            )

        self.set_dirty()
        self._refresh_shape_filters()

    def edit_label(self, item=None):
        if item and not isinstance(item, LabelListWidgetItem):
            raise TypeError("item must be LabelListWidgetItem type")

        if not self.canvas.editing():
            return

        selected_shapes = self.canvas.selected_shapes
        if not selected_shapes:
            return

        if len(selected_shapes) > 1:
            return self.batch_edit_labels(selected_shapes)

        if not item:
            item = self.current_item()
        if item is None:
            return
        shape = item.shape()
        if shape is None:
            return
        (
            text,
            flags,
            group_id,
            description,
            difficult,
            kie_linking,
        ) = self.label_dialog.pop_up(
            text=shape.label,
            flags=shape.flags,
            group_id=shape.group_id,
            description=shape.description,
            difficult=shape.difficult,
            kie_linking=shape.kie_linking,
            move_mode=self._config.get("move_mode", "auto"),
        )
        if text is None:
            return
        if not self.validate_label(text):
            self.error_message(
                self.tr("Invalid label"),
                self.tr("Invalid label '{}' with validation type '{}'").format(
                    text, self._config["validate_label"]
                ),
            )
            return
        if self.attributes and text:
            text = self.reset_attribute(text, shape)
        shape.label = text
        shape.flags = flags
        shape.group_id = group_id
        shape.description = description
        shape.difficult = difficult
        shape.kie_linking = kie_linking

        # Add to label history
        self.label_dialog.add_label_history(shape.label)

        # Update last group_id
        if group_id is not None:
            self.label_dialog._last_gid = group_id

        # Update unique label list
        if not self.unique_label_list.find_items_by_label(shape.label):
            unique_label_item = self.unique_label_list.create_item_from_label(
                shape.label
            )
            self.unique_label_list.addItem(unique_label_item)
            rgb = self._get_rgb_by_label(shape.label)
            self.unique_label_list.set_item_label(
                unique_label_item, shape.label, rgb, LABEL_OPACITY
            )

        self._update_shape_color(shape)
        if shape.group_id is None:
            color = shape.fill_color.getRgb()[:3]
            item.setText("{}".format(html.escape(shape.label)))
            item.setBackground(QtGui.QColor(*color, LABEL_OPACITY))
        else:
            item.setText(f"{shape.label} ({shape.group_id})")
        self.set_dirty()
        self._refresh_shape_filters()

        # update top-right attributes panel
        selected_idx = self.canvas.shapes.index(selected_shapes[0])
        self.update_attributes(selected_idx)

    def file_search_changed(self):
        search_text = self.file_search.text()
        self.import_image_folder(
            self.last_open_dir,
            pattern=search_text,
            load=False,
        )

    def file_selection_changed(self):
        items = self.file_list_widget.selectedItems()
        if not items:
            return
        item = items[0]

        if not self.may_continue():
            return

        if self._filter_navigation_active:
            self._settle_current_filter_navigation_file()

        current_index = self.fn_to_index[str(item.text())]
        if current_index < len(self.image_list):
            filename = self.image_list[current_index]
            if filename:
                self.load_file(filename)

    def _on_inspector_navigate(self, file_path: str, shape_index: int):
        """Navigate to a file and select a specific shape (inspector click)."""
        normalized = str(file_path)

        # Convert JSON path to image path if needed
        target_image = self._json_path_to_image(normalized)
        if target_image is None:
            self.status(
                self.tr("Cannot find image for: %s") % osp.basename(normalized)
            )
            return

        # If the requested file is not already open, switch to it
        current_image = str(self.filename) if self.filename else ""
        if current_image != target_image:
            if target_image in self.fn_to_index:
                idx = self.fn_to_index[target_image]
                item = self.file_list_widget.item(idx)
                if item:
                    self.file_list_widget.setCurrentItem(item)
            elif osp.isfile(target_image):
                self.load_file(target_image)
            else:
                self.status(self.tr("Image not found: %s") % target_image)
                return

        # Verify the file actually loaded before navigating to shape
        if str(self.filename) != target_image:
            return

        # Select the shape and center on it
        if 0 <= shape_index < len(self.canvas.shapes):
            shape = self.canvas.shapes[shape_index]
            self.canvas.select_shapes([shape])
            self._center_on_shape(shape)

    def _json_path_to_image(self, json_path: str):
        """Convert a JSON annotation path to its corresponding image path.

        Matches by basename in image_list (e.g. 000389.json → 000389.jpg).
        Returns the image path if found, or None.
        """
        if not json_path.endswith(".json"):
            return json_path if osp.isfile(json_path) else None

        json_basename = osp.splitext(osp.basename(json_path))[0]

        for img_path in self.image_list:
            img_str = str(img_path)
            img_basename = osp.splitext(osp.basename(img_str))[0]
            if img_basename == json_basename and osp.isfile(img_str):
                return img_str

        return None

    def _center_on_shape(self, shape):
        """Center the canvas view on the given shape's bounding box.

        Computes the center of the shape in pixmap coordinates and
        scrolls the canvas so the shape appears centered in the viewport.
        """
        pixmap = self.canvas.pixmap
        if pixmap is None or pixmap.width() <= 0 or pixmap.height() <= 0:
            return

        # Get shape center in pixmap coordinates
        if hasattr(shape, "center") and shape.center is not None:
            cx, cy = shape.center.x(), shape.center.y()
        else:
            points = shape.points
            if not points:
                return
            cx = sum(p.x() for p in points) / len(points)
            cy = sum(p.y() for p in points) / len(points)

        x_ratio = cx / pixmap.width()
        y_ratio = cy / pixmap.height()

        canvas_size = self.canvas.size()
        scroll_area = self._central_widget
        scroll_area_size = scroll_area.viewport().size()

        target_x = x_ratio * canvas_size.width() - scroll_area_size.width() / 2
        target_y = (
            y_ratio * canvas_size.height() - scroll_area_size.height() / 2
        )

        self.set_scroll(QtCore.Qt.Orientation.Horizontal, target_x)
        self.set_scroll(QtCore.Qt.Orientation.Vertical, target_y)

    def _on_inspector_shape_edit(
        self, file_path: str, shape_index: int, field: str, value
    ):
        """Handle an edit from the inspector's editable table.

        Modifies the corresponding Shape in canvas, marks the file dirty,
        and schedules a canvas redraw.
        """
        if str(self.filename) != str(file_path):
            return
        if shape_index < 0 or shape_index >= len(self.canvas.shapes):
            return

        shape = self.canvas.shapes[shape_index]

        if field == "label":
            shape.label = str(value)
        elif field == "group_id":
            try:
                shape.group_id = int(value) if str(value).strip() else None
            except ValueError:
                return
        elif field == "description":
            shape.description = str(value)
        else:
            return

        self.set_dirty()
        self.canvas.update()

    def _schedule_inspector_table_refresh(self):
        """Debounced refresh of the inspector editable table."""
        self._inspector_table_refresh_timer.start()

    def _refresh_inspector_table(self):
        """Refresh the inspector editable table from current canvas shapes."""
        if (
            not hasattr(self, "inspector_panel")
            or self.inspector_panel is None
        ):
            return
        # Don't reset the model while the user is editing a cell
        if self.inspector_panel.table_widget.is_editing:
            self._inspector_table_refresh_timer.start()  # retry later
            return
        if self.filename and self.canvas.shapes is not None:
            self.inspector_panel.set_current_file(str(self.filename))
            self.inspector_panel.refresh_table_from_shapes(
                file_path=str(self.filename),
                shapes=self.canvas.shapes,
                image_path=getattr(self, "image_path", "") or "",
            )

    def _update_inspector_file_list(self):
        """Feed current file list to the inspector panel."""
        if (
            not hasattr(self, "inspector_panel")
            or self.inspector_panel is None
        ):
            return
        # Collect JSON annotation files from the loaded image_list
        json_paths = []
        output_dir = getattr(self, "output_dir", None) or None
        for f in self.image_list:
            f_str = str(f)
            if f_str.endswith(".json"):
                json_paths.append(f_str)
                continue
            # Check same directory as image
            base, _ = osp.splitext(f_str)
            json_path = base + ".json"
            if osp.isfile(json_path):
                json_paths.append(json_path)
                continue
            # When output_dir is set, check there too
            if output_dir:
                basename = osp.basename(base) + ".json"
                json_path = osp.join(output_dir, basename)
                if osp.isfile(json_path):
                    json_paths.append(json_path)
        if json_paths:
            self.inspector_panel.set_file_list(json_paths)

    def toggle_inspector_panel(self):
        """Show/hide the inspector panel."""
        if (
            hasattr(self, "inspector_panel")
            and self.inspector_panel is not None
        ):
            visible = not self.inspector_panel.isVisible()
            self.inspector_panel.setVisible(visible)
            if hasattr(self, "actions") and hasattr(
                self.actions, "toggle_inspector"
            ):
                self.actions.toggle_inspector.setChecked(visible)

    def attribute_selection_changed(self, i, property, combo):
        if self._building_attributes_panel:
            return
        selected_option = combo.currentText()
        if i < len(self.canvas.shapes):
            if not self.canvas.shapes[i].attributes:
                self.canvas.shapes[i].attributes = {}
            if (
                self.canvas.shapes[i].attributes.get(property, "")
                == selected_option
            ):
                return
            self.canvas.shapes[i].attributes[property] = selected_option
            self.save_attributes(self.canvas.shapes)

    def attribute_radio_changed(self, i, property, option, checked):
        if self._building_attributes_panel:
            return
        if checked and i < len(self.canvas.shapes):
            if not self.canvas.shapes[i].attributes:
                self.canvas.shapes[i].attributes = {}
            if self.canvas.shapes[i].attributes.get(property) == option:
                return
            self.canvas.shapes[i].attributes[property] = option
            self.save_attributes(self.canvas.shapes)
            self.canvas.update()

    def attribute_line_changed(self, i, property, line: QLineEdit):
        if self._building_attributes_panel:
            return
        line_text = line.text()
        if i < len(self.canvas.shapes):
            if not self.canvas.shapes[i].attributes:
                self.canvas.shapes[i].attributes = {}
            if self.canvas.shapes[i].attributes.get(property, "") == line_text:
                return
            self.canvas.shapes[i].attributes[property] = line_text
            self.save_attributes(self.canvas.shapes)

    def update_selected_options(self, selected_options):
        if not isinstance(selected_options, dict):
            return

        row_count = self.grid_layout.rowCount()
        for row in range(row_count):
            category_label = None
            property_widget = None
            if self.grid_layout.itemAtPosition(row, 0):
                category_label = self.grid_layout.itemAtPosition(
                    row, 0
                ).widget()
            if self.grid_layout.itemAtPosition(row, 1):
                property_widget = self.grid_layout.itemAtPosition(
                    row, 1
                ).widget()
            if category_label and property_widget:
                category = category_label.text()
                if category in selected_options:
                    selected_option = selected_options[category]

                    if isinstance(property_widget, QComboBox):
                        index = property_widget.findText(selected_option)
                        if index >= 0:
                            property_widget.setCurrentIndex(index)
                    elif isinstance(property_widget, QWidget):
                        for child in property_widget.findChildren(
                            QRadioButton
                        ):
                            if child.text() == selected_option:
                                child.setChecked(True)
                                break
        return

    def update_attributes(self, shape_index):
        if shape_index >= len(self.canvas.shapes) or shape_index < 0:
            self._reset_attributes_panel()
            self.hide_attributes_panel()
            return

        update_shape = self.canvas.shapes[shape_index]
        update_category = update_shape.label

        self._reset_attributes_panel()
        self._building_attributes_panel = True
        try:
            row_counter = 0
            info_style = "QLabel { color: #aaa; font-size: 11px; }"
            val_style = (
                "QLabel { color: #eee; font-size: 11px;"
                " font-family: monospace; }"
            )

            def _add_info_row(label_text, value_text, value_widget=None):
                nonlocal row_counter
                lbl = QLabel(label_text)
                lbl.setStyleSheet(info_style)
                self.grid_layout.addWidget(lbl, row_counter, 0)
                if value_widget is not None:
                    self.grid_layout.addWidget(value_widget, row_counter, 1)
                else:
                    val = QLabel(str(value_text))
                    val.setStyleSheet(val_style)
                    self.grid_layout.addWidget(val, row_counter, 1)
                row_counter += 1

            idx_edit = QtWidgets.QLineEdit(str(shape_index))
            idx_edit.setReadOnly(True)
            idx_edit.setStyleSheet(
                "QLineEdit { font-size: 11px; padding: 1px 3px; }"
            )
            _add_info_row(self.tr("索引"), None, idx_edit)

            type_edit = QtWidgets.QLineEdit(update_shape.shape_type or "")
            type_edit.setReadOnly(True)
            type_edit.setStyleSheet(
                "QLineEdit { font-size: 11px; padding: 1px 3px; }"
            )
            _add_info_row(self.tr("类型"), None, type_edit)

            label_edit = QtWidgets.QLineEdit(update_shape.label)
            label_edit.setStyleSheet(
                "QLineEdit { font-size: 11px; padding: 1px 3px; }"
            )
            label_edit.textChanged.connect(
                lambda t, idx=shape_index: self._info_panel_label_changed(
                    idx, t
                )
            )
            _add_info_row(self.tr("标签"), None, label_edit)

            gid_edit = QtWidgets.QLineEdit(
                str(update_shape.group_id)
                if update_shape.group_id is not None
                else ""
            )
            gid_edit.setValidator(QIntValidator())
            gid_edit.setStyleSheet(
                "QLineEdit { font-size: 11px; padding: 1px 3px; }"
            )
            gid_edit.textChanged.connect(
                lambda t, idx=shape_index: self._info_panel_gid_changed(idx, t)
            )
            _add_info_row(self.tr("Group ID"), None, gid_edit)

            color_swatch = QLabel()
            fill_rgb = update_shape.fill_color.getRgb()[:3]
            color_swatch.setFixedSize(40, 16)
            color_swatch.setStyleSheet(
                f"background-color: rgb({fill_rgb[0]},{fill_rgb[1]},{fill_rgb[2]});"
                " border: 1px solid #666; border-radius: 2px;"
            )
            _add_info_row(self.tr("颜色"), None, color_swatch)

            diff_cb = QtWidgets.QCheckBox()
            diff_cb.setChecked(getattr(update_shape, "difficult", False))
            diff_cb.toggled.connect(
                lambda c, idx=shape_index: self._info_panel_difficult_changed(
                    idx, c
                )
            )
            _add_info_row(self.tr("Difficult"), None, diff_cb)

            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setFrameShadow(QFrame.Shadow.Sunken)
            self.grid_layout.addWidget(sep, row_counter, 0, 1, 2)
            row_counter += 1

            if update_category in self.attributes:
                current_attibute = self.attributes[update_category]
                if not update_shape.attributes:
                    update_shape.attributes = {}

                for property, options in current_attibute.items():
                    widget_type = self.attribute_widget_types.get(
                        update_category, {}
                    ).get(property, "combobox")
                    current_value = update_shape.attributes.get(property, None)
                    font_metrics = QFontMetrics(self.scroll_area.font())
                    available_width = self.scroll_area.width() - 30
                    property_display = property
                    if (
                        _measure_text_width(font_metrics, property)
                        > available_width
                    ):
                        while (
                            _measure_text_width(
                                font_metrics, property_display + "..."
                            )
                            > available_width
                            and len(property_display) > 1
                        ):
                            property_display = property_display[:-1]
                        property_display += "..."

                    property_label = QLabel(property_display)
                    if property_display != property:
                        property_label.setToolTip(property)

                    self.grid_layout.addWidget(
                        property_label, row_counter, 0, 1, 2
                    )
                    row_counter += 1

                    if widget_type == "radiobutton":
                        radio_group = QButtonGroup()
                        radio_container = QWidget()
                        main_layout = QVBoxLayout()
                        main_layout.setContentsMargins(0, 0, 0, 0)
                        main_layout.setSpacing(2)

                        def get_truncated_text(text, max_width):
                            if (
                                _measure_text_width(font_metrics, text)
                                <= max_width
                            ):
                                return text, text
                            truncated = text
                            while (
                                _measure_text_width(
                                    font_metrics, truncated + "..."
                                )
                                > max_width
                                and len(truncated) > 1
                            ):
                                truncated = truncated[:-1]
                            return truncated + "...", text

                        def get_button_width(text):
                            return _measure_text_width(font_metrics, text) + 30

                        def create_radio_button_with_handler(
                            display_text, original_text, prop, shape_idx
                        ):
                            radio_button = QRadioButton(display_text)
                            if display_text != original_text:
                                radio_button.setToolTip(original_text)
                            radio_group.addButton(radio_button)

                            def handler(checked):
                                if checked:
                                    self.attribute_radio_changed(
                                        shape_idx, prop, original_text, checked
                                    )

                            radio_button.toggled.connect(handler)
                            return radio_button

                        buttons_data = []
                        for option in options:
                            display_text, original_text = get_truncated_text(
                                option, available_width
                            )
                            button_width = get_button_width(display_text)
                            buttons_data.append(
                                (display_text, original_text, button_width)
                            )

                        current_row_buttons = []
                        current_row_width = 0

                        idx = 0
                        while idx < len(buttons_data):
                            (
                                display_text,
                                original_text,
                                button_width,
                            ) = buttons_data[idx]

                            if not current_row_buttons:
                                current_row_buttons.append(
                                    (display_text, original_text)
                                )
                                current_row_width = button_width
                                idx += 1
                                continue

                            if (
                                current_row_width + button_width
                                <= available_width
                            ):
                                current_row_buttons.append(
                                    (display_text, original_text)
                                )
                                current_row_width += button_width
                                idx += 1
                            else:
                                if len(current_row_buttons) == 1:
                                    (
                                        first_display,
                                        first_original,
                                    ) = current_row_buttons[0]
                                    first_truncated, _ = get_truncated_text(
                                        first_original,
                                        available_width - button_width,
                                    )
                                    first_truncated_width = get_button_width(
                                        first_truncated
                                    )

                                    if (
                                        first_truncated_width + button_width
                                        <= available_width
                                    ):
                                        current_row_buttons = [
                                            (first_truncated, first_original),
                                            (display_text, original_text),
                                        ]
                                        current_row_width = (
                                            first_truncated_width
                                            + button_width
                                        )
                                        idx += 1
                                    else:
                                        row_layout = QHBoxLayout()
                                        row_layout.setContentsMargins(
                                            0, 0, 0, 0
                                        )
                                        row_layout.setSpacing(4)

                                        for (
                                            btn_display,
                                            btn_original,
                                        ) in current_row_buttons:
                                            radio_button = create_radio_button_with_handler(
                                                btn_display,
                                                btn_original,
                                                property,
                                                shape_index,
                                            )
                                            row_layout.addWidget(radio_button)
                                            if (
                                                current_value == btn_original
                                                or (
                                                    current_value is None
                                                    and btn_original
                                                    == options[0]
                                                )
                                            ):
                                                radio_button.setChecked(True)

                                        row_layout.addStretch()
                                        row_widget = QWidget()
                                        row_widget.setLayout(row_layout)
                                        main_layout.addWidget(row_widget)

                                        current_row_buttons = []
                                        current_row_width = 0
                                        continue
                                else:
                                    row_layout = QHBoxLayout()
                                    row_layout.setContentsMargins(0, 0, 0, 0)
                                    row_layout.setSpacing(4)
                                    for (
                                        btn_display,
                                        btn_original,
                                    ) in current_row_buttons:
                                        radio_button = (
                                            create_radio_button_with_handler(
                                                btn_display,
                                                btn_original,
                                                property,
                                                shape_index,
                                            )
                                        )
                                        row_layout.addWidget(radio_button)
                                        if current_value == btn_original or (
                                            current_value is None
                                            and btn_original == options[0]
                                        ):
                                            radio_button.setChecked(True)

                                    row_layout.addStretch()
                                    row_widget = QWidget()
                                    row_widget.setLayout(row_layout)
                                    main_layout.addWidget(row_widget)

                                    current_row_buttons = []
                                    current_row_width = 0
                                    continue

                        if current_row_buttons:
                            row_layout = QHBoxLayout()
                            row_layout.setContentsMargins(0, 0, 0, 0)
                            row_layout.setSpacing(4)
                            for (
                                btn_display,
                                btn_original,
                            ) in current_row_buttons:
                                radio_button = (
                                    create_radio_button_with_handler(
                                        btn_display,
                                        btn_original,
                                        property,
                                        shape_index,
                                    )
                                )
                                row_layout.addWidget(radio_button)
                                if current_value == btn_original or (
                                    current_value is None
                                    and btn_original == options[0]
                                ):
                                    radio_button.setChecked(True)
                            row_layout.addStretch()
                            row_widget = QWidget()
                            row_widget.setLayout(row_layout)
                            main_layout.addWidget(row_widget)

                        radio_container.setLayout(main_layout)
                        self.grid_layout.addWidget(
                            radio_container, row_counter, 0, 1, 2
                        )
                        row_counter += 1
                    elif widget_type == "group_id":
                        property_combo = QComboBox()
                        options = [""] + sorted(
                            {
                                str(obj.group_id)
                                for obj in self.canvas.shapes
                                if obj.group_id is not None
                            }
                        )
                        property_combo.addItems(options)
                        if current_value:
                            index = property_combo.findText(current_value)
                            if index >= 0:
                                property_combo.setCurrentIndex(index)
                        property_combo.currentIndexChanged.connect(
                            lambda _, prop=property, combo=property_combo, shape_idx=shape_index: self.attribute_selection_changed(
                                shape_idx, prop, combo
                            )
                        )
                        self.grid_layout.addWidget(
                            property_combo, row_counter, 0, 1, 2
                        )
                        row_counter += 1
                    elif widget_type == "lineedit":
                        property_line = QLineEdit()
                        if current_value:
                            property_line.setText(current_value)
                        property_line.textChanged.connect(
                            lambda _, prop=property, line=property_line, shape_idx=shape_index: self.attribute_line_changed(
                                shape_idx, prop, line
                            )
                        )
                        self.grid_layout.addWidget(
                            property_line, row_counter, 0, 1, 2
                        )
                        row_counter += 1
                    else:
                        property_combo = QComboBox()
                        property_combo.addItems(options)
                        if current_value:
                            index = property_combo.findText(current_value)
                            if index >= 0:
                                property_combo.setCurrentIndex(index)
                        property_combo.currentIndexChanged.connect(
                            lambda _, prop=property, combo=property_combo, shape_idx=shape_index: self.attribute_selection_changed(
                                shape_idx, prop, combo
                            )
                        )
                        self.grid_layout.addWidget(
                            property_combo, row_counter, 0, 1, 2
                        )
                        row_counter += 1

        finally:
            self._building_attributes_panel = False
        self.scroll_area.setWidgetResizable(True)
        self.show_attributes_panel()

    def show_attributes_panel(self):
        if hasattr(self, "scroll_area"):
            self.scroll_area.setVisible(True)
        if hasattr(self, "shape_attributes"):
            self.shape_attributes.setVisible(True)

    def hide_attributes_panel(self):
        if hasattr(self, "scroll_area"):
            self.scroll_area.setVisible(False)
        if hasattr(self, "shape_attributes"):
            self.shape_attributes.setVisible(False)

    def _info_panel_label_changed(self, shape_index, text):
        if self._building_attributes_panel:
            return
        if shape_index >= len(self.canvas.shapes):
            return
        shape = self.canvas.shapes[shape_index]
        new_label = text.strip()
        if not new_label or new_label == shape.label:
            return
        shape.label = new_label
        self._update_shape_color(shape)
        item = self.label_list.find_item_by_shape(shape)
        if item is not None:
            if shape.group_id is None:
                item.setText(new_label)
            else:
                item.setText(f"{new_label} ({shape.group_id})")
        self.set_dirty()
        self.canvas.update()

    def _info_panel_gid_changed(self, shape_index, text):
        if self._building_attributes_panel:
            return
        if shape_index >= len(self.canvas.shapes):
            return
        shape = self.canvas.shapes[shape_index]
        text = text.strip()
        new_gid = int(text) if text else None
        if new_gid == shape.group_id:
            return
        shape.group_id = new_gid
        item = self.label_list.find_item_by_shape(shape)
        if item is not None:
            if new_gid is None:
                item.setText(shape.label)
            else:
                item.setText(f"{shape.label} ({new_gid})")
        self.set_dirty()
        self._refresh_shape_filters()
        self.canvas.update()

    def _info_panel_difficult_changed(self, shape_index, checked):
        if self._building_attributes_panel:
            return
        if shape_index >= len(self.canvas.shapes):
            return
        self.canvas.shapes[shape_index].difficult = checked
        self.set_dirty()

    def _reset_attributes_panel(self):
        """Clear attribute widgets without recreating the scroll area."""
        if hasattr(self, "grid_layout_container"):
            old_container = self.scroll_area.takeWidget()
            if old_container is not None:
                old_container.deleteLater()
        self.grid_layout = QGridLayout()
        self.grid_layout_container = QWidget()
        self.grid_layout_container.setLayout(self.grid_layout)
        self.scroll_area.setWidget(self.grid_layout_container)

    def save_attributes(self, _shapes):
        filename = osp.splitext(self.image_path)[0] + ".json"
        if self.output_dir:
            label_file_without_path = osp.basename(filename)
            filename = osp.join(self.output_dir, label_file_without_path)
        label_file = LabelFile()

        def format_shape(s):
            data = s.other_data.copy()
            info = {
                "label": s.label,
                "points": [(p.x(), p.y()) for p in s.points],
                "group_id": s.group_id,
                "description": s.description,
                "difficult": s.difficult,
                "shape_type": s.shape_type,
                "flags": s.flags,
                "attributes": s.attributes,
                "kie_linking": s.kie_linking,
            }
            if s.shape_type == "rotation":
                info["direction"] = s.direction
            data.update(info)

            return data

        # Get current shapes
        # Excluding auto labeling special shapes
        shapes = [
            format_shape(shape)
            for shape in _shapes
            if shape.label
            not in [
                AutoLabelingMode.OBJECT,
                AutoLabelingMode.ADD,
                AutoLabelingMode.REMOVE,
            ]
        ]
        flags = {}
        for i in range(self.flag_widget.count()):
            item = self.flag_widget.item(i)
            key = item.text()
            flag = item.checkState() == Qt.CheckState.Checked
            flags[key] = flag
        self.other_data[CHECKED_FIELD] = self._annotation_checked()
        try:
            image_path = osp.relpath(self.image_path, osp.dirname(filename))
            image_data = (
                self.image_data if self._config["store_data"] else None
            )
            if osp.dirname(filename) and not osp.exists(osp.dirname(filename)):
                os.makedirs(osp.dirname(filename))
            label_file.save(
                filename=filename,
                shapes=shapes,
                image_path=image_path,
                image_data=image_data,
                image_height=self.image.height(),
                image_width=self.image.width(),
                other_data=self.other_data,
                flags=flags,
            )
            self.label_file = label_file
            items = self.file_list_widget.findItems(
                self.image_path, Qt.MatchFlag.MatchExactly
            )
            if len(items) > 0:
                if len(items) != 1:
                    raise RuntimeError("There are duplicate files.")
                items[0].setCheckState(Qt.CheckState.Checked)
                self._set_file_item_checked(
                    items[0], self._annotation_checked()
                )
            # disable allows next and previous image to proceed
            # self.filename = filename
            return True
        except LabelFileError as e:
            self.error_message(
                self.tr("Error saving label data"), self.tr("<b>%s</b>") % e
            )
            return False

    # React to canvas signals.
    def shape_selection_changed(self, selected_shapes):
        self._no_selection_slot = True
        for shape in self.canvas.selected_shapes:
            shape.selected = False
        self.label_list.clearSelection()
        self.canvas.selected_shapes = selected_shapes
        allow_merge_shape_type = {"rectangle": 0, "polygon": 0}
        for shape in self.canvas.selected_shapes:
            shape.selected = True
            if shape.shape_type in ["rectangle", "polygon"]:
                allow_merge_shape_type[shape.shape_type] += 1
            item = self.label_list.find_item_by_shape(shape)
            # NOTE: Handle the case when the shape is not found
            if item is not None:
                self.label_list.select_item(item)
                self.label_list.scroll_to_item(item)
        self._no_selection_slot = False
        n_selected = len(selected_shapes)
        same_type = (
            len(set(shape.shape_type for shape in selected_shapes)) <= 1
        )
        self.actions.delete.setEnabled(n_selected)
        self.actions.duplicate.setEnabled(n_selected)
        self.actions.copy.setEnabled(n_selected)
        self.actions.edit.setEnabled(n_selected >= 1 and same_type)
        self.actions.copy_coordinates.setEnabled(n_selected == 1)
        self.actions.union_selection.setEnabled(
            not all(value > 0 for value in allow_merge_shape_type.values())
            and (
                allow_merge_shape_type["rectangle"] > 1
                or allow_merge_shape_type["polygon"] > 1
            )
        )
        self.set_text_editing(True)

        selected_count = len(self.canvas.selected_shapes)
        is_drawing_mode = (
            hasattr(self.canvas, "current") and self.canvas.current is not None
        )
        if selected_count == 1 and not is_drawing_mode:
            for i in range(len(self.canvas.shapes)):
                if self.canvas.shapes[i].selected:
                    self.update_attributes(i)
                    break
        else:
            self.hide_attributes_panel()

        if self.auto_focus_instance:
            self._auto_focus_on_selection(selected_shapes)

    def add_label(self, shape, update_last_label=True, refresh_filters=True):
        if shape.group_id is None:
            text = shape.label
        else:
            text = f"{shape.label} ({shape.group_id})"
        label_list_item = LabelListWidgetItem(text, shape)
        self.label_list.add_iem(label_list_item)
        if not self.unique_label_list.find_items_by_label(shape.label):
            item = self.unique_label_list.create_item_from_label(shape.label)
            self.unique_label_list.addItem(item)
            rgb = self._get_rgb_by_label(shape.label)
            self.unique_label_list.set_item_label(
                item, shape.label, rgb, LABEL_OPACITY
            )

        if shape.label not in self.label_info:
            rgb = self._get_rgb_by_label(shape.label)
            self.label_info[shape.label] = dict(
                delete=False,
                value=None,
                color=list(rgb),
                opacity=LABEL_OPACITY,
                visible=True,
            )

        # Add label to history if it is not a special label
        if shape.label not in [
            AutoLabelingMode.OBJECT,
            AutoLabelingMode.ADD,
            AutoLabelingMode.REMOVE,
        ]:
            self.label_dialog.add_label_history(
                shape.label, update_last_label=update_last_label
            )
            if update_last_label and shape.group_id is not None:
                self.label_dialog._last_gid = shape.group_id

        for action in self.actions.on_shapes_present:
            action.setEnabled(True)

        self._update_shape_color(shape)
        color = shape.fill_color.getRgb()[:3]
        label_list_item.setText("{}".format(html.escape(text)))
        label_list_item.setBackground(QtGui.QColor(*color, LABEL_OPACITY))
        if refresh_filters:
            self._refresh_shape_filters()

    def load_labels(self, labels, clear_existing=True):
        """
        Load labels to the unique label list widget.

        Args:
            labels (list): List of label names to load
            clear_existing (bool): Whether to clear existing labels before loading new ones
        """
        if not labels:
            return

        if clear_existing:
            self.unique_label_list.clear()

        for label in labels:
            # Check if label already exists to avoid duplicates
            if not self.unique_label_list.find_items_by_label(label):
                item = self.unique_label_list.create_item_from_label(label)
                self.unique_label_list.addItem(item)
                rgb = self._get_rgb_by_label(label)
                self.unique_label_list.set_item_label(
                    item, label, rgb, LABEL_OPACITY
                )

    def _update_shape_color(self, shape):
        r, g, b = self._get_rgb_by_label(shape.label, shape.group_id)
        shape.line_color = QtGui.QColor(r, g, b)
        shape.vertex_fill_color = QtGui.QColor(r, g, b)
        shape.hvertex_fill_color = QtGui.QColor(255, 255, 255)
        shape.fill_color = QtGui.QColor(r, g, b, 128)
        shape.select_line_color = QtGui.QColor(255, 255, 255)
        shape.select_fill_color = QtGui.QColor(r, g, b, 155)

    def _get_rgb_by_label(self, label, group_id=None, skip_label_info=False):
        # 如果 shape 有 group_id，按实例分配颜色
        if group_id is not None and group_id >= 0:
            instance_id = int(group_id)
            # 跳过索引0（黑色），使用1-based索引循环
            color_idx = (instance_id % (len(LABEL_COLORMAP) - 1)) + 1
            return LABEL_COLORMAP[color_idx]

        if label == "AUTOLABEL_ADD":
            return (144, 238, 144)
        if label == "AUTOLABEL_REMOVE":
            return (255, 182, 193)
        if label in self.label_info and not skip_label_info:
            return tuple(self.label_info[label]["color"])
        if self._config["shape_color"] == "auto":
            if not self.unique_label_list.find_items_by_label(label):
                item = self.unique_label_list.create_item_from_label(label)
                self.unique_label_list.addItem(item)
            item = self.unique_label_list.find_items_by_label(label)[0]
            label_id = self.unique_label_list.indexFromItem(item).row() + 1
            label_id += self._runtime_shape_color_shift
            return LABEL_COLORMAP[label_id % len(LABEL_COLORMAP)]
        if (
            self._config["shape_color"] == "manual"
            and self._config["label_colors"]
            and label in self._config["label_colors"]
        ):
            return self._config["label_colors"][label]
        if self._config["default_shape_color"]:
            return self._config["default_shape_color"]
        return (0, 255, 0)

    def remove_labels(self, shapes):
        for shape in shapes:
            item = self.label_list.find_item_by_shape(shape)
            if item is not None:
                self.label_list.remove_item(item)
        self._refresh_shape_filters()

    def load_shapes(
        self, shapes, replace=True, update_last_label=True, store_backup=True
    ):
        _t0 = time.perf_counter()
        self._no_selection_slot = True
        self.label_list.setUpdatesEnabled(False)
        try:
            for shape in shapes:
                self.add_label(
                    shape,
                    update_last_label=update_last_label,
                    refresh_filters=False,
                )
            self.label_list.clearSelection()
        finally:
            self.label_list.setUpdatesEnabled(True)
            self._no_selection_slot = False
        _t_list = time.perf_counter()
        self.canvas.load_shapes(
            shapes, replace=replace, store_backup=store_backup
        )
        _t_canvas = time.perf_counter()
        self._refresh_shape_filters()
        _t_filter = time.perf_counter()
        total_time = _t_filter - _t0
        if total_time > 0.1:
            _perf_log(
                "load_shapes slow: %d shapes, list=%.3fs, canvas=%.3fs, "
                "filter=%.3fs, total=%.3fs",
                len(shapes),
                _t_list - _t0,
                _t_canvas - _t_list,
                _t_filter - _t_canvas,
                total_time,
            )

    def load_flags(self, flags):
        self.flag_widget.clear()
        for key, flag in flags.items():
            item = QtWidgets.QListWidgetItem(key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if flag else Qt.CheckState.Unchecked
            )
            self.flag_widget.addItem(item)

    def _collect_filter_options(self):
        """Single-pass collection of unique labels, gids, and shape_types.

        Returns:
            (labels_set, gids_set, types_set): sets of strings.
        """
        labels_set = set()
        gids_set = set()
        types_set = set()
        for item in self.label_list:
            shape = item.shape()
            labels_set.add(str(shape.label))
            if shape.group_id is not None:
                gids_set.add(str(shape.group_id))
            if shape.shape_type:
                types_set.add(str(shape.shape_type))
        return labels_set, gids_set, types_set

    def _refresh_shape_filters(self):
        # Restore filter state from pending (cross-image persistence)
        if self._pending_filter_restore is not None:
            restored = self._pending_filter_restore
            self._pending_filter_restore = None
            self._filter_state.set_labels(restored.labels)
            self._filter_state.set_gid(restored.gid)
            self._filter_state.set_shape_type(restored.shape_type)
        # Rebuild index for the new image
        self._filter_index = None
        self._rebuild_filter_index()
        # Single-pass collection for all three filter boxes
        labels_set, gids_set, types_set = self._collect_filter_options()
        # Merge selected labels into the current-image label set
        selected_labels = self._filter_state.labels
        all_label_set = set(labels_set) | selected_labels
        self.update_combo_box(block_signal=True, precomputed=all_label_set)
        self.update_gid_box(block_signal=True, precomputed=gids_set)
        self.update_shape_type_box(block_signal=True, precomputed=types_set)
        self._apply_combined_shape_filters()

    def apply_label_visibility(self):
        changed = self._filter_engine.apply_label_visibility()
        if changed:
            self.canvas.update()
            if (
                hasattr(self, "navigator_dialog")
                and self.navigator_dialog.isVisible()
            ):
                self.update_navigator_shapes()

    def update_combo_box(self, block_signal=False, precomputed=None):
        # Use filter state as the authoritative current filter value
        selected_labels = self._filter_state.labels

        unique_labels_list = (
            list(precomputed) if precomputed is not None else []
        )
        if precomputed is None:
            for item in self.label_list:
                unique_labels_list.append(str(item.shape().label))
            unique_labels_list = list(set(unique_labels_list))

        # Build combo display: "All Labels" (empty) + all unique labels
        unique_labels_list.append("")
        # Ensure selected labels are in the list (cross-image persistence)
        for lbl in selected_labels:
            if lbl and lbl not in unique_labels_list:
                unique_labels_list.append(lbl)
        unique_labels_list.sort()
        blocker = None
        if block_signal:
            blocker = QtCore.QSignalBlocker(
                self.label_filter_combobox.text_box
            )
        self.label_filter_combobox.update_items(unique_labels_list)
        del blocker

    def update_gid_box(self, block_signal=False, precomputed=None):
        # Use filter state as the authoritative current filter value
        filter_gid = self._filter_state.gid
        current_gid = (
            filter_gid
            if filter_gid != "-1"
            else self.gid_filter_combobox.gid_box.currentText()
        )

        unique_gid_list = list(precomputed) if precomputed is not None else []
        if precomputed is None:
            for item in self.label_list:
                gid = item.shape().group_id
                if gid is not None:
                    unique_gid_list.append(str(gid))
            unique_gid_list = list(set(unique_gid_list))

        # Add a null row for showing all the labels
        unique_gid_list.append("-1")
        if (
            current_gid
            and current_gid != "-1"
            and current_gid not in unique_gid_list
        ):
            unique_gid_list.append(current_gid)
        unique_gid_list.sort()
        blocker = None
        if block_signal:
            blocker = QtCore.QSignalBlocker(self.gid_filter_combobox.gid_box)
        self.gid_filter_combobox.update_items(unique_gid_list)
        self.set_gid_filter_value(current_gid, block_signal=block_signal)
        del blocker

    def save_labels(self, filename):
        label_file = LabelFile()
        # Get current shapes
        # Excluding auto labeling special shapes
        shapes = [
            item.shape().to_dict()
            for item in self.label_list
            if item.shape().label
            not in [
                AutoLabelingMode.OBJECT,
                AutoLabelingMode.ADD,
                AutoLabelingMode.REMOVE,
            ]
        ]
        flags = {}
        for i in range(self.flag_widget.count()):
            item = self.flag_widget.item(i)
            key = item.text()
            flag = item.checkState() == Qt.CheckState.Checked
            flags[key] = flag
        self.other_data[CHECKED_FIELD] = self._annotation_checked()
        try:
            image_path = osp.relpath(self.image_path, osp.dirname(filename))
            image_data = (
                self.image_data if self._config["store_data"] else None
            )
            if osp.dirname(filename) and not osp.exists(osp.dirname(filename)):
                os.makedirs(osp.dirname(filename))

            label_file.save(
                filename=filename,
                shapes=shapes,
                image_path=image_path,
                image_data=image_data,
                image_height=self.image.height(),
                image_width=self.image.width(),
                other_data=self.other_data,
                flags=flags,
            )
            self.label_file = label_file
            items = self.file_list_widget.findItems(
                self.image_path, Qt.MatchFlag.MatchExactly
            )
            if len(items) > 0:
                if len(items) != 1:
                    raise RuntimeError("There are duplicate files.")
                items[0].setCheckState(Qt.CheckState.Checked)
                self._set_file_item_checked(
                    items[0], self._annotation_checked()
                )
            # disable allows next and previous image to proceed
            # Refresh derived index for the saved file
            if self._dataset_index_worker is not None:
                self._pending_dataset_index_refresh_files.add(self.image_path)
            elif self._dataset_filter_index is not None:
                self._dataset_filter_index.refresh_file(
                    self.image_path, self.output_dir
                )
            return True
        except LabelFileError as e:
            self.error_message(
                self.tr("Error saving label data"), self.tr("<b>%s</b>") % e
            )
            return False

    def duplicate_selected_shape(self):
        added_shapes = self.canvas.duplicate_selected_shapes()
        self.label_list.clearSelection()
        self.label_list.setUpdatesEnabled(False)
        try:
            for shape in added_shapes:
                self.add_label(shape, refresh_filters=False)
        finally:
            self.label_list.setUpdatesEnabled(True)
        if added_shapes:
            self._refresh_shape_filters()
        self.set_dirty()

    def paste_selected_shape(self):
        if self._config["system_clipboard"]:
            clipboard = QtWidgets.QApplication.clipboard()
            json_str = clipboard.text()
            shapes = []
            try:
                shapeDicts = json.loads(json_str)
                for shapeDict in shapeDicts:
                    shapes.append(Shape().load_from_dict(shapeDict))
            except json.JSONDecodeError as e:
                self.error_message(
                    self.tr("Error pasting shapes"),
                    self.tr("Error decoding shapes: %s") % str(e),
                )
                return
            self.load_shapes(shapes, replace=False)
        else:
            self.load_shapes(self._copied_shapes, replace=False)
        self.set_dirty()

    def toggle_system_clipboard(self, system_clipboard):
        self._config["system_clipboard"] = system_clipboard
        self.actions.paste.setEnabled(
            bool(system_clipboard or self._copied_shapes)
        )

    def copy_selected_shape(self):
        if self._config["system_clipboard"]:
            clipboard = QtWidgets.QApplication.clipboard()
            clipboard.setText(
                json.dumps([s.to_dict() for s in self.canvas.selected_shapes])
            )
        else:
            self._copied_shapes = [
                s.copy() for s in self.canvas.selected_shapes
            ]
            self.actions.paste.setEnabled(len(self._copied_shapes) > 0)

    def text_selection_changed(self, index):
        # Single-label combobox change: treat as set replacement
        label = self.label_filter_combobox.text_box.currentText()
        if label in ("", None):
            self._filter_state.set_labels(set())
        else:
            self._filter_state.set_labels({str(label)})
        self._apply_combined_shape_filters()

    def gid_selection_changed(self, index):
        raw_gid = self.gid_filter_combobox.gid_box.currentText()
        self._filter_state.set_gid(raw_gid)
        self._apply_combined_shape_filters()

    def label_selection_changed(self):
        if self._no_selection_slot:
            return
        if self.canvas.editing():
            selected_shapes = []
            for item in self.label_list.selected_items():
                selected_shapes.append(item.shape())
            if selected_shapes:
                self.canvas.select_shapes(selected_shapes)
            else:
                self.canvas.deselect_shape()

    def label_item_changed(self, item):
        shape = item.shape()
        shape.visible = item.checkState() == Qt.CheckState.Checked
        self.canvas.set_shape_visible(
            shape, item.checkState() == Qt.CheckState.Checked
        )
        self._update_select_toggle_button_tooltip()
        if (
            hasattr(self, "navigator_dialog")
            and self.navigator_dialog.isVisible()
        ):
            self.update_navigator_shapes()

    def label_order_changed(self):
        self.set_dirty()
        self.canvas.load_shapes([item.shape() for item in self.label_list])

    # Callback functions:
    def new_shape(self):
        """Pop-up and give focus to the label editor.

        position MUST be in global coordinates.
        """
        # Keypoint fill mode: auto-assign label and group_id for new points
        if (
            hasattr(self, "keypoint_fill_mode")
            and self.keypoint_fill_mode.is_active
        ):
            shape = self.canvas.shapes[-1] if self.canvas.shapes else None
            if shape and getattr(shape, "shape_type", None) == "point":
                label, group_id = (
                    self.keypoint_fill_mode.get_next_label_and_group_id()
                )
                if label and group_id is not None:
                    shape.label = label
                    shape.group_id = group_id
                    self.add_label(shape)
                    self.canvas.shapes_backups.pop()
                    self.canvas.store_shapes()
                    self.keypoint_fill_mode.advance()
                    self.set_dirty()
                    return

        items = self.unique_label_list.selectedItems()
        text = None
        if items:
            text = items[0].data(Qt.ItemDataRole.UserRole)
        flags = {}
        group_id = None
        description = ""
        difficult = False
        kie_linking = []

        if self.canvas.shapes[-1].label in [
            AutoLabelingMode.ADD,
            AutoLabelingMode.REMOVE,
        ]:
            text = self.canvas.shapes[-1].label
        elif (
            self._config["display_label_popup"]
            or not text
            or self.canvas.shapes[-1].label == AutoLabelingMode.OBJECT
        ):
            last_label = self.find_last_label()
            last_gid = (
                self.find_last_gid()
                if self._config["auto_use_last_gid"]
                else None
            )
            if self.digit_to_label is not None:
                text = self.digit_to_label
                self.digit_to_label = None
                if last_gid is not None:
                    group_id = last_gid
            elif self._config["auto_use_last_label"] and last_label:
                text = last_label
                if last_gid is not None:
                    group_id = last_gid
            else:
                previous_text = self.label_dialog.edit.text()
                (
                    text,
                    flags,
                    group_id,
                    description,
                    difficult,
                    kie_linking,
                ) = self.label_dialog.pop_up(
                    text,
                    group_id=last_gid,
                    move_mode=self._config.get("move_mode", "auto"),
                )
                if not text:
                    self.label_dialog.edit.setText(previous_text)

        if text and not self.validate_label(text):
            self.error_message(
                self.tr("Invalid label"),
                self.tr("Invalid label '{}' with validation type '{}'").format(
                    text, self._config["validate_label"]
                ),
            )
            text = ""
            return

        if self.attributes and text:
            text = self.reset_attribute(text, self.canvas.shapes[-1])

        if text:
            self.label_list.clearSelection()
            shape = self.canvas.set_last_label(text, flags, group_id)
            shape.group_id = group_id
            shape.description = description
            if text not in [AutoLabelingMode.ADD, AutoLabelingMode.REMOVE]:
                shape.label = text
            shape.difficult = difficult
            shape.kie_linking = kie_linking
            self.add_label(shape)
            self.actions.edit_mode.setEnabled(True)
            self.actions.undo_last_point.setEnabled(False)
            self.actions.undo.setEnabled(True)
            self.set_dirty()
            if (
                self.canvas.drawing()
                and self.canvas.create_mode == "polygon"
                and not self.actions.create_brush_polygon_mode.isEnabled()
            ):
                self.canvas._brush_drawing = True

            shape.selected = True
            self.show_attributes_panel()
            for i, canvas_shape in enumerate(self.canvas.shapes):
                if canvas_shape is shape:
                    self.update_attributes(i)
                    break
        else:
            self.canvas.undo_last_line()
            self.canvas.shapes_backups.pop()

    def show_shape(self, shape_height, shape_width, pos):
        """Display annotation width and height while hovering inside.

        Parameters:
        - shape_height (float): The height of the shape.
        - shape_width (float): The width of the shape.
        - pos (QPointF): The current mouse coordinates inside the shape.
        """
        num_images = len(self.image_list)
        if shape_height > 0 and shape_width > 0:
            if num_images and self.filename in self.image_list:
                self.status(
                    str(self.tr("X: %d, Y: %d | H: %d, W: %d"))
                    % (
                        int(pos.x()),
                        int(pos.y()),
                        shape_height,
                        shape_width,
                    )
                )
            else:
                self.status(
                    str(self.tr("X: %d, Y: %d | H: %d, W: %d"))
                    % (int(pos.x()), int(pos.y()), shape_height, shape_width)
                )
        elif self.image_path:
            if num_images and self.filename in self.image_list:
                self.status(
                    str(self.tr("X: %d, Y: %d"))
                    % (
                        int(pos.x()),
                        int(pos.y()),
                    )
                )
            else:
                self.status(
                    str(self.tr("X: %d, Y: %d")) % (int(pos.x()), int(pos.y()))
                )

    def on_navigator_request(self, x_ratio, y_ratio):
        """Handle navigation request from navigator widget."""
        if not hasattr(self, "image") or self.image.isNull():
            return

        scroll_area = self._central_widget
        canvas_size = self.canvas.size()
        scroll_area_size = scroll_area.viewport().size()

        target_x = x_ratio * canvas_size.width() - scroll_area_size.width() / 2
        target_y = (
            y_ratio * canvas_size.height() - scroll_area_size.height() / 2
        )

        self.set_scroll(Qt.Orientation.Horizontal, target_x)
        self.set_scroll(Qt.Orientation.Vertical, target_y)

    def update_navigator_viewport(self):
        """Update the viewport rectangle in the navigator."""
        if not hasattr(self, "navigator_dialog") or not hasattr(self, "image"):
            return

        if not self.navigator_dialog.isVisible():
            return

        if self.image.isNull():
            return

        scroll_area = self._central_widget
        canvas_size = self.canvas.size()
        scroll_area_size = scroll_area.viewport().size()
        if canvas_size.width() <= 0 or canvas_size.height() <= 0:
            return

        h_scroll = self.scroll_bars[Qt.Orientation.Horizontal].value()
        v_scroll = self.scroll_bars[Qt.Orientation.Vertical].value()
        x_ratio = max(0.0, h_scroll / canvas_size.width())
        y_ratio = max(0.0, v_scroll / canvas_size.height())
        width_ratio = min(1.0, scroll_area_size.width() / canvas_size.width())
        height_ratio = min(
            1.0, scroll_area_size.height() / canvas_size.height()
        )

        self.navigator_dialog.set_viewport(
            x_ratio, y_ratio, width_ratio, height_ratio
        )
        self.update_navigator_shapes()

    def update_navigator_shapes(self):
        """Update shapes overlay in navigator."""
        if (
            not hasattr(self, "navigator_dialog")
            or not self.navigator_dialog.isVisible()
        ):
            return

        shapes = getattr(self.canvas, "shapes", [])
        canvas_visible = getattr(self.canvas, "visible", {})
        h_shape = getattr(self.canvas, "h_hape", None)
        for shape in shapes:
            shape._is_highlighted = shape == h_shape
        self.navigator_dialog.set_shapes(shapes, canvas_visible)

    def on_navigator_zoom_changed(
        self, zoom_percentage: int, mouse_pos: Optional[QtCore.QPoint] = None
    ) -> None:
        """Handle zoom change from navigator controls."""

        if not hasattr(self, "image") or self.image.isNull():
            return

        if mouse_pos is not None:
            canvas_pos = self._convert_navigator_pos_to_canvas(mouse_pos)
            if canvas_pos:
                canvas_width_old = self.canvas.width()

                self.zoom_widget.setValue(zoom_percentage)
                self.zoom_mode = self.MANUAL_ZOOM
                self.zoom_values[self.filename] = (
                    self.zoom_mode,
                    zoom_percentage,
                )
                self.paint_canvas()

                canvas_width_new = self.canvas.width()
                if canvas_width_old != canvas_width_new:
                    canvas_scale_factor = canvas_width_new / canvas_width_old
                    x_shift = round(
                        canvas_pos.x() * canvas_scale_factor - canvas_pos.x()
                    )
                    y_shift = round(
                        canvas_pos.y() * canvas_scale_factor - canvas_pos.y()
                    )
                    self.set_scroll(
                        QtCore.Qt.Orientation.Horizontal,
                        self.scroll_bars[
                            QtCore.Qt.Orientation.Horizontal
                        ].value()
                        + x_shift,
                    )
                    self.set_scroll(
                        QtCore.Qt.Orientation.Vertical,
                        self.scroll_bars[
                            QtCore.Qt.Orientation.Vertical
                        ].value()
                        + y_shift,
                    )

                return

        # Handle direct zoom changes
        if (
            hasattr(self, "canvas")
            and hasattr(self.canvas, "width")
            and hasattr(self.canvas, "height")
        ):
            if hasattr(self.navigator_dialog, "navigator"):
                nav_widget = self.navigator_dialog.navigator
                if (
                    hasattr(nav_widget, "viewport_rect")
                    and not nav_widget.viewport_rect.isEmpty()
                ):
                    nav_rect_center_x = nav_widget.viewport_rect.center().x()
                    nav_rect_center_y = nav_widget.viewport_rect.center().y()
                    canvas_pos = self._convert_navigator_pos_to_canvas(
                        QtCore.QPoint(
                            int(nav_rect_center_x), int(nav_rect_center_y)
                        )
                    )

                    if canvas_pos:
                        canvas_width_old = self.canvas.width()

                        self.zoom_widget.setValue(zoom_percentage)
                        self.zoom_mode = self.MANUAL_ZOOM
                        self.zoom_values[self.filename] = (
                            self.zoom_mode,
                            zoom_percentage,
                        )
                        self.paint_canvas()

                        canvas_width_new = self.canvas.width()
                        if canvas_width_old != canvas_width_new:
                            canvas_scale_factor = (
                                canvas_width_new / canvas_width_old
                            )
                            x_shift = round(
                                canvas_pos.x() * canvas_scale_factor
                                - canvas_pos.x()
                            )
                            y_shift = round(
                                canvas_pos.y() * canvas_scale_factor
                                - canvas_pos.y()
                            )
                            self.set_scroll(
                                QtCore.Qt.Orientation.Horizontal,
                                self.scroll_bars[
                                    QtCore.Qt.Orientation.Horizontal
                                ].value()
                                + x_shift,
                            )
                            self.set_scroll(
                                QtCore.Qt.Orientation.Vertical,
                                self.scroll_bars[
                                    QtCore.Qt.Orientation.Vertical
                                ].value()
                                + y_shift,
                            )
                        return

            self.zoom_widget.setValue(zoom_percentage)
            self.zoom_mode = self.MANUAL_ZOOM
            self.zoom_values[self.filename] = (self.zoom_mode, zoom_percentage)
            self.paint_canvas()
        else:
            self.zoom_widget.setValue(zoom_percentage)
            self.zoom_mode = self.MANUAL_ZOOM
            self.zoom_values[self.filename] = (self.zoom_mode, zoom_percentage)
            self.paint_canvas()

    def _convert_navigator_pos_to_canvas(
        self, navigator_pos: QtCore.QPoint
    ) -> Optional[QtCore.QPoint]:
        """Convert navigator mouse position to canvas coordinates."""
        if (
            not hasattr(self, "navigator_dialog")
            or not self.navigator_dialog.isVisible()
        ):
            return None

        navigator_widget = self.navigator_dialog.navigator
        if (
            not navigator_widget.image_rect
            or navigator_widget.image_rect.isEmpty()
        ):
            return None

        relative_x = navigator_pos.x() - navigator_widget.image_rect.x()
        relative_y = navigator_pos.y() - navigator_widget.image_rect.y()
        if (
            relative_x < 0
            or relative_x > navigator_widget.image_rect.width()
            or relative_y < 0
            or relative_y > navigator_widget.image_rect.height()
        ):
            return None

        # Convert to ratio (0.0 to 1.0)
        x_ratio = relative_x / navigator_widget.image_rect.width()
        y_ratio = relative_y / navigator_widget.image_rect.height()

        # Convert to canvas coordinates
        canvas_x = int(x_ratio * self.canvas.width())
        canvas_y = int(y_ratio * self.canvas.height())

        return QtCore.QPoint(canvas_x, canvas_y)

    def on_navigator_viewport_update_requested(self):
        """Handle viewport update request from navigator resize"""
        QtCore.QTimer.singleShot(50, self.update_navigator_viewport)

    def toggle_navigator(self):
        """Toggle the navigator window visibility"""
        if self.navigator_dialog.isVisible():
            self.navigator_dialog.hide()
            if hasattr(self, "actions") and hasattr(
                self.actions, "show_navigator"
            ):
                self.actions.show_navigator.setChecked(False)
        else:
            self.navigator_dialog.show()
            if hasattr(self, "image") and not self.image.isNull():
                self.navigator_dialog.set_image(
                    QtGui.QPixmap.fromImage(self.image)
                )
                self.update_navigator_viewport()
            if hasattr(self, "actions") and hasattr(
                self.actions, "show_navigator"
            ):
                self.actions.show_navigator.setChecked(True)

    def scroll_request(self, delta, orientation, mode):
        scroll_bar = self.scroll_bars[orientation]
        units = -delta * (0.1 if mode == 0 else 1)
        step = scroll_bar.singleStep() if mode == 0 else scroll_bar.maximum()
        value = scroll_bar.value() + step * units
        self.set_scroll(orientation, value)

    def set_scroll(self, orientation, value):
        self.scroll_bars[orientation].setValue(round(value))
        self.scroll_values[orientation][self.filename] = value
        self.update_navigator_viewport()

    def set_zoom(self, value, block_signals=False):
        self.actions.fit_width.setChecked(False)
        self.actions.fit_window.setChecked(False)
        self.zoom_mode = self.MANUAL_ZOOM
        if block_signals:
            self.zoom_widget.blockSignals(True)
        self.zoom_widget.setValue(value)
        if block_signals:
            self.zoom_widget.blockSignals(False)
        self.zoom_values[self.filename] = (self.zoom_mode, value)
        if hasattr(self, "navigator_dialog"):
            self.navigator_dialog.set_zoom_value(value)

    def add_zoom(self, increment=1.1):
        zoom_value = self.zoom_widget.value() * increment
        if increment > 1:
            zoom_value = math.ceil(zoom_value)
        else:
            zoom_value = math.floor(zoom_value)
        self.set_zoom(zoom_value)

    def zoom_request(self, delta, pos):
        canvas_width_old = self.canvas.width()
        units = 1.1
        if delta < 0:
            units = 0.9
        self.add_zoom(units)

        canvas_width_new = self.canvas.width()
        if canvas_width_old != canvas_width_new:
            canvas_scale_factor = canvas_width_new / canvas_width_old

            x_shift = round(pos.x() * canvas_scale_factor - pos.x())
            y_shift = round(pos.y() * canvas_scale_factor - pos.y())

            self.set_scroll(
                Qt.Orientation.Horizontal,
                self.scroll_bars[Qt.Orientation.Horizontal].value() + x_shift,
            )
            self.set_scroll(
                Qt.Orientation.Vertical,
                self.scroll_bars[Qt.Orientation.Vertical].value() + y_shift,
            )

    def set_fit_window(self, value=True):
        if value:
            self.actions.fit_width.setChecked(False)
        self.zoom_mode = self.FIT_WINDOW if value else self.MANUAL_ZOOM
        self.adjust_scale()

    def set_fit_width(self, value=True):
        if value:
            self.actions.fit_window.setChecked(False)
        self.zoom_mode = self.FIT_WIDTH if value else self.MANUAL_ZOOM
        self.adjust_scale()

    def set_cross_line(self):
        crosshair_dialog = CrosshairSettingsDialog(**self.crosshair_settings)
        if crosshair_dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            crosshair_settings = crosshair_dialog.get_settings()
            show = crosshair_settings["show"]
            width = crosshair_settings["width"]
            color = crosshair_settings["color"]
            opacity = crosshair_settings["opacity"]
            self.canvas.set_cross_line(show, width, color, opacity)
            self._config["canvas"]["crosshair"] = crosshair_settings

    def set_canvas_params(self, key, value):
        self._config[key] = value
        assert hasattr(self.canvas, key), f"Canvas has no attribute {key}"
        setattr(self.canvas, key, value)
        self.canvas.update()

    def toggle_pose_view(self, enabled: bool) -> None:
        """Toggle the Pose View rendering mode on the canvas.

        Args:
            enabled: Whether pose view should be active.
        """
        self.canvas.pose_config.enabled = enabled
        self._sync_pose_config()
        if hasattr(self, "pose_view_panel"):
            self.pose_view_panel.setVisible(enabled)
        self.canvas.update()

    def _sync_pose_config(self) -> None:
        """Copy PoseDisplayConfig fields into self._config['pose_view']."""
        if "pose_view" not in self._config:
            self._config["pose_view"] = {}
        self._config["pose_view"].update(self.canvas.pose_config.to_dict())

    def _on_pose_panel_changed(self) -> None:
        """Handle pose panel parameter changes: repaint + sync config."""
        self.canvas.update()
        self._sync_pose_config()

    def open_settings_dialog(self):
        if self._settings_controller is None:
            return
        if self._settings_dialog is None:
            self._settings_dialog = SettingsDialog(
                self, self._settings_controller
            )
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    def add_point_to_edge(self):
        shape = self.canvas.prev_h_shape
        edge_index = self.canvas.prev_h_edge
        point = self.canvas.prev_move_point
        if shape is None or edge_index is None or point is None:
            return
        self.canvas.add_point_to_edge()
        self.canvas.update()
        self.set_dirty()

    def on_new_brightness_contrast(self, qimage):
        self.canvas.load_pixmap(
            QtGui.QPixmap.fromImage(qimage), clear_shapes=False
        )

    def brightness_contrast(self, _):
        self.brightness_contrast_dialog.update_image(
            utils.img_data_to_pil(self.image_data)
        )

        brightness, contrast = self.brightness_contrast_values.get(
            self.filename, (None, None)
        )
        if brightness is not None:
            self.brightness_contrast_dialog.slider_brightness.setValue(
                brightness
            )
        if contrast is not None:
            self.brightness_contrast_dialog.slider_contrast.setValue(contrast)

        self.brightness_contrast_dialog.exec()

        brightness = self.brightness_contrast_dialog.slider_brightness.value()
        contrast = self.brightness_contrast_dialog.slider_contrast.value()
        self.brightness_contrast_values[self.filename] = (brightness, contrast)

    def hide_selected_polygons(self):
        shapes_to_hide = []
        for item in self.label_list:
            if item.shape().selected:
                item.setCheckState(Qt.CheckState.Unchecked)
                item.shape().visible = False
                shapes_to_hide.append(item.shape())

        self.selected_polygon_stack.extend(shapes_to_hide)
        self.canvas.update()
        if (
            hasattr(self, "navigator_dialog")
            and self.navigator_dialog.isVisible()
        ):
            self.update_navigator_shapes()

    def show_hidden_polygons(self):
        if self.selected_polygon_stack:
            shape_to_show = self.selected_polygon_stack.pop()
            item = self.label_list.find_item_by_shape(shape_to_show)
            if item:
                item.setCheckState(Qt.CheckState.Checked)
                shape_to_show.visible = True
                self.canvas.update()
                if (
                    hasattr(self, "navigator_dialog")
                    and self.navigator_dialog.isVisible()
                ):
                    self.update_navigator_shapes()
            else:
                logger.warning(
                    f"Shape associated with the hidden item was not found in label list, could not show."
                )

    def get_next_files(self, filename, num_files):
        """Get the next files in the list."""
        if not self.image_list:
            return []
        filenames = []
        current_index = 0
        if filename is not None:
            try:
                current_index = self.fn_to_index[str(filename)]
            except ValueError:
                return []
            filenames.append(filename)
        for _ in range(num_files):
            if current_index + 1 < len(self.image_list):
                filenames.append(self.image_list[current_index + 1])
                current_index += 1
            else:
                filenames.append(self.image_list[-1])
                break
        return filenames

    def inform_next_files(self, filename):
        """Inform the next files to be annotated.
        This list can be used by the user to preload the next files
        or running a background process to process them
        """
        next_files = self.get_next_files(filename, 5)
        if next_files:
            self.next_files_changed.emit(next_files)

    def load_file(self, filename=None):  # noqa: C901
        """Load the specified file, or the last opened file if None."""
        _t_load = time.perf_counter()

        # NOTE(jack): Does we need to save the config here?
        # save_config(self._config)

        # For auto labeling, clear the previous marks
        # and inform the next files to be annotated
        # NOTE(jack): this is not needed for now
        # self.clear_auto_labeling_marks()
        # self.inform_next_files(filename)

        # Keep file list selection in sync without deferring actual loading to
        # itemSelectionChanged. Deferring created a two-stage next-image path.
        self._sync_file_list_current_row(filename)

        # ① Save viewport of the image we are leaving
        self.viewport_controller.on_file_leaving(
            filename=self.viewport_controller.last_loaded,
            canvas=self.canvas,
            zoom_widget=self.zoom_widget,
            zoom_mode=self.zoom_mode,
        )

        # Save current filter values for cross-page persistence
        if self._global_filter_keep_enabled:
            self._pending_filter_restore = self._copy_filter_state()
        else:
            self._pending_filter_restore = None

        self.reset_state()
        self.canvas.setEnabled(False)

        if filename is None:
            filename = self.settings.value("filename", "")
        filename = str(filename)
        if not QtCore.QFile.exists(filename):
            self.error_message(
                self.tr("Error opening file"),
                self.tr("No such file: <b>%s</b>") % filename,
            )
            return False

        # assumes same name, but json extension
        label_file = osp.splitext(filename)[0] + ".json"
        image_dir = None
        if self.output_dir:
            image_dir = osp.dirname(filename)
            label_file_without_path = osp.basename(label_file)
            label_file = self.output_dir + "/" + label_file_without_path

        if QtCore.QFile.exists(label_file) and LabelFile.is_label_file(
            label_file
        ):
            try:
                _t_label = time.perf_counter()
                self.label_file = LabelFile(label_file, image_dir)
                _perf_log(
                    "load_file label json: %.3fs, %s",
                    time.perf_counter() - _t_label,
                    label_file,
                )
            except LabelFileError as e:
                self.error_message(
                    self.tr("Error opening file"),
                    self.tr(
                        "<p><b>%s</b></p>"
                        "<p>Make sure <i>%s</i> is a valid label file."
                    )
                    % (e, label_file),
                )
                self.status(self.tr("Error reading %s") % label_file)
                return False
            self.image_data = self.label_file.image_data
            self.image_path = osp.join(
                osp.dirname(label_file),
                self.label_file.image_path,
            )
            self.other_data = self.label_file.other_data
            self.other_data[CHECKED_FIELD] = self._annotation_checked()
            self.shape_text_edit.textChanged.disconnect()
            self.shape_text_edit.setPlainText(
                self.other_data.get("description", "")
            )
            self.shape_text_edit.textChanged.connect(self.shape_text_changed)
        else:
            self.image_data = LabelFile.load_image_file(filename)
            if self.image_data:
                self.image_path = filename
            self.label_file = None
            self.other_data = {CHECKED_FIELD: False}
            self.shape_text_edit.textChanged.disconnect()
            self.shape_text_edit.setPlainText("")
            self.shape_text_edit.textChanged.connect(self.shape_text_changed)
        self.shape_text_label.setText(self.tr("Image Description"))
        self.shape_text_edit.setDisabled(False)

        # Reset the label loop count
        self.label_loop_count = -1
        self.select_loop_count = -1

        # TODO(jack): icc profile issue warning
        # - qt.gui.icc: fromIccProfile: failed minimal tag size sanity
        # - qt.gui.icc: fromIccProfile: invalid tag offset alignment
        _t_image = time.perf_counter()
        image = QtGui.QImage.fromData(self.image_data)
        _perf_log(
            "load_file image decode: %.3fs, %s",
            time.perf_counter() - _t_image,
            filename,
        )

        if image.isNull():
            formats = [
                f"*.{fmt.data().decode()}"
                for fmt in QtGui.QImageReader.supportedImageFormats()
            ]
            self.error_message(
                self.tr("Error opening file"),
                self.tr(
                    "<p>Make sure <i>{0}</i> is a valid image file.<br/>"
                    "Supported image formats: {1}</p>"
                ).format(filename, ",".join(formats)),
            )
            self.status(self.tr("Error reading %s") % filename)
            return False
        self.image = image
        self.filename = filename

        if (
            hasattr(self, "navigator_dialog")
            and self.navigator_dialog.isVisible()
        ):
            self.navigator_dialog.set_image(QtGui.QPixmap.fromImage(image))
            self.update_navigator_shapes()
        if (
            hasattr(self, "_should_restore_navigator")
            and self._should_restore_navigator
        ):
            self._should_restore_navigator = False
            if self.navigator_dialog.isVisible():
                self.update_navigator_viewport()
        if self._config["keep_prev"]:
            prev_shapes = self.canvas.shapes
        _t_pixmap = time.perf_counter()
        self.canvas.load_pixmap(QtGui.QPixmap.fromImage(image))
        _perf_log(
            "load_file canvas.load_pixmap: %.3fs, %s",
            time.perf_counter() - _t_pixmap,
            filename,
        )

        # load label flags
        flags = {k: False for k in self.image_flags or []}
        if self.label_file:
            for shape in self.label_file.shapes:
                default_flags = {}
                if self._config["label_flags"]:
                    for pattern, keys in self._config["label_flags"].items():
                        if re.match(pattern, shape.label):
                            for key in keys:
                                default_flags[key] = False
                    shape.flags = {
                        **default_flags,
                        **shape.flags,
                    }
            _t_shapes = time.perf_counter()
            self.load_shapes(
                self.label_file.shapes,
                update_last_label=False,
                store_backup=False,
            )
            _perf_log(
                "load_file load_shapes: %.3fs, count=%d, %s",
                time.perf_counter() - _t_shapes,
                len(self.label_file.shapes),
                filename,
            )
            if self.label_file.flags is not None:
                flags.update(self.label_file.flags)
        self.load_flags(flags)

        # load shapes
        if self._config["keep_prev"] and self.no_shape():
            self.load_shapes(
                prev_shapes,
                replace=False,
                update_last_label=False,
                store_backup=False,
            )
            self.set_dirty()
        else:
            self.set_clean()
        # Correct the checked state of the current file list item after load.
        self._update_current_file_checked_item()
        self.canvas.setEnabled(True)

        # set zoom / viewport values
        is_initial_load = not self.zoom_values
        restored_state = self.viewport_controller.on_file_loaded(
            filename=self.filename,
            canvas=self.canvas,
            zoom_widget=self.zoom_widget,
            keep_prev_viewport=self._config.get("keep_prev_viewport", False),
        )
        if restored_state is not None:
            self.zoom_mode = restored_state.zoom_mode
            self.zoom_values[self.filename] = (
                restored_state.zoom_mode,
                restored_state.zoom_value,
            )
        elif self.filename in self.zoom_values:
            self.zoom_mode = self.zoom_values[self.filename][0]
            self.set_zoom(self.zoom_values[self.filename][1])
        elif is_initial_load or not self._config["keep_prev_scale"]:
            self.adjust_scale(initial=True)

        # Legacy scroll values (fallback when viewport_controller has no state)
        if restored_state is None:
            for orientation in self.scroll_values:
                if self.filename in self.scroll_values[orientation]:
                    self.set_scroll(
                        orientation,
                        self.scroll_values[orientation][self.filename],
                    )

        # set brightness contrast values
        brightness, contrast = self.brightness_contrast_values.get(
            self.filename, (None, None)
        )
        if self._config["keep_prev_brightness"] and self.recent_files:
            brightness, _ = self.brightness_contrast_values.get(
                self.recent_files[0], (None, None)
            )
        if self._config["keep_prev_contrast"] and self.recent_files:
            _, contrast = self.brightness_contrast_values.get(
                self.recent_files[0], (None, None)
            )
        self.brightness_contrast_values[self.filename] = (brightness, contrast)
        if brightness is not None or contrast is not None:
            self.brightness_contrast_dialog.update_image(
                utils.img_data_to_pil(self.image_data)
            )
            if brightness is not None:
                self.brightness_contrast_dialog.slider_brightness.setValue(
                    brightness
                )
            if contrast is not None:
                self.brightness_contrast_dialog.slider_contrast.setValue(
                    contrast
                )
            self.brightness_contrast_dialog.on_new_value()

        _t_canvas = time.perf_counter()
        self.paint_canvas()
        _perf_log(
            "load_file paint_canvas: %.3fs, %s",
            time.perf_counter() - _t_canvas,
            filename,
        )
        self.add_recent_file(self.filename)
        self.toggle_actions(True)
        self.canvas.setFocus()
        self._sync_annotation_checked_state()
        self.update_thumbnail_display()

        if self.compare_view_manager.is_active():
            self.compare_view_manager.load_compare_for_file(self.filename)

        # Refresh keypoint tool window on image change
        if self.keypoint_tool_window is not None:
            self.keypoint_tool_window.refresh_all()

        # Auto-activate keypoint fill mode if enabled and single object found
        self._check_auto_activate_keypoint_fill()

        # Populate inspector editable table with current file's shapes
        self._refresh_inspector_table()

        _perf_log(
            "load_file total: %.3fs, %s",
            time.perf_counter() - _t_load,
            filename,
        )

        return True

    # Instance visibility shortcuts and methods
    def _setup_instance_visibility_shortcuts(self):
        """Setup keyboard shortcuts for instance visibility control"""
        # H: Hide current instance
        self.hide_instance_shortcut = QShortcut(QtGui.QKeySequence("H"), self)
        self.hide_instance_shortcut.activated.connect(
            self.hide_current_instance
        )

        # Shift+H: Focus mode (hide all except current)
        self.focus_instance_shortcut = QShortcut(
            QtGui.QKeySequence("Shift+H"), self
        )
        self.focus_instance_shortcut.activated.connect(
            self.focus_current_instance
        )

        # Ctrl+Shift+H: Show all instances
        self.show_all_shortcut = QShortcut(
            QtGui.QKeySequence("Ctrl+Shift+H"), self
        )
        self.show_all_shortcut.activated.connect(self.show_all_instances)

        # Alt+H: Toggle auto-focus instance mode
        self.auto_focus_instance = False
        self.auto_focus_instance_shortcut = QShortcut(
            QtGui.QKeySequence("Alt+H"), self
        )
        self.auto_focus_instance_shortcut.activated.connect(
            self.toggle_auto_focus_instance
        )

    def hide_current_instance(self):
        """Hide the currently selected instance (same group_id)"""
        selected_shapes = getattr(self.canvas, "selected_shapes", [])
        if not selected_shapes:
            self.status(self.tr("No shape selected"))
            return
        current_shape = selected_shapes[0]
        if current_shape.group_id is None:
            self.status(self.tr("Selected shape has no group_id"))
            return
        target_group_id = current_shape.group_id
        for shape in self.canvas.shapes:
            if shape.group_id == target_group_id:
                shape.hidden_by_filter = True
        self.canvas.update()
        self.status(
            self.tr(f"Hidden instance with group_id={target_group_id}")
        )

    def focus_current_instance(self):
        """Focus mode: hide all instances except current"""
        selected_shapes = getattr(self.canvas, "selected_shapes", [])
        if not selected_shapes:
            self.status(self.tr("No shape selected"))
            return
        current_shape = selected_shapes[0]
        if current_shape.group_id is None:
            self.status(self.tr("Selected shape has no group_id"))
            return
        target_group_id = current_shape.group_id
        for shape in self.canvas.shapes:
            shape.hidden_by_filter = shape.group_id != target_group_id
        self.canvas.update()
        self.status(
            self.tr(f"Focus mode: only showing group_id={target_group_id}")
        )

    def show_all_instances(self):
        """Show all instances"""
        for shape in self.canvas.shapes:
            shape.hidden_by_filter = False
        self.canvas.update()
        self.status(self.tr("All instances visible"))

    def toggle_auto_focus_instance(self):
        """Toggle auto-focus instance aggregation mode."""
        self.auto_focus_instance = not self.auto_focus_instance
        if self.auto_focus_instance:
            self.status(
                self.tr("自动聚合模式已开启（选中即聚焦，ESC 退出聚合）"), 3000
            )
        else:
            self.show_all_instances()
            self.status(self.tr("自动聚合模式已关闭"), 2000)

    def _auto_focus_on_selection(self, selected_shapes):
        """Auto-focus the selected shape's group_id if auto-focus is on."""
        if not self.auto_focus_instance:
            return
        if not selected_shapes:
            return
        current_shape = selected_shapes[0]
        if current_shape.group_id is None:
            return
        target_group_id = current_shape.group_id
        for shape in self.canvas.shapes:
            shape.hidden_by_filter = shape.group_id != target_group_id
        self.canvas.update()
        self.status(
            self.tr("自动聚合: group_id={gid}").format(gid=target_group_id),
            2000,
        )

    def _escape_auto_focus_if_active(self):
        """Handle ESC in auto-focus mode: temporarily show all instances."""
        if not self.auto_focus_instance:
            return False
        has_hidden = any(
            getattr(s, "hidden_by_filter", False) for s in self.canvas.shapes
        )
        if not has_hidden:
            return False
        for shape in self.canvas.shapes:
            shape.hidden_by_filter = False
        self.canvas.update()
        self.status(self.tr("已退出聚合（自动聚合模式仍开启）"), 2000)
        return True

    # QT Overload
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self._escape_auto_focus_if_active():
                event.accept()
                return
            event.accept()
            return
        super(LabelingWidget, self).keyPressEvent(event)

    def resizeEvent(self, _):
        if (
            self.canvas
            and not self.image.isNull()
            and self.zoom_mode != self.MANUAL_ZOOM
        ):
            self.adjust_scale()
        self.update_thumbnail_pixmap()

    def paint_canvas(self):
        if self.image.isNull():
            return
        self.canvas.scale = 0.01 * self.zoom_widget.value()
        self.canvas.adjustSize()
        self.canvas.update()
        self.update_navigator_viewport()

    def adjust_scale(self, initial=False):
        value = self.scalers[self.FIT_WINDOW if initial else self.zoom_mode]()
        value = int(100 * value)
        self.zoom_widget.setValue(value)
        self.zoom_values[self.filename] = (self.zoom_mode, value)
        if hasattr(self, "navigator_dialog"):
            self.navigator_dialog.set_zoom_value(value)

    def scale_fit_window(self):
        """Figure out the size of the pixmap to fit the main widget."""
        e = 2.0  # So that no scrollbars are generated.
        w1 = self.central_widget().width() - e
        h1 = self.central_widget().height() - e
        wh_ratio1 = w1 / h1
        # Calculate a new scale value based on the pixmap's aspect ratio.
        w2 = self.canvas.pixmap.width() - 0.0
        h2 = self.canvas.pixmap.height() - 0.0
        wh_ratio2 = w2 / h2
        return w1 / w2 if wh_ratio2 >= wh_ratio1 else h1 / h2

    def scale_fit_width(self):
        # The epsilon does not seem to work too well here.
        w = self.central_widget().width() - 2.0
        return w / self.canvas.pixmap.width()

    # ------------------------------------------------------------------ #
    # Viewport state reset helpers
    # ------------------------------------------------------------------ #

    def _clear_view_state_for_files(self, filenames):
        """清除指定文件列表的视图状态。

        同时清理 viewport_controller、zoom_values 和 scroll_values，
        防止后续从旧缓存恢复。

        Returns:
            实际清理的文件数量。
        """
        count = 0
        for filename in filenames:
            removed = self.viewport_controller.clear_state(filename)
            zoom_removed = self.zoom_values.pop(filename, None) is not None
            h_removed = (
                self.scroll_values[Qt.Orientation.Horizontal].pop(
                    filename, None
                )
                is not None
            )
            v_removed = (
                self.scroll_values[Qt.Orientation.Vertical].pop(filename, None)
                is not None
            )
            if removed or zoom_removed or h_removed or v_removed:
                count += 1
        return count

    def _get_files_from_target_to_end(self, target_file):
        """获取从 target_file 到 image_list 末尾的所有文件。"""
        if target_file not in self.fn_to_index:
            return []
        idx = self.fn_to_index[target_file]
        return self.image_list[idx:]

    def _get_files_from_current_to_end(self):
        """获取从当前文件到 image_list 末尾的所有文件。"""
        if self.filename is None or self.filename not in self.fn_to_index:
            return []
        return self._get_files_from_target_to_end(self.filename)

    def _reset_image_views_for_files(self, filenames, scope_label):
        """统一重置指定文件列表的视图状态并给出状态栏反馈。

        如果目标范围包含当前正在显示的图片，则立即恢复默认视图。
        """
        if not filenames:
            self.status(self.tr("没有可重置的图像视图状态"), 3000)
            return

        should_reset_current = (
            self.filename in filenames and self.filename is not None
        )
        cleared = self._clear_view_state_for_files(filenames)
        if cleared == 0 and not should_reset_current:
            self.status(
                self.tr("未找到可重置的 {scope} 图像视图状态").format(
                    scope=scope_label
                ),
                3000,
            )
            return

        if should_reset_current and not self.image.isNull():
            self.zoom_mode = self.FIT_WINDOW
            self.adjust_scale(initial=True)
            h_bar = self.scroll_bars[Qt.Orientation.Horizontal]
            v_bar = self.scroll_bars[Qt.Orientation.Vertical]
            if h_bar is not None:
                h_bar.setValue(h_bar.minimum())
            if v_bar is not None:
                v_bar.setValue(v_bar.minimum())
            self.paint_canvas()

        self.status(
            self.tr("已重置 {scope} 的 {count} 个图像视图状态").format(
                scope=scope_label, count=cleared
            ),
            3000,
        )

    def reset_current_image_view(self):
        """重置当前图像的视图状态。"""
        if self.filename is None:
            self.status(self.tr("请先打开一张图片"), 3000)
            return
        self._reset_image_views_for_files([self.filename], self.tr("当前图像"))

    def reset_views_from_current_to_end(self):
        """重置从当前图像到末尾的所有图像视图状态。"""
        filenames = self._get_files_from_current_to_end()
        self._reset_image_views_for_files(filenames, self.tr("从当前到末尾"))

    def reset_all_image_views(self):
        """重置所有图像的视图状态。"""
        filenames = list(self.image_list)
        self._reset_image_views_for_files(filenames, self.tr("全部"))

    # QT Overload
    def closeEvent(self, event):
        if not self.may_continue():
            event.ignore()
        self.settings.setValue(
            "filename", self.filename if self.filename else ""
        )
        self.settings.setValue("recent_files", self.recent_files)
        if self.last_open_dir:
            self.settings.setValue("last_open_dir", self.last_open_dir)

        if hasattr(self, "navigator_dialog"):
            navigator_visible = self.navigator_dialog.isVisible()
            self.settings.setValue("navigator/visible", navigator_visible)
            if navigator_visible:
                self.settings.setValue(
                    "navigator/geometry", self.navigator_dialog.saveGeometry()
                )
                self.settings.setValue(
                    "navigator/size", self.navigator_dialog.size()
                )
                self.settings.setValue(
                    "navigator/position", self.navigator_dialog.pos()
                )

        if self._settings_controller is not None:
            self._settings_controller.close_session()

        self._sync_pose_config()
        save_config(self._config)

        if hasattr(self, "async_exif_scanner") and self.async_exif_scanner:
            try:
                self.async_exif_scanner.stop_scan()
            except (RuntimeError, AttributeError):
                pass

        # ask the use for where to save the labels
        # self.settings.setValue('window/geometry', self.saveGeometry())

    # QT Overload
    def dragEnterEvent(self, event):
        extensions = [
            f".{fmt.data().decode().lower()}"
            for fmt in QtGui.QImageReader.supportedImageFormats()
        ]
        if event.mimeData().hasUrls():
            items = [i.toLocalFile() for i in event.mimeData().urls()]
            if any(i.lower().endswith(tuple(extensions)) for i in items):
                event.accept()
        else:
            event.ignore()

    # QT Overload
    def dropEvent(self, event):
        if not self.may_continue():
            event.ignore()
            return
        items = [i.toLocalFile() for i in event.mimeData().urls()]
        self.import_dropped_image_files(items)

    def load_recent(self, filename):
        if self.may_continue():
            self.load_file(filename)

    def load_recent_dir(self, dirpath):
        self.import_image_folder(dirpath)

    def open_prev_unchecked_image(self):
        if (
            not self.may_continue()
            or len(self.image_list) <= 0
            or self.filename is None
        ):
            return

        current_index = self.fn_to_index[str(self.filename)]
        for i in range(current_index - 1, -1, -1):
            if not self._file_item_annotation_checked(
                self.file_list_widget.item(i)
            ):
                filename = self.image_list[i]
                if filename:
                    self.load_file(filename)
                break

    def open_next_unchecked_image(self, _value=False):
        if (
            not self.may_continue()
            or len(self.image_list) <= 0
            or self.filename is None
        ):
            return

        current_index = self.fn_to_index[str(self.filename)]
        for i in range(current_index + 1, len(self.image_list)):
            if not self._file_item_annotation_checked(
                self.file_list_widget.item(i)
            ):
                filename = self.image_list[i]
                if filename:
                    self.load_file(filename)
                break

    def open_prev_image(self, _value=False):
        if not self.may_continue():
            return
        if self.file_list_widget.count() <= 0:
            return
        if self.filename is None:
            return
        if self._filter_navigation_active:
            if self._open_prev_filter_navigation_image():
                return
        current_index = self.fn_to_index[str(self.filename)]
        if current_index - 1 >= 0:
            filename = self.file_list_widget.item(current_index - 1).text()
            if filename:
                self.load_file(filename)

    def open_next_image(self, _value=False, load=True):
        _t_next = time.perf_counter()
        _perf_log("open_next_image enter: current=%s", self.filename)
        if not self.may_continue():
            return
        count = self.file_list_widget.count()
        if count <= 0:
            return
        if self._filter_navigation_active:
            if self._open_next_filter_navigation_image(load=load):
                return
        filename = None
        if self.filename is None:
            filename = self.file_list_widget.item(0).text()
        else:
            current_index = self.fn_to_index[str(self.filename)]
            if current_index + 1 < count:
                filename = self.file_list_widget.item(current_index + 1).text()
            else:
                filename = self.file_list_widget.item(count - 1).text()
        self.filename = filename
        if self.filename and load:
            self.load_file(self.filename)
        _perf_log(
            "open_next_image exit: %.3fs, next=%s",
            time.perf_counter() - _t_next,
            self.filename,
        )

    # File
    def open_file(self, _value=False):
        if not self.may_continue():
            return
        path = osp.dirname(str(self.filename)) if self.filename else "."
        formats = [
            f"*.{fmt.data().decode()}"
            for fmt in QtGui.QImageReader.supportedImageFormats()
        ]
        filters = self.tr("Image & Label files (%s)") % " ".join(
            formats + [f"*{LabelFile.suffix}"]
        )
        file_dialog = FileDialogPreview(self)
        file_dialog.setFileMode(QtWidgets.QFileDialog.FileMode.ExistingFile)
        file_dialog.setNameFilter(filters)
        file_dialog.setWindowTitle(
            self.tr("%s - Choose Image or Label file") % __appname__,
        )
        file_dialog.setWindowFilePath(path)
        file_dialog.setViewMode(QtWidgets.QFileDialog.ViewMode.Detail)
        if file_dialog.exec():
            filename = file_dialog.selectedFiles()[0]
            if filename:
                self.file_list_widget.clear()
                self.fn_to_index.clear()
                self.load_file(filename)

    def change_output_dir_dialog(self, _value=False):
        default_output_dir = self.output_dir
        if default_output_dir is None and self.filename:
            default_output_dir = osp.dirname(self.filename)
        if default_output_dir is None:
            default_output_dir = self.current_path()

        output_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            self.tr("%s - Save/Load Annotations in Directory") % __appname__,
            default_output_dir,
            QtWidgets.QFileDialog.Option.ShowDirsOnly
            | QtWidgets.QFileDialog.Option.DontResolveSymlinks,
        )
        output_dir = str(output_dir)

        if not output_dir:
            return

        if self._dataset_index_worker is not None:
            self._dataset_index_worker.cancel()
            self._dataset_index_worker.wait()

        if self._dataset_filter_index is not None:
            self._dataset_filter_index.close()
            self._dataset_filter_index = None

        self.output_dir = output_dir

        self.statusBar().showMessage(
            self.tr("%s . Annotations will be saved/loaded in %s")
            % ("Change Annotations Dir", self.output_dir)
        )
        self.statusBar().show()

        current_filename = self.filename
        self.import_image_folder(self.last_open_dir, load=False)

        if current_filename in self.image_list:
            # retain currently selected file
            self.file_list_widget.setCurrentRow(
                self.fn_to_index[str(current_filename)]
            )
            self.file_list_widget.repaint()

    def save_file(self, _value=False):
        assert not self.image.isNull(), "cannot save empty image"
        if self.label_file:
            # DL20180323 - overwrite when in directory
            self._save_file(self.label_file.filename)
        elif self.output_file:
            self._save_file(self.output_file)
            self.close()
        else:
            self._save_file(self.save_file_dialog())

    def save_file_as(self, _value=False):
        assert not self.image.isNull(), "cannot save empty image"
        self._save_file(self.save_file_dialog())

    def save_file_dialog(self):
        caption = self.tr("%s - Choose File") % __appname__
        filters = self.tr("Label files (*%s)") % LabelFile.suffix
        if self.output_dir:
            file_dialog = QtWidgets.QFileDialog(
                self, caption, self.output_dir, filters
            )
        else:
            file_dialog = QtWidgets.QFileDialog(
                self, caption, self.current_path(), filters
            )
        file_dialog.setDefaultSuffix(LabelFile.suffix[1:])
        file_dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptMode.AcceptSave)
        file_dialog.setOption(
            QtWidgets.QFileDialog.Option.DontConfirmOverwrite, False
        )
        file_dialog.setOption(
            QtWidgets.QFileDialog.Option.DontUseNativeDialog, False
        )
        basename = osp.basename(osp.splitext(self.filename)[0])
        if self.output_dir:
            default_labelfile_name = osp.join(
                self.output_dir, basename + LabelFile.suffix
            )
        else:
            default_labelfile_name = osp.join(
                self.current_path(), basename + LabelFile.suffix
            )
        filename = file_dialog.getSaveFileName(
            self,
            self.tr("Choose File"),
            default_labelfile_name,
            self.tr("Label files (*%s)") % LabelFile.suffix,
        )
        if isinstance(filename, tuple):
            filename, _ = filename
        return filename

    def _save_file(self, filename):
        if filename and self.save_labels(filename):
            self.add_recent_file(filename)
            self.set_clean()

    def close_file(self, _value=False):
        if not self.may_continue():
            return
        self.reset_state()
        self.set_clean()
        self.toggle_actions(False)
        self.canvas.setEnabled(False)
        self.actions.save_as.setEnabled(False)

    def toggle_compare_view(self):
        """Toggle the compare view on or off."""
        if self.compare_view_manager.is_active():
            self.close_compare_view()
            return

        if not self.filename:
            self.status(self.tr("Please open an image first"), 3000)
            return

        compare_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            self.tr("Select Compare Image Directory"),
            "",
            QtWidgets.QFileDialog.Option.ShowDirsOnly
            | QtWidgets.QFileDialog.Option.DontResolveSymlinks,
        )
        if not compare_dir:
            return

        if not self.compare_view_manager.set_compare_directory(compare_dir):
            self.status(self.tr("Invalid compare directory"), 3000)
            return

        self.compare_view_manager.load_compare_for_file(self.filename)
        self.compare_view_slider.show_slider()

    def close_compare_view(self, confirm=True):
        """Close the compare view."""
        if confirm:
            reply = QtWidgets.QMessageBox.question(
                self,
                self.tr("Close Compare View"),
                self.tr("Are you sure you want to close the compare view?"),
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if reply != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        self.compare_view_manager.close()
        self.compare_view_slider.hide_slider()

    def get_label_file(self):
        if self.label_file:
            return self.label_file.filename
        base = self.image_path if self.image_path else self.filename
        if base.lower().endswith(".json"):
            return base
        lf = osp.splitext(base)[0] + ".json"
        if self.output_dir:
            lf = osp.join(self.output_dir, osp.basename(lf))
        return lf

    def get_image_file(self):
        if not self.filename.lower().endswith(".json"):
            image_file = self.filename
        else:
            image_file = self.image_path

        return image_file

    def delete_file(self):
        mb = QtWidgets.QMessageBox
        if self._config.get("keep_prev", False):
            mb.warning(
                self,
                self.tr("Attention"),
                self.tr(
                    "Please disable 'Keep Previous Annotation' before deleting the label file."
                ),
                mb.StandardButton.Ok,
            )
            return

        msg = self.tr(
            "You are about to permanently delete this label file, "
            "proceed anyway?"
        )
        answer = mb.warning(
            self,
            self.tr("Attention"),
            msg,
            mb.StandardButton.Yes | mb.StandardButton.No,
        )
        if answer != mb.StandardButton.Yes:
            return

        label_file = self.get_label_file()
        if osp.exists(label_file):
            os.remove(label_file)
            logger.info(f"Label file is removed: {label_file}")

            item = self.file_list_widget.currentItem()
            item.setCheckState(Qt.CheckState.Unchecked)
            self._set_file_item_checked(item, False)

            filename = self.filename
            self.reset_state()
            self.filename = filename
            if self.filename:
                self.load_file(self.filename)

    def delete_image_file(self):
        if len(self.image_list) < 2:
            return

        mb = QtWidgets.QMessageBox
        if self._config.get("keep_prev", False):
            mb.warning(
                self,
                self.tr("Attention"),
                self.tr(
                    "Please disable 'Keep Previous Annotation' before deleting the image file."
                ),
                mb.StandardButton.Ok,
            )
            return

        msg = self.tr(
            "You are about to permanently delete this image file, "
            "proceed anyway?"
        )
        answer = mb.warning(
            self,
            self.tr("Attention"),
            msg,
            mb.StandardButton.Yes | mb.StandardButton.No,
        )
        if answer != mb.StandardButton.Yes:
            return

        image_file = self.get_image_file()
        if osp.exists(image_file):
            image_path, image_name = osp.split(image_file)
            save_path = osp.join(image_path, "..", "_delete_")
            os.makedirs(save_path, exist_ok=True)
            save_file = osp.join(save_path, image_name)
            shutil.move(image_file, save_file)
            logger.info(f"Image file is moved to: {osp.realpath(save_file)}")

            label_dir_path = osp.dirname(self.filename)
            if self.output_dir:
                label_dir_path = self.output_dir
            label_name = osp.splitext(image_name)[0] + ".json"
            label_file = osp.join(label_dir_path, label_name)
            if not osp.exists(label_file):
                label_file = osp.join(osp.dirname(image_file), label_name)
            if osp.exists(label_file):
                os.remove(label_file)
                logger.info(f"Label file is removed: {image_file}")

            filename = None
            if self.filename is None:
                filename = self.image_list[0]
            else:
                current_index = self.fn_to_index[str(self.filename)]
                if current_index + 1 < len(self.image_list):
                    filename = self.image_list[current_index + 1]
                else:
                    filename = self.image_list[0]

            self.reset_state()
            if osp.isfile(image_path):
                image_path = osp.dirname(image_path)
            self.import_image_folder(image_path)

            self.filename = filename
            if self.filename:
                self.load_file(self.filename)

    # Message Dialogs. #
    def has_labels(self):
        if self.no_shape():
            self.error_message(
                "No objects labeled",
                "You must label at least one object to save the file.",
            )
            return False
        return True

    def has_label_file(self):
        if self.filename is None:
            return False

        label_file = self.get_label_file()
        return osp.exists(label_file)

    def may_continue(self):
        if not self.dirty:
            return True
        mb = QtWidgets.QMessageBox
        msg = self.tr(
            f'Save annotations to "{self.filename!r}" before closing?'
        )
        answer = mb.question(
            self,
            self.tr("Save annotations?"),
            msg,
            mb.StandardButton.Save
            | mb.StandardButton.Discard
            | mb.StandardButton.Cancel,
            mb.StandardButton.Save,
        )
        if answer == mb.StandardButton.Discard:
            return True
        if answer == mb.StandardButton.Save:
            self.save_file()
            return True
        # answer == mb.Cancel
        return False

    def error_message(self, title, message):
        return QtWidgets.QMessageBox.critical(
            self, title, f"<p><b>{title}</b></p>{message}"
        )

    def current_path(self):
        return osp.dirname(str(self.filename)) if self.filename else "."

    def toggle_visibility_shapes(self, value):
        for index, item in enumerate(self.label_list):
            item.setCheckState(
                Qt.CheckState.Checked if value else Qt.CheckState.Unchecked
            )
            self.label_list[index].shape().visible = True if value else False
        self._config["show_shapes"] = value
        self._update_select_toggle_button_tooltip()
        if (
            hasattr(self, "navigator_dialog")
            and self.navigator_dialog.isVisible()
        ):
            self.update_navigator_shapes()

    def remove_selected_point(self):
        self.canvas.remove_selected_point()
        self.canvas.update()
        if self.canvas.h_hape is not None and not self.canvas.h_hape.points:
            self.canvas.delete_shape(self.canvas.h_hape)
            self.remove_labels([self.canvas.h_hape])
            self.set_dirty()
            if self.no_shape():
                for action in self.actions.on_shapes_present:
                    action.setEnabled(False)

    def delete_selected_shape(self):
        self.remove_labels(self.canvas.delete_selected())
        self.set_dirty()
        if self.no_shape():
            for action in self.actions.on_shapes_present:
                action.setEnabled(False)
        # Refresh keypoint fill mode after shape deletion
        if (
            hasattr(self, "keypoint_fill_mode")
            and self.keypoint_fill_mode.is_active
        ):
            self.keypoint_fill_mode.refresh()

    def copy_shape(self):
        self.canvas.end_move(copy=True)
        self.label_list.setUpdatesEnabled(False)
        try:
            for shape in self.canvas.selected_shapes:
                self.add_label(shape, refresh_filters=False)
        finally:
            self.label_list.setUpdatesEnabled(True)
        if self.canvas.selected_shapes:
            self._refresh_shape_filters()
        self.label_list.clearSelection()
        self.set_dirty()

    def move_shape(self):
        self.canvas.end_move(copy=False)
        self.set_dirty()

    def open_folder_dialog(self, _value=False, dirpath=None):
        if not self.may_continue():
            return

        default_open_dir_path = dirpath if dirpath else "."
        if self.last_open_dir and osp.exists(self.last_open_dir):
            default_open_dir_path = self.last_open_dir
        else:
            default_open_dir_path = (
                osp.dirname(self.filename) if self.filename else "."
            )

        target_dir_path = str(
            QtWidgets.QFileDialog.getExistingDirectory(
                self,
                self.tr("%s - Open Directory") % __appname__,
                default_open_dir_path,
                QtWidgets.QFileDialog.Option.ShowDirsOnly
                | QtWidgets.QFileDialog.Option.DontResolveSymlinks,
            )
        )
        self.import_image_folder(target_dir_path)

    @property
    def image_list(self):
        lst = []
        for i in range(self.file_list_widget.count()):
            item = self.file_list_widget.item(i)
            lst.append(item.text())
        return lst

    def import_dropped_image_files(self, image_files):
        extensions = [
            f".{fmt.data().decode().lower()}"
            for fmt in QtGui.QImageReader.supportedImageFormats()
        ]

        self.filename = None
        valid_files = []
        for file in image_files:
            if file in self.image_list or not file.lower().endswith(
                tuple(extensions)
            ):
                continue
            valid_files.append(file)
            label_file = osp.splitext(file)[0] + ".json"
            if self.output_dir:
                label_file_without_path = osp.basename(label_file)
                label_file = self.output_dir + "/" + label_file_without_path
            item = self._create_file_list_item(
                file, label_file, load_checked=False
            )
            self.file_list_widget.addItem(item)
            self.fn_to_index[file] = self.file_list_widget.count() - 1

        if len(self.image_list) > 1:
            self.actions.open_next_image.setEnabled(True)
            self.actions.open_prev_image.setEnabled(True)
            self.actions.open_next_unchecked_image.setEnabled(True)
            self.actions.open_prev_unchecked_image.setEnabled(True)

        self.toggle_actions(True)
        self.open_next_image()

    def import_image_folder(self, dirpath, pattern=None, load=True):
        _t0 = time.perf_counter()
        if not self.may_continue() or not dirpath:
            return

        if self.compare_view_manager.is_active():
            self.close_compare_view(confirm=False)

        # Cancel any previous background label check.
        if hasattr(self, "_label_check_worker") and self._label_check_worker:
            self._label_check_worker.cancel()
            self._label_check_worker.wait()
            self._label_check_worker = None

        self.last_open_dir = dirpath
        self.filename = None
        self.file_list_widget.clear()
        self.fn_to_index.clear()
        image_files = []

        search_pattern = parse_search_pattern(pattern) if pattern else None

        # Phase 1: scan paths only (no network IO for labels).
        for file_index, filename in enumerate(
            utils.scan_all_images(dirpath), start=1
        ):
            if search_pattern:
                if search_pattern.mode == "index":
                    if search_pattern.index != file_index:
                        continue
                else:
                    if not matches_filename(filename, search_pattern):
                        continue

                    # Attribute filtering is deferred to Phase 2 because
                    # it requires reading JSON content over the network.
                    if search_pattern.mode == "attribute":
                        pass

            image_files.append(filename)

        # Bulk atomic insert (avoids 38k individual addItem calls).
        self.file_list_widget.addItems(image_files)
        for i, path in enumerate(image_files):
            self.fn_to_index[path] = i

        # All items start as unchecked; labels are verified in background.
        for i in range(self.file_list_widget.count()):
            item = self.file_list_widget.item(i)
            item.setCheckState(Qt.CheckState.Unchecked)
            self._set_file_item_checked(item, False)

        self.actions.open_next_image.setEnabled(True)
        self.actions.open_prev_image.setEnabled(True)
        self.actions.open_next_unchecked_image.setEnabled(True)
        self.actions.open_prev_unchecked_image.setEnabled(True)
        self.toggle_actions(True)
        self.open_next_image(load=load)

        # NOTE: inspector file list sync is deferred to the background
        # label check worker to avoid blocking the UI with 38k network
        # IO calls (osp.isfile) on remote storage.

        # Cancel any pending dataset index timer from a previous directory.
        if self._dataset_index_timer is not None:
            self._dataset_index_timer.stop()
            self._dataset_index_timer = None

        _perf_log(
            "import_image_folder phase1: %d files in %.3fs",
            len(image_files),
            time.perf_counter() - _t0,
        )

        # Phase 2: background label check with progress dialog.
        self._start_label_check_worker(image_files)

    def _start_label_check_worker(self, image_files):
        """Launch modal progress dialog and background label checker."""
        if not image_files:
            return

        progress = QtWidgets.QProgressDialog(
            self.tr("Checking label files..."),
            self.tr("Cancel"),
            0,
            len(image_files),
            self,
        )
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(500)
        progress.setValue(0)
        progress.setWindowTitle(self.tr("Loading Labels"))

        self._label_check_worker = LabelCheckWorker(
            image_files,
            output_dir=self.output_dir,
            batch_size=500,
        )
        self._label_check_worker.progress.connect(progress.setValue)
        self._label_check_worker.batch_ready.connect(
            self._on_label_check_batch
        )
        self._label_check_worker.labels_found.connect(
            self._on_inspector_labels_found
        )
        self._label_check_worker.finished.connect(progress.close)
        self._label_check_worker.finished.connect(
            lambda: setattr(self, "_label_check_worker", None)
        )
        progress.canceled.connect(self._label_check_worker.cancel)
        self._label_check_worker.start()

    def _on_label_check_batch(self, batch):
        """Update check state for a batch of items."""
        for img_path, has_label in batch:
            if img_path not in self.fn_to_index:
                continue
            row = self.fn_to_index[img_path]
            item = self.file_list_widget.item(row)
            if item is None:
                continue
            if has_label:
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
            if self._config.get("file_list_checkbox_editable", False):
                self._set_file_item_checked(item, has_label)

    def _on_inspector_labels_found(self, label_paths):
        """Pass discovered label files to the inspector panel."""
        if (
            not hasattr(self, "inspector_panel")
            or self.inspector_panel is None
        ):
            return
        if label_paths:
            self.inspector_panel.set_file_list(label_paths)

    def toggle_auto_labeling_widget(self):
        """Toggle auto labeling widget visibility."""
        if self.auto_labeling_widget.isVisible():
            self.auto_labeling_widget.hide()
            self.actions.run_all_images.setEnabled(False)
        else:
            self.auto_labeling_widget.show()
            self.actions.run_all_images.setEnabled(True)
        self.update_thumbnail_display()

    @pyqtSlot()
    def new_shapes_from_auto_labeling(self, auto_labeling_result):
        """Apply auto labeling results to the current image."""
        if not self.image or not self.image_path:
            return

        result_image_path = getattr(auto_labeling_result, "image_path", None)
        if result_image_path and self.filename:
            current_filename = osp.normpath(osp.abspath(self.filename))
            result_filename = osp.normpath(osp.abspath(result_image_path))
            if result_filename != current_filename:
                logger.warning(
                    "Ignore stale auto labeling result for "
                    f"{result_filename}; current file is {current_filename}"
                )
                return

        # Clear existing shapes
        if auto_labeling_result.replace:
            self.load_shapes([], replace=True)
            self.label_list.clear()
            self.load_shapes(auto_labeling_result.shapes, replace=True)
        else:  # Just update existing shapes
            # Remove shapes with label AutoLabelingMode.OBJECT
            for shape in self.canvas.shapes:
                if shape.label == AutoLabelingMode.OBJECT:
                    item = self.label_list.find_item_by_shape(shape)
                    self.label_list.remove_item(item)
            self.load_shapes(auto_labeling_result.shapes, replace=False)

        # Set image description
        if auto_labeling_result.description:
            description = auto_labeling_result.description
            self.shape_text_label.setText(self.tr("Image Description"))
            self.shape_text_edit.textChanged.disconnect()
            self.shape_text_edit.setPlainText(description)
            self.shape_text_edit.textChanged.connect(self.shape_text_changed)
            self.other_data["description"] = description
            self.shape_text_edit.setDisabled(False)

        self.set_dirty()

    def clear_auto_labeling_marks(self):
        """Clear auto labeling marks from the current image."""
        # Clean up label list
        for shape in self.canvas.shapes:
            if shape.label in [
                AutoLabelingMode.OBJECT,
                AutoLabelingMode.ADD,
                AutoLabelingMode.REMOVE,
            ]:
                try:
                    item = self.label_list.find_item_by_shape(shape)
                    self.label_list.remove_item(item)
                except ValueError:
                    pass

        # Clean up unique label list
        for shape_label in [
            AutoLabelingMode.OBJECT,
            AutoLabelingMode.ADD,
            AutoLabelingMode.REMOVE,
        ]:
            for item in self.unique_label_list.find_items_by_label(
                shape_label
            ):
                self.unique_label_list.takeItem(
                    self.unique_label_list.row(item)
                )

        # Remove shapes from the canvas
        self.canvas.shapes = [
            shape
            for shape in self.canvas.shapes
            if shape.label
            not in [
                AutoLabelingMode.OBJECT,
                AutoLabelingMode.ADD,
                AutoLabelingMode.REMOVE,
            ]
        ]
        self.canvas.update()

    def find_last_label(self):
        """
        Find the last label in the label list.
        Exclude labels for auto labeling.
        """

        # Get from dialog history
        last_label = self.label_dialog.get_last_label()
        if last_label:
            return last_label

        # Get selected label from the label list
        items = self.label_list.selected_items()
        if items:
            shape = items[0].data(Qt.ItemDataRole.UserRole)
            return shape.label

        # Get the last label from the label list
        for item in reversed(self.label_list):
            shape = item.data(Qt.ItemDataRole.UserRole)
            if shape.label not in [
                AutoLabelingMode.OBJECT,
                AutoLabelingMode.ADD,
                AutoLabelingMode.REMOVE,
            ]:
                return shape.label

        # No label is found
        return ""

    def find_last_gid(self):
        last_gid = self.label_dialog.get_last_gid()
        if last_gid is not None:
            return last_gid

        for item in reversed(self.label_list):
            shape = item.data(Qt.ItemDataRole.UserRole)
            if (
                shape.label
                not in [
                    AutoLabelingMode.OBJECT,
                    AutoLabelingMode.ADD,
                    AutoLabelingMode.REMOVE,
                ]
                and shape.group_id is not None
            ):
                return shape.group_id
        return None

    def set_cache_auto_label(self):
        self.auto_labeling_widget.on_cache_auto_label_changed(
            self.cache_auto_label, self.cache_auto_label_group_id
        )

    def finish_auto_labeling_object(self):
        """Finish auto labeling object."""
        has_object, cache_label = False, None
        for shape in self.canvas.shapes:
            if shape.label == AutoLabelingMode.OBJECT:
                cache_label = shape.cache_label
                cache_description = shape.cache_description
                has_object = True
                break

        # If there is no object, do nothing
        if not has_object:
            return

        # Ask a label for the object
        text, flags, group_id, description, difficult, kie_linking = (
            "",
            {},
            None,
            None,
            False,
            [],
        )
        last_label = self.find_last_label()
        last_gid = (
            self.find_last_gid() if self._config["auto_use_last_gid"] else None
        )
        if self._config["auto_use_last_label"] and last_label:
            text = last_label
            if last_gid is not None:
                group_id = last_gid
        elif cache_label is not None:
            text = cache_label
            description = cache_description
        else:
            previous_text = self.label_dialog.edit.text()
            (
                text,
                flags,
                group_id,
                description,
                difficult,
                kie_linking,
            ) = self.label_dialog.pop_up(
                text=self.find_last_label(),
                flags={},
                group_id=last_gid,
                description=None,
                difficult=False,
                kie_linking=[],
                move_mode=self._config.get("move_mode", "auto"),
            )
            if not text:
                self.label_dialog.edit.setText(previous_text)
                return

        self.cache_auto_label = text
        self.cache_auto_label_group_id = group_id
        if not self.validate_label(text):
            self.error_message(
                self.tr("Invalid label"),
                self.tr("Invalid label '{}' with validation type '{}'").format(
                    text, self._config["validate_label"]
                ),
            )
            return

        if self.attributes and text:
            text = self.reset_attribute(text, shape)

        # Add to label history
        self.label_dialog.add_label_history(text)

        # Update label for the object
        updated_shapes = False
        for shape in self.canvas.shapes:
            if shape.label == AutoLabelingMode.OBJECT:
                updated_shapes = True
                shape.label = text
                shape.flags = flags
                shape.group_id = group_id
                shape.description = description
                shape.difficult = difficult
                shape.kie_linking = kie_linking
                # Update unique label list
                if not self.unique_label_list.find_items_by_label(shape.label):
                    unique_label_item = (
                        self.unique_label_list.create_item_from_label(
                            shape.label
                        )
                    )
                    self.unique_label_list.addItem(unique_label_item)
                    rgb = self._get_rgb_by_label(shape.label)
                    self.unique_label_list.set_item_label(
                        unique_label_item, shape.label, rgb, LABEL_OPACITY
                    )

                # Update label list
                self._update_shape_color(shape)
                item = self.label_list.find_item_by_shape(shape)
                if shape.group_id is None:
                    color = shape.fill_color.getRgb()[:3]
                    item.setText(
                        '{} <font color="#{:02x}{:02x}{:02x}">●</font>'.format(
                            html.escape(shape.label), *color
                        )
                    )
                else:
                    item.setText(f"{shape.label} ({shape.group_id})")

        # Clean up auto labeling objects
        self.clear_auto_labeling_marks()

        # Update shape colors
        for shape in self.canvas.shapes:
            self._update_shape_color(shape)
            color = shape.fill_color.getRgb()[:3]
            item = self.label_list.find_item_by_shape(shape)
            item.setText("{}".format(html.escape(shape.label)))
            item.setBackground(QtGui.QColor(*color, LABEL_OPACITY))
            self.unique_label_list.update_item_color(
                shape.label, color, LABEL_OPACITY
            )

        if updated_shapes:
            self.set_dirty()

    def shape_text_changed(self):
        description = self.shape_text_edit.toPlainText()
        if self.canvas.current is not None:
            self.canvas.current.description = description
        elif self.canvas.editing() and len(self.canvas.selected_shapes) == 1:
            self.canvas.selected_shapes[0].description = description
        else:
            self.other_data["description"] = description
        self.set_dirty()

    def set_text_editing(self, enable):
        """Set text editing."""
        if enable:
            # Enable text editing and set shape text from selected shape
            if len(self.canvas.selected_shapes) == 1:
                self.shape_text_label.setText(self.tr("Object Description"))
                self.shape_text_edit.textChanged.disconnect()
                self.shape_text_edit.setPlainText(
                    self.canvas.selected_shapes[0].description or ""
                )
                self.shape_text_edit.textChanged.connect(
                    self.shape_text_changed
                )
            else:
                self.shape_text_label.setText(self.tr("Image Description"))
                self.shape_text_edit.textChanged.disconnect()
                self.shape_text_edit.setPlainText(
                    self.other_data.get("description", "")
                )
                self.shape_text_edit.textChanged.connect(
                    self.shape_text_changed
                )
            self.shape_text_edit.setDisabled(False)
        else:
            self.shape_text_edit.setDisabled(True)
            self.shape_text_label.setText(self.tr("Description"))
            self.shape_text_edit.textChanged.disconnect()
            self.shape_text_edit.setPlainText("")
            self.shape_text_edit.textChanged.connect(self.shape_text_changed)

    def group_selected_shapes(self):
        self.canvas.group_selected_shapes()
        self.set_dirty()
        self.load_file(self.filename)

    def ungroup_selected_shapes(self):
        self.canvas.ungroup_selected_shapes()
        self.set_dirty()
        self.load_file(self.filename)

    def update_thumbnail_pixmap(self):
        if self.thumbnail_pixmap and not self.thumbnail_pixmap.isNull():
            width = self.thumbnail_image_label.width()
            if width > 0:
                self.thumbnail_image_label.setPixmap(
                    self.thumbnail_pixmap.scaledToWidth(
                        width,
                        QtCore.Qt.TransformationMode.SmoothTransformation,
                    )
                )

    def update_thumbnail_display(self):
        _t_thumbnail = time.perf_counter()
        self.thumbnail_pixmap = None
        self.thumbnail_image_label.clear()
        self.thumbnail_container.hide()

        model_config = (
            self.auto_labeling_widget.model_manager.loaded_model_config
        )
        supported_model_list = list(_THUMBNAIL_RENDER_MODELS.keys())
        if not (
            model_config
            and model_config.get("type") in supported_model_list
            and self.image_list
        ):
            return

        try:
            image_dir = osp.dirname(self.filename)
            parent_dir = osp.dirname(image_dir)
            base_name = osp.splitext(osp.basename(self.filename))[0]
            save_dir, _thumbnail_file_ext = _THUMBNAIL_RENDER_MODELS[
                model_config["type"]
            ]
            thumbnail_dir = osp.join(parent_dir, save_dir)
            thumbnail_path = osp.join(
                thumbnail_dir, base_name + _thumbnail_file_ext
            )
            if not osp.exists(thumbnail_path):
                return

            self.thumbnail_pixmap = QtGui.QPixmap(thumbnail_path)
            if not self.thumbnail_pixmap.isNull():
                self.thumbnail_container.show()
                self.update_thumbnail_pixmap()
            _perf_log(
                "update_thumbnail_display: %.3fs, %s",
                time.perf_counter() - _t_thumbnail,
                self.filename,
            )

        except Exception as e:
            logger.error(f"Failed to load thumbnail image: {str(e)}")

    def toggle_description_visibility(self, checked):
        self.description_dock.setVisible(checked)

    def toggle_labels_visibility(self, checked):
        self.label_dock.setVisible(checked)

    def toggle_shapes_visibility(self, checked):
        self.shape_dock.setVisible(checked)

    def _set_label_display_mode(self, mode):
        self._config["label_display_mode"] = mode
        self.canvas.label_display_mode = mode
        for key, btn in self._display_mode_buttons.items():
            btn.setChecked(key == mode)
        self.canvas.update()

    def _toggle_display_score(self, checked):
        self._config["show_scores"] = checked
        self.canvas.show_scores = checked
        self.canvas.update()
