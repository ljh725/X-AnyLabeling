"""Registered inspection rules for structural, group and duplicate checks."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping, Optional, Sequence

from .duplicate import (
    DuplicatePair,
    DuplicateSeverity,
    DuplicateThresholds,
    PRESETS,
    RectangleSnapshot,
    evaluate_pair,
    full_scan,
    legacy_same_group_pair,
    rectangle_snapshot_from_points,
    relation_for,
    thresholds_from_mapping,
)
from .models import (
    CoverageState,
    FileSnapshot,
    InspectionIssue,
    InspectionProfile,
    IssueEvidence,
    IssueLocation,
    IssueSeverity,
    ShapeSnapshot,
    canonical_relation_key,
    stable_issue_id,
    utc_now_iso,
)
from .profiles import RuleCatalog


@dataclass(frozen=True)
class RuleContext:
    """Everything a rule needs, with no access to live Qt widgets."""

    profile: InspectionProfile
    file: FileSnapshot
    should_cancel: Callable[[], bool] = lambda: False
    duplicate_pairs: Optional[tuple[DuplicatePair, ...]] = None


@dataclass(frozen=True)
class RuleOutcome:
    """Rule result with explicit coverage and filtered evidence."""

    state: CoverageState
    issues: tuple[InspectionIssue, ...] = ()
    reason: str = ""
    truncated: bool = False
    filtered: tuple[Mapping[str, Any], ...] = ()


def _bbox(shape: ShapeSnapshot) -> Optional[tuple[float, float, float, float]]:
    if not shape.input_valid or len(shape.points) < 2:
        return None
    xs = [point[0] for point in shape.points]
    ys = [point[1] for point in shape.points]
    if not all(math.isfinite(value) for value in xs + ys):
        return None
    if max(xs) <= min(xs) or max(ys) <= min(ys):
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _bbox_area(box: tuple[float, float, float, float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _intersection_area(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    return max(0.0, right - left) * max(0.0, bottom - top)


def _bbox_overlap_of_smaller(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    smaller = min(_bbox_area(first), _bbox_area(second))
    if smaller <= 0:
        return 0.0
    return _intersection_area(first, second) / smaller


def _corner_exception_applies(
    members: Sequence[ShapeSnapshot],
    label: str,
    exceptions: Mapping[str, Any],
) -> bool:
    if not isinstance(exceptions, Mapping):
        return False
    attribute = exceptions.get(label)
    if not isinstance(attribute, str) or not attribute:
        return False
    for member in members:
        if bool(member.attributes.get(attribute)) or bool(
            member.flags.get(attribute)
        ):
            return True
    return False


def _make_issue(
    context: RuleContext,
    rule_id: str,
    implementation_version: str,
    rule_name: str,
    title: str,
    message: str,
    severity: IssueSeverity,
    *,
    object_ids: Sequence[str] = (),
    shape_indices: Sequence[int] = (),
    group_id: Optional[int] = None,
    region: Optional[Sequence[float]] = None,
    metrics: Optional[Mapping[str, float]] = None,
    thresholds: Optional[Mapping[str, Any]] = None,
    suggested_action: str = "",
    relation: str = "",
    filtered_reason: str = "",
    family_suffix: str = "",
) -> InspectionIssue:
    file = context.file
    location = IssueLocation(
        relative_path=file.relative_path,
        image_path=file.image_path,
        object_ids=tuple(str(item) for item in object_ids),
        shape_indices=tuple(int(item) for item in shape_indices),
        group_id=group_id,
        region=(tuple(float(item) for item in region[:4]) if region else None),
        snapshot_digest=file.annotation_digest,
    )
    family = _family_key(
        rule_id,
        file.relative_path,
        object_ids,
        region,
        group_id=group_id,
        suffix=family_suffix,
    )
    issue_id = stable_issue_id(
        family, "aggregate", file.relative_path, object_ids, region
    )
    evidence = IssueEvidence(
        rule_id=rule_id,
        implementation_version=implementation_version,
        rule_name=rule_name,
        message=message,
        severity=severity,
        metrics=dict(metrics or {}),
        thresholds=dict(thresholds or {}),
        snapshot_digest=file.annotation_digest,
        relation=relation,
        filtered_reason=filtered_reason,
    )
    return InspectionIssue(
        issue_id=issue_id,
        family_key=family,
        title=title,
        message=message,
        severity=severity,
        location=location,
        evidence=(evidence,),
        suggested_action=suggested_action,
        created_at=utc_now_iso(),
        updated_at=utc_now_iso(),
    )


def _family_key(
    rule_id: str,
    relative_path: str,
    object_ids: Sequence[str],
    region: Optional[Sequence[float]],
    *,
    group_id: Optional[int] = None,
    suffix: str = "",
) -> str:
    if rule_id in ("duplicate_boxes", "legacy_same_group_duplicate"):
        prefix = "duplicate_pair"
    elif rule_id == "corner_completeness":
        prefix = "corner_group"
    elif rule_id == "classroom_relation":
        prefix = "classroom_relation"
    elif rule_id == "group_completeness":
        prefix = "group_completeness"
    elif rule_id == "count_constraint":
        prefix = "count_constraint"
    else:
        prefix = rule_id
    object_key = ",".join(sorted(str(item) for item in object_ids))
    region_key = ",".join(f"{float(item):.3f}" for item in region or ())
    group_key = "" if group_id is None else str(group_id)
    return (
        f"{prefix}|{relative_path}|{object_key}|{region_key}|"
        f"group:{group_key}|{suffix}"
    )


def _not_applicable(reason: str) -> RuleOutcome:
    return RuleOutcome(state=CoverageState.NOT_APPLICABLE, reason=reason)


def _completed(
    issues: Sequence[InspectionIssue],
    *,
    reason: str = "",
    truncated: bool = False,
    filtered: Sequence[Mapping[str, Any]] = (),
) -> RuleOutcome:
    return RuleOutcome(
        state=CoverageState.COMPLETED,
        issues=tuple(issues),
        reason=reason,
        truncated=truncated,
        filtered=tuple(filtered),
    )


def run_label_required(
    context: RuleContext, parameters: Mapping[str, Any]
) -> RuleOutcome:
    issues = []
    for shape in context.file.shapes:
        if shape.label:
            continue
        issues.append(
            _make_issue(
                context,
                "label_required",
                "1.0.0",
                "标签必填",
                "对象缺少标签",
                f"对象 #{shape.index} 的标签为空。",
                IssueSeverity.ERROR,
                object_ids=(shape.shape_id,),
                shape_indices=(shape.index,),
                suggested_action="为对象设置合法类别。",
            )
        )
    if not context.file.shapes:
        return _not_applicable("图片没有对象，仍需图像查漏")
    return _completed(issues)


def run_shape_type_binding(
    context: RuleContext, parameters: Mapping[str, Any]
) -> RuleOutcome:
    expected_types = parameters.get("expected_types", {}) or {}
    if not isinstance(expected_types, Mapping) or not expected_types:
        return _not_applicable("未配置标签与形状类型绑定")
    issues = []
    for shape in context.file.shapes:
        expected = expected_types.get(shape.label)
        if not expected or shape.shape_type == expected:
            continue
        issues.append(
            _make_issue(
                context,
                "shape_type_binding",
                "1.0.0",
                "标签形状类型",
                "标签与形状类型不匹配",
                f"对象 #{shape.index} 标签 {shape.label} 应为 "
                f"{expected}，实际为 {shape.shape_type or '空'}。",
                IssueSeverity.ERROR,
                object_ids=(shape.shape_id,),
                shape_indices=(shape.index,),
                metrics={"expected": 1.0},
                thresholds={"expected": expected, "actual": shape.shape_type},
                suggested_action="改为正确形状类型或核对标签映射。",
            )
        )
    return _completed(issues)


def run_points_required(
    context: RuleContext, parameters: Mapping[str, Any]
) -> RuleOutcome:
    issues = []
    for shape in context.file.shapes:
        if not shape.input_valid:
            # Report the raw input problem from the geometry rule instead of
            # guessing a point count from a partially parsed list.
            continue
        if shape.shape_type == "rectangle":
            needed = 2
        elif shape.shape_type == "polygon":
            needed = 3
        else:
            needed = 1
        if len(shape.points) >= needed:
            continue
        issues.append(
            _make_issue(
                context,
                "points_required",
                "1.0.0",
                "坐标点数量",
                "对象坐标点不足",
                f"对象 #{shape.index} 类型 {shape.shape_type or '空'} "
                f"需要至少 {needed} 个点，实际 {len(shape.points)} 个。",
                IssueSeverity.ERROR,
                object_ids=(shape.shape_id,),
                shape_indices=(shape.index,),
                metrics={"points": float(len(shape.points))},
                thresholds={"required": needed},
                suggested_action="重新绘制或修复该对象。",
            )
        )
    return _completed(issues)


def run_group_id_required(
    context: RuleContext, parameters: Mapping[str, Any]
) -> RuleOutcome:
    labels = parameters.get("labels", []) or []
    if not isinstance(labels, (list, tuple, set)) or not labels:
        return _not_applicable("未配置必须分组的标签")
    required = {str(item) for item in labels}
    issues = []
    for shape in context.file.shapes:
        if shape.label not in required:
            continue
        if isinstance(shape.group_id, int) and shape.group_id >= 0:
            continue
        issues.append(
            _make_issue(
                context,
                "group_id_required",
                "1.0.0",
                "分组必填",
                "对象缺少合法分组",
                f"对象 #{shape.index} 标签 {shape.label} 未设置合法 "
                "group_id。",
                IssueSeverity.ERROR,
                object_ids=(shape.shape_id,),
                shape_indices=(shape.index,),
                suggested_action="为该对象建立正确分组关系。",
            )
        )
    return _completed(issues)


def run_bbox_geometry_valid(
    context: RuleContext, parameters: Mapping[str, Any]
) -> RuleOutcome:
    rectangles = [
        s for s in context.file.shapes if s.shape_type == "rectangle"
    ]
    if not rectangles:
        return _not_applicable("没有矩形对象")
    issues = []
    skipped = 0
    for shape in rectangles:
        if not shape.input_valid:
            region = _partial_region(shape)
            issues.append(
                _make_issue(
                    context,
                    "bbox_geometry_valid",
                    "1.0.0",
                    "矩形几何合法性",
                    "矩形输入坐标异常",
                    "对象 #{} 的原始坐标存在异常，未按合法矩形处理: "
                    "{}。检查不会丢弃这些异常点后继续计算。".format(
                        shape.index, "；".join(shape.input_errors)
                    ),
                    IssueSeverity.ERROR,
                    object_ids=(shape.shape_id,),
                    shape_indices=(shape.index,),
                    region=region,
                    thresholds={"input_errors": list(shape.input_errors)},
                    suggested_action="修正原始坐标或重新绘制该对象。",
                )
            )
            continue
        box = _bbox(shape)
        if box is None or _bbox_area(box) <= 0:
            issues.append(
                _make_issue(
                    context,
                    "bbox_geometry_valid",
                    "1.0.0",
                    "矩形几何合法性",
                    "矩形坐标无效",
                    f"对象 #{shape.index} 的坐标非有限数、点不足或面积为零。",
                    IssueSeverity.ERROR,
                    object_ids=(shape.shape_id,),
                    shape_indices=(shape.index,),
                    region=box,
                    suggested_action="修正矩形坐标或重新绘制。",
                )
            )
        if not shape.identity_valid:
            skipped += 1
    return _completed(
        issues,
        reason=(
            f"{skipped} 个对象身份异常，已按快照临时身份检查"
            if skipped
            else ""
        ),
    )


def _partial_region(
    shape: ShapeSnapshot,
) -> Optional[tuple[float, float, float, float]]:
    if len(shape.points) < 2:
        return None
    xs = [point[0] for point in shape.points]
    ys = [point[1] for point in shape.points]
    if not all(math.isfinite(value) for value in xs + ys):
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _thresholds(
    parameters: Mapping[str, Any],
) -> tuple[DuplicateThresholds, Mapping[str, Any]]:
    preset = str(parameters.get("preset", "medium"))
    if preset not in PRESETS:
        preset = "medium"
    advanced = parameters.get("thresholds")
    if isinstance(advanced, Mapping) and advanced:
        thresholds = thresholds_from_mapping(advanced)
        return thresholds, {"preset": preset, **thresholds.to_dict()}
    thresholds = PRESETS[preset]
    return thresholds, {"preset": preset, **thresholds.to_dict()}


def _duplicate_snapshots(
    context: RuleContext,
) -> tuple[list[RectangleSnapshot], list[InspectionIssue]]:
    snapshots: list[RectangleSnapshot] = []
    issues: list[InspectionIssue] = []
    for shape in context.file.shapes:
        if shape.shape_type != "rectangle":
            continue
        if not shape.input_valid:
            issues.append(
                _make_issue(
                    context,
                    "duplicate_boxes",
                    "1.0.0",
                    "疑似重复框",
                    "重复框输入坐标异常",
                    "对象 #{} 的原始坐标存在异常，未参与重复框几何计算: "
                    "{}。".format(shape.index, "；".join(shape.input_errors)),
                    IssueSeverity.ERROR,
                    object_ids=(shape.shape_id,),
                    shape_indices=(shape.index,),
                    suggested_action="修正原始坐标后重新检查。",
                )
            )
            continue
        try:
            snapshots.append(
                rectangle_snapshot_from_points(
                    shape.shape_id,
                    shape.label,
                    shape.points,
                    shape.group_id,
                )
            )
        except (TypeError, ValueError) as error:
            issues.append(
                _make_issue(
                    context,
                    "duplicate_boxes",
                    "1.0.0",
                    "疑似重复框",
                    "重复框检查输入无效",
                    f"对象 #{shape.index} 无法参与几何检查: {error}。",
                    IssueSeverity.ERROR,
                    object_ids=(shape.shape_id,),
                    shape_indices=(shape.index,),
                    suggested_action="修正矩形坐标后重新检查。",
                )
            )
    return snapshots, issues


def run_duplicate_boxes(
    context: RuleContext, parameters: Mapping[str, Any]
) -> RuleOutcome:
    snapshots, invalid_issues = _duplicate_snapshots(context)
    if not snapshots:
        if invalid_issues:
            return _completed(invalid_issues)
        return _not_applicable("没有可比较的矩形对象；仍需图像查漏")
    thresholds, threshold_snapshot = _thresholds(parameters)
    max_pairs = int(parameters.get("max_pairs", 5000) or 5000)
    truncated = False
    if context.duplicate_pairs is None:
        result = full_scan(
            snapshots, thresholds, context.should_cancel, max_pairs=max_pairs
        )
        pairs = result.pairs
        cancelled = result.cancelled
        truncated = result.truncated
    else:
        pairs = context.duplicate_pairs
        cancelled = context.should_cancel()
    if len(pairs) > max_pairs:
        pairs = pairs[:max_pairs]
        truncated = True
    issues, filtered = duplicate_pair_issues(
        context,
        parameters,
        pairs,
        threshold_snapshot=threshold_snapshot,
    )
    issues = list(invalid_issues) + issues
    reason = "已取消，保留部分证据" if cancelled else ""
    if truncated:
        reason = f"候选对超过上限 {max_pairs}，结果已截断"
    if cancelled:
        return RuleOutcome(
            state=CoverageState.CANCELLED,
            issues=tuple(issues),
            reason=reason,
            truncated=truncated,
            filtered=tuple(filtered),
        )
    return _completed(
        issues, reason=reason, truncated=truncated, filtered=filtered
    )


def duplicate_pair_issues(
    context: RuleContext,
    parameters: Mapping[str, Any],
    pairs: Sequence[DuplicatePair],
    *,
    threshold_snapshot: Optional[Mapping[str, Any]] = None,
) -> tuple[list[InspectionIssue], list[dict[str, Any]]]:
    """Convert already classified pairs into issues.

    Shared by the runner rule and the incremental edit refresh so both
    paths produce identical families and evidence for the same pairs.
    """
    snapshots, _ = _duplicate_snapshots(context)
    by_id = {item.shape_id: item for item in snapshots}
    if threshold_snapshot is None:
        _, threshold_snapshot = _thresholds(parameters)
    relations = dict(parameters.get("relations", {}) or {})
    if not relations:
        relations = dict(context.profile.relations)
    issues: list[InspectionIssue] = []
    filtered: list[dict[str, Any]] = []
    for pair in pairs:
        first = by_id.get(pair.first_id)
        second = by_id.get(pair.second_id)
        if first is None or second is None:
            continue
        same_label = first.label == second.label
        relation = (
            "same_class"
            if same_label
            else relation_for(first, second, relations)
        )
        if relation in ("allowed_coexist", "allowed_containment"):
            filtered.append(
                {
                    "first_id": first.shape_id,
                    "second_id": second.shape_id,
                    "relation": relation,
                    "metrics": pair.metrics.to_dict(),
                }
            )
            continue
        if relation == "unknown" and not same_label:
            relation_label = "未配置类别关系"
            title = "跨类几何重叠待判断"
            suggested = "确认两类目标是否允许重叠；不要仅凭几何重叠删除框。"
        elif relation == "mutually_exclusive":
            relation_label = "配置为互斥类别"
            title = "互斥类别几何重叠"
            suggested = (
                "核对两个对象是否确属互斥类别，再决定保留、改类或删除。"
            )
        else:
            relation_label = "同类几何重叠"
            title = "疑似重复矩形框"
            suggested = "查看两个框及证据，人工判断是否为重复对象。"
        issue = _make_issue(
            context,
            "duplicate_boxes",
            "1.0.0",
            "疑似重复框",
            title,
            (
                f"对象 {first.shape_id}（{first.label}）与 "
                f"{second.shape_id}（{second.label}）几何重叠；"
                f"{relation_label}。"
            ),
            IssueSeverity.WARNING,
            object_ids=(first.shape_id, second.shape_id),
            region=_union_region(first, second),
            metrics=pair.metrics.to_dict(),
            thresholds=threshold_snapshot,
            suggested_action=suggested,
            relation=relation,
            filtered_reason=relation_label,
        )
        issues.append(issue)
    return issues, filtered


def _union_region(
    first: RectangleSnapshot, second: RectangleSnapshot
) -> tuple[float, float, float, float]:
    return (
        min(first.bbox[0], second.bbox[0]),
        min(first.bbox[1], second.bbox[1]),
        max(first.bbox[2], second.bbox[2]),
        max(first.bbox[3], second.bbox[3]),
    )


def run_legacy_same_group_duplicate(
    context: RuleContext, parameters: Mapping[str, Any]
) -> RuleOutcome:
    tolerance = float(parameters.get("edge_tolerance_px", 2.0) or 2.0)
    snapshots, invalid_issues = _duplicate_snapshots(context)
    if not snapshots:
        return (
            _completed(invalid_issues)
            if invalid_issues
            else _not_applicable("没有可比较的矩形对象")
        )
    issues = list(invalid_issues)
    for index, first in enumerate(snapshots):
        for second in snapshots[index + 1 :]:
            if context.should_cancel():
                return RuleOutcome(
                    state=CoverageState.CANCELLED,
                    issues=tuple(issues),
                    reason="已取消，保留部分证据",
                )
            metrics = legacy_same_group_pair(first, second, tolerance)
            if metrics is None:
                continue
            if len(issues) >= 5000:
                return _completed(
                    issues,
                    reason="旧重复框规则候选超过上限 5000，结果已截断",
                    truncated=True,
                )
            issues.append(
                _make_issue(
                    context,
                    "legacy_same_group_duplicate",
                    "l2-13.v1",
                    "旧同组重复框规则",
                    "同组矩形边缘接近",
                    (
                        f"对象 {first.shape_id} 与 {second.shape_id} 同类同组，"
                        f"边缘差异在 {tolerance:g} 像素内。"
                    ),
                    IssueSeverity.WARNING,
                    object_ids=(first.shape_id, second.shape_id),
                    region=_union_region(first, second),
                    metrics=metrics.to_dict(),
                    thresholds={
                        "edge_tolerance_px": tolerance,
                        "rule_id": "L2-13",
                    },
                    suggested_action="核对是否为重复框；旧规则依据独立保留。",
                    relation="legacy_same_group",
                )
            )
    return _completed(issues)


def run_corner_completeness(
    context: RuleContext, parameters: Mapping[str, Any]
) -> RuleOutcome:
    corner_labels = parameters.get("corner_labels", {}) or {}
    if not corner_labels:
        corner_labels = {
            key: context.profile.label_bindings.get(key, "")
            for key in (
                "top_left",
                "top_right",
                "bottom_left",
                "bottom_right",
            )
        }
    screen_label = str(
        parameters.get("screen_label", "")
        or context.profile.label_bindings.get("screen", "")
        or ""
    )
    if not isinstance(corner_labels, Mapping) or len(corner_labels) < 4:
        return _not_applicable("屏幕四角点标签映射未完成")
    if not all(str(value or "").strip() for value in corner_labels.values()):
        return _not_applicable("屏幕四角点标签映射未完成")
    if not screen_label:
        return _not_applicable("未配置屏幕主体标签")
    labels = {str(key): str(value) for key, value in corner_labels.items()}
    required_labels = [labels[key] for key in sorted(labels)]
    exceptions = parameters.get(
        "exceptions", {}
    ) or context.profile.exceptions.get("corner_occlusion_attributes", {})
    groups: dict[int, list[ShapeSnapshot]] = {}
    screens_without_group = 0
    for shape in context.file.shapes:
        if shape.label == screen_label and shape.group_id is None:
            screens_without_group += 1
        if shape.group_id is None:
            continue
        if shape.label == screen_label or shape.label in required_labels:
            groups.setdefault(shape.group_id, []).append(shape)
    issues = []
    for group_id, members in sorted(groups.items()):
        counts = {
            label: sum(1 for shape in members if shape.label == label)
            for label in required_labels
        }
        screen = next(
            (shape for shape in members if shape.label == screen_label), None
        )
        region = _bbox(screen) if screen is not None else None
        for label in required_labels:
            count = counts[label]
            if count == 1:
                continue
            object_ids = tuple(
                shape.shape_id for shape in members if shape.label == label
            )
            if count == 0 and _corner_exception_applies(
                members, label, exceptions
            ):
                issues.append(
                    _make_issue(
                        context,
                        "corner_completeness",
                        "1.0.0",
                        "四角点完整性",
                        "角点缺失按配置例外处理",
                        (
                            f"分组 {group_id} 的 {label} 缺失，但该组命中"
                            "项目明确配置的遮挡/不可见例外；仍需人工核对。"
                        ),
                        IssueSeverity.INFO,
                        group_id=group_id,
                        region=region,
                        metrics={"count": 0.0},
                        thresholds={"expected": 1, "label": label},
                        suggested_action="确认例外依据是否仍成立。",
                        family_suffix=f"label:{label}:exception",
                    )
                )
                continue
            issue = _make_issue(
                context,
                "corner_completeness",
                "1.0.0",
                "四角点完整性",
                ("屏幕缺少角点" if count == 0 else "屏幕存在重复角点"),
                (f"分组 {group_id} 的 {label} 数量为 {count}，" "应为 1。"),
                IssueSeverity.ERROR,
                object_ids=object_ids,
                shape_indices=tuple(
                    shape.index for shape in members if shape.label == label
                ),
                group_id=group_id,
                region=region,
                metrics={"count": float(count)},
                thresholds={"expected": 1, "label": label},
                suggested_action="按可信屏幕分组补齐或修正角点。",
                family_suffix=f"label:{label}",
            )
            issues.append(issue)
    if not groups:
        reason = "没有可信屏幕分组"
        if screens_without_group:
            reason += f"；{screens_without_group} 个屏幕缺少分组"
        return _not_applicable(reason)
    if screens_without_group:
        issues.append(
            _make_issue(
                context,
                "corner_completeness",
                "1.0.0",
                "四角点完整性",
                "屏幕角点关联待确认",
                f"{screens_without_group} 个屏幕对象没有 group_id，"
                "无法逐实例核对角点。",
                IssueSeverity.WARNING,
                suggested_action="建立可信屏幕分组后重新检查。",
                family_suffix="screen-association",
            )
        )
    return _completed(issues)


def run_classroom_relation(
    context: RuleContext, parameters: Mapping[str, Any]
) -> RuleOutcome:
    relations = dict(parameters.get("relations", {}) or {})
    if not relations:
        relations = dict(context.profile.relations)
    if not relations:
        return _not_applicable("未配置课堂动作类别关系")
    min_overlap = float(parameters.get("min_overlap", 0.2) or 0.2)
    shapes = [shape for shape in context.file.shapes if _bbox(shape)]
    issues = []
    for index, first in enumerate(shapes):
        first_box = _bbox(first)
        if first_box is None:
            continue
        for second in shapes[index + 1 :]:
            if first.label == second.label:
                continue
            relation = relations.get(
                canonical_relation_key(first.label, second.label),
                "unknown",
            )
            if relation != "mutually_exclusive":
                continue
            second_box = _bbox(second)
            if second_box is None:
                continue
            overlap = _bbox_overlap_of_smaller(first_box, second_box)
            if overlap < min_overlap:
                continue
            issues.append(
                _make_issue(
                    context,
                    "classroom_relation",
                    "1.0.0",
                    "课堂动作关系",
                    "互斥动作类别重叠",
                    (
                        f"{first.label} 与 {second.label} 被项目配置为互斥，"
                        f"框重叠比例为 {overlap:.3f}。"
                    ),
                    IssueSeverity.WARNING,
                    object_ids=(first.shape_id, second.shape_id),
                    shape_indices=(first.index, second.index),
                    region=(
                        min(first_box[0], second_box[0]),
                        min(first_box[1], second_box[1]),
                        max(first_box[2], second_box[2]),
                        max(first_box[3], second_box[3]),
                    ),
                    metrics={"overlap_of_smaller": overlap},
                    thresholds={"min_overlap": min_overlap},
                    suggested_action="核对动作类别和框位置，按业务规则处理。",
                    relation=relation,
                )
            )
    return _completed(issues)


def run_group_completeness(
    context: RuleContext, parameters: Mapping[str, Any]
) -> RuleOutcome:
    groups = parameters.get("groups", {}) or {}
    if not isinstance(groups, Mapping) or not groups:
        return _not_applicable("未配置成组完整性要求")
    by_group: dict[int, list[ShapeSnapshot]] = {}
    for shape in context.file.shapes:
        if shape.group_id is None:
            continue
        by_group.setdefault(shape.group_id, []).append(shape)
    if not by_group:
        return _not_applicable("没有可信分组")
    issues = []
    for group_label, required_labels in groups.items():
        if not isinstance(required_labels, (list, tuple, set)):
            continue
        required = [str(item) for item in required_labels]
        for group_id, members in sorted(by_group.items()):
            labels = {shape.label for shape in members}
            if group_label not in labels:
                continue
            for label in required:
                count = sum(1 for shape in members if shape.label == label)
                if count == 1:
                    continue
                issues.append(
                    _make_issue(
                        context,
                        "group_completeness",
                        "1.0.0",
                        "成组完整性",
                        "分组成员缺失或重复",
                        (
                            f"分组 {group_id}（{group_label}）的 {label} "
                            f"数量为 {count}，应为 1。"
                        ),
                        IssueSeverity.ERROR,
                        group_id=group_id,
                        object_ids=tuple(
                            shape.shape_id
                            for shape in members
                            if shape.label == label
                        ),
                        metrics={"count": float(count)},
                        thresholds={"expected": 1, "label": label},
                        suggested_action="补齐或修正该分组内的必要成员。",
                        family_suffix=f"{group_label}:{label}",
                    )
                )
    return _completed(issues)


def run_count_constraint(
    context: RuleContext, parameters: Mapping[str, Any]
) -> RuleOutcome:
    counts = parameters.get("counts", {}) or {}
    if not isinstance(counts, Mapping) or not counts:
        return _not_applicable("未配置数量约束")
    issues = []
    grouped: dict[Optional[int], list[ShapeSnapshot]] = {}
    for shape in context.file.shapes:
        grouped.setdefault(shape.group_id, []).append(shape)
    for label, rules in counts.items():
        if not isinstance(rules, Mapping):
            continue
        minimum = rules.get("min")
        maximum = rules.get("max")
        scope = str(rules.get("scope", "image"))
        buckets = (
            {None: context.file.shapes}
            if scope == "image"
            else {
                group_id: members
                for group_id, members in grouped.items()
                if group_id is not None
            }
        )
        for group_id, members in buckets.items():
            count = sum(1 for shape in members if shape.label == label)
            violated = (minimum is not None and count < int(minimum)) or (
                maximum is not None and count > int(maximum)
            )
            if not violated:
                continue
            issues.append(
                _make_issue(
                    context,
                    "count_constraint",
                    "1.0.0",
                    "数量约束",
                    "对象数量不符合约束",
                    f"{label} 数量为 {count}，约束为 min={minimum} "
                    f"max={maximum}（scope={scope}）。",
                    IssueSeverity.WARNING,
                    group_id=group_id,
                    metrics={"count": float(count)},
                    thresholds={
                        "min": minimum,
                        "max": maximum,
                        "scope": scope,
                    },
                    suggested_action="核对是否漏标或多标；数量相等不能证明无漏标。",
                    family_suffix=f"{label}:{scope}",
                )
            )
    return _completed(issues)


def register_default_rules(catalog: RuleCatalog) -> None:
    """Register every built-in rule with Chinese metadata."""
    entries = (
        (
            "label_required",
            "1.0.0",
            "标签必填",
            "检查每个对象是否具有非空标签。",
            "image",
            (),
            run_label_required,
        ),
        (
            "shape_type_binding",
            "1.0.0",
            "标签形状类型",
            "按项目配置检查标签是否使用了预期形状类型。",
            "image",
            ("expected_types",),
            run_shape_type_binding,
        ),
        (
            "points_required",
            "1.0.0",
            "坐标点数量",
            "检查矩形、多边形等对象是否有足够坐标点。",
            "image",
            (),
            run_points_required,
        ),
        (
            "group_id_required",
            "1.0.0",
            "分组必填",
            "检查项目指定标签是否具有合法 group_id。",
            "image",
            ("labels",),
            run_group_id_required,
        ),
        (
            "bbox_geometry_valid",
            "1.0.0",
            "矩形几何合法性",
            "检查矩形坐标是否有限、点是否足够且面积大于零。",
            "image",
            (),
            run_bbox_geometry_valid,
        ),
        (
            "duplicate_boxes",
            "1.0.0",
            "疑似重复框",
            "使用旧版双屏几何指标检查同类及跨类矩形重叠。",
            "image",
            ("preset", "thresholds", "relations", "max_pairs"),
            run_duplicate_boxes,
        ),
        (
            "legacy_same_group_duplicate",
            "l2-13.v1",
            "旧同组重复框规则",
            "保留旧 L2-13 的同类同组边缘接近依据。",
            "image",
            ("edge_tolerance_px",),
            run_legacy_same_group_duplicate,
        ),
        (
            "corner_completeness",
            "1.0.0",
            "四角点完整性",
            "按可信屏幕分组检查四类角点是否各有一个。",
            "group",
            ("corner_labels", "screen_label", "exceptions"),
            run_corner_completeness,
        ),
        (
            "classroom_relation",
            "1.0.0",
            "课堂动作关系",
            "按项目配置检查互斥动作类别是否几何重叠。",
            "image",
            ("relations", "min_overlap"),
            run_classroom_relation,
        ),
        (
            "group_completeness",
            "1.0.0",
            "成组完整性",
            "按可信分组检查必要成员是否各有一个。",
            "group",
            ("groups",),
            run_group_completeness,
        ),
        (
            "count_constraint",
            "1.0.0",
            "数量约束",
            "按图片或分组检查对象数量上下限。",
            "image",
            ("counts",),
            run_count_constraint,
        ),
    )
    for (
        rule_id,
        version,
        name,
        description,
        scope,
        parameters,
        executor,
    ) in entries:
        stage = "post_label"
        if rule_id == "corner_completeness":
            stage = "in_progress"
        catalog.register(
            _meta(
                rule_id,
                version,
                name,
                description,
                stage,
                scope,
                parameters,
            ),
            executor,
        )


RULE_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "label_required": ("shapes.label",),
    "shape_type_binding": ("shapes.label", "shapes.shape_type"),
    "points_required": ("shapes.shape_type", "shapes.points"),
    "group_id_required": ("shapes.label", "shapes.group_id"),
    "bbox_geometry_valid": ("shapes.shape_type", "shapes.points"),
    "duplicate_boxes": (
        "shapes.shape_type",
        "shapes.points",
        "shapes.label",
        "shapes.group_id",
    ),
    "legacy_same_group_duplicate": (
        "shapes.points",
        "shapes.label",
        "shapes.group_id",
    ),
    "corner_completeness": (
        "shapes.label",
        "shapes.group_id",
        "shapes.points",
    ),
    "classroom_relation": ("shapes.label", "shapes.points"),
    "group_completeness": ("shapes.group_id", "shapes.label"),
    "count_constraint": ("shapes.label", "shapes.group_id"),
}


def _meta(
    rule_id: str,
    version: str,
    name: str,
    description: str,
    stage: str,
    scope: str,
    parameters: Sequence[str],
) -> Any:
    from .models import RuleMeta

    return RuleMeta(
        rule_id=rule_id,
        implementation_version=version,
        name=name,
        description=description,
        stage=stage,
        scope=scope,
        parameters=tuple(parameters),
        examples={
            "normal": "对象字段完整且几何合法。",
            "abnormal": "对象缺少必要字段或触发配置约束。",
        },
        depends_on=RULE_DEPENDENCIES.get(rule_id, ()),
    )
