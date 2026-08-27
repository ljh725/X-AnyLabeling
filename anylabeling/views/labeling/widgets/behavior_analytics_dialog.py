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
        self.setWindowTitle(self.tr("Local Behavior Analytics"))
        self.setMinimumWidth(520)
        layout = QtWidgets.QVBoxLayout(self)

        self.enabled_box = QtWidgets.QCheckBox(
            self.tr("Enable local behavior recording (default off)")
        )
        self.enabled_box.setChecked(bool(enabled))
        self.enabled_box.toggled.connect(self.enabled_changed)
        layout.addWidget(self.enabled_box)
        privacy = QtWidgets.QLabel(
            self.tr(
                "Only local JSONL events are read. No model call, upload, image "
                "pixels, free text or absolute paths are included in the analysis."
            )
        )
        privacy.setWordWrap(True)
        layout.addWidget(privacy)

        range_layout = QtWidgets.QHBoxLayout()
        range_layout.addWidget(QtWidgets.QLabel(self.tr("Range")))
        self.range_box = QtWidgets.QComboBox()
        self.range_box.addItem(self.tr("Current project session"), "project")
        self.range_box.addItem(
            self.tr("Preset or custom local range"), "preset"
        )
        self.range_box.addItem(self.tr("Baseline vs comparison"), "dual")
        range_layout.addWidget(self.range_box, 1)
        layout.addLayout(range_layout)

        self.preset_box = QtWidgets.QComboBox()
        self.preset_box.addItem(self.tr("Recent 1 day"), "recent_1d")
        self.preset_box.addItem(self.tr("Recent 7 days"), "recent_7d")
        self.preset_box.addItem(self.tr("Recent 30 days"), "recent_30d")
        self.preset_box.addItem(self.tr("Custom local range"), "custom")
        self.preset_box.addItem(self.tr("All local data"), "all")
        layout.addWidget(self.preset_box)
        self.timezone_label = QtWidgets.QLabel(
            self.tr(
                "Local time uses the system timezone and is converted to UTC."
            )
        )
        layout.addWidget(self.timezone_label)
        custom_layout = QtWidgets.QHBoxLayout()
        custom_layout.addWidget(QtWidgets.QLabel(self.tr("Custom start")))
        self.custom_start_edit = QtWidgets.QLineEdit()
        self.custom_start_edit.setPlaceholderText("YYYY-MM-DDTHH:MM:SS")
        custom_layout.addWidget(self.custom_start_edit, 1)
        custom_layout.addWidget(QtWidgets.QLabel(self.tr("end")))
        self.custom_end_edit = QtWidgets.QLineEdit()
        self.custom_end_edit.setPlaceholderText("YYYY-MM-DDTHH:MM:SS")
        custom_layout.addWidget(self.custom_end_edit, 1)
        layout.addLayout(custom_layout)
        dual_layout = QtWidgets.QHBoxLayout()
        dual_layout.addWidget(QtWidgets.QLabel(self.tr("Baseline")))
        self.baseline_box = QtWidgets.QComboBox()
        self.comparison_box = QtWidgets.QComboBox()
        for box in (self.baseline_box, self.comparison_box):
            box.addItem(self.tr("Recent 1 day"), "recent_1d")
            box.addItem(self.tr("Recent 7 days"), "recent_7d")
            box.addItem(self.tr("Recent 30 days"), "recent_30d")
            box.addItem(self.tr("Custom local range"), "custom")
        dual_layout.addWidget(self.baseline_box, 1)
        dual_layout.addWidget(QtWidgets.QLabel(self.tr("Comparison")))
        dual_layout.addWidget(self.comparison_box, 1)
        layout.addLayout(dual_layout)

        output_layout = QtWidgets.QHBoxLayout()
        output_layout.addWidget(QtWidgets.QLabel(self.tr("Output")))
        self.output_edit = QtWidgets.QLineEdit()
        self.output_edit.setPlaceholderText(
            self.tr("Choose an analysis bundle folder")
        )
        output_layout.addWidget(self.output_edit, 1)
        browse = QtWidgets.QPushButton(self.tr("Browse"))
        browse.clicked.connect(self._browse_output)
        output_layout.addWidget(browse)
        layout.addLayout(output_layout)

        self.recording_label = QtWidgets.QLabel(
            self.tr("Recording status: disabled or not started.")
        )
        self.recording_label.setWordWrap(True)
        layout.addWidget(self.recording_label)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.quality_label = QtWidgets.QLabel(
            self.tr(
                "Measurement quality: not evaluated. v2 exports add "
                "image_metrics.csv, rework_metrics.csv and "
                "measurement_quality.json. Duration conclusions require "
                "95% coverage; feature comparisons require two groups with "
                "30 valid episodes each."
            )
        )
        self.quality_label.setWordWrap(True)
        layout.addWidget(self.quality_label)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Close
        )
        export_button = buttons.addButton(
            self.tr("Export deterministic analysis"),
            QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole,
        )
        cleanup_button = buttons.addButton(
            self.tr("Clean retained logs"),
            QtWidgets.QDialogButtonBox.ButtonRole.ActionRole,
        )
        export_button.clicked.connect(self._request_export)
        cleanup_button.clicked.connect(self.cleanup_requested)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def set_status(self, message: str) -> None:
        """Show progress or the last operation result."""
        self.status_label.setText(message)

    def set_recording_status(self, health: object | None) -> None:
        """Show local recorder counters without exposing event contents."""
        if health is None:
            self.recording_label.setText(
                self.tr("Recording status: disabled or not started.")
            )
            return
        self.recording_label.setText(
            self.tr(
                "Recording status: enabled | accepted=%1, written=%2, "
                "dropped=%3, errors=%4, gaps=%5, current=%6"
            )
            .replace("%1", str(health.accepted))
            .replace("%2", str(health.written))
            .replace("%3", str(health.dropped))
            .replace("%4", str(health.write_errors))
            .replace("%5", str(health.sequence_gaps))
            .replace("%6", str(health.current_shard or "-"))
        )

    def set_quality_summary(
        self,
        quality_gate: bool,
        *,
        low_confidence_reasons: list[str] | None = None,
        comparison_unavailable: list[str] | None = None,
    ) -> None:
        """Show quality state and honest comparison limitations."""
        status = (
            self.tr("passed") if quality_gate else self.tr("low confidence")
        )
        reason_labels = {
            "missing_context": self.tr("context unavailable for comparison"),
            "missing_boundary": self.tr("object boundary incomplete"),
            "missing_focus_idle_boundaries": self.tr(
                "focus/idle boundaries unavailable"
            ),
            "missing_monotonic_boundaries": self.tr(
                "action duration boundary incomplete"
            ),
            "insufficient_samples": self.tr("insufficient samples"),
        }
        details = [
            reason_labels.get(reason, reason)
            for reason in (low_confidence_reasons or [])
        ]
        details.extend(
            reason_labels.get(reason, reason)
            for reason in (comparison_unavailable or [])
        )
        suffix = f" ({'; '.join(details)})" if details else ""
        self.quality_label.setText(
            self.tr("Measurement quality: %1").replace(
                "%1", f"{status}{suffix}"
            )
        )

    def _browse_output(self) -> None:
        """Choose an output directory without creating it yet."""
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self, self.tr("Choose analysis output directory")
        )
        if directory:
            self.output_edit.setText(directory)

    def _request_export(self) -> None:
        """Validate the output and notify the host window."""
        output = self.output_edit.text().strip()
        if not output:
            self.set_status(self.tr("Choose an output directory first."))
            return
        self.export_requested.emit(self.range_box.currentData(), output)
