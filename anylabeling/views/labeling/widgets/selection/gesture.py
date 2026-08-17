"""State machine for Ctrl-assisted canvas selection gestures."""

from dataclasses import dataclass
from enum import Enum


class SelectionGesturePhase(Enum):
    """Transient phases of a Ctrl-assisted selection gesture."""

    IDLE = "idle"
    PENDING = "pending"
    RUBBER_BAND = "rubber_band"


@dataclass
class SelectionGesture:
    """Track click-versus-drag arbitration without mutating selection state."""

    phase: SelectionGesturePhase = SelectionGesturePhase.IDLE
    origin: object = None

    def begin(self, origin) -> None:
        """Start a pending gesture at an image-space point."""
        self.origin = origin
        self.phase = SelectionGesturePhase.PENDING

    def update(self, current, threshold: float) -> bool:
        """Advance to rubber-band mode after moving past ``threshold``."""
        if self.phase is not SelectionGesturePhase.PENDING:
            return self.phase is SelectionGesturePhase.RUBBER_BAND
        if self.origin is None:
            return False
        if (current - self.origin).manhattanLength() >= threshold:
            self.phase = SelectionGesturePhase.RUBBER_BAND
        return self.phase is SelectionGesturePhase.RUBBER_BAND

    @property
    def active(self) -> bool:
        """Return whether a transient gesture is being tracked."""
        return self.phase is not SelectionGesturePhase.IDLE

    @property
    def rubber_band(self) -> bool:
        """Return whether the gesture is currently drawing a selection box."""
        return self.phase is SelectionGesturePhase.RUBBER_BAND

    def reset(self) -> None:
        """Cancel the transient gesture and clear its origin."""
        self.phase = SelectionGesturePhase.IDLE
        self.origin = None
