"""Versioned data contracts shared by the inspection service and Inspector UI."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping, Optional, Sequence

PROFILE_SCHEMA_VERSION = "inspection-profile.v1"
REPORT_SCHEMA_VERSION = "inspection-report.v1"
FEEDBACK_SCHEMA_VERSION = "inspection-feedback.v1"
SESSION_SCHEMA_VERSION = "inspection-session.v1"
CANDIDATE_SCHEMA_VERSION = "inspection-candidate.v1"

ALLOWED_STAGES = ("pre_label", "in_progress", "post_label")
RELATION_VALUES = (
    "mutually_exclusive",
    "allowed_coexist",
    "allowed_containment",
    "unknown",
)


class RunScope(str, Enum):
    """The four user-selectable inspection scopes."""

    CURRENT_IMAGE = "current_image"
    SELECTED_FILES = "selected_files"
    DATASET = "dataset"
    CHANGED_FILES = "changed_files"


class RunState(str, Enum):
    """Terminal and in-flight state of one inspection run."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    FAILED = "failed"


class CoverageState(str, Enum):
    """Per-file/per-rule execution outcome."""

    COMPLETED = "completed"
    NOT_APPLICABLE = "not_applicable"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    NOT_RUN = "not_run"


class Decision(str, Enum):
    """Human review decision, independent from machine verification."""

    PENDING = "pending"
    CONFIRMED_ERROR = "confirmed_error"
    FALSE_POSITIVE = "false_positive"
    ACCEPTABLE = "acceptable"
    NEEDS_DISCUSSION = "needs_discussion"


class ActionState(str, Enum):
    """Human edit action, not proof that the rule now passes."""

    UNCHANGED = "unchanged"
    MODIFIED = "modified"
    DELETED = "deleted"
    RELABELED = "relabeled"
    ADDED = "added"


class VerificationState(str, Enum):
    """Machine verification status for one issue family."""

    CURRENT = "current"
    STALE = "stale"
    PENDING_RECHECK = "pending_recheck"
    NOT_DETECTED = "not_detected_on_successful_recheck"
    UNVERIFIABLE = "unverifiable"


class IssueSeverity(str, Enum):
    """Severity is a review priority, never a validation verdict."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class CandidateStatus(str, Enum):
    """Lifecycle of an external model candidate."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEFERRED = "deferred"


def utc_now_iso() -> str:
    """Return a timezone-aware ISO timestamp with second precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run_id(profile_id: str) -> str:
    """Create a sortable, collision-resistant run identifier."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:8]
    return f"{stamp}-{profile_id}-{suffix}"


def normalize_path(path: str) -> str:
    """Return a comparable absolute path identity (case-insensitive)."""
    if not str(path or "").strip():
        return ""
    return os.path.normcase(os.path.abspath(str(path)))


def dataset_identity(dataset_root: str) -> str:
    """Return the stable storage identity of a dataset root."""
    normalized = normalize_path(dataset_root)
    if not normalized:
        return "unbound"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def output_identity(output_root: str) -> str:
    """Return the annotation output identity.

    Empty means "annotations live beside the images", which is distinct
    from any explicit output directory and must survive a round trip
    through an explicit-but-equal path.
    """
    return normalize_path(output_root)


def config_rule_versions(
    profile_snapshot: Mapping[str, Any],
) -> dict[str, str]:
    """Extract enabled rule id -> implementation version from a snapshot."""
    versions: dict[str, str] = {}
    for rule in profile_snapshot.get("rules", []) or []:
        if not isinstance(rule, Mapping) or not rule.get("enabled", True):
            continue
        rule_id = str(rule.get("rule_id", ""))
        if rule_id:
            versions[rule_id] = str(rule.get("implementation_version", ""))
    return versions


def canonical_relation_key(first: str, second: str) -> str:
    """Return an unordered, serialization-safe relation key."""
    left, right = sorted((str(first), str(second)))
    return f"{left}|{right}"


