"""Content signatures that decide whether a review confirmation is valid."""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Optional, Sequence

from .models import (
    ReviewRules,
    normalize_bounds,
    signature_for,
)

RECTANGLE_SHAPE_TYPES = frozenset({"rectangle"})


def _number_text(value: Any) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("shape coordinate is not finite")
    if number == 0:
        return "0"
    if number.is_integer():
        return str(int(number))
    return format(number, ".12g")


def point_xy(point: Any) -> tuple[float, float]:
    """Read one point from a Qt point or a numeric pair."""
    if hasattr(point, "x") and hasattr(point, "y"):
        x_value = point.x()
        y_value = point.y()
        return float(x_value), float(y_value)
    return float(point[0]), float(point[1])


def shape_points(shape: Any) -> list[tuple[float, float]]:
    """Return serializable points for one shape."""
    return [point_xy(point) for point in getattr(shape, "points", ())]


def shape_bounds(shape: Any) -> Optional[tuple[float, float, float, float]]:
    """Return normalized image-space bounds, or ``None`` if unusable."""
    points = shape_points(shape)
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return normalize_bounds((min(xs), min(ys), max(xs), max(ys)))


def _canonical_points(shape: Any) -> list[tuple[str, str]]:
    points = [
        (_number_text(x_value), _number_text(y_value))
        for x_value, y_value in shape_points(shape)
    ]
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    return points


def _attributes_payload(shape: Any) -> Any:
    attributes = getattr(shape, "attributes", None)
    if isinstance(attributes, Mapping):
        return dict(attributes)
    return attributes or {}


def _flags_payload(shape: Any) -> Any:
    flags = getattr(shape, "flags", None)
    if isinstance(flags, Mapping):
        return dict(flags)
    return flags or {}


def box_rule_for(shape: Any, rules: ReviewRules) -> str:
    """Return the configured box rule for the shape's current label."""
    return rules.box_rule(str(getattr(shape, "label", "") or ""))


def shape_geometry_signature(shape: Any, rules: ReviewRules) -> str:
    """Return the geometry signature for one shape.

    Rectangles are canonicalized through normalized bounds so vertex order
    and int/float JSON spelling do not invalidate a confirmation.  When the
    box rule is unknown the label is part of the geometry signature, because
    the editor cannot prove that two classes use the same box convention.
    """
    shape_type = str(getattr(shape, "shape_type", "polygon"))
    rule = box_rule_for(shape, rules)
    payload: dict[str, Any] = {
        "shape_type": shape_type,
        "box_rule": rule,
        "rules": rules.geometry_signature(),
    }
    if shape_type in RECTANGLE_SHAPE_TYPES:
        bounds = shape_bounds(shape)
        payload["bounds"] = (
            [_number_text(value) for value in bounds]
            if bounds is not None
            else None
        )
    else:
        payload["points"] = _canonical_points(shape)
    if rule == "unknown":
        payload["label"] = str(getattr(shape, "label", "") or "")
    return signature_for(payload)


def shape_category_signature(
    shape: Any, rules: ReviewRules, geometry_signature: Optional[str] = None
) -> str:
    """Return the category signature for one shape."""
    geometry = geometry_signature or shape_geometry_signature(shape, rules)
    return signature_for(
        {
            "label": str(getattr(shape, "label", "") or ""),
            "attributes": _attributes_payload(shape),
            "flags": _flags_payload(shape),
            "geometry": geometry,
            "rules": rules.category_signature(),
        }
    )


def shape_content_payload(shape: Any) -> dict[str, Any]:
    """Return content that matters for undo/redo and change detection."""
    return {
        "shape_id": str(getattr(shape, "xanylabeling_shape_id", "")),
        "label": str(getattr(shape, "label", "") or ""),
        "shape_type": str(getattr(shape, "shape_type", "polygon")),
        "points": _canonical_points(shape),
        "attributes": _attributes_payload(shape),
        "flags": _flags_payload(shape),
        "group_id": getattr(shape, "group_id", None),
        "difficult": bool(getattr(shape, "difficult", False)),
        "description": str(getattr(shape, "description", "") or ""),
    }


def content_hash(shapes: Iterable[Any]) -> str:
    """Return a stable hash over every shape's reviewable content."""
    payload = sorted(
        (
            shape_content_payload(shape)
            for shape in shapes
            if str(getattr(shape, "xanylabeling_shape_id", ""))
        ),
        key=lambda item: item["shape_id"],
    )
    return signature_for(payload)


def bbox_intersects_bounds(
    left: Sequence[float], right: Sequence[float]
) -> bool:
    """Return whether two image-space rectangles overlap."""
    return not (
        left[2] < right[0]
        or right[2] < left[0]
        or left[3] < right[1]
        or right[3] < left[1]
    )
