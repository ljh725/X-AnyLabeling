"""Standalone four-extreme creation without refinement or review sessions."""

from __future__ import annotations

from typing import Any

from PyQt6 import QtCore, QtGui, QtWidgets

from ..review_refinement.extreme import EDGES, ExtremeDraft
from ..shape import Shape


class RectangleCreation(QtWidgets.QWidget):
    """Own only an uncommitted rectangle creation draft."""

    def __init__(self, owner: Any) -> None:
        """Connect independent creation actions to the existing canvas."""
        super().__init__(owner)
        self.owner = owner
        self.canvas = owner.canvas
        self.draft: ExtremeDraft | None = None
        self.pointer: QtCore.QPointF | None = None
        self._changing_tool = False
        self._committing = False
        self._release_pending = False
        self._last_label: str | None = None
        self.commands: dict[str, QtGui.QAction] = {}
        self.menu = owner.menus.tool.addMenu(self.tr("Four extremes"))
        for key, title, callback in (
            ("rectangle_extreme", "Four extremes", self.start_extreme),
            ("rectangle_submit", "Submit draft", self.submit_draft),
            ("rectangle_back", "Back one boundary", self.back),
            ("rectangle_continue", "Continue drawing", self.continue_drawing),
        ):
            action = QtGui.QAction(self.tr(title), self.canvas)
            action.setShortcut(
                owner._config.get("shortcuts", {}).get(key) or ""
            )
            action.setShortcutContext(QtCore.Qt.ShortcutContext.WidgetShortcut)
            action.setAutoRepeat(False)
            action.triggered.connect(
                lambda _checked=False, run=callback: run()
            )
            self.canvas.addAction(action)
            self.menu.addAction(action)
            self.commands[key] = action
            setattr(owner.actions, key, action)
        self.canvas.rectangle_creation = self
        self.canvas.installEventFilter(self)
        self.canvas.selection_changed.connect(self.refresh)
        self.canvas.shape_moved.connect(self.refresh)
        self.refresh()

    @staticmethod
    def tr(text: str) -> str:
        """Reuse the existing translations of the retained creation commands."""
        return QtCore.QCoreApplication.translate("RectangleWorkflow", text)

    def refresh(self, *_args: Any) -> None:
        """Enable actions according to the image and pending draft."""
        loaded = (
            self.canvas.pixmap is not None and not self.canvas.pixmap.isNull()
        )
        self.commands["rectangle_extreme"].setEnabled(loaded)
        self.commands["rectangle_continue"].setEnabled(loaded)
        self.commands["rectangle_submit"].setEnabled(
            self.draft is not None and self.draft.complete
        )
        self.commands["rectangle_back"].setEnabled(
            self.draft is not None and bool(self.draft.points)
        )
        if self.draft is not None:
            if self.draft.complete:
                message = self.tr("Draft ready: submit or go back.")
            else:
                names = [
                    self.tr(edge)
                    for edge in ("Top", "Right", "Bottom", "Left")
                ]
                message = self.tr("Click boundary {step}/4: {edge}").format(
                    step=len(self.draft.points) + 1,
                    edge=names[len(self.draft.points)],
                )
            self.owner.status(message)

    def _toggle_tool(self, edit: bool) -> None:
        """Use the normal mode transition without canceling this draft."""
        self._changing_tool = True
        try:
            self.owner.toggle_draw_mode(edit=edit, create_mode="rectangle")
        finally:
            self._changing_tool = False

    def before_tool_change(self, edit: bool, create_mode: str) -> None:
        """Cancel only uncommitted creation on an external tool change."""
        if not self._changing_tool and not self._committing:
            if self.draft is not None:
                self.owner.digit_bind_draw_manager.clear_pending()
            self.reset()

    def reset(self) -> None:
        """Discard draft state while leaving committed shapes untouched."""
        if self.draft is not None:
            self.canvas.current = None
            self.canvas.line.points = []
            self.canvas.drawing_polygon.emit(False)
        self.draft = None
        self.pointer = None
        self._release_pending = False
        self.refresh()

    def start_extreme(self) -> None:
        """Start a four-boundary draft on the current image."""
        if self.canvas.pixmap is None or self.canvas.pixmap.isNull():
            return
        if self.draft is not None:
            self.owner.digit_bind_draw_manager.clear_pending()
        self.reset()
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
        """Start another draft with the last successfully committed label."""
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

    def cancel(self) -> None:
        """Cancel creation and return to ordinary editing."""
        self.owner.digit_bind_draw_manager.clear_pending()
        self.reset()
        self._toggle_tool(True)
        self.canvas.setFocus()
        self.canvas.update()

    def submit_draft(self) -> None:
        """Commit through the existing shape, label and undo transaction."""
        if self.draft is None or not self.draft.complete or self._committing:
            return
        left, top, right, bottom = self.draft.bbox()
        shape = Shape(shape_type="rectangle")
        shape.points = [
            QtCore.QPointF(x, y)
            for x, y in (
                (left, top),
                (right, top),
                (right, bottom),
                (left, bottom),
            )
        ]
        backups = list(self.canvas.shapes_backups)
        pending = getattr(self.canvas, "_pending_initial_backup", False)
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
        self.canvas.shapes_backups.pop()
        self.canvas.store_shapes()
        self.draft = None
        self.canvas.drawing_polygon.emit(False)
        self._toggle_tool(True)
        self.canvas.select_shapes([shape])
        self.canvas.setFocus()
        self.refresh()

    def eventFilter(
        self, watched: QtCore.QObject, event: QtCore.QEvent
    ) -> bool:
        """Consume creation clicks and draft-control keys only while active."""
        if watched is not self.canvas:
            return False
        kind = event.type()
        if (
            kind == QtCore.QEvent.Type.MouseButtonRelease
            and self._release_pending
        ):
            self._release_pending = False
            return True
        if self.draft is None:
            return False
        if kind == QtCore.QEvent.Type.MouseMove:
            self.pointer = self.canvas.transform_pos(event.position())
            self.canvas.update()
            return True
        if kind in (
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
                        self.owner.status(
                            self.tr("Rejected: image bounds or minimum size.")
                        )
                self.canvas.update()
            return True
        if kind not in (
            QtCore.QEvent.Type.ShortcutOverride,
            QtCore.QEvent.Type.KeyPress,
        ):
            return False
        key = event.key()
        undo = key == QtCore.Qt.Key.Key_Z and bool(
            event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier
        )
        if not undo and key not in (
            QtCore.Qt.Key.Key_Escape,
            QtCore.Qt.Key.Key_Return,
            QtCore.Qt.Key.Key_Enter,
            QtCore.Qt.Key.Key_Backspace,
        ):
            return False
        event.accept()
        if kind == QtCore.QEvent.Type.KeyPress:
            if undo or key == QtCore.Qt.Key.Key_Backspace:
                self.back()
            elif key == QtCore.Qt.Key.Key_Escape:
                self.cancel()
            else:
                self.submit_draft()
        return True

    def paint_draft(self, painter: QtGui.QPainter) -> None:
        """Draw temporary extreme guides in image coordinates."""
        if self.draft is None:
            return
        painter.save()
        pen = QtGui.QPen(QtGui.QColor(255, 210, 40))
        pen.setCosmetic(True)
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
