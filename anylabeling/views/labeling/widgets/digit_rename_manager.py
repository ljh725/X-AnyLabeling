import html
from typing import Dict, Optional

from PyQt6 import QtCore, QtGui, QtWidgets

from ..utils.qt import new_icon_path
from ..utils.style import (
    get_cancel_btn_style,
    get_dialog_style,
    get_ok_btn_style,
)
from .popup import Popup

LABEL_OPACITY = 128


class _CellLineEdit(QtWidgets.QLineEdit):
    """QLineEdit subclass that intercepts Enter/Return to prevent
    the parent QDialog from auto-accepting when the user presses Enter
    inside a table cell.  Instead, focus moves to the next row."""

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() in (
            QtCore.Qt.Key.Key_Return,
            QtCore.Qt.Key.Key_Enter,
        ):
            table = self.parent()
            if isinstance(table, QtWidgets.QTableWidget):
                row = table.indexAt(self.pos()).row()
                next_row = (row + 1) % table.rowCount()
                next_widget = table.cellWidget(next_row, 1)
                if next_widget is not None:
                    next_widget.setFocus()
                    next_widget.selectAll()
            event.accept()
            return
        super().keyPressEvent(event)


class DigitRenameManager:
    """Manage digit-based relabel shortcuts for selected shapes."""

    def __init__(self, label_widget: QtWidgets.QWidget) -> None:
        """Initialize the manager.

        Args:
            label_widget: The main labeling widget instance.
        """
        self._label_widget = label_widget
        self.rename_shortcuts = self._load_rename_shortcuts()

    def _load_rename_shortcuts(self) -> Dict[int, Dict[str, str]]:
        """Load and normalize digit relabel shortcuts from config."""
        raw_shortcuts = self._label_widget._config.get("rename_shortcuts", {})
        normalized = {}

        if not isinstance(raw_shortcuts, dict):
            self._label_widget._config["rename_shortcuts"] = normalized
            return normalized

        for key, value in raw_shortcuts.items():
            try:
                digit_key = int(key)
            except (TypeError, ValueError):
                continue

            if not 0 <= digit_key <= 9:
                continue

            label_value = ""
            if isinstance(value, dict):
                label_value = value.get("label", "") or ""
            elif value is not None:
                label_value = str(value)

            label_value = label_value.strip()
            if label_value:
                normalized[digit_key] = {"label": label_value}

        self._label_widget._config["rename_shortcuts"] = normalized
        return normalized

    def is_rename_mode_active(self) -> bool:
        """Return whether digit relabel should handle key presses."""
        canvas = self._label_widget.canvas
        selected_shapes = getattr(canvas, "selected_shapes", []) or []
        return canvas.editing() and len(selected_shapes) > 0

    def trigger_rename(self, digit_num: int) -> bool:
        """Handle a digit key press in rename mode.

        Args:
            digit_num: Pressed digit key in the range 0-9.

        Returns:
            True when the rename path handled the key press.
        """
        mapping = self.rename_shortcuts.get(digit_num)
        rename_label = self._extract_label(mapping)

        if not rename_label:
            message = self._label_widget.tr(
                "按键 {digit} 未设置重命名映射，"
                "请在数字快捷重命名管理器中配置"
            ).format(digit=digit_num)
            self._label_widget.status(message, 2000)
            return True

        self._apply_rename(rename_label)
        return True

    def _extract_label(self, mapping: Optional[Dict[str, str]]) -> str:
        """Extract a normalized label string from a mapping entry."""
        if not mapping:
            return ""
        return (mapping.get("label", "") or "").strip()

    def _apply_rename(self, rename_label: str) -> None:
        """Apply a relabel operation to all selected shapes."""
        label_widget = self._label_widget
        shapes = list(
            getattr(label_widget.canvas, "selected_shapes", []) or []
        )

        if not shapes:
            label_widget.status(label_widget.tr("未选中任何标注对象"), 2000)
            return

        if not label_widget.validate_label(rename_label):
            label_widget.status(
                label_widget.tr(
                    "标签 '{label}' 无效，验证类型为 '{type}'"
                ).format(
                    label=rename_label,
                    type=label_widget._config["validate_label"],
                ),
                3000,
            )
            return

        label_widget.canvas.store_shapes()

        updated_count = 0
        for shape in shapes:
            shape.label = rename_label
            label_widget._update_shape_color(shape)

            item = label_widget.label_list.find_item_by_shape(shape)
            if item is not None:
                if shape.group_id is None:
                    color = shape.fill_color.getRgb()[:3]
                    item.setText("{}".format(html.escape(shape.label)))
                    item.setBackground(QtGui.QColor(*color, LABEL_OPACITY))
                else:
                    item.setText(f"{shape.label} ({shape.group_id})")
            updated_count += 1

        label_widget.label_dialog.add_label_history(rename_label)

        if not label_widget.unique_label_list.find_items_by_label(
            rename_label
        ):
            unique_label_item = (
                label_widget.unique_label_list.create_item_from_label(
                    rename_label
                )
            )
            label_widget.unique_label_list.addItem(unique_label_item)
            rgb = label_widget._get_rgb_by_label(rename_label)
            label_widget.unique_label_list.set_item_label(
                unique_label_item,
                rename_label,
                rgb,
                LABEL_OPACITY,
            )

        label_widget.set_dirty()
        label_widget._refresh_shape_filters()

        if len(shapes) == 1:
            try:
                selected_idx = label_widget.canvas.shapes.index(shapes[0])
                label_widget.update_attributes(selected_idx)
            except ValueError:
                pass

        label_widget.status(
            label_widget.tr("已将 {count} 个对象重命名为 '{label}'").format(
                count=updated_count,
                label=rename_label,
            ),
            2000,
        )

    def update_shortcuts(
        self, new_shortcuts: Dict[int, Dict[str, str]]
    ) -> None:
        """Replace configured relabel shortcuts and sync them to config."""
        self.rename_shortcuts = new_shortcuts
        self._label_widget._config["rename_shortcuts"] = new_shortcuts


