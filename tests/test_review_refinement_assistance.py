"""Tests for request-only rectangle review assistance."""

from anylabeling.views.labeling.review_refinement.assistance import (
    CandidatePreviewController,
    EdgeCandidateService,
    build_loupe_roi,
)


def test_loupe_roi_is_bounded_and_coordinate_invariant() -> None:
    """ROI clipping must not rewrite the requested image center."""
    roi = build_loupe_roi((1.5, 2.0), (20, 20), radius_px=4)
    assert roi.x == 0
    assert roi.y == 0
    assert roi.center_x == 1.5
    assert roi.center_y == 2.0


def test_candidate_service_requires_explicit_request() -> None:
    """Construction is inert; only request computes a candidate."""
    service = EdgeCandidateService()
    candidate = service.request("left", [0, 0, 10, 0], 5)
    assert candidate is not None
    assert candidate.coordinate == 6.5
    assert candidate.confidence == 1.0


def test_candidate_preview_accept_is_one_transaction() -> None:
    """Reject/cancel have no side effect and accept commits once."""
    service = EdgeCandidateService()
    candidate = service.request("right", [0, 4, 0], 10)
    controller = CandidatePreviewController()
    controller.show(candidate)
    committed = []
    assert controller.accept(
        lambda value: value.confidence >= 1, committed.append
    )
    assert committed == [candidate]
    assert controller.preview is None
