"""Read-only file manifest and input adapters for inspection runs."""

from __future__ import annotations

import hashlib
import json
import math
import os
import os.path as osp
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from anylabeling.views.labeling.shape_identity import (
    SHAPE_ID_FIELD,
    validate_shape_identities,
)

from .models import FileSnapshot, Manifest, ShapeSnapshot, utc_now_iso

IMAGE_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
)


def annotation_path_for(image_path: str, output_dir: str = "") -> str:
    """Resolve the single annotation path used by the application."""
    stem = osp.splitext(osp.basename(image_path))[0] + ".json"
    if output_dir:
        return osp.join(output_dir, stem)
    return osp.join(osp.dirname(image_path), stem)


def _digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def shape_collection_digest(
    shapes: Sequence[ShapeSnapshot],
) -> str:
    """Stable digest of parsed shapes for memory/disk comparison."""
    normalized = []
    for shape in shapes:
        item = shape.to_dict()
        if not shape.identity_valid:
            item["shape_id"] = ""
        if shape.shape_type == "rectangle" and shape.points:
            xs = [round(point[0], 6) for point in shape.points]
            ys = [round(point[1], 6) for point in shape.points]
            item["points"] = [
                [min(xs), min(ys)],
                [max(xs), min(ys)],
                [max(xs), max(ys)],
                [min(xs), max(ys)],
            ]
        normalized.append(item)
    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return _digest_bytes(payload.encode("utf-8"))


def file_digest(path: str, *, content: bool = True) -> str:
    """Return a content digest, falling back to stat identity when needed."""
    if not path or not osp.isfile(path):
        return ""
    if content:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    stat = os.stat(path)
    return hashlib.sha256(
        f"{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8")
    ).hexdigest()


def _relative_path(path: str, root: str) -> str:
    if root:
        try:
            return osp.relpath(path, root).replace("\\", "/")
        except ValueError:
            pass
    return osp.basename(path).replace("\\", "/")


def _parse_points(raw_points: Any) -> tuple[tuple[float, float], ...]:
    points: list[tuple[float, float]] = []
    if not isinstance(raw_points, (list, tuple)):
        return ()
    for point in raw_points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        try:
            x_value = float(point[0])
            y_value = float(point[1])
        except (TypeError, ValueError):
            continue
        points.append((x_value, y_value))
    return tuple(points)


