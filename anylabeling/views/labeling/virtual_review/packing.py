"""Deterministic screen-space packing for virtual-review tasks."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Optional

from .models import (
    VirtualPackingOptions,
    VirtualPackingResult,
    VirtualReviewPage,
    VirtualTask,
    union_bboxes,
)

BBox = tuple[float, float, float, float]
ViewportSize = tuple[float, float]
MIN_REVIEW_ZOOM_PERCENT = 1
MAX_REVIEW_ZOOM_PERCENT = 1000


def _normalized_bbox(bbox: object) -> Optional[BBox]:
    """Return a finite positive-area bbox, or ``None`` when invalid."""
    try:
        values = tuple(float(value) for value in bbox)
    except (TypeError, ValueError):
        return None
    if len(values) != 4:
        return None
    left, top, right, bottom = values
    if (
        not all(math.isfinite(value) for value in values)
        or right <= left
        or bottom <= top
    ):
        return None
    return left, top, right, bottom


def _normalized_viewport(viewport_size: object) -> Optional[ViewportSize]:
    """Return a finite positive viewport pair, or ``None``."""
    try:
        width, height = viewport_size
        width = float(width)
        height = float(height)
    except (TypeError, ValueError):
        return None
    if (
        not math.isfinite(width)
        or not math.isfinite(height)
        or width <= 0
        or height <= 0
    ):
        return None
    return width, height


def bbox_gap(first: Optional[BBox], second: Optional[BBox]) -> Optional[float]:
    """Return the shortest Euclidean gap between two axis-aligned boxes."""
    first_box = _normalized_bbox(first)
    second_box = _normalized_bbox(second)
    if first_box is None or second_box is None:
        return None
    first_left, first_top, first_right, first_bottom = first_box
    second_left, second_top, second_right, second_bottom = second_box
    horizontal = max(
        first_left - second_right,
        second_left - first_right,
        0.0,
    )
    vertical = max(
        first_top - second_bottom,
        second_top - first_bottom,
        0.0,
    )
    return math.hypot(horizontal, vertical)


def bboxes_overlap(
    first: Optional[BBox], second: Optional[BBox]
) -> Optional[bool]:
    """Return strict positive-area overlap, or ``None`` for invalid boxes."""
    first_box = _normalized_bbox(first)
    second_box = _normalized_bbox(second)
    if first_box is None or second_box is None:
        return None
    return min(first_box[2], second_box[2]) > max(
        first_box[0], second_box[0]
    ) and min(first_box[3], second_box[3]) > max(first_box[1], second_box[1])


def fit_scale(
    bbox: Optional[BBox],
    viewport_size: object,
    fit_margin: float = 1.35,
) -> float:
    """Return the quantized scale the review viewport can actually apply."""
    normalized_bbox = _normalized_bbox(bbox)
    viewport = _normalized_viewport(viewport_size)
    if normalized_bbox is None or viewport is None:
        return 0.0
    try:
        margin = float(fit_margin)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(margin) or margin <= 0:
        return 0.0
    viewport_width, viewport_height = viewport
    left, top, right, bottom = normalized_bbox
    width = right - left
    height = bottom - top
    raw_scale = min(
        viewport_width / (width * margin),
        viewport_height / (height * margin),
    )
    bounded_scale = max(
        MIN_REVIEW_ZOOM_PERCENT / 100.0,
        min(MAX_REVIEW_ZOOM_PERCENT / 100.0, raw_scale),
    )
    zoom_percent = int(bounded_scale * 100.0)
    return zoom_percent / 100.0


def projected_short_side(
    bbox: Optional[BBox], scale: float
) -> Optional[float]:
    """Return a box's projected screen-space short side."""
    normalized_bbox = _normalized_bbox(bbox)
    if normalized_bbox is None or not math.isfinite(scale) or scale <= 0:
        return None
    return (
        min(
            normalized_bbox[2] - normalized_bbox[0],
            normalized_bbox[3] - normalized_bbox[1],
        )
        * scale
    )


def projected_gap(
    first: Optional[BBox], second: Optional[BBox], scale: float
) -> Optional[float]:
    """Return a pairwise bbox gap after applying ``scale``."""
    gap = bbox_gap(first, second)
    if gap is None or not math.isfinite(scale) or scale <= 0:
        return None
    return gap * scale


def _task_anchor_bbox(task: VirtualTask) -> Optional[BBox]:
    """Return the precise anchor bbox with a legacy-task fallback."""
    return task.anchor_bbox or task.bbox


@dataclass(frozen=True)
class PageEvaluation:
    """Geometry evaluation for a tentative page."""

    accepted: bool
    bbox: Optional[BBox] = None
    scale: float = 0.0
    min_projected_anchor_px: float = 0.0
    union_area: float = 0.0


