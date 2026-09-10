"""Transient state model for rectangle-edge interactions."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from PyQt6 import QtCore

from .rect_edge_alignment import RectEdgeRef
from .shape import Shape


class RectEdgePhase(str, Enum):
    """Mutually exclusive mouse phases for direct edge editing."""

    IDLE = "idle"
    HOVER = "hover"
    PENDING = "pending"
    DRAGGING = "dragging"


@dataclass
class RectEdgeInteractionController:
    """Own transient mouse and keyboard rectangle-edge state."""

    hover_edge: Optional[RectEdgeRef] = None
    pending_edge: Optional[RectEdgeRef] = None
    pending_press_pos: Optional[QtCore.QPointF] = None
    pending_image_pos: Optional[QtCore.QPointF] = None
    active_edge: Optional[RectEdgeRef] = None
    drag_start_points: Optional[list[QtCore.QPointF]] = None

    @property
    def phase(self) -> RectEdgePhase:
        """Return the current mouse phase from its complete state payload."""
        if self.active_edge is not None and self.drag_start_points is not None:
            return RectEdgePhase.DRAGGING
        if (
            self.pending_edge is not None
            and self.pending_press_pos is not None
            and self.pending_image_pos is not None
        ):
            return RectEdgePhase.PENDING
        if self.hover_edge is not None:
            return RectEdgePhase.HOVER
        return RectEdgePhase.IDLE

    @property
    def is_dragging(self) -> bool:
        """Return whether a complete active drag payload exists."""
        return self.phase is RectEdgePhase.DRAGGING

    @property
    def has_pending(self) -> bool:
        """Return whether a complete pending payload exists."""
        return self.phase is RectEdgePhase.PENDING

    def set_hover(self, edge: Optional[RectEdgeRef]) -> None:
        """Set the currently hovered rectangle edge."""
        self.hover_edge = edge

    def begin_pending(
        self,
        edge: RectEdgeRef,
        press_pos: QtCore.QPointF,
        image_pos: QtCore.QPointF,
    ) -> None:
        """Enter pending phase for a pressed edge."""
        self.active_edge = None
        self.drag_start_points = None
        self.hover_edge = edge
        self.pending_edge = edge
        self.pending_press_pos = QtCore.QPointF(press_pos)
        self.pending_image_pos = QtCore.QPointF(image_pos)

    def start_drag(
        self, edge: RectEdgeRef, start_points: list[QtCore.QPointF]
    ) -> None:
        """Promote a pending edge to an active drag transaction."""
        self.clear_pending()
        self.active_edge = edge
        self.drag_start_points = [
            QtCore.QPointF(point) for point in start_points
        ]

    def refresh_active(self, edge: RectEdgeRef) -> None:
        """Replace the active edge geometry without changing drag phase."""
        if self.active_edge is None:
            raise RuntimeError("Cannot refresh an edge without an active edge")
        self.active_edge = edge

    def clear_pending(self) -> None:
        """Clear the complete pending payload."""
        self.pending_edge = None
        self.pending_press_pos = None
        self.pending_image_pos = None

    def clear_mouse(self) -> None:
        """Return the mouse interaction to idle phase."""
        self.hover_edge = None
        self.active_edge = None
        self.drag_start_points = None
        self.clear_pending()

    def cancel_drag(
        self,
    ) -> Optional[tuple[Shape, list[QtCore.QPointF]]]:
        """Return a geometry restore payload and reset mouse state."""
        if not self.is_dragging:
            return None
        assert self.active_edge is not None
        assert self.drag_start_points is not None
        restore = (
            self.active_edge.shape,
            [QtCore.QPointF(point) for point in self.drag_start_points],
        )
        self.clear_mouse()
        return restore

    def clear_all(self) -> None:
        """Clear all rectangle-edge interaction state."""
        self.clear_mouse()
