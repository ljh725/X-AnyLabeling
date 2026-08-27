"""Privacy-safe shape context buckets for behavior analytics."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterable, Sequence
from typing import Any

from .versions import CONTEXT_SCHEMA_VERSION

CONTEXT_VERSION = CONTEXT_SCHEMA_VERSION
_MACHINE_CONTEXT_SALT = secrets.token_bytes(32)


def _bucket(
    value: float, thresholds: tuple[float, ...], labels: tuple[str, ...]
) -> str:
    """Return a stable bucket label for a numeric value."""
    for index, threshold in enumerate(thresholds):
        if value < threshold:
            return labels[index]
    return labels[-1]


def _numeric_points(
    points: Iterable[Sequence[float]] | None,
) -> list[tuple[float, float]]:
    """Keep only finite two-dimensional point coordinates in memory."""
    result = []
    for point in points or ():
        if len(point) < 2:
            continue
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError):
            continue
        if x == x and y == y:
            result.append((x, y))
    return result


def _label_key(label: str | None, salt: bytes, allowlist: set[str]) -> str:
    """Return a safe category or salted stable key without raw text."""
    if label and label in allowlist:
        return label
    if not label:
        return "unknown"
    digest = hashlib.sha256(salt + label.encode("utf-8")).hexdigest()
    return f"label-{digest[:16]}"


def build_shape_context(
    *,
    points: Iterable[Sequence[float]] | None,
    shape_type: str | None,
    label: str | None,
    initial_source: str = "manual",
    salt: bytes | None = None,
    label_allowlist: Iterable[str] = (),
    edit_target: str | None = None,
    image_size: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Build a bounded context summary without storing raw geometry."""
    numeric = _numeric_points(points)
    salt = salt if salt is not None else _MACHINE_CONTEXT_SALT
    labels = ("small", "medium", "large")
    if not numeric:
        return {
            "context_version": CONTEXT_VERSION,
            "shape_type": shape_type or "unknown",
            "edit_target": edit_target or "unknown",
            "point_count_bucket": "none",
            "complexity_bucket": "none",
            "size_bucket": "unknown",
            "aspect_ratio_bucket": "unknown",
            "label_key": _label_key(label, salt, set(label_allowlist)),
            "initial_source": initial_source or "unknown",
        }
    xs = [point[0] for point in numeric]
    ys = [point[1] for point in numeric]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    if image_size and len(image_size) >= 2:
        try:
            canvas_width = max(1.0, float(image_size[0]))
            canvas_height = max(1.0, float(image_size[1]))
            width /= canvas_width
            height /= canvas_height
        except (TypeError, ValueError):
            pass
    area = width * height
    ratio = width / height if height else float("inf")
    size_bucket = _bucket(area, (1_000, 10_000), labels)
    ratio_bucket = (
        "degenerate"
        if width == 0 or height == 0
        else "wide" if ratio >= 2 else "tall" if ratio <= 0.5 else "balanced"
    )
    point_bucket = (
        "2" if len(numeric) <= 2 else "3-8" if len(numeric) <= 8 else "9+"
    )
    complexity_bucket = (
        "simple"
        if len(numeric) <= 4
        else "moderate" if len(numeric) <= 8 else "complex"
    )
    return {
        "context_version": CONTEXT_VERSION,
        "shape_type": shape_type or "unknown",
        "edit_target": edit_target or "unknown",
        "point_count_bucket": point_bucket,
        "complexity_bucket": complexity_bucket,
        "size_bucket": size_bucket,
        "aspect_ratio_bucket": ratio_bucket,
        "label_key": _label_key(label, salt, set(label_allowlist)),
        "initial_source": initial_source or "unknown",
    }
