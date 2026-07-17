"""State model for the stable rectangle-refinement preview."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from PyQt6 import QtCore

from .shape import Shape


class StablePreviewMode(str, Enum):
    """Mutually exclusive stable-preview content modes."""

    NONE = "none"
    TARGET = "target"
    DRAG_LOCKED = "drag_locked"


@dataclass
class StablePreviewState:
    """Own transient preview content and window-interaction state."""

    shape: Optional[Shape] = None
    mode: StablePreviewMode = StablePreviewMode.NONE
    locked_rect: Optional[QtCore.QRectF] = None
    active_edge_name: Optional[str] = None
    target_rect: Optional[QtCore.QRectF] = None
    window_rect: Optional[QtCore.QRectF] = None
    window_dragging: bool = False
    window_resizing: bool = False
    window_press_pos: Optional[QtCore.QPointF] = None
    window_press_rect: Optional[QtCore.QRectF] = None

    def begin_target(self, shape: Shape, rect: QtCore.QRectF) -> None:
        """Enter target-preview mode and clear drag-locked content."""
        self.shape = shape
        self.mode = StablePreviewMode.TARGET
        self.target_rect = QtCore.QRectF(rect)
        self.locked_rect = None
        self.active_edge_name = None

    def begin_drag_locked(
        self, shape: Shape, edge_name: str, rect: QtCore.QRectF
    ) -> None:
        """Enter drag-locked mode and clear target content."""
        self.shape = shape
        self.mode = StablePreviewMode.DRAG_LOCKED
        self.locked_rect = QtCore.QRectF(rect)
        self.active_edge_name = edge_name
        self.target_rect = None

    def clear_drag_locked(self) -> None:
        """Clear drag-locked content when that mode is active."""
        self.locked_rect = None
        self.active_edge_name = None
        if self.mode is StablePreviewMode.DRAG_LOCKED:
            self.mode = StablePreviewMode.NONE
            self.shape = None

    def clear_target(self) -> None:
        """Clear target content when that mode is active."""
        self.target_rect = None
        if self.mode is StablePreviewMode.TARGET:
            self.mode = StablePreviewMode.NONE
            self.shape = None

    def begin_window_interaction(
        self,
        press_pos: QtCore.QPointF,
        press_rect: QtCore.QRectF,
        *,
        dragging: bool,
        resizing: bool,
    ) -> None:
        """Capture preview-window move or resize transaction state."""
        self.window_press_pos = QtCore.QPointF(press_pos)
        self.window_press_rect = QtCore.QRectF(press_rect)
        self.window_dragging = dragging
        self.window_resizing = resizing

    def end_window_interaction(self) -> None:
        """Clear preview-window move and resize transaction state."""
        self.window_dragging = False
        self.window_resizing = False
        self.window_press_pos = None
        self.window_press_rect = None

    def clear_all(self) -> None:
        """Return preview content to none and end window interaction."""
        self.shape = None
        self.mode = StablePreviewMode.NONE
        self.locked_rect = None
        self.active_edge_name = None
        self.target_rect = None
        self.end_window_interaction()
