"""Tests for persistent review session lifecycle."""

from anylabeling.views.labeling.review_refinement.session import (
    RefinementSessionController,
    RefinementSessionState,
)


def test_session_preserves_identity_but_clears_target_on_image_change() -> (
    None
):
    """Cross-image persistence must not carry the active target."""
    session = RefinementSessionController(persist_across_images=True)
    session.start("image-a")
    session.select_target("target-a")
    session.image_changed("image-b")
    assert session.state is RefinementSessionState.ACTIVE
    assert session.image_token == "image-b"
    assert session.target_token is None


def test_session_pause_and_stop_are_transient_safe() -> None:
    """Focus loss pauses, while stop clears all session identity."""
    session = RefinementSessionController()
    session.start("image-a")
    session.focus_changed(False)
    assert session.state is RefinementSessionState.PAUSED
    session.stop()
    assert session.state is RefinementSessionState.INACTIVE
    assert session.image_token is None
