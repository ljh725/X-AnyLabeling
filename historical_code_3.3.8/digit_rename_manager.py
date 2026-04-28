"""
Digit Rename Manager Module

This module provides functionality for managing digit-based relabeling shortcuts.
Users can assign labels to digit keys 0-9 and quickly relabel selected shapes
by pressing the corresponding digit key while in edit mode.

Classes:
    - DigitRenameManager: Core logic for digit rename operations
    - DigitRenameShortcutDialog: UI dialog for configuring digit-label mappings
"""

from typing import Dict, List, Optional, Callable, Any
import html

from PyQt5 import QtCore, QtGui, QtWidgets

from .popup import Popup


# Constants
LABEL_OPACITY = 128


class DigitRenameManager:
    """
    Manager class for digit-based relabeling operations.
    
    This class encapsulates the core logic for:
    - Loading and normalizing rename shortcuts from config
    - Triggering rename operations based on digit key presses
    - Applying label changes to selected shapes
    
    Attributes:
        rename_shortcuts: Dict mapping digit keys (0-9) to label configurations
    """
    
    def __init__(
        self,
        config: Dict[str, Any],
        canvas_getter: Callable[[], Any],
        label_list_getter: Callable[[], Any],
        unique_label_list_getter: Callable[[], Any],
        label_dialog_getter: Callable[[], Any],
        status_callback: Callable[[str, int], None],
        set_dirty_callback: Callable[[], None],
        update_shape_color_callback: Callable[[Any], None],
        get_rgb_by_label_callback: Callable[[str], tuple],
        update_combo_box_callback: Callable[[], None],
        update_gid_box_callback: Callable[[], None],
        tr_callback: Callable[[str], str],
    ):
        """
        Initialize the DigitRenameManager.
        
        Args:
            config: Application configuration dictionary
            canvas_getter: Callable that returns the canvas object
            label_list_getter: Callable that returns the label list widget
            unique_label_list_getter: Callable that returns the unique label list widget
            label_dialog_getter: Callable that returns the label dialog
            status_callback: Callable for displaying status messages
            set_dirty_callback: Callable to mark file as modified
            update_shape_color_callback: Callable to update shape color
            get_rgb_by_label_callback: Callable to get RGB color for a label
            update_combo_box_callback: Callable to update combo box
            update_gid_box_callback: Callable to update GID box
            tr_callback: Callable for translation
        """
        self._config = config
        self._canvas_getter = canvas_getter
        self._label_list_getter = label_list_getter
        self._unique_label_list_getter = unique_label_list_getter
        self._label_dialog_getter = label_dialog_getter
        self._status = status_callback
        self._set_dirty = set_dirty_callback
        self._update_shape_color = update_shape_color_callback
        self._get_rgb_by_label = get_rgb_by_label_callback
        self._update_combo_box = update_combo_box_callback
        self._update_gid_box = update_gid_box_callback
        self._tr = tr_callback
        
        # Initialize rename shortcuts from config
        self.rename_shortcuts = self._load_rename_shortcuts()
        
    def _load_rename_shortcuts(self) -> Dict[int, Dict[str, str]]:
        """
        Load and normalize rename shortcuts from configuration.
        
        Returns:
            Normalized dictionary mapping digit keys to label configurations
        """
        raw_shortcuts = self._config.get("rename_shortcuts", {})
        normalized = {}
        
        if not isinstance(raw_shortcuts, dict):
            return normalized
            
        for key, value in raw_shortcuts.items():
            try:
                normalized_key = int(key)
            except (TypeError, ValueError):
                continue
                
            label_value = ""
            if isinstance(value, dict):
                label_value = value.get("label", "") or ""
            elif value is not None:
                label_value = str(value)
                
            if label_value:
                normalized[normalized_key] = {"label": label_value}
                
        # Sync back to config
        self._config["rename_shortcuts"] = normalized
        return normalized
    
    def is_rename_mode_active(self) -> bool:
        """
        Check if rename mode should be active.
        
        Returns:
            True if canvas is in editing mode and has selected shapes
        """
        canvas = self._canvas_getter()
        return (
            canvas.editing()
            and getattr(canvas, "selected_shapes", None)
            and len(canvas.selected_shapes) > 0
        )
    
    def trigger_rename(self, digit_num: int) -> bool:
        """
        Trigger rename operation for the given digit key.
        
        Args:
            digit_num: The digit key pressed (0-9)
            
        Returns:
            True if rename was attempted (regardless of success), False otherwise
        """
        mapping = self.rename_shortcuts.get(digit_num)
        rename_label = self._extract_label(mapping)
        
        if not rename_label:
            self._show_no_mapping_message(digit_num)
            return True  # Rename was attempted but no mapping found
            
        self._apply_rename(rename_label)
        return True
    
    def _extract_label(self, mapping: Optional[Dict[str, str]]) -> str:
        """
        Extract and validate label from mapping.
        
        Args:
            mapping: The mapping dictionary or None
            
        Returns:
            Stripped label string or empty string if invalid
        """
        if not mapping:
            return ""
        return (mapping.get("label", "") or "").strip()
    
    def _show_no_mapping_message(self, digit_num: int) -> None:
        """
        Display status message when no mapping is configured for a digit key.
        
        Args:
            digit_num: The digit key that has no mapping
        """
        message = self._tr(
            "No relabel mapping set for key {digit}. "
            "Please configure the mapping in Digit Relabel Manager."
        ).format(digit=digit_num)
        self._status(message, 2000)
    
    def _apply_rename(self, rename_label: str) -> None:
        """
        Apply rename operation to all selected shapes.
        
        Args:
            rename_label: The new label to apply
        """
        canvas = self._canvas_getter()
        shapes = list(getattr(canvas, "selected_shapes", []) or [])
        
        if not shapes:
            self._status(self._tr("No shapes selected for relabel."), 2000)
            return
            
        updated_count = 0
        label_list = self._label_list_getter()
        
        for shape in shapes:
            shape.label = rename_label
            self._update_shape_color(shape)
            
            item = label_list.find_item_by_shape(shape)
            if item is not None:
                if shape.group_id is None:
                    color = shape.fill_color.getRgb()[:3]
                    item.setText("{}".format(html.escape(shape.label)))
                    item.setBackground(QtGui.QColor(*color, LABEL_OPACITY))
                else:
                    item.setText(f"{shape.label} ({shape.group_id})")
            updated_count += 1
            
        # Update label history
        label_dialog = self._label_dialog_getter()
        label_dialog.add_label_history(rename_label)
        
        # Update unique label list if needed
        unique_label_list = self._unique_label_list_getter()
        if not unique_label_list.find_items_by_label(rename_label):
            unique_label_item = unique_label_list.create_item_from_label(rename_label)
            unique_label_list.addItem(unique_label_item)
            rgb = self._get_rgb_by_label(rename_label)
            unique_label_list.set_item_label(
                unique_label_item, rename_label, rgb, LABEL_OPACITY
            )
            
        # Mark as dirty and update UI
        self._set_dirty()
        self._update_combo_box()
        self._update_gid_box()
        
        self._status(
            self._tr("Relabeled {count} shape(s) to '{label}'").format(
                count=updated_count, label=rename_label
            ),
            2000,
        )
    
    def update_shortcuts(self, new_shortcuts: Dict[int, Dict[str, str]]) -> None:
        """
        Update rename shortcuts and sync to config.
        
        Args:
            new_shortcuts: New mapping dictionary
        """
        self.rename_shortcuts = new_shortcuts
        self._config["rename_shortcuts"] = new_shortcuts


