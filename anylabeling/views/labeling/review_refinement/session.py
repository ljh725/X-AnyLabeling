"""Pure state machine for a persistent rectangle-review session."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RefinementSessionState(str, Enum):
    """Stable states of the opt-in review session."""

    INACTIVE = "inactive"
    ACTIVE = "active"
    PAUSED = "paused"


@dataclass
class RefinementSessionController:
    """Keep persistent session state separate from transient edge state."""

    persist_across_images: bool = True
    state: RefinementSessionState = RefinementSessionState.INACTIVE
    image_token: str | None = None
    target_token: str | None = None

    def start(self, image_token: str) -> None:
        """Start or resume a session for an image token."""
        self.state = RefinementSessionState.ACTIVE
        self.image_token = str(image_token)

    def select_target(self, target_token: str | None) -> None:
        """Replace the current target without carrying transient geometry."""
        self.target_token = None if target_token is None else str(target_token)

    def image_changed(self, image_token: str) -> None:
        """Switch images, preserving the session only when configured."""
        if not self.persist_across_images:
            self.stop()
            return
        self.image_token = str(image_token)
        self.target_token = None

    def focus_changed(self, focused: bool) -> None:
        """Pause active time while retaining the session identity."""
        if self.state is RefinementSessionState.INACTIVE:
            return
        self.state = (
            RefinementSessionState.ACTIVE
            if focused
            else RefinementSessionState.PAUSED
        )

    def stop(self) -> None:
        """End the session and clear its target/image identity."""
        self.state = RefinementSessionState.INACTIVE
        self.image_token = None
        self.target_token = None
