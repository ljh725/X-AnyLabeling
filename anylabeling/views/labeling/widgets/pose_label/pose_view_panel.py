"""PoseViewPanel — QDockWidget combining settings + color tabs.

Follows the InspectorPanel pattern: a ``QDockWidget`` that is embedded
in the right sidebar via a ``QFrame`` wrapper and toggled from the
View menu.
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6 import QtCore, QtWidgets

from .pose_color_panel import PoseColorPanel
from .pose_config import PoseDisplayConfig
from .pose_settings_panel import PoseSettingsPanel


class PoseViewPanel(QtWidgets.QDockWidget):
    """Dock panel for pose keypoint label display configuration.

    Contains two tabs: display settings and colour configuration.

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
        self.setObjectName("PoseView")
        self.setWindowTitle(self.tr("姿态视图 (Pose View)"))
        self.setMinimumWidth(240)

        self._config = config
        self._on_change = on_change

        tab = QtWidgets.QTabWidget()
        self._settings_tab = PoseSettingsPanel(config, on_change=on_change)
        tab.addTab(self._settings_tab, self.tr("显示设置"))
        self._color_tab = PoseColorPanel(config, on_change=on_change)
        tab.addTab(self._color_tab, self.tr("颜色配置"))

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(tab)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setWidget(scroll)

    def sync_from_config(self) -> None:
        """Refresh all child panel controls from the config."""
        self._settings_tab.sync_from_config()
        self._color_tab.sync_from_config()
