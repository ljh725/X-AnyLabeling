"""
L2 geometric / visual-relation rules (L2-01 … L2-12).

Each rule consumes:
- the per-file QA matches (face→head, head→person) produced by
  ``matching.match_all_faces`` / ``match_all_heads``
- the threshold profile (rule thresholds, body bands, expand params)

and emits ``QualityIssue`` objects carrying ``primary_metric``,
``metrics``, ``thresholds_hit`` and (for match rules) ``match`` +
``candidates``.

Design notes:
- Cross-class relations are *temporary QA inferences*. They never bind a
  formal group_id and never write back to JSON.
- ``error_requires`` is honored: an error-level threshold that needs
  secondary confirmation is downgraded to warning when the confirmation
  fails.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import replace
from typing import Any, Dict, List, Optional, Tuple

from . import geometry as G
from .matching import (
    FaceHeadMatch,
    HeadPersonMatch,
    MatchingCfg,
    match_all_faces,
    match_all_heads,
)
from .quality_issue import (
    MatchCandidate,
    PrimaryMetric,
    QcFile,
    QcShape,
    QualityIssue,
)
from .severity_eval import evaluate_severity
from .threshold_profile import RuleThreshold, ThresholdProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


class FileContext:
    """Pre-computed per-file matches + label indexes for L2 rules."""

    def __init__(self, qc_file: QcFile, cfg: MatchingCfg) -> None:
        self.qc_file = qc_file
        self.cfg = cfg
        self.face_matches: List[FaceHeadMatch] = match_all_faces(qc_file, cfg)
        self.head_matches: List[HeadPersonMatch] = match_all_heads(
            qc_file, cfg
        )
        self.persons: List[QcShape] = qc_file.shapes_with_label("person")
        self.heads: List[QcShape] = qc_file.shapes_with_label("head")

    def keypoints_for_group(self, group_id: Optional[int]) -> List[QcShape]:
        if group_id is None:
            return []
        return [
            s
            for s in self.qc_file.shapes
            if s.group_id == group_id and s.shape_type == "point"
        ]


def _bbox_list(bbox: Optional[G.BBox]) -> Optional[List[float]]:
    if bbox is None:
        return None
    return [round(c, 2) for c in bbox]


def _match_dict(
    qa_entity_id: int,
    best_shape_index: Optional[int],
    confidence: Optional[float],
    extras: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "qa_entity_id": qa_entity_id,
        "matched_shape_index": best_shape_index,
        "confidence": (
            round(float(confidence), 4) if confidence is not None else None
        ),
    }
    if extras:
        d.update(extras)
    return d


def _match_gap_rule(rule: RuleThreshold, cfg: MatchingCfg) -> RuleThreshold:
    """Convert min_accept_score config into a match_gap threshold."""
    warning = rule.warning_threshold
    if isinstance(warning, dict) and isinstance(
        warning.get("min_accept_score"), (int, float)
    ):
        warning = max(0.0, 1.0 - float(warning["min_accept_score"]))
    elif warning is None:
        warning = max(0.0, 1.0 - float(cfg.min_accept_score))
    return replace(rule, warning_threshold=warning)


def _rule_with_error_threshold(
    rule: RuleThreshold, threshold_key: str
) -> RuleThreshold:
    """Select a branch-specific error threshold from a dict threshold."""
    error = rule.error_threshold
    if isinstance(error, dict) and isinstance(
        error.get(threshold_key), (int, float)
    ):
        return replace(rule, error_threshold=float(error[threshold_key]))
    return rule


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_l2(
    qc_file: QcFile,
    profile: ThresholdProfile,
    cfg: MatchingCfg,
) -> List[QualityIssue]:
    """Run all enabled L2 rules against one file."""
    ctx = FileContext(qc_file, cfg)
    issues: List[QualityIssue] = []
    for runner in _L2_RUNNERS:
        rule = profile.get_rule(runner.rule_id)
        if rule is None or not rule.enabled:
            continue
        try:
            issues.extend(runner.func(ctx, profile, cfg, rule))
        except Exception as exc:  # noqa: BLE001 — isolate rule crashes
            logger.error(
                f"L2 rule {runner.rule_id} crashed on "
                f"{qc_file.file_path}: {exc}",
                exc_info=True,
            )
    return issues


# ---------------------------------------------------------------------------
# L2-01 face_matched_head_candidate  (face → head match gap)
# ---------------------------------------------------------------------------


def l2_01_face_matched_head_candidate(
    ctx: FileContext,
    profile: ThresholdProfile,
    cfg: MatchingCfg,
    rule: RuleThreshold,
) -> List[QualityIssue]:
    out: List[QualityIssue] = []
    for idx, m in enumerate(ctx.face_matches):
        best_score = 1.0 - m.match_gap if m.best is not None else 0.0
        primary = PrimaryMetric(
            "face_head_match_gap", m.match_gap, rule.direction
        )
        severity, hit = evaluate_severity(
            _match_gap_rule(rule, cfg),
            m.match_gap,
            error_requires_satisfied=False,
        )
        if hit and isinstance(rule.warning_threshold, dict):
            hit["min_accept_score"] = rule.warning_threshold.get(
                "min_accept_score"
            )
        if severity is None:
            # even below gap threshold, an absent match is the signal
            if m.best is None:
                severity = rule.default_severity
                hit = {
                    "level": severity,
                    "reason": "no_candidate_passed_hard_filter",
                    "best_score": 0.0,
                }
            else:
                continue
        msg = _msg_face_head_match(m, best_score)
        out.append(
            _build_match_issue(
                ctx,
                rule,
                m.face,
                m.face_bbox,
                severity,
                hit,
                primary,
                metrics={
                    "face_head_match_gap": m.match_gap,
                    "best_score": best_score,
                    "ambiguous": 1.0 if m.ambiguous else 0.0,
                },
                match=_match_dict(idx, _shape_idx(m.matched_head), best_score),
                candidates=m.candidates,
                message=msg,
            )
        )
    return out


def _msg_face_head_match(m: FaceHeadMatch, best_score: float) -> str:
    if m.best is None:
        return (
            f"[face无匹配head] shape #{m.face.shape_index} "
            f"未找到满足硬过滤的候选 head（最高分 0.00 < "
            f"可接受阈值），请复核"
        )
    ambig = "（候选分差小，匹配不确定）" if m.ambiguous else ""
    return (
        f"[face/head匹配弱] shape #{m.face.shape_index} "
        f"最高候选分 {best_score:.2f}{ambig}，请复核 face/head 关系"
    )


# ---------------------------------------------------------------------------
# L2-02 face_inside_matched_head  (overflow ratio)
# ---------------------------------------------------------------------------


def l2_02_face_inside_matched_head(
    ctx: FileContext,
    profile: ThresholdProfile,
    cfg: MatchingCfg,
    rule: RuleThreshold,
) -> List[QualityIssue]:
    out: List[QualityIssue] = []
    for idx, m in enumerate(ctx.face_matches):
        if m.matched_head_bbox is None or m.face_bbox is None:
            continue
        overflow = G.overflow_ratio(m.face_bbox, m.matched_head_bbox)
        primary = PrimaryMetric(
            "face_head_overflow_ratio", overflow, rule.direction
        )
        severity, hit = evaluate_severity(
            rule, overflow, error_requires_satisfied=True
        )
        if severity is None:
            continue
        out.append(
            _build_match_issue(
                ctx,
                rule,
                m.face,
                m.face_bbox,
                severity,
                hit,
                primary,
                metrics={
                    "face_head_overflow_ratio": overflow,
                    "face_head_area_ratio": G.area_ratio(
                        m.face_bbox, m.matched_head_bbox
                    ),
                    "face_head_center_distance_norm": G.center_distance_norm(
                        m.face_bbox, m.matched_head_bbox
                    ),
                },
                match=_match_dict(
                    idx,
                    _shape_idx(m.matched_head),
                    1.0 - m.match_gap if m.best else 0.0,
                ),
                candidates=m.candidates,
                message=(
                    f"[face超出head] shape #{m.face.shape_index} "
                    f"overflow_ratio={overflow:.2f}，请复核 face/head 框边界"
                ),
            )
        )
    return out


# ---------------------------------------------------------------------------
# L2-03 face_head_area_ratio  (two_sided)
# ---------------------------------------------------------------------------


def l2_03_face_head_area_ratio(
    ctx: FileContext,
    profile: ThresholdProfile,
    cfg: MatchingCfg,
    rule: RuleThreshold,
) -> List[QualityIssue]:
    out: List[QualityIssue] = []
    for idx, m in enumerate(ctx.face_matches):
        if m.matched_head_bbox is None or m.face_bbox is None:
            continue
        ar = G.area_ratio(m.face_bbox, m.matched_head_bbox)
        face_ge_head = G.bbox_area(m.face_bbox) >= G.bbox_area(
            m.matched_head_bbox
        )
        # error_requires: face_area_ge_head_area
        err_ok = face_ge_head
        primary = PrimaryMetric("face_head_area_ratio", ar, rule.direction)
        severity, hit = evaluate_severity(
            rule, ar, error_requires_satisfied=err_ok
        )
        if severity is None:
            continue
        hit = dict(hit)
        hit["face_area_ge_head_area"] = face_ge_head
        out.append(
            _build_match_issue(
                ctx,
                rule,
                m.face,
                m.face_bbox,
                severity,
                hit,
                primary,
                metrics={
                    "face_head_area_ratio": ar,
                    "face_head_overflow_ratio": G.overflow_ratio(
                        m.face_bbox, m.matched_head_bbox
                    ),
                },
                match=_match_dict(
                    idx,
                    _shape_idx(m.matched_head),
                    1.0 - m.match_gap if m.best else 0.0,
                ),
                candidates=m.candidates,
                message=(
                    f"[face/head面积比异常] shape #{m.face.shape_index} "
                    f"area_ratio={ar:.2f}（合理区间 0.08~0.70），"
                    f"{'face>=head' if face_ge_head else ''}"
                ),
            )
        )
    return out


# ---------------------------------------------------------------------------
# L2-04 face_head_center_alignment
# ---------------------------------------------------------------------------


def l2_04_face_head_center_alignment(
    ctx: FileContext,
    profile: ThresholdProfile,
    cfg: MatchingCfg,
    rule: RuleThreshold,
) -> List[QualityIssue]:
    out: List[QualityIssue] = []
    for idx, m in enumerate(ctx.face_matches):
        if m.matched_head_bbox is None or m.face_bbox is None:
            continue
        dist = G.center_distance_norm(m.face_bbox, m.matched_head_bbox)
        primary = PrimaryMetric(
            "face_head_center_distance_norm", dist, rule.direction
        )
        severity, hit = evaluate_severity(
            rule, dist, error_requires_satisfied=True
        )
        if severity is None:
            continue
        out.append(
            _build_match_issue(
                ctx,
                rule,
                m.face,
                m.face_bbox,
                severity,
                hit,
                primary,
                metrics={
                    "face_head_center_distance_norm": dist,
                    "face_head_area_ratio": G.area_ratio(
                        m.face_bbox, m.matched_head_bbox
                    ),
                },
                match=_match_dict(
                    idx,
                    _shape_idx(m.matched_head),
                    1.0 - m.match_gap if m.best else 0.0,
                ),
                candidates=m.candidates,
                message=(
                    f"[face/head中心偏移] shape #{m.face.shape_index} "
                    f"中心偏移 norm={dist:.2f}（dx/head_w 或 dy/head_h），"
                    f"请复核"
                ),
            )
        )
    return out


# ---------------------------------------------------------------------------
# L2-05 head_matched_person_candidate  (head → person match gap)
# ---------------------------------------------------------------------------


def l2_05_head_matched_person_candidate(
    ctx: FileContext,
    profile: ThresholdProfile,
    cfg: MatchingCfg,
    rule: RuleThreshold,
) -> List[QualityIssue]:
    out: List[QualityIssue] = []
    for idx, m in enumerate(ctx.head_matches):
        best_score = 1.0 - m.match_gap if m.best is not None else 0.0
        primary = PrimaryMetric(
            "head_person_match_gap", m.match_gap, rule.direction
        )
        severity, hit = evaluate_severity(
            _match_gap_rule(rule, cfg),
            m.match_gap,
            error_requires_satisfied=False,
        )
        if hit and isinstance(rule.warning_threshold, dict):
            hit["min_accept_score"] = rule.warning_threshold.get(
                "min_accept_score"
            )
        if severity is None:
            # default behavior: no person → info; person present but no
            # match → warning. The rule's default_severity covers it.
            if m.best is None:
                severity = "info" if not m.file_has_person else "warning"
                hit = {
                    "level": severity,
                    "reason": (
                        "no_person_in_file"
                        if not m.file_has_person
                        else "no_candidate_passed_hard_filter"
                    ),
                    "best_score": 0.0,
                }
            else:
                continue
        out.append(
            _build_match_issue(
                ctx,
                rule,
                m.head,
                m.head_bbox,
                severity,
                hit,
                primary,
                metrics={
                    "head_person_match_gap": m.match_gap,
                    "best_score": best_score,
                    "ambiguous": 1.0 if m.ambiguous else 0.0,
                    "file_has_person": 1.0 if m.file_has_person else 0.0,
                },
                match=_match_dict(
                    idx, _shape_idx(m.matched_person), best_score
                ),
                candidates=m.candidates,
                message=_msg_head_person_match(m, best_score),
            )
        )
    return out


def _msg_head_person_match(m: HeadPersonMatch, best_score: float) -> str:
    if m.best is None:
        if not m.file_has_person:
            return (
                f"[head无person] shape #{m.head.shape_index} "
                f"本图无 person，head 可能合法独立存在（info）"
            )
        return (
            f"[head无匹配person] shape #{m.head.shape_index} "
            f"图内有 person 但未通过硬过滤，请复核 head/person 关系"
        )
    ambig = "（候选分差小，匹配不确定）" if m.ambiguous else ""
    return (
        f"[head/person匹配弱] shape #{m.head.shape_index} "
        f"最高候选分 {best_score:.2f}{ambig}，请复核"
    )


# ---------------------------------------------------------------------------
# L2-06 head_person_spatial  (spatial violation score)
# ---------------------------------------------------------------------------


def l2_06_head_person_spatial(
    ctx: FileContext,
    profile: ThresholdProfile,
    cfg: MatchingCfg,
    rule: RuleThreshold,
) -> List[QualityIssue]:
    out: List[QualityIssue] = []
    for idx, m in enumerate(ctx.head_matches):
        if m.matched_person_bbox is None or m.head_bbox is None:
            continue
        pb = m.matched_person_bbox
        hb = m.head_bbox
        x_ov = G.x_overlap_ratio(hb, pb)
        hc = G.bbox_center(hb)
        head_y_rel = (hc[1] - pb[1]) / G.bbox_height(pb)
        expanded_person = G.expand_bbox(
            pb, cfg.head_person_filter.person_expand_ratio
        )
        outside_expanded = not G.point_in_bbox(hc, expanded_person)

        # spatial violation score: how badly does head sit relative to person
        score = _spatial_violation_score(x_ov, head_y_rel, outside_expanded)
        primary = PrimaryMetric(
            "head_person_spatial_violation_score", score, rule.direction
        )

        err_ok = head_y_rel > 0.80 or x_ov < 0.05 or outside_expanded
        severity, hit = evaluate_severity(
            rule, score, error_requires_satisfied=err_ok
        )
        if severity is None:
            continue
        hit = dict(hit)
        hit.update(
            {
                "head_center_y_rel": round(head_y_rel, 4),
                "x_overlap_ratio": round(x_ov, 4),
                "outside_expanded_person": bool(outside_expanded),
            }
        )
        out.append(
            _build_match_issue(
                ctx,
                rule,
                m.head,
                hb,
                severity,
                hit,
                primary,
                metrics={
                    "head_person_spatial_violation_score": score,
                    "head_center_y_rel": head_y_rel,
                    "x_overlap_ratio": x_ov,
                    "head_person_area_ratio": G.area_ratio(hb, pb),
                },
                match=_match_dict(
                    idx,
                    _shape_idx(m.matched_person),
                    1.0 - m.match_gap if m.best else 0.0,
                ),
                candidates=m.candidates,
                message=(
                    f"[head/person空间异常] shape #{m.head.shape_index} "
                    f"violation={score:.2f}, y_rel={head_y_rel:.2f}, "
                    f"x_ov={x_ov:.2f}，请复核"
                ),
            )
        )
    return out


def _spatial_violation_score(
    x_ov: float, head_y_rel: float, outside_expanded: bool
) -> float:
    """0..1: how badly the head sits relative to the matched person."""
    score = 0.0
    # x overlap too low
    if x_ov < 0.15:
        score += min(1.0, (0.15 - x_ov) / 0.15) * 0.4
    # head center too low in person (lower body / below)
    if head_y_rel > 0.60:
        score += min(1.0, (head_y_rel - 0.60) / 0.40) * 0.4
    if outside_expanded:
        score += 0.3
    return min(1.0, score)


# ---------------------------------------------------------------------------
# L2-07 head_person_area_ratio  (two_sided)
# ---------------------------------------------------------------------------


def l2_07_head_person_area_ratio(
    ctx: FileContext,
    profile: ThresholdProfile,
    cfg: MatchingCfg,
    rule: RuleThreshold,
) -> List[QualityIssue]:
    out: List[QualityIssue] = []
    for idx, m in enumerate(ctx.head_matches):
        if m.matched_person_bbox is None or m.head_bbox is None:
            continue
        ar = G.area_ratio(m.head_bbox, m.matched_person_bbox)
        primary = PrimaryMetric("head_person_area_ratio", ar, rule.direction)
        severity, hit = evaluate_severity(
            rule, ar, error_requires_satisfied=True
        )
        if severity is None:
            continue
        out.append(
            _build_match_issue(
                ctx,
                rule,
                m.head,
                m.head_bbox,
                severity,
                hit,
                primary,
                metrics={
                    "head_person_area_ratio": ar,
                    "head_person_spatial_violation_score": _spatial_violation_score(
                        G.x_overlap_ratio(m.head_bbox, m.matched_person_bbox),
                        (
                            G.bbox_center(m.head_bbox)[1]
                            - m.matched_person_bbox[1]
                        )
                        / G.bbox_height(m.matched_person_bbox),
                        False,
                    ),
                },
                match=_match_dict(
                    idx,
                    _shape_idx(m.matched_person),
                    1.0 - m.match_gap if m.best else 0.0,
                ),
                candidates=m.candidates,
                message=(
                    f"[head/person面积比异常] shape #{m.head.shape_index} "
                    f"area_ratio={ar:.3f}（合理区间 0.015~0.25），请复核"
                ),
            )
        )
    return out


# ---------------------------------------------------------------------------
# L2-08 cross_class_size_order  (face < head < person)
# ---------------------------------------------------------------------------


def l2_08_cross_class_size_order(
    ctx: FileContext,
    profile: ThresholdProfile,
    cfg: MatchingCfg,
    rule: RuleThreshold,
) -> List[QualityIssue]:
    """Check size order along a matched chain: face < head < person."""
    out: List[QualityIssue] = []
    # face vs matched head
    for idx, m in enumerate(ctx.face_matches):
        if m.matched_head_bbox is None or m.face_bbox is None:
            continue
        face_a = G.bbox_area(m.face_bbox)
        head_a = G.bbox_area(m.matched_head_bbox)
        if head_a <= G._EPS:
            continue
        ratio = face_a / head_a  # 1.0 means face == head
        # violation score: 0 if face much smaller, →1 as ratio approaches 1
        violation = max(0.0, (ratio - 0.0))  # any positive is suspect
        # clamp: spec warns at >0, errors at >=0.95
        primary = PrimaryMetric(
            "size_order_violation_score", violation, rule.direction
        )
        # error_requires: face_ge_head_0_95
        err_ok = ratio >= 0.95
        severity, hit = evaluate_severity(
            _rule_with_error_threshold(rule, "face_head"),
            violation,
            error_requires_satisfied=err_ok,
        )
        if severity is None:
            continue
        hit = dict(hit)
        hit["face_head_size_ratio"] = round(ratio, 4)
        hit["error_requires_key"] = "face_ge_head_0_95"
        out.append(
            _build_match_issue(
                ctx,
                rule,
                m.face,
                m.face_bbox,
                severity,
                hit,
                primary,
                metrics={
                    "size_order_violation_score": violation,
                    "face_head_size_ratio": ratio,
                },
                match=_match_dict(
                    idx,
                    _shape_idx(m.matched_head),
                    1.0 - m.match_gap if m.best else 0.0,
                ),
                candidates=m.candidates,
                message=(
                    f"[大小顺序异常] shape #{m.face.shape_index} "
                    f"face/head 面积比 {ratio:.2f}（应 face<head），请复核"
                ),
            )
        )

    # head vs matched person
    for idx, m in enumerate(ctx.head_matches):
        if m.matched_person_bbox is None or m.head_bbox is None:
            continue
        head_a = G.bbox_area(m.head_bbox)
        person_a = G.bbox_area(m.matched_person_bbox)
        if person_a <= G._EPS:
            continue
        ratio = head_a / person_a
        violation = max(0.0, ratio)
        primary = PrimaryMetric(
            "size_order_violation_score", violation, rule.direction
        )
        err_ok = ratio >= 0.50
        severity, hit = evaluate_severity(
            _rule_with_error_threshold(rule, "head_person"),
            violation,
            error_requires_satisfied=err_ok,
        )
        if severity is None:
            continue
        hit = dict(hit)
        hit["head_person_size_ratio"] = round(ratio, 4)
        hit["error_requires_key"] = "head_ge_person_0_50"
        out.append(
            _build_match_issue(
                ctx,
                rule,
                m.head,
                m.head_bbox,
                severity,
                hit,
                primary,
                metrics={
                    "size_order_violation_score": violation,
                    "head_person_size_ratio": ratio,
                },
                match=_match_dict(
                    idx,
                    _shape_idx(m.matched_person),
                    1.0 - m.match_gap if m.best else 0.0,
                ),
                candidates=m.candidates,
                message=(
                    f"[大小顺序异常] shape #{m.head.shape_index} "
                    f"head/person 面积比 {ratio:.2f}（应 head<<person），"
                    f"请复核"
                ),
            )
        )
    return out


# ---------------------------------------------------------------------------
# L2-09 keypoint_inside_person
# ---------------------------------------------------------------------------


def l2_09_keypoint_inside_person(
    ctx: FileContext,
    profile: ThresholdProfile,
    cfg: MatchingCfg,
    rule: RuleThreshold,
) -> List[QualityIssue]:
    """For each person, check that its group's keypoints stay inside."""
    out: List[QualityIssue] = []
    expand = profile.config.get("person_expand_for_keypoints", {}) or {}
    ratio = (
        float(expand.get("ratio", 0.05)) if isinstance(expand, dict) else 0.05
    )
    min_pixels = (
        float(expand.get("min_pixels", 8.0))
        if isinstance(expand, dict)
        else 8.0
    )
    torso_set = set(
        profile.config.get("torso_keypoints", [])
        or [
            "l_sho",
            "r_sho",
            "l_hip",
            "r_hip",
        ]
    )

    for person in ctx.persons:
        if person.shape_type != "rectangle":
            continue
        pb = G.shape_bbox(person.shape_type, person.points)
        if pb is None or not G.is_valid_bbox(pb):
            continue
        expanded = G.expand_bbox(pb, ratio, min_pixels)
        kps = ctx.keypoints_for_group(person.group_id)
        if not kps:
            continue

        outside: List[Tuple[QcShape, float, bool]] = []
        max_dist_norm = 0.0
        torso_outside = False
        for kp in kps:
            if not kp.points:
                continue
            pt = kp.points[0]
            dist_norm = G.normalized_point_distance(pt, expanded)
            if dist_norm > G._EPS:
                is_torso = kp.label in torso_set
                outside.append((kp, dist_norm, is_torso))
                if is_torso:
                    torso_outside = True
                if dist_norm > max_dist_norm:
                    max_dist_norm = dist_norm

        if not outside:
            continue
        # farthest exceeds margin by more than 2x the expand (heuristic)
        farthest_exceeds = max_dist_norm > 2.0 * max(ratio, 0.01) + 0.01
        err_ok = torso_outside or len(outside) >= 3 or farthest_exceeds
        primary = PrimaryMetric(
            "keypoint_outside_distance_norm", max_dist_norm, rule.direction
        )
        severity, hit = evaluate_severity(
            rule, max_dist_norm, error_requires_satisfied=err_ok
        )
        if severity is None:
            continue
        hit = dict(hit)
        hit.update(
            {
                "outside_count": len(outside),
                "torso_keypoint_outside": bool(torso_outside),
                "farthest_outside_exceeds_margin": bool(farthest_exceeds),
            }
        )
        # emit one issue per person (aggregated), shape_index = person
        worst_kp, worst_dist, _ = max(outside, key=lambda t: t[1])
        out.append(
            QualityIssue(
                rule_id=rule.rule_id,
                rule_name=rule.rule_name,
                severity=severity,
                file_path=ctx.qc_file.file_path,
                image_path=ctx.qc_file.image_path,
                shape_index=worst_kp.shape_index,
                label=worst_kp.label,
                group_id=person.group_id,
                bbox=_bbox_list(pb),
                message=(
                    f"[关键点出person] group_id={person.group_id} "
                    f"{len(outside)} 个关键点越出 person 扩展框，"
                    f"最远 norm={max_dist_norm:.2f}（{worst_kp.label}），"
                    f"请复核"
                ),
                primary_metric=primary,
                metrics={
                    "keypoint_outside_distance_norm": max_dist_norm,
                    "outside_count": float(len(outside)),
                    "torso_keypoint_outside": 1.0 if torso_outside else 0.0,
                },
                thresholds_hit=hit,
                match=_match_dict(
                    person.shape_index,
                    person.shape_index,
                    None,
                    extras={"group_id": person.group_id},
                ),
            )
        )
    return out


