"""Pure state contracts for the dense annotation review workflow.

The model deliberately has no Qt dependency.  It records what the user
confirmed, which content signatures those confirmations belong to, and the
spatial coverage plan.  A confirmation is only valid while its stored
signature equals the current content signature.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence

REVIEW_FIELD = "xanylabeling_dense_review"
REVIEW_VERSION = 1
NEW_PENDING_BATCH_ID = "__new_pending__"
OTHER_BATCH_ID = "__other__"
OTHER_BATCH_NAME = "其他待处理"
NEW_PENDING_BATCH_NAME = "新增待处理"
SUPPORTED_SHAPE_TYPES = ("rectangle",)
REVIEW_DIMENSIONS = ("category", "geometry")
DIMENSION_LABELS = {
    "category": "类别",
    "geometry": "框",
}
BOX_RULE_VALUES = ("visible", "full", "unknown")
BOX_RULE_LABELS = {
    "visible": "可见框",
    "full": "完整框",
    "unknown": "未知",
}
DEFAULT_BOX_RULE = "unknown"
DEFAULT_COVERAGE_COLUMNS = 4
DEFAULT_COVERAGE_ROWS = 3
DEFAULT_COVERAGE_OVERLAP = 0.15


class IncompatibleReviewState(ValueError):
    """Raised when persisted progress cannot be interpreted safely."""

    def __init__(self, reason: str, payload: Optional[Mapping] = None):
        super().__init__(reason)
        self.reason = reason
        self.payload = dict(payload) if payload is not None else None


def canonical_json(value: Any) -> str:
    """Return a stable JSON representation for signature hashing."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def signature_for(value: Any) -> str:
    """Return a stable SHA-256 signature for one JSON-compatible value."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def normalize_bounds(
    bounds: Iterable[float],
) -> Optional[tuple[float, float, float, float]]:
    """Normalize four bounds and return ``None`` for unusable geometry."""
    values = tuple(float(value) for value in bounds)
    if len(values) != 4:
        return None
    x0, y0, x1, y1 = values
    if not all(value == value for value in values):
        return None
    xmin, xmax = sorted((x0, x1))
    ymin, ymax = sorted((y0, y1))
    if xmax - xmin < 1e-9 and ymax - ymin < 1e-9:
        return None
    return (xmin, ymin, xmax, ymax)


def bounds_intersect(left: Sequence[float], right: Sequence[float]) -> bool:
    """Return whether two inclusive image-space bounds overlap."""
    return not (
        left[2] < right[0]
        or right[2] < left[0]
        or left[3] < right[1]
        or right[3] < left[1]
    )


def bounds_union(
    left: Sequence[float], right: Sequence[float]
) -> tuple[float, float, float, float]:
    """Return the smallest bounds containing both rectangles."""
    return (
        min(left[0], right[0]),
        min(left[1], right[1]),
        max(left[2], right[2]),
        max(left[3], right[3]),
    )


@dataclass(frozen=True)
class ConfigIssue:
    """Describe one blocking review-configuration problem."""

    code: str
    message: str
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class LabelRule:
    """Optional per-class review guidance."""

    label: str
    box_rule: str = DEFAULT_BOX_RULE
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "box_rule": self.box_rule,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LabelRule":
        box_rule = str(data.get("box_rule", DEFAULT_BOX_RULE))
        if box_rule not in BOX_RULE_VALUES:
            box_rule = DEFAULT_BOX_RULE
        return cls(
            label=str(data.get("label", "")),
            box_rule=box_rule,
            note=str(data.get("note", "")),
        )


@dataclass(frozen=True)
class ReviewRules:
    """Versioned class and box rules used by both signatures and the UI."""

    rules: Mapping[str, LabelRule] = field(default_factory=dict)
    default_box_rule: str = DEFAULT_BOX_RULE

    def normalized(self) -> "ReviewRules":
        rules = {
            label: rule
            for label, rule in self.rules.items()
            if label and rule.label == label
        }
        default = (
            self.default_box_rule
            if self.default_box_rule in BOX_RULE_VALUES
            else DEFAULT_BOX_RULE
        )
        return ReviewRules(rules=dict(rules), default_box_rule=default)

    def box_rule(self, label: str) -> str:
        rule = self.rules.get(label)
        if rule is not None:
            return rule.box_rule
        return self.default_box_rule

    def note(self, label: str) -> str:
        rule = self.rules.get(label)
        return rule.note if rule is not None else ""

    def category_signature(self) -> str:
        normalized = self.normalized()
        return signature_for(
            {
                "rules": {
                    label: rule.to_dict()
                    for label, rule in sorted(normalized.rules.items())
                },
                "default_box_rule": normalized.default_box_rule,
            }
        )

    def geometry_signature(self) -> str:
        normalized = self.normalized()
        return signature_for(
            {
                "box_rules": {
                    label: rule.box_rule
                    for label, rule in sorted(normalized.rules.items())
                },
                "default_box_rule": normalized.default_box_rule,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        return {
            "rules": {
                label: rule.to_dict()
                for label, rule in sorted(normalized.rules.items())
            },
            "default_box_rule": normalized.default_box_rule,
        }

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "ReviewRules":
        if not isinstance(data, Mapping):
            return cls()
        raw_rules = data.get("rules", {})
        rules: dict[str, LabelRule] = {}
        if isinstance(raw_rules, Mapping):
            for key, value in raw_rules.items():
                if not isinstance(value, Mapping):
                    continue
                rule = LabelRule.from_dict({"label": key, **value})
                rules[str(key)] = rule
        return cls(
            rules=rules,
            default_box_rule=str(
                data.get("default_box_rule", DEFAULT_BOX_RULE)
            ),
        ).normalized()


@dataclass(frozen=True)
class BatchDefinition:
    """One user-configured confusion batch."""

    name: str
    labels: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "labels": list(self.labels)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BatchDefinition":
        labels = data.get("labels", ())
        if not isinstance(labels, (list, tuple)):
            labels = ()
        return cls(
            name=str(data.get("name", "")),
            labels=tuple(str(label) for label in labels if str(label)),
        )

    def display_name(self) -> str:
        if self.name:
            return self.name
        return " / ".join(self.labels) or "未命名批次"


@dataclass(frozen=True)
class CoverageSettings:
    """Grid granularity for spatial omission review."""

    columns: int = DEFAULT_COVERAGE_COLUMNS
    rows: int = DEFAULT_COVERAGE_ROWS
    overlap: float = DEFAULT_COVERAGE_OVERLAP

    def normalized(self) -> "CoverageSettings":
        return CoverageSettings(
            columns=max(1, min(24, int(self.columns))),
            rows=max(1, min(24, int(self.rows))),
            overlap=max(0.0, min(0.75, float(self.overlap))),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        return {
            "columns": normalized.columns,
            "rows": normalized.rows,
            "overlap": normalized.overlap,
        }

    @classmethod
    def from_dict(
        cls, data: Optional[Mapping[str, Any]]
    ) -> "CoverageSettings":
        if not isinstance(data, Mapping):
            return cls()
        try:
            return cls(
                columns=int(data.get("columns", DEFAULT_COVERAGE_COLUMNS)),
                rows=int(data.get("rows", DEFAULT_COVERAGE_ROWS)),
                overlap=float(data.get("overlap", DEFAULT_COVERAGE_OVERLAP)),
            ).normalized()
        except (TypeError, ValueError):
            return cls()


@dataclass(frozen=True)
class ReviewConfig:
    """Local review configuration, versioned by its canonical content."""

    batches: tuple[BatchDefinition, ...] = ()
    rules: ReviewRules = field(default_factory=ReviewRules)
    coverage: CoverageSettings = field(default_factory=CoverageSettings)

    def normalized(self) -> "ReviewConfig":
        batches = tuple(
            BatchDefinition(
                name=batch.name,
                labels=tuple(
                    dict.fromkeys(label for label in batch.labels if label)
                ),
            )
            for batch in self.batches
        )
        return ReviewConfig(
            batches=batches,
            rules=self.rules.normalized(),
            coverage=self.coverage.normalized(),
        )

    def validate(self, translate=str) -> tuple[ConfigIssue, ...]:
        """Return blocking configuration problems in a stable order."""
        normalized = self.normalized()
        issues: list[ConfigIssue] = []
        owners: dict[str, list[str]] = {}
        for index, batch in enumerate(normalized.batches):
            name = batch.display_name()
            if not batch.labels:
                issues.append(
                    ConfigIssue(
                        "empty_batch",
                        translate("批次“{name}”没有配置类别").format(
                            name=name
                        ),
                    )
                )
            for label in batch.labels:
                owners.setdefault(label, []).append(name)
        conflicts = sorted(
            (label, names) for label, names in owners.items() if len(names) > 1
        )
        for label, names in conflicts:
            issues.append(
                ConfigIssue(
                    "duplicate_label",
                    translate("类别“{label}”同时出现在批次：{names}").format(
                        label=label, names=", ".join(names)
                    ),
                    (label,),
                )
            )
        return tuple(issues)

    def label_to_batch(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for index, batch in enumerate(self.normalized().batches):
            batch_id = f"batch-{index}"
            for label in batch.labels:
                mapping[label] = batch_id
        return mapping

    def batch_id_for_label(self, label: str) -> str:
        return self.label_to_batch().get(label, OTHER_BATCH_ID)

    def signature(self) -> str:
        return signature_for(self.to_dict())

    def rules_signature(self) -> str:
        return self.rules.category_signature()

    def batch_signature(self) -> str:
        normalized = self.normalized()
        return signature_for([batch.to_dict() for batch in normalized.batches])

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        return {
            "batches": [batch.to_dict() for batch in normalized.batches],
            "rules": normalized.rules.to_dict(),
            "coverage": normalized.coverage.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "ReviewConfig":
        if not isinstance(data, Mapping):
            return cls()
        raw_batches = data.get("batches", ())
        batches: list[BatchDefinition] = []
        if isinstance(raw_batches, (list, tuple)):
            for item in raw_batches:
                if isinstance(item, Mapping):
                    batches.append(BatchDefinition.from_dict(item))
        return cls(
            batches=tuple(batches),
            rules=ReviewRules.from_dict(data.get("rules")),
            coverage=CoverageSettings.from_dict(data.get("coverage")),
        ).normalized()


@dataclass
class ObjectReviewState:
    """Progress and current content signatures for one persistent object."""

    shape_id: str
    display_index: int
    label: str
    shape_type: str
    bounds: tuple[float, float, float, float]
    category_signature: str
    geometry_signature: str
    category_confirmed: Optional[str] = None
    geometry_confirmed: Optional[str] = None
    difficult: bool = False
    difficulty_dimensions: tuple[str, ...] = ()
    difficulty_reason: str = ""
    skipped: bool = False
    added: bool = False
    supported: bool = True
    load_failed: bool = False

    def confirmed(self, dimension: str) -> bool:
        if dimension == "category":
            return self.category_confirmed == self.category_signature
        if dimension == "geometry":
            return self.geometry_confirmed == self.geometry_signature
        return False

    def confirmed_both(self) -> bool:
        return self.confirmed("category") and self.confirmed("geometry")

    def both_pending(self) -> bool:
        return not self.confirmed("category") and not self.confirmed(
            "geometry"
        )

    def apply_confirmation(self, dimensions: Iterable[str]) -> bool:
        """Store current signatures for the requested dimensions."""
        if self.difficult or self.skipped or self.load_failed:
            return False
        changed = False
        for dimension in dimensions:
            if dimension == "category":
                if self.category_confirmed != self.category_signature:
                    self.category_confirmed = self.category_signature
                    changed = True
            elif dimension == "geometry":
                if self.geometry_confirmed != self.geometry_signature:
                    self.geometry_confirmed = self.geometry_signature
                    changed = True
        return changed

    def clear_confirmation(self, dimensions: Iterable[str]) -> None:
        for dimension in dimensions:
            if dimension == "category":
                self.category_confirmed = None
            elif dimension == "geometry":
                self.geometry_confirmed = None

    def status_text(self) -> str:
        if self.load_failed:
            return "加载失败"
        if not self.supported:
            return "不支持"
        if self.difficult:
            return "疑难"
        if self.skipped:
            return "暂跳"
        category = self.confirmed("category")
        geometry = self.confirmed("geometry")
        if category and geometry:
            return "已确认"
        if category:
            return "框待审"
        if geometry:
            return "类别待审"
        if self.added:
            return "新增待审"
        return "待审"

    def to_dict(self) -> dict[str, Any]:
        return {
            "shape_id": self.shape_id,
            "display_index": self.display_index,
            "label": self.label,
            "shape_type": self.shape_type,
            "bounds": list(self.bounds),
            "category_signature": self.category_signature,
            "geometry_signature": self.geometry_signature,
            "category_confirmed": self.category_confirmed,
            "geometry_confirmed": self.geometry_confirmed,
            "difficult": self.difficult,
            "difficulty_dimensions": list(self.difficulty_dimensions),
            "difficulty_reason": self.difficulty_reason,
            "skipped": self.skipped,
            "added": self.added,
            "supported": self.supported,
            "load_failed": self.load_failed,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ObjectReviewState":
        try:
            load_failed = bool(data.get("load_failed", False))
            bounds = normalize_bounds(data["bounds"])
            if bounds is None:
                if not load_failed:
                    raise ValueError("invalid bounds")
                bounds = (0.0, 0.0, 0.0, 0.0)
            dimensions = tuple(
                str(item)
                for item in data.get("difficulty_dimensions", ())
                if str(item) in REVIEW_DIMENSIONS
            )
            return cls(
                shape_id=str(data["shape_id"]),
                display_index=int(data.get("display_index", 0)),
                label=str(data.get("label", "")),
                shape_type=str(data.get("shape_type", "rectangle")),
                bounds=bounds,
                category_signature=str(data["category_signature"]),
                geometry_signature=str(data["geometry_signature"]),
                category_confirmed=_optional_text(
                    data.get("category_confirmed")
                ),
                geometry_confirmed=_optional_text(
                    data.get("geometry_confirmed")
                ),
                difficult=bool(data.get("difficult", False)),
                difficulty_dimensions=dimensions,
                difficulty_reason=str(data.get("difficulty_reason", "")),
                skipped=bool(data.get("skipped", False)),
                added=bool(data.get("added", False)),
                supported=bool(data.get("supported", True)),
                load_failed=load_failed,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise IncompatibleReviewState(
                f"对象进度字段无效：{error}"
            ) from error


@dataclass
class BatchState:
    """A stable batch snapshot for the current review round."""

    batch_id: str
    name: str
    labels: tuple[str, ...]
    member_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "name": self.name,
            "labels": list(self.labels),
            "member_ids": list(self.member_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BatchState":
        try:
            member_ids = data.get("member_ids", ())
            if not isinstance(member_ids, (list, tuple)):
                raise ValueError("member_ids must be a list")
            return cls(
                batch_id=str(data["batch_id"]),
                name=str(data.get("name", "")),
                labels=tuple(str(item) for item in data.get("labels", ())),
                member_ids=[str(item) for item in member_ids],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise IncompatibleReviewState(
                f"批次进度字段无效：{error}"
            ) from error


@dataclass
class CoverageRegion:
    """One explicit spatial omission-review region."""

    region_id: str
    row: int
    column: int
    rect: tuple[float, float, float, float]
    completed: bool = False
    difficult: bool = False
    skipped: bool = False
    baseline: dict[str, tuple[float, float, float, float]] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "row": self.row,
            "column": self.column,
            "rect": list(self.rect),
            "completed": self.completed,
            "difficult": self.difficult,
            "skipped": self.skipped,
            "baseline": {
                shape_id: list(bounds)
                for shape_id, bounds in self.baseline.items()
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CoverageRegion":
        try:
            rect = normalize_bounds(data["rect"])
            if rect is None:
                raise ValueError("invalid region rect")
            raw_baseline = data.get("baseline", {})
            baseline: dict[str, tuple[float, float, float, float]] = {}
            if not isinstance(raw_baseline, Mapping):
                raise ValueError("baseline must be a mapping")
            for shape_id, bounds in raw_baseline.items():
                normalized = normalize_bounds(bounds)
                if normalized is not None:
                    baseline[str(shape_id)] = normalized
            return cls(
                region_id=str(data["region_id"]),
                row=int(data.get("row", 0)),
                column=int(data.get("column", 0)),
                rect=rect,
                completed=bool(data.get("completed", False)),
                difficult=bool(data.get("difficult", False)),
                skipped=bool(data.get("skipped", False)),
                baseline=baseline,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise IncompatibleReviewState(
                f"查漏区域字段无效：{error}"
            ) from error


@dataclass
class CoveragePlan:
    """Stable image-space region plan for one image."""

    plan_id: str
    columns: int
    rows: int
    overlap: float
    image_width: int
    image_height: int
    regions: list[CoverageRegion] = field(default_factory=list)
    current_region: str = ""

    def region(self, region_id: str) -> Optional[CoverageRegion]:
        for region in self.regions:
            if region.region_id == region_id:
                return region
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "columns": self.columns,
            "rows": self.rows,
            "overlap": self.overlap,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "regions": [region.to_dict() for region in self.regions],
            "current_region": self.current_region,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CoveragePlan":
        try:
            raw_regions = data.get("regions", ())
            if not isinstance(raw_regions, (list, tuple)):
                raise ValueError("regions must be a list")
            plan = cls(
                plan_id=str(data["plan_id"]),
                columns=int(data["columns"]),
                rows=int(data["rows"]),
                overlap=float(data["overlap"]),
                image_width=int(data["image_width"]),
                image_height=int(data["image_height"]),
                regions=[
                    CoverageRegion.from_dict(item)
                    for item in raw_regions
                    if isinstance(item, Mapping)
                ],
                current_region=str(data.get("current_region", "")),
            )
            if len(plan.regions) != plan.columns * plan.rows:
                raise ValueError("region count does not match grid")
            return plan
        except (KeyError, TypeError, ValueError) as error:
            raise IncompatibleReviewState(
                f"查漏计划字段无效：{error}"
            ) from error


def _parse_objects(raw: Any) -> dict[str, ObjectReviewState]:
    if not isinstance(raw, Mapping):
        raise ValueError("objects must be a mapping")
    objects = {}
    for shape_id, value in raw.items():
        if not isinstance(value, Mapping):
            raise ValueError("object entry must be a mapping")
        objects[str(shape_id)] = ObjectReviewState.from_dict(value)
    return objects


def _parse_batches(raw: Any) -> list[BatchState]:
    if not isinstance(raw, (list, tuple)):
        raise ValueError("batches must be a list")
    batches = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("batch entry must be a mapping")
        batches.append(BatchState.from_dict(item))
    return batches


def _parse_new_pending(raw: Any) -> list[str]:
    if not isinstance(raw, (list, tuple)):
        raise ValueError("new_pending must be a list")
    return [str(item) for item in raw]


def _validate_queue_membership(
    objects: Mapping[str, ObjectReviewState],
    batches: Iterable[BatchState],
    new_pending: Iterable[str],
) -> None:
    for shape_id, item in objects.items():
        if item.shape_id != shape_id:
            raise ValueError(f"object key {shape_id!r} does not match id")
    claimed: set[str] = set()
    for batch in batches:
        for shape_id in batch.member_ids:
            if shape_id in claimed:
                raise ValueError(f"duplicate queue membership: {shape_id}")
            claimed.add(shape_id)
    for shape_id in new_pending:
        if shape_id in claimed:
            raise ValueError(f"duplicate queue membership: {shape_id}")
        claimed.add(shape_id)


def _parse_dimensions(raw: Any) -> tuple[str, ...]:
    dimensions = tuple(
        str(item) for item in raw if str(item) in REVIEW_DIMENSIONS
    )
    return dimensions or REVIEW_DIMENSIONS


def _parse_coverage(raw: Any) -> Optional[CoveragePlan]:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("coverage must be a mapping or null")
    return CoveragePlan.from_dict(raw)


@dataclass
class ReviewState:
    """Persisted progress for one image and output directory."""

    version: int = REVIEW_VERSION
    image_fingerprint: str = ""
    image_width: int = 0
    image_height: int = 0
    rules_signature: str = ""
    batch_signature: str = ""
    objects: dict[str, ObjectReviewState] = field(default_factory=dict)
    batches: list[BatchState] = field(default_factory=list)
    new_pending: list[str] = field(default_factory=list)
    dimensions: tuple[str, ...] = REVIEW_DIMENSIONS
    coverage: Optional[CoveragePlan] = None
    current_batch: str = ""
    current_object: str = ""

    def batch(self, batch_id: str) -> Optional[BatchState]:
        for batch in self.batches:
            if batch.batch_id == batch_id:
                return batch
        return None

    def member_ids(self, batch_id: str) -> list[str]:
        if batch_id == NEW_PENDING_BATCH_ID:
            return list(self.new_pending)
        batch = self.batch(batch_id)
        return list(batch.member_ids) if batch is not None else []

    def batch_for_object(self, shape_id: str) -> Optional[str]:
        if shape_id in self.new_pending:
            return NEW_PENDING_BATCH_ID
        for batch in self.batches:
            if shape_id in batch.member_ids:
                return batch.batch_id
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "image_fingerprint": self.image_fingerprint,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "rules_signature": self.rules_signature,
            "batch_signature": self.batch_signature,
            "objects": {
                shape_id: item.to_dict()
                for shape_id, item in sorted(self.objects.items())
            },
            "batches": [batch.to_dict() for batch in self.batches],
            "new_pending": list(self.new_pending),
            "dimensions": list(self.dimensions),
            "coverage": (
                self.coverage.to_dict() if self.coverage is not None else None
            ),
            "current_batch": self.current_batch,
            "current_object": self.current_object,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewState":
        if not isinstance(data, Mapping):
            raise IncompatibleReviewState("进度必须是 JSON 对象")
        version = data.get("version")
        if version != REVIEW_VERSION:
            raise IncompatibleReviewState(
                f"未知的密集复核进度版本：{version!r}", data
            )
        try:
            objects = _parse_objects(data.get("objects", {}))
            batches = _parse_batches(data.get("batches", ()))
            new_pending_ids = _parse_new_pending(data.get("new_pending", ()))
            _validate_queue_membership(objects, batches, new_pending_ids)
            dimensions = _parse_dimensions(
                data.get("dimensions", REVIEW_DIMENSIONS)
            )
            coverage = _parse_coverage(data.get("coverage"))
            return cls(
                version=REVIEW_VERSION,
                image_fingerprint=str(data.get("image_fingerprint", "")),
                image_width=int(data.get("image_width", 0)),
                image_height=int(data.get("image_height", 0)),
                rules_signature=str(data.get("rules_signature", "")),
                batch_signature=str(data.get("batch_signature", "")),
                objects=objects,
                batches=batches,
                new_pending=new_pending_ids,
                dimensions=dimensions,
                coverage=coverage,
                current_batch=str(data.get("current_batch", "")),
                current_object=str(data.get("current_object", "")),
            )
        except IncompatibleReviewState:
            raise
        except (TypeError, ValueError) as error:
            raise IncompatibleReviewState(
                f"密集复核进度无法解析：{error}", data
            ) from error


@dataclass(frozen=True)
class CandidateScope:
    """Materialized confirmation scope for one batch and dimension set."""

    batch_id: str
    dimensions: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    excluded: Mapping[str, str]
    fingerprint: str
    total: int

    @property
    def excluded_count(self) -> int:
        return len(self.excluded)

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "dimensions": list(self.dimensions),
            "candidate_ids": list(self.candidate_ids),
            "excluded": dict(self.excluded),
            "fingerprint": self.fingerprint,
            "total": self.total,
        }


@dataclass(frozen=True)
class BatchConfirmation:
    """Result of one atomic batch confirmation attempt."""

    status: str
    confirmed_ids: tuple[str, ...] = ()
    excluded: Mapping[str, str] = field(default_factory=dict)
    next_batch_id: str = ""
    next_object_id: str = ""
    conflict: bool = False


@dataclass(frozen=True)
class CompletionStatus:
    """Derived completion state; never read a standalone ``complete`` flag."""

    complete: bool
    object_complete: bool
    coverage_complete: bool
    supported: bool
    reasons: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        if self.complete:
            return "本流程整图完成"
        if not self.supported:
            return "不支持完整复核"
        return "未完成"

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "label": self.label,
            "object_complete": self.object_complete,
            "coverage_complete": self.coverage_complete,
            "supported": self.supported,
            "reasons": list(self.reasons),
        }


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    return text or None
