"""Field-scoped edit commands shared by the labeling view.

The native 4.2.1 batch edit writes every dialog field to every selected
shape and cannot be undone. These helpers keep the native entry point but
patch only the fields the user explicitly changed and record one undo step
for the whole batch.
"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any, Callable, Collection, Iterable, Mapping

if TYPE_CHECKING:
    from .shape import Shape

# Shape attributes a batch edit may patch, in dialog order.
BATCH_FIELDS = (
    "label",
    "flags",
    "group_id",
    "description",
    "difficult",
    "kie_linking",
)
REVIEW_STATUS_FIELD = "review_status"


def apply_field_changes(
    canvas: Any,
    shapes: Iterable[Shape],
    values: Mapping[str, Any],
    touched: Collection[str],
    label_resolver: Callable[[Shape, str], str] | None = None,
) -> list[Shape]:
    """Patch only the explicitly touched fields of every target shape.

    Args:
        canvas: Canvas owning the shapes; targets outside it are ignored.
        shapes: Shapes the user selected before opening the dialog.
        values: Mapping of field name to the value read from the dialog.
        touched: Field names the user actually changed in the dialog.
        label_resolver: Optional callable ``(shape, label) -> label`` used to
            resolve label-specific attributes per shape.

    Returns:
        The shapes that actually changed. No shape is mutated and no undo
        step is recorded when nothing would change.
    """
    targets = [shape for shape in shapes if shape in canvas.shapes]
    selected = [field for field in BATCH_FIELDS if field in touched]
    review_touched = REVIEW_STATUS_FIELD in touched
    if not targets or (not selected and not review_touched):
        return []

    patches = []
    for shape in targets:
        resolved_label = None
        patch = {}
        if "label" in selected:
            resolved_label = values["label"]
            if label_resolver is not None:
                resolved_shape = shape.copy()
                resolved_label = label_resolver(resolved_shape, resolved_label)
                if resolved_shape.attributes != shape.attributes:
                    patch["attributes"] = resolved_shape.attributes
        for field in selected:
            new_value = resolved_label if field == "label" else values[field]
            if getattr(shape, field, None) != new_value:
                patch[field] = new_value
        if review_touched:
            status = values[REVIEW_STATUS_FIELD]
            if shape.other_data.get(REVIEW_STATUS_FIELD) != status:
                patch[REVIEW_STATUS_FIELD] = status

        if patch:
            patches.append((shape, patch))

    if not patches:
        return []
    current = [shape.to_dict() for shape in canvas.shapes]
    if (
        not canvas.shapes_backups
        or [shape.to_dict() for shape in canvas.shapes_backups[-1]] != current
    ):
        canvas.store_shapes()

    for shape, patch in patches:
        for field, value in patch.items():
            if field == REVIEW_STATUS_FIELD:
                shape.other_data[field] = deepcopy(value)
            else:
                setattr(shape, field, deepcopy(value))
    return [shape for shape, _patch in patches]


def store_undo_step(canvas: Any) -> None:
    """Record one undo step for a completed batch edit.

    The canvas stores the state *after* each edit, so the current state must
    already be pushed before the batch by ``apply_field_changes``. The final
    snapshot recorded here completes the transaction.
    """
    if not canvas.shapes_backups:
        canvas.store_shapes()
    canvas.store_shapes()