# ---------------------------------------------------------------------------
# L2-10 body_part_vertical_band
# ---------------------------------------------------------------------------


def l2_10_body_part_vertical_band(
    ctx: FileContext,
    profile: ThresholdProfile,
    cfg: MatchingCfg,
    rule: RuleThreshold,
) -> List[QualityIssue]:
    bands_raw = profile.config.get("body_part_bands", {}) or {}
    bands = _resolve_bands(bands_raw)

    out: List[QualityIssue] = []
    for person in ctx.persons:
        if person.shape_type != "rectangle":
            continue
        pb = G.shape_bbox(person.shape_type, person.points)
        if pb is None or not G.is_valid_bbox(pb):
            continue
        kps = ctx.keypoints_for_group(person.group_id)
        violations: List[Tuple[QcShape, float, str]] = []
        max_viol = 0.0
        for kp in kps:
            band = _band_for_label(kp.label, bands)
            if band is None or not kp.points:
                continue
            y_rel = G.keypoint_y_rel(kp.points[0], pb)
            if y_rel is None:
                continue
            dist = G.band_violation_distance(
                y_rel, band["y_min"], band["y_max"]
            )
            if dist > G._EPS:
                violations.append((kp, dist, kp.label))
                if dist > max_viol:
                    max_viol = dist
        if not violations:
            continue
        # error_requires: crossed wrong band OR multiple points anomalous
        crossed = any(v[1] > 0.20 for v in violations)
        multi = len(violations) >= 2
        err_ok = crossed or multi
        primary = PrimaryMetric(
            "body_part_band_violation_distance", max_viol, rule.direction
        )
        severity, hit = evaluate_severity(
            rule, max_viol, error_requires_satisfied=err_ok
        )
        if severity is None:
            continue
        hit = dict(hit)
        hit.update(
            {
                "violation_count": len(violations),
                "keypoint_crossed_wrong_band": bool(crossed),
                "multiple_keypoints_anomalous": bool(multi),
            }
        )
        worst = max(violations, key=lambda v: v[1])
        out.append(
            QualityIssue(
                rule_id=rule.rule_id,
                rule_name=rule.rule_name,
                severity=severity,
                file_path=ctx.qc_file.file_path,
                image_path=ctx.qc_file.image_path,
                shape_index=worst[0].shape_index,
                label=worst[0].label,
                group_id=person.group_id,
                bbox=_bbox_list(pb),
                message=(
                    f"[人体垂直分区异常] group_id={person.group_id} "
                    f"{len(violations)} 个关键点越出期望身体区，"
                    f"最远距离 {max_viol:.2f}（{worst[2]}），请复核"
                ),
                primary_metric=primary,
                metrics={
                    "body_part_band_violation_distance": max_viol,
                    "violation_count": float(len(violations)),
                },
                thresholds_hit=hit,
                match=_match_dict(
                    person.shape_index,
                    person.shape_index,
                    None,
                    extras={"group_id": person.group_id},
                ),
            )
        )
    return out