def stable_issue_id(
    family_key: str,
    rule_id: str,
    file_identity: str,
    object_ids: Sequence[str],
    region: Optional[Sequence[float]] = None,
) -> str:
    """Build a stable issue id from identity, rule and location."""
    payload = {
        "family": family_key,
        "rule": rule_id,
        "file": file_identity,
        "objects": sorted(str(item) for item in object_ids),
        "region": [round(float(item), 3) for item in region or ()],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _tuple_float(values: Iterable[Any]) -> tuple[float, ...]:
    return tuple(float(value) for value in values)


@dataclass(frozen=True)
class RuleConfig:
    """One rule selection with its immutable parameter payload."""

    rule_id: str
    enabled: bool = True
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "enabled": bool(self.enabled),
            "parameters": dict(self.parameters),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RuleConfig":
        if not isinstance(data, Mapping):
            raise ValueError("rule configuration must be a mapping")
        rule_id = str(data.get("rule_id", "")).strip()
        if not rule_id:
            raise ValueError("rule configuration requires rule_id")
        parameters = data.get("parameters", {}) or {}
        if not isinstance(parameters, Mapping):
            raise ValueError(f"parameters for {rule_id} must be a mapping")
        return cls(
            rule_id=rule_id,
            enabled=bool(data.get("enabled", True)),
            parameters=dict(parameters),
        )


@dataclass(frozen=True)
class RuleMeta:
    """Registered rule metadata shown in the profile editor."""

    rule_id: str
    implementation_version: str
    name: str
    description: str
    stage: str
    scope: str
    parameters: tuple[str, ...] = ()
    examples: Mapping[str, str] = field(default_factory=dict)
    enabled_by_default: bool = True
    depends_on: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "implementation_version": self.implementation_version,
            "name": self.name,
            "description": self.description,
            "stage": self.stage,
            "scope": self.scope,
            "parameters": list(self.parameters),
            "examples": dict(self.examples),
            "enabled_by_default": bool(self.enabled_by_default),
            "depends_on": list(self.depends_on),
        }


@dataclass(frozen=True)
class InspectionProfile:
    """A scenario profile with rule selections and project bindings."""

    profile_id: str
    name: str
    description: str
    stage: str
    rules: tuple[RuleConfig, ...]
    version: int = 1
    schema_version: str = PROFILE_SCHEMA_VERSION
    label_bindings: Mapping[str, str] = field(default_factory=dict)
    relations: Mapping[str, str] = field(default_factory=dict)
    exceptions: Mapping[str, Any] = field(default_factory=dict)
    builtin: bool = False
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    @property
    def enabled_rules(self) -> tuple[RuleConfig, ...]:
        return tuple(rule for rule in self.rules if rule.enabled)

    def rule_config(self, rule_id: str) -> Optional[RuleConfig]:
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        return None

    def fingerprint(self) -> str:
        payload = self.to_dict()
        payload.pop("created_at", None)
        payload.pop("updated_at", None)
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "profile_version": int(self.version),
            "name": self.name,
            "description": self.description,
            "stage": self.stage,
            "rules": [rule.to_dict() for rule in self.rules],
            "label_bindings": dict(self.label_bindings),
            "relations": dict(self.relations),
            "exceptions": dict(self.exceptions),
            "builtin": bool(self.builtin),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InspectionProfile":
        if not isinstance(data, Mapping):
            raise ValueError("profile must be a mapping")
        rules_raw = data.get("rules", []) or []
        if not isinstance(rules_raw, Sequence) or isinstance(
            rules_raw, (str, bytes)
        ):
            raise ValueError("profile rules must be a list")
        relations = data.get("relations", {}) or {}
        if not isinstance(relations, Mapping):
            raise ValueError("profile relations must be a mapping")
        bindings = data.get("label_bindings", {}) or {}
        if not isinstance(bindings, Mapping):
            raise ValueError("profile label_bindings must be a mapping")
        exceptions = data.get("exceptions", {}) or {}
        if not isinstance(exceptions, Mapping):
            raise ValueError("profile exceptions must be a mapping")
        profile = cls(
            profile_id=str(data.get("profile_id", "")).strip(),
            name=str(data.get("name", "")).strip(),
            description=str(data.get("description", "")).strip(),
            stage=str(data.get("stage", "post_label")).strip(),
            rules=tuple(RuleConfig.from_dict(item) for item in rules_raw),
            version=int(data.get("profile_version", 1) or 1),
            schema_version=str(
                data.get("schema_version", PROFILE_SCHEMA_VERSION)
            ),
            label_bindings={str(k): str(v) for k, v in bindings.items()},
            relations={str(k): str(v) for k, v in relations.items()},
            exceptions=dict(exceptions),
            builtin=bool(data.get("builtin", False)),
            created_at=str(data.get("created_at", utc_now_iso())),
            updated_at=str(data.get("updated_at", utc_now_iso())),
        )
        if not profile.profile_id:
            raise ValueError("profile requires profile_id")
        if not profile.name:
            raise ValueError("profile requires name")
        if profile.stage not in ALLOWED_STAGES:
            raise ValueError(f"unknown profile stage: {profile.stage}")
        return profile


