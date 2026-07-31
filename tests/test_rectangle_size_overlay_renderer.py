"""Tests for the extracted rectangle-size Qt overlay renderer."""

from __future__ import annotations

from PyQt6 import QtGui

from anylabeling.views.labeling.rectangle_size import (
    DimensionViolation,
    RectangleSizeIssue,
)
from anylabeling.views.labeling.widgets.rectangle_size_overlay import (
    RectangleSizeOverlayRenderer,
    RectangleSizeOverlayRequest,
    issue_overlay_lines,
    merge_overlay_requests,
    overlay_request_from_issue,
)


def _issue(candidate_id="person-1") -> RectangleSizeIssue:
    """Return one issue with both dimensions failing."""
    return RectangleSizeIssue(
        candidate_id=candidate_id,
        shape_index=0,
        label="person",
        bbox=(50.0, 80.0, 70.0, 100.0),
        width=20.0,
        height=20.0,
        violations=(
            DimensionViolation(
                dimension="width",
                actual_px=20.0,
                threshold_px=36.0,
            ),
            DimensionViolation(
                dimension="height",
                actual_px=20.0,
                threshold_px=36.0,
            ),
        ),
    )


def _render(
    renderer,
    requests,
    *,
    scale=1.0,
):
    """Render requests into a transparent image and return image/placements."""
    image = QtGui.QImage(
        600,
        500,
        QtGui.QImage.Format.Format_ARGB32_Premultiplied,
    )
    image.fill(0)
    painter = QtGui.QPainter(image)
    painter.scale(scale, scale)
    original_transform = painter.transform()
    placements = renderer.render(
        painter,
        requests,
        (0.0, 0.0, 140.0, 120.0),
    )
    restored_transform = painter.transform()
    painter.end()
    return image, placements, original_transform, restored_transform


def test_issue_formatter_aggregates_category_and_both_dimensions() -> None:
    """Each shape should produce one prompt containing every failed dimension."""
    lines = issue_overlay_lines(_issue())

    assert lines[0] == "person  W 20.0 px  H 20.0 px"
    assert "W 20.0 px <= 36 px" in lines[1]
    assert "H 20.0 px <= 36 px" in lines[1]


def test_request_from_issue_preserves_identity_geometry_and_label_rect() -> (
    None
):
    """Issue adaptation must remain immutable and reconnectable."""
    issue = _issue()
    request = overlay_request_from_issue(
        issue,
        label_rect=(50.0, 60.0, 80.0, 14.0),
    )

    assert request.candidate_id == issue.candidate_id
    assert request.bbox == issue.bbox
    assert request.label_rect == (50.0, 60.0, 80.0, 14.0)
    assert request.warning


def test_renderer_draws_background_and_restores_painter_transform(
    qapp,
) -> None:
    """Rendering should produce pixels without leaking painter state."""
    renderer = RectangleSizeOverlayRenderer()
    request = overlay_request_from_issue(_issue())

    image, placements, before, after = _render(renderer, [request])

    assert len(placements) == 1
    x, y, _width, _height = placements[0].rect
    pixel = image.pixelColor(int(x + 2), int(y + 2))
    assert pixel.alpha() > 0
    assert before == after


def test_fixed_box_dimensions_are_zoom_independent(qapp) -> None:
    """Canvas scaling may move the anchor but must not resize the prompt."""
    renderer = RectangleSizeOverlayRenderer()
    request = overlay_request_from_issue(_issue())

    _image1, placements1, _before1, _after1 = _render(
        renderer,
        [request],
        scale=1.0,
    )
    _image4, placements4, _before4, _after4 = _render(
        renderer,
        [request],
        scale=4.0,
    )

    assert placements1[0].rect[2:] == placements4[0].rect[2:]


def test_renderer_lays_out_multiple_requests_without_dropping(qapp) -> None:
    """Coincident multi-category warnings should all be painted."""
    renderer = RectangleSizeOverlayRenderer()
    requests = [
        RectangleSizeOverlayRequest(
            candidate_id=index,
            lines=(f"label-{index}  W 20.0 px  H 20.0 px", "W <= 36 px"),
            bbox=(50.0, 80.0, 70.0, 100.0),
        )
        for index in range(3)
    ]

    _image, placements, _before, _after = _render(renderer, requests)

    assert [placement.request.candidate_id for placement in placements] == [
        0,
        1,
        2,
    ]
    assert len({placement.rect[:2] for placement in placements}) == 3


def test_normal_request_uses_same_box_pipeline(qapp) -> None:
    """The extracted renderer must also preserve the legacy neutral style."""
    renderer = RectangleSizeOverlayRenderer()
    request = RectangleSizeOverlayRequest(
        candidate_id="legacy",
        lines=("W 80.0 px  H 60.0 px",),
        bbox=(20.0, 30.0, 100.0, 90.0),
        warning=False,
    )

    _image, placements, _before, _after = _render(renderer, [request])

    assert len(placements) == 1
    assert not placements[0].request.warning


def test_merge_prefers_abnormal_request_for_the_same_shape() -> None:
    """A hovered abnormal shape must not receive a duplicate ordinary box."""
    abnormal = overlay_request_from_issue(_issue())
    normal = RectangleSizeOverlayRequest(
        candidate_id=abnormal.candidate_id,
        lines=("W 20.0 px  H 20.0 px",),
        bbox=abnormal.bbox,
        warning=False,
    )

    merged = merge_overlay_requests(normal, [abnormal])

    assert merged == (abnormal,)


def test_merge_appends_distinct_normal_request_after_abnormal_boxes() -> None:
    """Distinct ordinary context should join the same stable layout pass."""
    abnormal = overlay_request_from_issue(_issue())
    normal = RectangleSizeOverlayRequest(
        candidate_id="hovered-head",
        lines=("W 80.0 px  H 60.0 px",),
        bbox=(100.0, 100.0, 180.0, 160.0),
        warning=False,
    )

    merged = merge_overlay_requests(normal, [abnormal])

    assert merged == (abnormal, normal)