def _resolve_bands(bands_raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    bands: List[Dict[str, Any]] = []
    if not isinstance(bands_raw, dict):
        return bands
    for _name, body in bands_raw.items():
        if not isinstance(body, dict):
            continue
        aliases = body.get("label_aliases", []) or []
        bands.append(
            {
                "aliases": set(aliases),
                "y_min": body.get("y_rel_min", body.get("y_min")),
                "y_max": body.get("y_rel_max", body.get("y_max")),
            }
        )
    return bands


def _band_for_label(
    label: str, bands: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    for b in bands:
        if label in b["aliases"]:
            return b
    return None


# ---------------------------------------------------------------------------
# L2-11 head_keypoints_near_head_face
# ---------------------------------------------------------------------------


def l2_11_head_keypoints_near_head_face(
    ctx: FileContext,
    profile: ThresholdProfile,
    cfg: MatchingCfg,
    rule: RuleThreshold,
) -> List[QualityIssue]:
    head_kp_labels = set(
        profile.config.get("head_keypoint_labels", [])
        or [
            "nose",
            "l_eye",
            "r_eye",
            "l_ear",
            "r_ear",
        ]
    )
    out: List[QualityIssue] = []
    # for each head, check its group's head keypoints
    for head in ctx.heads:
        if head.shape_type != "rectangle":
            continue
        hb = G.shape_bbox(head.shape_type, head.points)
        if hb is None or not G.is_valid_bbox(hb):
            continue
        # also consider a face in the same group as an anchor
        face_bbox = _first_face_bbox_in_group(ctx, head.group_id)
        anchor = face_bbox if face_bbox is not None else hb
        face_expanded = G.expand_bbox(anchor, 0.20)
        head_expanded = G.expand_bbox(hb, 0.15)

        kps = ctx.keypoints_for_group(head.group_id)
        far_points: List[Tuple[QcShape, float]] = []
        max_dist = 0.0
        for kp in kps:
            if kp.label not in head_kp_labels or not kp.points:
                continue
            pt = kp.points[0]
            # nose/eye prefer face expand 20%, else head expand 15%;
            # ear may use head expand 20%
            if kp.label == "l_ear" or kp.label == "r_ear":
                box = G.expand_bbox(hb, 0.20)
            else:
                box = face_expanded if face_bbox is not None else head_expanded
            dist = G.normalized_point_distance(pt, box)
            if dist > G._EPS:
                far_points.append((kp, dist))
                if dist > max_dist:
                    max_dist = dist
        if not far_points:
            continue
        at_least_two = len(far_points) >= 2
        err_ok = at_least_two
        primary = PrimaryMetric(
            "head_keypoint_box_distance_norm", max_dist, rule.direction
        )
        severity, hit = evaluate_severity(
            rule, max_dist, error_requires_satisfied=err_ok
        )
        if severity is None:
            continue
        hit = dict(hit)
        hit.update(
            {
                "far_head_keypoint_count": len(far_points),
                "at_least_two_head_keypoints_far": bool(at_least_two),
            }
        )
        worst = max(far_points, key=lambda t: t[1])
        out.append(
            QualityIssue(
                rule_id=rule.rule_id,
                rule_name=rule.rule_name,
                severity=severity,
                file_path=ctx.qc_file.file_path,
                image_path=ctx.qc_file.image_path,
                shape_index=worst[0].shape_index,
                label=worst[0].label,
                group_id=head.group_id,
                bbox=_bbox_list(hb),
                message=(
                    f"[头部点远离face/head] head shape #{head.shape_index} "
                    f"的同组头部关键点 {len(far_points)} 个远离候选 face/head，"
                    f"最远 norm={max_dist:.2f}（{worst[0].label}），请复核"
                ),
                primary_metric=primary,
                metrics={
                    "head_keypoint_box_distance_norm": max_dist,
                    "far_head_keypoint_count": float(len(far_points)),
                },
                thresholds_hit=hit,
                match=_match_dict(
                    head.shape_index,
                    head.shape_index,
                    None,
                    extras={"group_id": head.group_id},
                ),
            )
        )
    return out


def _first_face_bbox_in_group(
    ctx: FileContext, group_id: Optional[int]
) -> Optional[G.BBox]:
    if group_id is None:
        return None
    for s in ctx.qc_file.shapes:
        if (
            s.group_id == group_id
            and s.label == "face"
            and s.shape_type == "rectangle"
        ):
            return G.shape_bbox(s.shape_type, s.points)
    return None


# ---------------------------------------------------------------------------
# L2-12 image_level_class_density  (z-score, info/warning only)
# ---------------------------------------------------------------------------


def l2_12_image_level_class_density(
    ctx: FileContext,
    profile: ThresholdProfile,
    cfg: MatchingCfg,
    rule: RuleThreshold,
) -> List[QualityIssue]:
    """Per-image class count vs a historical baseline (if any).

    Stage-1 has no historical distribution, so this only emits info/
    warning and never errors.  When no baseline is provided we still emit
    a single info issue recording the per-class counts for the daily
    report.
    """
    counts = Counter(s.label for s in ctx.qc_file.shapes)
    # baseline could be supplied via profile.config['class_density_baseline']
    baseline = profile.config.get("class_density_baseline", {}) or {}
    if not isinstance(baseline, dict) or not baseline:
        # no history → daily stat only, info level
        return [
            QualityIssue(
                rule_id=rule.rule_id,
                rule_name=rule.rule_name,
                severity="info",
                file_path=ctx.qc_file.file_path,
                image_path=ctx.qc_file.image_path,
                shape_index=-1,
                message=(
                    f"[单图类密度统计] 本图 shape 计数 "
                    f"{dict(counts.most_common())}（无历史分布，仅观察）"
                ),
                primary_metric=PrimaryMetric(
                    "class_density_zscore", 0.0, rule.direction
                ),
                metrics={
                    "class_density_zscore": 0.0,
                    "total_shape_count": float(sum(counts.values())),
                },
                thresholds_hit={
                    "level": "info",
                    "reason": "no_historical_distribution",
                    "class_counts": dict(counts),
                },
            )
        ]
    out: List[QualityIssue] = []
    for label, count in counts.items():
        stats = baseline.get(label) or {}
        if not isinstance(stats, dict):
            continue
        mean = stats.get("mean")
        std = stats.get("std")
        if not isinstance(mean, (int, float)) or not isinstance(
            std, (int, float)
        ):
            continue
        z = (count - mean) / std if std > G._EPS else 0.0
        primary = PrimaryMetric("class_density_zscore", z, rule.direction)
        severity, hit = evaluate_severity(
            rule, z, error_requires_satisfied=False
        )
        if severity is None:
            continue
        out.append(
            QualityIssue(
                rule_id=rule.rule_id,
                rule_name=rule.rule_name,
                severity=severity,
                file_path=ctx.qc_file.file_path,
                image_path=ctx.qc_file.image_path,
                shape_index=-1,
                label=label,
                message=(
                    f"[类密度异常] label='{label}' 本图 {count} 个，"
                    f"z-score={z:.2f}（基线 mean={mean:.1f}, "
                    f"std={std:.1f}），请复核"
                ),
                primary_metric=primary,
                metrics={
                    "class_density_zscore": z,
                    "count": float(count),
                    "baseline_mean": float(mean),
                    "baseline_std": float(std),
                },
                thresholds_hit=hit,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Runner registry
# ---------------------------------------------------------------------------


class _Runner:
    __slots__ = ("rule_id", "func")

    def __init__(self, rule_id: str, func) -> None:
        self.rule_id = rule_id
        self.func = func


_L2_RUNNERS = [
    _Runner("L2-01", l2_01_face_matched_head_candidate),
    _Runner("L2-02", l2_02_face_inside_matched_head),
    _Runner("L2-03", l2_03_face_head_area_ratio),
    _Runner("L2-04", l2_04_face_head_center_alignment),
    _Runner("L2-05", l2_05_head_matched_person_candidate),
    _Runner("L2-06", l2_06_head_person_spatial),
    _Runner("L2-07", l2_07_head_person_area_ratio),
    _Runner("L2-08", l2_08_cross_class_size_order),
    _Runner("L2-09", l2_09_keypoint_inside_person),
    _Runner("L2-10", l2_10_body_part_vertical_band),
    _Runner("L2-11", l2_11_head_keypoints_near_head_face),
    _Runner("L2-12", l2_12_image_level_class_density),
]


# ---------------------------------------------------------------------------
# Shared issue builder
# ---------------------------------------------------------------------------


def _build_match_issue(
    ctx: FileContext,
    rule: RuleThreshold,
    shape: QcShape,
    bbox: Optional[G.BBox],
    severity: str,
    hit: Dict[str, Any],
    primary: PrimaryMetric,
    metrics: Dict[str, float],
    match: Dict[str, Any],
    candidates: List[MatchCandidate],
    message: str,
) -> QualityIssue:
    return QualityIssue(
        rule_id=rule.rule_id,
        rule_name=rule.rule_name,
        severity=severity,
        file_path=ctx.qc_file.file_path,
        image_path=ctx.qc_file.image_path,
        shape_index=shape.shape_index,
        label=shape.label,
        group_id=shape.group_id,
        bbox=_bbox_list(bbox),
        message=message,
        primary_metric=primary,
        metrics=metrics,
        thresholds_hit=hit,
        match=match,
        candidates=list(candidates),
    )


def _shape_idx(shape: Optional[QcShape]) -> Optional[int]:
    return shape.shape_index if shape is not None else None
