"""Pose settings sidebar panel (layout mode, sliders, toggles).

A ``QFrame`` inserted into ``LabelingWidget.right_sidebar_layout``.
All controls read/write the shared :class:`PoseDisplayConfig` instance
and trigger ``canvas.update()`` on change.
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from ...utils.style import get_panel_style
from .pose_config import PoseDisplayConfig


class PoseSettingsPanel(QtWidgets.QFrame):
    """Sidebar panel for pose label display parameters.

    Args:
        config: Shared PoseDisplayConfig instance.
        on_change: Callback invoked after any parameter change.
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
        self._build_layout_mode(main)
        self._build_color_mode(main)
        self._build_sliders(main)
        self._build_toggles(main)

    # -- Build helpers ---------------------------------------------------

    def _build_header(self, layout: QtWidgets.QVBoxLayout) -> None:
        """Add the panel title label."""
        hdr = QtWidgets.QLabel(self.tr("姿态视图设置"))
        hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hdr.setStyleSheet("font-weight: bold; font-size: 11px;")
        layout.addWidget(hdr)

    def _build_layout_mode(self, layout: QtWidgets.QVBoxLayout) -> None:
        """Add the layout-mode radio group."""
        grp = QtWidgets.QButtonGroup(self)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(3)
        self._layout_btns: dict[str, QtWidgets.QPushButton] = {}
        for key, label in [
            ("direct", self.tr("方向引线")),
            ("anti", self.tr("防遮挡")),
            ("column", self.tr("侧栏列表")),
        ]:
            btn = QtWidgets.QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(22)
            btn.setStyleSheet(self._btn_style())
            btn.clicked.connect(lambda _, k=key: self._set_layout_mode(k))
            grp.addButton(btn)
            row.addWidget(btn)
            self._layout_btns[key] = btn
        if self._config.layout_mode in self._layout_btns:
            self._layout_btns[self._config.layout_mode].setChecked(True)
        layout.addLayout(row)

    def _build_color_mode(self, layout: QtWidgets.QVBoxLayout) -> None:
        """Add the color-mode radio group."""
        grp = QtWidgets.QButtonGroup(self)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(3)
        self._color_btns: dict[str, QtWidgets.QPushButton] = {}
        for key, label in [
            ("bodypart", self.tr("按部位")),
            ("person", self.tr("按目标")),
        ]:
            btn = QtWidgets.QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(22)
            btn.setStyleSheet(self._btn_style())
            btn.clicked.connect(lambda _, k=key: self._set_color_mode(k))
            grp.addButton(btn)
            row.addWidget(btn)
            self._color_btns[key] = btn
        if self._config.color_mode in self._color_btns:
            self._color_btns[self._config.color_mode].setChecked(True)
        layout.addLayout(row)

    def _build_sliders(self, layout: QtWidgets.QVBoxLayout) -> None:
        """Add parameter sliders."""
        slider_defs = [
            (
                "font_size",
                self.tr("标签字号"),
                8,
                16,
                self._config.font_size,
                "",
            ),
            (
                "opacity",
                self.tr("透明度"),
                30,
                100,
                int(self._config.opacity * 100),
                "%",
            ),
            (
                "leader_length",
                self.tr("引线长度"),
                15,
                80,
                self._config.leader_length,
                "px",
            ),
            (
                "border_width",
                self.tr("描边宽度"),
                0,
                40,
                int(self._config.border_width * 10),
                "",
            ),
            (
                "column_gap",
                self.tr("列间距"),
                4,
                30,
                self._config.column_gap,
                "px",
            ),
        ]
        self._sliders: dict[str, QtWidgets.QSlider] = {}
        self._slider_labels: dict[str, QtWidgets.QLabel] = {}
        for key, label_text, lo, hi, val, suffix in slider_defs:
            row = QtWidgets.QHBoxLayout()
            lbl = QtWidgets.QLabel(label_text)
            lbl.setStyleSheet("font-size: 11px;")
            val_lbl = QtWidgets.QLabel(self._format_slider(key, val, suffix))
            val_lbl.setStyleSheet("font-size: 11px; color: #89b4fa;")
            val_lbl.setFixedWidth(45)
            val_lbl.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            slider = QtWidgets.QSlider(Qt.Orientation.Horizontal)
            slider.setMinimum(lo)
            slider.setMaximum(hi)
            slider.setValue(val)
            slider.setStyleSheet(self._slider_style())
            slider.valueChanged.connect(
                lambda v, k=key, s=suffix: self._on_slider(k, v, s)
            )
            row.addWidget(lbl)
            row.addWidget(val_lbl)
            layout.addLayout(row)
            layout.addWidget(slider)
            self._sliders[key] = slider
            self._slider_labels[key] = val_lbl

    def _build_toggles(self, layout: QtWidgets.QVBoxLayout) -> None:
        """Add display option checkboxes."""
        toggle_defs = [
            ("show_skeleton", self.tr("骨骼连线")),
            ("show_midline", self.tr("中线参考")),
            ("show_bbox", self.tr("目标框")),
            (
                "occlusion_highlight",
                self.tr("遮挡高亮"),
            ),
            ("show_leader", self.tr("引线")),
            ("font_shadow", self.tr("文字阴影")),
        ]
        self._toggles: dict[str, QtWidgets.QCheckBox] = {}
        for key, label_text in toggle_defs:
            cb = QtWidgets.QCheckBox(label_text)
            cb.setChecked(getattr(self._config, key))
            cb.setStyleSheet("font-size: 11px;")
            cb.toggled.connect(lambda v, k=key: self._on_toggle(k, v))
            layout.addWidget(cb)
            self._toggles[key] = cb

    # -- Handlers --------------------------------------------------------

    def _set_layout_mode(self, mode: str) -> None:
        """Update config.layout_mode and repaint."""
        self._config.layout_mode = mode
        self._notify()

    def _set_color_mode(self, mode: str) -> None:
        """Update config.color_mode and repaint."""
        self._config.color_mode = mode
        self._notify()

    def _on_slider(self, key: str, value: int, suffix: str) -> None:
        """Handle slider value change."""
        if key == "opacity":
            self._config.opacity = value / 100.0
        elif key == "border_width":
            self._config.border_width = value / 10.0
        else:
            setattr(self._config, key, value)
        self._slider_labels[key].setText(
            self._format_slider(key, value, suffix)
        )
        self._notify()

    def _on_toggle(self, key: str, value: bool) -> None:
        """Handle checkbox toggle."""
        setattr(self._config, key, value)
        self._notify()

    def _notify(self) -> None:
        """Fire the on_change callback."""
        if self._on_change:
            self._on_change()

    # -- Sync from config ------------------------------------------------

    def sync_from_config(self) -> None:
        """Refresh all controls from the config object."""
        if self._config.layout_mode in self._layout_btns:
            for k, b in self._layout_btns.items():
                b.setChecked(k == self._config.layout_mode)
        if self._config.color_mode in self._color_btns:
            for k, b in self._color_btns.items():
                b.setChecked(k == self._config.color_mode)
        slider_map = {
            "font_size": (self._config.font_size, ""),
            "opacity": (int(self._config.opacity * 100), "%"),
            "leader_length": (self._config.leader_length, "px"),
            "border_width": (
                int(self._config.border_width * 10),
                "",
            ),
            "column_gap": (self._config.column_gap, "px"),
        }
        for key, (val, suffix) in slider_map.items():
            if key in self._sliders:
                self._sliders[key].blockSignals(True)
                self._sliders[key].setValue(val)
                self._sliders[key].blockSignals(False)
                self._slider_labels[key].setText(
                    self._format_slider(key, val, suffix)
                )
        for key, cb in self._toggles.items():
            cb.blockSignals(True)
            cb.setChecked(getattr(self._config, key))
            cb.blockSignals(False)

    # -- Style helpers ---------------------------------------------------

    @staticmethod
    def _btn_style() -> str:
        """Return the button QSS string."""
        return (
            "QPushButton { border: 1px solid #555; border-radius: 3px;"
            " font-size: 11px; padding: 2px 4px; }"
            "QPushButton:checked { background: #e94560;"
            " color: white; border-color: #e94560; }"
        )

    @staticmethod
    def _slider_style() -> str:
        """Return the slider QSS string."""
        return (
            "QSlider::groove:horizontal {"
            " height: 4px; background: #3a3a52;"
            " border-radius: 2px; }"
            "QSlider::handle:horizontal {"
            " width: 13px; height: 13px;"
            " border-radius: 6px; background: #89b4fa;"
            " border: 2px solid #252536; }"
        )

    @staticmethod
    def _format_slider(key: str, value: int, suffix: str) -> str:
        """Format the slider value display."""
        if key == "opacity":
            return f"{value / 100.0:.2f}{suffix}"
        if key == "border_width":
            return f"{value / 10.0:.1f}{suffix}"
        return f"{value}{suffix}"
