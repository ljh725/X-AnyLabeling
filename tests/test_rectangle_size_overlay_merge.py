"""Canvas tests for merged ordinary and abnormal rectangle overlays."""

from __future__ import annotations

from PyQt6 import QtCore

import pytest

from anylabeling.views.labeling.rectangle_size import (
    DimensionViolation,
    RectangleSizeIssue,
)
from anylabeling.views.labeling.widgets.canvas import Canvas
from anylabeling.views.labeling.shape import Shape


def _rectangle(
    label: str,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
) -> Shape:
    """Return one closed rectangle."""
    shape = Shape(label=label, shape_type="rectangle")
    shape.points = [
        QtCore.QPointF(x, y),
        QtCore.QPointF(x + width, y),
        QtCore.QPointF(x + width, y + height),
        QtCore.QPointF(x, y + height),
    ]
    shape.close()
    return shape


def _issue(
    shape: Shape,
    shape_index: int,
    *,
    threshold: float = 36.0,
) -> RectangleSizeIssue:
    """Build one width-and-height issue for a real shape."""
    x_values = [point.x() for point in shape.points]
    y_values = [point.y() for point in shape.points]
    bbox = (
        min(x_values),
        min(y_values),
        max(x_values),
        max(y_values),
    )
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    return RectangleSizeIssue(
        candidate_id=id(shape),
        shape_index=shape_index,
        label=shape.label,
        bbox=bbox,
        width=width,
        height=height,
        violations=(
            DimensionViolation("width", width, threshold),
            DimensionViolation("height", height, threshold),
        ),
    )


@pytest.fixture
def merge_canvas(canvas):
    """Return a Canvas configured for combined overlay request inspection."""
    canvas.show_rectangle_pixels = True
    canvas.show_rectangle_size_violations = True
    canvas.show_labels = False
    return canvas


def test_hovered_abnormal_shape_produces_only_one_warning_request(
    merge_canvas,
) -> None:
    """The same candidate must not create ordinary and abnormal duplicates."""
    shape = _rectangle("person", x=20.0, y=30.0, width=20.0, height=20.0)
    merge_canvas.load_shapes([shape], store_backup=False)
    merge_canvas._set_selected_shapes([shape], source="canvas")
    issue = _issue(shape, 0)
    merge_canvas.set_rectangle_size_issues([issue])

    requests = merge_canvas._combined_size_overlay_requests()

    assert len(requests) == 1
    assert requests[0].candidate_id == id(shape)
    assert requests[0].warning
    assert requests[0].lines[0].startswith("person")


def test_custom_candidate_lookup_still_deduplicates_selected_shape(
    merge_canvas,
) -> None:
    """Non-default Monitor identities should reconnect through shape_lookup."""
    shape = _rectangle("person", x=20.0, y=30.0, width=20.0, height=20.0)
    merge_canvas.load_shapes([shape], store_backup=False)
    merge_canvas._set_selected_shapes([shape], source="canvas")
    source = _issue(shape, 0)
    issue = RectangleSizeIssue(
        candidate_id="custom-person",
        shape_index=source.shape_index,
        label=source.label,
        bbox=source.bbox,
        width=source.width,
        height=source.height,
        violations=source.violations,
    )
    merge_canvas.set_rectangle_size_issues(
        [issue],
        shape_lookup={"custom-person": shape},
    )

    requests = merge_canvas._combined_size_overlay_requests()

    assert len(requests) == 1
    assert requests[0].candidate_id == "custom-person"


def test_distinct_normal_and_abnormal_shapes_share_one_request_sequence(
    merge_canvas,
) -> None:
    """An unrelated selected rectangle should remain after abnormal requests."""
    abnormal_shape = _rectangle(
        "person",
        x=20.0,
        y=30.0,
        width=20.0,
        height=20.0,
    )
    normal_shape = _rectangle(
        "head",
        x=100.0,
        y=100.0,
        width=80.0,
        height=60.0,
    )
    merge_canvas.load_shapes(
        [abnormal_shape, normal_shape],
        store_backup=False,
    )
    merge_canvas._set_selected_shapes([normal_shape], source="canvas")
    issue = _issue(abnormal_shape, 0)
    merge_canvas.set_rectangle_size_issues([issue])

    requests = merge_canvas._combined_size_overlay_requests()

    assert [request.candidate_id for request in requests] == [
        id(abnormal_shape),
        id(normal_shape),
    ]
    assert requests[0].warning
    assert not requests[1].warning