@dataclass(frozen=True)
class ShapeSnapshot:
    """Immutable, read-only view of one annotation object."""

    shape_id: str
    index: int
    label: str
    shape_type: str
    points: tuple[tuple[float, float], ...]
    group_id: Optional[int] = None
    flags: Mapping[str, Any] = field(default_factory=dict)
    attributes: Mapping[str, Any] = field(default_factory=dict)
    difficult: bool = False
    identity_valid: bool = True
    identity_reason: str = ""
    input_errors: tuple[str, ...] = ()

    @property
    def bbox(self) -> Optional[tuple[float, float, float, float]]:
        if self.points:
            xs = [point[0] for point in self.points]
            ys = [point[1] for point in self.points]
            return (min(xs), min(ys), max(xs), max(ys))
        return None

    @property
    def input_valid(self) -> bool:
        """Return whether the raw input was parsed without any diagnostics."""
        return not self.input_errors

    @property
    def area(self) -> float:
        bbox = self.bbox
        if bbox is None:
            return 0.0
        return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])

    def to_dict(self) -> dict[str, Any]:
        return {
            "shape_id": self.shape_id,
            "index": int(self.index),
            "label": self.label,
            "shape_type": self.shape_type,
            "points": [list(point) for point in self.points],
            "group_id": self.group_id,
            "flags": dict(self.flags),
            "attributes": dict(self.attributes),
            "difficult": bool(self.difficult),
            "identity_valid": bool(self.identity_valid),
            "identity_reason": self.identity_reason,
            "input_errors": list(self.input_errors),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ShapeSnapshot":
        points_raw = data.get("points", []) or []
        points = []
        for point in points_raw:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            points.append((float(point[0]), float(point[1])))
        return cls(
            shape_id=str(data.get("shape_id", "")),
            index=int(data.get("index", 0) or 0),
            label=str(data.get("label", "")),
            shape_type=str(data.get("shape_type", "")),
            points=tuple(points),
            group_id=(
                int(data["group_id"])
                if isinstance(data.get("group_id"), int)
                and not isinstance(data.get("group_id"), bool)
                else None
            ),
            flags=dict(data.get("flags", {}) or {}),
            attributes=dict(data.get("attributes", {}) or {}),
            difficult=bool(data.get("difficult", False)),
            identity_valid=bool(data.get("identity_valid", True)),
            identity_reason=str(data.get("identity_reason", "")),
            input_errors=tuple(
                str(item) for item in data.get("input_errors", []) or []
            ),
        )


@dataclass(frozen=True)
class FileSnapshot:
    """Immutable annotation and image identity for one file."""

    relative_path: str
    image_path: str
    annotation_path: str
    image_width: int = 0
    image_height: int = 0
    annotation_digest: str = ""
    shape_digest: str = ""
    image_digest: str = ""
    image_digest_kind: str = ""
    annotation_normalized_digest: str = ""
    image_orientation: str = ""
    shapes: tuple[ShapeSnapshot, ...] = ()
    annotation_state: str = "present"
    error: str = ""
    unsaved: bool = False
    read_at: str = field(default_factory=utc_now_iso)

    @property
    def identity_key(self) -> str:
        return f"{self.relative_path}|{self.annotation_digest}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "image_path": self.image_path,
            "annotation_path": self.annotation_path,
            "image_width": int(self.image_width),
            "image_height": int(self.image_height),
            "annotation_digest": self.annotation_digest,
            "shape_digest": self.shape_digest,
            "image_digest": self.image_digest,
            "image_digest_kind": self.image_digest_kind,
            "annotation_normalized_digest": self.annotation_normalized_digest,
            "image_orientation": self.image_orientation,
            "shapes": [shape.to_dict() for shape in self.shapes],
            "annotation_state": self.annotation_state,
            "error": self.error,
            "unsaved": bool(self.unsaved),
            "read_at": self.read_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FileSnapshot":
        return cls(
            relative_path=str(data.get("relative_path", "")),
            image_path=str(data.get("image_path", "")),
            annotation_path=str(data.get("annotation_path", "")),
            image_width=int(data.get("image_width", 0) or 0),
            image_height=int(data.get("image_height", 0) or 0),
            annotation_digest=str(data.get("annotation_digest", "")),
            shape_digest=str(data.get("shape_digest", "")),
            image_digest=str(data.get("image_digest", "")),
            image_digest_kind=str(data.get("image_digest_kind", "")),
            annotation_normalized_digest=str(
                data.get("annotation_normalized_digest", "")
            ),
            image_orientation=str(data.get("image_orientation", "")),
            shapes=tuple(
                ShapeSnapshot.from_dict(item)
                for item in data.get("shapes", []) or []
            ),
            annotation_state=str(data.get("annotation_state", "present")),
            error=str(data.get("error", "")),
            unsaved=bool(data.get("unsaved", False)),
            read_at=str(data.get("read_at", utc_now_iso())),
        )


@dataclass(frozen=True)
class Manifest:
    """Complete file manifest used by one inspection run."""

    dataset_root: str
    output_root: str
    files: tuple[FileSnapshot, ...]
    errors: tuple[Mapping[str, Any], ...] = ()
    excluded: tuple[Mapping[str, Any], ...] = ()
    generated_at: str = field(default_factory=utc_now_iso)
    complete: bool = True

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def shape_count(self) -> int:
        return sum(len(file.shapes) for file in self.files)

    def fingerprint(self) -> str:
        payload = {
            "dataset_root": self.dataset_root,
            "output_root": self.output_root,
            "files": [
                [file.relative_path, file.annotation_digest]
                for file in self.files
            ],
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_root": self.dataset_root,
            "output_root": self.output_root,
            "files": [file.to_dict() for file in self.files],
            "errors": [dict(error) for error in self.errors],
            "excluded": [dict(item) for item in self.excluded],
            "generated_at": self.generated_at,
            "complete": bool(self.complete),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Manifest":
        return cls(
            dataset_root=str(data.get("dataset_root", "")),
            output_root=str(data.get("output_root", "")),
            files=tuple(
                FileSnapshot.from_dict(item)
                for item in data.get("files", []) or []
            ),
            errors=tuple(dict(item) for item in data.get("errors", []) or []),
            excluded=tuple(
                dict(item) for item in data.get("excluded", []) or []
            ),
            generated_at=str(data.get("generated_at", utc_now_iso())),
            complete=bool(data.get("complete", True)),
        )


@dataclass(frozen=True)
class IssueLocation:
    """Location is explicit about image, objects and independent regions."""

    relative_path: str
    image_path: str = ""
    object_ids: tuple[str, ...] = ()
    shape_indices: tuple[int, ...] = ()
    group_id: Optional[int] = None
    region: Optional[tuple[float, float, float, float]] = None
    snapshot_digest: str = ""
    ambiguous: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "image_path": self.image_path,
            "object_ids": list(self.object_ids),
            "shape_indices": list(self.shape_indices),
            "group_id": self.group_id,
            "region": list(self.region) if self.region else None,
            "snapshot_digest": self.snapshot_digest,
            "ambiguous": bool(self.ambiguous),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IssueLocation":
        region_raw = data.get("region")
        region = (
            tuple(float(value) for value in region_raw[:4])
            if isinstance(region_raw, (list, tuple)) and len(region_raw) >= 4
            else None
        )
        return cls(
            relative_path=str(data.get("relative_path", "")),
            image_path=str(data.get("image_path", "")),
            object_ids=tuple(
                str(item) for item in data.get("object_ids", []) or []
            ),
            shape_indices=tuple(
                int(item) for item in data.get("shape_indices", []) or []
            ),
            group_id=(
                int(data["group_id"])
                if isinstance(data.get("group_id"), int)
                and not isinstance(data.get("group_id"), bool)
                else None
            ),
            region=region,
            snapshot_digest=str(data.get("snapshot_digest", "")),
            ambiguous=bool(data.get("ambiguous", False)),
        )


@dataclass(frozen=True)
class IssueEvidence:
    """One rule's evidence for an issue, preserving its own version."""

    rule_id: str
    implementation_version: str
    rule_name: str
    message: str
    severity: IssueSeverity = IssueSeverity.WARNING
    metrics: Mapping[str, float] = field(default_factory=dict)
    thresholds: Mapping[str, Any] = field(default_factory=dict)
    snapshot_digest: str = ""
    relation: str = ""
    filtered_reason: str = ""
    source: str = "local"
    verification: VerificationState = VerificationState.CURRENT
    verification_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "implementation_version": self.implementation_version,
            "rule_name": self.rule_name,
            "message": self.message,
            "severity": self.severity.value,
            "metrics": {
                str(key): round(float(value), 6)
                for key, value in self.metrics.items()
                if isinstance(value, (int, float))
                and not isinstance(value, bool)
            },
            "thresholds": dict(self.thresholds),
            "snapshot_digest": self.snapshot_digest,
            "relation": self.relation,
            "filtered_reason": self.filtered_reason,
            "source": self.source,
            "verification": self.verification.value,
            "verification_reason": self.verification_reason,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IssueEvidence":
        severity_raw = str(data.get("severity", "warning"))
        try:
            severity = IssueSeverity(severity_raw)
        except ValueError:
            severity = IssueSeverity.WARNING
        verification_raw = str(data.get("verification", "current"))
        try:
            verification = VerificationState(verification_raw)
        except ValueError:
            verification = VerificationState.CURRENT
        return cls(
            rule_id=str(data.get("rule_id", "")),
            implementation_version=str(data.get("implementation_version", "")),
            rule_name=str(data.get("rule_name", "")),
            message=str(data.get("message", "")),
            severity=severity,
            metrics=dict(data.get("metrics", {}) or {}),
            thresholds=dict(data.get("thresholds", {}) or {}),
            snapshot_digest=str(data.get("snapshot_digest", "")),
            relation=str(data.get("relation", "")),
            filtered_reason=str(data.get("filtered_reason", "")),
            source=str(data.get("source", "local")),
            verification=verification,
            verification_reason=str(data.get("verification_reason", "")),
        )


@dataclass(frozen=True)
class InspectionIssue:
    """Current issue family with independent human and machine state."""

    issue_id: str
    family_key: str
    title: str
    message: str
    severity: IssueSeverity
    location: IssueLocation
    evidence: tuple[IssueEvidence, ...]
    suggested_action: str = ""
    decision: Decision = Decision.PENDING
    action: ActionState = ActionState.UNCHANGED
    verification: VerificationState = VerificationState.CURRENT
    history: tuple[Mapping[str, Any], ...] = ()
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    @property
    def rule_ids(self) -> tuple[str, ...]:
        return tuple(sorted({item.rule_id for item in self.evidence}))

    @property
    def open(self) -> bool:
        return self.verification in (
            VerificationState.CURRENT,
            VerificationState.PENDING_RECHECK,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "family_key": self.family_key,
            "title": self.title,
            "message": self.message,
            "severity": self.severity.value,
            "location": self.location.to_dict(),
            "evidence": [item.to_dict() for item in self.evidence],
            "suggested_action": self.suggested_action,
            "decision": self.decision.value,
            "action": self.action.value,
            "verification": self.verification.value,
            "history": [dict(item) for item in self.history],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InspectionIssue":
        severity_raw = str(data.get("severity", "warning"))
        decision_raw = str(data.get("decision", "pending"))
        action_raw = str(data.get("action", "unchanged"))
        verification_raw = str(data.get("verification", "current"))
        try:
            severity = IssueSeverity(severity_raw)
        except ValueError:
            severity = IssueSeverity.WARNING
        try:
            decision = Decision(decision_raw)
        except ValueError:
            decision = Decision.PENDING
        try:
            action = ActionState(action_raw)
        except ValueError:
            action = ActionState.UNCHANGED
        try:
            verification = VerificationState(verification_raw)
        except ValueError:
            verification = VerificationState.UNVERIFIABLE
        return cls(
            issue_id=str(data.get("issue_id", "")),
            family_key=str(data.get("family_key", "")),
            title=str(data.get("title", "")),
            message=str(data.get("message", "")),
            severity=severity,
            location=IssueLocation.from_dict(data.get("location", {}) or {}),
            evidence=tuple(
                IssueEvidence.from_dict(item)
                for item in data.get("evidence", []) or []
            ),
            suggested_action=str(data.get("suggested_action", "")),
            decision=decision,
            action=action,
            verification=verification,
            history=tuple(
                dict(item) for item in data.get("history", []) or []
            ),
            created_at=str(data.get("created_at", utc_now_iso())),
            updated_at=str(data.get("updated_at", utc_now_iso())),
        )


@dataclass(frozen=True)
class CoverageEntry:
    """Explicit per-file/per-rule coverage instead of implicit success."""

    relative_path: str
    rule_id: str
    state: CoverageState
    reason: str = ""
    issue_count: int = 0
    duration_ms: float = 0.0
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "rule_id": self.rule_id,
            "state": self.state.value,
            "reason": self.reason,
            "issue_count": int(self.issue_count),
            "duration_ms": round(float(self.duration_ms), 3),
            "truncated": bool(self.truncated),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CoverageEntry":
        try:
            state = CoverageState(str(data.get("state", "not_run")))
        except ValueError:
            state = CoverageState.NOT_RUN
        return cls(
            relative_path=str(data.get("relative_path", "")),
            rule_id=str(data.get("rule_id", "")),
            state=state,
            reason=str(data.get("reason", "")),
            issue_count=int(data.get("issue_count", 0) or 0),
            duration_ms=float(data.get("duration_ms", 0.0) or 0.0),
            truncated=bool(data.get("truncated", False)),
        )


@dataclass(frozen=True)
class RunReport:
    """Immutable run report; human feedback is stored separately."""

    run_id: str
    state: RunState
    scope: RunScope
    dataset_root: str
    output_root: str
    manifest_fingerprint: str
    profile_snapshot: Mapping[str, Any]
    coverage: tuple[CoverageEntry, ...]
    issues: tuple[InspectionIssue, ...]
    started_at: str = field(default_factory=utc_now_iso)
    finished_at: str = ""
    schema_version: str = REPORT_SCHEMA_VERSION
    requested_files: int = 0
    completed_files: int = 0
    failed_files: int = 0
    excluded_files: int = 0
    not_run_files: int = 0
    truncated: bool = False
    error: str = ""
    generation: int = 0
    source_kind: str = "disk"
    scope_notes: tuple[str, ...] = ()

    @property
    def config_digest(self) -> str:
        """Return the frozen effective-configuration digest of this run."""
        return str(self.profile_snapshot.get("snapshot_digest", "") or "")

    def summary(self) -> dict[str, Any]:
        # Object identity must include the file: the same object id may
        # legitimately exist in two different images.
        objects: set[tuple[str, str]] = set()
        issue_files: set[str] = set()
        verification_counts: dict[str, int] = {}
        for issue in self.issues:
            issue_files.add(issue.location.relative_path)
            for object_id in issue.location.object_ids:
                objects.add((issue.location.relative_path, object_id))
            key = issue.verification.value
            verification_counts[key] = verification_counts.get(key, 0) + 1
        return {
            "requested_files": self.requested_files,
            "completed_files": self.completed_files,
            "failed_files": self.failed_files,
            "excluded_files": self.excluded_files,
            "not_run_files": self.not_run_files,
            "issue_count": len(self.issues),
            "object_count": len(objects),
            "image_count": len(issue_files),
            "verification_counts": dict(sorted(verification_counts.items())),
            "truncated": bool(self.truncated),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "state": self.state.value,
            "scope": self.scope.value,
            "dataset_root": self.dataset_root,
            "output_root": self.output_root,
            "manifest_fingerprint": self.manifest_fingerprint,
            "profile": dict(self.profile_snapshot),
            "coverage": [entry.to_dict() for entry in self.coverage],
            "issues": [issue.to_dict() for issue in self.issues],
            "summary": self.summary(),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "requested_files": int(self.requested_files),
            "completed_files": int(self.completed_files),
            "failed_files": int(self.failed_files),
            "excluded_files": int(self.excluded_files),
            "not_run_files": int(self.not_run_files),
            "truncated": bool(self.truncated),
            "error": self.error,
            "generation": int(self.generation),
            "source_kind": self.source_kind,
            "scope_notes": list(self.scope_notes),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunReport":
        try:
            state = RunState(str(data.get("state", "failed")))
        except ValueError:
            state = RunState.FAILED
        try:
            scope = RunScope(str(data.get("scope", "dataset")))
        except ValueError:
            scope = RunScope.DATASET
        return cls(
            run_id=str(data.get("run_id", "")),
            state=state,
            scope=scope,
            dataset_root=str(data.get("dataset_root", "")),
            output_root=str(data.get("output_root", "")),
            manifest_fingerprint=str(data.get("manifest_fingerprint", "")),
            profile_snapshot=dict(data.get("profile", {}) or {}),
            coverage=tuple(
                CoverageEntry.from_dict(item)
                for item in data.get("coverage", []) or []
            ),
            issues=tuple(
                InspectionIssue.from_dict(item)
                for item in data.get("issues", []) or []
            ),
            started_at=str(data.get("started_at", utc_now_iso())),
            finished_at=str(data.get("finished_at", "")),
            schema_version=str(
                data.get("schema_version", REPORT_SCHEMA_VERSION)
            ),
            requested_files=int(data.get("requested_files", 0) or 0),
            completed_files=int(data.get("completed_files", 0) or 0),
            failed_files=int(data.get("failed_files", 0) or 0),
            excluded_files=int(data.get("excluded_files", 0) or 0),
            not_run_files=int(data.get("not_run_files", 0) or 0),
            truncated=bool(data.get("truncated", False)),
            error=str(data.get("error", "")),
            generation=int(data.get("generation", 0) or 0),
            source_kind=str(data.get("source_kind", "disk")),
            scope_notes=tuple(
                str(item) for item in data.get("scope_notes", []) or []
            ),
        )


@dataclass(frozen=True)
class FeedbackRecord:
    """Human decision for one issue family, with revision-safe history."""

    family_key: str
    issue_id: str
    decision: Decision = Decision.PENDING
    action: ActionState = ActionState.UNCHANGED
    verification: VerificationState = VerificationState.CURRENT
    note: str = ""
    evidence_digest: str = ""
    updated_at: str = field(default_factory=utc_now_iso)
    history: tuple[Mapping[str, Any], ...] = ()
    dataset_key: str = ""
    dataset_root: str = ""
    output_root: str = ""
    profile_fingerprint: str = ""
    rule_versions: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "family_key": self.family_key,
            "issue_id": self.issue_id,
            "decision": self.decision.value,
            "action": self.action.value,
            "verification": self.verification.value,
            "note": self.note,
            "evidence_digest": self.evidence_digest,
            "updated_at": self.updated_at,
            "history": [dict(item) for item in self.history],
            "dataset_key": self.dataset_key,
            "dataset_root": self.dataset_root,
            "output_root": self.output_root,
            "profile_fingerprint": self.profile_fingerprint,
            "rule_versions": dict(self.rule_versions),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FeedbackRecord":
        try:
            decision = Decision(str(data.get("decision", "pending")))
        except ValueError:
            decision = Decision.PENDING
        try:
            action = ActionState(str(data.get("action", "unchanged")))
        except ValueError:
            action = ActionState.UNCHANGED
        try:
            verification = VerificationState(
                str(data.get("verification", "current"))
            )
        except ValueError:
            verification = VerificationState.UNVERIFIABLE
        return cls(
            family_key=str(data.get("family_key", "")),
            issue_id=str(data.get("issue_id", "")),
            decision=decision,
            action=action,
            verification=verification,
            note=str(data.get("note", "")),
            evidence_digest=str(data.get("evidence_digest", "")),
            updated_at=str(data.get("updated_at", utc_now_iso())),
            history=tuple(
                dict(item) for item in data.get("history", []) or []
            ),
            dataset_key=str(data.get("dataset_key", "")),
            dataset_root=str(data.get("dataset_root", "")),
            output_root=str(data.get("output_root", "")),
            profile_fingerprint=str(data.get("profile_fingerprint", "")),
            rule_versions={
                str(key): str(value)
                for key, value in (data.get("rule_versions", {}) or {}).items()
            },
        )


@dataclass(frozen=True)
class ReviewSession:
    """Queue filters and cursor, stored independently from run evidence."""

    report_id: str
    dataset_root: str
    output_root: str
    filters: Mapping[str, Any] = field(default_factory=dict)
    cursor: Mapping[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=utc_now_iso)
    revision: int = 0
    schema_version: str = SESSION_SCHEMA_VERSION
    dataset_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "dataset_root": self.dataset_root,
            "output_root": self.output_root,
            "filters": dict(self.filters),
            "cursor": dict(self.cursor),
            "updated_at": self.updated_at,
            "revision": int(self.revision),
            "dataset_key": self.dataset_key,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewSession":
        return cls(
            report_id=str(data.get("report_id", "")),
            dataset_root=str(data.get("dataset_root", "")),
            output_root=str(data.get("output_root", "")),
            filters=dict(data.get("filters", {}) or {}),
            cursor=dict(data.get("cursor", {}) or {}),
            updated_at=str(data.get("updated_at", utc_now_iso())),
            revision=int(data.get("revision", 0) or 0),
            schema_version=str(
                data.get("schema_version", SESSION_SCHEMA_VERSION)
            ),
            dataset_key=str(data.get("dataset_key", "")),
        )


@dataclass(frozen=True)
class Candidate:
    """External model candidate kept separate from formal shapes."""

    candidate_id: str
    source: str
    source_version: str
    relative_path: str
    image_path: str
    label: str
    region: tuple[float, float, float, float]
    image_width: int = 0
    image_height: int = 0
    orientation: str = ""
    score: Optional[float] = None
    status: CandidateStatus = CandidateStatus.PENDING
    reason: str = ""
    accepted_shape_id: str = ""
    accepted_at: str = ""
    schema_version: str = CANDIDATE_SCHEMA_VERSION
    dataset_key: str = ""
    image_digest: str = ""
    image_digest_kind: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "source": self.source,
            "source_version": self.source_version,
            "relative_path": self.relative_path,
            "image_path": self.image_path,
            "label": self.label,
            "region": list(self.region),
            "image_width": int(self.image_width),
            "image_height": int(self.image_height),
            "orientation": self.orientation,
            "score": self.score,
            "status": self.status.value,
            "reason": self.reason,
            "accepted_shape_id": self.accepted_shape_id,
            "accepted_at": self.accepted_at,
            "dataset_key": self.dataset_key,
            "image_digest": self.image_digest,
            "image_digest_kind": self.image_digest_kind,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Candidate":
        region_raw = data.get("region", []) or []
        if not isinstance(region_raw, (list, tuple)) or len(region_raw) < 4:
            raise ValueError("candidate region must contain four numbers")
        try:
            status = CandidateStatus(str(data.get("status", "pending")))
        except ValueError:
            status = CandidateStatus.PENDING
        score = data.get("score")
        return cls(
            candidate_id=str(data.get("candidate_id", "")),
            source=str(data.get("source", "")),
            source_version=str(data.get("source_version", "")),
            relative_path=str(data.get("relative_path", "")),
            image_path=str(data.get("image_path", "")),
            label=str(data.get("label", "")),
            region=_tuple_float(region_raw[:4]),
            image_width=int(data.get("image_width", 0) or 0),
            image_height=int(data.get("image_height", 0) or 0),
            orientation=str(data.get("orientation", "")),
            score=float(score) if isinstance(score, (int, float)) else None,
            status=status,
            reason=str(data.get("reason", "")),
            accepted_shape_id=str(data.get("accepted_shape_id", "")),
            accepted_at=str(data.get("accepted_at", "")),
            schema_version=str(
                data.get("schema_version", CANDIDATE_SCHEMA_VERSION)
            ),
            dataset_key=str(data.get("dataset_key", "")),
            image_digest=str(data.get("image_digest", "")),
            image_digest_kind=str(data.get("image_digest_kind", "")),
        )


@dataclass(frozen=True)
class InspectionStatus:
    """Five independent completion dimensions shown to the user."""

    execution: Mapping[str, Any] = field(default_factory=dict)
    issue_handling: Mapping[str, Any] = field(default_factory=dict)
    object_review: Mapping[str, Any] = field(default_factory=dict)
    spatial_omission: Mapping[str, Any] = field(default_factory=dict)
    formal_acceptance: Mapping[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution": dict(self.execution),
            "issue_handling": dict(self.issue_handling),
            "object_review": dict(self.object_review),
            "spatial_omission": dict(self.spatial_omission),
            "formal_acceptance": dict(self.formal_acceptance),
            "notes": list(self.notes),
        }
