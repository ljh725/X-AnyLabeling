"""Pure Python batch editing for fields on marked annotation objects.

The module deliberately operates on raw annotation dictionaries.  It keeps
the distinction between a missing field and a field containing its runtime
default, so an explicit SET operation can create a missing JSON field without
normalizing unrelated shapes or roots.
"""

from __future__ import annotations

import copy
import math
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
from anylabeling.views.labeling.widgets.object_relabel import (
    SHAPE_ID_FIELD,
    STATUS_CANCELLED,
    STATUS_CHANGEABLE,
    STATUS_CONFLICT,
    STATUS_DELETED,
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    STATUS_UNCHANGED,
    MarkedObjectRef,
    ObjectIdentityConflict,
    ObjectKey,
    _final_status,
    _has_invalid_shape_id,
    _is_within,
    _shape_id_counts,
    read_annotation_data,
)

FIELD_CREATED = "created"
FIELD_UPDATED = "updated"
FIELD_UNCHANGED = "unchanged"
FIELD_CONFLICT = "conflict"

FIELD_REGISTRY = {
    "label": {"kind": "label", "value_type": "string"},
    "difficult": {"kind": "difficult", "value_type": "boolean"},
    "group_id": {"kind": "group_id", "value_type": "integer_or_null"},
    "description": {"kind": "description", "value_type": "string"},
    "score": {"kind": "score", "value_type": "number_or_null"},
    "flags.<key>": {"kind": "flags", "value_type": "boolean"},
    "attributes.<key>": {
        "kind": "attributes",
        "value_type": "json_scalar",
    },
}

MISSING = object()
JsonScalar = str | int | float | bool | None
PathResolver = Callable[[str], Optional[str]]


class ObjectFieldEditPlanError(ValueError):
    """Raised when a marked-object field edit plan is invalid."""


class ObjectFieldConflict(ValueError):
    """Raised when a target field cannot be edited safely."""


@dataclass(frozen=True)
class FieldAssignment:
    """One immutable field path and its JSON scalar target value."""

    path: tuple[str, ...] | str
    value: JsonScalar
    field_kind: str = field(init=False)

    def __post_init__(self) -> None:
        """Normalize and validate the assignment path and value."""
        normalized = normalize_field_path(self.path)
        kind = validate_field_value(normalized, self.value)
        object.__setattr__(self, "path", normalized)
        object.__setattr__(self, "field_kind", kind)

    @property
    def path_text(self) -> str:
        """Return the dotted UI and manifest representation."""
        return ".".join(self.path)


@dataclass(frozen=True)
class ObjectFieldEditPlan:
    """Immutable field edit plan grouped by annotation file."""

    project_id: str
    assignments: tuple[FieldAssignment, ...]
    targets_by_annotation_path: Mapping[str, tuple[MarkedObjectRef, ...]]

    def __post_init__(self) -> None:
        """Freeze mappings and validate plan-level invariants."""
        if not isinstance(self.project_id, str) or not self.project_id.strip():
            raise ObjectFieldEditPlanError("project id must be non-empty")
        assignments = tuple(self.assignments)
        if not assignments:
            raise ObjectFieldEditPlanError("at least one field is required")
        paths = [assignment.path for assignment in assignments]
        if len(paths) != len(set(paths)):
            raise ObjectFieldEditPlanError(
                "duplicate field paths are not allowed"
            )
        grouped = {
            osp.abspath(osp.normpath(path)): tuple(refs)
            for path, refs in self.targets_by_annotation_path.items()
        }
        if not grouped or not any(grouped.values()):
            raise ObjectFieldEditPlanError("marked object snapshot is empty")
        object.__setattr__(self, "assignments", assignments)
        object.__setattr__(
            self, "targets_by_annotation_path", MappingProxyType(grouped)
        )

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


