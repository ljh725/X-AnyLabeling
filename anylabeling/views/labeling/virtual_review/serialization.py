"""Canonical serialization for queue persistence and signatures.

Every persisted payload (criteria, packing options, locators, member
snapshots, task-content signatures) is encoded through this module so
that build-time signatures and runtime signatures are computed from the
same quantization and canonicalization rules.  Changing a rule here
changes it everywhere; no caller may re-implement quantization locally.
"""

from __future__ import annotations

import hashlib
import json
import math
import os.path as osp
from typing import Any, Optional, Sequence

from .models import VirtualPackingOptions, VirtualTaskCriteria

COORDINATE_DECIMALS = 2


def canonical_json(value: Any) -> str:
    """Return a deterministic JSON text for hashable payloads."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_digest(payload: Any) -> str:
    """Return the SHA-256 digest of a canonical JSON payload."""

    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def quantize_coordinate(value: Any) -> Optional[float]:
    """Quantize one geometry coordinate to the shared grid."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, COORDINATE_DECIMALS)


def quantize_points(points: Any) -> tuple[tuple[float, float], ...]:
    """Quantize an annotation point list, dropping invalid points."""

    if not isinstance(points, (list, tuple)):
        return ()
    quantized: list[tuple[float, float]] = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        x_value = quantize_coordinate(point[0])
        y_value = quantize_coordinate(point[1])
        if x_value is None or y_value is None:
            continue
        quantized.append((x_value, y_value))
    return tuple(quantized)


def quantize_bbox(
    bbox: Any,
) -> Optional[tuple[float, float, float, float]]:
    """Quantize a ``(left, top, right, bottom)`` box, or ``None``."""

    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    values = [quantize_coordinate(value) for value in bbox]
    if any(value is None for value in values):
        return None
    left, top, right, bottom = values  # type: ignore[misc]
    if right < left or bottom < top:
        return None
    return (left, top, right, bottom)  # type: ignore[misc]


def points_to_bbox(
    points: Sequence[tuple[float, float]],
) -> Optional[tuple[float, float, float, float]]:
    """Return the axis-aligned bounds of a quantized point list."""

    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def geometry_fingerprint(points: Any, bbox: Any = None) -> Optional[str]:
    """Return the shared geometry fingerprint of one member shape.

    The fingerprint prefers the full quantized point list and falls back
    to the quantized bbox when points are unavailable.  Both build-time
    and runtime locators must call this function; mixing local
    quantization rules would break identity across restarts.
    """

    quantized = quantize_points(points)
    if quantized:
        payload: Any = {"pts": [list(point) for point in quantized]}
    else:
        box = quantize_bbox(bbox)
        if box is None:
            return None
        payload = {"bbox": list(box)}
    return canonical_digest(payload)


def criteria_to_dict(criteria: VirtualTaskCriteria) -> dict:
    """Serialize criteria into a canonical JSON-ready dict."""

    return {
        "labels": sorted(criteria.labels),
        "shape_types": sorted(criteria.shape_types),
        "group_id_mode": str(criteria.group_id_mode.value),
        "group_id": criteria.group_id,
        "min_width": criteria.min_width,
        "max_width": criteria.max_width,
        "min_height": criteria.min_height,
        "max_height": criteria.max_height,
    }


def criteria_from_dict(payload: Any) -> VirtualTaskCriteria:
    """Deserialize criteria, revalidating through the model constructor."""

    if not isinstance(payload, dict):
        raise ValueError("criteria payload must be a mapping")
    data = dict(payload)
    data["labels"] = frozenset(str(x) for x in data.get("labels", ()))
    data["shape_types"] = frozenset(
        str(x) for x in data.get("shape_types", ())
    )
    try:
        return VirtualTaskCriteria(**data)
    except TypeError as exc:
        raise ValueError(f"invalid criteria payload: {exc}") from exc


def packing_to_dict(options: VirtualPackingOptions) -> dict:
    """Serialize packing options into a canonical JSON-ready dict."""

    return {
        "mode": str(options.mode.value),
        "max_tasks_per_page": options.max_tasks_per_page,
        "min_projected_anchor_px": options.min_projected_anchor_px,
        "min_projected_gap_px": options.min_projected_gap_px,
        "fit_margin": options.fit_margin,
    }


def packing_from_dict(payload: Any) -> VirtualPackingOptions:
    """Deserialize packing options via the validating constructor."""

    if not isinstance(payload, dict):
        raise ValueError("packing payload must be a mapping")
    try:
        return VirtualPackingOptions(**payload)
    except TypeError as exc:
        raise ValueError(f"invalid packing payload: {exc}") from exc


def normalize_relative_path(root: str, path: str) -> str:
    """Return a canonical POSIX-style path relative to ``root``.

    The stored form never depends on the host platform's separator, so
    a sidecar written on Windows rebinds on any other platform.  Paths
    outside ``root`` are stored relative anyway (with ``..`` segments)
    instead of failing, preserving reviewer-chosen layouts.
    """

    root_text = str(root)
    path_text = str(path)
    if not root_text:
        return osp.relpath(path_text, ".").replace("\\", "/")
    return osp.relpath(path_text, root_text).replace("\\", "/")


def resolve_relative_path(root: str, rel_path: str) -> str:
    """Rejoin a stored relative path under ``root``."""

    rel_text = str(rel_path).replace("\\", "/")
    joined = osp.join(str(root), *rel_text.split("/"))
    return osp.normpath(joined)


def member_snapshot_dict(
    ordinal: int,
    label: str,
    shape_type: str,
    normalized_group_id: Optional[str],
    bbox: Any,
    point_count: int,
    fingerprint: Optional[str],
) -> dict:
    """Return one canonical member snapshot payload."""

    box = quantize_bbox(bbox)
    return {
        "ordinal": int(ordinal),
        "label": str(label),
        "shape_type": str(shape_type),
        "gid": normalized_group_id,
        "bbox": list(box) if box is not None else None,
        "pts": int(point_count),
        "fp": fingerprint,
    }


def locator_signature(locator: Any) -> Optional[str]:
    """Return the task-content signature of a locator payload.

    The signature covers exactly the reviewed member content: labels,
    shape types, normalized group ids, geometry fingerprints, and their
    order.  It deliberately excludes ordinals so that insertions above a
    task do not invalidate freshness, and excludes image dimensions
    because they are constant for one image file.
    """

    if not isinstance(locator, dict):
        return None
    members = locator.get("members")
    if not isinstance(members, (list, tuple)) or not members:
        return None
    payload = [
        {
            "label": member.get("label"),
            "shape_type": member.get("shape_type"),
            "gid": member.get("gid"),
            "fp": member.get("fp"),
            "pts": member.get("pts"),
        }
        for member in members
        if isinstance(member, dict)
    ]
    if len(payload) != len(members):
        return None
    return canonical_digest(payload)


__all__ = [
    "COORDINATE_DECIMALS",
    "canonical_digest",
    "canonical_json",
    "criteria_from_dict",
    "criteria_to_dict",
    "geometry_fingerprint",
    "locator_signature",
    "member_snapshot_dict",
    "normalize_relative_path",
    "packing_from_dict",
    "packing_to_dict",
    "points_to_bbox",
    "quantize_bbox",
    "quantize_coordinate",
    "quantize_points",
    "resolve_relative_path",
]
