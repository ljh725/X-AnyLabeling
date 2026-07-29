"""Pure helpers for building in-memory shape filter indexes."""

from typing import Any, Dict, Iterable, List

FilterIndex = Dict[str, Any]


def build_shape_filter_index(items: Iterable[Any]) -> FilterIndex:
    """Build label/gid/shape_type lookup buckets for label-list items.

    Args:
        items: Iterable of objects exposing ``shape()``.

    Returns:
        A dict compatible with :class:`ShapeFilterEngine`.
    """
    index: FilterIndex = {"label": {}, "gid": {}, "shape_type": {}, "all": []}
    for item in items:
        shape = item.shape()
        index["all"].append(item)
        _append_bucket(index["label"], str(shape.label), item)
        if shape.group_id is not None:
            _append_bucket(index["gid"], str(shape.group_id), item)
        if shape.shape_type:
            _append_bucket(index["shape_type"], str(shape.shape_type), item)
    return index


def _append_bucket(buckets: Dict[str, List[Any]], key: str, item: Any) -> None:
    """Append ``item`` to a string-keyed lookup bucket."""
    buckets.setdefault(key, []).append(item)
