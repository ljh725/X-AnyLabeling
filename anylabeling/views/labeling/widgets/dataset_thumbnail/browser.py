"""Dataset-level label thumbnail browser window."""

from __future__ import annotations

import hashlib
import os.path as osp
from typing import Callable, Iterable, Optional

from PyQt6 import QtCore, QtGui, QtWidgets

from anylabeling.views.labeling.dataset_index import (
    DatasetThumbnailPage,
    DatasetThumbnailRef,
)
from anylabeling.views.labeling.widgets.object_relabel import (
    KEEP_ON_RESULT,
    REMOVE_ON_RESULT,
)

from .pipeline import ThumbnailRenderResult, ThumbnailRenderer


def thumbnail_cache_root(dataset_root: str) -> str:
    """Return a stable user-cache directory for one dataset."""
    token = hashlib.sha256(
        osp.normcase(osp.abspath(dataset_root)).encode("utf-8")
    ).hexdigest()[:24]
    cache_root = QtCore.QStandardPaths.writableLocation(
        QtCore.QStandardPaths.StandardLocation.CacheLocation
    )
    if not cache_root:
        cache_root = QtCore.QStandardPaths.writableLocation(
            QtCore.QStandardPaths.StandardLocation.TempLocation
        )
    return osp.join(cache_root, "dataset_thumbnails", token)


class ThumbnailItemModel(QtCore.QAbstractListModel):
    """Model containing one bounded page of thumbnail references."""

    RefRole = QtCore.Qt.ItemDataRole.UserRole + 1
    ImageRole = QtCore.Qt.ItemDataRole.UserRole + 2
    ErrorRole = QtCore.Qt.ItemDataRole.UserRole + 3
    MutationErrorRole = QtCore.Qt.ItemDataRole.UserRole + 4

    def __init__(self, parent: Optional[QtCore.QObject] = None) -> None:
        """Initialize an empty thumbnail page."""
        super().__init__(parent)
        self._items: tuple[DatasetThumbnailRef, ...] = ()
        self._images: dict[tuple[str, str, int], QtGui.QImage] = {}
        self._render_errors: dict[tuple[str, str, int], str] = {}
        self._mutation_errors: dict[tuple[str, str], str] = {}

    @staticmethod
    def item_key(ref: DatasetThumbnailRef) -> tuple[str, str, int]:
        """Return a stable view key for a thumbnail reference."""
        return (ref.image_path, ref.shape_id, ref.shape_index)

    @staticmethod
    def identity_key(ref: DatasetThumbnailRef) -> tuple[str, str]:
        """Return the permanent object identity used across page reloads."""
        return (osp.normcase(osp.abspath(ref.image_path)), ref.shape_id)

    def set_items(
        self,
        items: Iterable[DatasetThumbnailRef],
        mutation_errors: Optional[dict[tuple[str, str], str]] = None,
    ) -> None:
        """Replace the current page and clear stale render state."""
        self.beginResetModel()
        self._items = tuple(items)
        self._images.clear()
        self._render_errors.clear()
        self._mutation_errors = dict(mutation_errors or {})
        self.endResetModel()

    def ref_at(self, row: int) -> Optional[DatasetThumbnailRef]:
        """Return the reference at a model row, if present."""
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    def is_selectable(self, row: int) -> bool:
        """Return whether a row has the minimum data needed for relabeling."""
        ref = self.ref_at(row)
        return bool(
            ref
            and ref.shape_id.strip()
            and ref.bbox is not None
            and self.item_key(ref) not in self._render_errors
        )

    def set_render_result(self, result: ThumbnailRenderResult) -> None:
        """Apply a render result to its matching row."""
        key = self.item_key(result.ref)
        try:
            row = next(
                index
                for index, ref in enumerate(self._items)
                if self.item_key(ref) == key
            )
        except StopIteration:
            return
        if result.error:
            self._render_errors[key] = result.error
        elif result.image_bytes:
            image = QtGui.QImage.fromData(result.image_bytes, "PNG")
            if image.isNull():
                self._render_errors[key] = "thumbnail data is invalid"
            else:
                self._images[key] = image
        self.dataChanged.emit(
            self.index(row, 0),
            self.index(row, 0),
            [self.ImageRole, self.ErrorRole, QtCore.Qt.ItemDataRole.UserRole],
        )

    def set_mutation_errors(self, errors: dict[tuple[str, str], str]) -> None:
        """Replace persistent relabel errors without resetting the page."""
        self._mutation_errors = dict(errors)
        if self._items:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._items) - 1, 0),
                [self.MutationErrorRole],
            )

    def data(
        self,
        index: QtCore.QModelIndex,
        role: int = QtCore.Qt.ItemDataRole.DisplayRole,
    ):
        """Return display, reference, image and error data for a row."""
        ref = self.ref_at(index.row()) if index.isValid() else None
        if ref is None:
            return None
        key = self.item_key(ref)
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return osp.basename(ref.image_path)
        if role == self.RefRole:
            return ref
        if role == self.ImageRole:
            return self._images.get(key)
        if role == self.ErrorRole:
            return self._render_errors.get(key, "")
        if role == self.MutationErrorRole:
            return self._mutation_errors.get(self.identity_key(ref), "")
        return None

    def rowCount(
        self, parent: QtCore.QModelIndex = QtCore.QModelIndex()
    ) -> int:
        """Return the number of rows in the current page."""
        return 0 if parent.isValid() else len(self._items)

    def flags(self, index: QtCore.QModelIndex) -> QtCore.Qt.ItemFlag:
        """Allow selection only for rows with valid metadata."""
        flags = QtCore.Qt.ItemFlag.ItemIsEnabled
        if index.isValid() and self.is_selectable(index.row()):
            flags |= QtCore.Qt.ItemFlag.ItemIsSelectable
        return flags


