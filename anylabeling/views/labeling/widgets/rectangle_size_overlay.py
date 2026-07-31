"""Qt renderer for single and multi rectangle-size warning overlays."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from PyQt6 import QtCore, QtGui
from PyQt6.QtCore import Qt

from ..rectangle_size import (
    BBox,
    CandidateId,
    RectangleSizeIssue,
)
from ..rectangle_size.layout import (
    OverlayLayoutItem,
    OverlayLayoutPlacement,
    RectXYWH,
    layout_overlay_items,
)


@dataclass(frozen=True)
class RectangleSizeOverlayStyle:
    """Fixed screen-space style matching the existing size prompt."""

    font_family: str = "Arial"
    font_point_size: int = 9
    padding_px: float = 4.0
    anchor_gap_px: float = 6.0
    collision_gap_px: float = 4.0
    background_rgba: Tuple[int, int, int, int] = (0, 0, 0, 180)
    normal_text_color: str = "#FFFFFF"
    warning_color: str = "#FFB300"
    warning_border_width_px: float = 1.5


@dataclass(frozen=True)
class RectangleSizeOverlayRequest:
    """One image-space overlay request ready for measurement and layout."""

    candidate_id: CandidateId
    lines: Tuple[str, ...]
    bbox: BBox
    label_rect: Optional[RectXYWH] = None
    warning: bool = True


@dataclass(frozen=True)
class RectangleSizeOverlayPlacement:
    """Rendered screen-space placement plus its original request."""

    request: RectangleSizeOverlayRequest
    rect: RectXYWH


def map_rect_tuple(
    transform: QtGui.QTransform,
    rect: BBox,
) -> BBox:
    """Map and normalize a bbox through a Qt transform.

    Args:
        transform: Source-to-screen painter transform.
        rect: ``(x_min, y_min, x_max, y_max)`` source rectangle.

    Returns:
        Normalized mapped rectangle.
    """
    x_min, y_min, x_max, y_max = rect
    points = (
        transform.map(QtCore.QPointF(x_min, y_min)),
        transform.map(QtCore.QPointF(x_max, y_min)),
        transform.map(QtCore.QPointF(x_min, y_max)),
        transform.map(QtCore.QPointF(x_max, y_max)),
    )
    x_values = tuple(point.x() for point in points)
    y_values = tuple(point.y() for point in points)
    return (
        min(x_values),
        min(y_values),
        max(x_values),
        max(y_values),
    )


def issue_overlay_lines(issue: RectangleSizeIssue) -> Tuple[str, ...]:
    """Format one aggregated issue into a two-line multi-category prompt.

    Args:
        issue: Evaluated rectangle-size issue.

    Returns:
        Title line with category and W/H, followed by all failed dimensions.
    """
    title = f"{issue.label}  W {issue.width:.1f} px  H {issue.height:.1f} px"
    failures = []
    for violation in issue.violations:
        dimension = "W" if violation.dimension == "width" else "H"
        failures.append(
            f"{dimension} {violation.actual_px:.1f} px"
            f" <= {violation.threshold_px:g} px"
        )
    if not failures:
        return (title,)
    return (title, "  ".join(failures))


def overlay_request_from_issue(
    issue: RectangleSizeIssue,
    *,
    label_rect: Optional[RectXYWH] = None,
) -> RectangleSizeOverlayRequest:
    """Build one warning request from an evaluator issue.

    Args:
        issue: Evaluated issue containing all failed dimensions.
        label_rect: Optional image-space standard label rectangle.

    Returns:
        Immutable renderer request.
    """
    return RectangleSizeOverlayRequest(
        candidate_id=issue.candidate_id,
        lines=issue_overlay_lines(issue),
        bbox=issue.bbox,
        label_rect=label_rect,
        warning=True,
    )


def merge_overlay_requests(
    normal_request: Optional[RectangleSizeOverlayRequest],
    issue_requests: Iterable[RectangleSizeOverlayRequest],
) -> Tuple[RectangleSizeOverlayRequest, ...]:
    """Merge ordinary and abnormal overlays without duplicating one shape.

    Abnormal requests retain their stable input order and take precedence.
    A distinct ordinary hover/selection/creation request is appended so all
    boxes participate in one collision-aware layout pass.

    Args:
        normal_request: Optional ordinary live W/H request.
        issue_requests: Proactive abnormal requests.

    Returns:
        Immutable combined request sequence.

    Raises:
        ValueError: If abnormal requests duplicate a candidate identity.
    """
    abnormal = tuple(issue_requests)
    candidate_ids = set()
    for request in abnormal:
        if request.candidate_id in candidate_ids:
            raise ValueError(
                "Abnormal overlay requests need unique candidate_id values"
            )
        candidate_ids.add(request.candidate_id)
    if normal_request is None or normal_request.candidate_id in candidate_ids:
        return abnormal
    return abnormal + (normal_request,)


class RectangleSizeOverlayRenderer:
    """Measure, lay out, and paint fixed-size rectangle warning boxes."""

    def __init__(
        self,
        style: Optional[RectangleSizeOverlayStyle] = None,
    ) -> None:
        """Initialize the renderer with an immutable visual style.

        Args:
            style: Optional replacement style.
        """
        self.style = style or RectangleSizeOverlayStyle()

    def render(
        self,
        painter: QtGui.QPainter,
        requests: Iterable[RectangleSizeOverlayRequest],
        image_viewport: BBox,
    ) -> Tuple[RectangleSizeOverlayPlacement, ...]:
        """Render requests in widget pixels and return their placements.

        The incoming painter may already contain Canvas scale/translation.
        Geometry is first mapped through that transform; painting then uses
        ``resetTransform()`` so font, padding, gaps, and borders stay fixed
        across zoom levels.

        Args:
            painter: Active Canvas painter.
            requests: Image-space overlay requests in stable paint order.
            image_viewport: Current visible image-space viewport.

        Returns:
            Immutable screen-space placements in request order.

        Raises:
            ValueError: If a request has no text lines.
        """
        request_tuple = tuple(requests)
        if not request_tuple:
            return ()
        for request in request_tuple:
            if not request.lines or any(
                not isinstance(line, str) or not line for line in request.lines
            ):
                raise ValueError("Overlay requests need non-empty text lines")

        font = QtGui.QFont(
            self.style.font_family,
            self.style.font_point_size,
            QtGui.QFont.Weight.Bold,
        )
        metrics = QtGui.QFontMetrics(font)
        line_height = metrics.height()
        transform = painter.transform()
        screen_viewport = map_rect_tuple(transform, image_viewport)

        layout_items = []
        for request in request_tuple:
            text_width = max(
                metrics.horizontalAdvance(line) for line in request.lines
            )
            box_width = text_width + 2.0 * self.style.padding_px
            box_height = (
                line_height * len(request.lines) + 2.0 * self.style.padding_px
            )
            screen_label_rect = self._map_label_rect(
                transform,
                request.label_rect,
            )
            layout_items.append(
                OverlayLayoutItem(
                    candidate_id=request.candidate_id,
                    bbox=map_rect_tuple(transform, request.bbox),
                    box_width=box_width,
                    box_height=box_height,
                    label_rect=screen_label_rect,
                )
            )

        layouts = layout_overlay_items(
            layout_items,
            screen_viewport,
            gap=self.style.anchor_gap_px,
            collision_gap=self.style.collision_gap_px,
        )
        placements = tuple(
            RectangleSizeOverlayPlacement(
                request=request,
                rect=layout.rect,
            )
            for request, layout in zip(request_tuple, layouts)
        )
        self._paint(painter, font, metrics, placements)
        return placements

    @staticmethod
    def _map_label_rect(
        transform: QtGui.QTransform,
        label_rect: Optional[RectXYWH],
    ) -> Optional[RectXYWH]:
        """Map an optional image-space ``(x, y, w, h)`` label rectangle."""
        if label_rect is None:
            return None
        x, y, width, height = label_rect
        mapped = map_rect_tuple(
            transform,
            (x, y, x + width, y + height),
        )
        return (
            mapped[0],
            mapped[1],
            mapped[2] - mapped[0],
            mapped[3] - mapped[1],
        )

    def _paint(
        self,
        painter: QtGui.QPainter,
        font: QtGui.QFont,
        metrics: QtGui.QFontMetrics,
        placements: Tuple[RectangleSizeOverlayPlacement, ...],
    ) -> None:
        """Paint measured placements without leaking painter state."""
        background = QtGui.QColor(*self.style.background_rgba)
        normal_text = QtGui.QColor(self.style.normal_text_color)
        warning_color = QtGui.QColor(self.style.warning_color)
        line_height = metrics.height()

        painter.save()
        try:
            painter.resetTransform()
            painter.setOpacity(1.0)
            painter.setFont(font)
            for placement in placements:
                x, y, width, height = placement.rect
                box_rect = QtCore.QRectF(x, y, width, height)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QtGui.QBrush(background))
                painter.drawRect(box_rect)
                if placement.request.warning:
                    painter.setPen(
                        QtGui.QPen(
                            warning_color,
                            self.style.warning_border_width_px,
                        )
                    )
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(box_rect)

                text_color = (
                    warning_color if placement.request.warning else normal_text
                )
                painter.setPen(QtGui.QPen(text_color))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                for index, line in enumerate(placement.request.lines):
                    painter.drawText(
                        QtCore.QPointF(
                            x + self.style.padding_px,
                            y
                            + self.style.padding_px
                            + (index + 1) * line_height
                            - metrics.descent(),
                        ),
                        line,
                    )
        finally:
            painter.restore()


__all__ = [
    "RectangleSizeOverlayPlacement",
    "RectangleSizeOverlayRenderer",
    "RectangleSizeOverlayRequest",
    "RectangleSizeOverlayStyle",
    "issue_overlay_lines",
    "map_rect_tuple",
    "merge_overlay_requests",
    "overlay_request_from_issue",
]
