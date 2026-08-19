"""Pure feedback view model for rectangle-edge refinement."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewFeedbackSnapshot:
    """Immutable geometry and phase values consumed by UI feedback."""

    edge: str
    phase: str
    original_coord: float
    current_coord: float
    signed_delta: float
    width: float
    height: float
    rejection_reason: str | None = None


def make_feedback_snapshot(
    edge: str,
    phase: str,
    original_coord: float,
    current_coord: float,
    width: float,
    height: float,
    rejection_reason: str | None = None,
) -> ReviewFeedbackSnapshot:
    """Build a consistent snapshot for drag, nudge, commit or cancel state."""
    return ReviewFeedbackSnapshot(
        edge=edge,
        phase=phase,
        original_coord=float(original_coord),
        current_coord=float(current_coord),
        signed_delta=float(current_coord) - float(original_coord),
        width=float(width),
        height=float(height),
        rejection_reason=rejection_reason,
    )
