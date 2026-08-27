"""Project-wide persistence helpers for Shape identities."""

from __future__ import annotations

import json
import os
import os.path as osp
import stat
import tempfile
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from .shape_identity import (
    MISSING_SHAPE_ID,
    SHAPE_ID_FIELD,
    normalize_shape_identities,
)


@dataclass(frozen=True)
class ProjectShapeIdentityFileResult:
    """Describe the identity changes made to one annotation file."""

    path: str
    changed: bool
    assigned_count: int
    error: Optional[str] = None


@dataclass(frozen=True)
class ProjectShapeIdentityResult:
    """Summarize a project-wide Shape identity operation."""

    files_scanned: int
    files_changed: int
    shapes_assigned: int
    files_failed: int
    file_results: tuple[ProjectShapeIdentityFileResult, ...]


def discover_project_json_files(roots: Iterable[str]) -> tuple[str, ...]:
    """Return deduplicated JSON annotation files below ``roots``.

    Roots may overlap, which is common when the annotation output directory is
    inside the image project directory.  Paths are normalized before
    deduplication, while the returned order is deterministic.
    """
    discovered: dict[str, str] = {}
    for root in roots:
        if not root:
            continue
        root_path = osp.abspath(osp.normpath(str(root)))
        if osp.isfile(root_path):
            if root_path.lower().endswith(".json"):
                discovered.setdefault(osp.normcase(root_path), root_path)
            continue
        if not osp.isdir(root_path):
            continue
        for current_root, _directories, filenames in os.walk(root_path):
            for filename in filenames:
                if filename.lower().endswith(".json"):
                    path = osp.abspath(osp.join(current_root, filename))
                    discovered.setdefault(osp.normcase(path), path)
    return tuple(discovered[key] for key in sorted(discovered))


def ensure_project_shape_ids(
    json_paths: Iterable[str],
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> ProjectShapeIdentityResult:
    """Assign and persist unique Shape IDs for the supplied JSON files.

    Files that already satisfy the identity invariant are left untouched.
    Each file is processed independently so one malformed or inaccessible
    annotation does not discard successful repairs in other files.
    """
    file_results = []
    paths = tuple(str(path) for path in json_paths)
    total = len(paths)
    for index, path in enumerate(paths, start=1):
        try:
            result = _ensure_file_shape_ids(str(path))
        except (
            Exception
        ) as exc:  # pragma: no cover - defensive filesystem guard
            result = ProjectShapeIdentityFileResult(
                path=str(path),
                changed=False,
                assigned_count=0,
                error=str(exc),
            )
        file_results.append(result)
        if progress_callback is not None:
            progress_callback(index, total)

    return ProjectShapeIdentityResult(
        files_scanned=len(file_results),
        files_changed=sum(result.changed for result in file_results),
        shapes_assigned=sum(result.assigned_count for result in file_results),
        files_failed=sum(result.error is not None for result in file_results),
        file_results=tuple(file_results),
    )


def _ensure_file_shape_ids(path: str) -> ProjectShapeIdentityFileResult:
    """Repair one JSON file and atomically persist it when needed."""
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return ProjectShapeIdentityFileResult(
            path=path,
            changed=False,
            assigned_count=0,
        )

    if "shapes" not in data:
        return ProjectShapeIdentityFileResult(
            path=path,
            changed=False,
            assigned_count=0,
        )

    raw_shapes = data["shapes"]
    if not isinstance(raw_shapes, list):
        raise ValueError("JSON 'shapes' field must be an array")
    if any(not isinstance(shape, dict) for shape in raw_shapes):
        raise ValueError("each JSON Shape must be an object")

    normalized = normalize_shape_identities(
        shape.get(SHAPE_ID_FIELD, MISSING_SHAPE_ID) for shape in raw_shapes
    )
    identity_order_changed = any(
        not shape or next(iter(shape)) != SHAPE_ID_FIELD
        for shape in raw_shapes
    )
    if not normalized.diagnostics and not identity_order_changed:
        return ProjectShapeIdentityFileResult(
            path=path,
            changed=False,
            assigned_count=0,
        )

    repaired_shapes = []
    for shape, shape_id in zip(raw_shapes, normalized.identities):
        repaired_shape = {SHAPE_ID_FIELD: shape_id}
        repaired_shape.update(
            (key, value)
            for key, value in shape.items()
            if key != SHAPE_ID_FIELD
        )
        repaired_shapes.append(repaired_shape)
    data["shapes"] = repaired_shapes
    _atomic_json_dump(path, data)
    return ProjectShapeIdentityFileResult(
        path=path,
        changed=True,
        assigned_count=normalized.repaired_count,
    )


def _atomic_json_dump(path: str, data: dict) -> None:
    """Write JSON beside its source and replace the source atomically."""
    source_mode = stat.S_IMODE(os.stat(path).st_mode)
    temporary_path = None
    try:
        file_descriptor, temporary_path = tempfile.mkstemp(
            prefix=f".{osp.basename(path)}.",
            suffix=".tmp",
            dir=osp.dirname(osp.abspath(path)),
            text=True,
        )
        os.chmod(temporary_path, source_mode)
        with os.fdopen(
            file_descriptor, "w", encoding="utf-8", newline=""
        ) as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path and osp.exists(temporary_path):
            try:
                os.remove(temporary_path)
            except OSError:
                pass