@dataclass(frozen=True)
class FieldMutation:
    """One target field's preflight or staging mutation."""

    path: tuple[str, ...]
    status: str
    old_value: JsonScalar = None
    old_value_missing: bool = False
    new_value: JsonScalar = None

    @property
    def path_text(self) -> str:
        """Return the dotted field path."""
        return ".".join(self.path)


@dataclass(frozen=True)
class ObjectFieldDetail:
    """Per-object field statuses and legacy-format warnings."""

    shape_id: str
    status: str
    mutations: tuple[FieldMutation, ...] = ()
    warnings: tuple[str, ...] = ()
    message: str = ""


@dataclass(frozen=True)
class FileFieldPreflight:
    """Preflight result for one annotation JSON file."""

    annotation_path: str
    file_status: str
    object_statuses: Mapping[str, str]
    object_details: Mapping[str, ObjectFieldDetail] = field(
        default_factory=dict
    )
    warnings: tuple[str, ...] = ()
    message: str = ""


@dataclass(frozen=True)
class ObjectFieldPreflightSummary:
    """Aggregated field and object counters shown before confirmation."""

    assignments: tuple[FieldAssignment, ...]
    snapshot_objects: int
    candidate_files: int
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    conflict: int = 0
    deleted: int = 0
    failed: int = 0
    cancelled: bool = False
    warnings: tuple[str, ...] = ()
    file_details: tuple[FileFieldPreflight, ...] = ()

    @property
    def field_counts(self) -> dict[str, int]:
        """Return field-level counters for UI and tests."""
        return {
            FIELD_CREATED: self.created,
            FIELD_UPDATED: self.updated,
            FIELD_UNCHANGED: self.unchanged,
            FIELD_CONFLICT: self.conflict,
        }


@dataclass(frozen=True)
class ObjectFieldTransformation:
    """Pure per-file transformation output."""

    data: Mapping[str, Any]
    changed: bool
    statuses: Mapping[str, str]
    mutations: Mapping[str, tuple[FieldMutation, ...]] = field(
        default_factory=dict
    )
    warnings: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class ObjectFieldResult:
    """Final result for one marked object."""

    key: ObjectKey
    status: str
    mutations: tuple[FieldMutation, ...] = ()
    warnings: tuple[str, ...] = ()
    message: str = ""


@dataclass(frozen=True)
class ObjectFieldEditResult:
    """Structured result for one object field edit batch."""

    transaction_id: str
    phase: str
    cancelled: bool
    manifest_path: Optional[str] = None
    objects: tuple[ObjectFieldResult, ...] = ()
    files: tuple[FileOperationResult, ...] = ()

    @property
    def counts(self) -> dict[str, int]:
        """Return stable object-level status counters."""
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
    def field_counts(self) -> dict[str, int]:
        """Return field mutation counts from the actual object results."""
        counts = Counter(
            mutation.status
            for item in self.objects
            for mutation in item.mutations
        )
        return {
            FIELD_CREATED: counts.get(FIELD_CREATED, 0),
            FIELD_UPDATED: counts.get(FIELD_UPDATED, 0),
            FIELD_UNCHANGED: counts.get(FIELD_UNCHANGED, 0),
            FIELD_CONFLICT: counts.get(FIELD_CONFLICT, 0),
        }

    @property
    def file_counts(self) -> dict[str, int]:
        """Return file-level status counters."""
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
class ObjectFieldStagedBatch:
    """Frozen staging state bridging transactions and object results."""

    plan: ObjectFieldEditPlan
    operation: OperationResult
    file_object_statuses: Mapping[str, Mapping[str, str]]
    file_mutations: Mapping[str, Mapping[str, tuple[FieldMutation, ...]]]
    file_warnings: Mapping[str, Mapping[str, tuple[str, ...]]]


