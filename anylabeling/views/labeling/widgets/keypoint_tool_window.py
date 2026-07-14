"""
Keypoint Tool Window Module (PyQt6,精简版)

为关键点补标流程提供独立工具窗口，显示所有 person 对象的补标进度，
支持一键切换目标并自动进入补标模式。

去除 3.3.0 中过度分层的架构(data_view / data_operation / message_manager)，
将数据读取与操作逻辑直接内联到内容组件中。

Classes:
    - KeypointDockContent: 内容组件(UI + 业务逻辑)
    - KeypointToolWindow: 独立窗口容器
"""

import logging
from typing import Any, Dict, Optional, Set

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

logger = logging.getLogger(__name__)

# COCO 17 关键点标准顺序
KEYPOINT_ORDER = [
    "nose",
    "l_eye",
    "r_eye",
    "l_ear",
    "r_ear",
    "l_sho",
    "r_sho",
    "l_elb",
    "r_elb",
    "l_wri",
    "r_wri",
    "l_hip",
    "r_hip",
    "l_knee",
    "r_knee",
    "l_ank",
    "r_ank",
]


class KeypointDockContent(QtWidgets.QWidget):
    """
    关键点标注工具窗口的内容组件。

    职责:
    - 列出所有 person 对象及补标进度
    - 点击切换对象，自动设置 group_id 筛选并激活补标模式
    - 显示当前对象的 17 个关键点完成状态
    """

    def __init__(
        self,
        fill_mode: Any,
        label_widget: Any,
        parent: Optional[QtWidgets.QWidget] = None,
    ):
        super().__init__(parent)

        self.fill_mode = fill_mode
        self.label_widget = label_widget
        self.current_group_id: Optional[int] = None

        self._setup_ui()
        self._connect_signals()
        self._load_settings()
        self.refresh_all()

        logger.debug("KeypointDockContent initialized")

    # ---------- UI Setup ----------

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        # Auto-activation toggle
        self.auto_activate_cb = QtWidgets.QCheckBox(
            "自动锁定目标 (Auto-Activate)"
        )
        self.auto_activate_cb.setToolTip(
            "开启后，切换图片时若检测到唯一对象将自动进入补全模式"
        )
        self.auto_activate_cb.stateChanged.connect(
            self._on_auto_activate_changed
        )
        layout.addWidget(self.auto_activate_cb)

        # Header
        self.header_label = QtWidgets.QLabel("共 0 人")
        self.header_label.setStyleSheet("font-weight: bold; font-size: 12pt;")
        layout.addWidget(self.header_label)

        self.stats_label = QtWidgets.QLabel("未完成: 0 人 | 已完成: 0 人")
        self.stats_label.setStyleSheet("color: #666; font-size: 9pt;")
        layout.addWidget(self.stats_label)

        # Person list
        self.person_list = QtWidgets.QListWidget()
        self.person_list.setMaximumHeight(150)
        self.person_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        layout.addWidget(self.person_list)

        # Separator
        sep1 = QtWidgets.QFrame()
        sep1.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep1.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        layout.addWidget(sep1)

        # Current person info
        self.current_label = QtWidgets.QLabel("未选中对象")
        self.current_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.current_label)

        # Progress bar
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(len(KEYPOINT_ORDER))
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m")
        layout.addWidget(self.progress_bar)

        # Hint label
        self.hint_label = QtWidgets.QLabel("")
        self.hint_label.setStyleSheet(
            "background-color: #e8f4e8; "
            "border: 1px solid #4CAF50; "
            "border-radius: 3px; "
            "padding: 5px; "
            "color: #2e7d32; "
            "font-size: 10pt;"
        )
        self.hint_label.setWordWrap(True)
        self.hint_label.setVisible(False)
        layout.addWidget(self.hint_label)

        # Separator
        sep2 = QtWidgets.QFrame()
        sep2.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep2.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        layout.addWidget(sep2)

        # Keypoint status list
        kp_label = QtWidgets.QLabel("关键点状态:")
        kp_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(kp_label)

        self.keypoint_list = QtWidgets.QListWidget()
        layout.addWidget(self.keypoint_list)

    def _connect_signals(self) -> None:
        self.person_list.itemClicked.connect(self._on_person_selected)
        self.person_list.itemDoubleClicked.connect(self._on_person_activated)
        self.keypoint_list.itemClicked.connect(self._on_keypoint_clicked)

        # 鼠标滚轮切换组 ID
        self.person_list.installEventFilter(self)

        # NOTE: canvas.new_shape -> refresh_all is wired externally by
        # LabelWidget when it creates the KeypointToolWindow instance.
        # Do NOT connect it here to avoid duplicate emissions.

        # Fill mode signals
        if hasattr(self.fill_mode, "mode_activated"):
            self.fill_mode.mode_activated.connect(self._on_fill_mode_activated)
        if hasattr(self.fill_mode, "mode_deactivated"):
            self.fill_mode.mode_deactivated.connect(
                self._on_fill_mode_deactivated
            )
        if hasattr(self.fill_mode, "current_label_changed"):
            self.fill_mode.current_label_changed.connect(
                self._on_label_changed
            )

    def eventFilter(self, obj: object, event: QtCore.QEvent) -> bool:
        """拦截 person_list 的滚轮事件，向上/向下切换组 ID.

        滚轮切换时默认不进入补全模式；
        仅当“自动锁定目标”勾选后才自动进入补全模式。
        """
        if (
            obj is self.person_list
            and event.type() == QtCore.QEvent.Type.Wheel
        ):
            delta = event.angleDelta().y()
            auto_activate = self.auto_activate_enabled
            if delta > 0:
                self.switch_to_prev_person(activate=auto_activate)
            elif delta < 0:
                self.switch_to_next_person(activate=auto_activate)
            return True
        return super().eventFilter(obj, event)

    # ---------- Data Layer (内联原 data_view / data_operation) ----------

    def _get_person_data(self) -> Dict[int, Dict[str, Any]]:
        """遍历 label_list 获取所有 person 对象数据."""
        person_data: Dict[int, Dict[str, Any]] = {}

        for item in self.label_widget.label_list:
            shape = item.shape()
            if shape.group_id is None:
                continue
            gid = shape.group_id
            if gid not in person_data:
                person_data[gid] = {
                    "completed": 0,
                    "total": len(KEYPOINT_ORDER),
                    "rect": None,
                }
            if shape.label == "person" and shape.shape_type == "rectangle":
                person_data[gid]["rect"] = shape
            if shape.shape_type == "point" and shape.label in KEYPOINT_ORDER:
                person_data[gid]["completed"] += 1

        # 过滤掉既无 person 框也无关键点的 group
        return {
            gid: d
            for gid, d in person_data.items()
            if d["rect"] is not None or d["completed"] > 0
        }

    def _get_keypoint_status(self, group_id: int) -> Set[str]:
        """获取指定 group_id 已完成的关键点标签集合."""
        completed = set()
        for item in self.label_widget.label_list:
            shape = item.shape()
            if (
                shape.group_id == group_id
                and shape.shape_type == "point"
                and shape.label in KEYPOINT_ORDER
            ):
                completed.add(shape.label)
        return completed

    def _sync_gid_filter(self, group_id: int) -> None:
        """设置 group_id 筛选(直接操作 combobox)."""
        if not hasattr(self.label_widget, "gid_filter_combobox"):
            return
        combo = self.label_widget.gid_filter_combobox.gid_box
        gid_text = str(group_id)
        target_index = 0
        for i in range(combo.count()):
            if combo.itemText(i) == gid_text:
                target_index = i
                break
        combo.blockSignals(True)
        combo.setCurrentIndex(target_index)
        combo.blockSignals(False)
        self.label_widget.gid_selection_changed(target_index)

    def _clear_gid_filter(self) -> None:
        """清除 group_id 筛选，显示全部."""
        if not hasattr(self.label_widget, "gid_filter_combobox"):
            return
        combo = self.label_widget.gid_filter_combobox.gid_box
        combo.blockSignals(True)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)
        self.label_widget.gid_selection_changed(0)

    # ---------- Public Actions ----------

    def switch_to_person(self, group_id: int, activate: bool = True) -> None:
        """切换到指定 person 对象."""
        logger.debug(
            f"Switching to person with group_id: {group_id}, activate={activate}"
        )

        # 退出当前 fill mode
        if self.fill_mode.is_active:
            self.fill_mode.deactivate()

        # 设置筛选
        self._sync_gid_filter(group_id)
        self.current_group_id = group_id

        # 同步列表选中状态
        for i in range(self.person_list.count()):
            item = self.person_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == group_id:
                self.person_list.setCurrentItem(item)
                break

        if activate:
            # 激活 fill mode
            success = self.fill_mode.activate(group_id)
            if success:
                self.label_widget.toggle_draw_mode(
                    edit=False, create_mode="point"
                )
                self._update_current_person_info()
            else:
                self._update_current_person_info()
                self._show_hint(
                    f"Group {group_id}: 所有关键点已完成", complete=True
                )
        else:
            self._update_current_person_info()

        # 将焦点还给画布，用户无需再点击一下就能继续标注
        if hasattr(self.label_widget, "canvas"):
            self.label_widget.canvas.setFocus()

    def switch_to_prev_person(self, activate: bool = True) -> None:
        """切换到上一个人."""
        person_data = self._get_person_data()
        if not person_data:
            return
        sorted_gids = sorted(person_data.keys())
        if self.current_group_id is None:
            self.switch_to_person(sorted_gids[-1], activate=activate)
        else:
            try:
                idx = sorted_gids.index(self.current_group_id)
                prev_idx = (idx - 1) % len(sorted_gids)
                self.switch_to_person(sorted_gids[prev_idx], activate=activate)
            except ValueError:
                self.switch_to_person(sorted_gids[0], activate=activate)

    def switch_to_next_person(self, activate: bool = True) -> None:
        """切换到下一个人."""
        person_data = self._get_person_data()
        if not person_data:
            return
        sorted_gids = sorted(person_data.keys())
        if self.current_group_id is None:
            self.switch_to_person(sorted_gids[0], activate=activate)
        else:
            try:
                idx = sorted_gids.index(self.current_group_id)
                next_idx = (idx + 1) % len(sorted_gids)
                self.switch_to_person(sorted_gids[next_idx], activate=activate)
            except ValueError:
                self.switch_to_person(sorted_gids[0], activate=activate)

    def refresh_all(self) -> None:
        """刷新全部数据显示."""
        person_data = self._get_person_data()
        total = len(person_data)
        completed = sum(
            1 for d in person_data.values() if d["completed"] == d["total"]
        )
        incomplete = total - completed

        self.header_label.setText(f"共 {total} 人")
        self.stats_label.setText(
            f"未完成: {incomplete} 人 | 已完成: {completed} 人"
        )

        # 更新人员列表
        self.person_list.clear()
        for gid in sorted(person_data.keys()):
            data = person_data[gid]
            c, t = data["completed"], data["total"]
            item = QtWidgets.QListWidgetItem(f"Group {gid}: {c}/{t}")
            item.setData(Qt.ItemDataRole.UserRole, gid)
            if c == t:
                item.setForeground(QtGui.QColor(0, 128, 0))
            elif c > 0:
                item.setForeground(QtGui.QColor(200, 150, 0))
            else:
                item.setForeground(QtGui.QColor(180, 0, 0))
            self.person_list.addItem(item)

        self._update_current_person_info()

    # ---------- UI Updates ----------

    def _update_current_person_info(self) -> None:
        if self.current_group_id is None:
            self.current_label.setText("未选中对象")
            self.progress_bar.setValue(0)
            self.keypoint_list.clear()
            self.hint_label.setVisible(False)
            return

        person_data = self._get_person_data()
        if self.current_group_id not in person_data:
            self.current_label.setText("未选中对象")
            self.progress_bar.setValue(0)
            self.keypoint_list.clear()
            self.hint_label.setVisible(False)
            self.current_group_id = None
            return

        data = person_data[self.current_group_id]
        self.current_label.setText(f"当前对象: Group {self.current_group_id}")
        self.progress_bar.setValue(data["completed"])
        self._update_hint_label()
        self._update_keypoint_list()

    def _update_keypoint_list(self) -> None:
        self.keypoint_list.clear()
        if self.current_group_id is None:
            return

        existing = self._get_keypoint_status(self.current_group_id)
        current_active = (
            self.fill_mode.current_label if self.fill_mode.is_active else None
        )

        # 已完成
        completed_kps = [kp for kp in KEYPOINT_ORDER if kp in existing]
        if completed_kps:
            header = QtWidgets.QListWidgetItem("✅ 已完成")
            header.setForeground(QtGui.QColor(100, 100, 100))
            header.setFlags(header.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.keypoint_list.addItem(header)
            for kp in completed_kps:
                it = QtWidgets.QListWidgetItem(f"  • {kp}")
                it.setForeground(QtGui.QColor(0, 150, 0))
                it.setData(Qt.ItemDataRole.UserRole, kp)
                self.keypoint_list.addItem(it)

        # 待标注
        missing = [kp for kp in KEYPOINT_ORDER if kp not in existing]
        if missing:
            header = QtWidgets.QListWidgetItem("⏳ 待标注")
            header.setForeground(QtGui.QColor(100, 100, 100))
            header.setFlags(header.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.keypoint_list.addItem(header)
            for kp in missing:
                it = QtWidgets.QListWidgetItem()
                it.setData(Qt.ItemDataRole.UserRole, kp)
                if kp == current_active:
                    it.setText(f"→ {kp} (当前)")
                    it.setForeground(QtGui.QColor(255, 255, 255))
                    it.setBackground(QtGui.QColor(33, 150, 243))
                    font = it.font()
                    font.setBold(True)
                    it.setFont(font)
                else:
                    it.setText(f"  • {kp}")
                    it.setForeground(QtGui.QColor(100, 100, 100))
                self.keypoint_list.addItem(it)

        # 滚动到当前项
        if current_active:
            for i in range(self.keypoint_list.count()):
                it = self.keypoint_list.item(i)
                if it.data(Qt.ItemDataRole.UserRole) == current_active:
                    self.keypoint_list.setCurrentItem(it)
                    self.keypoint_list.scrollToItem(it)
                    break

    def _update_hint_label(self) -> None:
        if self.current_group_id is None:
            self.hint_label.setVisible(False)
            return

        completed = self._get_keypoint_status(self.current_group_id)
        next_kp = None
        for kp in KEYPOINT_ORDER:
            if kp not in completed:
                next_kp = kp
                break

        if next_kp:
            self._show_hint(f"提示: 下一个待标注点: {next_kp}", complete=False)
        else:
            self._show_hint("✓ 所有关键点已完成!", complete=True)

    def _show_hint(self, text: str, complete: bool = False) -> None:
        self.hint_label.setText(text)
        if complete:
            self.hint_label.setStyleSheet(
                "background-color: #e8f4e8; "
                "border: 1px solid #4CAF50; "
                "border-radius: 3px; "
                "padding: 5px; "
                "color: #1b5e20; "
                "font-weight: bold; "
                "font-size: 10pt;"
            )
        else:
            self.hint_label.setStyleSheet(
                "background-color: #e8f4e8; "
                "border: 1px solid #4CAF50; "
                "border-radius: 3px; "
                "padding: 5px; "
                "color: #2e7d32; "
                "font-size: 10pt;"
            )
        self.hint_label.setVisible(True)

    # ---------- Event Handlers ----------

    def _on_person_selected(self, item: QtWidgets.QListWidgetItem) -> None:
        """单击：仅切换画面目标（设置 gid filter），不进入补全模式."""
        gid = item.data(Qt.ItemDataRole.UserRole)
        if gid is None:
            return
        # 若当前处于补全模式则先退出，避免状态冲突
        if self.fill_mode.is_active:
            self.fill_mode.deactivate()
        self._sync_gid_filter(gid)
        self.current_group_id = gid
        self._update_current_person_info()

        # 将焦点还给画布，用户无需再点击一下就能继续标注
        if hasattr(self.label_widget, "canvas"):
            self.label_widget.canvas.setFocus()

    def _on_person_activated(self, item: QtWidgets.QListWidgetItem) -> None:
        """双击：切换画面目标并进入补全模式."""
        gid = item.data(Qt.ItemDataRole.UserRole)
        if gid is not None:
            self.switch_to_person(gid)

    def _on_keypoint_clicked(self, item: QtWidgets.QListWidgetItem) -> None:
        label = item.data(Qt.ItemDataRole.UserRole)
        if label and self.fill_mode.is_active:
            if self.fill_mode.jump_to_label(label):
                logger.debug(f"Jumped to label via click: {label}")

    def _on_fill_mode_activated(
        self, group_id: int, missing_count: int
    ) -> None:
        self.current_group_id = group_id
        self._update_current_person_info()

    def _on_fill_mode_deactivated(self, last_group_id: int) -> None:
        # 不清除 current_group_id，保持对当前目标的引用
        self._update_current_person_info()
        # 恢复选择模式
        if hasattr(self.label_widget, "toggle_draw_mode"):
            self.label_widget.toggle_draw_mode(
                edit=True, create_mode="rectangle"
            )

    def _on_label_changed(self, label: str, index: int, total: int) -> None:
        self._update_keypoint_list()

    def _on_auto_activate_changed(self, state: int) -> None:
        """Handle auto-activation checkbox change."""
        enabled = state == Qt.CheckState.Checked.value
        if hasattr(self.label_widget, "_config"):
            self.label_widget._config["auto_activate_keypoint_fill"] = enabled
        logger.debug(f"Auto-activation set to: {enabled}")

    def _load_settings(self) -> None:
        """Load auto-activation setting."""
        if hasattr(self.label_widget, "_config"):
            enabled = self.label_widget._config.get(
                "auto_activate_keypoint_fill", False
            )
            self.auto_activate_cb.setChecked(enabled)

    @property
    def auto_activate_enabled(self) -> bool:
        """Check if auto-activation is enabled."""
        return self.auto_activate_cb.isChecked()


class KeypointToolWindow(QtWidgets.QWidget):
    """
    关键点标注工具窗口 —— 独立浮动窗口。

    去除 3.3.0 的单例模式，由 label_widget 直接持有实例。
    """

    def __init__(
        self,
        fill_mode: Any,
        label_widget: Any,
        parent: Optional[QtWidgets.QWidget] = None,
    ):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle(self.tr("Keypoint Fill Tool"))
        self.resize(400, 600)

        self.content_widget = KeypointDockContent(
            fill_mode, label_widget, self
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.content_widget)

        logger.debug("KeypointToolWindow initialized")

    def refresh_all(self) -> None:
        self.content_widget.refresh_all()

    def switch_to_prev_person(self) -> None:
        self.content_widget.switch_to_prev_person()

    def switch_to_next_person(self) -> None:
        self.content_widget.switch_to_next_person()

    def closeEvent(self, event) -> None:
        """关闭时仅隐藏，不销毁，便于再次打开."""
        self.hide()