def _group_id(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def shape_snapshots_from_raw(
    raw_shapes: Sequence[Any],
    *,
    digest_prefix: str = "",
) -> tuple[tuple[ShapeSnapshot, ...], tuple[Mapping[str, Any], ...]]:
    """Parse shape dicts with read-only identity diagnostics.

    Missing or duplicate identities receive an ephemeral identity that is
    valid only for this snapshot. Nothing is written back to the file.
    """
    validated_shapes = [
        item for item in raw_shapes if isinstance(item, Mapping)
    ]
    identities = [
        (
            item.get(SHAPE_ID_FIELD)
            if isinstance(item, Mapping)
            and isinstance(item.get(SHAPE_ID_FIELD), str)
            and item.get(SHAPE_ID_FIELD)
            else None
        )
        for item in validated_shapes
    ]
    diagnostics = {
        item.index: item for item in validate_shape_identities(identities)
    }
    shapes: list[ShapeSnapshot] = []
    issues: list[Mapping[str, Any]] = []
    for index, item in enumerate(validated_shapes):
        diagnostic = diagnostics.get(index)
        serialized_id = identities[index] or ""
        if diagnostic is None:
            shape_id = serialized_id
            identity_valid = True
            reason = ""
        else:
            shape_id = f"ephemeral-{digest_prefix[:8] or 'snapshot'}-{index}"
            identity_valid = False
            reason = diagnostic.reason
            issues.append(
                {
                    "relative_path": "",
                    "shape_index": index,
                    "reason": diagnostic.reason,
                    "original_id": (
                        None
                        if diagnostic.original_id is None
                        else str(diagnostic.original_id)
                    ),
                }
            )
        shape_type = str(item.get("shape_type", "") or "")
        points = _parse_points(item.get("points", []))
        if shape_type == "rectangle" and len(points) == 2:
            x1, y1 = points[0]
            x2, y2 = points[1]
            points = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
        shapes.append(
            ShapeSnapshot(
                shape_id=shape_id,
                index=index,
                label=str(item.get("label", "") or ""),
                shape_type=shape_type,
                points=points,
                group_id=_group_id(item.get("group_id")),
                flags=(
                    dict(item.get("flags", {}) or {})
                    if isinstance(item.get("flags"), Mapping)
                    else {}
                ),
                attributes=(
                    dict(item.get("attributes", {}) or {})
                    if isinstance(item.get("attributes"), Mapping)
                    else {}
                ),
                difficult=bool(item.get("difficult", False)),
                identity_valid=identity_valid,
                identity_reason=reason,
            )
        )
    for issue in issues:
        issue["relative_path"] = ""
    return tuple(shapes), tuple(issues)


def load_file_snapshot(
    image_path: str,
    dataset_root: str = "",
    output_dir: str = "",
    *,
    relative_path: str = "",
    annotation_path: str = "",
    hash_images: bool = False,
) -> FileSnapshot:
    """Read one image/annotation pair without modifying either file."""
    image_path = osp.abspath(image_path)
    annotation_path = annotation_path or annotation_path_for(
        image_path, output_dir
    )
    relative = relative_path or _relative_path(image_path, dataset_root)
    image_digest = (
        file_digest(image_path, content=True)
        if hash_images
        else file_digest(image_path, content=False)
    )
    if not osp.isfile(annotation_path):
        return FileSnapshot(
            relative_path=relative,
            image_path=image_path,
            annotation_path=annotation_path,
            image_digest=image_digest,
            annotation_state="missing",
            shapes=(),
            read_at=utc_now_iso(),
        )
    try:
        with open(annotation_path, "rb") as handle:
            payload = handle.read()
        data = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return FileSnapshot(
            relative_path=relative,
            image_path=image_path,
            annotation_path=annotation_path,
            image_digest=image_digest,
            annotation_digest=(
                _digest_bytes(payload) if "payload" in locals() else ""
            ),
            annotation_state="error",
            error=str(error),
            read_at=utc_now_iso(),
        )
    if not isinstance(data, Mapping):
        return FileSnapshot(
            relative_path=relative,
            image_path=image_path,
            annotation_path=annotation_path,
            image_digest=image_digest,
            annotation_digest=_digest_bytes(payload),
            annotation_state="error",
            error="annotation JSON root must be an object",
            read_at=utc_now_iso(),
        )
    digest = _digest_bytes(payload)
    try:
        width = int(data.get("imageWidth", 0) or 0)
        height = int(data.get("imageHeight", 0) or 0)
    except (TypeError, ValueError) as error:
        return FileSnapshot(
            relative_path=relative,
            image_path=image_path,
            annotation_path=annotation_path,
            annotation_digest=digest,
            image_digest=image_digest,
            annotation_state="error",
            error=f"invalid image dimensions: {error}",
            read_at=utc_now_iso(),
        )
    shapes, identity_issues = shape_snapshots_from_raw(
        data.get("shapes", []) or [], digest_prefix=digest
    )
    for issue in identity_issues:
        issue["relative_path"] = relative
    return FileSnapshot(
        relative_path=relative,
        image_path=image_path,
        annotation_path=annotation_path,
        image_width=width,
        image_height=height,
        annotation_digest=digest,
        shape_digest=shape_collection_digest(shapes),
        image_digest=image_digest,
        shapes=shapes,
        annotation_state="present",
        read_at=utc_now_iso(),
    )


def memory_file_snapshot(
    image_path: str,
    relative_path: str,
    shapes_data: Sequence[Mapping[str, Any]],
    *,
    image_width: int = 0,
    image_height: int = 0,
    output_dir: str = "",
    annotation_path: str = "",
    unsaved: bool = True,
) -> FileSnapshot:
    """Build a current in-memory snapshot without reading or writing JSON."""
    normalized = [
        dict(item) for item in shapes_data if isinstance(item, Mapping)
    ]
    payload = json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, default=str
    ).encode("utf-8")
    digest = _digest_bytes(payload)
    shapes, identity_issues = shape_snapshots_from_raw(
        normalized, digest_prefix=digest
    )
    for issue in identity_issues:
        issue["relative_path"] = relative_path
    return FileSnapshot(
        relative_path=relative_path,
        image_path=osp.abspath(image_path) if image_path else "",
        annotation_path=(
            annotation_path or annotation_path_for(image_path, output_dir)
        ),
        image_width=int(image_width),
        image_height=int(image_height),
        annotation_digest=digest,
        shape_digest=shape_collection_digest(shapes),
        image_digest="",
        shapes=shapes,
        annotation_state="memory",
        unsaved=bool(unsaved),
        read_at=utc_now_iso(),
    )


