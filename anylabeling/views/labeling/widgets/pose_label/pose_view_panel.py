"""PoseViewPanel — QDockWidget with single-page settings + colors.

Follows the InspectorPanel pattern: a ``QDockWidget`` embedded in the
right sidebar via a ``QFrame`` wrapper, toggled from the View menu.
Both the display-settings section and the colour-configuration section
appear on one scrollable page.
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6 import QtWidgets

from .pose_color_panel import PoseColorPanel
from .pose_config import PoseDisplayConfig
from .pose_settings_panel import PoseSettingsPanel


class PoseViewPanel(QtWidgets.QDockWidget):
    """Dock panel for pose keypoint label display configuration.

    Contains display settings and colour configuration on a single
    scrollable page.

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

        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._settings_panel = PoseSettingsPanel(config, on_change=on_change)
        layout.addWidget(self._settings_panel)

        self._color_panel = PoseColorPanel(config, on_change=on_change)
        layout.addWidget(self._color_panel)

        layout.addStretch()

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setWidget(scroll)

    def sync_from_config(self) -> None:
        """Refresh all child panel controls from the config."""
        self._settings_panel.sync_from_config()
        self._color_panel.sync_from_config()
