"""Pure cross-image object marking and object-level relabel domain logic.

This module has no PyQt dependency. It owns the immutable object
references, the marking store, the strict per-object preflight, the pure
JSON transform, and the object-level facade over the generic JSON
transaction engine in :mod:`label_batch`.
"""

import copy
import json
import os.path as osp
from collections import Counter
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from anylabeling.views.labeling.widgets.label_batch import (
    CancelCheck,
    FileOperationResult,
    JsonTransactionEngine,
    OperationResult,
    ProgressCallback,
    StagedTransform,
)

SHAPE_ID_FIELD = "xanylabeling_shape_id"

STATUS_CHANGEABLE = "changeable"
STATUS_CHANGED = "changed"
STATUS_UNCHANGED = "unchanged"
STATUS_DELETED = "deleted"
STATUS_CONFLICT = "conflict"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_SUCCEEDED = "succeeded"

REMOVE_ON_RESULT = frozenset(
    {STATUS_SUCCEEDED, STATUS_UNCHANGED, STATUS_DELETED}
)
KEEP_ON_RESULT = frozenset({STATUS_CONFLICT, STATUS_FAILED, STATUS_CANCELLED})

ObjectKey = tuple[str, str, str]
PathResolver = Callable[[str], Optional[str]]


class ObjectRelabelPlanError(ValueError):
    """Raised when a snapshot cannot become a valid relabel plan."""


class ObjectIdentityConflict(ValueError):
    """Raised when a target shape id is not unique inside one file."""


def normalize_object_key(
    project_id: str, image_id: str, shape_id: str
) -> ObjectKey:
    """Return the canonical full key for one cross-image object."""
    return (
        str(project_id),
        str(image_id),
        str(shape_id),
    )


@dataclass(frozen=True)
class MarkedObjectRef:
    """Immutable reference to one cross-image marked object.

    ``display_summary`` is a short human hint only; it never participates
    in identity or path resolution.
    """

    project_id: str
    image_id: str
    shape_id: str
    display_summary: str = ""

    def __post_init__(self) -> None:
        """Validate the three identity components."""
        for name in ("project_id", "image_id", "shape_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"MarkedObjectRef.{name} must be a non-empty string"
                )

    @property
    def object_key(self) -> ObjectKey:
        """Return the normalized full object key."""
        return normalize_object_key(
            self.project_id, self.image_id, self.shape_id
        )


@dataclass(frozen=True)
class ObjectRelabelPlan:
    """Immutable object-level relabel plan grouped by annotation file."""

    project_id: str
    target_label: str
    targets_by_annotation_path: Mapping[str, tuple[MarkedObjectRef, ...]]

    @property
    def total_objects(self) -> int:
        """Return the number of unique target object keys."""
        return len(
            {
                ref.object_key
                for refs in self.targets_by_annotation_path.values()
                for ref in refs
            }
        )

    @property
    def file_count(self) -> int:
        """Return the number of involved annotation files."""
        return len(self.targets_by_annotation_path)


def _is_within(path: str, root: str) -> bool:
    """Return whether ``path`` stays inside ``root`` after normalization."""

    def norm(value: str) -> str:
        normalized = osp.abspath(osp.normpath(value))
        return osp.normcase(normalized)

    try:
        return osp.commonpath([norm(path), norm(root)]) == norm(root)
    except ValueError:
        return False


