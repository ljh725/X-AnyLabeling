"""Loose relative-geometry filtering for body, head, and face rectangles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, List, Optional, Sequence, Tuple

from .rect_refine_types import (
    BBox,
    DEFAULT_RECT_REFINE_LABEL_ROLES,
    RectRefineLabelRoles,
    ShapeRefineView,
)

_EPS = 1e-9


@dataclass(frozen=True)
class GroupingResult:
    """Rectangles retained for one selected anchor."""

    members: Tuple[ShapeRefineView, ...]
    nonblocking_message: Optional[str] = None


def _area(bbox: BBox) -> float:
    """Return non-negative rectangle area."""
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def _valid_bbox(bbox: Optional[BBox]) -> bool:
    """Return whether a bounding box has positive width and height."""
    return bbox is not None and _area(bbox) > _EPS


def loosely_nested(inner: ShapeRefineView, outer: ShapeRefineView) -> bool:
    """Return whether two rectangles form a plausible loose nesting.

    The filter intentionally avoids weighted scores and fixed pixel
    thresholds. The inner rectangle may extend outside the outer rectangle by
    half of its own size, which keeps clipped and slightly misaligned true
    targets. The only size guard rejects a supposed inner rectangle that is
    larger than its outer rectangle.
    """
    if not _valid_bbox(inner.bbox) or not _valid_bbox(outer.bbox):
        return False
    inner_bbox = inner.bbox
    outer_bbox = outer.bbox
    if _area(inner_bbox) > _area(outer_bbox):
        return False

    inner_width = inner_bbox[2] - inner_bbox[0]
    inner_height = inner_bbox[3] - inner_bbox[1]
    center_x = (inner_bbox[0] + inner_bbox[2]) / 2.0
    center_y = (inner_bbox[1] + inner_bbox[3]) / 2.0
    return (
        outer_bbox[0] - inner_width / 2.0
        <= center_x
        <= outer_bbox[2] + inner_width / 2.0
        and outer_bbox[1] - inner_height / 2.0
        <= center_y
        <= outer_bbox[3] + inner_height / 2.0
    )


def _refinable(
    view: ShapeRefineView,
    label_roles: RectRefineLabelRoles,
) -> bool:
    """Return whether a Shape view participates in three-box filtering."""
    return (
        label_roles.contains(view.label)
        and view.shape_type == "rectangle"
        and _valid_bbox(view.bbox)
    )


def _related(
    inner_labels: FrozenSet[str],
    outer_labels: FrozenSet[str],
    pool: Sequence[ShapeRefineView],
) -> List[Tuple[ShapeRefineView, ShapeRefineView]]:
    """Return all loose inner/outer pairs in stable canvas order."""
    inner_views = [view for view in pool if view.label in inner_labels]
    outer_views = [view for view in pool if view.label in outer_labels]
    return [
        (inner, outer)
        for outer in outer_views
        for inner in inner_views
        if loosely_nested(inner, outer)
    ]


def _dedupe_sorted(
    views: Sequence[ShapeRefineView],
) -> Tuple[ShapeRefineView, ...]:
    """Deduplicate views by runtime identity and preserve canvas order."""
    unique = {view.shape_id: view for view in views}
    return tuple(sorted(unique.values(), key=lambda view: view.shape_index))


def infer(
    anchor: ShapeRefineView,
    all_shapes: Sequence[ShapeRefineView],
    label_roles: RectRefineLabelRoles = DEFAULT_RECT_REFINE_LABEL_ROLES,
) -> GroupingResult:
    """Filter geometrically related rectangles for one selected anchor."""
    if not _refinable(anchor, label_roles):
        return GroupingResult(
            members=(anchor,),
            nonblocking_message="anchor_invalid_geometry",
        )

    pool = [view for view in all_shapes if _refinable(view, label_roles)]
    head_body_pairs = _related(
        label_roles.head,
        label_roles.body,
        pool,
    )
    face_head_pairs = _related(
        label_roles.face,
        label_roles.head,
        pool,
    )
    members: List[ShapeRefineView] = [anchor]

    if anchor.label in label_roles.body:
        heads = [
            head
            for head, body in head_body_pairs
            if body.shape_id == anchor.shape_id
        ]
        head_ids = {head.shape_id for head in heads}
        faces = [
            face for face, head in face_head_pairs if head.shape_id in head_ids
        ]
        members.extend(heads)
        members.extend(faces)
    elif anchor.label in label_roles.head:
        members.extend(
            body
            for head, body in head_body_pairs
            if head.shape_id == anchor.shape_id
        )
        members.extend(
            face
            for face, head in face_head_pairs
            if head.shape_id == anchor.shape_id
        )
    else:
        heads = [
            head
            for face, head in face_head_pairs
            if face.shape_id == anchor.shape_id
        ]
        head_ids = {head.shape_id for head in heads}
        bodies = [
            body for head, body in head_body_pairs if head.shape_id in head_ids
        ]
        members.extend(heads)
        members.extend(bodies)

    return GroupingResult(members=_dedupe_sorted(members))


__all__ = [
    "GroupingResult",
    "infer",
    "loosely_nested",
]