def normalize_field_path(path: str | Sequence[str]) -> tuple[str, ...]:
    """Normalize a supported top-level or one-level nested field path."""
    if isinstance(path, str):
        parts = tuple(path.split("."))
    else:
        parts = tuple(path)
    if not parts or any(
        not isinstance(part, str) or not part for part in parts
    ):
        raise ObjectFieldEditPlanError(
            "field path must contain non-empty strings"
        )
    if len(parts) > 2:
        raise ObjectFieldEditPlanError(
            "nested field paths may contain one dot"
        )
    if len(parts) == 2 and parts[0] not in {"flags", "attributes"}:
        raise ObjectFieldEditPlanError(
            "only flags.<key> and attributes.<key> are supported"
        )
    if len(parts) == 1 and parts[0] in {
        SHAPE_ID_FIELD,
        "points",
        "shape_type",
        "direction",
        "kie_linking",
        "flags",
        "attributes",
    }:
        raise ObjectFieldEditPlanError(
            f"field is protected or requires a child path: {parts[0]}"
        )
    supported = {"label", "difficult", "group_id", "description", "score"}
    if len(parts) == 1 and parts[0] not in supported:
        raise ObjectFieldEditPlanError(f"unsupported field: {parts[0]}")
    return parts


def _is_finite_number(value: object) -> bool:
    """Return whether a non-bool number is finite."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and (not isinstance(value, float) or math.isfinite(value))
    )


def validate_field_value(path: tuple[str, ...], value: JsonScalar) -> str:
    """Validate a field value and return its registered field kind."""
    root = path[0]
    if root == "label":
        if not isinstance(value, str) or not value.strip():
            raise ObjectFieldEditPlanError("label must be a non-empty string")
        return "label"
    if root == "difficult":
        if not isinstance(value, bool):
            raise ObjectFieldEditPlanError("difficult must be boolean")
        return "difficult"
    if root == "group_id":
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            raise ObjectFieldEditPlanError(
                "group_id must be an integer or null"
            )
        return "group_id"
    if root == "description":
        if not isinstance(value, str):
            raise ObjectFieldEditPlanError("description must be a string")
        return "description"
    if root == "score":
        if value is not None and not _is_finite_number(value):
            raise ObjectFieldEditPlanError(
                "score must be a finite number or null"
            )
        return "score"
    if root == "flags":
        if not isinstance(value, bool):
            raise ObjectFieldEditPlanError("flags values must be boolean")
        return "flags"
    if root == "attributes":
        if value is not None and isinstance(value, (dict, list)):
            raise ObjectFieldEditPlanError(
                "attributes values must be JSON scalars"
            )
        if isinstance(value, float) and not math.isfinite(value):
            raise ObjectFieldEditPlanError(
                "attributes values must contain finite numbers"
            )
        return "attributes"
    raise ObjectFieldEditPlanError(f"unsupported field: {root}")


def build_object_field_edit_plan(
    refs: Iterable[MarkedObjectRef],
    project_id: str,
    assignments: Iterable[FieldAssignment],
    annotation_root: str,
    path_resolver: PathResolver,
) -> ObjectFieldEditPlan:
    """Build an immutable field edit plan from a frozen mark snapshot."""
    if not isinstance(project_id, str) or not project_id.strip():
        raise ObjectFieldEditPlanError("project id must be non-empty")
    if not isinstance(annotation_root, str) or not annotation_root.strip():
        raise ObjectFieldEditPlanError("annotation root must be non-empty")
    normalized_assignments = tuple(assignments)
    if not all(
        isinstance(item, FieldAssignment) for item in normalized_assignments
    ):
        raise ObjectFieldEditPlanError(
            "assignments must be FieldAssignment values"
        )
    ref_list = list(refs)
    if not ref_list:
        raise ObjectFieldEditPlanError("marked object snapshot is empty")
    problems: list[str] = []
    grouped: dict[str, dict[ObjectKey, MarkedObjectRef]] = {}
    for ref in ref_list:
        if ref.project_id != project_id:
            problems.append(
                f"{ref.display_summary or ref.shape_id}: belongs to another project"
            )
            continue
        resolved = path_resolver(ref.image_id)
        if not resolved:
            problems.append(
                f"{ref.display_summary or ref.shape_id}: annotation path cannot be resolved"
            )
            continue
        path = osp.abspath(osp.normpath(resolved))
        if not _is_within(path, annotation_root):
            problems.append(
                f"{ref.display_summary or ref.shape_id}: annotation path escapes project root"
            )
            continue
        grouped.setdefault(path, {})[ref.object_key] = ref
    if problems:
        raise ObjectFieldEditPlanError("; ".join(problems))
    return ObjectFieldEditPlan(
        project_id=project_id,
        assignments=normalized_assignments,
        targets_by_annotation_path=MappingProxyType(
            {path: tuple(items.values()) for path, items in grouped.items()}
        ),
    )


def _json_values_equal(left: object, right: object) -> bool:
    """Compare JSON values without treating bool as an integer."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return (
            not isinstance(left, bool)
            and not isinstance(right, bool)
            and left == right
        )
    return type(left) is type(right) and left == right