def build_object_relabel_plan(
    refs: Iterable[MarkedObjectRef],
    project_id: str,
    target_label: str,
    annotation_root: str,
    path_resolver: PathResolver,
) -> ObjectRelabelPlan:
    """Build an immutable plan from a frozen marking snapshot.

    The resolver maps an ``image_id`` to its annotation JSON path. Every
    resolved path must stay inside ``annotation_root``; entries from other
    projects, unresolvable images, or escaping paths are rejected.
    """

    label = target_label.strip() if isinstance(target_label, str) else ""
    if not label:
        raise ObjectRelabelPlanError("target label must be a non-empty string")
    if not isinstance(project_id, str) or not project_id.strip():
        raise ObjectRelabelPlanError("project id must be a non-empty string")
    if not isinstance(annotation_root, str) or not annotation_root.strip():
        raise ObjectRelabelPlanError("annotation root must be non-empty")

    problems: list[str] = []
    grouped: dict[str, dict[ObjectKey, MarkedObjectRef]] = {}
    ref_list = list(refs)
    if not ref_list:
        raise ObjectRelabelPlanError("marked object snapshot is empty")
    for ref in ref_list:
        if ref.project_id != project_id:
            problems.append(
                f"{ref.display_summary or ref.shape_id}: belongs to another "
                f"project ({ref.project_id})"
            )
            continue
        resolved = path_resolver(ref.image_id)
        if not resolved:
            problems.append(
                f"{ref.display_summary or ref.shape_id}: cannot resolve "
                f"annotation path for {ref.image_id}"
            )
            continue
        path = osp.abspath(osp.normpath(resolved))
        if not _is_within(path, annotation_root):
            problems.append(
                f"{ref.display_summary or ref.shape_id}: annotation path "
                f"escapes the project root ({path})"
            )
            continue
        grouped.setdefault(path, {})[ref.object_key] = ref
    if problems:
        raise ObjectRelabelPlanError("; ".join(problems))
    targets = MappingProxyType(
        {
            path: tuple(refs_by_key.values())
            for path, refs_by_key in grouped.items()
        }
    )
    return ObjectRelabelPlan(
        project_id=project_id,
        target_label=label,
        targets_by_annotation_path=targets,
    )


@dataclass(frozen=True)
class FileObjectPreflight:
    """Preflight outcome for one annotation file."""

    annotation_path: str
    file_status: str
    object_statuses: Mapping[str, str]
    message: str = ""


@dataclass(frozen=True)
class ObjectPreflightSummary:
    """Aggregated preflight counters shown before confirmation."""

    target_label: str
    snapshot_objects: int
    candidate_files: int
    changeable: int = 0
    unchanged: int = 0
    deleted: int = 0
    conflict: int = 0
    failed: int = 0
    cancelled: bool = False
    file_details: tuple[FileObjectPreflight, ...] = ()


@dataclass(frozen=True)
class ObjectTransformation:
    """Pure per-file transform output for object relabeling."""

    data: Mapping[str, Any]
    changed: bool
    statuses: Mapping[str, str]


