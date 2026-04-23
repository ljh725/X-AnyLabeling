"""
Keypoint Fill Mode Module

A lightweight adapter that provides keypoint completion functionality.
This module enables real-time keypoint labeling with automatic group_id
inheritance and missing label calculation.

For X-AnyLabeling 4.0.0-beta.4 (PyQt6).

Classes:
    - KeypointFillMode: Manages group_id binding and missing label calculation
"""

import logging
import re
from typing import Any, Callable, List, Optional, Set

from PyQt6 import QtCore
from PyQt6.QtCore import Qt

logger = logging.getLogger(__name__)


class _LabelCycle(QtCore.QObject):
    """
    Lightweight label cycler — embedded replacement for DigitLabelCycleManager.

    Provides just enough functionality for KeypointFillMode:
    - parse comma/semicolon-separated label strings
    - activate / deactivate / advance / next / prev / jump
    - track current index and emit label_changed signal
    """

    label_changed = QtCore.pyqtSignal(str, int, int)  # (label, index, total)
    cycle_activated = QtCore.pyqtSignal(list)  # (labels_list)
    cycle_deactivated = QtCore.pyqtSignal()

    LABEL_SEPARATOR_PATTERN = r"[,;，]"
    DEFAULT_LABEL = "object"

    def __init__(
        self,
        status_callback: Optional[Callable[[str, int], None]] = None,
        tr_callback: Optional[Callable[[str], str]] = None,
        label_setter: Optional[Callable[[str], None]] = None,
    ):
        super().__init__()
        self._status = status_callback
        self._tr = tr_callback or (lambda x: x)
        self._label_setter = label_setter
        self._labels: List[str] = []
        self._index: int = -1

    # ---------- Properties ----------

    @property
    def is_active(self) -> bool:
        return len(self._labels) > 0

    @property
    def is_multi_label(self) -> bool:
        return len(self._labels) > 1

    @property
    def labels(self) -> List[str]:
        return self._labels.copy()

    @property
    def current_label(self) -> Optional[str]:
        if not self.is_active or self._index < 0:
            return None
        return self._labels[self._index]

    @property
    def current_index(self) -> int:
        return self._index

    @property
    def total_count(self) -> int:
        return len(self._labels)

    # ---------- Core Methods ----------

    def _parse(self, label_string: str) -> List[str]:
        if not label_string:
            return [self.DEFAULT_LABEL]
        labels = [
            s.strip()
            for s in re.split(self.LABEL_SEPARATOR_PATTERN, label_string)
            if s.strip()
        ]
        return labels if labels else [self.DEFAULT_LABEL]

    def activate(self, label_string: str) -> str:
        self._labels = self._parse(label_string)
        self._index = 0
        current = self._labels[0]
        if self._label_setter:
            self._label_setter(current)
        self.cycle_activated.emit(self._labels)
        self.label_changed.emit(current, 0, len(self._labels))
        return current

    def deactivate(self) -> None:
        if self.is_active:
            logger.debug(f"Cycle deactivated: was {self._labels}")
        self._labels = []
        self._index = -1
        self.cycle_deactivated.emit()

    def advance(self) -> Optional[str]:
        if not self.is_active:
            return None
        if not self.is_multi_label:
            return self.current_label
        self._index = (self._index + 1) % len(self._labels)
        new_label = self._labels[self._index]
        if self._label_setter:
            self._label_setter(new_label)
        self.label_changed.emit(new_label, self._index, len(self._labels))
        return new_label

    def next(self, show_status: bool = True) -> Optional[str]:
        if not self.is_active:
            return None
        self._index = (self._index + 1) % len(self._labels)
        new_label = self._labels[self._index]
        if self._label_setter:
            self._label_setter(new_label)
        if show_status and self._status:
            self._status(
                self._tr("Next label: {label} ({idx}/{total})").format(
                    label=new_label, idx=self._index + 1, total=len(self._labels)
                ),
                1500,
            )
        self.label_changed.emit(new_label, self._index, len(self._labels))
        return new_label

    def prev(self, show_status: bool = True) -> Optional[str]:
        if not self.is_active:
            return None
        self._index = (self._index - 1) % len(self._labels)
        new_label = self._labels[self._index]
        if self._label_setter:
            self._label_setter(new_label)
        if show_status and self._status:
            self._status(
                self._tr("Previous label: {label} ({idx}/{total})").format(
                    label=new_label, idx=self._index + 1, total=len(self._labels)
                ),
                1500,
            )
        self.label_changed.emit(new_label, self._index, len(self._labels))
        return new_label

    def jump(self, target_index: int, show_status: bool = True) -> Optional[str]:
        if not self.is_active:
            return None
        zero_based = target_index - 1
        if not 0 <= zero_based < len(self._labels):
            if self._status:
                self._status(
                    self._tr("Invalid index: {idx}, valid range: 1-{max}").format(
                        idx=target_index, max=len(self._labels)
                    ),
                    2000,
                )
            return None
        self._index = zero_based
        new_label = self._labels[self._index]
        if self._label_setter:
            self._label_setter(new_label)
        if show_status and self._status:
            self._status(
                self._tr("Jumped to label: {label} ({idx}/{total})").format(
                    label=new_label, idx=self._index + 1, total=len(self._labels)
                ),
                1500,
            )
        self.label_changed.emit(new_label, self._index, len(self._labels))
        return new_label


