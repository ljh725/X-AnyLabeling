"""Inspector controls for the virtual target review page session."""

from __future__ import annotations

import math
from typing import Optional

from PyQt6 import QtCore, QtWidgets

from ...virtual_review import (
    GroupIdMode,
    PackingMode,
    VirtualPackingOptions,
)


def _tr(text: str) -> str:
    """Translate a virtual-review UI string with a stable context."""
    return QtCore.QCoreApplication.translate("VirtualReviewWidget", text)


class VirtualReviewWidget(QtWidgets.QWidget):
    """Collect virtual-review criteria and expose navigation controls."""

    start_requested = QtCore.pyqtSignal(object)
    stop_requested = QtCore.pyqtSignal()
    previous_requested = QtCore.pyqtSignal()
    next_requested = QtCore.pyqtSignal()
    overview_requested = QtCore.pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        """Initialize the criteria form and review controls."""
        super().__init__(parent)
        self._labels: list[str] = []
        self._packing_stats = (0, 0, 0)
        self._progress = (-1, 0, 0)
        self._build_ui()

    def _build_ui(self) -> None:
        """Build the compact Inspector form."""
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()

        self.label_box = QtWidgets.QComboBox()
        self.label_box.addItem(_tr("全部标签"), None)
        form.addRow(_tr("锚点标签"), self.label_box)

        self.shape_box = QtWidgets.QComboBox()
        self.shape_box.addItem(_tr("全部形状"), None)
        for shape_type in (
            "rectangle",
            "polygon",
            "rotation",
            "quadrilateral",
            "point",
            "circle",
            "line",
        ):
            self.shape_box.addItem(shape_type, shape_type)
        form.addRow(_tr("形状类型"), self.shape_box)

        self.group_box = QtWidgets.QComboBox()
        self.group_box.addItem(_tr("任意"), GroupIdMode.ANY)
        self.group_box.addItem(_tr("有效 group_id"), GroupIdMode.VALID)
        self.group_box.addItem(_tr("缺少 group_id"), GroupIdMode.MISSING)
        self.group_box.addItem(_tr("指定 group_id"), GroupIdMode.EXACT)
        form.addRow(_tr("group_id"), self.group_box)

        self.group_id_edit = QtWidgets.QLineEdit()
        self.group_id_edit.setPlaceholderText(_tr("指定 group_id"))
        self.group_id_edit.setEnabled(False)
        form.addRow(_tr("指定值"), self.group_id_edit)
        self.group_box.currentIndexChanged.connect(
            lambda: self.group_id_edit.setEnabled(
                self.group_box.currentData() == GroupIdMode.EXACT
            )
        )

        self.min_width_edit = QtWidgets.QLineEdit()
        self.min_width_edit.setPlaceholderText(_tr("不限"))
        self.max_width_edit = QtWidgets.QLineEdit()
        self.max_width_edit.setPlaceholderText(_tr("不限"))
        form.addRow(
            _tr("宽度像素"),
            self._range_widget(self.min_width_edit, self.max_width_edit),
        )

        self.min_height_edit = QtWidgets.QLineEdit()
        self.min_height_edit.setPlaceholderText(_tr("不限"))
        self.max_height_edit = QtWidgets.QLineEdit()
        self.max_height_edit.setPlaceholderText(_tr("不限"))
        form.addRow(
            _tr("高度像素"),
            self._range_widget(self.min_height_edit, self.max_height_edit),
        )

        self.mode_box = QtWidgets.QComboBox()
        self.mode_box.addItem(_tr("单任务"), PackingMode.SINGLE)
        self.mode_box.addItem(_tr("均衡"), PackingMode.BALANCED)
        self.mode_box.addItem(_tr("高密度"), PackingMode.DENSE)
        form.addRow(_tr("显示模式"), self.mode_box)

        self.max_tasks_spin = QtWidgets.QSpinBox()
        self.max_tasks_spin.setRange(1, 3)
        self.max_tasks_spin.setToolTip(_tr("单页最多同时显示的原子任务数"))
        form.addRow(_tr("单页任务上限"), self.max_tasks_spin)

        self.min_anchor_spin = QtWidgets.QDoubleSpinBox()
        self.min_anchor_spin.setRange(0.0, 4000.0)
        self.min_anchor_spin.setDecimals(1)
        self.min_anchor_spin.setSingleStep(8.0)
        self.min_anchor_spin.setSuffix(_tr(" px"))
        self.min_anchor_spin.setToolTip(
            _tr("适配视口后锚点最短边的最小投影像素")
        )
        form.addRow(_tr("最小投影尺寸"), self.min_anchor_spin)

        self.min_gap_spin = QtWidgets.QDoubleSpinBox()
        self.min_gap_spin.setRange(0.0, 4000.0)
        self.min_gap_spin.setDecimals(1)
        self.min_gap_spin.setSingleStep(8.0)
        self.min_gap_spin.setSuffix(_tr(" px"))
        self.min_gap_spin.setToolTip(
            _tr("适配视口后同页任务包围盒之间的最小投影间距")
        )
        form.addRow(_tr("最小投影间距"), self.min_gap_spin)

        self.mode_box.currentIndexChanged.connect(self._on_mode_changed)
        self._apply_mode_preset(PackingMode.BALANCED)
        self.mode_box.setCurrentIndex(
            self.mode_box.findData(PackingMode.BALANCED)
        )

        layout.addLayout(form)

        action_row = QtWidgets.QHBoxLayout()
        self.start_button = QtWidgets.QPushButton(_tr("生成任务"))
        self.stop_button = QtWidgets.QPushButton(_tr("退出"))
        self.start_button.clicked.connect(self._emit_start)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        action_row.addWidget(self.start_button)
        action_row.addWidget(self.stop_button)
        layout.addLayout(action_row)

        navigation_row = QtWidgets.QHBoxLayout()
        self.previous_button = QtWidgets.QPushButton(_tr("上一个"))
        self.next_button = QtWidgets.QPushButton(_tr("下一个"))
        self.overview_button = QtWidgets.QPushButton(_tr("查看全图"))
        self.previous_button.clicked.connect(self.previous_requested.emit)
        self.next_button.clicked.connect(self.next_requested.emit)
        self.overview_button.clicked.connect(self.overview_requested.emit)
        navigation_row.addWidget(self.previous_button)
        navigation_row.addWidget(self.next_button)
        navigation_row.addWidget(self.overview_button)
        layout.addLayout(navigation_row)

        self.progress_label = QtWidgets.QLabel(_tr("未生成任务"))
        self.progress_label.setWordWrap(True)
        layout.addWidget(self.progress_label)
        layout.addStretch(1)

    @staticmethod
    def _range_widget(
        minimum: QtWidgets.QLineEdit,
        maximum: QtWidgets.QLineEdit,
    ) -> QtWidgets.QWidget:
        """Return a compact min/max editor row."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(minimum)
        layout.addWidget(QtWidgets.QLabel("~"))
        layout.addWidget(maximum)
        return widget

    def _on_mode_changed(self) -> None:
        """Apply the selected density preset to the explicit controls."""
        mode = self.mode_box.currentData()
        if isinstance(mode, PackingMode):
            self._apply_mode_preset(mode)

    def _apply_mode_preset(self, mode: PackingMode) -> None:
        """Populate effective packing values from a named preset."""
        options = VirtualPackingOptions.preset(mode)
        self.max_tasks_spin.setValue(options.max_tasks_per_page)
        self.min_anchor_spin.setValue(options.min_projected_anchor_px)
        self.min_gap_spin.setValue(options.min_projected_gap_px)
        single = mode is PackingMode.SINGLE
        self.max_tasks_spin.setEnabled(not single)
        if single:
            self.max_tasks_spin.setValue(1)

    def set_labels(self, labels: set[str]) -> None:
        """Replace the label choices while preserving the current choice."""
        current = self.label_box.currentData()
        self.label_box.blockSignals(True)
        self.label_box.clear()
        self.label_box.addItem(_tr("全部标签"), None)
        self._labels = sorted(str(label) for label in labels)
        for label in self._labels:
            self.label_box.addItem(label, label)
        index = self.label_box.findData(current)
        self.label_box.setCurrentIndex(max(index, 0))
        self.label_box.blockSignals(False)

    @staticmethod
    def _parse_optional_float(editor: QtWidgets.QLineEdit) -> Optional[float]:
        """Parse a blank-or-nonnegative numeric field."""
        text = editor.text().strip()
        if not text:
            return None
        value = float(text)
        if not math.isfinite(value) or value < 0:
            raise ValueError("尺寸必须是有限非负数")
        return value

    def criteria_payload(self) -> dict:
        """Return validated criteria input for the controller."""
        group_mode = self.group_box.currentData() or GroupIdMode.ANY
        group_id = self.group_id_edit.text().strip() or None
        return {
            "labels": frozenset(
                {self.label_box.currentData()}
                if self.label_box.currentData()
                else set()
            ),
            "shape_types": frozenset(
                {self.shape_box.currentData()}
                if self.shape_box.currentData()
                else set()
            ),
            "group_id_mode": group_mode,
            "group_id": group_id,
            "min_width": self._parse_optional_float(self.min_width_edit),
            "max_width": self._parse_optional_float(self.max_width_edit),
            "min_height": self._parse_optional_float(self.min_height_edit),
            "max_height": self._parse_optional_float(self.max_height_edit),
        }

    def packing_payload(self) -> dict:
        """Return the effective packing options for the controller."""
        mode = self.mode_box.currentData()
        if not isinstance(mode, PackingMode):
            mode = PackingMode.BALANCED
        return {
            "mode": mode,
            "max_tasks_per_page": self.max_tasks_spin.value(),
            "min_projected_anchor_px": float(self.min_anchor_spin.value()),
            "min_projected_gap_px": float(self.min_gap_spin.value()),
        }

    def _emit_start(self) -> None:
        """Validate form input and request a new virtual session."""
        try:
            payload = {
                "criteria": self.criteria_payload(),
                "packing": self.packing_payload(),
            }
            VirtualPackingOptions(**payload["packing"])
        except (TypeError, ValueError) as exc:
            self.progress_label.setText(_tr("条件无效：%s") % exc)
            return
        self.start_requested.emit(payload)

    def set_packing_stats(
        self, atomic_tasks: int, pages: int, fallback: int
    ) -> None:
        """Store packing diagnostics and refresh the progress label."""
        self._packing_stats = (int(atomic_tasks), int(pages), int(fallback))
        self._refresh_progress()

    def set_progress(
        self, index: int, total: int, page_task_count: int = 0
    ) -> None:
        """Update the progress position and refresh the label."""
        self._progress = (int(index), int(total), int(page_task_count))
        self._refresh_progress()

    def _refresh_progress(self) -> None:
        """Render the combined page progress and packing statistics."""
        index, total, page_tasks = self._progress
        atomic, pages, fallback = self._packing_stats
        if total <= 0:
            self.progress_label.setText(_tr("未生成任务"))
            return
        text = _tr("当前页面：%d/%d（本页任务 %d）") % (
            index + 1,
            total,
            page_tasks,
        )
        if atomic > 0:
            text += "\n" + _tr(
                "任务 %d → 页面 %d（减少 %d 次翻页）· 单页兜底 %d"
            ) % (atomic, pages, atomic - pages, fallback)
        self.progress_label.setText(text)

    def set_running(self, running: bool) -> None:
        """Enable or disable controls that require an active session."""
        self.previous_button.setEnabled(running)
        self.next_button.setEnabled(running)
        self.overview_button.setEnabled(running)