class ThumbnailItemDelegate(QtWidgets.QStyledItemDelegate):
    """Paint a compact image, label and identity summary for each item."""

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> None:
        """Paint one thumbnail card without creating child widgets."""
        painter.save()
        rect = option.rect.adjusted(4, 4, -4, -4)
        selected = bool(
            option.state & QtWidgets.QStyle.StateFlag.State_Selected
        )
        painter.setPen(
            QtGui.QPen(
                QtGui.QColor("#4c8dff") if selected else QtGui.QColor("#777")
            )
        )
        painter.setBrush(
            QtGui.QColor("#263241") if selected else QtGui.QColor("#20242b")
        )
        painter.drawRoundedRect(rect, 5, 5)
        image_rect = rect.adjusted(8, 8, -8, -42)
        image = index.data(ThumbnailItemModel.ImageRole)
        error = index.data(ThumbnailItemModel.ErrorRole) or ""
        mutation_error = index.data(ThumbnailItemModel.MutationErrorRole) or ""
        if isinstance(image, QtGui.QImage) and not image.isNull():
            pixmap = QtGui.QPixmap.fromImage(image)
            painter.drawPixmap(
                image_rect,
                pixmap.scaled(
                    image_rect.size(),
                    QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                    QtCore.Qt.TransformationMode.SmoothTransformation,
                ),
            )
        else:
            painter.setPen(QtGui.QColor("#c8c8c8"))
            painter.drawText(
                image_rect,
                QtCore.Qt.AlignmentFlag.AlignCenter,
                error or "Loading…",
            )
        if mutation_error:
            painter.fillRect(
                image_rect.adjusted(0, image_rect.height() - 34, 0, 0),
                QtGui.QColor(150, 25, 25, 210),
            )
            painter.setPen(QtGui.QColor("#ffffff"))
            painter.drawText(
                image_rect.adjusted(4, image_rect.height() - 32, -4, -2),
                QtCore.Qt.AlignmentFlag.AlignLeft
                | QtCore.Qt.AlignmentFlag.AlignVCenter,
                mutation_error,
            )
        ref = index.data(ThumbnailItemModel.RefRole)
        if isinstance(ref, DatasetThumbnailRef):
            painter.setPen(QtGui.QColor("#ffffff"))
            painter.drawText(
                rect.adjusted(8, rect.height() - 35, -8, -20),
                QtCore.Qt.AlignmentFlag.AlignLeft
                | QtCore.Qt.AlignmentFlag.AlignVCenter,
                ref.label,
            )
            painter.setPen(QtGui.QColor("#a9b4c2"))
            painter.drawText(
                rect.adjusted(8, rect.height() - 20, -8, -5),
                QtCore.Qt.AlignmentFlag.AlignLeft
                | QtCore.Qt.AlignmentFlag.AlignVCenter,
                f"{osp.basename(ref.image_path)}  #{ref.shape_id[:8]}",
            )
        painter.restore()

    def sizeHint(
        self,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> QtCore.QSize:
        """Return a fixed card size suitable for an icon-mode grid."""
        del option, index
        return QtCore.QSize(220, 190)


class DatasetLabelThumbnailWindow(QtWidgets.QWidget):
    """Non-modal label browser that emits selected objects for relabeling."""

    relabel_requested = QtCore.pyqtSignal(object, str)
    navigate_requested = QtCore.pyqtSignal(object)
    closed = QtCore.pyqtSignal()

    def __init__(
        self,
        index_controller,
        project_id: str,
        dataset_root: str,
        target_labels: Optional[Callable[[], Iterable[str]]] = None,
        digit_label_resolver: Optional[Callable[[int], Optional[str]]] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        """Initialize the browser against a read-only index controller."""
        super().__init__(parent, QtCore.Qt.WindowType.Window)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._controller = index_controller
        self._project_id = project_id
        self._dataset_root = osp.normcase(osp.abspath(dataset_root))
        self._target_labels = target_labels or (lambda: [])
        self._digit_label_resolver = digit_label_resolver or (
            lambda _digit: None
        )
        self._page_size = 100
        self._page = 0
        self._selected_label = ""
        self._current_total = 0
        self._closed = False
        self._render_generation = 0
        self._mutation_errors: dict[tuple[str, str], str] = {}
        self._retained_selection: set[tuple[str, str]] = set()
        self._digit_shortcuts: list[QtGui.QShortcut] = []
        self._model = ThumbnailItemModel(self)
        self._renderer = ThumbnailRenderer(
            thumbnail_cache_root(dataset_root), parent=self
        )
        self._visible_timer = QtCore.QTimer(self)
        self._visible_timer.setSingleShot(True)
        self._visible_timer.setInterval(40)
        self._visible_timer.timeout.connect(self._request_visible)
        self._reload_timer = QtCore.QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(75)
        self._reload_timer.timeout.connect(self._load_page)
        self._renderer.result_ready.connect(self._on_render_result)
        state_signal = getattr(self._controller, "state_changed", None)
        if state_signal is not None:
            state_signal.connect(self._on_controller_state_changed)
        refresh_signal = getattr(
            self._controller, "file_refresh_finished", None
        )
        if refresh_signal is not None:
            refresh_signal.connect(self._on_file_refresh_finished)
        self._build_ui()
        self._load_labels()

    def _index_is_ready(self) -> bool:
        """Return whether the controller owns a verified readable index."""
        return bool(
            self._controller.is_query_ready
            and getattr(self._controller, "state_value", "ready") == "ready"
        )

    def _build_ui(self) -> None:
        """Construct the compact browser controls and grid."""
        self.setWindowTitle(self.tr("Dataset Label Thumbnails"))
        self.resize(980, 760)
        root = QtWidgets.QVBoxLayout(self)
        controls = QtWidgets.QHBoxLayout()
        controls.addWidget(QtWidgets.QLabel(self.tr("Label:")))
        self.label_combo = QtWidgets.QComboBox()
        self.label_combo.currentIndexChanged.connect(self._on_label_changed)
        controls.addWidget(self.label_combo, 1)
        self.summary_label = QtWidgets.QLabel()
        controls.addWidget(self.summary_label)
        self.refresh_index_button = QtWidgets.QPushButton(
            self.tr("Refresh index")
        )
        self.refresh_index_button.clicked.connect(self._refresh_index)
        controls.addWidget(self.refresh_index_button)
        self.rebuild_index_button = QtWidgets.QPushButton(
            self.tr("Rebuild index")
        )
        self.rebuild_index_button.clicked.connect(self._rebuild_index)
        controls.addWidget(self.rebuild_index_button)
        root.addLayout(controls)

        self.view = QtWidgets.QListView()
        self.view.setModel(self._model)
        self.view.setItemDelegate(ThumbnailItemDelegate(self.view))
        self.view.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
        self.view.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
        self.view.setMovement(QtWidgets.QListView.Movement.Static)
        self.view.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.view.setSpacing(6)
        self.view.verticalScrollBar().valueChanged.connect(
            lambda _value: self._visible_timer.start()
        )
        self.view.selectionModel().selectionChanged.connect(
            lambda *_args: self._update_selection_summary()
        )
        self.view.doubleClicked.connect(self._activate_index)
        self.view.installEventFilter(self)
        root.addWidget(self.view, 1)

        footer = QtWidgets.QHBoxLayout()
        self.page_label = QtWidgets.QLabel()
        footer.addWidget(self.page_label)
        footer.addStretch(1)
        self.previous_button = QtWidgets.QPushButton(self.tr("Previous"))
        self.previous_button.clicked.connect(self._previous_page)
        footer.addWidget(self.previous_button)
        self.next_button = QtWidgets.QPushButton(self.tr("Next"))
        self.next_button.clicked.connect(self._next_page)
        footer.addWidget(self.next_button)
        self.relabel_button = QtWidgets.QPushButton(
            self.tr("Relabel selected")
        )
        self.relabel_button.clicked.connect(self._request_relabel)
        footer.addWidget(self.relabel_button)
        root.addLayout(footer)
        self._install_digit_shortcuts()
        self._update_selection_summary()

    def _install_digit_shortcuts(self) -> None:
        """Install window-local relabel shortcuts for configured digits."""
        for digit in range(10):
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(str(digit)), self)
            shortcut.setContext(QtCore.Qt.ShortcutContext.WindowShortcut)
            shortcut.setAutoRepeat(False)
            shortcut.activated.connect(
                lambda digit=digit: self._apply_digit_shortcut(digit)
            )
            self._digit_shortcuts.append(shortcut)

    def eventFilter(
        self, watched: QtCore.QObject, event: QtCore.QEvent
    ) -> bool:
        """Activate the current card on Enter without changing click behavior."""
        if (
            watched is self.view
            and event.type() == QtCore.QEvent.Type.KeyPress
        ):
            if event.key() in (
                QtCore.Qt.Key.Key_Return,
                QtCore.Qt.Key.Key_Enter,
            ):
                self._activate_index(self.view.currentIndex())
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def _activate_index(self, index: QtCore.QModelIndex) -> None:
        """Request main-canvas navigation for one explicitly activated card."""
        if not index.isValid() or not self._model.is_selectable(index.row()):
            return
        ref = self._model.ref_at(index.row())
        if ref is not None:
            self.navigate_requested.emit(ref)

    def _apply_digit_shortcut(self, digit: int) -> bool:
        """Relabel the current selection through the shared batch workflow."""
        focus = QtWidgets.QApplication.focusWidget()
        if isinstance(
            focus,
            (
                QtWidgets.QLineEdit,
                QtWidgets.QTextEdit,
                QtWidgets.QPlainTextEdit,
                QtWidgets.QAbstractSpinBox,
                QtWidgets.QComboBox,
            ),
        ):
            return False
        refs = self._selected_refs()
        if not refs:
            return False
        target = self._digit_label_resolver(digit)
        if not target or not str(target).strip():
            return False
        self.relabel_requested.emit(refs, str(target).strip())
        return True

    def focus_object(self, image_path: str, shape_id: str) -> bool:
        """Reveal and select one indexed object without emitting navigation."""
        location = self._controller.query_thumbnail_location(
            image_path, shape_id
        )
        if location is None:
            return False
        label_index = self.label_combo.findData(location.label)
        if label_index < 0:
            return False

        self.label_combo.blockSignals(True)
        self.label_combo.setCurrentIndex(label_index)
        self.label_combo.blockSignals(False)
        self._selected_label = location.label
        self._page = location.offset // self._page_size
        self._load_page()

        identity = (
            osp.normcase(osp.abspath(location.image_path)),
            location.shape_id,
        )
        for row in range(self._model.rowCount()):
            ref = self._model.ref_at(row)
            if ref is None or self._model.identity_key(ref) != identity:
                continue
            index = self._model.index(row, 0)
            self.view.clearSelection()
            self.view.selectionModel().select(
                index,
                QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect,
            )
            self.view.setCurrentIndex(index)
            self.view.scrollTo(
                index,
                QtWidgets.QAbstractItemView.ScrollHint.PositionAtCenter,
            )
            return True
        return False

    def _load_labels(self) -> None:
        """Load label counts from the active index or show its state."""
        if not self._index_is_ready():
            self._set_unavailable_state()
            return
        previous_label = self._selected_label
        self.label_combo.blockSignals(True)
        self.label_combo.clear()
        for label, count in self._controller.query_label_counts():
            if count > 0:
                self.label_combo.addItem(f"{label} ({count})", label)
        if self.label_combo.count():
            target_index = self.label_combo.findData(previous_label)
            self.label_combo.setCurrentIndex(max(0, target_index))
            self.label_combo.blockSignals(False)
            self._selected_label = str(self.label_combo.currentData() or "")
            self.refresh_index_button.hide()
            self.rebuild_index_button.hide()
            self._load_page()
        else:
            self.label_combo.blockSignals(False)
            self._set_empty_state()

    def refresh_from_index(self) -> None:
        """Reload labels and the current page after an index refresh."""
        self._load_labels()

    def _on_controller_state_changed(self, *_args) -> None:
        """Reflect READY/stale transitions without keeping old results."""
        if self._index_is_ready():
            self._load_labels()
        else:
            self._set_unavailable_state()

    def _on_file_refresh_finished(
        self, _image_path: str, succeeded: bool, _message: str
    ) -> None:
        """Refresh after successful JSON-to-index synchronization."""
        if succeeded and self._index_is_ready():
            self._reload_timer.start()
        elif not succeeded:
            self._reload_timer.stop()
            self._set_unavailable_state()

    def _set_empty_state(self) -> None:
        """Show a truthful empty-label state for a ready index."""
        self._selected_label = ""
        self._page = 0
        self._current_total = 0
        self._render_generation = self._renderer.invalidate()
        self._model.set_items(())
        self.summary_label.setText(self.tr("No labeled objects in the index"))
        self.page_label.setText("")
        self.relabel_button.setEnabled(False)
        self.refresh_index_button.hide()
        self.rebuild_index_button.hide()

    def _set_unavailable_state(self) -> None:
        """Clear old data while the controller cannot serve safe queries."""
        self._model.set_items(())
        self._current_total = 0
        state = getattr(self._controller, "state_value", "unavailable")
        self.summary_label.setText(
            self.tr("Index unavailable: %1").replace("%1", str(state))
        )
        self.page_label.setText("")
        self.relabel_button.setEnabled(False)
        busy = bool(getattr(self._controller, "is_busy", False))
        self.refresh_index_button.setEnabled(not busy)
        self.rebuild_index_button.setEnabled(not busy)
        self.refresh_index_button.show()
        self.rebuild_index_button.show()

    def _refresh_index(self) -> None:
        """Start the existing incremental index recovery path."""
        if self._controller.refresh():
            self._set_unavailable_state()

    def _rebuild_index(self) -> None:
        """Start the existing full index recovery path."""
        if self._controller.rebuild():
            self._set_unavailable_state()

    def _on_label_changed(self, index: int) -> None:
        """Reset page and selection when the observed label changes."""
        label = self.label_combo.itemData(index)
        self._selected_label = str(label or "")
        self._page = 0
        self._load_page()

    def _load_page(self) -> None:
        """Fetch one page from SQLite and request visible thumbnails."""
        if not self._index_is_ready() or not self._selected_label:
            self._set_unavailable_state()
            return
        page: DatasetThumbnailPage = self._controller.query_thumbnail_objects(
            self._selected_label, self._page_size, self._page * self._page_size
        )
        last_page = max(0, (page.total - 1) // self._page_size)
        if self._page > last_page:
            self._page = last_page
            page = self._controller.query_thumbnail_objects(
                self._selected_label,
                self._page_size,
                self._page * self._page_size,
            )
        self._current_total = page.total
        self._render_generation = self._renderer.invalidate()
        self._model.set_items(page.items, self._mutation_errors)
        self.view.clearSelection()
        self._restore_retained_selection()
        self._update_page_controls()
        self._visible_timer.start(0)

    def _request_visible(self) -> None:
        """Request only visible rows plus a small one-screen look-ahead."""
        if not self._model.rowCount():
            return
        viewport = self.view.viewport().rect().adjusted(0, -220, 0, 220)
        refs = []
        for row in range(self._model.rowCount()):
            index = self._model.index(row, 0)
            if self.view.visualRect(index).intersects(viewport):
                ref = self._model.ref_at(row)
                if ref is not None:
                    refs.append(ref)
        self._renderer.request(refs, generation=self._render_generation)

    def _on_render_result(self, result: ThumbnailRenderResult) -> None:
        """Apply only results belonging to the renderer's current generation."""
        if result.generation != self._renderer.generation:
            return
        self._model.set_render_result(result)
        self._update_selection_summary()

    def _update_page_controls(self) -> None:
        """Update page text and navigation enablement."""
        pages = max(
            1, (self._current_total + self._page_size - 1) // self._page_size
        )
        self.page_label.setText(
            self.tr("Page %1 / %2 (%3 objects)")
            .replace("%1", str(self._page + 1))
            .replace("%2", str(pages))
            .replace("%3", str(self._current_total))
        )
        self.previous_button.setEnabled(self._page > 0)
        self.next_button.setEnabled(
            (self._page + 1) * self._page_size < self._current_total
        )

    def _previous_page(self) -> None:
        """Navigate to the previous result page."""
        if self._page > 0:
            self._page -= 1
            self._load_page()

    def _next_page(self) -> None:
        """Navigate to the next result page."""
        if (self._page + 1) * self._page_size < self._current_total:
            self._page += 1
            self._load_page()

    def _selected_refs(self) -> tuple[DatasetThumbnailRef, ...]:
        """Return selectable refs currently selected in the grid."""
        refs = []
        for index in self.view.selectionModel().selectedIndexes():
            if self._model.is_selectable(index.row()):
                ref = self._model.ref_at(index.row())
                if ref is not None:
                    refs.append(ref)
        return tuple(refs)

    def _restore_retained_selection(self) -> None:
        """Restore only failed/cancelled selections still on this page."""
        selection_model = self.view.selectionModel()
        for row in range(self._model.rowCount()):
            ref = self._model.ref_at(row)
            if (
                ref is not None
                and self._model.identity_key(ref) in self._retained_selection
                and self._model.is_selectable(row)
            ):
                selection_model.select(
                    self._model.index(row, 0),
                    QtCore.QItemSelectionModel.SelectionFlag.Select,
                )

    def _update_selection_summary(self) -> None:
        """Update selected object/file counts and button state."""
        refs = self._selected_refs()
        files = {ref.image_path for ref in refs}
        self.summary_label.setText(
            self.tr("Selected: %1 objects in %2 files")
            .replace("%1", str(len(refs)))
            .replace("%2", str(len(files)))
        )
        self.relabel_button.setEnabled(bool(refs) and self._index_is_ready())

    def _request_relabel(self) -> None:
        """Choose a target label and emit the immutable page selection."""
        refs = self._selected_refs()
        if not refs:
            return
        labels = [
            str(label) for label in self._target_labels() if str(label).strip()
        ]
        target, ok = QtWidgets.QInputDialog.getItem(
            self,
            self.tr("Relabel selected objects"),
            self.tr("Target label:"),
            labels,
            0,
            True,
        )
        if ok and target.strip():
            self.relabel_requested.emit(refs, target.strip())

    def apply_relabel_result(self, result) -> None:
        """Retain failed objects and coalesce successful index refreshes."""
        for item in result.objects:
            identity = (
                osp.normcase(osp.abspath(item.key[1])),
                item.key[2],
            )
            if item.status in KEEP_ON_RESULT:
                self._retained_selection.add(identity)
                if item.status != "cancelled":
                    self._mutation_errors[identity] = item.message or self.tr(
                        "Relabel failed: %1"
                    ).replace("%1", item.status)
            elif item.status in REMOVE_ON_RESULT:
                self._retained_selection.discard(identity)
                self._mutation_errors.pop(identity, None)
        self._model.set_mutation_errors(self._mutation_errors)
        self.view.clearSelection()
        self._restore_retained_selection()
        self._update_selection_summary()
        if result.committed_annotation_paths:
            self._reload_timer.start()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Stop accepting render results when the window closes."""
        if self._closed:
            super().closeEvent(event)
            return
        self._closed = True
        self._visible_timer.stop()
        self._reload_timer.stop()
        self._renderer.close()
        self.closed.emit()
        super().closeEvent(event)