class KeypointFillMode(QtCore.QObject):
    """
    关键点补标模式

    职责:
    - 管理 group_id 绑定
    - 计算缺失标签列表
    - 委托给内嵌 _LabelCycle 处理标签循环

    Signals:
        mode_activated: 补标模式激活时发出 (group_id, missing_count)
        mode_deactivated: 补标模式退出时发出 (last_group_id)
        current_label_changed: 当前标签变更信号，用于UI高亮同步 (label, index, total)
    """

    # COCO 17 关键点标准顺序（简写格式）
    KEYPOINT_ORDER: List[str] = [
        "nose", "l_eye", "r_eye", "l_ear", "r_ear",
        "l_sho", "r_sho", "l_elb", "r_elb", "l_wri",
        "r_wri", "l_hip", "r_hip", "l_knee", "r_knee",
        "l_ank", "r_ank",
    ]

    PERSON_LABEL: str = "person"

    mode_activated = QtCore.pyqtSignal(int, int)  # (group_id, missing_count)
    mode_deactivated = QtCore.pyqtSignal(int)  # (last_group_id)
    current_label_changed = QtCore.pyqtSignal(str, int, int)  # (label, index, total)

    def __init__(
        self,
        shapes_getter: Callable[[], List[Any]],
        status_callback: Optional[Callable[[str, int], None]] = None,
        tr_callback: Optional[Callable[[str], str]] = None,
        label_setter: Optional[Callable[[str], None]] = None,
    ):
        super().__init__()

        self._cycle = _LabelCycle(
            status_callback=status_callback,
            tr_callback=tr_callback,
            label_setter=label_setter,
        )
        self._cycle.label_changed.connect(self.current_label_changed.emit)

        self._get_shapes = shapes_getter
        self._status = status_callback
        self._tr = tr_callback or (lambda x: x)

        self._active: bool = False
        self._target_group_id: Optional[int] = None
        self._missing_labels: List[str] = []

        logger.debug("KeypointFillMode initialized")

    # ---------- Properties ----------

    @property
    def is_active(self) -> bool:
        return self._active and self._cycle.is_active

    @property
    def target_group_id(self) -> Optional[int]:
        return self._target_group_id

    @property
    def current_label(self) -> Optional[str]:
        if not self._active:
            return None
        return self._cycle.current_label

    @property
    def current_index(self) -> int:
        if not self._active:
            return 0
        return self._cycle.current_index

    @property
    def total_count(self) -> int:
        return len(self._missing_labels)

    @property
    def remaining_count(self) -> int:
        if not self._active:
            return 0
        return self._cycle.total_count - self._cycle.current_index

    # ---------- Public Methods ----------

    def activate(self, group_id: int) -> bool:
        """
        Activate fill mode for the specified group_id.

        Returns True if activation successful, False if no missing keypoints.
        """
        if group_id is None:
            if self._status:
                self._status(self._tr("Cannot activate: group_id is None"), 2000)
            return False

        existing_labels = self._get_existing_labels(group_id)
        self._missing_labels = [
            kp for kp in self.KEYPOINT_ORDER if kp not in existing_labels
        ]

        if not self._missing_labels:
            if self._status:
                self._status(
                    self._tr("Group {gid}: All keypoints complete").format(
                        gid=group_id
                    ),
                    2000,
                )
            return False

        label_string = ",".join(self._missing_labels)
        self._cycle.activate(label_string)

        self._active = True
        self._target_group_id = group_id

        logger.info(
            f"KeypointFillMode activated: gid={group_id}, "
            f"missing={len(self._missing_labels)}"
        )

        self.mode_activated.emit(group_id, len(self._missing_labels))
        self._show_status()
        return True

    def deactivate(self) -> None:
        """Deactivate fill mode."""
        if not self._active:
            return

        self._cycle.deactivate()
        self._active = False
        old_group_id = self._target_group_id
        self._target_group_id = None
        self._missing_labels = []

        logger.info(f"KeypointFillMode deactivated (old_group_id={old_group_id})")
        self.mode_deactivated.emit(old_group_id if old_group_id is not None else -1)

        if self._status:
            self._status(self._tr("Keypoint fill mode exited"), 2000)

    def get_next_label_and_group_id(self) -> tuple:
        """
        Get the next label and group_id to assign.

        Returns:
            Tuple of (label, group_id), or (None, None) if not active.
        """
        if not self.is_active:
            return None, None
        return self._cycle.current_label, self._target_group_id

    def advance(self) -> Optional[str]:
        """
        Advance to the next missing label after a point is created.

        Returns:
            The new current label, or None if complete.
        """
        if not self.is_active:
            return None

        if self._cycle.current_index >= self._cycle.total_count - 1:
            if self._status:
                self._status(
                    self._tr("group_id {gid}: All keypoints filled!").format(
                        gid=self._target_group_id
                    ),
                    3000,
                )
            self.deactivate()
            return None

        new_label = self._cycle.advance()
        self._show_status()
        return new_label

    def jump_to_label(self, label: str) -> bool:
        """
        Jump to a specific label in the cycle.

        Returns:
            True if jump successful, False otherwise.
        """
        if not self.is_active:
            return False
        if label not in self._missing_labels:
            return False
        index = self._missing_labels.index(label)
        self._cycle.jump(index + 1)
        self._show_status()
        return True

    def refresh(self) -> None:
        """
        Refresh the missing labels list based on current shapes.

        Call this after undo/redo or external shape modifications.
        """
        if not self._active or self._target_group_id is None:
            return

        existing_labels = self._get_existing_labels(self._target_group_id)
        new_missing = [kp for kp in self.KEYPOINT_ORDER if kp not in existing_labels]

        if not new_missing:
            if self._status:
                self._status(
                    self._tr("Group {gid}: All keypoints complete!").format(
                        gid=self._target_group_id
                    ),
                    3000,
                )
            self.deactivate()
            return

        if new_missing != self._missing_labels:
            self._missing_labels = new_missing
            label_string = ",".join(new_missing)
            self._cycle.activate(label_string)
            self._show_status()

    def get_status_message(self) -> str:
        """Get a formatted status message for the current state."""
        if not self.is_active:
            return ""
        current = self._cycle.current_label
        index = self._cycle.current_index + 1
        total = self._cycle.total_count
        return self._tr(
            "[Fill Mode] Group {gid} | {label} ({index}/{total}) | ] skip, [ back"
        ).format(gid=self._target_group_id, label=current, index=index, total=total)

    # ---------- Private Helpers ----------

    def _get_existing_labels(self, group_id: int) -> Set[str]:
        shapes = self._get_shapes()
        existing = set()
        for shape in shapes:
            if (
                getattr(shape, "group_id", None) == group_id
                and getattr(shape, "shape_type", None) == "point"
                and getattr(shape, "label", None) in self.KEYPOINT_ORDER
            ):
                existing.add(shape.label)
        return existing

    def _show_status(self) -> None:
        if self._status:
            self._status(self.get_status_message(), 10000)