def scan_image_paths(
    directory: str,
    extensions: Sequence[str] = IMAGE_EXTENSIONS,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> list[str]:
    """Enumerate image files in stable natural-ish order."""
    allowed = {extension.lower() for extension in extensions}
    paths: list[str] = []
    for root, directories, files in os.walk(directory):
        directories.sort()
        for name in sorted(files):
            if should_cancel is not None and should_cancel():
                return paths
            if osp.splitext(name)[1].lower() in allowed:
                paths.append(osp.join(root, name))
    return paths


def build_manifest(
    dataset_root: str,
    output_dir: str = "",
    image_paths: Optional[Iterable[str]] = None,
    *,
    extensions: Sequence[str] = IMAGE_EXTENSIONS,
    hash_images: bool = False,
    excluded_paths: Iterable[str] = (),
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Manifest:
    """Build a complete manifest, preserving per-file read failures."""
    dataset_root = osp.abspath(dataset_root) if dataset_root else ""
    if image_paths is None:
        paths = scan_image_paths(
            dataset_root, extensions=extensions, should_cancel=should_cancel
        )
    else:
        paths = [osp.abspath(path) for path in image_paths]
    excluded = {osp.abspath(path) for path in excluded_paths}
    if excluded:
        paths = [path for path in paths if osp.abspath(path) not in excluded]
    files: list[FileSnapshot] = []
    errors: list[Mapping[str, Any]] = []
    cancelled = False
    for path in paths:
        if should_cancel is not None and should_cancel():
            cancelled = True
            break
        try:
            files.append(
                load_file_snapshot(
                    path,
                    dataset_root,
                    output_dir,
                    hash_images=hash_images,
                )
            )
        except (OSError, ValueError) as error:
            errors.append(
                {
                    "relative_path": _relative_path(path, dataset_root),
                    "image_path": path,
                    "error": str(error),
                }
            )
    files.sort(key=lambda item: item.relative_path)
    return Manifest(
        dataset_root=dataset_root,
        output_root=osp.abspath(output_dir) if output_dir else "",
        files=tuple(files),
        errors=tuple(errors),
        complete=not cancelled,
        generated_at=utc_now_iso(),
    )


def filter_manifest(
    manifest: Manifest, relative_paths: Iterable[str]
) -> Manifest:
    """Return a manifest restricted to explicit file identities."""
    selected = {str(path).replace("\\", "/") for path in relative_paths}
    files = tuple(
        file for file in manifest.files if file.relative_path in selected
    )
    return Manifest(
        dataset_root=manifest.dataset_root,
        output_root=manifest.output_root,
        files=files,
        errors=manifest.errors,
        complete=manifest.complete,
        generated_at=manifest.generated_at,
    )


def changed_relative_paths(
    previous: Optional[Manifest], current: Manifest
) -> tuple[str, ...]:
    """Compare content digests, including added and removed files."""
    if previous is None:
        return tuple(file.relative_path for file in current.files)
    old = {
        file.relative_path: file.annotation_digest for file in previous.files
    }
    new = {
        file.relative_path: file.annotation_digest for file in current.files
    }
    changed = {
        path
        for path in set(old).union(new)
        if old.get(path, "") != new.get(path, "")
    }
    return tuple(sorted(changed))


def is_finite_points(shape: ShapeSnapshot) -> bool:
    """Return whether all parsed coordinates are finite numbers."""
    return all(
        math.isfinite(point[0]) and math.isfinite(point[1])
        for point in shape.points
    )