def read_annotation_data(path: str) -> dict[str, Any]:
    """Read and structurally validate one annotation JSON file."""

    with open(path, "r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ValueError(f"annotation root must be an object: {path}")
    shapes = data.get("shapes", [])
    if not isinstance(shapes, list):
        raise ValueError(f"annotation shapes must be a list: {path}")
    return data


def _shape_id_counts(
    shapes: Sequence[Any], target_ids: frozenset[str]
) -> dict[str, int]:
    """Count occurrences of target ids among well-formed shape entries."""
    counts: Counter[str] = Counter()
    for shape in shapes:
        if not isinstance(shape, dict):
            continue
        shape_id = shape.get(SHAPE_ID_FIELD)
        if (
            isinstance(shape_id, str)
            and shape_id.strip()
            and shape_id in target_ids
        ):
            counts[shape_id] += 1
    return dict(counts)


def _has_invalid_shape_id(shapes: Sequence[Any]) -> bool:
    """Return whether any shape lacks a valid persistent identity."""
    for shape in shapes:
        if not isinstance(shape, dict):
            return True
        shape_id = shape.get(SHAPE_ID_FIELD)
        if not isinstance(shape_id, str) or not shape_id.strip():
            return True
    return False


def classify_file_objects(
    data: Mapping[str, Any],
    shape_ids: Iterable[str],
    target_label: str,
) -> tuple[str, dict[str, str]]:
    """Classify each requested id as changeable/unchanged/deleted/conflict.

    Returns ``(file_status, statuses)`` where ``file_status`` is ``ok``
    or ``conflict``; duplicate or illegally-typed target ids make the
    whole file conflict.
    """

    shapes = data.get("shapes", [])
    target_ids = frozenset(shape_ids)
    if _has_invalid_shape_id(shapes):
        return (
            STATUS_CONFLICT,
            {shape_id: STATUS_CONFLICT for shape_id in target_ids},
        )
    counts = _shape_id_counts(shapes, target_ids)
    label_by_id: dict[str, str] = {}
    for shape in shapes:
        if not isinstance(shape, dict):
            continue
        shape_id = shape.get(SHAPE_ID_FIELD)
        if isinstance(shape_id, str) and shape_id in counts:
            label_by_id.setdefault(shape_id, shape.get("label"))
    statuses: dict[str, str] = {}
    file_conflict = False
    for shape_id in target_ids:
        occurrences = counts.get(shape_id, 0)
        if occurrences == 0:
            statuses[shape_id] = STATUS_DELETED
        elif occurrences > 1:
            statuses[shape_id] = STATUS_CONFLICT
            file_conflict = True
        elif label_by_id.get(shape_id) == target_label:
            statuses[shape_id] = STATUS_UNCHANGED
        else:
            statuses[shape_id] = STATUS_CHANGEABLE
    return (STATUS_CONFLICT if file_conflict else "ok"), statuses


def transform_objects_by_id(
    data: Mapping[str, Any],
    shape_ids: Iterable[str],
    target_label: str,
) -> ObjectTransformation:
    """Relabel only uniquely-matched target shapes; never mutate input."""

    if not isinstance(data, dict):
        raise ValueError("annotation root must be an object")
    result = copy.deepcopy(dict(data))
    shapes = result.get("shapes", [])
    if not isinstance(shapes, list):
        raise ValueError("annotation JSON shapes must be a list")
    target_ids = frozenset(shape_ids)
    if _has_invalid_shape_id(shapes):
        raise ObjectIdentityConflict(
            "annotation contains missing or invalid shape identities"
        )
    duplicates = {
        shape_id: count
        for shape_id, count in _shape_id_counts(shapes, target_ids).items()
        if count > 1
    }
    if duplicates:
        raise ObjectIdentityConflict(
            "duplicate target shape ids: " + ", ".join(sorted(duplicates))
        )
    statuses: dict[str, str] = {}
    for shape in shapes:
        if not isinstance(shape, dict):
            continue
        shape_id = shape.get(SHAPE_ID_FIELD)
        if isinstance(shape_id, str) and shape_id in target_ids:
            if shape.get("label") == target_label:
                statuses[shape_id] = STATUS_UNCHANGED
            else:
                shape["label"] = target_label
                statuses[shape_id] = STATUS_CHANGED
    for shape_id in target_ids.difference(statuses):
        statuses[shape_id] = STATUS_DELETED
    changed = STATUS_CHANGED in statuses.values()
    return ObjectTransformation(
        data=result,
        changed=changed,
        statuses=MappingProxyType(statuses),
    )


@dataclass(frozen=True)
class ObjectMutationResult:
    """Final per-object outcome keyed by the full object identity."""

    key: ObjectKey
    status: str
    message: str = ""


@dataclass(frozen=True)
class ObjectRelabelResult:
    """Structured aggregate result for one object relabel batch."""

    transaction_id: str
    phase: str
    cancelled: bool
    manifest_path: Optional[str] = None
    objects: tuple[ObjectMutationResult, ...] = ()
    files: tuple[FileOperationResult, ...] = ()

    @property
    def counts(self) -> dict[str, int]:
        """Return stable per-object status counters."""
        counts = {
            STATUS_SUCCEEDED: 0,
            STATUS_UNCHANGED: 0,
            STATUS_DELETED: 0,
            STATUS_CONFLICT: 0,
            STATUS_FAILED: 0,
            STATUS_CANCELLED: 0,
        }
        for item in self.objects:
            counts[item.status] = counts.get(item.status, 0) + 1
        return counts

    @property
    def file_counts(self) -> dict[str, int]:
        """Return per-file status counters."""
        counts: dict[str, int] = {}
        for item in self.files:
            counts[item.status] = counts.get(item.status, 0) + 1
        return counts

    @property
    def committed_annotation_paths(self) -> tuple[str, ...]:
        """Return source paths that were atomically replaced."""
        return tuple(
            osp.abspath(item.source_path)
            for item in self.files
            if item.status == STATUS_SUCCEEDED
        )


@dataclass(frozen=True)
class ObjectStagedBatch:
    """Frozen staging state bridging file operations and object statuses."""

    plan: ObjectRelabelPlan
    operation: OperationResult
    file_object_statuses: Mapping[str, Mapping[str, str]] = field(
        default_factory=dict
    )


class ObjectRelabelEngine:
    """Object-level preflight/stage/commit facade over JSON transactions."""

    def __init__(self, transaction_root: str) -> None:
        """Initialize with the project-owned transaction directory."""
        self._engine = JsonTransactionEngine(transaction_root)

    def preflight(
        self,
        plan: ObjectRelabelPlan,
        cancel_check: Optional[CancelCheck] = None,
        progress: Optional[ProgressCallback] = None,
    ) -> ObjectPreflightSummary:
        """Classify every snapshot object by reading the target files."""
        counters: Counter[str] = Counter()
        details: list[FileObjectPreflight] = []
        cancelled = False
        paths = tuple(plan.targets_by_annotation_path)
        for index, path in enumerate(paths, 1):
            if cancel_check and cancel_check():
                cancelled = True
                break
            ids = _ids_for_path(plan, path)
            try:
                data = read_annotation_data(path)
                file_status, statuses = classify_file_objects(
                    data, ids, plan.target_label
                )
                message = ""
            except (OSError, ValueError) as exc:
                file_status = STATUS_FAILED
                statuses = {shape_id: STATUS_FAILED for shape_id in ids}
                message = str(exc)
            if file_status == STATUS_CONFLICT:
                # The whole file exits staging, so the aggregate counters
                # must not promise any submittable object from it.
                counters.update(
                    {shape_id: STATUS_CONFLICT for shape_id in ids}.values()
                )
            else:
                counters.update(statuses.values())
            details.append(
                FileObjectPreflight(
                    annotation_path=path,
                    file_status=file_status,
                    object_statuses=MappingProxyType(dict(statuses)),
                    message=message,
                )
            )
            if progress:
                progress("preflight", index, len(paths), path)
        return ObjectPreflightSummary(
            target_label=plan.target_label,
            snapshot_objects=plan.total_objects,
            candidate_files=len(details),
            changeable=counters.get(STATUS_CHANGEABLE, 0),
            unchanged=counters.get(STATUS_UNCHANGED, 0),
            deleted=counters.get(STATUS_DELETED, 0),
            conflict=counters.get(STATUS_CONFLICT, 0),
            failed=counters.get(STATUS_FAILED, 0),
            cancelled=cancelled,
            file_details=tuple(details),
        )

    def stage(
        self,
        plan: ObjectRelabelPlan,
        cancel_check: Optional[CancelCheck] = None,
        progress: Optional[ProgressCallback] = None,
    ) -> ObjectStagedBatch:
        """Stage target files with per-object statuses, without replacing."""

        records: dict[str, dict[str, str]] = {}

        def transform(
            source: str, original: Mapping[str, Any]
        ) -> StagedTransform:
            ids = _ids_for_path(plan, source)
            try:
                outcome = transform_objects_by_id(
                    original, ids, plan.target_label
                )
            except ObjectIdentityConflict as exc:
                records[source] = {
                    shape_id: STATUS_CONFLICT for shape_id in ids
                }
                return StagedTransform(
                    data=original,
                    changed=False,
                    skip_reason=str(exc),
                    metadata={"object_statuses": dict(records[source])},
                )
            records[source] = {
                shape_id: (
                    STATUS_CHANGEABLE if status == STATUS_CHANGED else status
                )
                for shape_id, status in outcome.statuses.items()
            }
            matched = sum(
                1
                for status in records[source].values()
                if status == STATUS_CHANGEABLE
            )
            return StagedTransform(
                data=outcome.data,
                changed=outcome.changed,
                matched_shapes=matched,
                metadata={"object_statuses": dict(records[source])},
            )

        operation = self._engine.stage_files(
            tuple(plan.targets_by_annotation_path),
            transform,
            cancel_check,
            progress,
            domain=self._plan_metadata(plan),
        )
        for path in plan.targets_by_annotation_path:
            if path in records:
                continue
            fallback = (
                STATUS_CANCELLED if operation.cancelled else STATUS_FAILED
            )
            records[path] = {
                shape_id: fallback for shape_id in _ids_for_path(plan, path)
            }
        frozen_records = MappingProxyType(
            {
                path: MappingProxyType(dict(statuses))
                for path, statuses in records.items()
            }
        )
        return ObjectStagedBatch(
            plan=plan,
            operation=operation,
            file_object_statuses=frozen_records,
        )

    def commit(
        self, staged: ObjectStagedBatch, root: str
    ) -> ObjectRelabelResult:
        """Atomically commit staged files and derive per-object results."""

        committed = self._engine.commit(staged.operation, root)
        file_status_by_path: dict[str, str] = {}
        for item in committed.files:
            file_status_by_path.setdefault(
                osp.abspath(item.source_path), item.status
            )
        objects: list[ObjectMutationResult] = []
        for path, per_file in staged.file_object_statuses.items():
            file_status = file_status_by_path.get(
                osp.abspath(path), STATUS_FAILED
            )
            for ref in staged.plan.targets_by_annotation_path.get(path, ()):
                stage_status = per_file.get(ref.shape_id, STATUS_FAILED)
                objects.append(
                    ObjectMutationResult(
                        key=ref.object_key,
                        status=_final_status(stage_status, file_status),
                    )
                )
        return ObjectRelabelResult(
            transaction_id=committed.transaction_id,
            phase=committed.phase,
            cancelled=False,
            manifest_path=committed.manifest_path,
            objects=tuple(objects),
            files=committed.files,
        )

    def cancelled_result(
        self,
        staged: Optional[ObjectStagedBatch] = None,
        plan: Optional[ObjectRelabelPlan] = None,
        manifest_path: Optional[str] = None,
    ) -> ObjectRelabelResult:
        """Build an all-cancelled result for an aborted batch."""
        active_plan = staged.plan if staged is not None else plan
        assert active_plan is not None
        objects = tuple(
            ObjectMutationResult(key=ref.object_key, status=STATUS_CANCELLED)
            for refs in active_plan.targets_by_annotation_path.values()
            for ref in refs
        )
        return ObjectRelabelResult(
            transaction_id=(
                staged.operation.transaction_id if staged is not None else ""
            ),
            phase="cancelled",
            cancelled=True,
            manifest_path=manifest_path
            or (
                staged.operation.manifest_path if staged is not None else None
            ),
            objects=objects,
            files=staged.operation.files if staged is not None else (),
        )

    @staticmethod
    def _plan_metadata(plan: ObjectRelabelPlan) -> dict[str, Any]:
        """Return serializable plan metadata for the transaction manifest."""
        return {
            "kind": "object-relabel",
            "project_id": plan.project_id,
            "target_label": plan.target_label,
            "paths": {
                path: sorted({ref.shape_id for ref in refs})
                for path, refs in plan.targets_by_annotation_path.items()
            },
        }


def _ids_for_path(plan: ObjectRelabelPlan, path: str) -> frozenset[str]:
    """Return the target shape ids grouped under one annotation path."""
    return frozenset(
        ref.shape_id for ref in plan.targets_by_annotation_path.get(path, ())
    )


def _final_status(stage_status: str, file_status: str) -> str:
    """Map a staged object status plus file outcome to a final status.

    A failed file leaves the on-disk state unknown, so its changeable
    and unchanged objects become failures that keep their marks for a
    precise retry. ``skipped`` is the normal, verified outcome for
    unchanged-only files and stays successful.
    """

    if stage_status == STATUS_CHANGEABLE:
        return (
            STATUS_SUCCEEDED
            if file_status == STATUS_SUCCEEDED
            else STATUS_FAILED
        )
    if stage_status == STATUS_UNCHANGED:
        if file_status == STATUS_FAILED:
            return STATUS_FAILED
        return STATUS_UNCHANGED
    if stage_status == STATUS_CANCELLED:
        return STATUS_CANCELLED
    return stage_status


@dataclass(frozen=True)
class MarkSyncReport:
    """Structured store change produced by applying one batch result."""

    removed_keys: tuple[ObjectKey, ...] = ()
    kept_keys: tuple[ObjectKey, ...] = ()
    objects_before: int = 0
    objects_after: int = 0


class MarkedObjectStore:
    """Session-scoped single owner of the active cross-image marks.

    The store keeps only :class:`MarkedObjectRef` instances in memory and
    never writes JSON, SQLite, or sidecar files. Snapshots are frozen
    tuples; later store changes cannot alter an in-flight batch.
    """

    def __init__(self) -> None:
        """Initialize an empty marking store."""
        self._marks: dict[ObjectKey, MarkedObjectRef] = {}

    def toggle(self, ref: MarkedObjectRef) -> bool:
        """Add the ref and return True, or remove it and return False."""
        key = ref.object_key
        if key in self._marks:
            del self._marks[key]
            return False
        self._marks[key] = ref
        return True

    def contains(self, key: ObjectKey) -> bool:
        """Return whether the full object key is currently marked."""
        return key in self._marks

    def snapshot(self) -> tuple[MarkedObjectRef, ...]:
        """Return a frozen snapshot ordered by the full object key."""
        return tuple(
            self._marks[key] for key in sorted(self._marks, key=_key_order)
        )

    def snapshot_for_project(
        self, project_id: str
    ) -> tuple[MarkedObjectRef, ...]:
        """Return a frozen snapshot limited to one project."""
        return tuple(
            self._marks[key]
            for key in sorted(self._marks, key=_key_order)
            if key[0] == project_id
        )

    def refs_for_image(
        self, project_id: str, image_id: str
    ) -> tuple[MarkedObjectRef, ...]:
        """Return marks belonging to one image, ordered by shape id."""
        return tuple(
            self._marks[key]
            for key in sorted(self._marks, key=_key_order)
            if key[0] == project_id and key[1] == image_id
        )

    def remove(self, key: ObjectKey) -> bool:
        """Remove one mark by full key; return whether it existed."""
        if key in self._marks:
            del self._marks[key]
            return True
        return False

    def remove_many(self, keys: Iterable[ObjectKey]) -> int:
        """Remove several marks; return how many actually existed."""
        removed = 0
        for key in keys:
            if self.remove(key):
                removed += 1
        return removed

    def clear(self) -> int:
        """Remove every mark; return how many were cleared."""
        count = len(self._marks)
        self._marks.clear()
        return count

    def counts(self) -> dict[str, int]:
        """Return object and file counters for UI badges."""
        files = {(key[0], key[1]) for key in self._marks}
        return {"objects": len(self._marks), "files": len(files)}

    def counts_for_project(self, project_id: str) -> dict[str, int]:
        """Return object and file counters limited to one project."""
        project_keys = [key for key in self._marks if key[0] == project_id]
        files = {(key[0], key[1]) for key in project_keys}
        return {"objects": len(project_keys), "files": len(files)}

    def apply_relabel_result(
        self, result: ObjectRelabelResult
    ) -> MarkSyncReport:
        """Sync marks with per-object results without touching others."""
        before = len(self._marks)
        removed: list[ObjectKey] = []
        kept: list[ObjectKey] = []
        for item in result.objects:
            if item.status in REMOVE_ON_RESULT:
                if self.remove(item.key):
                    removed.append(item.key)
            else:
                kept.append(item.key)
        return MarkSyncReport(
            removed_keys=tuple(removed),
            kept_keys=tuple(kept),
            objects_before=before,
            objects_after=len(self._marks),
        )

    def apply_field_edit_result(self, result) -> MarkSyncReport:
        """Sync marks with a field-edit result without touching others.

        The field-edit domain object intentionally lives in a separate
        module, so this method uses its small structural ``objects``
        contract instead of importing that module and creating a cycle.
        """
        before = len(self._marks)
        removed: list[ObjectKey] = []
        kept: list[ObjectKey] = []
        for item in result.objects:
            if item.status in REMOVE_ON_RESULT:
                if self.remove(item.key):
                    removed.append(item.key)
            else:
                kept.append(item.key)
        return MarkSyncReport(
            removed_keys=tuple(removed),
            kept_keys=tuple(kept),
            objects_before=before,
            objects_after=len(self._marks),
        )


def _key_order(key: ObjectKey) -> tuple[str, str, str]:
    """Return the sortable identity for deterministic snapshots."""
    return key
