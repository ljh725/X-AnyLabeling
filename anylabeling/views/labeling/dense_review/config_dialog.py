"""Editor for optional confusion batches, class rules and grid settings."""

from __future__ import annotations

from typing import Iterable, Optional

from PyQt6 import QtCore, QtWidgets

from anylabeling.services.dense_review.models import (
    BOX_RULE_LABELS,
    BOX_RULE_VALUES,
    BatchDefinition,
    CoverageSettings,
    LabelRule,
    ReviewConfig,
    ReviewRules,
)


class DenseReviewConfigDialog(QtWidgets.QDialog):
    """Edit the local review configuration before or during a round."""

    def __init__(
        self,
        labels: Iterable[str],
        config: Optional[ReviewConfig] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._labels = sorted(
            {str(label) for label in labels if str(label)}
            | set((config or ReviewConfig()).rules.rules)
        )
        self._initial = (config or ReviewConfig()).normalized()
        self.setWindowTitle(self.tr("Dense Review Configuration"))
        self.resize(780, 620)
        self._build_ui()
        self._load(self._initial)

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        batch_group = QtWidgets.QGroupBox(
            self.tr("Confusion batches (a label may appear in only one)")
        )
        batch_layout = QtWidgets.QVBoxLayout(batch_group)
        self.batch_table = QtWidgets.QTableWidget(0, 2)
        self.batch_table.setHorizontalHeaderLabels(
            [self.tr("Batch name"), self.tr("Labels (comma separated)")]
        )
        self.batch_table.horizontalHeader().setStretchLastSection(True)
        self.batch_table.verticalHeader().setVisible(False)
        batch_layout.addWidget(self.batch_table, 1)
        batch_buttons = QtWidgets.QHBoxLayout()
        self.add_batch_button = QtWidgets.QPushButton(self.tr("Add batch"))
        self.remove_batch_button = QtWidgets.QPushButton(
            self.tr("Remove selected batch")
        )
        batch_buttons.addWidget(self.add_batch_button)
        batch_buttons.addWidget(self.remove_batch_button)
        batch_buttons.addStretch(1)
        batch_layout.addLayout(batch_buttons)
        layout.addWidget(batch_group, 1)

        rules_group = QtWidgets.QGroupBox(
            self.tr("Class rules (unknown rules stay conservative)")
        )
        rules_layout = QtWidgets.QVBoxLayout(rules_group)
        self.rule_table = QtWidgets.QTableWidget(0, 3)
        self.rule_table.setHorizontalHeaderLabels(
            [
                self.tr("Label"),
                self.tr("Box rule"),
                self.tr("Category note"),
            ]
        )
        self.rule_table.horizontalHeader().setStretchLastSection(True)
        self.rule_table.verticalHeader().setVisible(False)
        rules_layout.addWidget(self.rule_table, 1)
        rule_buttons = QtWidgets.QHBoxLayout()
        self.add_rule_button = QtWidgets.QPushButton(self.tr("Add class"))
        self.remove_rule_button = QtWidgets.QPushButton(
            self.tr("Remove selected class")
        )
        self.default_rule_combo = QtWidgets.QComboBox()
        for value in BOX_RULE_VALUES:
            self.default_rule_combo.addItem(BOX_RULE_LABELS[value], value)
        rule_buttons.addWidget(self.add_rule_button)
        rule_buttons.addWidget(self.remove_rule_button)
        rule_buttons.addSpacing(12)
        rule_buttons.addWidget(QtWidgets.QLabel(self.tr("Default box rule")))
        rule_buttons.addWidget(self.default_rule_combo)
        rule_buttons.addStretch(1)
        rules_layout.addLayout(rule_buttons)
        layout.addWidget(rules_group, 1)

        coverage_group = QtWidgets.QGroupBox(self.tr("Spatial omission grid"))
        coverage_layout = QtWidgets.QHBoxLayout(coverage_group)
        self.columns_spin = QtWidgets.QSpinBox()
        self.columns_spin.setRange(1, 24)
        self.rows_spin = QtWidgets.QSpinBox()
        self.rows_spin.setRange(1, 24)
        self.overlap_spin = QtWidgets.QSpinBox()
        self.overlap_spin.setRange(0, 75)
        self.overlap_spin.setSuffix("%")
        coverage_layout.addWidget(QtWidgets.QLabel(self.tr("Columns")))
        coverage_layout.addWidget(self.columns_spin)
        coverage_layout.addWidget(QtWidgets.QLabel(self.tr("Rows")))
        coverage_layout.addWidget(self.rows_spin)
        coverage_layout.addWidget(QtWidgets.QLabel(self.tr("Overlap")))
        coverage_layout.addWidget(self.overlap_spin)
        coverage_layout.addStretch(1)
        layout.addWidget(coverage_group)

        self.validation_label = QtWidgets.QLabel()
        self.validation_label.setWordWrap(True)
        layout.addWidget(self.validation_label)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        self.ok_button = buttons.button(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
        )
        layout.addWidget(buttons)

        self.add_batch_button.clicked.connect(self._add_batch)
        self.remove_batch_button.clicked.connect(self._remove_batch)
        self.add_rule_button.clicked.connect(self._add_rule)
        self.remove_rule_button.clicked.connect(self._remove_rule)
        self.batch_table.itemChanged.connect(self._validate)
        self.rule_table.itemChanged.connect(self._validate)
        self.default_rule_combo.currentIndexChanged.connect(self._validate)
        self.columns_spin.valueChanged.connect(self._validate)
        self.rows_spin.valueChanged.connect(self._validate)
        self.overlap_spin.valueChanged.connect(self._validate)

    def _load(self, config: ReviewConfig) -> None:
        self.batch_table.setRowCount(0)
        for batch in config.batches:
            self._append_batch(batch.name, batch.labels)
        self.rule_table.setRowCount(0)
        for label, rule in sorted(config.rules.rules.items()):
            self._append_rule(label, rule.box_rule, rule.note)
        self.default_rule_combo.setCurrentIndex(
            max(
                0,
                self.default_rule_combo.findData(
                    config.rules.default_box_rule
                ),
            )
        )
        coverage = config.coverage
        self.columns_spin.setValue(coverage.columns)
        self.rows_spin.setValue(coverage.rows)
        self.overlap_spin.setValue(round(coverage.overlap * 100))
        self._validate()

    def _append_batch(self, name: str, labels: Iterable[str]) -> None:
        row = self.batch_table.rowCount()
        self.batch_table.insertRow(row)
        self.batch_table.setItem(row, 0, QtWidgets.QTableWidgetItem(name))
        self.batch_table.setItem(
            row,
            1,
            QtWidgets.QTableWidgetItem(", ".join(labels)),
        )

    def _append_rule(self, label: str, box_rule: str, note: str) -> None:
        row = self.rule_table.rowCount()
        self.rule_table.insertRow(row)
        self.rule_table.setItem(row, 0, QtWidgets.QTableWidgetItem(label))
        combo = QtWidgets.QComboBox()
        for value in BOX_RULE_VALUES:
            combo.addItem(BOX_RULE_LABELS[value], value)
        combo.setCurrentIndex(max(0, combo.findData(box_rule)))
        combo.currentIndexChanged.connect(self._validate)
        self.rule_table.setCellWidget(row, 1, combo)
        self.rule_table.setItem(row, 2, QtWidgets.QTableWidgetItem(note))

    def _add_batch(self) -> None:
        self._append_batch("", ())
        self.batch_table.setCurrentCell(self.batch_table.rowCount() - 1, 0)
        self._validate()

    def _remove_batch(self) -> None:
        row = self.batch_table.currentRow()
        if row >= 0:
            self.batch_table.removeRow(row)
            self._validate()

    def _add_rule(self) -> None:
        self._append_rule("", "unknown", "")
        self.rule_table.setCurrentCell(self.rule_table.rowCount() - 1, 0)
        self._validate()

    def _remove_rule(self) -> None:
        row = self.rule_table.currentRow()
        if row >= 0:
            self.rule_table.removeRow(row)
            self._validate()

    def _table_text(self, table, row: int, column: int) -> str:
        item = table.item(row, column)
        return item.text().strip() if item is not None else ""

    def config(self) -> ReviewConfig:
        batches = []
        for row in range(self.batch_table.rowCount()):
            name = self._table_text(self.batch_table, row, 0)
            labels = tuple(
                label.strip()
                for label in self._table_text(self.batch_table, row, 1).split(
                    ","
                )
                if label.strip()
            )
            if name or labels:
                batches.append(BatchDefinition(name=name, labels=labels))
        rules = {}
        for row in range(self.rule_table.rowCount()):
            label = self._table_text(self.rule_table, row, 0)
            if not label:
                continue
            combo = self.rule_table.cellWidget(row, 1)
            box_rule = (
                combo.currentData()
                if isinstance(combo, QtWidgets.QComboBox)
                else "unknown"
            )
            note = self._table_text(self.rule_table, row, 2)
            rules[label] = LabelRule(
                label=label, box_rule=box_rule or "unknown", note=note
            )
        coverage = CoverageSettings(
            columns=self.columns_spin.value(),
            rows=self.rows_spin.value(),
            overlap=self.overlap_spin.value() / 100.0,
        )
        return ReviewConfig(
            batches=tuple(batches),
            rules=ReviewRules(
                rules=rules,
                default_box_rule=(
                    self.default_rule_combo.currentData() or "unknown"
                ),
            ),
            coverage=coverage,
        ).normalized()

    def _validate(self, *_args) -> None:
        config = self.config()
        issues = config.validate()
        if issues:
            self.validation_label.setText(
                "；".join(issue.message for issue in issues)
            )
            self.ok_button.setEnabled(False)
            return
        if not self.batch_table.rowCount():
            self.validation_label.setText(
                self.tr(
                    "No confusion batch is configured; all objects will "
                    "enter the other-pending queue."
                )
            )
        else:
            self.validation_label.setText(
                self.tr(
                    "Batches only control order; every label remains "
                    "selectable."
                )
            )
        self.ok_button.setEnabled(True)

    def _accept(self) -> None:
        self._validate()
        if not self.ok_button.isEnabled():
            return
        self.accept()

    @staticmethod
    def available_labels(model) -> list[str]:
        return list(model)
