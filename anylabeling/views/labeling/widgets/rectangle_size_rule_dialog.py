"""Editable rule table for proactive rectangle-size validation."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Dict, Tuple

from PyQt6 import QtCore, QtWidgets

from anylabeling.views.labeling.rectangle_size.config_codec import (
    RectangleSizeConfigError,
    parse_rectangle_size_rules,
    serialize_rectangle_size_rules,
)
from anylabeling.views.labeling.rectangle_size.models import RectangleSizeRule
from anylabeling.views.labeling.utils.style import (
    get_cancel_btn_style,
    get_dialog_style,
    get_ok_btn_style,
    get_settings_combo_style,
)

_ENABLED_COLUMN = 0
_LABEL_COLUMN = 1
_WIDTH_COLUMN = 2
_HEIGHT_COLUMN = 3
_MODE_COLUMN = 4
_REMOVE_COLUMN = 5


class RectangleSizeRuleTable(QtWidgets.QWidget):
    """Edit rectangle-size rules without persisting application state."""

    rules_changed = QtCore.pyqtSignal()

    def __init__(
        self,
        rules: Iterable[RectangleSizeRule] = (),
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        """Initialize the rule editor.

        Args:
            rules: Initial validated rules.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._build_ui()
        self.set_rules(rules)

    def _build_ui(self) -> None:
        """Build the table and row-management controls."""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.table = QtWidgets.QTableWidget(0, 6, self)
        self.table.setObjectName("rectangleSizeRuleTable")
        self.table.setHorizontalHeaderLabels(
            [
                self.tr("Enabled"),
                self.tr("Label"),
                self.tr("Min width (px)"),
                self.tr("Min height (px)"),
                self.tr("Trigger"),
                self.tr("Action"),
            ]
        )
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(60)
        header.setSectionResizeMode(
            _ENABLED_COLUMN,
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents,
        )
        header.setSectionResizeMode(
            _LABEL_COLUMN,
            QtWidgets.QHeaderView.ResizeMode.Stretch,
        )
        for column in (_WIDTH_COLUMN, _HEIGHT_COLUMN, _MODE_COLUMN):
            header.setSectionResizeMode(
                column,
                QtWidgets.QHeaderView.ResizeMode.Interactive,
            )
        self.table.setColumnWidth(_WIDTH_COLUMN, 145)
        self.table.setColumnWidth(_HEIGHT_COLUMN, 145)
        self.table.setColumnWidth(_MODE_COLUMN, 190)
        header.setSectionResizeMode(
            _REMOVE_COLUMN,
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents,
        )
        self.table.setHorizontalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.table.itemChanged.connect(self.rules_changed)
        layout.addWidget(self.table, 1)

        controls = QtWidgets.QHBoxLayout()
        self.add_button = QtWidgets.QPushButton(self.tr("Add rule"), self)
        self.add_button.setObjectName("addRectangleSizeRuleButton")
        self.add_button.setStyleSheet(get_cancel_btn_style())
        self.add_button.clicked.connect(self.add_empty_rule)
        controls.addWidget(self.add_button)
        controls.addStretch(1)
        layout.addLayout(controls)

    def set_rules(self, rules: Iterable[RectangleSizeRule]) -> None:
        """Replace all rows only after the complete input validates.

        Args:
            rules: Rule models to display.

        Raises:
            RectangleSizeConfigError: If any input rule is invalid.
        """
        raw_rows = serialize_rectangle_size_rules(tuple(rules))
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(0)
            for raw_row in raw_rows:
                self._append_raw_row(raw_row)
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)
        self.rules_changed.emit()

    def rules(self) -> Tuple[RectangleSizeRule, ...]:
        """Return a validated immutable snapshot of all table rows.

        Returns:
            Current normalized rules.

        Raises:
            RectangleSizeConfigError: If any editable value is invalid.
        """
        return parse_rectangle_size_rules(
            [self._raw_row(row) for row in range(self.table.rowCount())]
        )

    def add_empty_rule(self) -> None:
        """Append an enabled rule row ready for user input."""
        self._append_raw_row(
            {
                "label": "",
                "min_width_px": None,
                "min_height_px": None,
                "trigger_mode": "any",
                "enabled": True,
            }
        )
        self.table.setCurrentCell(self.table.rowCount() - 1, _LABEL_COLUMN)
        label_editor = self.table.cellWidget(
            self.table.rowCount() - 1,
            _LABEL_COLUMN,
        )
        if label_editor is not None:
            label_editor.setFocus()
        self.rules_changed.emit()

    def remove_row(self, row: int) -> None:
        """Remove one rule row if its index exists.

        Args:
            row: Zero-based table row.
        """
        if 0 <= row < self.table.rowCount():
            self.table.removeRow(row)
            self.rules_changed.emit()

    def _append_raw_row(self, raw_rule: Dict[str, Any]) -> None:
        """Append one already-normalized or intentionally empty row."""
        row = self.table.rowCount()
        self.table.insertRow(row)

        enabled_item = QtWidgets.QTableWidgetItem()
        enabled_item.setFlags(
            QtCore.Qt.ItemFlag.ItemIsEnabled
            | QtCore.Qt.ItemFlag.ItemIsSelectable
            | QtCore.Qt.ItemFlag.ItemIsUserCheckable
        )
        enabled_item.setCheckState(
            QtCore.Qt.CheckState.Checked
            if raw_rule["enabled"]
            else QtCore.Qt.CheckState.Unchecked
        )
        enabled_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, _ENABLED_COLUMN, enabled_item)

        label_editor = QtWidgets.QLineEdit(self.table)
        label_editor.setObjectName("rectangleSizeRuleLabel")
        label_editor.setText(str(raw_rule["label"]))
        label_editor.setPlaceholderText(self.tr("Exact label"))
        label_editor.textChanged.connect(self.rules_changed)
        self.table.setCellWidget(row, _LABEL_COLUMN, label_editor)

        width_editor = self._threshold_editor(raw_rule["min_width_px"])
        height_editor = self._threshold_editor(raw_rule["min_height_px"])
        self.table.setCellWidget(row, _WIDTH_COLUMN, width_editor)
        self.table.setCellWidget(row, _HEIGHT_COLUMN, height_editor)

        mode_editor = QtWidgets.QComboBox(self.table)
        mode_editor.setObjectName("rectangleSizeRuleTrigger")
        mode_editor.addItem(self.tr("Any configured dimension"), "any")
        mode_editor.addItem(self.tr("All configured dimensions"), "all")
        mode_index = mode_editor.findData(raw_rule["trigger_mode"])
        mode_editor.setCurrentIndex(max(mode_index, 0))
        mode_editor.setStyleSheet(get_settings_combo_style())
        mode_editor.currentIndexChanged.connect(self.rules_changed)
        self.table.setCellWidget(row, _MODE_COLUMN, mode_editor)

        remove_button = QtWidgets.QPushButton(self.tr("Remove"), self.table)
        remove_button.setObjectName("removeRectangleSizeRuleButton")
        remove_button.setStyleSheet(get_cancel_btn_style())
        remove_button.clicked.connect(
            lambda _checked=False, button=remove_button: self._remove_button_row(
                button
            )
        )
        self.table.setCellWidget(row, _REMOVE_COLUMN, remove_button)
        self.table.setRowHeight(row, 38)

    def _threshold_editor(self, value: object) -> QtWidgets.QLineEdit:
        """Create one optional positive pixel-threshold editor."""
        editor = QtWidgets.QLineEdit(self.table)
        editor.setObjectName("rectangleSizeRuleThreshold")
        editor.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        editor.setPlaceholderText(self.tr("Not checked"))
        if value is not None:
            editor.setText(f"{float(value):g}")
        editor.textChanged.connect(self.rules_changed)
        return editor

    def _remove_button_row(self, button: QtWidgets.QPushButton) -> None:
        """Find and remove the current row that owns a clicked button."""
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, _REMOVE_COLUMN) is button:
                self.remove_row(row)
                return

    def _raw_row(self, row: int) -> Dict[str, Any]:
        """Read one table row into the shared config-codec shape."""
        enabled_item = self.table.item(row, _ENABLED_COLUMN)
        label_editor = self.table.cellWidget(row, _LABEL_COLUMN)
        width_editor = self.table.cellWidget(row, _WIDTH_COLUMN)
        height_editor = self.table.cellWidget(row, _HEIGHT_COLUMN)
        mode_editor = self.table.cellWidget(row, _MODE_COLUMN)
        if not isinstance(label_editor, QtWidgets.QLineEdit):
            raise RectangleSizeConfigError(
                f"Rule row {row + 1}: label editor is unavailable"
            )
        if not isinstance(width_editor, QtWidgets.QLineEdit):
            raise RectangleSizeConfigError(
                f"Rule row {row + 1}: width editor is unavailable"
            )
        if not isinstance(height_editor, QtWidgets.QLineEdit):
            raise RectangleSizeConfigError(
                f"Rule row {row + 1}: height editor is unavailable"
            )
        if not isinstance(mode_editor, QtWidgets.QComboBox):
            raise RectangleSizeConfigError(
                f"Rule row {row + 1}: trigger editor is unavailable"
            )
        return {
            "label": label_editor.text(),
            "min_width_px": width_editor.text(),
            "min_height_px": height_editor.text(),
            "trigger_mode": mode_editor.currentData(),
            "enabled": (
                enabled_item is not None
                and enabled_item.checkState() == QtCore.Qt.CheckState.Checked
            ),
        }