def _field_value(
    shape: dict[str, Any], path: tuple[str, ...]
) -> tuple[object, bool]:
    """Read a field and return ``(value, missing)``."""
    if len(path) == 1:
        if path[0] not in shape:
            return MISSING, True
        return shape[path[0]], False
    parent = shape.get(path[0], MISSING)
    if parent is MISSING:
        return MISSING, True
    if not isinstance(parent, dict):
        raise ObjectFieldConflict(
            f"{path[0]} must be an object to edit {'.'.join(path)}"
        )
    if path[1] not in parent:
        return MISSING, True
    return parent[path[1]], False


def _set_field_value(
    shape: dict[str, Any], assignment: FieldAssignment
) -> FieldMutation:
    """Set one field and return its mutation status."""
    old_value, missing = _field_value(shape, assignment.path)
    if missing:
        status = FIELD_CREATED
    elif _json_values_equal(old_value, assignment.value):
        status = FIELD_UNCHANGED
    else:
        status = FIELD_UPDATED
    if status != FIELD_UNCHANGED:
        value = copy.deepcopy(assignment.value)
        if len(assignment.path) == 1:
            shape[assignment.path[0]] = value
        else:
            parent = shape.get(assignment.path[0], MISSING)
            if parent is MISSING:
                parent = {}
                shape[assignment.path[0]] = parent
            if not isinstance(parent, dict):
                raise ObjectFieldConflict(
                    f"{assignment.path[0]} must be an object"
                )
            parent[assignment.path[1]] = value
    return FieldMutation(
        path=assignment.path,
        status=status,
        old_value=None if missing else old_value,
        old_value_missing=missing,
        new_value=assignment.value,
    )


def _shape_lookup(
    data: Mapping[str, Any], target_ids: frozenset[str]
) -> dict[str, dict[str, Any]]:
    """Validate Shape identities and return unique target dictionaries."""
    if not isinstance(data, dict):
        raise ValueError("annotation root must be an object")
    shapes = data.get("shapes", [])
    if not isinstance(shapes, list):
        raise ValueError("annotation JSON shapes must be a list")
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
    return {
        shape[SHAPE_ID_FIELD]: shape
        for shape in shapes
        if isinstance(shape, dict) and shape.get(SHAPE_ID_FIELD) in target_ids
    }


def _legacy_warnings(shape: Mapping[str, Any]) -> tuple[str, ...]:
    """Return warnings for a legacy difficult alias on one Shape."""
    flags = shape.get("flags")
    if not isinstance(flags, dict) or "difficult" not in flags:
        return ()
    warnings = ["legacy flags.difficult is present"]
    if "difficult" in shape and shape.get("difficult") != flags.get(
        "difficult"
    ):
        warnings.append("top-level difficult conflicts with flags.difficult")
    return tuple(warnings)