def evaluate_page(
    tasks: Iterable[VirtualTask],
    viewport_size: object,
    options: VirtualPackingOptions,
) -> PageEvaluation:
    """Check the hard projected-size and separation gates for a page."""
    page_tasks = tuple(tasks)
    if not page_tasks or len(page_tasks) > options.max_tasks_per_page:
        return PageEvaluation(False)
    boxes = [_normalized_bbox(task.bbox) for task in page_tasks]
    anchor_boxes = [
        _normalized_bbox(_task_anchor_bbox(task)) for task in page_tasks
    ]
    if any(box is None for box in boxes + anchor_boxes):
        return PageEvaluation(False)
    bbox = union_bboxes(boxes)
    scale = fit_scale(bbox, viewport_size, options.fit_margin)
    if scale <= 0:
        return PageEvaluation(False)
    projected_sizes = [
        projected_short_side(anchor_bbox, scale)
        for anchor_bbox in anchor_boxes
    ]
    if any(
        size is None or size < options.min_projected_anchor_px
        for size in projected_sizes
    ):
        return PageEvaluation(False, bbox, scale)
    for index, first in enumerate(boxes):
        for second in boxes[index + 1 :]:
            overlap = bboxes_overlap(first, second)
            if overlap is None or overlap:
                return PageEvaluation(False, bbox, scale)
            gap = projected_gap(first, second, scale)
            if gap is None or gap < options.min_projected_gap_px:
                return PageEvaluation(False, bbox, scale)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    return PageEvaluation(
        accepted=True,
        bbox=bbox,
        scale=scale,
        min_projected_anchor_px=min(projected_sizes),
        union_area=width * height,
    )


def _page_from_tasks(
    tasks: tuple[VirtualTask, ...],
    evaluation: PageEvaluation,
    fallback: bool,
) -> VirtualReviewPage:
    """Create an immutable page from ordered atomic tasks."""
    task_ids = tuple(task.task_id for task in tasks)
    member_ids = tuple(
        member_id for task in tasks for member_id in task.member_ids
    )
    anchor_ids = tuple(task.anchor_id for task in tasks)
    return VirtualReviewPage(
        page_id=f"page:{'|'.join(task_ids)}",
        task_ids=task_ids,
        member_ids=member_ids,
        anchor_ids=anchor_ids,
        bbox=evaluation.bbox,
        projected_scale=evaluation.scale,
        min_projected_anchor_px=evaluation.min_projected_anchor_px,
        fallback=fallback,
    )


def _singleton_page(
    task: VirtualTask,
    viewport_size: object,
    options: VirtualPackingOptions,
    fallback: bool,
) -> VirtualReviewPage:
    """Create a one-task fallback page, retaining available geometry."""
    evaluation = evaluate_page((task,), viewport_size, options)
    return _page_from_tasks(
        (task,), evaluation, fallback or not evaluation.accepted
    )


def pack_virtual_tasks(
    tasks: Iterable[VirtualTask],
    viewport_size: object,
    options: VirtualPackingOptions,
) -> VirtualPackingResult:
    """Pack atomic tasks into deterministic, editable review pages."""
    ordered_tasks = tuple(tasks)
    remaining = list(ordered_tasks)
    if not remaining:
        return VirtualPackingResult((), 0, 0)
    if options.max_tasks_per_page == 1:
        pages = tuple(
            _singleton_page(task, viewport_size, options, False)
            for task in remaining
        )
        return VirtualPackingResult(
            pages,
            len(remaining),
            sum(page.fallback for page in pages),
        )

    pages: list[VirtualReviewPage] = []
    fallback_count = 0
    while remaining:
        seed = remaining.pop(0)
        current = [seed]
        seed_evaluation = evaluate_page(current, viewport_size, options)
        if not seed_evaluation.accepted:
            page = _singleton_page(seed, viewport_size, options, True)
            pages.append(page)
            fallback_count += 1
            continue

        while len(current) < options.max_tasks_per_page:
            candidates: list[
                tuple[tuple[float, float, int], int, PageEvaluation]
            ] = []
            for index, candidate in enumerate(remaining):
                evaluation = evaluate_page(
                    (*current, candidate), viewport_size, options
                )
                if evaluation.accepted:
                    candidates.append(
                        (
                            (
                                -evaluation.min_projected_anchor_px,
                                evaluation.union_area,
                                candidate.anchor_index,
                            ),
                            index,
                            evaluation,
                        )
                    )
            if not candidates:
                break
            _, selected_index, _ = min(candidates, key=lambda item: item[0])
            current.append(remaining.pop(selected_index))
        evaluation = evaluate_page(current, viewport_size, options)
        page = _page_from_tasks(tuple(current), evaluation, False)
        pages.append(page)

    return VirtualPackingResult(
        tuple(pages), len(ordered_tasks), fallback_count
    )


__all__ = [
    "PageEvaluation",
    "bbox_gap",
    "bboxes_overlap",
    "evaluate_page",
    "fit_scale",
    "pack_virtual_tasks",
    "projected_gap",
    "projected_short_side",
]
