"""Pure selection-set operations used by the canvas gesture layer."""

from collections.abc import Iterable


def _unique(shapes: Iterable) -> list:
    """Return shapes once, preserving their input order."""
    result = []
    seen = set()
    for shape in shapes:
        identity = id(shape)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(shape)
    return result


def toggle_shape(selected_shapes: Iterable, shape) -> list:
    """Toggle one shape in a selection while preserving order.

    Args:
        selected_shapes: Current selected shapes.
        shape: Shape to add or remove.

    Returns:
        A new selection list.
    """
    selected = _unique(selected_shapes)
    if any(current is shape for current in selected):
        return [current for current in selected if current is not shape]
    return selected + [shape]


def add_shapes(selected_shapes: Iterable, candidates: Iterable) -> list:
    """Append candidates to a selection without duplicate identities."""
    return _unique([*selected_shapes, *candidates])