def transform_objects_by_fields(
    data: Mapping[str, Any],
    shape_ids: Iterable[str],
    assignments: Iterable[FieldAssignment],
) -> ObjectFieldTransformation:
    """Apply field assignments to uniquely matched target Shapes only."""
    normalized = tuple(assignments)
    if not normalized:
        raise ObjectFieldEditPlanError("at least one field is required")
    target_ids = frozenset(shape_ids)
    result = copy.deepcopy(dict(data))
    lookup = _shape_lookup(result, target_ids)
    statuses: dict[str, str] = {}
    mutations: dict[str, tuple[FieldMutation, ...]] = {}
    warnings: dict[str, tuple[str, ...]] = {}
    for shape_id in sorted(target_ids):
        shape = lookup.get(shape_id)
        if shape is None:
            statuses[shape_id] = STATUS_DELETED
            mutations[shape_id] = ()
            warnings[shape_id] = ()
            continue
        # Inspect the source representation before applying the requested
        # top-level value so a pre-existing difficult alias mismatch is not
        # hidden by the edit itself.
        source_warnings = _legacy_warnings(shape)
        object_mutations = tuple(
            _set_field_value(shape, assignment) for assignment in normalized
        )
        mutations[shape_id] = object_mutations
        warnings[shape_id] = tuple(
            dict.fromkeys(source_warnings + _legacy_warnings(shape))
        )
        statuses[shape_id] = (
            STATUS_UNCHANGED
            if all(item.status == FIELD_UNCHANGED for item in object_mutations)
            else STATUS_CHANGEABLE
        )
    return ObjectFieldTransformation(
        data=result,
        changed=any(
            status == STATUS_CHANGEABLE for status in statuses.values()
        ),
        statuses=MappingProxyType(statuses),
        mutations=MappingProxyType(mutations),
        warnings=MappingProxyType(warnings),
    )


def _ids_for_path(plan: ObjectFieldEditPlan, path: str) -> frozenset[str]:
    """Return target Shape IDs grouped under one annotation path."""
    return frozenset(
        ref.shape_id for ref in plan.targets_by_annotation_path.get(path, ())
    )


def _object_details(
    outcome: ObjectFieldTransformation,
) -> dict[str, ObjectFieldDetail]:
    """Convert a transformation into immutable preflight details."""
    return {
        shape_id: ObjectFieldDetail(
            shape_id=shape_id,
            status=status,
            mutations=outcome.mutations.get(shape_id, ()),
            warnings=outcome.warnings.get(shape_id, ()),
        )
        for shape_id, status in outcome.statuses.items()
    }


