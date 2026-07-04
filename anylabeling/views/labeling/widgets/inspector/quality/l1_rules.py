"""
L1 hard rules — JSON field / label / shape_type / points / group_id /
basic geometry legality.

L1 rules are deterministic "the annotation is structurally broken" checks.
They do NOT use the threshold profile's warning/error thresholds; the v0
profile carries only a stub ``error_threshold: 1`` so the rules appear in
the report snapshot.  Severity is fixed (mostly ``error``).
"""

from __future__ import annotations

import logging
from typing import List, Optional

from . import geometry as G
from .quality_issue import PrimaryMetric, QcFile, QcShape, QualityIssue
from .threshold_profile import ThresholdProfile

logger = logging.getLogger(__name__)


# Labels expected to be rectangles vs points (mirrors the existing
# inspector LabelShapeTypeBinding, kept local to avoid the PyQt import
# chain).
RECTANGLE_LABELS = {"person", "head", "face"}
POINT_LABELS = {
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


def _bbox_list(bbox: Optional[G.BBox]) -> Optional[List[float]]:
    if bbox is None:
        return None
    return [round(c, 2) for c in bbox]


def run_l1(
    qc_file: QcFile,
    profile: ThresholdProfile,
) -> List[QualityIssue]:
    """Run all L1 rules against one file."""
    issues: List[QualityIssue] = []
    for shape in qc_file.shapes:
        issues.extend(_check_label_required(qc_file, shape))
        issues.extend(_check_shape_type_binding(qc_file, shape))
        issues.extend(_check_points_required(qc_file, shape))
        issues.extend(_check_group_id_required(qc_file, shape))
        issues.extend(_check_bbox_geom_valid(qc_file, shape))
    return issues


# ---------------------------------------------------------------------------
# L1-01 label required
# ---------------------------------------------------------------------------


def _check_label_required(
    qc_file: QcFile, shape: QcShape
) -> List[QualityIssue]:
    if shape.label:
        return []
    return [
        QualityIssue(
            rule_id="L1-01",
            rule_name="label_required",
            severity="error",
            file_path=qc_file.file_path,
            image_path=qc_file.image_path,
            shape_index=shape.shape_index,
            label="",
            group_id=shape.group_id,
            message=(f"[空标签] shape #{shape.shape_index} 标签为空"),
            primary_metric=PrimaryMetric(
                "label_present", 0.0, "lower_is_worse"
            ),
            metrics={"label_present": 0.0},
            thresholds_hit={
                "level": "error",
                "rule": "label_required",
            },
        )
    ]


# ---------------------------------------------------------------------------
# L1-02 shape_type binding
# ---------------------------------------------------------------------------


def _check_shape_type_binding(
    qc_file: QcFile, shape: QcShape
) -> List[QualityIssue]:
    label = shape.label
    if not label:
        return []  # handled by L1-01
    expected: Optional[str] = None
    if label in RECTANGLE_LABELS:
        expected = "rectangle"
    elif label in POINT_LABELS:
        expected = "point"
    if expected is None:
        return []  # unbound labels are not an L1 error here
    if shape.shape_type == expected:
        return []
    return [
        QualityIssue(
            rule_id="L1-02",
            rule_name="shape_type_binding",
            severity="error",
            file_path=qc_file.file_path,
            image_path=qc_file.image_path,
            shape_index=shape.shape_index,
            label=label,
            group_id=shape.group_id,
            message=(
                f"[类型不匹配] shape #{shape.shape_index} "
                f"label='{label}' 应为 {expected}，"
                f"实际为 {shape.shape_type or '空'}"
            ),
            primary_metric=PrimaryMetric(
                "shape_type_match", 0.0, "lower_is_worse"
            ),
            metrics={"shape_type_match": 0.0},
            thresholds_hit={
                "level": "error",
                "expected": expected,
                "actual": shape.shape_type,
            },
        )
    ]


# ---------------------------------------------------------------------------
# L1-03 points required
# ---------------------------------------------------------------------------


def _check_points_required(
    qc_file: QcFile, shape: QcShape
) -> List[QualityIssue]:
    needed = 2 if shape.shape_type == "rectangle" else 1
    if len(shape.points) >= needed:
        return []
    return [
        QualityIssue(
            rule_id="L1-03",
            rule_name="points_required",
            severity="error",
            file_path=qc_file.file_path,
            image_path=qc_file.image_path,
            shape_index=shape.shape_index,
            label=shape.label,
            group_id=shape.group_id,
            message=(
                f"[坐标点不足] shape #{shape.shape_index} "
                f"shape_type='{shape.shape_type}' 需要 >= {needed} 个点，"
                f"实际 {len(shape.points)} 个"
            ),
            primary_metric=PrimaryMetric(
                "points_count", float(len(shape.points)), "lower_is_worse"
            ),
            metrics={"points_count": float(len(shape.points))},
            thresholds_hit={
                "level": "error",
                "needed": needed,
                "actual": len(shape.points),
            },
        )
    ]


# ---------------------------------------------------------------------------
# L1-04 group_id required
# ---------------------------------------------------------------------------


def _check_group_id_required(
    qc_file: QcFile, shape: QcShape
) -> List[QualityIssue]:
    requires_gid = shape.label in {"person", "head", "face"} and (
        shape.shape_type == "rectangle"
    )
    if not requires_gid:
        return []
    gid = shape.group_id
    if isinstance(gid, int) and not isinstance(gid, bool) and gid >= 0:
        return []
    return [
        QualityIssue(
            rule_id="L1-04",
            rule_name="group_id_required",
            severity="error",
            file_path=qc_file.file_path,
            image_path=qc_file.image_path,
            shape_index=shape.shape_index,
            label=shape.label,
            group_id=None,
            message=(
                f"[缺少group_id] shape #{shape.shape_index} "
                f"label='{shape.label}' 矩形框未设置合法 group_id"
            ),
            primary_metric=PrimaryMetric(
                "group_id_valid", 0.0, "lower_is_worse"
            ),
            metrics={"group_id_valid": 0.0},
            thresholds_hit={"level": "error"},
        )
    ]


# ---------------------------------------------------------------------------
# L1-05 bbox geometry valid
# ---------------------------------------------------------------------------


def _check_bbox_geom_valid(
    qc_file: QcFile, shape: QcShape
) -> List[QualityIssue]:
    if shape.shape_type != "rectangle":
        return []
    if len(shape.points) < 2:
        return []  # handled by L1-03
    bbox = G.shape_bbox(shape.shape_type, shape.points)
    valid = 1.0 if G.is_valid_bbox(bbox) else 0.0
    if valid > 0:
        return []
    return [
        QualityIssue(
            rule_id="L1-05",
            rule_name="bbox_geom_valid",
            severity="error",
            file_path=qc_file.file_path,
            image_path=qc_file.image_path,
            shape_index=shape.shape_index,
            label=shape.label,
            group_id=shape.group_id,
            bbox=_bbox_list(bbox),
            message=(
                f"[bbox退化] shape #{shape.shape_index} "
                f"矩形框面积/尺寸非法 (points={shape.points})"
            ),
            primary_metric=PrimaryMetric(
                "bbox_validity", 0.0, "lower_is_worse"
            ),
            metrics={"bbox_validity": 0.0},
            thresholds_hit={"level": "error"},
        )
    ]
