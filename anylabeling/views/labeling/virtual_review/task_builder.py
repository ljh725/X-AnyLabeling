"""Deterministic virtual task construction."""

from __future__ import annotations

from typing import Iterable

from .models import (
    GroupIdMode,
    VirtualShapeView,
    VirtualTask,
    VirtualTaskCriteria,
    union_bboxes,
)


def _in_range(
    value: float | None,
    minimum: float | None,
    maximum: float | None,
) -> bool:
    """Return whether a value satisfies an inclusive optional range."""

    if value is None:
        return minimum is None and maximum is None
    if minimum is not None and value < minimum:
        return False
    if maximum is not None and value > maximum:
        return False
    return True


def matches_criteria(
    shape: VirtualShapeView,
    criteria: VirtualTaskCriteria,
) -> bool:
    """Return whether ``shape`` is an eligible virtual-task anchor."""

    if not shape.base_visible:
        return False
    if criteria.labels and shape.label not in criteria.labels:
        return False
    if criteria.shape_types and shape.shape_type not in criteria.shape_types:
        return False

    normalized_gid = shape.normalized_group_id
    if criteria.group_id_mode is GroupIdMode.VALID and normalized_gid is None:
        return False
    if (
        criteria.group_id_mode is GroupIdMode.MISSING
        and normalized_gid is not None
    ):
        return False
    if criteria.group_id_mode is GroupIdMode.EXACT:
        if normalized_gid is None or normalized_gid != criteria.group_id:
            return False

    return _in_range(
        shape.width, criteria.min_width, criteria.max_width
    ) and _in_range(shape.height, criteria.min_height, criteria.max_height)


def build_virtual_tasks(
    shapes: Iterable[VirtualShapeView],
    criteria: VirtualTaskCriteria,
) -> tuple[VirtualTask, ...]:
    """Build one deterministic task per matching group or ungrouped anchor.

    The input order is preserved.  Group expansion intentionally includes
    base-hidden members; the Canvas decides whether those members can be
    rendered, so virtual review never changes base visibility.
    """

    views = tuple(shapes)
    matching = [
        (index, shape)
        for index, shape in enumerate(views)
        if matches_criteria(shape, criteria)
    ]
    tasks: list[VirtualTask] = []
    seen_keys: set[tuple[str, str]] = set()

    for anchor_index, anchor in matching:
        normalized_gid = anchor.normalized_group_id
        if normalized_gid is None:
            task_key = ("shape", anchor.shape_id)
            member_views = (anchor,)
            task_id = f"shape:{anchor.shape_id}"
        else:
            task_key = ("group", normalized_gid)
            if task_key in seen_keys:
                continue
            member_views = tuple(
                shape
                for shape in views
                if shape.normalized_group_id == normalized_gid
            )
            task_id = f"group:{normalized_gid}"

        if task_key in seen_keys:
            continue
        seen_keys.add(task_key)
        tasks.append(
            VirtualTask(
                task_id=task_id,
                anchor_id=anchor.shape_id,
                member_ids=tuple(shape.shape_id for shape in member_views),
                group_id=normalized_gid,
                anchor_index=anchor_index,
                bbox=union_bboxes(shape.bbox for shape in member_views),
                anchor_bbox=anchor.bbox,
            )
        )

    return tuple(tasks)


__all__ = ["build_virtual_tasks", "matches_criteria"]
