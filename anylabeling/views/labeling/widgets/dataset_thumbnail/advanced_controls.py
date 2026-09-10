"""Compact controls for explicit filtering, review and display policies."""

from dataclasses import replace

from PyQt6 import QtCore, QtGui, QtWidgets

from ...dataset_index.thumbnail_query import ThumbnailQuery, REVIEW_STATES
from .render_options import RenderOptions


def review_text(state: str) -> str:
    """Translate manual state names consistently on controls and cards."""
    names = dict(
        zip(
            REVIEW_STATES,
            ("Unreviewed", "Confirmed", "Needs editing", "Skipped"),
        )
    )
    return QtCore.QCoreApplication.translate(
        "ThumbnailReview", names.get(state, "Unreviewed")
    )


class ThumbnailFiltersDialog(QtWidgets.QDialog):
    """Edit optional numeric ranges without applying partial invalid input."""

    def __init__(
        self, query: ThumbnailQuery, parent: QtWidgets.QWidget
    ) -> None:
        """Build a compact attribute form with blank optional bounds."""
        super().__init__(parent)
        self.setWindowTitle(self.tr("Thumbnail filters"))
        self.query = query
        self.fields = {}
        form = QtWidgets.QFormLayout(self)
        self.area_unit = QtWidgets.QComboBox()
        self.area_unit.addItem(self.tr("Pixels squared"), "pixels")
        self.area_unit.addItem(self.tr("Percent of original image"), "percent")
        self.area_unit.setCurrentIndex(
            self.area_unit.findData(query.area_unit)
        )
        form.addRow(self.tr("Area unit"), self.area_unit)
        for key, title in (
            ("area", self.tr("Box area")),
            ("ratio", self.tr("Width / height")),
            ("score", self.tr("Score (scoring)")),
        ):
            row = QtWidgets.QHBoxLayout()
            for suffix, hint in (
                ("min", self.tr("Minimum (optional)")),
                ("max", self.tr("Maximum (optional)")),
            ):
                name = f"{key}_{suffix}"
                edit = QtWidgets.QLineEdit()
                edit.setPlaceholderText(hint)
                edit.setValidator(QtGui.QDoubleValidator(edit))
                value = getattr(query, name)
                edit.setText("" if value is None else str(value))
                self.fields[name] = edit
                row.addWidget(edit)
            form.addRow(title, row)
        for key, title in (
            ("group_id", self.tr("Group ID (exact; -1 = missing)")),
            ("description", self.tr("Description contains")),
            ("shape_type", self.tr("Shape type (exact)")),
        ):
            edit = QtWidgets.QLineEdit(getattr(query, key))
            self.fields[key] = edit
            form.addRow(title, edit)
        self.difficult = QtWidgets.QComboBox()
        for title, value in (
            (self.tr("All"), ""),
            (self.tr("Yes"), "yes"),
            (self.tr("No"), "no"),
        ):
            self.difficult.addItem(title, value)
        self.difficult.setCurrentIndex(
            self.difficult.findData(query.difficult)
        )
        form.addRow(self.tr("Difficult"), self.difficult)
        note = QtWidgets.QLabel(
            self.tr(
                "Blank means no limit. Missing scores or image sizes do not count as zero. Width / height outliers are ranked automatically; no threshold is required."
            )
        )
        note.setWordWrap(True)
        form.addRow(note)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        form.addRow(self.error)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
            | QtWidgets.QDialogButtonBox.StandardButton.Reset
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(
            QtWidgets.QDialogButtonBox.StandardButton.Reset
        ).clicked.connect(self.clear_fields)
        form.addRow(buttons)
        self.resize(520, 380)

    def clear_fields(self) -> None:
        """Clear optional limits without changing the applied query."""
        for edit in self.fields.values():
            edit.clear()
        self.area_unit.setCurrentIndex(0)
        self.difficult.setCurrentIndex(0)

    def accept(self) -> None:
        """Validate all bounds before returning a complete query snapshot."""
        values = {}
        try:
            for key, edit in self.fields.items():
                text = edit.text().strip()
                values[key] = (
                    (float(text) if text else None)
                    if key.endswith(("_min", "_max"))
                    else text
                )
            self.query = replace(
                self.query,
                **values,
                area_unit=self.area_unit.currentData(),
                difficult=self.difficult.currentData(),
            )
            self.query.validate()
        except ValueError:
            self.error.setText(
                self.tr(
                    "Enter valid numbers; minimum must not exceed maximum."
                )
            )
            return
        super().accept()


class ThumbnailFeedbackLabel(QtWidgets.QLabel):
    """Reserve space for feedback only while a message is present."""

    def setText(self, text: str) -> None:
        """Display a complete message without stretching the search toolbar."""
        super().setText(text)
        self.setVisible(bool(text))

    def clear(self) -> None:
        """Remove both the message and its layout space."""
        self.setText("")