class ObjectFieldEditEngine:
    """Preflight, stage and commit facade for field assignments."""

    def __init__(self, transaction_root: str) -> None:
        """Initialize the engine with a project-owned transaction root."""
        self._engine = JsonTransactionEngine(transaction_root)

    def preflight(
        self,
        plan: ObjectFieldEditPlan,
        cancel_check: Optional[CancelCheck] = None,
        progress: Optional[ProgressCallback] = None,
    ) -> ObjectFieldPreflightSummary:
        """Read every target file and aggregate field/object outcomes."""
        counters: Counter[str] = Counter()
        field_counters: Counter[str] = Counter()
        details: list[FileFieldPreflight] = []
        warnings: list[str] = []
        cancelled = False
        paths = tuple(plan.targets_by_annotation_path)
        for index, path in enumerate(paths, 1):
            if cancel_check and cancel_check():
                cancelled = True
                break
            ids = _ids_for_path(plan, path)
            try:
                outcome = transform_objects_by_fields(
                    read_annotation_data(path), ids, plan.assignments
                )
                object_details = _object_details(outcome)
                file_status = (
                    STATUS_CHANGEABLE if outcome.changed else "skipped"
                )
                message = ""
                file_warnings = tuple(
                    sorted(
                        {
                            warning
                            for values in outcome.warnings.values()
                            for warning in values
                        }
                    )
                )
                for detail in object_details.values():
                    counters[detail.status] += 1
                    for mutation in detail.mutations:
                        field_counters[mutation.status] += 1
                warnings.extend(file_warnings)
            except ObjectIdentityConflict as exc:
                file_status = STATUS_CONFLICT
                object_details = {
                    shape_id: ObjectFieldDetail(
                        shape_id=shape_id,
                        status=STATUS_CONFLICT,
                        message=str(exc),
                    )
                    for shape_id in ids
                }
                counters.update([STATUS_CONFLICT] * len(ids))
                message = str(exc)
                file_warnings = ()
            except ObjectFieldConflict as exc:
                file_status = STATUS_CONFLICT
                object_details = {
                    shape_id: ObjectFieldDetail(
                        shape_id=shape_id,
                        status=STATUS_CONFLICT,
                        message=str(exc),
                    )
                    for shape_id in ids
                }
                counters.update([STATUS_CONFLICT] * len(ids))
                message = str(exc)
                file_warnings = ()
            except (OSError, ValueError, TypeError) as exc:
                file_status = STATUS_FAILED
                object_details = {
                    shape_id: ObjectFieldDetail(
                        shape_id=shape_id,
                        status=STATUS_FAILED,
                        message=str(exc),
                    )
                    for shape_id in ids
                }
                counters.update([STATUS_FAILED] * len(ids))
                message = str(exc)
                file_warnings = ()
            details.append(
                FileFieldPreflight(
                    annotation_path=path,
                    file_status=file_status,
                    object_statuses=MappingProxyType(
                        {
                            key: detail.status
                            for key, detail in object_details.items()
                        }
                    ),
                    object_details=MappingProxyType(object_details),
                    warnings=file_warnings,
                    message=message,
                )
            )
            if progress:
                progress("preflight", index, len(paths), path)
        return ObjectFieldPreflightSummary(
            assignments=plan.assignments,
            snapshot_objects=plan.total_objects,
            candidate_files=len(details),
            created=field_counters.get(FIELD_CREATED, 0),
            updated=field_counters.get(FIELD_UPDATED, 0),
            unchanged=field_counters.get(FIELD_UNCHANGED, 0),
            conflict=counters.get(STATUS_CONFLICT, 0)
            + field_counters.get(FIELD_CONFLICT, 0),
            deleted=counters.get(STATUS_DELETED, 0),
            failed=counters.get(STATUS_FAILED, 0),
            cancelled=cancelled,
            warnings=tuple(sorted(set(warnings))),
            file_details=tuple(details),
        )

    def stage(
        self,
        plan: ObjectFieldEditPlan,
        cancel_check: Optional[CancelCheck] = None,
        progress: Optional[ProgressCallback] = None,
    ) -> ObjectFieldStagedBatch:
        """Stage target files with field and object metadata."""
        records: dict[str, dict[str, str]] = {}
        mutations: dict[str, dict[str, tuple[FieldMutation, ...]]] = {}
        warnings: dict[str, dict[str, tuple[str, ...]]] = {}

        def transform(
            source: str, original: Mapping[str, Any]
        ) -> StagedTransform:
            ids = _ids_for_path(plan, source)
            try:
                outcome = transform_objects_by_fields(
                    original, ids, plan.assignments
                )
            except (ObjectIdentityConflict, ObjectFieldConflict) as exc:
                records[source] = {
                    shape_id: STATUS_CONFLICT for shape_id in ids
                }
                mutations[source] = {shape_id: () for shape_id in ids}
                warnings[source] = {shape_id: () for shape_id in ids}
                return StagedTransform(
                    data=original,
                    changed=False,
                    skip_reason=str(exc),
                    metadata={"object_statuses": records[source]},
                )
            records[source] = dict(outcome.statuses)
            mutations[source] = {
                shape_id: tuple(values)
                for shape_id, values in outcome.mutations.items()
            }
            warnings[source] = dict(outcome.warnings)
            changed_objects = sum(
                status == STATUS_CHANGEABLE
                for status in records[source].values()
            )
            metadata = {
                "object_statuses": dict(records[source]),
                "field_statuses": {
                    shape_id: [
                        {"path": item.path_text, "status": item.status}
                        for item in values
                    ]
                    for shape_id, values in mutations[source].items()
                },
                "warnings": warnings[source],
            }
            return StagedTransform(
                data=outcome.data,
                changed=outcome.changed,
                matched_shapes=changed_objects,
                metadata=metadata,
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
            ids = _ids_for_path(plan, path)
            records[path] = {shape_id: fallback for shape_id in ids}
            mutations[path] = {shape_id: () for shape_id in ids}
            warnings[path] = {shape_id: () for shape_id in ids}
        return ObjectFieldStagedBatch(
            plan=plan,
            operation=operation,
            file_object_statuses=MappingProxyType(
                {
                    path: MappingProxyType(dict(values))
                    for path, values in records.items()
                }
            ),
            file_mutations=MappingProxyType(
                {
                    path: MappingProxyType(dict(values))
                    for path, values in mutations.items()
                }
            ),
            file_warnings=MappingProxyType(
                {
                    path: MappingProxyType(dict(values))
                    for path, values in warnings.items()
                }
            ),
        )

    def commit(
        self, staged: ObjectFieldStagedBatch, root: str
    ) -> ObjectFieldEditResult:
        """Atomically commit staged files and derive object results."""
        committed = self._engine.commit(staged.operation, root)
        file_status_by_path = {
            osp.abspath(item.source_path): item.status
            for item in committed.files
        }
        objects: list[ObjectFieldResult] = []
        for path, per_file in staged.file_object_statuses.items():
            file_status = file_status_by_path.get(
                osp.abspath(path), STATUS_FAILED
            )
            refs = staged.plan.targets_by_annotation_path.get(path, ())
            for ref in refs:
                stage_status = per_file.get(ref.shape_id, STATUS_FAILED)
                objects.append(
                    ObjectFieldResult(
                        key=ref.object_key,
                        status=_final_status(stage_status, file_status),
                        mutations=staged.file_mutations.get(path, {}).get(
                            ref.shape_id, ()
                        ),
                        warnings=staged.file_warnings.get(path, {}).get(
                            ref.shape_id, ()
                        ),
                    )
                )
        return ObjectFieldEditResult(
            transaction_id=committed.transaction_id,
            phase=committed.phase,
            cancelled=False,
            manifest_path=committed.manifest_path,
            objects=tuple(objects),
            files=committed.files,
        )

    def cancelled_result(
        self,
        staged: Optional[ObjectFieldStagedBatch] = None,
        plan: Optional[ObjectFieldEditPlan] = None,
    ) -> ObjectFieldEditResult:
        """Build an all-cancelled result for an aborted batch."""
        active_plan = staged.plan if staged is not None else plan
        if active_plan is None:
            raise ValueError("plan or staged batch is required")
        objects = tuple(
            ObjectFieldResult(key=ref.object_key, status=STATUS_CANCELLED)
            for refs in active_plan.targets_by_annotation_path.values()
            for ref in refs
        )
        return ObjectFieldEditResult(
            transaction_id=(staged.operation.transaction_id if staged else ""),
            phase="cancelled",
            cancelled=True,
            manifest_path=(
                staged.operation.manifest_path if staged is not None else None
            ),
            objects=objects,
            files=staged.operation.files if staged is not None else (),
        )

    def restore(
        self, manifest_path: str, root: Optional[str] = None
    ) -> OperationResult:
        """Restore a committed field-edit transaction from its manifest."""
        return self._engine.restore(manifest_path, root)

    @staticmethod
    def _plan_metadata(plan: ObjectFieldEditPlan) -> dict[str, Any]:
        """Return serializable field plan metadata for a manifest."""
        return {
            "kind": "object-field-edit",
            "project_id": plan.project_id,
            "assignments": [
                {"path": item.path_text, "value": item.value}
                for item in plan.assignments
            ],
            "paths": {
                path: sorted({ref.shape_id for ref in refs})
                for path, refs in plan.targets_by_annotation_path.items()
            },
        }