class DigitRenameShortcutDialog(QtWidgets.QDialog):
    """
    Dialog for managing digit relabel shortcuts (single page 0-9).
    
    This dialog allows users to configure which label should be applied
    when pressing each digit key (0-9) while shapes are selected.
    """
    
    PAGE_SIZE = 10
    
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        """
        Initialize the dialog.
        
        Args:
            parent: Parent widget (typically LabelingWidget)
        """
        super().__init__(parent)
        
        self._parent = parent
        self.rename_shortcuts: Dict[int, Dict[str, str]] = {}
        
        # Load existing shortcuts from parent
        self._load_from_parent()
        
        # Setup UI
        self._setup_window()
        self._setup_styles()
        self._setup_layout()
        
        # Initialize table content
        self._update_table()
        self._move_to_center()
    
    def _load_from_parent(self) -> None:
        """Load existing rename shortcuts from parent widget."""
        if not hasattr(self._parent, "digit_rename_manager"):
            # Fallback to direct attribute access for backward compatibility
            if hasattr(self._parent, "rename_digit_shortcuts"):
                source = self._parent.rename_digit_shortcuts
            else:
                return
        else:
            source = self._parent.digit_rename_manager.rename_shortcuts
            
        if source is None:
            return
            
        for key, value in source.items():
            try:
                normalized_key = int(key)
            except (TypeError, ValueError):
                continue
                
            label_value = ""
            if isinstance(value, dict):
                label_value = value.get("label", "") or ""
            else:
                label_value = str(value)
            self.rename_shortcuts[normalized_key] = {"label": label_value}
    
    def _setup_window(self) -> None:
        """Configure window properties."""
        self.setWindowTitle(self.tr("Digit Relabel Manager"))
        self.setModal(True)
        self.setMinimumSize(420, 360)
        self.setWindowFlags(
            self.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint
        )
    
    def _setup_styles(self) -> None:
        """Apply stylesheet to the dialog."""
        self.setStyleSheet(
            """
            QDialog {
                background-color: #f5f5f7;
                border-radius: 10px;
            }
            QLabel {
                color: #1d1d1f;
                font-size: 13px;
            }
            QLineEdit {
                padding: 2px 6px;
                background: white;
                border: 1px solid #d2d2d7;
                border-radius: 4px;
                min-height: 22px;
                selection-background-color: #0071e3;
            }
            QHeaderView::section {
                background-color: #f0f0f0;
                padding: 6px;
                border: 1px solid #d2d2d7;
                font-weight: bold;
            }
            """
        )
    
    def _setup_layout(self) -> None:
        """Create and configure the dialog layout."""
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        # Header
        header_label = QtWidgets.QLabel(
            self.tr("Configure relabel mappings for digit keys 0-9 (single page).")
        )
        header_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(header_label)
        
        # Table
        self._table = self._create_table()
        layout.addWidget(self._table)
        
        # Buttons
        button_layout = self._create_button_layout()
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def _create_table(self) -> QtWidgets.QTableWidget:
        """Create and configure the mapping table."""
        table = QtWidgets.QTableWidget()
        table.setColumnCount(2)
        table.setRowCount(self.PAGE_SIZE)
        table.setHorizontalHeaderLabels([self.tr("Digit"), self.tr("Label")])
        table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeToContents
        )
        table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.Stretch
        )
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        
        for row in range(self.PAGE_SIZE):
            # Digit column (read-only)
            digit_item = QtWidgets.QTableWidgetItem()
            digit_item.setTextAlignment(QtCore.Qt.AlignCenter)
            digit_item.setFlags(digit_item.flags() ^ QtCore.Qt.ItemIsEditable)
            digit_item.setText(str(row))
            table.setItem(row, 0, digit_item)
            
            # Label column (editable)
            label_edit = QtWidgets.QLineEdit()
            label_edit.setPlaceholderText(self.tr("Enter label"))
            label_edit.textChanged.connect(
                lambda text, index=row: self._on_label_changed(index, text)
            )
            table.setCellWidget(row, 1, label_edit)
            
        return table
    
    def _create_button_layout(self) -> QtWidgets.QHBoxLayout:
        """Create the button layout."""
        layout = QtWidgets.QHBoxLayout()
        layout.setSpacing(8)
        
        # Reset button
        reset_button = self._create_button(
            self.tr("Reset"),
            self._on_reset,
            primary=False
        )
        
        # Cancel button
        cancel_button = self._create_button(
            self.tr("Cancel"),
            self.reject,
            primary=False
        )
        
        # OK button
        ok_button = self._create_button(
            self.tr("OK"),
            self._on_save,
            primary=True
        )
        
        layout.addWidget(reset_button)
        layout.addStretch()
        layout.addWidget(cancel_button)
        layout.addWidget(ok_button)
        
        return layout
    
    def _create_button(
        self,
        text: str,
        callback: Callable,
        primary: bool = False
    ) -> QtWidgets.QPushButton:
        """Create a styled button."""
        button = QtWidgets.QPushButton(text)
        button.setFixedSize(100, 32)
        button.clicked.connect(callback)
        
        if primary:
            button.setStyleSheet(
                """
                QPushButton {
                    background-color: #0071e3;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-weight: 500;
                }
                QPushButton:hover {
                    background-color: #0077ED;
                }
                QPushButton:pressed {
                    background-color: #0068D0;
                }
                """
            )
        else:
            button.setStyleSheet(
                """
                QPushButton {
                    background-color: #f5f5f7;
                    color: #1d1d1f;
                    border: 1px solid #d2d2d7;
                    border-radius: 6px;
                    font-weight: 500;
                }
                QPushButton:hover {
                    background-color: #e5e5e5;
                }
                QPushButton:pressed {
                    background-color: #d5d5d5;
                }
                """
            )
        return button
    
    def _update_table(self) -> None:
        """Update table content from current shortcuts."""
        for row in range(self.PAGE_SIZE):
            label_edit = self._table.cellWidget(row, 1)
            if label_edit is None:
                continue
                
            label_edit.blockSignals(True)
            data = self.rename_shortcuts.get(row)
            text = data.get("label", "") if data else ""
            label_edit.setText(text)
            label_edit.blockSignals(False)
    
    def _on_label_changed(self, index: int, text: str) -> None:
        """Handle label text change."""
        text = (text or "").strip()
        if text:
            self.rename_shortcuts[index] = {"label": text}
        else:
            self.rename_shortcuts.pop(index, None)
    
    def _on_reset(self) -> None:
        """Handle reset button click."""
        confirm = QtWidgets.QMessageBox.warning(
            self,
            self.tr("Confirm Reset"),
            self.tr(
                "Are you sure you want to clear all relabel mappings? "
                "This cannot be undone."
            ),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        
        if confirm == QtWidgets.QMessageBox.Yes:
            self.rename_shortcuts.clear()
            self._update_table()
    
    def _on_save(self) -> None:
        """Handle save button click."""
        # Collect current values from table
        result = {}
        for row in range(self.PAGE_SIZE):
            label_edit = self._table.cellWidget(row, 1)
            if label_edit is None:
                continue
            text = label_edit.text().strip()
            if text:
                result[row] = {"label": text}
        
        self.rename_shortcuts = result
        
        # Update parent's manager or direct attribute
        if hasattr(self._parent, "digit_rename_manager"):
            self._parent.digit_rename_manager.update_shortcuts(result)
        elif hasattr(self._parent, "rename_digit_shortcuts"):
            self._parent.rename_digit_shortcuts = result
            
        if hasattr(self._parent, "_config") and isinstance(self._parent._config, dict):
            self._parent._config["rename_shortcuts"] = result
        
        self.accept()
        
        # Show success popup (lazy import to avoid circular dependency)
        from ..utils.qt import new_icon_path
        popup = Popup(
            self.tr("Digit relabel shortcuts saved successfully"),
            self._parent,
            msec=1000,
            icon=new_icon_path("copy-green", "svg"),
        )
        popup.show_popup(self._parent)
    
    def _move_to_center(self) -> None:
        """Center the dialog on screen."""
        screen = QtWidgets.QApplication.desktop().screenGeometry()
        size = self.geometry()
        self.move(
            (screen.width() - size.width()) // 2,
            (screen.height() - size.height()) // 2,
        )