class AdvancedThumbnailControls(QtWidgets.QWidget):
    """Keep query changes, manual review actions and rendering separate."""

    query_changed = QtCore.pyqtSignal(object)
    status_requested = QtCore.pyqtSignal(str)
    display_changed = QtCore.pyqtSignal()

    def __init__(
        self, query: ThumbnailQuery, width: int, parent: QtWidgets.QWidget
    ) -> None:
        """Create two compact control rows above the thumbnail view."""
        super().__init__(parent)
        self.query = query
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(3)
        search = QtWidgets.QHBoxLayout()
        self.filename = QtWidgets.QLineEdit(query.filename)
        self.filename.setPlaceholderText(self.tr("Search image filename"))
        self.filename.setClearButtonEnabled(True)
        search.addWidget(self.filename, 1)
        self.locate_button = QtWidgets.QPushButton(self.tr("Locate selected"))
        self.locate_button.setToolTip(
            self.tr(
                "Select one search result, then confirm to clear the filename "
                "search and jump to its page. Other filters and sorting stay."
            )
        )
        self.locate_button.setEnabled(False)
        search.addWidget(self.locate_button)
        self.sort = QtWidgets.QComboBox()
        for text, key in (
            (self.tr("Image / Shape order"), "original"),
            (self.tr("Small targets: pixels"), "small_pixels"),
            (self.tr("Small targets: image percent"), "small_relative"),
            (self.tr("Aspect outliers first"), "aspect_outliers"),
        ):
            self.sort.addItem(text, key)
        self.sort.setCurrentIndex(self.sort.findData(query.sort))
        self.sort.setToolTip(
            self.tr(
                "Outliers deviate from the same label's median width / height. This is a ranking, not a quality verdict."
            )
        )
        search.addWidget(self.sort)
        self.review_filter = QtWidgets.QComboBox()
        self.review_filter.addItem(self.tr("All review states"), "")
        for state in REVIEW_STATES:
            self.review_filter.addItem(review_text(state), state)
        self.review_filter.setCurrentIndex(
            self.review_filter.findData(query.review)
        )
        search.addWidget(self.review_filter)
        self.filters_button = QtWidgets.QPushButton(
            self.tr("Attributes / ranges…")
        )
        self.filters_button.clicked.connect(self.edit_filters)
        search.addWidget(self.filters_button)
        clear = QtWidgets.QPushButton(self.tr("Clear filters"))
        clear.clicked.connect(self.clear_query)
        search.addWidget(clear)
        root.addLayout(search)
        self._search_timer = QtCore.QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self.apply_query)
        self.filename.textChanged.connect(lambda: self._search_timer.start())
        self.sort.currentIndexChanged.connect(self.apply_query)
        self.review_filter.currentIndexChanged.connect(self.apply_query)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(self.tr("Mark selected:")))
        self.state_choice = QtWidgets.QComboBox()
        for state in REVIEW_STATES:
            self.state_choice.addItem(review_text(state), state)
        self.state_choice.setCurrentIndex(1)
        row.addWidget(self.state_choice)
        self.mark_button = QtWidgets.QPushButton(self.tr("Set review state"))
        self.mark_button.setEnabled(False)
        self.mark_button.clicked.connect(
            lambda: self.status_requested.emit(self.state_choice.currentData())
        )
        row.addWidget(self.mark_button)
        self.feedback = ThumbnailFeedbackLabel()
        self.feedback.setWordWrap(True)
        self.feedback.hide()
        display = row
        display.addSpacing(12)
        display.addWidget(QtWidgets.QLabel(self.tr("Card size")))
        self.size_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.size_slider.setRange(160, 520)
        self.size_slider.setValue(width)
        self.size_slider.setFixedWidth(100)
        display.addWidget(self.size_slider)
        self.context_mode = QtWidgets.QComboBox()
        self.context_mode.addItem(self.tr("With context"), "context")
        self.context_mode.addItem(self.tr("Tight crop"), "tight")
        display.addWidget(self.context_mode)
        self.padding = QtWidgets.QSpinBox()
        self.padding.setRange(0, 100)
        self.padding.setValue(15)
        self.padding.setSuffix(" %")
        self.padding.setToolTip(
            self.tr("Padding on each side, relative to the target box")
        )
        display.addWidget(self.padding)
        self.box = QtWidgets.QCheckBox(self.tr("Show target boundary"))
        display.addWidget(self.box)
        display.addStretch(1)
        root.addLayout(display)
        root.addWidget(self.feedback)
        self.context_mode.currentIndexChanged.connect(self._display_changed)
        self.padding.valueChanged.connect(self._display_changed)
        self.box.toggled.connect(self._display_changed)

    def _display_changed(self) -> None:
        """Publish a new immutable rendering policy."""
        self.padding.setEnabled(self.context_mode.currentData() == "context")
        self.display_changed.emit()

    def render_options(self) -> RenderOptions:
        """Read context controls without affecting annotation data."""
        return RenderOptions(
            (
                0
                if self.context_mode.currentData() == "tight"
                else self.padding.value() / 100
            ),
            self.box.isChecked(),
        )

    def apply_query(self) -> None:
        """Freeze a complete query and debounce filename typing."""
        self._search_timer.stop()
        self.query = replace(
            self.query,
            filename=self.filename.text().strip(),
            sort=self.sort.currentData(),
            review=self.review_filter.currentData(),
        )
        self.query_changed.emit(self.query)

    def clear_filename(self) -> None:
        """Clear filename typing without triggering a page-one reload."""
        self._search_timer.stop()
        with QtCore.QSignalBlocker(self.filename):
            self.filename.clear()
        self.query = replace(self.query, filename="")

    def edit_filters(self) -> None:
        """Apply an accepted attribute dialog as a single query change."""
        dialog = ThumbnailFiltersDialog(self.query, self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.query = dialog.query
            self.apply_query()

    def clear_query(self) -> None:
        """Restore the original sort and remove optional restrictions."""
        self.query = ThumbnailQuery()
        for widget in (self.filename, self.sort, self.review_filter):
            widget.blockSignals(True)
        self.filename.clear()
        self.sort.setCurrentIndex(0)
        self.review_filter.setCurrentIndex(0)
        for widget in (self.filename, self.sort, self.review_filter):
            widget.blockSignals(False)
        self.filters_button.setToolTip("")
        self.apply_query()
