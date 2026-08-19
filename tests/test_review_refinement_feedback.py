"""Tests for immutable rectangle-refinement feedback snapshots."""

from anylabeling.views.labeling.review_refinement.feedback import (
    make_feedback_snapshot,
)


def test_feedback_snapshot_uses_one_signed_delta_definition() -> None:
    """The displayed delta is always current minus original."""
    snapshot = make_feedback_snapshot("left", "dragging", 10, 8, 20, 30)
    assert snapshot.signed_delta == -2
    assert snapshot.width == 20
    assert snapshot.height == 30
