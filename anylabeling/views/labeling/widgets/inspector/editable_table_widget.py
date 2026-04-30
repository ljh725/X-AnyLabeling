"""
Editable Table Widget — QTableView-based shape data editor.

Phase 2 features:
- Display all shapes for the current file in a sortable table.
- In-place editing of label, group_id, description.
- Bidirectional sync: table edits → shape updates → canvas redraw.

Architecture:
    EditableTableWidget (QWidget)
      └── QTableView
            └── EditableTableModel (QAbstractTableModel)
                  Backed by FlattenedRecord list + edit callback.

Signals:
    shape_clicked(file_path: str, shape_index: int)
    shape_double_clicked(file_path: str, shape_index: int)
"""

import logging
from typing import Any, Callable, Dict, List, Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, QModelIndex

from .flat_index import FlattenedRecord

logger = logging.getLogger(__name__)

# ── Column definitions ──────────────────────────────────────────
# Each tuple: (header_text, field_name, editable)
_COLUMNS = [
    ("#", "shape_index", False),
    ("Label", "label", True),
    ("Group ID", "group_id", True),
    ("Type", "shape_type", False),
    ("Description", "description", True),
]

_COL_COUNT = len(_COLUMNS)


# ---------------------------------------------------------------------------
# EditableTableModel
# ---------------------------------------------------------------------------

class EditableTableModel(QtCore.QAbstractTableModel):
    """Table model backed by FlattenedRecord list.

    Editing delegates to an external callback so the parent widget can
    modify the actual Shape object, mark the file dirty, and redraw.

    Signals (via edit_callback):
        callback(file_path, shape_index, field, value) -> None
    """

    def __init__(self, parent: Optional[QtCore.QObject] = None):
        super().__init__(parent)
        self._records: List[FlattenedRecord] = []
        self._edit_callback: Optional[
            Callable[[str, int, str, Any], None]
        ] = None

    def set_records(
        self, records: List[FlattenedRecord]
    ) -> None:
        """Replace all records (triggers model reset)."""
        self.beginResetModel()
        self._records = list(records)
        self.endResetModel()

    def set_edit_callback(
        self,
        callback: Optional[Callable[[str, int, str, Any], None]],
    ) -> None:
        """Register the callback invoked when the user edits a cell."""
        self._edit_callback = callback

    # ── QAbstractTableModel interface ────────────────────────────

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._records)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return _COL_COUNT

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < _COL_COUNT:
                return _COLUMNS[section][0]
        return None

    def data(
        self,
        index: QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if not index.isValid():
            return None
        row = index.row()
        if not (0 <= row < len(self._records)):
            return None
        rec = self._records[row]
        field = _COLUMNS[index.column()][1]

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return self._display_value(rec, field)

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if field in ("shape_index", "group_id"):
                return Qt.AlignmentFlag.AlignCenter

        if role == Qt.ItemDataRole.UserRole:
            return rec

        return None

    def setData(
        self,
        index: QModelIndex,
        value,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        if self._edit_callback is None:
            return False

        rec = self._records[index.row()]
        field = _COLUMNS[index.column()][1]
        try:
            self._edit_callback(rec.file_path, rec.shape_index, field, value)
            return True
        except Exception:
            logger.error(
                "Edit failed: file=%s idx=%d field=%s",
                rec.file_path, rec.shape_index, field,
                exc_info=True,
            )
            return False

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        flags = super().flags(index)
        if not index.isValid():
            return flags
        if _COLUMNS[index.column()][2]:  # editable?
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    # ── helpers ──────────────────────────────────────────────────

    @staticmethod
    def _display_value(rec: FlattenedRecord, field: str) -> str:
        if field == "shape_index":
            return str(rec.shape_index)
        if field == "label":
            return rec.label
        if field == "group_id":
            return str(rec.group_id) if rec.group_id is not None else ""
        if field == "shape_type":
            return rec.shape_type
        if field == "description":
            return rec.description
        return ""


# ---------------------------------------------------------------------------
# EditableTableWidget
# ---------------------------------------------------------------------------

class EditableTableWidget(QtWidgets.QWidget):
    """QTableView-based shape data table with click-to-navigate."""

    shape_clicked = QtCore.pyqtSignal(str, int)        # file_path, shape_index
    shape_double_clicked = QtCore.pyqtSignal(str, int)  # file_path, shape_index

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self._model = EditableTableModel(self)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # ── header ───────────────────────────────────────────────
        header_layout = QtWidgets.QHBoxLayout()
        self.title_label = QtWidgets.QLabel("数据表格")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 11pt;")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        self.record_count_label = QtWidgets.QLabel("")
        self.record_count_label.setStyleSheet("color: #888; font-size: 9pt;")
        header_layout.addWidget(self.record_count_label)
        layout.addLayout(header_layout)

        # ── table view ───────────────────────────────────────────
        self._table_view = QtWidgets.QTableView()
        self._table_view.setModel(self._model)
        self._table_view.setAlternatingRowColors(True)
        self._table_view.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table_view.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self._table_view.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
            | QtWidgets.QAbstractItemView.EditTrigger.SelectedClicked
            | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self._table_view.setSortingEnabled(False)
        self._table_view.verticalHeader().setVisible(False)
        self._table_view.horizontalHeader().setStretchLastSection(True)
        self._table_view.setShowGrid(True)

        # Click navigation (imitates IssueListWidget behaviour)
        self._table_view.clicked.connect(self._on_clicked)
        self._table_view.doubleClicked.connect(self._on_double_clicked)

        layout.addWidget(self._table_view)

    def populate(self, records: List[FlattenedRecord]) -> None:
        """Replace the table contents."""
        self._model.set_records(records)
        self.record_count_label.setText(f"{len(records)} 条记录")
        self._table_view.resizeColumnsToContents()

    def clear_results(self) -> None:
        """Reset to empty state."""
        self._model.set_records([])
        self.record_count_label.setText("")

    @property
    def model(self) -> EditableTableModel:
        return self._model

    def set_edit_callback(
        self,
        callback: Optional[Callable[[str, int, str, Any], None]],
    ) -> None:
        self._model.set_edit_callback(callback)

    # ── event handlers ───────────────────────────────────────────

    def _on_clicked(self, index: QModelIndex) -> None:
        rec = self._model.data(index, Qt.ItemDataRole.UserRole)
        if isinstance(rec, FlattenedRecord) and rec.shape_index >= 0:
            self.shape_clicked.emit(rec.file_path, rec.shape_index)

    def _on_double_clicked(self, index: QModelIndex) -> None:
        rec = self._model.data(index, Qt.ItemDataRole.UserRole)
        if isinstance(rec, FlattenedRecord) and rec.shape_index >= 0:
            self.shape_double_clicked.emit(rec.file_path, rec.shape_index)
