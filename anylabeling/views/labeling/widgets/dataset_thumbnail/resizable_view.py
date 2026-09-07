"""Uniform card scaling without changing selection or page contents."""

from PyQt6 import QtCore, QtGui, QtWidgets


class ResizableThumbnailView(QtWidgets.QListView):
    """Resize every card with a bounded edge gesture on any one card."""

    resize_started = QtCore.pyqtSignal()
    resize_finished = QtCore.pyqtSignal()
    object_clicked = QtCore.pyqtSignal(QtCore.QModelIndex)
    MIN_WIDTH = 160
    MAX_WIDTH = 520
    DEFAULT_WIDTH = 220

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        """Prepare a throttled layout gesture and normal click tracking."""
        super().__init__(parent)
        self.card_width = self.DEFAULT_WIDTH
        self.is_resizing = False
        self._edge = ""
        self._origin = QtCore.QPointF()
        self._start_width = self.card_width
        self._pending_width = self.card_width
        self._anchor = QtCore.QPersistentModelIndex()
        self._click_index = QtCore.QPersistentModelIndex()
        self._click_origin = QtCore.QPointF()
        self._layout_timer = QtCore.QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.setInterval(16)
        self._layout_timer.timeout.connect(self._apply_pending_width)
        self.setMouseTracking(True)

    def card_size(self) -> QtCore.QSize:
        """Return the shared size, preserving the original card ratio."""
        return QtCore.QSize(
            self.card_width, round(self.card_width * 190 / 220)
        )

    def set_card_width(self, width: int) -> None:
        """Apply a bounded display size without resetting the model."""
        width = max(self.MIN_WIDTH, min(self.MAX_WIDTH, int(width)))
        if width == self.card_width:
            return
        self.card_width = width
        self.doItemsLayout()
        self.viewport().update()

    def _edge_at(self, point: QtCore.QPoint) -> str:
        """Return the resize edge within a card's visible border."""
        index = self.indexAt(point)
        if not index.isValid():
            return ""
        rect = self.visualRect(index).adjusted(4, 4, -4, -4)
        right = abs(point.x() - rect.right()) <= 6
        bottom = abs(point.y() - rect.bottom()) <= 6
        if right and bottom:
            return "corner"
        if right:
            return "right"
        return "bottom" if bottom else ""

    def _set_edge_cursor(self, edge: str) -> None:
        """Distinguish resizing from ordinary card selection."""
        cursors = {
            "right": QtCore.Qt.CursorShape.SizeHorCursor,
            "bottom": QtCore.Qt.CursorShape.SizeVerCursor,
            "corner": QtCore.Qt.CursorShape.SizeFDiagCursor,
        }
        if edge:
            self.viewport().setCursor(cursors[edge])
        else:
            self.viewport().unsetCursor()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        """Consume edge presses before Qt can alter the selection."""
        self._click_index = QtCore.QPersistentModelIndex()
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            point = event.position().toPoint()
            self._edge = self._edge_at(point)
            if self._edge:
                self.is_resizing = True
                self._origin = event.globalPosition()
                self._start_width = self.card_width
                self._pending_width = self.card_width
                self._anchor = QtCore.QPersistentModelIndex(
                    self.indexAt(point)
                )
                self._set_edge_cursor(self._edge)
                self.resize_started.emit()
                event.accept()
                return
            self._click_index = QtCore.QPersistentModelIndex(
                self.indexAt(point)
            )
            self._click_origin = event.globalPosition()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        """Preview one shared scale, at most once per layout timer tick."""
        if self.is_resizing:
            delta = event.globalPosition() - self._origin
            distance = (
                delta.y() * 220 / 190 if self._edge == "bottom" else delta.x()
            )
            self._pending_width = round(self._start_width + distance)
            if not self._layout_timer.isActive():
                self._layout_timer.start()
            event.accept()
            return
        self._set_edge_cursor(self._edge_at(event.position().toPoint()))
        if (
            event.globalPosition() - self._click_origin
        ).manhattanLength() > QtWidgets.QApplication.startDragDistance():
            self._click_index = QtCore.QPersistentModelIndex()
        super().mouseMoveEvent(event)

    def _apply_pending_width(self) -> None:
        """Keep the dragged card visible through a grid reflow."""
        self.set_card_width(self._pending_width)
        if self._anchor.isValid():
            self.scrollTo(
                QtCore.QModelIndex(self._anchor),
                QtWidgets.QAbstractItemView.ScrollHint.EnsureVisible,
            )

    def finish_resize(self) -> None:
        """Finish once on release or focus loss, including the final tick."""
        if not self.is_resizing:
            return
        self._layout_timer.stop()
        self._apply_pending_width()
        self.is_resizing = False
        self._anchor = QtCore.QPersistentModelIndex()
        self._set_edge_cursor("")
        self.resize_finished.emit()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        """Commit scaling or record only a selected left-clicked object."""
        if self.is_resizing:
            self.finish_resize()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        index = self.indexAt(event.position().toPoint())
        if (
            event.button() == QtCore.Qt.MouseButton.LeftButton
            and self._click_index.isValid()
            and index == self._click_index
            and self.selectionModel().isSelected(index)
        ):
            self.object_clicked.emit(index)
        self._click_index = QtCore.QPersistentModelIndex()

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        """Keep border double clicks from navigating to the main canvas."""
        if self._edge_at(event.position().toPoint()):
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def focusOutEvent(self, event: QtGui.QFocusEvent) -> None:
        """Release a gesture if its window loses input focus."""
        self.finish_resize()
        super().focusOutEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        """Reset the hover cursor without interrupting a grabbed drag."""
        if not self.is_resizing:
            self._set_edge_cursor("")
        super().leaveEvent(event)
