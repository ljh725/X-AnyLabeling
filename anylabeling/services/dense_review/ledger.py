"""Ledger construction: every alive object enters one stable review queue."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from .models import (
    NEW_PENDING_BATCH_ID,
    OTHER_BATCH_ID,
    OTHER_BATCH_NAME,
    REVIEW_DIMENSIONS,
    SUPPORTED_SHAPE_TYPES,
    BatchState,
    ObjectReviewState,
    ReviewConfig,
    ReviewState,
)
from .signatures import (
    shape_bounds,
    shape_category_signature,
    shape_geometry_signature,
    shape_points,
)


def reviewable_shapes(shapes: Iterable[Any]) -> list[Any]:
    """Return shapes with a usable persistent identity."""
    return [
        shape
        for shape in shapes
        if str(getattr(shape, "xanylabeling_shape_id", ""))
    ]


def spatial_order(shapes: Iterable[Any]) -> list[Any]:
    """Sort shapes top-to-bottom then left-to-right by their centers."""
    candidates = []
    for shape in reviewable_shapes(shapes):
        bounds = shape_bounds(shape)
        if bounds is None:
            points = shape_points(shape)
            if points:
                xs = [point[0] for point in points]
                ys = [point[1] for point in points]
                bounds = (min(xs), min(ys), max(xs), max(ys))
            else:
                bounds = (0.0, 0.0, 0.0, 0.0)
        center_x = (bounds[0] + bounds[2]) / 2.0
        center_y = (bounds[1] + bounds[3]) / 2.0
        candidates.append(
            (
                (
                    round(center_y, 3),
                    round(center_x, 3),
                    str(getattr(shape, "xanylabeling_shape_id", "")),
                ),
                shape,
            )
        )
    candidates.sort(key=lambda item: item[0])
    return [shape for _key, shape in candidates]


def build_object_state(
    shape: Any,
    config: ReviewConfig,
    display_index: int,
    *,
    added: bool = False,
) -> ObjectReviewState:
    """Build one object ledger entry from live shape content."""
    bounds = shape_bounds(shape)
    shape_id = str(getattr(shape, "xanylabeling_shape_id", ""))
    label = str(getattr(shape, "label", "") or "")
    shape_type = str(getattr(shape, "shape_type", "polygon"))
    rules = config.rules
    geometry_signature = shape_geometry_signature(shape, rules)
    load_failed = bounds is None or not bool(shape_points(shape))
    return ObjectReviewState(
        shape_id=shape_id,
        display_index=display_index,
        label=label,
        shape_type=shape_type,
        bounds=bounds or (0.0, 0.0, 0.0, 0.0),
        category_signature=shape_category_signature(
            shape, rules, geometry_signature
        ),
        geometry_signature=geometry_signature,
        added=added,
        supported=shape_type in SUPPORTED_SHAPE_TYPES,
        load_failed=load_failed,
    )


def create_state(
    config: ReviewConfig,
    shapes: Iterable[Any],
    image_fingerprint: str,
    image_width: int,
    image_height: int,
) -> ReviewState:
    """Create a fresh review round for every alive object."""
    ordered = spatial_order(shapes)
    objects: dict[str, ObjectReviewState] = {}
    for index, shape in enumerate(ordered, start=1):
        item = build_object_state(shape, config, index)
        objects[item.shape_id] = item
    batches = assign_batches(config, objects)
    state = ReviewState(
        image_fingerprint=image_fingerprint,
        image_width=int(image_width),
        image_height=int(image_height),
        rules_signature=config.rules_signature(),
        batch_signature=config.batch_signature(),
        objects=objects,
        batches=batches,
        new_pending=[],
        dimensions=REVIEW_DIMENSIONS,
    )
    state.current_batch = batches[0].batch_id if batches else ""
    state.current_object = (
        batches[0].member_ids[0] if batches and batches[0].member_ids else ""
    )
    return state


def assign_batches(
    config: ReviewConfig,
    objects: Mapping[str, ObjectReviewState],
) -> list[BatchState]:
    """Assign every object to its configured batch or the other queue."""
    normalized = config.normalized()
    batches: list[BatchState] = []
    for index, definition in enumerate(normalized.batches):
        batches.append(
            BatchState(
                batch_id=f"batch-{index}",
                name=definition.display_name(),
                labels=definition.labels,
            )
        )
    batch_by_label = normalized.label_to_batch()
    batch_lookup = {batch.batch_id: batch for batch in batches}
    other = BatchState(
        batch_id=OTHER_BATCH_ID,
        name=OTHER_BATCH_NAME,
        labels=(),
    )
    for item in sorted(objects.values(), key=lambda obj: obj.display_index):
        batch_id = (
            batch_by_label.get(item.label, OTHER_BATCH_ID)
            if item.supported
            else OTHER_BATCH_ID
        )
        target = batch_lookup.get(batch_id)
        if target is None:
            target = other
        target.member_ids.append(item.shape_id)
    if other.member_ids:
        batches.append(other)
    return batches


def rebuild_batches(
    state: ReviewState,
    config: ReviewConfig,
    *,
    preserve_current: bool = True,
) -> None:
    """Explicitly rebuild the remaining queue from current labels."""
    previous_object = state.current_object if preserve_current else ""
    batches = assign_batches(config, state.objects)
    state.batches = batches
    state.new_pending = []
    state.batch_signature = config.batch_signature()
    state.current_batch = batches[0].batch_id if batches else ""
    state.current_object = ""
    if previous_object:
        for batch in batches:
            if previous_object in batch.member_ids:
                state.current_batch = batch.batch_id
                state.current_object = previous_object
                break
    if not state.current_object:
        for batch in batches:
            if batch.member_ids:
                state.current_batch = batch.batch_id
                state.current_object = batch.member_ids[0]
                break


def next_display_index(state: ReviewState) -> int:
    """Return the next stable short number for a newly added object."""
    return (
        max(
            (item.display_index for item in state.objects.values()),
            default=0,
        )
        + 1
    )


def batches_with_pending(
    state: ReviewState,
    dimensions: Iterable[str],
) -> list[BatchState]:
    """Return batches that still have confirmable objects for a dimension."""
    requested = tuple(dimensions)
    result = []
    for batch in state.batches:
        for shape_id in batch.member_ids:
            item = state.objects.get(shape_id)
            if item is None or item.difficult or item.skipped:
                continue
            if item.load_failed or not item.supported:
                continue
            if any(not item.confirmed(dimension) for dimension in requested):
                result.append(batch)
                break
    return result


def next_object_in_batch(
    state: ReviewState,
    batch_id: str,
    dimensions: Iterable[str],
    after_object_id: str = "",
) -> Optional[str]:
    """Return the next pending object in one batch, wrapping once."""
    requested = tuple(dimensions)
    members = state.member_ids(batch_id)
    if not members:
        return None
    start = 0
    if after_object_id in members:
        start = members.index(after_object_id) + 1
    for offset in range(len(members)):
        shape_id = members[(start + offset) % len(members)]
        item = state.objects.get(shape_id)
        if item is None or item.difficult or item.skipped:
            continue
        if item.load_failed or not item.supported:
            continue
        if any(not item.confirmed(dimension) for dimension in requested):
            return shape_id
    return None