def test_draw_submits_combined_requests_in_one_renderer_call(
    merge_canvas,
) -> None:
    """Ordinary and abnormal boxes must participate in one layout operation."""
    abnormal_shape = _rectangle(
        "person",
        x=20.0,
        y=30.0,
        width=20.0,
        height=20.0,
    )
    normal_shape = _rectangle(
        "head",
        x=100.0,
        y=100.0,
        width=80.0,
        height=60.0,
    )
    merge_canvas.load_shapes(
        [abnormal_shape, normal_shape],
        store_backup=False,
    )
    merge_canvas._set_selected_shapes([normal_shape], source="canvas")
    merge_canvas.set_rectangle_size_issues([_issue(abnormal_shape, 0)])
    calls = []

    class RecordingRenderer:
        """Capture render arguments without requiring a paint device."""

        def render(
            self,
            painter: object,
            requests: tuple,
            image_viewport: tuple,
        ) -> tuple:
            """Record one combined render call."""
            calls.append((painter, requests, image_viewport))
            return ()

    merge_canvas._rectangle_size_overlay_renderer = RecordingRenderer()
    painter_token = object()

    merge_canvas._draw_size_overlay(painter_token)

    assert len(calls) == 1
    assert len(calls[0][1]) == 2
    assert calls[0][0] is painter_token


def test_abnormal_overlay_is_independent_from_ordinary_pixel_toggle(
    merge_canvas,
) -> None:
    """Turning off ordinary W/H display must not suppress active violations."""
    shape = _rectangle("person", x=20.0, y=30.0, width=20.0, height=20.0)
    merge_canvas.load_shapes([shape], store_backup=False)
    merge_canvas.set_rectangle_size_issues([_issue(shape, 0)])
    merge_canvas.show_rectangle_pixels = False

    requests = merge_canvas._combined_size_overlay_requests()

    assert len(requests) == 1
    assert requests[0].warning


def test_disabled_violation_feature_preserves_legacy_small_person_warning(
    canvas,
) -> None:
    """The old strict small-person prompt remains when proactive mode is off."""
    shape = _rectangle("person", x=20.0, y=30.0, width=20.0, height=20.0)
    canvas.load_shapes([shape], store_backup=False)
    canvas._set_selected_shapes([shape], source="canvas")
    canvas.show_rectangle_pixels = True
    canvas.show_rectangle_size_violations = False

    requests = canvas._combined_size_overlay_requests()

    assert len(requests) == 1
    assert requests[0].warning
    assert len(requests[0].lines) == 2


def test_enabled_violation_feature_uses_monitor_as_warning_authority(
    merge_canvas,
) -> None:
    """Without a Monitor issue, an ordinary small-person box stays neutral."""
    shape = _rectangle("person", x=20.0, y=30.0, width=20.0, height=20.0)
    merge_canvas.load_shapes([shape], store_backup=False)
    merge_canvas._set_selected_shapes([shape], source="canvas")

    requests = merge_canvas._combined_size_overlay_requests()

    assert len(requests) == 1
    assert not requests[0].warning
    assert len(requests[0].lines) == 1


def test_stale_hidden_issue_is_filtered_at_paint_boundary(
    merge_canvas,
) -> None:
    """Canvas visibility remains authoritative while Monitor refresh is pending."""
    shape = _rectangle("person", x=20.0, y=30.0, width=20.0, height=20.0)
    merge_canvas.load_shapes([shape], store_backup=False)
    merge_canvas.set_rectangle_size_issues([_issue(shape, 0)])
    shape.visible = False

    assert merge_canvas._violation_overlay_requests() == ()


def test_full_shape_replacement_clears_stale_issue_state(merge_canvas) -> None:
    """Loading another image must synchronously discard prior issue payloads."""
    old_shape = _rectangle(
        "person",
        x=20.0,
        y=30.0,
        width=20.0,
        height=20.0,
    )
    new_shape = _rectangle(
        "head",
        x=100.0,
        y=100.0,
        width=80.0,
        height=60.0,
    )
    merge_canvas.load_shapes([old_shape], store_backup=False)
    merge_canvas.set_rectangle_size_issues([_issue(old_shape, 0)])
    assert merge_canvas.rectangle_size_issues

    merge_canvas.load_shapes([new_shape], store_backup=False)

    assert merge_canvas.rectangle_size_issues == ()
    assert merge_canvas._violation_overlay_requests() == ()


def test_issue_setter_is_atomic_on_duplicate_identity(merge_canvas) -> None:
    """Invalid snapshots must not replace the last valid issue state."""
    shape = _rectangle("person", x=20.0, y=30.0, width=20.0, height=20.0)
    merge_canvas.load_shapes([shape], store_backup=False)
    issue = _issue(shape, 0)
    merge_canvas.set_rectangle_size_issues([issue])

    with pytest.raises(ValueError):
        merge_canvas.set_rectangle_size_issues([issue, issue])

    assert merge_canvas.rectangle_size_issues == (issue,)
