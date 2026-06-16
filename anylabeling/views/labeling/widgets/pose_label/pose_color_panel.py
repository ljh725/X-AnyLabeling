"""Pose color sidebar panel (font color, body-part colors, presets).

A ``QFrame`` inserted into ``LabelingWidget.right_sidebar_layout``.
Provides controls for font colour mode, per-body-part colour pickers,
and quick-apply colour presets.
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from ...utils.style import get_panel_style
from .pose_config import PoseDisplayConfig
from .pose_constants import BODY_PART_ORDER, COLOR_PRESETS

_BODY_PART_LABELS = {
    "head": "Head",
    "la": "Left Arm",
    "ra": "Right Arm",
    "ll": "Left Leg",
    "rl": "Right Leg",
}


class _ColorSwatchButton(QtWidgets.QPushButton):
    """Small clickable square showing a colour."""

    color_changed = QtCore.pyqtSignal(str)

    def __init__(
        self, hex_color: str, parent: Optional[QtWidgets.QWidget] = None
    ) -> None:
        super().__init__(parent)
        self._hex = hex_color
        self.setFixedSize(28, 22)
        self._update_icon()
        self.clicked.connect(self._pick_color)

    def _update_icon(self) -> None:
        """Refresh the button background."""
        self.setStyleSheet(
            f"QPushButton {{ background: {self._hex};"
            " border: 1px solid #3a3a52; border-radius: 3px; }}"
            "QPushButton:hover { border: 1px solid #89b4fa; }"
        )

    def _pick_color(self) -> None:
        """Open QColorDialog and emit the chosen colour."""
        dlg = QtWidgets.QColorDialog(self)
        dlg.setCurrentColor(QtGui.QColor(self._hex))
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            c = dlg.currentColor()
            if c.isValid():
                self._hex = c.name()
                self._update_icon()
                self.color_changed.emit(self._hex)

    @property
    def hex_color(self) -> str:
        """Return the current colour as a hex string."""
        return self._hex

    def set_color(self, hex_color: str) -> None:
        """Programmatically set the colour."""
        self._hex = hex_color
        self._update_icon()


class PoseColorPanel(QtWidgets.QFrame):
    """Sidebar panel for pose colour configuration.

    Args:
        config: Shared PoseDisplayConfig instance.
        on_change: Callback invoked after any colour change.
        parent: Parent widget.
    """

    def __init__(
        self,
        config: PoseDisplayConfig,
        on_change: Optional[Callable[[], None]] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("sidebarPanel")
        self.setStyleSheet(get_panel_style())
        self._config = config
        self._on_change = on_change
        main = QtWidgets.QVBoxLayout(self)
        main.setContentsMargins(4, 4, 4, 4)
        main.setSpacing(4)
        self._build_header(main)
        self._build_font_color(main)
        self._build_body_colors(main)
        self._build_presets(main)

    # -- Build helpers ---------------------------------------------------

    def _build_header(self, layout: QtWidgets.QVBoxLayout) -> None:
        """Add the panel title label."""
        hdr = QtWidgets.QLabel(self.tr("Pose Colors"))
        hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hdr.setStyleSheet("font-weight: bold; font-size: 11px;")
        layout.addWidget(hdr)

    def _build_font_color(self, layout: QtWidgets.QVBoxLayout) -> None:
        """Add font-colour-mode radio buttons + custom picker."""
        grp = QtWidgets.QButtonGroup(self)
        grp.setExclusive(True)
        self._font_color_btns: dict[str, QtWidgets.QRadioButton] = {}
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(2)
        for i, (key, label) in enumerate(
            [
                ("white", self.tr("White")),
                ("black", self.tr("Black")),
                ("auto", self.tr("Auto")),
                ("yellow", self.tr("Yellow")),
                ("custom", self.tr("Custom")),
            ]
        ):
            rb = QtWidgets.QRadioButton(label)
            rb.setStyleSheet("font-size: 11px;")
            rb.setChecked(self._config.font_color_mode == key)
            rb.toggled.connect(
                lambda checked, k=key: self._set_font_color_mode(k, checked)
            )
            grp.addButton(rb)
            grid.addWidget(rb, i // 3, i % 3)
            self._font_color_btns[key] = rb
        layout.addLayout(grid)
        custom_row = QtWidgets.QHBoxLayout()
        custom_row.setSpacing(4)
        self._custom_swatch = _ColorSwatchButton(
            self._config.custom_font_color
        )
        self._custom_swatch.color_changed.connect(self._on_custom_font_color)
        self._custom_swatch.setVisible(
            self._config.font_color_mode == "custom"
        )
        custom_row.addWidget(QtWidgets.QLabel(self.tr("Custom:")))
        custom_row.addWidget(self._custom_swatch)
        custom_row.addStretch()
        layout.addLayout(custom_row)

    def _build_body_colors(self, layout: QtWidgets.QVBoxLayout) -> None:
        """Add body-part colour pickers."""
        self._body_swatch: dict[str, _ColorSwatchButton] = {}
        for part in BODY_PART_ORDER:
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(4)
            hex_val = self._config.body_colors.get(part, "#7f849c")
            swatch = _ColorSwatchButton(hex_val)
            swatch.color_changed.connect(
                lambda h, p=part: self._set_body_color(p, h)
            )
            row.addWidget(swatch)
            row.addWidget(
                QtWidgets.QLabel(self.tr(_BODY_PART_LABELS.get(part, part)))
            )
            row.addStretch()
            layout.addLayout(row)
            self._body_swatch[part] = swatch

    def _build_presets(self, layout: QtWidgets.QVBoxLayout) -> None:
        """Add colour preset buttons."""
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(3)
        for name in COLOR_PRESETS:
            btn = QtWidgets.QPushButton(self.tr(name.title()))
            btn.setFixedHeight(22)
            btn.setStyleSheet(
                "QPushButton { border: 1px solid #555;"
                " border-radius: 3px; font-size: 10px;"
                " padding: 2px 6px; }"
                "QPushButton:hover { background: #2e2e44; }"
            )
            btn.clicked.connect(lambda _, n=name: self._apply_preset(n))
            row.addWidget(btn)
        layout.addLayout(row)
        reset_btn = QtWidgets.QPushButton(self.tr("Reset Colors"))
        reset_btn.setFixedHeight(22)
        reset_btn.setStyleSheet(
            "QPushButton { border: 1px solid #555;"
            " border-radius: 3px; font-size: 10px;"
            " padding: 2px 6px; }"
            "QPushButton:hover { background: #f38ba8;"
            " color: #1e1e2e; border-color: #f38ba8; }"
        )
        reset_btn.clicked.connect(lambda: self._apply_preset("default"))
        layout.addWidget(reset_btn)

    # -- Handlers --------------------------------------------------------

    def _set_font_color_mode(self, mode: str, checked: bool) -> None:
        """Update config.font_color_mode."""
        if not checked:
            return
        self._config.font_color_mode = mode
        self._custom_swatch.setVisible(mode == "custom")
        self._notify()

    def _on_custom_font_color(self, hex_color: str) -> None:
        """Update custom font colour."""
        self._config.custom_font_color = hex_color
        self._notify()

    def _set_body_color(self, part: str, hex_color: str) -> None:
        """Update one body-part colour."""
        self._config.body_colors[part] = hex_color
        self._notify()

    def _apply_preset(self, name: str) -> None:
        """Apply a named colour preset."""
        self._config.apply_preset(name)
        self.sync_from_config()
        self._notify()

    def _notify(self) -> None:
        """Fire the on_change callback."""
        if self._on_change:
            self._on_change()

    # -- Sync -----------------------------------------------------------

    def sync_from_config(self) -> None:
        """Refresh all swatches and radios from the config."""
        for part in BODY_PART_ORDER:
            if part in self._body_swatch:
                hex_val = self._config.body_colors.get(part)
                if hex_val:
                    self._body_swatch[part].set_color(hex_val)
        for key, rb in self._font_color_btns.items():
            rb.blockSignals(True)
            rb.setChecked(self._config.font_color_mode == key)
            rb.blockSignals(False)
        self._custom_swatch.set_color(self._config.custom_font_color)
        self._custom_swatch.setVisible(
            self._config.font_color_mode == "custom"
        )
