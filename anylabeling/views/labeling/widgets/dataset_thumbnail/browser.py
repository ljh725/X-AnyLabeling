"""Dataset-level label thumbnail browser window."""

from __future__ import annotations

import hashlib
import os.path as osp
import time
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
    FocusRole = QtCore.Qt.ItemDataRole.UserRole + 5

    def __init__(self, parent: Optional[QtCore.QObject] = None) -> None:
        """Initialize an empty thumbnail page."""
        super().__init__(parent)
        self._items: tuple[DatasetThumbnailRef, ...] = ()
        self._images: dict[tuple[str, str, int], QtGui.QImage] = {}
        self._render_errors: dict[tuple[str, str, int], str] = {}
        self._mutation_errors: dict[tuple[str, str], str] = {}
        self._focus_identity: Optional[tuple[str, str]] = None

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
            image = getattr(result, "image", None)
            if image is None:
                image = QtGui.QImage.fromData(result.image_bytes, "PNG")
            if image.isNull():
                self._render_errors[key] = "thumbnail data is invalid"
            else:
                self._render_errors.pop(key, None)
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

    def set_focus_identity(self, identity: Optional[tuple[str, str]]) -> None:
        """Set the object emphasized by reverse navigation."""
        normalized = None
        if identity is not None:
            normalized = (osp.normcase(osp.abspath(identity[0])), identity[1])
        if normalized == self._focus_identity:
            return
        self._focus_identity = normalized
        if self._items:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._items) - 1, 0),
                [self.FocusRole],
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
        if role == self.FocusRole:
            return self.identity_key(ref) == self._focus_identity
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
        border_color = "#35a2ff" if selected else "#777"
        border_width = 4 if selected else 1
        painter.setPen(QtGui.QPen(QtGui.QColor(border_color), border_width))
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
            fitted = pixmap.scaled(
                image_rect.size(),
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            target = QtCore.QRect(QtCore.QPoint(), fitted.size())
            target.moveCenter(image_rect.center())
            painter.drawPixmap(target.topLeft(), fitted)
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
        if index.data(ThumbnailItemModel.FocusRole):
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 3))
            painter.drawRoundedRect(rect.adjusted(6, 6, -6, -6), 4, 4)
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
    undo_requested = QtCore.pyqtSignal(object)
    restore_requested = QtCore.pyqtSignal(str)
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
        defer_initial_load: bool = False,
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
        self._initialized = False
        self._single_undo = None
        self._render_requested = set()
        self._render_finished = {}
        self._render_generation = 0
        self._mutation_errors: dict[tuple[str, str], str] = {}
        self._retained_selection: set[tuple[str, str]] = set()
        self._programmatic_selection = False
        self._relabel_refresh_pending = False
        self._result_base_summary = ""
        self._result_details = ""
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
        progress_signal = getattr(self._controller, "progress_changed", None)
        if progress_signal is not None:
            progress_signal.connect(self._on_scan_progress)
        busy_signal = getattr(self._controller, "busy_changed", None)
        if busy_signal is not None:
            busy_signal.connect(self._on_scan_busy_changed)
        self._build_ui()
        if defer_initial_load:
            QtCore.QTimer.singleShot(0, self._initialize)
        else:
            self._initialize()

    def _initialize(self) -> None:
        """Load the first page once, after the production window is shown."""
        if not self._closed and not self._initialized:
            self._initialized = True
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
        self.scan_button = QtWidgets.QPushButton(self.tr("Start scan"))
        self.scan_button.clicked.connect(self._start_scan)
        controls.addWidget(self.scan_button)
        root.addLayout(controls)

        self.result_frame = QtWidgets.QFrame()
        self.result_frame.setObjectName("thumbnailRelabelResultBar")
        result_layout = QtWidgets.QVBoxLayout(self.result_frame)
        result_layout.setContentsMargins(10, 7, 8, 7)
        result_header = QtWidgets.QHBoxLayout()
        self.result_summary_label = QtWidgets.QLabel()
        self.result_summary_label.setWordWrap(True)
        result_header.addWidget(self.result_summary_label, 1)
        self.result_details_button = QtWidgets.QPushButton(self.tr("Details"))
        self.result_details_button.clicked.connect(self._toggle_result_details)
        result_header.addWidget(self.result_details_button)
        self.result_restore_button = QtWidgets.QPushButton(
            self.tr("Restore this operation…")
        )
        self.result_restore_button.clicked.connect(
            self._request_result_restore
        )
        result_header.addWidget(self.result_restore_button)
        self.result_close_button = QtWidgets.QToolButton()
        self.result_close_button.setText("×")
        self.result_close_button.setToolTip(self.tr("Dismiss"))
        self.result_close_button.clicked.connect(self.result_frame.hide)
        result_header.addWidget(self.result_close_button)
        result_layout.addLayout(result_header)
        self.result_details_edit = QtWidgets.QPlainTextEdit()
        self.result_details_edit.setReadOnly(True)
        self.result_details_edit.setMaximumHeight(130)
        self.result_details_edit.hide()
        result_layout.addWidget(self.result_details_edit)
        self.result_frame.hide()
        root.addWidget(self.result_frame)

        progress_row = QtWidgets.QHBoxLayout()
        self.scan_progress_label = QtWidgets.QLabel()
        progress_row.addWidget(self.scan_progress_label)
        self.scan_progress_bar = QtWidgets.QProgressBar()
        progress_row.addWidget(self.scan_progress_bar, 1)
        root.addLayout(progress_row)
        self._set_scan_progress_visible(False)

        render_row = QtWidgets.QHBoxLayout()
        self.render_progress_label = QtWidgets.QLabel()
        self.render_progress_label.setToolTip(
            self.tr("Scanning indexes annotations; thumbnails load on demand.")
        )
        render_row.addWidget(self.render_progress_label, 1)
        self.retry_button = QtWidgets.QPushButton(
            self.tr("Retry failed images")
        )
        self.retry_button.clicked.connect(self._retry_failed_images)
        self.retry_button.setEnabled(False)
        render_row.addWidget(self.retry_button)
        root.addLayout(render_row)

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
            self._on_view_selection_changed
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
        self.undo_button = QtWidgets.QPushButton(
            self.tr("Undo last single-object relabel")
        )
        self.undo_button.clicked.connect(self._request_single_undo)
        footer.addWidget(self.undo_button)
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
        if not self._mutation_is_available():
            return False
        refs = self._selected_refs()
        if not refs:
            return False
        target = self._digit_label_resolver(digit)
        if not target or not str(target).strip():
            return False
        self.result_frame.hide()
        self.relabel_requested.emit(refs, str(target).strip())
        return True

    def focus_object(self, image_path: str, shape_id: str) -> bool:
        """Reveal an indexed object without adding a relabel candidate."""
        self._initialize()
        self._model.set_focus_identity(None)
        location = self._controller.query_thumbnail_location(
            image_path, shape_id
        )
        if location is None:
            return False
        label_index = self.label_combo.findData(location.label)
        if label_index < 0:
            return False

        identity = (
            osp.normcase(osp.abspath(location.image_path)),
            location.shape_id,
        )
        previous_guard = self._programmatic_selection
        self._programmatic_selection = True
        try:
            self.label_combo.blockSignals(True)
            self.label_combo.setCurrentIndex(label_index)
            self.label_combo.blockSignals(False)
            page = location.offset // self._page_size
            changed = (
                self._selected_label != location.label or self._page != page
            )
            self._selected_label = location.label
            self._page = page
            if changed:
                self._load_page()

            for row in range(self._model.rowCount()):
                ref = self._model.ref_at(row)
                if ref is None or self._model.identity_key(ref) != identity:
                    continue
                index = self._model.index(row, 0)
                self.view.selectionModel().setCurrentIndex(
                    index,
                    QtCore.QItemSelectionModel.SelectionFlag.NoUpdate,
                )
                self.view.scrollTo(
                    index,
                    QtWidgets.QAbstractItemView.ScrollHint.PositionAtCenter,
                )
                self._model.set_focus_identity(identity)
                return True
        finally:
            self._programmatic_selection = previous_guard
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
            self.scan_button.show()
            self.scan_button.setEnabled(
                not bool(getattr(self._controller, "is_busy", False))
            )
            self._load_page()
        else:
            self.label_combo.blockSignals(False)
            self._set_empty_state()

    def refresh_from_index(self) -> None:
        """Reload labels and the current page after an index refresh."""
        self._load_labels()

    def _on_controller_state_changed(self, *_args) -> None:
        """Reflect READY/stale transitions without keeping old results."""
        if bool(getattr(self._controller, "is_busy", False)):
            self._set_unavailable_state()
        elif self._index_is_ready():
            self._load_labels()
        else:
            self._set_unavailable_state()

    def _set_scan_progress_visible(self, visible: bool) -> None:
        """Show or hide the scan progress row."""
        self.scan_progress_label.setVisible(visible)
        self.scan_progress_bar.setVisible(visible)

    def _on_scan_progress(
        self, current: int, total: int, filename: str
    ) -> None:
        """Display progress forwarded by the shared index controller."""
        self._set_scan_progress_visible(True)
        if total > 0:
            self.scan_progress_bar.setRange(0, total)
            self.scan_progress_bar.setValue(max(0, min(current, total)))
        else:
            self.scan_progress_bar.setRange(0, 0)
        short_name = osp.basename(filename) if filename else ""
        self.scan_progress_label.setText(
            self.tr("Scanning: %1 / %2 %3")
            .replace("%1", str(current))
            .replace("%2", str(total))
            .replace("%3", short_name)
            .rstrip()
        )

    def _on_scan_busy_changed(self, busy: bool) -> None:
        """Gate mutation controls and load results when scanning ends."""
        self.scan_button.setEnabled(not busy)
        if busy:
            self._set_scan_progress_visible(True)
            self.scan_progress_bar.setRange(0, 0)
            self.scan_progress_label.setText(self.tr("Scanning…"))
            self.relabel_button.setEnabled(False)
            return
        self._set_scan_progress_visible(False)
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
            if self._result_base_summary:
                self.result_summary_label.setText(
                    self._result_base_summary
                    + " · "
                    + self.tr("Index refresh failed; relabel remains disabled")
                )

    def _set_empty_state(self) -> None:
        """Show a truthful empty-label state for a ready index."""
        self._selected_label = ""
        self._page = 0
        self._current_total = 0
        self._render_generation = self._renderer.invalidate()
        self._reset_render_progress()
        previous_guard = self._programmatic_selection
        self._programmatic_selection = True
        try:
            self._model.set_items(())
        finally:
            self._programmatic_selection = previous_guard
        self.summary_label.setText(self.tr("No labeled objects in the index"))
        self.page_label.setText("")
        self.relabel_button.setEnabled(False)
        self.scan_button.show()
        self.scan_button.setEnabled(True)
        self._set_scan_progress_visible(False)
        if self._index_is_ready():
            self._set_relabel_refresh_pending(False)

    def _set_unavailable_state(self) -> None:
        """Clear old data while the controller cannot serve safe queries."""
        self._render_generation = self._renderer.invalidate()
        self._reset_render_progress()
        self.undo_button.setEnabled(False)
        previous_guard = self._programmatic_selection
        self._programmatic_selection = True
        try:
            self._model.set_items(())
        finally:
            self._programmatic_selection = previous_guard
        self._current_total = 0
        state = getattr(self._controller, "state_value", "unavailable")
        self.summary_label.setText(
            self.tr("Index unavailable: %1").replace("%1", str(state))
        )
        self.page_label.setText("")
        self.relabel_button.setEnabled(False)
        busy = bool(getattr(self._controller, "is_busy", False))
        self.scan_button.setEnabled(not busy)
        self.scan_button.show()
        self._set_scan_progress_visible(busy)
        if busy and not self.scan_progress_label.text():
            self.scan_progress_bar.setRange(0, 0)
            self.scan_progress_label.setText(self.tr("Scanning…"))

    def _start_scan(self) -> None:
        """Start one explicit refresh or rebuild through the controller."""
        if bool(getattr(self._controller, "is_busy", False)):
            return
        self.scan_progress_label.setText(self.tr("Scanning…"))
        self.scan_progress_bar.setRange(0, 0)
        self._set_scan_progress_visible(True)
        if self._controller.is_query_ready:
            started = self._controller.refresh()
        else:
            started = self._controller.rebuild()
        if started:
            self._set_unavailable_state()
        else:
            self._set_scan_progress_visible(False)

    def _on_label_changed(self, index: int) -> None:
        """Reset page and selection when the observed label changes."""
        self._model.set_focus_identity(None)
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
        self._reset_render_progress()
        previous_guard = self._programmatic_selection
        self._programmatic_selection = True
        try:
            self._model.set_items(page.items, self._mutation_errors)
            self.view.clearSelection()
            self._restore_retained_selection()
        finally:
            self._programmatic_selection = previous_guard
        self._set_relabel_refresh_pending(False)
        self._update_page_controls()
        self._update_selection_summary()
        self._visible_timer.start(0)

    def _request_visible(self) -> None:
        """Request only visible rows plus a small one-screen look-ahead."""
        if not self._model.rowCount():
            return
        visible = self.view.viewport().rect()
        viewport = visible.adjusted(0, -220, 0, 220)
        refs = []
        prefetch = []
        for row in range(self._model.rowCount()):
            index = self._model.index(row, 0)
            if self.view.visualRect(index).intersects(viewport):
                ref = self._model.ref_at(row)
                if ref is not None:
                    if self.view.visualRect(index).intersects(visible):
                        refs.append(ref)
                    else:
                        prefetch.append(ref)
        for ref in refs:
            self._render_requested.add(self._model.item_key(ref))
        self._renderer.request(
            refs, generation=self._render_generation, prefetch=prefetch
        )
        self._update_render_progress()

    def _on_render_result(self, result: ThumbnailRenderResult) -> None:
        """Apply only results belonging to the renderer's current generation."""
        if result.generation != self._renderer.generation:
            return
        started = time.perf_counter()
        self._model.set_render_result(result)
        self._render_finished[self._model.item_key(result.ref)] = bool(
            result.error
        )
        self._update_render_progress()
        self._update_selection_summary()
        result.timings_ms["gui_apply"] = (time.perf_counter() - started) * 1000

    def _reset_render_progress(self) -> None:
        """Reset counts when the current page generation changes."""
        self._render_requested.clear()
        self._render_finished.clear()
        self._update_render_progress()

    def _update_render_progress(self) -> None:
        """Report visible requests only; prefetch cannot inflate progress."""
        ended = self._render_requested.intersection(self._render_finished)
        failed = sum(self._render_finished[key] for key in ended)
        self.render_progress_label.setText(
            self.tr("Thumbnails: %1/%2 finished, %3 failed (current view)")
            .replace("%1", str(len(ended)))
            .replace("%2", str(len(self._render_requested)))
            .replace("%3", str(failed))
        )
        self.retry_button.setEnabled(any(self._render_finished.values()))

    def _retry_failed_images(self) -> None:
        """Forget failed requests and retry them without changing selection."""
        refs = [
            ref
            for ref in self._model._items
            if self._render_finished.get(self._model.item_key(ref))
        ]
        for ref in refs:
            self._render_finished.pop(self._model.item_key(ref), None)
        self._renderer.retry(refs)
        self._request_visible()

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
            self._model.set_focus_identity(None)
            self._page -= 1
            self._load_page()

    def _next_page(self) -> None:
        """Navigate to the next result page."""
        if (self._page + 1) * self._page_size < self._current_total:
            self._model.set_focus_identity(None)
            self._page += 1
            self._load_page()
            self.view.doItemsLayout()
            self.view.scrollToTop()
            for row in range(self._model.rowCount()):
                if self._model.is_selectable(row):
                    self.view.selectionModel().setCurrentIndex(
                        self._model.index(row, 0),
                        QtCore.QItemSelectionModel.SelectionFlag.NoUpdate,
                    )
                    break

    def _on_view_selection_changed(self, *_args) -> None:
        """Clear navigation focus only after a user selection change."""
        if not self._programmatic_selection:
            self._model.set_focus_identity(None)
        self._update_selection_summary()

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
        self.undo_button.setEnabled(
            self._single_undo is not None and self._mutation_is_available()
        )
        files = {ref.image_path for ref in refs}
        self.summary_label.setText(
            self.tr("Selected: %1 objects in %2 files")
            .replace("%1", str(len(refs)))
            .replace("%2", str(len(files)))
        )
        busy = bool(getattr(self._controller, "is_busy", False))
        self.relabel_button.setEnabled(
            bool(refs)
            and self._index_is_ready()
            and not busy
            and not self._relabel_refresh_pending
        )

    def _mutation_is_available(self) -> bool:
        """Return whether the visible model is safe for a new mutation."""
        return bool(
            self._index_is_ready()
            and not bool(getattr(self._controller, "is_busy", False))
            and not self._relabel_refresh_pending
        )

    def _request_relabel(self) -> None:
        """Choose a target label and emit the immutable page selection."""
        if not self._mutation_is_available():
            return
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
            self.result_frame.hide()
            self.relabel_requested.emit(refs, target.strip())

    def apply_relabel_result(self, result) -> None:
        """Retain failed objects and coalesce successful index refreshes."""
        if result.committed_annotation_paths:
            self._single_undo = getattr(result, "undo_record", None)
        self._show_relabel_result(result)
        if result.committed_annotation_paths:
            self._set_relabel_refresh_pending(True)
        for item in result.objects:
            identity = (
                osp.normcase(osp.abspath(item.key[1])),
                item.key[2],
            )
            if item.status in KEEP_ON_RESULT:
                self._retained_selection.add(identity)
                if item.status == "cancelled":
                    self._mutation_errors[identity] = item.message or self.tr(
                        "Relabel cancelled before commit"
                    )
                else:
                    self._mutation_errors[identity] = item.message or self.tr(
                        "Relabel failed: %1"
                    ).replace("%1", item.status)
            elif item.status in REMOVE_ON_RESULT:
                self._retained_selection.discard(identity)
                self._mutation_errors.pop(identity, None)
        self._model.set_mutation_errors(self._mutation_errors)
        previous_guard = self._programmatic_selection
        self._programmatic_selection = True
        try:
            self.view.clearSelection()
            self._restore_retained_selection()
        finally:
            self._programmatic_selection = previous_guard
        self._update_selection_summary()
        if result.committed_annotation_paths:
            self._reload_timer.start()

    def apply_restore_result(self, result) -> None:
        """Show file-level recovery feedback and wait for a fresh model."""
        self.clear_single_undo()
        counts = result.counts
        restored = counts.get("succeeded", 0)
        conflict = counts.get("conflict", 0)
        failed = counts.get("failed", 0)
        if restored and not (conflict or failed):
            level = "success"
            title = self.tr("Recovery completed")
        elif restored:
            level = "warning"
            title = self.tr("Recovery partially completed")
        else:
            level = "error"
            title = self.tr("Recovery not completed")
        summary = self.tr("%1 — restored: %2, conflict: %3, failed: %4")
        summary = (
            summary.replace("%1", title)
            .replace("%2", str(restored))
            .replace("%3", str(conflict))
            .replace("%4", str(failed))
        )
        details = self._file_result_details(result)
        self._set_result_bar(level, summary, details, "")
        if restored:
            self._set_relabel_refresh_pending(True)
            self._update_selection_summary()
            self._reload_timer.start()

    def _show_relabel_result(self, result) -> None:
        """Render one structured relabel result in the in-window result bar."""
        counts = result.counts
        succeeded = counts.get("succeeded", 0)
        unchanged = counts.get("unchanged", 0)
        deleted = counts.get("deleted", 0)
        conflict = counts.get("conflict", 0)
        failed = counts.get("failed", 0)
        cancelled = counts.get("cancelled", 0)
        if result.cancelled:
            level = "neutral"
            stage = result.cancellation_stage
            if stage == "preflight":
                title = self.tr("Preflight stopped; no files entered commit")
            elif stage == "confirmation":
                title = self.tr(
                    "Commit was not confirmed; no files entered commit"
                )
            elif stage == "staging":
                title = self.tr("Staging stopped; no files were modified")
            else:
                title = self.tr("Relabel cancelled; no files were committed")
        elif succeeded > 0 and not (conflict or failed):
            level = "success"
            title = self.tr("Completed")
        elif (
            succeeded == 0
            and (unchanged or deleted)
            and not (conflict or failed)
        ):
            level = "neutral"
            title = self.tr("No write needed")
        elif succeeded > 0:
            level = "warning"
            title = self.tr("Partially completed")
        elif conflict or failed:
            level = "error"
            title = self.tr("Not completed")
        else:
            level = "neutral"
            title = self.tr("Not run")
        fragments = []
        target = str(getattr(result, "target_label", "") or "")
        if succeeded:
            fragments.append(
                self.tr('%1 changed to "%2"')
                .replace("%1", str(succeeded))
                .replace("%2", target)
            )
        for count, text in (
            (unchanged, self.tr("%1 unchanged")),
            (deleted, self.tr("%1 deleted")),
            (conflict, self.tr("%1 conflict")),
            (failed, self.tr("%1 failed")),
            (cancelled, self.tr("%1 cancelled")),
        ):
            if count:
                fragments.append(text.replace("%1", str(count)))
        if not fragments:
            fragments.append(self.tr("No objects were changed"))
        if conflict or failed:
            fragments.append(self.tr("Failed items remain selected"))
        summary = "%s — %s" % (title, ", ".join(fragments))
        manifest_path = result.manifest_path or ""
        can_restore = bool(
            manifest_path
            and osp.isfile(manifest_path)
            and result.committed_annotation_paths
        )
        self._set_result_bar(
            level,
            summary,
            self._object_result_details(result),
            manifest_path if can_restore else "",
        )

    def _object_result_details(self, result) -> str:
        """Return copyable object/file counts and recovery metadata."""
        counts = result.counts
        file_counts = result.file_counts
        return (
            self.tr(
                "Objects — succeeded: %1, unchanged: %2, deleted: %3, "
                "conflict: %4, failed: %5, cancelled: %6\n"
                "Files — succeeded: %7, skipped: %8, conflict: %9, failed: %10\n"
                "Recovery manifest: %11"
            )
            .replace("%11", result.manifest_path or self.tr("(none)"))
            .replace("%10", str(file_counts.get("failed", 0)))
            .replace("%9", str(file_counts.get("conflict", 0)))
            .replace("%8", str(file_counts.get("skipped", 0)))
            .replace("%7", str(file_counts.get("succeeded", 0)))
            .replace("%6", str(counts.get("cancelled", 0)))
            .replace("%5", str(counts.get("failed", 0)))
            .replace("%4", str(counts.get("conflict", 0)))
            .replace("%3", str(counts.get("deleted", 0)))
            .replace("%2", str(counts.get("unchanged", 0)))
            .replace("%1", str(counts.get("succeeded", 0)))
        )

    def _file_result_details(self, result) -> str:
        """Return copyable per-file restore outcomes."""
        lines = [
            self.tr("Recovery manifest: %1").replace(
                "%1", result.manifest_path or self.tr("(none)")
            )
        ]
        for item in result.files:
            line = "%s — %s" % (item.status, item.source_path)
            if item.message:
                line += ": " + item.message
            lines.append(line)
        return "\n".join(lines)

    def _set_result_bar(
        self, level: str, summary: str, details: str, manifest_path: str
    ) -> None:
        """Populate and reveal the persistent in-window result surface."""
        colors = {
            "success": ("#dff2e4", "#275d38"),
            "warning": ("#fff2cc", "#6b5200"),
            "error": ("#f9dddd", "#7a2525"),
            "neutral": ("#e8edf3", "#334155"),
        }
        background, foreground = colors.get(level, colors["neutral"])
        self.result_frame.setStyleSheet(
            "QFrame#thumbnailRelabelResultBar {"
            f"background: {background}; color: {foreground};"
            "border: 1px solid palette(mid); border-radius: 4px;}"
        )
        self.result_summary_label.setText(summary)
        self._result_base_summary = summary
        self._result_details = details
        self.result_details_edit.setPlainText(details)
        self.result_details_edit.hide()
        self.result_details_button.setText(self.tr("Details"))
        self.result_restore_button.setProperty("manifestPath", manifest_path)
        self.result_restore_button.setVisible(bool(manifest_path))
        self.result_frame.show()

    def _set_relabel_refresh_pending(self, pending: bool) -> None:
        """Gate mutations and expose whether the derived view is refreshing."""
        self._relabel_refresh_pending = pending
        self.undo_button.setEnabled(
            self._single_undo is not None and self._mutation_is_available()
        )
        if self._result_base_summary:
            summary = self._result_base_summary
            if pending:
                summary += " · " + self.tr("Refreshing thumbnails…")
            self.result_summary_label.setText(summary)

    def _toggle_result_details(self) -> None:
        """Toggle the copyable details area without dismissing the result."""
        visible = not self.result_details_edit.isVisible()
        self.result_details_edit.setVisible(visible)
        self.result_details_button.setText(
            self.tr("Hide details") if visible else self.tr("Details")
        )

    def _request_result_restore(self) -> None:
        """Request recovery from the exact manifest attached to this result."""
        manifest_path = str(
            self.result_restore_button.property("manifestPath") or ""
        )
        if manifest_path:
            self.restore_requested.emit(manifest_path)

    def clear_single_undo(self) -> None:
        """Invalidate the one-step inverse after another successful write."""
        self._single_undo = None
        self.undo_button.setEnabled(False)

    def _request_single_undo(self) -> None:
        """Request a guarded inverse without sharing the canvas undo stack."""
        if self._single_undo is not None and self._mutation_is_available():
            self.undo_requested.emit(self._single_undo)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Stop accepting render results when the window closes."""
        if self._closed:
            super().closeEvent(event)
            return
        self._closed = True
        self.clear_single_undo()
        self._visible_timer.stop()
        self._reload_timer.stop()
        self._renderer.close()
        self.closed.emit()
        super().closeEvent(event)
