"""
Validation Engine — pluggable rule-based checker for annotation quality.

Each rule is a subclass of ValidationRule.  The engine runs all registered
rules against a FlatIndex and collects Issues.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from anylabeling.views.labeling.person_instance import is_valid_group_id

from .flat_index import FlatIndex, FlattenedRecord

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Issue:
    """A single validation issue found by a rule."""

    rule_name: str  # e.g. "label_unregistered"
    severity: str  # "error" | "warning" | "info"
    message: str  # human-readable description
    file_path: str  # absolute path to the JSON file
    shape_index: int  # -1 for file-level issues
    label: str = ""
    group_id: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationReport:
    """Aggregated result of running all rules."""

    total_files: int = 0
    total_records: int = 0
    issues: List[Issue] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    def issues_by_rule(self) -> Dict[str, List[Issue]]:
        """Group issues by rule_name."""
        grouped: Dict[str, List[Issue]] = {}
        for issue in self.issues:
            grouped.setdefault(issue.rule_name, []).append(issue)
        return grouped


# ---------------------------------------------------------------------------
# Rule base class
# ---------------------------------------------------------------------------


class ValidationRule(ABC):
    """Abstract base for a validation rule."""

    name: str = ""
    severity: str = "error"
    description: str = ""

    @abstractmethod
    def check(
        self,
        record: FlattenedRecord,
        all_records: List[FlattenedRecord],
        index: FlatIndex,
    ) -> Optional[Issue]:
        """
        Check a single record.  Return an Issue if a problem is found,
        or None if the record passes.

        Args:
            record: The record being checked.
            all_records: All records in the same file (for cross-shape checks).
            index: The full FlatIndex (for cross-file checks, use sparingly).
        """
        ...

    def check_all(
        self,
        index: FlatIndex,
    ) -> List[Issue]:
        """
        Default implementation: iterate every record.
        Override for cross-record / cross-file batch checks.
        """
        issues: List[Issue] = []
        for file_path, records in index._by_file.items():
            for rec in records:
                issue = self.check(rec, records, index)
                if issue:
                    issues.append(issue)
        return issues


# ---------------------------------------------------------------------------
# Built-in rules
# ---------------------------------------------------------------------------


class LabelInAllowlist(ValidationRule):
    """Check that every shape label is in a pre-approved allowlist."""

    name = "label_in_allowlist"
    severity = "error"
    description = "标签名不在预定义列表中"

    def __init__(self, allowed_labels: Set[str]):
        self.allowed_labels = allowed_labels

    def check(self, record, all_records, index):
        if not record.label:
            return Issue(
                rule_name=self.name,
                severity=self.severity,
                message=f"[空标签] shape #{record.shape_index} 标签为空",
                file_path=record.file_path,
                shape_index=record.shape_index,
                label=record.label,
                group_id=record.group_id,
            )
        if record.label not in self.allowed_labels:
            return Issue(
                rule_name=self.name,
                severity=self.severity,
                message=f"[未注册标签] shape #{record.shape_index} label='{record.label}'",
                file_path=record.file_path,
                shape_index=record.shape_index,
                label=record.label,
                group_id=record.group_id,
            )
        return None


class GroupIdUniqueness(ValidationRule):
    """
    Check that within a single group_id, there are no duplicate shape types
    that should be unique.

    The UNIQUE_TYPES set is empty by default — users can add custom labels
    in the rule config UI.  Use GroupLabelUniqueness for per-label uniqueness
    within the shared project label set.
    """

    name = "group_id_uniqueness"
    severity = "error"
    description = "同一 group_id 内出现重复的关键形状类型"

    # shape types that should be unique within a group (user-configurable)
    UNIQUE_TYPES: Set[str] = set()

    def check_all(self, index: FlatIndex) -> List[Issue]:
        issues: List[Issue] = []
        for gid, records in index._by_group.items():
            if not is_valid_group_id(gid):
                continue
            type_counts: Dict[str, List[FlattenedRecord]] = {}
            for rec in records:
                if (
                    rec.shape_type == "rectangle"
                    and rec.label in self.UNIQUE_TYPES
                ):
                    type_counts.setdefault(rec.label, []).append(rec)
            for label, group in type_counts.items():
                if len(group) > 1:
                    for rec in group:
                        issues.append(
                            Issue(
                                rule_name=self.name,
                                severity=self.severity,
                                message=(
                                    f"[重复类型] group_id={gid} 内有 {len(group)} 个 "
                                    f"'{label}' 矩形框 (shape #{rec.shape_index})"
                                ),
                                file_path=rec.file_path,
                                shape_index=rec.shape_index,
                                label=rec.label,
                                group_id=gid,
                            )
                        )
        return issues

    def check(self, record, all_records, index):
        # Per-record check is not used; we use check_all for batch efficiency.
        return None


class GroupLabelUniqueness(ValidationRule):
    """
    Check that within a single group_id, each label appears at most once.

    Operates per-file (not cross-file).  Only checks labels in the
    configured label_set.
    """

    name = "group_label_uniqueness"
    severity = "error"
    description = "同一 group_id 内标签名重复出现"

    def __init__(self, label_set: Set[str]):
        self.label_set = label_set

    def check_all(self, index: FlatIndex) -> List[Issue]:
        issues: List[Issue] = []
        for file_path, records in index._by_file.items():
            by_group: Dict[int, Dict[str, List[FlattenedRecord]]] = {}
            for rec in records:
                if not is_valid_group_id(rec.group_id):
                    continue
                if rec.label not in self.label_set:
                    continue
                by_group.setdefault(rec.group_id, {}).setdefault(
                    rec.label, []
                ).append(rec)

            for gid, label_map in by_group.items():
                for label, group in label_map.items():
                    if len(group) > 1:
                        for rec in group:
                            issues.append(
                                Issue(
                                    rule_name=self.name,
                                    severity=self.severity,
                                    message=(
                                        f"[重复标签] group_id={gid} 内 "
                                        f"label='{label}' 出现 {len(group)} 次 "
                                        f"(shape #{rec.shape_index})"
                                    ),
                                    file_path=rec.file_path,
                                    shape_index=rec.shape_index,
                                    label=rec.label,
                                    group_id=gid,
                                )
                            )
        return issues

    def check(self, record, all_records, index):
        return None


class PersonRectRequiresGroupId(ValidationRule):
    """
    Check that every 'person' rectangle has a numeric group_id.

    group_id must be an integer (>=0).  None (missing) or non-integer
    values are treated as errors.
    """

    name = "person_rect_requires_group_id"
    severity = "error"
    description = "person 矩形框缺少 group_id（必须为数字）"

    def check(self, record, all_records, index):
        if record.label != "person" or record.shape_type != "rectangle":
            return None
        gid = record.group_id
        if not is_valid_group_id(gid):
            return Issue(
                rule_name=self.name,
                severity=self.severity,
                message=(
                    f"[缺少group_id] shape #{record.shape_index} "
                    f"的 person 矩形框未设置 group_id"
                ),
                file_path=record.file_path,
                shape_index=record.shape_index,
                label=record.label,
                group_id=gid if is_valid_group_id(gid) else None,
            )
        return None


class GroupIdValid(ValidationRule):
    """Check that group_id is a non-negative integer for supported shapes."""

    name = "group_id_valid"
    severity = "error"
    description = "group_id 必须是非负整数"

    def check(self, record, all_records, index):
        gid = record.group_id
        if gid is None or is_valid_group_id(gid):
            return None
        return Issue(
            rule_name=self.name,
            severity=self.severity,
            message=(
                f"[group_id异常] shape #{record.shape_index} "
                f"group_id={gid!r} 不是非负整数"
            ),
            file_path=record.file_path,
            shape_index=record.shape_index,
            label=record.label,
            group_id=None,
        )


class HeadFaceGroupIdRequired(ValidationRule):
    """Check that head/face shapes have a valid group_id."""

    name = "head_face_group_id_required"
    severity = "error"
    description = "head/face 必须有合法 group_id"

    def check(self, record, all_records, index):
        if record.label not in {"head", "face"}:
            return None
        gid = record.group_id
        if not is_valid_group_id(gid):
            return Issue(
                rule_name=self.name,
                severity=self.severity,
                message=(
                    f"[group_id缺失] shape #{record.shape_index} "
                    f"label='{record.label}' 的 group_id 不合法"
                ),
                file_path=record.file_path,
                shape_index=record.shape_index,
                label=record.label,
                group_id=None,
            )
        return None


class HeadFaceGroupIdUniqueness(ValidationRule):
    """Check that each head/face label occurs once per instance group."""

    name = "head_face_group_id_uniqueness"
    severity = "error"
    description = "同一 group_id 内 head 和 face 各自最多一个"

    def check_all(self, index: FlatIndex) -> List[Issue]:
        issues: List[Issue] = []
        for file_path, records in index._by_file.items():
            by_group_label: Dict[Tuple[int, str], List[FlattenedRecord]] = {}
            for rec in records:
                if rec.label not in {"head", "face"}:
                    continue
                gid = rec.group_id
                if not is_valid_group_id(gid):
                    continue
                by_group_label.setdefault((gid, rec.label), []).append(rec)

            for (gid, label), grouped in by_group_label.items():
                if len(grouped) <= 1:
                    continue
                for rec in grouped:
                    issues.append(
                        Issue(
                            rule_name=self.name,
                            severity=self.severity,
                            message=(
                                f"[标签重复] group_id={gid} 内 label='{label}' "
                                f"出现 {len(grouped)} 次 "
                                f"(shape #{rec.shape_index})"
                            ),
                            file_path=rec.file_path,
                            shape_index=rec.shape_index,
                            label=rec.label,
                            group_id=gid,
                        )
                    )
        return issues

    def check(self, record, all_records, index):
        return None


class LabelShapeTypeBinding(ValidationRule):
    """
    Check that labels are bound to the correct shape types.

    rectangle_labels -> must be 'rectangle'
    point_labels     -> must be 'point'
    Labels not in either set -> reported as 'unbound'.
    """

    name = "label_shape_type_binding"
    severity = "error"
    description = "标签与形状类型不匹配"

    def __init__(
        self,
        rectangle_labels: Set[str],
        point_labels: Set[str],
    ):
        self.rectangle_labels = rectangle_labels
        self.point_labels = point_labels
        self._all_bound_labels = rectangle_labels | point_labels

    def check(self, record, all_records, index):
        label = record.label

        if label not in self._all_bound_labels:
            return Issue(
                rule_name=self.name,
                severity=self.severity,
                message=(
                    f"[标签未绑定] shape #{record.shape_index} "
                    f"label='{label}' 未绑定形状类型"
                ),
                file_path=record.file_path,
                shape_index=record.shape_index,
                label=record.label,
                group_id=record.group_id,
            )

        if label in self.rectangle_labels:
            if record.shape_type != "rectangle":
                return Issue(
                    rule_name=self.name,
                    severity=self.severity,
                    message=(
                        f"[类型不匹配] shape #{record.shape_index} "
                        f"label='{label}' 应为 rectangle，"
                        f"实际为 {record.shape_type}"
                    ),
                    file_path=record.file_path,
                    shape_index=record.shape_index,
                    label=record.label,
                    group_id=record.group_id,
                )

        if label in self.point_labels:
            if record.shape_type != "point":
                return Issue(
                    rule_name=self.name,
                    severity=self.severity,
                    message=(
                        f"[类型不匹配] shape #{record.shape_index} "
                        f"label='{label}' 应为 point，"
                        f"实际为 {record.shape_type}"
                    ),
                    file_path=record.file_path,
                    shape_index=record.shape_index,
                    label=record.label,
                    group_id=record.group_id,
                )

        return None


class GroupIdKeypointIntegrity(ValidationRule):
    """
    Check pose subject binding.

    person is the only pose subject.  Keypoints must belong to a group_id
    that contains a person rectangle.  head/face may share the same group_id
    as auxiliary boxes, but they do not carry pose keypoints.
    """

    name = "group_id_keypoint_integrity"
    severity = "warning"
    description = (
        "person 是唯一的 pose 主体；关键点必须绑定到含 person 的 group_id"
    )

    COCO_KEYPOINTS: Set[str] = {
        "nose",
        "l_eye",
        "r_eye",
        "l_ear",
        "r_ear",
        "l_sho",
        "r_sho",
        "l_elb",
        "r_elb",
        "l_wri",
        "r_wri",
        "l_hip",
        "r_hip",
        "l_knee",
        "r_knee",
        "l_ank",
        "r_ank",
    }

    def check_all(self, index: FlatIndex) -> List[Issue]:
        issues: List[Issue] = []
        for gid, records in index._by_group.items():
            if not is_valid_group_id(gid):
                continue
            has_person_rect = any(
                r.label == "person" and r.shape_type == "rectangle"
                for r in records
            )
            has_head_or_face = any(
                r.label in {"head", "face"} and r.shape_type == "rectangle"
                for r in records
            )
            has_keypoints = any(
                r.shape_type == "point" and r.label in self.COCO_KEYPOINTS
                for r in records
            )
            if has_keypoints and not has_person_rect:
                for rec in records:
                    if (
                        rec.shape_type == "point"
                        and rec.label in self.COCO_KEYPOINTS
                    ):
                        if has_head_or_face:
                            message = (
                                f"[主体缺失] group_id={gid} 只有 head/face 辅助框，"
                                f"却出现关键点 '{rec.label}'；关键点只能绑定到 person"
                            )
                        else:
                            message = (
                                f"[主体缺失] group_id={gid} 有关键点 '{rec.label}'，"
                                f"但没有 person 矩形框；关键点只能绑定到 person"
                            )
                        issues.append(
                            Issue(
                                rule_name=self.name,
                                severity=self.severity,
                                message=message,
                                file_path=rec.file_path,
                                shape_index=rec.shape_index,
                                label=rec.label,
                                group_id=gid,
                                extra={
                                    "has_person": has_person_rect,
                                    "has_head_or_face": has_head_or_face,
                                    "subject": "person",
                                },
                            )
                        )
        return issues

    def check(self, record, all_records, index):
        return None


class RequiredFieldNotEmpty(ValidationRule):
    """Check that required fields are present and non-empty."""

    name = "required_field_not_empty"
    severity = "error"
    description = "必填字段为空"

    REQUIRED_FIELDS: List[Tuple[str, str]] = [
        ("label", "标签名"),
        ("points_count", "坐标点"),
    ]

    # map field names to record attribute accessors
    _FIELD_GETTERS = {
        "label": lambda r: r.label,
        "points_count": lambda r: r.points_count,
    }

    def check(self, record, all_records, index):
        for field_name, display_name in self.REQUIRED_FIELDS:
            value = self._FIELD_GETTERS.get(field_name, lambda r: None)(record)
            if field_name == "label":
                if not value:
                    return Issue(
                        rule_name=self.name,
                        severity=self.severity,
                        message=(
                            f"[字段为空] shape #{record.shape_index} "
                            f"'{display_name}' 字段为空"
                        ),
                        file_path=record.file_path,
                        shape_index=record.shape_index,
                        label=record.label,
                        group_id=record.group_id,
                        extra={"field": field_name},
                    )
                continue
            if field_name == "points_count" and value <= 0:
                return Issue(
                    rule_name=self.name,
                    severity=self.severity,
                    message=(
                        f"[字段为空] shape #{record.shape_index} "
                        f"'{display_name}' 字段为空"
                    ),
                    file_path=record.file_path,
                    shape_index=record.shape_index,
                    label=record.label,
                    group_id=record.group_id,
                    extra={"field": field_name},
                )
        return None


class AttributeConsistency(ValidationRule):
    """
    Check shape attribute / flag consistency.

    Common issues:
    - 'difficult' flag on a point keypoint (usually a mistake)
    - 'orphan_head' flag present but no 'head' label
    """

    name = "attribute_consistency"
    severity = "warning"
    description = "shape 属性/flag 一致性"

    def check(self, record, all_records, index):
        issues: List[Issue] = []

        # difficult flag on point keypoints is unusual
        if (
            record.difficulty
            and record.shape_type == "point"
            and record.label
            in {
                "nose",
                "l_eye",
                "r_eye",
                "l_ear",
                "r_ear",
                "l_sho",
                "r_sho",
                "l_elb",
                "r_elb",
                "l_wri",
                "r_wri",
                "l_hip",
                "r_hip",
                "l_knee",
                "r_knee",
                "l_ank",
                "r_ank",
            }
        ):
            return Issue(
                rule_name=self.name,
                severity=self.severity,
                message=(
                    f"[属性可疑] shape #{record.shape_index} "
                    f"关键点 '{record.label}' 标记了 difficult 标志"
                ),
                file_path=record.file_path,
                shape_index=record.shape_index,
                label=record.label,
                group_id=record.group_id,
            )

        # orphan_head flag but no head label
        if record.flags.get("orphan_head") and record.label != "head":
            return Issue(
                rule_name=self.name,
                severity=self.severity,
                message=(
                    f"[属性不一致] shape #{record.shape_index} "
                    f"有 orphan_head flag 但 label='{record.label}' 不是 'head'"
                ),
                file_path=record.file_path,
                shape_index=record.shape_index,
                label=record.label,
                group_id=record.group_id,
            )

        return None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class ValidationEngine:
    """
    Runs a set of rules against a FlatIndex and collects a ValidationReport.
    """

    def __init__(self, rules: Optional[List[ValidationRule]] = None):
        self._rules: List[ValidationRule] = rules or []

    @property
    def rules(self) -> List[ValidationRule]:
        return self._rules

    def add_rule(self, rule: ValidationRule) -> None:
        self._rules.append(rule)

    def remove_rule(self, rule_name: str) -> None:
        self._rules = [r for r in self._rules if r.name != rule_name]

    def run(
        self,
        index: FlatIndex,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> ValidationReport:
        """Run all registered rules and return a report.

        Args:
            index: Flattened annotation index to validate.
            progress_callback: Optional callable(current, total, rule_name).
        """
        report = ValidationReport(
            total_files=index.file_count,
            total_records=index.record_count,
        )
        total = len(self._rules)
        for idx, rule in enumerate(self._rules, 1):
            try:
                issues = rule.check_all(index)
                report.issues.extend(issues)
                logger.debug(f"Rule '{rule.name}': {len(issues)} issue(s)")
            except Exception as exc:
                logger.error(
                    f"Rule '{rule.name}' crashed: {exc}",
                    exc_info=True,
                )
            if progress_callback:
                progress_callback(idx, total, rule.name)
        return report
