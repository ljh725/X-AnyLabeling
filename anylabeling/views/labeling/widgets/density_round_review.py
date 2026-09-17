"""Dual-window editor for density-balanced rectangle review rounds."""

from __future__ import annotations

import copy
import os.path as osp
from typing import Iterable

from PyQt6 import QtCore, QtGui, QtWidgets

from ..density_round_review import (
    RectangleSnapshot,
    RoundReviewSession,
    rectangle_snapshots,
)
from ..shape import Shape
from .canvas import Canvas


def _shape_id(shape: Shape) -> str:
    """Return one shape's persistent identity."""
    return str(getattr(shape, "xanylabeling_shape_id", "") or "")


def _copy_shape_data(source: Shape, target: Shape) -> None:
    """Copy annotation data while preserving target-only UI state."""
    selected = target.selected
    hovered = target.hovered
    visible = target.visible
    loaded = source.copy()
    for name, value in loaded.__dict__.items():
        if name in {"selected", "hovered", "visible"}:
            continue
        setattr(target, name, value)
    target.selected = selected
    target.hovered = hovered
    target.visible = visible


class DensityReviewCanvas(Canvas):
    """Canvas projection that draws and edits only the active review round."""

    projection_changed = QtCore.pyqtSignal(object)
    transaction_started = QtCore.pyqtSignal(tuple)
    transaction_finished = QtCore.pyqtSignal(tuple, bool)
    all_preview_changed = QtCore.pyqtSignal(bool)

    def __init__(self, *args, **kwargs) -> None:
        """Initialize a rectangle-only review canvas."""
        preview_shortcut = kwargs.pop("preview_shortcut", "V")
        super().__init__(*args, **kwargs)
        self._round_members: set[str] = set()
        self._all_preview = False
        self._boundary = None
        self._transaction_ids: tuple[str, ...] = ()
        self._transaction_before: dict[
            str, tuple[tuple[float, float], ...]
        ] = {}
        self._can_edit = lambda _shape_id: True
        self._preview_sequence = QtGui.QKeySequence(preview_shortcut)
        self.label_on_selection = True
        self.set_editing(True)
        self.set_inspection_visibility(
            self._render_allowed,
            self._interaction_allowed,
            ignore_base_visibility=True,
        )
        self.shape_changed.connect(self.projection_changed)

    def set_can_edit(self, callback) -> None:
        """Install the coordinator's object-lock predicate."""
        self._can_edit = callback

    def set_round(self, members: Iterable[str], boundary) -> None:
        """Activate one frozen member set and boundary."""
        self._round_members = {str(value) for value in members}
        self._boundary = boundary
        self.deselect_shape()
        self.update()

    def set_all_preview(self, enabled: bool) -> None:
        """Temporarily draw all projections without enabling interaction."""
        enabled = bool(enabled)
        if self._all_preview == enabled:
            return
        self._all_preview = enabled
        self.all_preview_changed.emit(enabled)
        self.update()

    def _render_allowed(self, shape: Shape) -> bool:
        """Return whether a projection enters the paint pass."""
        return self._all_preview or _shape_id(shape) in self._round_members

    def _interaction_allowed(self, shape: Shape) -> bool:
        """Return whether a projection can be hit or edited."""
        shape_id = _shape_id(shape)
        return shape_id in self._round_members and bool(
            self._can_edit(shape_id)
        )

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        """Start one projected edit transaction after normal hit testing."""
        super().mousePressEvent(event)
        if (
            event.button() == QtCore.Qt.MouseButton.LeftButton
            and self.editing()
            and self.selected_shapes
        ):
            self._transaction_ids = tuple(
                _shape_id(shape) for shape in self.selected_shapes
            )
            self._transaction_before = {
                _shape_id(shape): tuple(
                    (point.x(), point.y()) for point in shape.points
                )
                for shape in self.selected_shapes
            }
            self.transaction_started.emit(self._transaction_ids)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        """Publish live projection geometry after the Canvas moves it."""
        before = {
            _shape_id(shape): tuple(
                (point.x(), point.y()) for point in shape.points
            )
            for shape in self.selected_shapes
        }
        super().mouseMoveEvent(event)
        for shape in self.selected_shapes:
            points = tuple((point.x(), point.y()) for point in shape.points)
            if before.get(_shape_id(shape)) != points:
                self.projection_changed.emit(shape)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        """Finish a projected edit transaction and release its lock."""
        super().mouseReleaseEvent(event)
        changed = False
        for shape in self.selected_shapes:
            points = tuple((point.x(), point.y()) for point in shape.points)
            if self._transaction_before.get(_shape_id(shape)) != points:
                changed = True
            self.projection_changed.emit(shape)
        if self._transaction_ids:
            self.transaction_finished.emit(self._transaction_ids, changed)
            self._transaction_ids = ()
            self._transaction_before = {}

    def _matches_preview_shortcut(self, event: QtGui.QKeyEvent) -> bool:
        """Return whether a key event matches the configured hold shortcut."""
        combination = QtCore.QKeyCombination(
            event.modifiers(), QtCore.Qt.Key(event.key())
        )
        return (
            QtGui.QKeySequence(combination).matches(self._preview_sequence)
            == QtGui.QKeySequence.SequenceMatch.ExactMatch
        )

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        """Handle the hold-to-preview key before normal canvas shortcuts."""
        if self._matches_preview_shortcut(event) and not event.isAutoRepeat():
            self.set_all_preview(True)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QtGui.QKeyEvent) -> None:
        """Restore the active round when the preview key is released."""
        if self._matches_preview_shortcut(event) and not event.isAutoRepeat():
            self.set_all_preview(False)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        """Paint normal content followed by the frozen dashed boundary."""
        super().paintEvent(event)
        if self.pixmap is None or self._boundary is None:
            return
        painter = QtGui.QPainter(self)
        pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 220), 1.5)
        pen.setStyle(QtCore.Qt.PenStyle.DashLine)
        painter.setPen(pen)
        offset = self.offset_to_center()
        scale = float(self.scale)
        if self._boundary.axis == "x":
            for coordinate in (self._boundary.start, self._boundary.end):
                x_pos = (coordinate + offset.x()) * scale
                painter.drawLine(
                    QtCore.QPointF(x_pos, offset.y() * scale),
                    QtCore.QPointF(
                        x_pos,
                        (offset.y() + self.pixmap.height()) * scale,
                    ),
                )
        else:
            for coordinate in (self._boundary.start, self._boundary.end):
                y_pos = (coordinate + offset.y()) * scale
                painter.drawLine(
                    QtCore.QPointF(offset.x() * scale, y_pos),
                    QtCore.QPointF(
                        (offset.x() + self.pixmap.width()) * scale,
                        y_pos,
                    ),
                )
        painter.end()


