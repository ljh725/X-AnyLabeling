"""Small internal UI for opt-in local behavior analysis."""

from __future__ import annotations

from PyQt6 import QtCore, QtWidgets


class BehaviorAnalyticsDialog(QtWidgets.QDialog):
    """Configure local recording, analysis range and cleanup actions."""

    export_requested = QtCore.pyqtSignal(str, str)
    cleanup_requested = QtCore.pyqtSignal()
    enabled_changed = QtCore.pyqtSignal(bool)

    def __init__(self, enabled: bool, parent=None) -> None:
        """Build the dialog with recording disabled unless explicitly enabled."""
        super().__init__(parent)
        self.setWindowTitle("Local Behavior Analytics")
        self.setMinimumWidth(520)
        layout = QtWidgets.QVBoxLayout(self)

        self.enabled_box = QtWidgets.QCheckBox(
            "Enable local behavior recording (default off)"
        )
        self.enabled_box.setChecked(bool(enabled))
        self.enabled_box.toggled.connect(self.enabled_changed)
        layout.addWidget(self.enabled_box)
        privacy = QtWidgets.QLabel(
            "Only local JSONL events are read. No model call, upload, image "
            "pixels, free text or absolute paths are included in the analysis."
        )
        privacy.setWordWrap(True)
        layout.addWidget(privacy)

        range_layout = QtWidgets.QHBoxLayout()
        range_layout.addWidget(QtWidgets.QLabel("Range"))
        self.range_box = QtWidgets.QComboBox()
        self.range_box.addItem("Current project session", "project")
        self.range_box.addItem("All natural days", "days")
        self.range_box.addItem("All local events", "all")
        range_layout.addWidget(self.range_box, 1)
        layout.addLayout(range_layout)

        output_layout = QtWidgets.QHBoxLayout()
        output_layout.addWidget(QtWidgets.QLabel("Output"))
        self.output_edit = QtWidgets.QLineEdit()
        self.output_edit.setPlaceholderText("Choose an analysis bundle folder")
        output_layout.addWidget(self.output_edit, 1)
        browse = QtWidgets.QPushButton("Browse")
        browse.clicked.connect(self._browse_output)
        output_layout.addWidget(browse)
        layout.addLayout(output_layout)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Close
        )
        export_button = buttons.addButton(
            "Export deterministic analysis",
            QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole,
        )
        cleanup_button = buttons.addButton(
            "Clean retained logs",
            QtWidgets.QDialogButtonBox.ButtonRole.ActionRole,
        )
        export_button.clicked.connect(self._request_export)
        cleanup_button.clicked.connect(self.cleanup_requested)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def set_status(self, message: str) -> None:
        """Show progress or the last operation result."""
        self.status_label.setText(message)

    def _browse_output(self) -> None:
        """Choose an output directory without creating it yet."""
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Choose analysis output directory"
        )
        if directory:
            self.output_edit.setText(directory)

    def _request_export(self) -> None:
        """Validate the output and notify the host window."""
        output = self.output_edit.text().strip()
        if not output:
            self.set_status("Choose an output directory first.")
            return
        self.export_requested.emit(self.range_box.currentData(), output)