class RectangleSizeRuleDialog(QtWidgets.QDialog):
    """Modal editor that publishes rules only after complete validation."""

    rules_applied = QtCore.pyqtSignal(tuple)

    def __init__(
        self,
        rules: Iterable[RectangleSizeRule] = (),
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        """Initialize the standalone rule configuration dialog.

        Args:
            rules: Initial rules shown in the editor.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._accepted_rules: Tuple[RectangleSizeRule, ...] | None = None
        self.setWindowTitle(self.tr("Rectangle size rules"))
        self.setMinimumSize(940, 420)
        self.setStyleSheet(get_dialog_style())
        self._build_ui(rules)

    def _build_ui(self, rules: Iterable[RectangleSizeRule]) -> None:
        """Build dialog guidance, rule table, errors, and actions."""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        help_label = QtWidgets.QLabel(
            self.tr(
                "A rectangle is abnormal when its actual value is less than "
                "or equal to the threshold. Blank dimensions are ignored."
            ),
            self,
        )
        help_label.setObjectName("rectangleSizeRuleHelp")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        self.rule_table = RectangleSizeRuleTable(rules, self)
        self.rule_table.rules_changed.connect(self._clear_error)
        layout.addWidget(self.rule_table, 1)

        self.error_label = QtWidgets.QLabel(self)
        self.error_label.setObjectName("rectangleSizeRuleError")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #d93025;")
        self.error_label.hide()
        layout.addWidget(self.error_label)

        self.button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        ok_button = self.button_box.button(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
        )
        cancel_button = self.button_box.button(
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        ok_button.setText(self.tr("Apply"))
        ok_button.setStyleSheet(get_ok_btn_style())
        ok_button.setDefault(True)
        cancel_button.setText(self.tr("Cancel"))
        cancel_button.setStyleSheet(get_cancel_btn_style())
        self.button_box.accepted.connect(self._apply_and_accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def set_rules(self, rules: Iterable[RectangleSizeRule]) -> None:
        """Replace editor rows without changing the last accepted snapshot.

        Args:
            rules: Complete validated rule set.
        """
        self.rule_table.set_rules(rules)
        self._clear_error()

    def rules(self) -> Tuple[RectangleSizeRule, ...]:
        """Return the current validated editor snapshot."""
        return self.rule_table.rules()

    @property
    def accepted_rules(self) -> Tuple[RectangleSizeRule, ...] | None:
        """Return the last snapshot accepted by this dialog instance."""
        return self._accepted_rules

    def _apply_and_accept(self) -> None:
        """Validate all rows, emit once, and close only on success."""
        try:
            rules = self.rules()
        except RectangleSizeConfigError as exc:
            self.error_label.setText(
                self.tr("Cannot apply rules: {0}").format(
                    self._localized_config_error(exc)
                )
            )
            self.error_label.show()
            return
        self._accepted_rules = rules
        self.rules_applied.emit(rules)
        self.accept()

    def _localized_config_error(
        self,
        error: RectangleSizeConfigError,
    ) -> str:
        """Format shared parser metadata in the active UI language.

        Args:
            error: Structured configuration error from the pure codec.

        Returns:
            Localized user-facing feedback with an optional one-based row.
        """
        if error.code == "empty_label":
            message = self.tr("Label must not be empty.")
        elif error.code == "duplicate_label":
            message = self.tr("The label '{0}' is duplicated.").format(
                error.details.get("label", "")
            )
        elif error.code == "invalid_threshold":
            if error.field_name == "min_width_px":
                message = self.tr(
                    "Width threshold must be a positive finite number."
                )
            else:
                message = self.tr(
                    "Height threshold must be a positive finite number."
                )
        elif error.code == "missing_threshold":
            message = self.tr(
                "An enabled rule needs at least one W/H threshold."
            )
        elif error.code == "invalid_trigger_mode":
            message = self.tr("Trigger must be 'any' or 'all'.")
        else:
            message = str(error)
        if error.row_index is None:
            return message
        return self.tr("Rule row {0}: {1}").format(
            error.row_index + 1,
            message,
        )

    def _clear_error(self) -> None:
        """Hide stale validation feedback after the editor changes."""
        self.error_label.clear()
        self.error_label.hide()


__all__ = ["RectangleSizeRuleDialog", "RectangleSizeRuleTable"]