class DensityRoundReviewWindow(QtWidgets.QWidget):
    """Top-level focused editor for one density review round."""

    previous_requested = QtCore.pyqtSignal()
    next_requested = QtCore.pyqtSignal()
    round_requested = QtCore.pyqtSignal(int)
    limit_changed = QtCore.pyqtSignal(int)
    create_requested = QtCore.pyqtSignal()
    duplicate_requested = QtCore.pyqtSignal()
    delete_requested = QtCore.pyqtSignal()
    relabel_requested = QtCore.pyqtSignal()
    undo_requested = QtCore.pyqtSignal()
    redo_requested = QtCore.pyqtSignal()
    digit_requested = QtCore.pyqtSignal(int)
    toggle_requested = QtCore.pyqtSignal()
    closing = QtCore.pyqtSignal()

    def __init__(
        self,
        canvas: DensityReviewCanvas,
        shortcuts: dict[str, object] | None = None,
    ) -> None:
        """Build the compact review bar and large canvas."""
        super().__init__(None, QtCore.Qt.WindowType.Window)
        self.setWindowTitle(self.tr("Density Round Review"))
        self.canvas = canvas
        self._shortcut_config = shortcuts or {}
        self._updating_round = False
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        bar = QtWidgets.QHBoxLayout()
        self.file_label = QtWidgets.QLabel(self.tr("No image"))
        self.last_label = QtWidgets.QLabel("")
        self.previous_button = QtWidgets.QPushButton(self.tr("Previous"))
        self.next_button = QtWidgets.QPushButton(self.tr("Next"))
        self.round_spin = QtWidgets.QSpinBox()
        self.round_spin.setMinimum(1)
        self.round_total = QtWidgets.QLabel("/ 1")
        self.count_label = QtWidgets.QLabel(self.tr("0 instances"))
        self.limit_spin = QtWidgets.QSpinBox()
        self.limit_spin.setRange(1, 1000)
        self.limit_state = QtWidgets.QLabel("")
        self.create_button = QtWidgets.QPushButton(self.tr("New rectangle"))
        self.relabel_button = QtWidgets.QPushButton(self.tr("Edit label"))
        self.duplicate_button = QtWidgets.QPushButton(self.tr("Duplicate"))
        self.delete_button = QtWidgets.QPushButton(self.tr("Delete"))
        self.close_button = QtWidgets.QPushButton(self.tr("Close"))
        for widget in (
            self.file_label,
            self.last_label,
            self.previous_button,
            self.next_button,
            QtWidgets.QLabel(self.tr("Round")),
            self.round_spin,
            self.round_total,
            self.count_label,
            QtWidgets.QLabel(self.tr("Limit")),
            self.limit_spin,
            self.limit_state,
            self.create_button,
            self.relabel_button,
            self.duplicate_button,
            self.delete_button,
            self.close_button,
        ):
            bar.addWidget(widget)
        bar.addStretch(1)
        layout.addLayout(bar)
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_area.setWidget(canvas)
        self.scroll_area.setWidgetResizable(True)
        layout.addWidget(self.scroll_area, 1)
        self.resize(1100, 760)
        self._connect_controls()
        self._create_shortcuts()

    def _connect_controls(self) -> None:
        """Connect compact bar controls to public request signals."""
        self.previous_button.clicked.connect(self.previous_requested)
        self.next_button.clicked.connect(self.next_requested)
        self.round_spin.valueChanged.connect(self._emit_round)
        self.limit_spin.valueChanged.connect(self.limit_changed)
        self.create_button.clicked.connect(self.create_requested)
        self.relabel_button.clicked.connect(self.relabel_requested)
        self.duplicate_button.clicked.connect(self.duplicate_requested)
        self.delete_button.clicked.connect(self.delete_requested)
        self.close_button.clicked.connect(self.toggle_requested)

    def _create_shortcuts(self) -> None:
        """Install review-local default shortcuts."""
        shortcuts = (
            (
                self._shortcut_config.get("density_review_previous", "["),
                self.previous_requested,
            ),
            (
                self._shortcut_config.get("density_review_next", "]"),
                self.next_requested,
            ),
            ("R", self.create_requested),
            ("Ctrl+E", self.relabel_requested),
            ("Ctrl+D", self.duplicate_requested),
            ("Delete", self.delete_requested),
            ("Ctrl+Z", self.undo_requested),
            ("Ctrl+Shift+Z", self.redo_requested),
        )
        self._shortcuts = []
        for key, signal in shortcuts:
            if not key:
                continue
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(key), self)
            shortcut.activated.connect(
                lambda target=signal: self._activate_shortcut(target)
            )
            self._shortcuts.append(shortcut)
        toggle = QtGui.QShortcut(
            QtGui.QKeySequence(
                self._shortcut_config.get("toggle_density_round_review", "F10")
            ),
            self,
        )
        toggle.activated.connect(self.toggle_requested)
        self._shortcuts.append(toggle)
        for digit in range(10):
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(str(digit)), self)
            shortcut.activated.connect(
                lambda value=digit: self._activate_digit_shortcut(value)
            )
            self._shortcuts.append(shortcut)

    def _shortcut_focus_blocked(self) -> bool:
        """Return whether a compact-bar editor owns the keyboard focus."""
        return isinstance(
            QtWidgets.QApplication.focusWidget(),
            (
                QtWidgets.QLineEdit,
                QtWidgets.QAbstractSpinBox,
                QtWidgets.QComboBox,
            ),
        )

    def _activate_shortcut(self, signal: QtCore.pyqtBoundSignal) -> None:
        """Ignore editing shortcuts while a compact-bar editor has focus."""
        if self._shortcut_focus_blocked():
            return
        signal.emit()

    def _activate_digit_shortcut(self, digit: int) -> None:
        """Emit one guarded digit rename request."""
        if self._shortcut_focus_blocked():
            return
        self.digit_requested.emit(digit)

    def _emit_round(self, value: int) -> None:
        """Emit a zero-based round request unless UI is being refreshed."""
        if not self._updating_round:
            self.round_requested.emit(value - 1)

    def update_state(
        self,
        filename: str | None,
        current_round: int,
        round_count: int,
        instance_count: int,
        applied_limit: int,
        pending_limit: int,
        last_filename: str = "",
    ) -> None:
        """Refresh all informational controls without causing navigation."""
        self.file_label.setText(
            osp.basename(filename) if filename else self.tr("No image")
        )
        self.last_label.setText(
            self.tr("Last closed: %s") % last_filename if last_filename else ""
        )
        self._updating_round = True
        self.round_spin.setRange(1, max(1, round_count))
        self.round_spin.setValue(current_round + 1)
        self.round_total.setText(f"/ {max(1, round_count)}")
        self._updating_round = False
        self.count_label.setText(self.tr("%d instances") % instance_count)
        self.limit_spin.blockSignals(True)
        self.limit_spin.setValue(pending_limit)
        self.limit_spin.blockSignals(False)
        self.limit_state.setText(
            self.tr("Current %d · Next %d") % (applied_limit, pending_limit)
        )

    def fit_image(self) -> None:
        """Fit the current image into the independent review viewport."""
        pixmap = self.canvas.pixmap
        if pixmap is None or pixmap.isNull():
            return
        viewport = self.scroll_area.viewport().size()
        if viewport.width() < 1 or viewport.height() < 1:
            return
        self.canvas.scale = min(
            viewport.width() / pixmap.width(),
            viewport.height() / pixmap.height(),
        )
        self.canvas.adjustSize()
        self.canvas.update()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Notify the coordinator before the top-level window closes."""
        self.closing.emit()
        super().closeEvent(event)


class DensityRoundReviewCoordinator(QtCore.QObject):
    """Coordinate the authoritative main document and review projection."""

    _DISPLAY_ATTRIBUTES = (
        "show_groups",
        "show_texts",
        "show_labels",
        "show_rectangle_pixels",
        "show_scores",
        "show_degrees",
        "show_attributes",
        "show_linking",
        "label_display_mode",
        "label_zoom_threshold",
    )

    def __init__(self, host) -> None:
        """Initialize an inactive review session for one LabelingWidget."""
        super().__init__(host)
        self.host = host
        config = host._config.get("density_round_review", {})
        default_limit = int(config.get("instances_per_round", 10))
        self.session = RoundReviewSession(default_limit)
        self.window: DensityRoundReviewWindow | None = None
        self.active = False
        self._syncing_selection = False
        self._syncing_shape = False
        self._pending_main_ids: tuple[str, ...] = ()
        self._locks: dict[str, str] = {}
        self._review_map: dict[str, Shape] = {}
        self._redo_stack: list[list[Shape]] = []
        self._undo_capture: list[Shape] | None = None
        self._history_navigation = False
        self._main_label_on_selection = None
        self._saved_isolation = False
        host.canvas.shape_changed.connect(self._on_main_shape_changed)
        host.canvas.shapes_changed.connect(self._on_main_shapes_changed)
        host.canvas.selection_changed.connect(self._on_main_selection_changed)
        host.canvas.shape_edit_started.connect(self._on_main_edit_started)
        host.canvas.shape_edit_finished.connect(self._on_main_edit_finished)

    def _make_canvas(self) -> DensityReviewCanvas:
        """Create a review Canvas with the host's compatible options."""
        config = self.host._config
        canvas_config = config["canvas"]
        canvas = DensityReviewCanvas(
            epsilon=canvas_config["epsilon"],
            double_click=canvas_config["double_click"],
            num_backups=canvas_config["num_backups"],
            wheel_rectangle_editing=canvas_config["wheel_rectangle_editing"],
            auto_highlight_shape=config.get("auto_highlight_shape", False),
            attributes=canvas_config.get("attributes", {}),
            rotation=canvas_config.get("rotation", {}),
            mask=canvas_config.get("mask", {}),
            brush=canvas_config.get("brush", {}),
            cuboid=canvas_config.get("cuboid", {}),
            double_click_edit_label=canvas_config.get(
                "double_click_edit_label", True
            ),
            preview_shortcut=config.get("shortcuts", {}).get(
                "density_review_preview_all", "V"
            ),
        )
        canvas.set_appearance_settings(self.host.appearance_settings)
        canvas.set_appearance_label_colors(self.host.appearance_label_colors)
        canvas.show_masks = False
        canvas.create_mode = "rectangle"
        canvas.set_can_edit(
            lambda shape_id: self._can_edit(shape_id, "review")
        )
        return canvas

    def _ensure_window(self) -> DensityRoundReviewWindow:
        """Create and connect the top-level review window once."""
        if self.window is not None:
            return self.window
        window = DensityRoundReviewWindow(
            self._make_canvas(), self.host._config.get("shortcuts", {})
        )
        window.previous_requested.connect(self.previous_round)
        window.next_requested.connect(self.next_round)
        window.round_requested.connect(self.select_round)
        window.limit_changed.connect(self.set_pending_limit)
        window.create_requested.connect(self.start_rectangle)
        window.delete_requested.connect(self.delete_selected)
        window.duplicate_requested.connect(self.duplicate_selected)
        window.relabel_requested.connect(self.relabel_selected)
        window.undo_requested.connect(self.undo)
        window.redo_requested.connect(self.redo)
        window.digit_requested.connect(self.rename_selected_with_digit)
        window.toggle_requested.connect(self.disable)
        window.closing.connect(self.disable)
        window.canvas.selection_changed.connect(
            self._on_review_selection_changed
        )
        window.canvas.projection_changed.connect(self._on_review_shape_changed)
        window.canvas.transaction_started.connect(self._on_review_edit_started)
        window.canvas.transaction_finished.connect(
            self._on_review_edit_finished
        )
        window.canvas.new_shape.connect(self._on_review_new_shape)
        window.canvas.edit_label_requested.connect(self.relabel_selected)
        self.window = window
        return window

    def toggle(self) -> None:
        """Toggle the density review mode and its second window."""
        if self.active:
            self.disable()
        else:
            self.enable()

    def enable(self) -> None:
        """Start a fresh review session for the current main image."""
        if self.active:
            if self.window is not None:
                self.window.raise_()
                self.window.activateWindow()
            return
        virtual = getattr(self.host, "virtual_review_controller", None)
        if virtual is not None and virtual.active:
            virtual.stop()
        self.active = True
        self._saved_isolation = self.host.canvas.isolation_enabled
        if self._saved_isolation:
            self.host.canvas.set_isolation_enabled(False)
        self._main_label_on_selection = self.host.canvas.label_on_selection
        self.host.canvas.label_on_selection = True
        self.host.canvas.set_inspection_visibility(
            interaction_predicate=lambda shape: self._can_edit(
                _shape_id(shape), "main"
            ),
            ignore_base_visibility=True,
        )
        window = self._ensure_window()
        self._restore_geometry(window)
        window.show()
        self.on_image_loaded(force=True)

    def disable(self) -> None:
        """End review mode, persist layout, and restore main Canvas state."""
        if not self.active:
            return
        self.active = False
        self._locks.clear()
        self._pending_main_ids = ()
        settings = self.host.settings
        if self.window is not None:
            settings.setValue(
                "density_round_review/geometry", self.window.saveGeometry()
            )
        if self.host.filename:
            settings.setValue(
                "density_round_review/last_filename",
                osp.basename(str(self.host.filename)),
            )
        self.host.canvas.clear_inspection_visibility()
        if self._main_label_on_selection is not None:
            self.host.canvas.label_on_selection = self._main_label_on_selection
        if self._saved_isolation and self.host.canvas.selected_shapes:
            self.host.canvas.set_isolation_enabled(True)
        if self.window is not None and self.window.isVisible():
            self.window.blockSignals(True)
            self.window.hide()
            self.window.blockSignals(False)
        self.host.canvas.update()

    def _restore_geometry(self, window: DensityRoundReviewWindow) -> None:
        """Restore saved geometry when it intersects an available screen."""
        geometry = self.host.settings.value("density_round_review/geometry")
        if geometry:
            window.restoreGeometry(geometry)
        frame = window.frameGeometry()
        if not any(
            screen.availableGeometry().intersects(frame)
            for screen in QtGui.QGuiApplication.screens()
        ):
            screen = (
                self.host.screen() or QtGui.QGuiApplication.primaryScreen()
            )
            if screen is not None:
                frame.moveCenter(screen.availableGeometry().center())
                window.move(frame.topLeft())

    def on_image_loaded(self, force: bool = False) -> None:
        """Load or refresh the projection after main image loading."""
        if not self.active or self.window is None:
            return
        filename = str(self.host.filename or "")
        pixmap = self.host.canvas.pixmap
        image_size = (
            (pixmap.width(), pixmap.height()) if pixmap is not None else (0, 0)
        )
        is_new_image = force or filename != self.session.image_key
        if is_new_image:
            self.session.load_image(
                filename,
                image_size,
                rectangle_snapshots(self.host.canvas.shapes),
            )
            review_config = self.host._config.setdefault(
                "density_round_review", {}
            )
            review_config["instances_per_round"] = self.session.applied_limit
        self._rebuild_projection()
        if pixmap is not None:
            self.window.canvas.load_pixmap(pixmap, clear_shapes=False)
        self.sync_display_from_main()
        self._activate_round(clear_main=False)
        if is_new_image:
            QtCore.QTimer.singleShot(0, self.window.fit_image)

    def sync_display_from_main(self) -> None:
        """Mirror main information display while permanently suppressing masks."""
        if not self.active or self.window is None:
            return
        source = self.host.canvas
        target = self.window.canvas
        for name in self._DISPLAY_ATTRIBUTES:
            if hasattr(source, name):
                setattr(target, name, getattr(source, name))
        target.set_appearance_settings(self.host.appearance_settings)
        target.set_appearance_label_colors(self.host.appearance_label_colors)
        target.set_appearance_image_token(str(self.host.filename or ""))
        target.show_masks = False
        target.label_on_selection = True
        target.update()

    def _rebuild_projection(self) -> None:
        """Recreate review copies from current authoritative rectangles."""
        if self.window is None:
            return
        selected_ids = {
            _shape_id(shape) for shape in self.window.canvas.selected_shapes
        }
        clones = []
        self._review_map = {}
        for source in self.host.canvas.shapes:
            if source.shape_type != "rectangle":
                continue
            clone = source.copy()
            clone.selected = False
            clone.hovered = False
            clone.visible = True
            clone.hidden_by_filter = False
            clones.append(clone)
            self._review_map[_shape_id(clone)] = clone
        self.window.canvas.load_shapes(
            clones, replace=True, store_backup=False
        )
        restored = [
            self._review_map[shape_id]
            for shape_id in selected_ids
            if shape_id in self._review_map
        ]
        if restored:
            self.window.canvas.select_shapes(restored, source="coordinator")

    def _main_map(self) -> dict[str, Shape]:
        """Return current authoritative shapes keyed by persistent identity."""
        return {
            _shape_id(shape): shape
            for shape in self.host.canvas.shapes
            if _shape_id(shape)
        }

    def _activate_round(self, clear_main: bool = True) -> None:
        """Publish current round visibility, boundary, selection, and UI."""
        if self.window is None:
            return
        self._syncing_selection = True
        try:
            self.window.canvas.deselect_shape()
            if clear_main:
                self.host.canvas.deselect_shape()
        finally:
            self._syncing_selection = False
        self.window.canvas.set_round(
            self.session.current_members,
            self.session.current_boundary,
        )
        last_filename = str(
            self.host.settings.value("density_round_review/last_filename", "")
            or ""
        )
        self.window.update_state(
            self.host.filename,
            self.session.current_round,
            self.session.round_count,
            len(self.session.current_members),
            self.session.applied_limit,
            self.session.pending_limit,
            last_filename,
        )

    def set_pending_limit(self, limit: int) -> None:
        """Stage a round limit for the next different image."""
        self.session.set_pending_limit(limit)
        self._activate_round(clear_main=False)

    def select_round(self, index: int) -> None:
        """Jump directly to one frozen round without moving the viewport."""
        if self._editing_active():
            self._status(self.tr("Finish the current edit first"))
            return
        if self.session.select_round(index):
            self._activate_round()

    def previous_round(self) -> None:
        """Move to the previous round or previous image's final round."""
        if self._editing_active():
            self._status(self.tr("Finish the current edit first"))
            return
        if self.session.current_round > 0:
            self.session.select_round(self.session.current_round - 1)
            self._activate_round()
            return
        if not self.host.may_continue():
            self._status(
                self.tr(
                    "Image change cancelled because annotations were not saved"
                )
            )
            return
        old = self.host.filename
        self.host.open_prev_image()
        if self.host.filename == old:
            self._status(self.tr("Already at the first image"))
            return
        if self.active:
            self.session.select_round(self.session.round_count - 1)
            self._activate_round()

    def next_round(self) -> None:
        """Move to the next round or next image's first round."""
        if self._editing_active():
            self._status(self.tr("Finish the current edit first"))
            return
        if self.session.current_round + 1 < self.session.round_count:
            self.session.select_round(self.session.current_round + 1)
            self._activate_round()
            return
        if not self.host.may_continue():
            self._status(
                self.tr(
                    "Image change cancelled because annotations were not saved"
                )
            )
            return
        old = self.host.filename
        self.host.open_next_image()
        if self.host.filename == old:
            self._status(self.tr("Already at the last image"))

    def sync_main_selection(self) -> None:
        """Confirm and send one same-round main selection to review."""
        if not self.active or self.window is None:
            return
        selected = [
            shape
            for shape in self.host.canvas.selected_shapes
            if shape.shape_type == "rectangle"
        ]
        ids = tuple(_shape_id(shape) for shape in selected)
        rounds = {self.session.round_for(shape_id) for shape_id in ids}
        if not ids or None in rounds:
            self._status(self.tr("Select review rectangles first"))
            return
        if len(rounds) != 1:
            self._status(
                self.tr("Selected objects belong to different rounds")
            )
            return
        self.session.select_round(rounds.pop())
        self._activate_round(clear_main=False)
        projections = [self._review_map[shape_id] for shape_id in ids]
        self._syncing_selection = True
        try:
            self.window.canvas.select_shapes(projections, source="main_sync")
        finally:
            self._syncing_selection = False
        self._pending_main_ids = ()

    def _on_review_selection_changed(self, shapes: list[Shape]) -> None:
        """Immediately mirror review selection into the main Canvas."""
        if self._syncing_selection or not self.active:
            return
        main_map = self._main_map()
        selected = [
            main_map[_shape_id(shape)]
            for shape in shapes
            if _shape_id(shape) in main_map
        ]
        self._syncing_selection = True
        try:
            self.host.canvas.select_shapes(selected, source="density_review")
        finally:
            self._syncing_selection = False
        self._pending_main_ids = ()

    def _on_main_selection_changed(self, shapes: list[Shape]) -> None:
        """Record main selection as pending until explicit confirmation."""
        if self._syncing_selection or not self.active:
            return
        self._pending_main_ids = tuple(_shape_id(shape) for shape in shapes)
        if self._pending_main_ids:
            self._status(
                self.tr("Pending review-window selection: %d")
                % len(self._pending_main_ids)
            )

    def _on_review_edit_started(self, shape_ids: tuple[str, ...]) -> None:
        """Acquire review ownership and ensure a main undo baseline."""
        if any(
            not self._acquire(shape_id, "review") for shape_id in shape_ids
        ):
            return
        if not self.host.canvas.shapes_backups or getattr(
            self.host.canvas, "_pending_initial_backup", False
        ):
            self.host.canvas.store_shapes()

    def _on_review_shape_changed(self, projection: Shape) -> None:
        """Copy one live projected mutation into the authoritative Shape."""
        if self._syncing_shape or not self.active:
            return
        source = self._main_map().get(_shape_id(projection))
        if source is None:
            return
        self._syncing_shape = True
        try:
            _copy_shape_data(projection, source)
            self.host._update_shape_color(source)
            self.host.canvas.notify_shape_changed(source)
            self.host.canvas.update()
        finally:
            self._syncing_shape = False

    def _on_review_edit_finished(
        self, shape_ids: tuple[str, ...], changed: bool
    ) -> None:
        """Commit one shared undo step and release review locks."""
        if changed:
            self._redo_stack.clear()
            self.host.canvas.store_shapes()
            self.host.set_dirty()
        for shape_id in shape_ids:
            self._release(shape_id, "review")

    def _on_main_shape_changed(self, source: Shape) -> None:
        """Refresh one review projection after an authoritative edit."""
        if self._syncing_shape or not self.active:
            return
        projection = self._review_map.get(_shape_id(source))
        if projection is None:
            return
        self._syncing_shape = True
        try:
            _copy_shape_data(source, projection)
            projection.selected = (
                projection in self.window.canvas.selected_shapes
            )
            self.window.canvas.update()
        finally:
            self._syncing_shape = False

    def _on_main_shapes_changed(self, _shapes: tuple[Shape, ...]) -> None:
        """Reconcile membership and rebuild projections after list changes."""
        if not self.active or self.window is None or self._syncing_shape:
            return
        if not self._history_navigation:
            self._redo_stack.clear()
        snapshots = rectangle_snapshots(self.host.canvas.shapes)
        current_ids = {snapshot.shape_id for snapshot in snapshots}
        known_ids = {
            shape_id
            for members in self.session.partition.rounds
            for shape_id in members
        }
        for shape_id in known_ids - current_ids:
            self.session.remove(shape_id)
        for snapshot in snapshots:
            if snapshot.shape_id not in known_ids:
                self.session.add_by_position(snapshot)
        self._rebuild_projection()
        self._activate_round(clear_main=False)

    def _on_main_edit_started(self, _kind: str) -> None:
        """Acquire locks for the main Canvas's active edit targets."""
        candidates = list(self.host.canvas.selected_shapes)
        if self.host.canvas.h_hape is not None:
            candidates.append(self.host.canvas.h_hape)
        for shape in candidates:
            self._acquire(_shape_id(shape), "main")

    def _on_main_edit_finished(self, _kind: str, _changed: bool) -> None:
        """Release every main-owned object lock after an edit."""
        if _changed:
            self._redo_stack.clear()
        for shape_id, owner in tuple(self._locks.items()):
            if owner == "main":
                self._release(shape_id, owner)

    def _can_edit(self, shape_id: str, owner: str) -> bool:
        """Return whether ``owner`` may edit a shape under current locks."""
        lock_owner = self._locks.get(shape_id)
        return lock_owner in (None, owner)

    def _acquire(self, shape_id: str, owner: str) -> bool:
        """Acquire one object lock when available."""
        if not shape_id or not self._can_edit(shape_id, owner):
            return False
        self._locks[shape_id] = owner
        return True

    def _release(self, shape_id: str, owner: str) -> None:
        """Release one lock only when owned by the caller."""
        if self._locks.get(shape_id) == owner:
            self._locks.pop(shape_id, None)

    def _editing_active(self) -> bool:
        """Return whether either Canvas has an unfinished edit transaction."""
        review = self.window.canvas if self.window is not None else None
        return bool(
            self._locks
            or getattr(self.host.canvas, "moving_shape", False)
            or getattr(self.host.canvas, "rect_edge_dragging", False)
            or (review is not None and getattr(review, "moving_shape", False))
            or (
                review is not None
                and getattr(review, "rect_edge_dragging", False)
            )
        )

    def start_rectangle(self) -> None:
        """Enter rectangle creation mode in the focused review Canvas."""
        if self.window is None or self._editing_active():
            return
        self.window.canvas.create_mode = "rectangle"
        self.window.canvas.set_editing(False)
        self.window.canvas.setFocus()

    def _on_review_new_shape(self) -> None:
        """Label and commit a newly drawn review rectangle to the main document."""
        if self.window is None or not self.window.canvas.shapes:
            return
        projection = self.window.canvas.shapes[-1]
        result = self.host.label_dialog.pop_up(
            text=projection.label,
            flags=projection.flags,
            group_id=projection.group_id,
            description=projection.description,
            difficult=projection.difficult,
            kie_linking=projection.kie_linking,
            move_mode=self.host._config.get("move_mode", "auto"),
        )
        text, flags, group_id, description, difficult, kie_linking = result
        if text is None or not self.host.validate_label(text):
            self.window.canvas.delete_shape(projection)
            self.window.canvas.set_editing(True)
            return
        projection.label = text
        projection.flags = flags
        projection.group_id = group_id
        projection.description = description
        projection.difficult = difficult
        projection.kie_linking = kie_linking
        source = projection.copy()
        source.selected = False
        self.host._update_shape_color(source)
        self.session.add_to_current(_shape_id(source))
        self._redo_stack.clear()
        self.host.load_shapes([source], replace=False)
        self.host.set_dirty()
        self.window.canvas.set_editing(True)
        self._rebuild_projection()
        self._activate_round(clear_main=False)

    def delete_selected(self) -> None:
        """Delete review-selected authoritative rectangles."""
        if self.window is None:
            return
        ids = {
            _shape_id(shape) for shape in self.window.canvas.selected_shapes
        }
        sources = [
            shape
            for shape in self.host.canvas.shapes
            if _shape_id(shape) in ids
        ]
        if not sources or any(
            not self._acquire(_shape_id(shape), "review") for shape in sources
        ):
            return
        self._redo_stack.clear()
        self._syncing_selection = True
        try:
            self.host.canvas.select_shapes(sources, source="density_review")
            self.host.delete_selected_shape()
        finally:
            self._syncing_selection = False
            for shape in sources:
                self._release(_shape_id(shape), "review")

    def duplicate_selected(self) -> None:
        """Duplicate review-selected rectangles into the current round."""
        if self.window is None:
            return
        main_map = self._main_map()
        copies = []
        for projection in self.window.canvas.selected_shapes:
            source = main_map.get(_shape_id(projection))
            if source is None:
                continue
            duplicate = source.copy_for_new_object()
            duplicate.move_by(QtCore.QPointF(5.0, 5.0))
            duplicate.selected = False
            self.session.add_to_current(_shape_id(duplicate))
            copies.append(duplicate)
        if copies:
            self._redo_stack.clear()
            self.host.load_shapes(copies, replace=False)
            self.host.set_dirty()

    def relabel_selected(self) -> None:
        """Route review relabeling through the host's shared label dialog."""
        if self.window is None:
            return
        ids = {
            _shape_id(shape) for shape in self.window.canvas.selected_shapes
        }
        sources = [
            shape
            for shape in self.host.canvas.shapes
            if _shape_id(shape) in ids
        ]
        if not sources:
            return
        self._syncing_selection = True
        try:
            self._redo_stack.clear()
            self.host.canvas.select_shapes(sources, source="density_review")
            self.host.edit_label()
        finally:
            self._syncing_selection = False
        for source in sources:
            self._on_main_shape_changed(source)

    def rename_selected_with_digit(self, digit: int) -> bool:
        """Apply an existing digit rename mapping to review selections."""
        if self.window is None or self._editing_active():
            return False
        ids = {
            _shape_id(shape) for shape in self.window.canvas.selected_shapes
        }
        sources = [
            shape
            for shape in self.host.canvas.shapes
            if _shape_id(shape) in ids
        ]
        if not sources:
            return False
        self._syncing_selection = True
        try:
            self.host.canvas.select_shapes(sources, source="density_review")
        finally:
            self._syncing_selection = False
        acquired = []
        for source in sources:
            shape_id = _shape_id(source)
            if not self._acquire(shape_id, "review"):
                for acquired_id in acquired:
                    self._release(acquired_id, "review")
                return False
            acquired.append(shape_id)
        before = tuple(source.label for source in sources)
        try:
            self.host.digit_rename_manager.trigger_rename(int(digit))
        finally:
            for shape_id in acquired:
                self._release(shape_id, "review")
        changed = before != tuple(source.label for source in sources)
        if not changed:
            return False
        self._redo_stack.clear()
        self.host.canvas.store_shapes()
        for source in sources:
            self._on_main_shape_changed(source)
        return True

    def undo(self) -> None:
        """Delegate undo to the authoritative main Canvas and refresh."""
        self.host.undo_shape_edit()

    def redo(self) -> None:
        """Restore the last shared undo snapshot into the main document."""
        if not self.active or not self._redo_stack:
            self._status(self.tr("Nothing to redo"))
            return
        shapes = self._redo_stack.pop()
        self._history_navigation = True
        try:
            self.host.label_list.clear()
            self.host.load_shapes(
                [shape.copy() for shape in shapes],
                replace=True,
                update_last_label=False,
            )
        finally:
            self._history_navigation = False
        self.host.set_dirty()

    def before_shared_undo(self) -> None:
        """Capture the current document before the host consumes undo state."""
        self._undo_capture = None
        if self.active and self.host.canvas.is_shape_restorable:
            self._history_navigation = True
            self._undo_capture = [
                shape.copy() for shape in self.host.canvas.shapes
            ]

    def after_shared_undo(self, restored: bool) -> None:
        """Publish one redo entry after a successful host-owned undo."""
        if restored and self._undo_capture is not None:
            self._redo_stack.append(self._undo_capture)
        self._undo_capture = None
        self._history_navigation = False

    def _status(self, message: str) -> None:
        """Publish one visible host status message."""
        self.host.status(message, 5000)


__all__ = [
    "DensityReviewCanvas",
    "DensityRoundReviewCoordinator",
    "DensityRoundReviewWindow",
]
