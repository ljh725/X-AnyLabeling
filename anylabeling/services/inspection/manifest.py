"""Read-only file manifest and input adapters for inspection runs."""

from __future__ import annotations

import hashlib
import json
import math
import os
import os.path as osp
from dataclasses import dataclass, field
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

EXCLUDED_REASON = "用户显式排除（未保存画布或人工排除）"


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
        if shape.shape_type == "rectangle" and len(shape.points) >= 2:
            xs = [point[0] for point in shape.points]
            ys = [point[1] for point in shape.points]
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


def image_orientation(path: str) -> str:
    """Return the EXIF orientation value of an image, or "" when unknown."""
    if not path or not osp.isfile(path):
        return ""
    try:
        from PIL import Image

        with Image.open(path) as image:
            value = image.getexif().get(0x0112, 1)
    except (OSError, ValueError, ImportError):
        return ""
    return str(int(value or 1))


def file_digest(path: str, *, content: bool = True) -> str:
    """Return a content digest, falling back to stat identity when needed."""
    if not path or not osp.isfile(path):
        return ""
    if content:
        digest = hashlib.sha256()
        try:
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            return ""
        return digest.hexdigest()
    try:
        stat = os.stat(path)
    except OSError:
        return ""
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


def _parse_points(
    raw_points: Any,
) -> tuple[tuple[tuple[float, float], ...], tuple[str, ...]]:
    """Parse coordinates without silently dropping malformed input.

    Invalid points are reported as diagnostics instead of being trimmed:
    trimming a rectangle down to two remaining points would fabricate a
    legal rectangle that never existed in the file.
    """
    points: list[tuple[float, float]] = []
    errors: list[str] = []
    if not isinstance(raw_points, (list, tuple)):
        return (), ("points 不是数组",)
    for index, point in enumerate(raw_points):
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            errors.append(f"第 {index} 个点不是坐标对")
            continue
        if isinstance(point[0], bool) or isinstance(point[1], bool):
            errors.append(f"第 {index} 个点坐标不是数值")
            continue
        try:
            x_value = float(point[0])
            y_value = float(point[1])
        except (TypeError, ValueError):
            errors.append(f"第 {index} 个点坐标不是数值")
            continue
        if not math.isfinite(x_value) or not math.isfinite(y_value):
            errors.append(f"第 {index} 个点坐标不是有限数值")
            continue
        points.append((x_value, y_value))
    return tuple(points), tuple(errors)


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
    """Parse shape dicts with read-only identity/input diagnostics.

    Missing or duplicate identities receive an ephemeral identity that is
    valid only for this snapshot. Nothing is written back to the file.
    Malformed coordinates are preserved as diagnostics on the snapshot so
    rules can report them instead of analysing a trimmed shape.
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
        points, point_errors = _parse_points(item.get("points", []))
        input_errors = list(point_errors)
        if shape_type == "rectangle" and len(points) == 2 and not point_errors:
            x1, y1 = points[0]
            x2, y2 = points[1]
            points = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
        group_raw = item.get("group_id")
        if group_raw not in (None, ""):
            group_id = _group_id(group_raw)
            if group_id is None:
                input_errors.append("group_id 不是非负整数")
        else:
            group_id = None
        shapes.append(
            ShapeSnapshot(
                shape_id=shape_id,
                index=index,
                label=str(item.get("label", "") or ""),
                shape_type=shape_type,
                points=points,
                group_id=group_id,
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
                input_errors=tuple(input_errors),
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
    hash_images: bool = True,
    read_orientation: bool = True,
) -> FileSnapshot:
    """Read one image/annotation pair without modifying either file."""
    image_path = osp.abspath(image_path)
    annotation_path = annotation_path or annotation_path_for(
        image_path, output_dir
    )
    relative = relative_path or _relative_path(image_path, dataset_root)
    image_digest = file_digest(image_path, content=hash_images)
    image_digest_kind = (
        ("content" if hash_images else "stat") if image_digest else ""
    )
    orientation = image_orientation(image_path) if read_orientation else ""
    if not osp.isfile(annotation_path):
        return FileSnapshot(
            relative_path=relative,
            image_path=image_path,
            annotation_path=annotation_path,
            image_digest=image_digest,
            image_digest_kind=image_digest_kind,
            image_orientation=orientation,
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
            image_digest_kind=image_digest_kind,
            image_orientation=orientation,
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
            image_digest_kind=image_digest_kind,
            image_orientation=orientation,
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
            image_digest_kind=image_digest_kind,
            image_orientation=orientation,
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
        annotation_normalized_digest=shape_collection_digest(shapes),
        image_digest=image_digest,
        image_digest_kind=image_digest_kind,
        image_orientation=orientation,
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
    image_digest: str = "",
    image_digest_kind: str = "",
) -> FileSnapshot:
    """Build a current in-memory snapshot without reading or writing JSON.

    The image identity is fixed from the file on disk (content digest) so a
    report for the current image can still be verified later; if the image
    cannot be read the digest stays empty and verification reports that the
    image identity is unverifiable instead of pretending it matches.
    """
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
    absolute_image = osp.abspath(image_path) if image_path else ""
    if not image_digest and absolute_image:
        image_digest = file_digest(absolute_image, content=True)
        image_digest_kind = "content" if image_digest else ""
    orientation = image_orientation(absolute_image) if absolute_image else ""
    normalized_digest = shape_collection_digest(shapes)
    return FileSnapshot(
        relative_path=relative_path,
        image_path=absolute_image,
        annotation_path=(
            annotation_path or annotation_path_for(image_path, output_dir)
        ),
        image_width=int(image_width),
        image_height=int(image_height),
        annotation_digest=digest,
        shape_digest=normalized_digest,
        annotation_normalized_digest=normalized_digest,
        image_digest=image_digest,
        image_digest_kind=image_digest_kind,
        image_orientation=orientation,
        shapes=shapes,
        annotation_state="memory",
        unsaved=bool(unsaved),
        read_at=utc_now_iso(),
    )


def scan_image_paths(
    directory: str,
    extensions: Sequence[str] = IMAGE_EXTENSIONS,
    should_cancel: Optional[Callable[[], bool]] = None,
    progress: Optional[Callable[[int, int, str], None]] = None,
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
                if progress is not None:
                    progress(
                        len(paths), 0, _relative_path(paths[-1], directory)
                    )
    return paths


def build_manifest(
    dataset_root: str,
    output_dir: str = "",
    image_paths: Optional[Iterable[str]] = None,
    *,
    extensions: Sequence[str] = IMAGE_EXTENSIONS,
    hash_images: bool = True,
    excluded_paths: Iterable[str] = (),
    should_cancel: Optional[Callable[[], bool]] = None,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> Manifest:
    """Build a complete manifest, preserving failures and exclusions."""
    dataset_root = osp.abspath(dataset_root) if dataset_root else ""
    excluded = [osp.abspath(path) for path in excluded_paths if path]
    excluded_set = set(excluded)
    if image_paths is None:
        paths = scan_image_paths(
            dataset_root,
            extensions=extensions,
            should_cancel=should_cancel,
            progress=progress,
        )
    else:
        paths = [osp.abspath(path) for path in image_paths]
    if excluded_set:
        paths = [
            path for path in paths if osp.abspath(path) not in excluded_set
        ]
    excluded_entries = tuple(
        {
            "relative_path": _relative_path(path, dataset_root),
            "image_path": path,
            "reason": EXCLUDED_REASON,
        }
        for path in sorted(excluded_set)
    )
    files: list[FileSnapshot] = []
    errors: list[Mapping[str, Any]] = []
    cancelled = False
    for index, path in enumerate(paths):
        if should_cancel is not None and should_cancel():
            cancelled = True
            break
        if progress is not None:
            progress(index, len(paths), _relative_path(path, dataset_root))
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
        if progress is not None:
            progress(index + 1, len(paths), _relative_path(path, dataset_root))
    files.sort(key=lambda item: item.relative_path)
    return Manifest(
        dataset_root=dataset_root,
        output_root=osp.abspath(output_dir) if output_dir else "",
        files=tuple(files),
        errors=tuple(errors),
        excluded=excluded_entries,
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
        excluded=manifest.excluded,
        complete=manifest.complete,
        generated_at=manifest.generated_at,
    )


@dataclass(frozen=True)
class ManifestDelta:
    """Explicit comparison result for the "changed files" scope."""

    added: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    reasons: Mapping[str, str] = field(default_factory=dict)
    conservative: bool = False

    @property
    def changed(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.added) | set(self.modified)))

    def notes(self) -> tuple[str, ...]:
        notes: list[str] = []
        if self.added:
            notes.append(f"新增文件 {len(self.added)} 个")
        if self.modified:
            notes.append(f"内容变化文件 {len(self.modified)} 个")
        if self.removed:
            notes.append(
                "已移除文件 {} 个: {}".format(
                    len(self.removed), ", ".join(self.removed[:5])
                )
            )
        if not self.changed and not self.removed:
            notes.append("未发现输入变化")
        return tuple(notes)


def _comparison_values(file: FileSnapshot) -> tuple[Any, ...]:
    """Identity used by the changed-file scope.

    ``annotation_state`` is part of the identity so "no annotation file at
    all" can never be confused with "annotation file with zero shapes".
    """
    return (
        file.annotation_state,
        file.annotation_digest,
        file.shape_digest,
        file.image_digest_kind,
        file.image_digest,
        file.image_width,
        file.image_height,
        file.image_orientation,
    )


def compare_manifests(
    previous: Optional[Manifest],
    current: Manifest,
    *,
    config_changed: bool = False,
) -> ManifestDelta:
    """Compare manifests without silently shrinking the checked scope."""
    if previous is None or previous.complete is False:
        reason = (
            "没有可信的上一份清单，保守检查全部文件"
            if previous is None
            else "上一份清单扫描未完成，保守检查全部文件"
        )
        return ManifestDelta(
            added=tuple(file.relative_path for file in current.files),
            removed=(),
            unchanged=(),
            reasons={file.relative_path: reason for file in current.files},
            conservative=True,
        )
    old = {file.relative_path: file for file in previous.files}
    new = {file.relative_path: file for file in current.files}
    added: list[str] = []
    modified: list[str] = []
    unchanged: list[str] = []
    removed: list[str] = []
    reasons: dict[str, str] = {}
    if config_changed:
        # A profile or rule implementation change invalidates every previous
        # result: the scope must fall back to the complete current set.
        for path in new:
            if path in old:
                modified.append(path)
                reasons[path] = "方案或规则实现版本变化"
            else:
                added.append(path)
                reasons[path] = "新增文件"
        removed = sorted(path for path in old if path not in new)
        return ManifestDelta(
            added=tuple(sorted(added)),
            modified=tuple(sorted(modified)),
            removed=tuple(removed),
            unchanged=(),
            reasons=reasons,
            conservative=False,
        )
    for path, file in new.items():
        old_file = old.get(path)
        if old_file is None:
            added.append(path)
            reasons[path] = "新增文件"
            continue
        if _comparison_values(old_file) == _comparison_values(file):
            unchanged.append(path)
            continue
        detail = []
        if (
            old_file.annotation_state != file.annotation_state
            or old_file.annotation_digest != file.annotation_digest
        ):
            detail.append("标注状态或内容变化")
        if (
            old_file.image_digest != file.image_digest
            or old_file.image_digest_kind != file.image_digest_kind
        ):
            detail.append("图片内容变化")
        if (
            old_file.image_width != file.image_width
            or old_file.image_height != file.image_height
        ):
            detail.append("图片尺寸变化")
        if old_file.image_orientation != file.image_orientation:
            detail.append("图片方向变化")
        reasons[path] = "、".join(detail) or "文件身份变化"
        modified.append(path)
    for path in old:
        if path not in new:
            removed.append(path)
    return ManifestDelta(
        added=tuple(sorted(added)),
        modified=tuple(sorted(modified)),
        removed=tuple(sorted(removed)),
        unchanged=tuple(sorted(unchanged)),
        reasons=reasons,
        conservative=False,
    )


def changed_relative_paths(
    previous: Optional[Manifest], current: Manifest
) -> tuple[str, ...]:
    """Compare content digests, including added files and image identity."""
    return compare_manifests(previous, current).changed


def is_finite_points(shape: ShapeSnapshot) -> bool:
    """Return whether all parsed coordinates are finite numbers."""
    return all(
        math.isfinite(point[0]) and math.isfinite(point[1])
        for point in shape.points
    )
