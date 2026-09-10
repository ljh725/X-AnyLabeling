"""Opt-in rectangle creation, refinement and observation workbench."""

from __future__ import annotations

from typing import Any

from PyQt6 import QtCore, QtGui, QtWidgets

from .. import rect_edge_alignment as rea
from ..review_refinement.extreme import EDGES, ExtremeDraft, observation_view
from ..shape import Shape
from .viewport_state_machine import ViewportState


class RectangleWorkflow(QtWidgets.QWidget):
    """Coordinate rectangle commands through existing canvas transactions."""

    def __init__(self, owner: Any) -> None:
        """Build visible commands without changing default drawing behavior."""
        super().__init__(owner)
        self.owner = owner
        self.canvas = owner.canvas
        self.draft: ExtremeDraft | None = None
        self.pointer: QtCore.QPointF | None = None
        self.refining = False
        self._changing_tool = False
        self._committing = False
        self._saved_flags: tuple[bool, bool] | None = None
        self._view_snapshot: tuple[str, ViewportState] | None = None
        self._target_id: str | None = None
        self._last_label: str | None = None
        self._release_pending = False
        config = owner._config.get("rectangle_workflow", {})
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        self.enabled_box = QtWidgets.QCheckBox(self.tr("Rectangle workbench"))
        layout.addWidget(self.enabled_box)
        self.controls = QtWidgets.QWidget()
        rows = QtWidgets.QVBoxLayout(self.controls)
        rows.setContentsMargins(0, 0, 0, 0)
        main = QtWidgets.QHBoxLayout()
        rows.addLayout(main)
        self.commands: dict[str, QtGui.QAction] = {}
        self._button(
            main,
            "rectangle_extreme",
            self.tr("Four extremes"),
            self.start_extreme,
        )
        self._button(
            main,
            "rectangle_submit",
            self.tr("Submit draft"),
            self.submit_draft,
        )
        self._button(
            main, "rectangle_back", self.tr("Back one boundary"), self.back
        )
        self._button(
            main,
            "rectangle_refine",
            self.tr("Refine rectangle"),
            self.start_refinement,
        )
        self._button(
            main,
            "rectangle_continue",
            self.tr("Continue drawing"),
            self.continue_drawing,
        )
        self._button(
            main,
            "rectangle_local_focus",
            self.tr("Local focus"),
            self.local_focus,
        )
        self._button(
            main,
            "rectangle_fit_object",
            self.tr("Fit object"),
            self.fit_object,
        )
        main.addStretch()
        edges = QtWidgets.QHBoxLayout()
        rows.addLayout(edges)
        self.edge_buttons: dict[str, QtWidgets.QPushButton] = {}
        for edge, title in zip(EDGES, ("Top", "Right", "Bottom", "Left")):
            button = QtWidgets.QPushButton(self.tr(title))
            button.setCheckable(True)
            button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            button.clicked.connect(
                lambda _checked=False, name=edge: self.select_edge(name)
            )
            edges.addWidget(button)
            self.edge_buttons[edge] = button
        self._button(
            edges,
            "rectangle_finish",
            self.tr("Finish refinement"),
            self.finish,
        )
        self._button(
            edges, "rectangle_next", self.tr("Next object"), self.next_object
        )
        self.auto_zoom = QtWidgets.QCheckBox(self.tr("Fit object on entry"))
        self.auto_zoom.setChecked(bool(config.get("auto_zoom", False)))
        self.auto_zoom.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.auto_zoom.toggled.connect(self._save_preferences)
        edges.addWidget(self.auto_zoom)
        self._button(
            edges,
            "rectangle_surroundings",
            self.tr("View surroundings"),
            self.restore_view,
        )
        self.message = QtWidgets.QLabel()
        self.message.setWordWrap(True)
        rows.addWidget(self.message)
        layout.addWidget(self.controls)
        self.enabled_box.toggled.connect(self._set_enabled)
        self.enabled_box.setChecked(bool(config.get("enabled", False)))
        self._set_enabled(self.enabled_box.isChecked())
        self.canvas.rectangle_workflow = self
        self.canvas.rectangle_workflow_refining = False
        self.canvas.installEventFilter(self)
        self.canvas.selection_changed.connect(self.selection_changed)
        self.canvas.rectangle_review_feedback_changed.connect(self.feedback)
        self.canvas.shape_moved.connect(self.refresh)
        self.refresh()

    def _button(
        self, row: QtWidgets.QHBoxLayout, key: str, title: str, callback: Any
    ) -> None:
        """Add a visible command with an optional canvas-scoped shortcut."""
        action = QtGui.QAction(title, self.canvas)
        shortcut = self.owner._config.get("shortcuts", {}).get(key)
        if shortcut:
            action.setShortcut(shortcut)
        action.setShortcutContext(QtCore.Qt.ShortcutContext.WidgetShortcut)
        action.triggered.connect(lambda _checked=False: callback())
        self.canvas.addAction(action)
        self.commands[key] = action
        setattr(self.owner.actions, key, action)
        button = QtWidgets.QToolButton()
        button.setDefaultAction(action)
        button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        row.addWidget(button)

    def apply_preferences(self) -> None:
        """Apply settings-dialog values without signal-driven config loss."""
        config = self.owner._config.get("rectangle_workflow", {})
        enabled, auto_zoom = (
            bool(config.get("enabled", False)),
            bool(config.get("auto_zoom", False)),
        )
        with QtCore.QSignalBlocker(self.enabled_box):
            self.enabled_box.setChecked(enabled)
        with QtCore.QSignalBlocker(self.auto_zoom):
            self.auto_zoom.setChecked(auto_zoom)
        self._set_enabled(enabled)

    def _save_preferences(self, _checked: bool = False) -> None:
        """Update normal application config without writing annotation data."""
        self.owner._config.setdefault("rectangle_workflow", {}).update(
            enabled=self.enabled_box.isChecked(),
            auto_zoom=self.auto_zoom.isChecked(),
        )

    def _set_enabled(self, enabled: bool) -> None:
        """Show optional controls and end transient work when disabled."""
        if not enabled:
            self.reset(restore=True)
        self.controls.setVisible(enabled)
        self._save_preferences()
        self.refresh()

    def selected(self) -> Shape | None:
        """Return the unique, visible and valid ordinary rectangle."""
        shapes = self.canvas.selected_shapes
        if len(shapes) != 1:
            return None
        return self._valid_rectangle(shapes[0])

    def _valid_rectangle(self, shape: Shape) -> Shape | None:
        """Return an editable rectangle, excluding invalid source geometry."""
        if shape.shape_type != "rectangle" or shape not in self.canvas.shapes:
            return None
        if not self.canvas.is_shape_interactive(shape):
            return None
        geometry = rea.geometry_from_shape(shape)
        pixmap = self.canvas.pixmap
        if geometry is None or pixmap is None:
            return None
        if not (
            0 <= geometry.x_min < geometry.x_max <= pixmap.width() - 1
            and 0 <= geometry.y_min < geometry.y_max <= pixmap.height() - 1
            and geometry.width >= 1
            and geometry.height >= 1
        ):
            return None
        return shape

    def refresh(self, *_args: Any) -> None:
        """Enable commands according to the current explicit workflow state."""
        enabled = self.enabled_box.isChecked()
        loaded = self.canvas.pixmap is not None
        selected = self.selected() is not None
        for action in self.commands.values():
            action.setEnabled(enabled and loaded)
        self.commands["rectangle_refine"].setEnabled(
            enabled and selected and self.draft is None
        )
        self.commands["rectangle_fit_object"].setEnabled(
            enabled and selected and self.draft is None
        )
        self.commands["rectangle_submit"].setEnabled(
            enabled and self.draft is not None and self.draft.complete
        )
        self.commands["rectangle_back"].setEnabled(
            enabled and self.draft is not None and bool(self.draft.points)
        )
        self.commands["rectangle_finish"].setEnabled(enabled and self.refining)
        self.commands["rectangle_next"].setEnabled(
            enabled and selected and self.draft is None
        )
        self.commands["rectangle_surroundings"].setEnabled(
            enabled and self._view_snapshot is not None
        )
        for button in self.edge_buttons.values():
            button.setEnabled(enabled and selected and self.draft is None)
        if self.draft is not None:
            if self.draft.complete:
                self.message.setText(
                    self.tr("Draft ready: submit or go back.")
                )
            else:
                names = (
                    self.tr("Top"),
                    self.tr("Right"),
                    self.tr("Bottom"),
                    self.tr("Left"),
                )
                self.message.setText(
                    self.tr("Click boundary {step}/4: {edge}").format(
                        step=len(self.draft.points) + 1,
                        edge=names[len(self.draft.points)],
                    )
                )
        elif not self.refining:
            self.message.setText(
                self.tr(
                    "Choose a drawing tool or select one rectangle to refine."
                )
            )

        if (
            self.draft is None
            and len(self.canvas.selected_shapes) == 1
            and self.canvas.selected_shapes[0].shape_type == "rectangle"
            and not selected
        ):
            self.message.setText(
                self.tr(
                    "Invalid rectangle: redraw it with the rectangle tool."
                )
            )

    def _toggle_tool(self, edit: bool) -> None:
        """Use existing mode and telemetry transitions without self-canceling."""
        self._changing_tool = True
        try:
            self.owner.toggle_draw_mode(edit=edit, create_mode="rectangle")
        finally:
            self._changing_tool = False

    def before_tool_change(self, edit: bool, create_mode: str) -> None:
        """Cancel drafts on external tool changes, retaining digit prefill."""
        if self._changing_tool or self._committing:
            return
        if (
            self.draft is not None
            and not edit
            and create_mode == "rectangle"
            and self.owner.digit_to_label is not None
        ):
            return
        self.reset(restore=True)

    def start_extreme(self) -> None:
        """Start an isolated four-boundary draft on the current image."""
        if self.canvas.pixmap is None:
            return
        self.reset(restore=False)
        self._toggle_tool(False)
        self.canvas.current = None
        self.canvas.line.points = []
        self.draft = ExtremeDraft(
            self.canvas.pixmap.width(), self.canvas.pixmap.height()
        )
        self.canvas.drawing_polygon.emit(True)
        self.canvas.setFocus()
        self.refresh()
        self.canvas.update()

    def continue_drawing(self) -> None:
        """Start another draft using the last successfully committed label."""
        if self._last_label:
            self.owner.digit_to_label = self._last_label
        self.start_extreme()

    def back(self) -> None:
        """Undo one draft boundary without touching annotation history."""
        if self.draft is not None:
            self.draft.back()
            self.refresh()
            self.canvas.update()
        self.canvas.setFocus()

    def submit_draft(self) -> None:
        """Commit through the existing rectangle and label transaction."""
        if self.draft is None or not self.draft.complete or self._committing:
            return
        left, top, right, bottom = self.draft.bbox()
        shape = Shape(shape_type="rectangle")
        shape.points = [
            QtCore.QPointF(left, top),
            QtCore.QPointF(right, top),
            QtCore.QPointF(right, bottom),
            QtCore.QPointF(left, bottom),
        ]
        backups = list(self.canvas.shapes_backups)
        pending = getattr(self.canvas, "_pending_initial_backup", False)
        # An empty image also needs a baseline for undoing its first creation.
        if not self.canvas.shapes_backups:
            self.canvas.store_shapes()
        self._committing = True
        try:
            self.canvas.current = shape
            self.canvas.finalise()
        finally:
            self._committing = False
        if shape not in self.canvas.shapes or not shape.label:
            if shape in self.canvas.shapes:
                self.canvas.shapes.remove(shape)
            self.canvas.current = None
            self.canvas.shapes_backups = backups
            self.canvas._pending_initial_backup = pending
            self.canvas.notify_shapes_changed()
            self.canvas.drawing_polygon.emit(True)
            self.refresh()
            self.canvas.update()
            return
        self._last_label = shape.label
        # Include final description/attributes in the creation snapshot.
        self.canvas.shapes_backups.pop()
        self.canvas.store_shapes()
        self.draft = None
        self.canvas.drawing_polygon.emit(False)
        self._toggle_tool(True)
        self.canvas.select_shapes([shape])
        self.start_refinement(observe=False)
        self.canvas.setFocus()
        self.refresh()

    def start_refinement(self, observe: bool = True) -> None:
        """Enter a bounded session for the selected valid rectangle."""
        shape = self.selected()
        if shape is None:
            return
        self._toggle_tool(True)
        if self._saved_flags is None:
            self._saved_flags = (
                self.canvas.rectangle_review_refinement_enabled,
                self.canvas.rect_edge_align_enabled,
            )
        self.refining = True
        self.canvas.rectangle_workflow_refining = True
        self.canvas.rectangle_review_refinement_enabled = True
        self.canvas.set_rect_edge_align_enabled(True)
        self._target_id = shape.xanylabeling_shape_id
        self.message.setText(
            self.tr(
                "Click a boundary point to adjust. "
                "Use buttons or Tab for 1px/5px nudges."
            )
        )
        if observe and self.auto_zoom.isChecked():
            self.fit_object()
        self.canvas.setFocus()
        self.refresh()

    def select_edge(self, edge: str) -> None:
        """Activate one explicit boundary and return focus to the canvas."""
        if not self.refining:
            self.start_refinement()
        shape = self.selected()
        if shape is None:
            return
        self.canvas.cancel_rect_edge_drag()
        self.canvas.clear_rect_edge_alignment()
        geometry = rea.geometry_from_shape(shape)
        self.canvas._activate_rect_edge_for_nudge(
            rea.edge_from_geometry(shape, geometry, edge)
        )
        self.canvas.setFocus()
        self.canvas.update()

    def feedback(self, snapshot: Any) -> None:
        """Display feedback outside the object's visible boundary."""
        active_edge = self.canvas.rect_edge_active_edge
        for name, button in self.edge_buttons.items():
            button.setChecked(
                snapshot is not None
                and active_edge is not None
                and active_edge.edge_name == name
            )
        if not self.refining or snapshot is None:
            return
        names = dict(
            zip(
                EDGES,
                (
                    self.tr("Top"),
                    self.tr("Right"),
                    self.tr("Bottom"),
                    self.tr("Left"),
                ),
            )
        )
        active = self.canvas.rect_edge_active_edge
        if active is None:
            return
        original = snapshot.original_coord
        direction = self.tr("right") if active.axis == "x" else self.tr("down")
        text = self.tr(
            "{edge}: delta {delta:+.1f}px | 1px / Shift 5px | Wheel up: {direction}"
        ).format(
            edge=names[active.edge_name],
            delta=active.coord - original,
            direction=direction,
        )
        if snapshot.phase == "rejected":
            text = (
                self.tr("Rejected: image bounds or minimum size.") + " " + text
            )
        self.message.setText(text)

    def selection_changed(self, _shapes: Any) -> None:
        """Retarget a running workflow without carrying transient edge state."""
        if self._committing or self._changing_tool or not self.refining:
            self.refresh()
            return
        shape = self.selected()
        identity = shape.xanylabeling_shape_id if shape is not None else None
        if identity != self._target_id:
            self.canvas.cancel_rect_edge_drag()
            self.canvas.clear_rect_edge_alignment()
            self._target_id = identity
            self._view_snapshot = None
        self.refresh()

    def finish(self) -> None:
        """End refinement, preserving committed edits and selected object."""
        self.canvas.cancel_rect_edge_drag()
        self.canvas.clear_rect_edge_alignment()
        self.refining = False
        self.canvas.rectangle_workflow_refining = False
        if self._saved_flags is not None:
            enabled, align = self._saved_flags
            self.canvas.rectangle_review_refinement_enabled = enabled
            self.canvas.set_rect_edge_align_enabled(align)
            self._saved_flags = None
        self._target_id = None
        self.refresh()
        self.canvas.setFocus()

    def reset(self, restore: bool = False) -> None:
        """Discard only transient work during reset or tool changes."""
        if restore:
            self.restore_view()
        if self.draft is not None:
            self.canvas.current = None
            self.canvas.line.points = []
            self.canvas.drawing_polygon.emit(False)
        self.draft = None
        self.pointer = None
        self._view_snapshot = None
        self._release_pending = False
        self.finish()

    def undo_state(self) -> tuple[str | None, str | None]:
        """Remember an explicitly selected target for a normal undo."""
        edge = self.canvas.rect_edge_active_edge
        return self._target_id, edge.edge_name if edge is not None else None

    def restore_after_undo(self, state: tuple[str | None, str | None]) -> None:
        """Rebind to restored shape identity without restoring stale geometry."""
        identity, edge_name = state
        if not self.refining or identity is None:
            return
        for shape in self.canvas.shapes:
            if shape.xanylabeling_shape_id == identity:
                self.canvas.select_shapes([shape])
                if edge_name and self.selected() is not None:
                    self.select_edge(edge_name)
                return
        self.finish()

    def next_object(self) -> None:
        """Advance through visible rectangles using existing file navigation."""
        current = self.selected()
        if current is None:
            return
        shapes = [
            s
            for s in self.canvas.shapes
            if self._valid_rectangle(s) is not None
        ]
        index = shapes.index(current)
        if index + 1 < len(shapes):
            self.finish()
            self._view_snapshot = None
            self.canvas.select_shapes([shapes[index + 1]])
            self.start_refinement()
            return
        if not self._navigate_file():
            return
        self._view_snapshot = None
        for shape in self.canvas.shapes:
            if self._valid_rectangle(shape) is not None:
                self.canvas.select_shapes([shape])
                if self.selected() is not None:
                    self.start_refinement()
                    return
        self.refresh()

    def _navigate_file(self) -> bool:
        """Restore the current in-memory document if next-file loading fails."""
        fields = (
            "filename",
            "image_path",
            "image_data",
            "label_file",
            "other_data",
            "image",
        )
        document = {name: getattr(self.owner, name) for name in fields}
        pixmap = self.canvas.pixmap
        shapes = list(self.canvas.shapes)
        backups = list(self.canvas.shapes_backups)
        dirty = self.owner.dirty
        target = self._target_id
        state = self.owner.viewport_controller.capture(
            self.canvas, self.owner.zoom_widget, self.owner.zoom_mode
        )
        self.owner.open_next_image()
        if self.canvas.pixmap is not None and not self.canvas.pixmap.isNull():
            return self.owner.filename != document["filename"]
        for name, value in document.items():
            setattr(self.owner, name, value)
        self.canvas.load_pixmap(pixmap)
        self.owner.load_shapes(shapes, replace=True, store_backup=False)
        self.canvas.shapes_backups = backups
        self.canvas.setEnabled(True)
        self.owner.toggle_actions(True)
        self.owner._sync_file_list_current_row(document["filename"])
        if dirty:
            self.owner.set_dirty()
        else:
            self.owner.set_clean()
        if state is not None:
            self.owner.viewport_controller.apply(
                state, self.canvas, self.owner.zoom_widget
            )
            self.owner._sync_viewport_ui(state)
        for shape in shapes:
            if shape.xanylabeling_shape_id == target:
                self.canvas.select_shapes([shape])
                self.start_refinement(observe=False)
                break
        self.message.setText(
            self.tr("Navigation failed; current edits restored.")
        )
        return False

    def _capture_view(self) -> None:
        """Remember one view snapshot tied to its source file."""
        filename = self.owner.filename
        if self._view_snapshot is None and filename:
            state = self.owner.viewport_controller.capture(
                self.canvas, self.owner.zoom_widget, self.owner.zoom_mode
            )
            if state is not None:
                self._view_snapshot = (filename, state)

    def fit_object(self) -> None:
        """Fit a selected object with context through the viewport controller."""
        shape = self.selected()
        if shape is None:
            return
        self._capture_view()
        geometry = rea.geometry_from_shape(shape)
        viewport = self.owner._central_widget.viewport()
        config = self.owner._config.get("rectangle_workflow", {})
        zoom, x, y = observation_view(
            (geometry.x_min, geometry.y_min, geometry.x_max, geometry.y_max),
            (self.canvas.pixmap.width(), self.canvas.pixmap.height()),
            (viewport.width(), viewport.height()),
            float(config.get("target_pixels", 400)),
            float(config.get("max_scale", 8)),
        )
        state = ViewportState(self.owner.MANUAL_ZOOM, zoom, x, y)
        result = self.owner.viewport_controller.apply(
            state, self.canvas, self.owner.zoom_widget
        )
        if result.success:
            self.owner._sync_viewport_ui(state)
        self.refresh()

    def local_focus(self) -> None:
        """Magnify the last canvas pointer while preserving its screen anchor."""
        if self.canvas.pixmap is None:
            return
        self._capture_view()
        pos = self.pointer
        if pos is None:
            pos = self.canvas.transform_pos(
                QtCore.QPointF(self.canvas.mapFromGlobal(QtGui.QCursor.pos()))
            )
        screen = (pos + self.canvas.offset_to_center()) * self.canvas.scale
        self.owner._zoom_around_canvas_pos(
            screen, lambda: self.owner.add_zoom(2.0)
        )
        self.canvas.setFocus()
        self.refresh()

    def restore_view(self) -> None:
        """Restore only a snapshot belonging to the current image."""
        if self._view_snapshot is None:
            return
        filename, state = self._view_snapshot
        if filename == self.owner.filename:
            result = self.owner.viewport_controller.apply(
                state, self.canvas, self.owner.zoom_widget
            )
            if result.success:
                self.owner._sync_viewport_ui(state)
        self._view_snapshot = None
        self.refresh()

    def eventFilter(
        self, watched: QtCore.QObject, event: QtCore.QEvent
    ) -> bool:
        """Route draft and refinement keys only when the canvas owns focus."""
        if watched is not self.canvas or not self.enabled_box.isChecked():
            return False
        kind = event.type()
        if kind == QtCore.QEvent.Type.MouseMove:
            self.pointer = self.canvas.transform_pos(event.position())
            if self.draft is not None:
                self.canvas.update()
                return True
        if self.draft is not None and kind in (
            QtCore.QEvent.Type.MouseButtonPress,
            QtCore.QEvent.Type.MouseButtonDblClick,
        ):
            if event.button() == QtCore.Qt.MouseButton.LeftButton:
                self._release_pending = True
                self.pointer = self.canvas.transform_pos(event.position())
                if not self.draft.complete:
                    if self.draft.accept(self.pointer.x(), self.pointer.y()):
                        if self.draft.complete:
                            self.submit_draft()
                        else:
                            self.refresh()
                    else:
                        self.message.setText(
                            self.tr("Rejected: image bounds or minimum size.")
                        )
                self.canvas.update()
            return True
        if (
            kind == QtCore.QEvent.Type.MouseButtonRelease
            and self._release_pending
        ):
            self._release_pending = False
            return True
        if kind not in (
            QtCore.QEvent.Type.ShortcutOverride,
            QtCore.QEvent.Type.KeyPress,
        ):
            return False
        key = event.key()
        ctrl_z = key == QtCore.Qt.Key.Key_Z and bool(
            event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier
        )
        keys = (
            QtCore.Qt.Key.Key_Escape,
            QtCore.Qt.Key.Key_Return,
            QtCore.Qt.Key.Key_Enter,
            QtCore.Qt.Key.Key_Backspace,
        )
        claimed = (self.draft is not None and (key in keys or ctrl_z)) or (
            self.refining
            and key
            in (
                QtCore.Qt.Key.Key_Return,
                QtCore.Qt.Key.Key_Enter,
                QtCore.Qt.Key.Key_Tab,
                QtCore.Qt.Key.Key_Backtab,
                QtCore.Qt.Key.Key_Escape,
            )
        )
        if not claimed:
            return False
        event.accept()
        if kind == QtCore.QEvent.Type.ShortcutOverride:
            return True
        return self._key(key, ctrl_z, event.modifiers())

    def _key(self, key: int, ctrl_z: bool, modifiers: Any) -> bool:
        """Execute a claimed canvas key without crossing transaction scopes."""
        if self.draft is not None:
            if ctrl_z or key == QtCore.Qt.Key.Key_Backspace:
                self.back()
            elif key == QtCore.Qt.Key.Key_Escape:
                self.reset(restore=True)
                self.canvas.drawing_polygon.emit(False)
                self._toggle_tool(True)
                self.canvas.update()
            else:
                self.submit_draft()
        elif key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            self.finish()
        elif key in (QtCore.Qt.Key.Key_Tab, QtCore.Qt.Key.Key_Backtab):
            self.canvas._cycle_rect_edge(
                key == QtCore.Qt.Key.Key_Backtab
                or bool(modifiers & QtCore.Qt.KeyboardModifier.ShiftModifier)
            )
        elif self.canvas.rect_edge_dragging:
            self.canvas.cancel_rect_edge_drag()
        elif self.canvas.rect_edge_active_edge is not None:
            self.canvas.clear_rect_edge_alignment()
            self.canvas.update()
        else:
            self.finish()
        return True

    def paint_draft(self, painter: QtGui.QPainter) -> None:
        """Draw transient extreme guides in the canvas image coordinate space."""
        if self.draft is None:
            return
        painter.save()
        pen = QtGui.QPen(QtGui.QColor(255, 210, 40))
        pen.setCosmetic(True)
        pen.setWidth(1)
        painter.setPen(pen)
        points = list(self.draft.points)
        if not self.draft.complete and self.pointer is not None:
            points.append((self.pointer.x(), self.pointer.y()))
        for edge, (x, y) in zip(EDGES, points):
            if edge in ("top", "bottom"):
                painter.drawLine(
                    QtCore.QPointF(0, y),
                    QtCore.QPointF(self.draft.width - 1, y),
                )
            else:
                painter.drawLine(
                    QtCore.QPointF(x, 0),
                    QtCore.QPointF(x, self.draft.height - 1),
                )
            painter.drawEllipse(
                QtCore.QPointF(x, y),
                3 / self.canvas.scale,
                3 / self.canvas.scale,
            )
        painter.restore()