class DigitRenameShortcutDialog(QtWidgets.QDialog):
    """Dialog for configuring digit relabel shortcuts."""

    PAGE_SIZE = 10
    _ROW_HEIGHT = 32

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        """Initialize the dialog.

        Args:
            parent: The parent labeling widget.
        """
        super().__init__(parent)
        self._parent = parent
        self.rename_shortcuts: Dict[int, Dict[str, str]] = {}

        self._load_from_parent()
        self._build_ui()
        self._update_table()

    def _load_from_parent(self) -> None:
        """Load existing relabel mappings from the parent widget."""
        manager = getattr(self._parent, "digit_rename_manager", None)
        if manager is None:
            return

        source = manager.rename_shortcuts or {}
        for key, value in source.items():
            try:
                normalized_key = int(key)
            except (TypeError, ValueError):
                continue

            if not 0 <= normalized_key <= 9:
                continue

            label_value = ""
            if isinstance(value, dict):
                label_value = value.get("label", "") or ""
            elif value is not None:
                label_value = str(value)

            label_value = label_value.strip()
            if label_value:
                self.rename_shortcuts[normalized_key] = {"label": label_value}

    def _build_ui(self) -> None:
        """Create the dialog UI."""
        self.setWindowTitle(self.tr("数字快捷重命名管理器"))
        self.setModal(True)
        self.setWindowFlags(
            self.windowFlags()
            & ~QtCore.Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setStyleSheet(get_dialog_style())

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        header_label = QtWidgets.QLabel(
            self.tr("编辑选中对象时，使用数字键 0-9 快速重命名标签")
        )
        header_label.setWordWrap(True)
        layout.addWidget(header_label)

        self._table = QtWidgets.QTableWidget(self.PAGE_SIZE, 2, self)
        self._table.setHorizontalHeaderLabels(
            [self.tr("数字键"), self.tr("标签")]
        )
        self._table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.NoSelection
        )
        self._table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setHorizontalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self._table.horizontalHeader().setSectionResizeMode(
            0,
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents,
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1,
            QtWidgets.QHeaderView.ResizeMode.Stretch,
        )

        for row in range(self.PAGE_SIZE):
            self._table.setRowHeight(row, self._ROW_HEIGHT)

            digit_item = QtWidgets.QTableWidgetItem(str(row))
            digit_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            digit_item.setFlags(
                digit_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable
            )
            self._table.setItem(row, 0, digit_item)

            label_edit = _CellLineEdit(self)
            label_edit.setPlaceholderText(self.tr("输入标签"))
            label_edit.textChanged.connect(
                lambda text, index=row: self._on_label_changed(index, text)
            )
            self._table.setCellWidget(row, 1, label_edit)

        layout.addWidget(self._table)

        button_layout = QtWidgets.QHBoxLayout()
        reset_button = QtWidgets.QPushButton(self.tr("重置"))
        reset_button.setStyleSheet(get_cancel_btn_style())
        reset_button.clicked.connect(self._on_reset)

        cancel_button = QtWidgets.QPushButton(self.tr("取消"))
        cancel_button.setStyleSheet(get_cancel_btn_style())
        cancel_button.setAutoDefault(False)
        cancel_button.setDefault(False)
        cancel_button.clicked.connect(self.reject)

        ok_button = QtWidgets.QPushButton(self.tr("确定"))
        ok_button.setStyleSheet(get_ok_btn_style())
        ok_button.setAutoDefault(False)
        ok_button.setDefault(False)
        ok_button.clicked.connect(self._on_save)

        button_layout.addWidget(reset_button)
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(ok_button)
        layout.addLayout(button_layout)

    def _update_table(self) -> None:
        """Update input widgets from current shortcut mappings."""
        for row in range(self.PAGE_SIZE):
            label_edit = self._table.cellWidget(row, 1)
            if label_edit is None:
                continue

            label_edit.blockSignals(True)
            data = self.rename_shortcuts.get(row)
            label_edit.setText(data.get("label", "") if data else "")
            label_edit.blockSignals(False)

    def _on_label_changed(self, index: int, text: str) -> None:
        """Update the in-memory mapping when a label field changes."""
        text = (text or "").strip()
        if text:
            self.rename_shortcuts[index] = {"label": text}
        else:
            self.rename_shortcuts.pop(index, None)

    def _on_reset(self) -> None:
        """Clear all configured relabel mappings after confirmation."""
        confirm = QtWidgets.QMessageBox.warning(
            self,
            self.tr("确认重置"),
            self.tr("确定要清空所有快捷重命名映射吗？此操作不可撤销。"),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )

        if confirm == QtWidgets.QMessageBox.StandardButton.Yes:
            self.rename_shortcuts.clear()
            self._update_table()

    def _on_save(self) -> None:
        """Persist the configured relabel mappings to the parent widget."""
        result = {}
        for row in range(self.PAGE_SIZE):
            label_edit = self._table.cellWidget(row, 1)
            if label_edit is None:
                continue

            text = label_edit.text().strip()
            if text:
                result[row] = {"label": text}

        self.rename_shortcuts = result

        manager = getattr(self._parent, "digit_rename_manager", None)
        if manager is not None:
            manager.update_shortcuts(result)

        if hasattr(self._parent, "_config") and isinstance(
            self._parent._config, dict
        ):
            self._parent._config["rename_shortcuts"] = result

        self.accept()

        popup = Popup(
            self.tr("数字快捷重命名映射已保存"),
            self._parent,
            msec=1000,
            icon=new_icon_path("copy-green", "svg"),
        )
        popup.show_popup(self._parent)
