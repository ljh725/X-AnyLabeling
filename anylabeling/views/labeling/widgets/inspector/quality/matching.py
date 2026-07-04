"""
QA temporary matching: face→head and head→person.

These are *temporary* geometric inferences, never written back to the
formal ``group_id`` or to the JSON.  Output: ranked candidate lists +
match-gap metrics consumed by the L2 rules.

Two matching protocols (see spec sections 4 and 5):

face → head (strict):
    hard filter: x_overlap >= 0.25, y_overlap >= 0.15,
                 face/head area <= 0.85, face center in expanded head 15%,
                 overflow <= 0.30
    score = .35 containment + .20 center_alignment
            + .20 area_ratio + .25 overlap

head → person (loose):
    hard filter: x_overlap >= 0.15,
                 head_center_y <= person_top + 0.60*person_h,
                 head/person area <= 0.40,
                 head center in expanded person 20%
    score = .30 upper_body_position + .25 x_overlap
            + .20 area_ratio + .15 center_distance + .10 keypoint_support
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import geometry as G
from .quality_issue import MatchCandidate, QcFile, QcShape

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public result types
# ---------------------------------------------------------------------------


@dataclass
class FaceHeadMatch:
    """Result of matching one face to candidate heads."""

    face: QcShape
    face_bbox: Optional[G.BBox] = None
    best: Optional[MatchCandidate] = None
    candidates: List[MatchCandidate] = field(default_factory=list)
    ambiguous: bool = False
    # primary metric for L2-01
    match_gap: float = 1.0  # 1 - best_score; 1.0 == no candidate
    # matched head shape (None if no best)
    matched_head: Optional[QcShape] = None
    matched_head_bbox: Optional[G.BBox] = None


@dataclass
class HeadPersonMatch:
    """Result of matching one head to candidate persons."""

    head: QcShape
    head_bbox: Optional[G.BBox] = None
    best: Optional[MatchCandidate] = None
    candidates: List[MatchCandidate] = field(default_factory=list)
    ambiguous: bool = False
    match_gap: float = 1.0
    matched_person: Optional[QcShape] = None
    matched_person_bbox: Optional[G.BBox] = None
    # whether the file contained any person at all
    file_has_person: bool = False


# ---------------------------------------------------------------------------
# Config extraction (from a ThresholdProfile.config dict)
# ---------------------------------------------------------------------------


@dataclass
class FaceHeadFilterCfg:
    min_x_overlap: float = 0.25
    min_y_overlap: float = 0.15
    max_face_head_area_ratio: float = 0.85
    head_expand_ratio: float = 0.15
    max_overflow_ratio: float = 0.30


@dataclass
class FaceHeadScoreCfg:
    containment: float = 0.35
    center_alignment: float = 0.20
    area_ratio: float = 0.20
    overlap: float = 0.25


@dataclass
class HeadPersonFilterCfg:
    min_x_overlap: float = 0.15
    max_head_y_rel_in_person: float = 0.60
    max_head_person_area_ratio: float = 0.40
    person_expand_ratio: float = 0.20


@dataclass
class HeadPersonScoreCfg:
    upper_body_position: float = 0.30
    x_overlap: float = 0.25
    area_ratio: float = 0.20
    center_distance: float = 0.15
    keypoint_support: float = 0.10


@dataclass
class MatchingCfg:
    min_accept_score: float = 0.55
    ambiguous_top_gap: float = 0.12
    top_n_candidates: int = 3
    face_head_filter: FaceHeadFilterCfg = field(
        default_factory=FaceHeadFilterCfg
    )
    face_head_score: FaceHeadScoreCfg = field(default_factory=FaceHeadScoreCfg)
    head_person_filter: HeadPersonFilterCfg = field(
        default_factory=HeadPersonFilterCfg
    )
    head_person_score: HeadPersonScoreCfg = field(
        default_factory=HeadPersonScoreCfg
    )


def matching_cfg_from_profile(config: Dict[str, Any]) -> MatchingCfg:
    """Build a ``MatchingCfg`` from the ``config`` block of a profile."""
    cfg = MatchingCfg()
    raw_matching = config.get("matching", {}) or {}
    if isinstance(raw_matching, dict):
        if isinstance(raw_matching.get("min_accept_score"), (int, float)):
            cfg.min_accept_score = float(raw_matching["min_accept_score"])
        if isinstance(raw_matching.get("ambiguous_top_gap"), (int, float)):
            cfg.ambiguous_top_gap = float(raw_matching["ambiguous_top_gap"])
        if isinstance(raw_matching.get("top_n_candidates"), int):
            cfg.top_n_candidates = int(raw_matching["top_n_candidates"])

    fhr = config.get("face_head_hard_filter", {}) or {}
    if isinstance(fhr, dict):
        cfg.face_head_filter = FaceHeadFilterCfg(
            min_x_overlap=float(fhr.get("min_x_overlap", 0.25)),
            min_y_overlap=float(fhr.get("min_y_overlap", 0.15)),
            max_face_head_area_ratio=float(
                fhr.get("max_face_head_area_ratio", 0.85)
            ),
            head_expand_ratio=float(fhr.get("head_expand_ratio", 0.15)),
            max_overflow_ratio=float(fhr.get("max_overflow_ratio", 0.30)),
        )

    fhs = config.get("face_head_score_weights", {}) or {}
    if isinstance(fhs, dict):
        cfg.face_head_score = FaceHeadScoreCfg(
            containment=float(fhs.get("containment", 0.35)),
            center_alignment=float(fhs.get("center_alignment", 0.20)),
            area_ratio=float(fhs.get("area_ratio", 0.20)),
            overlap=float(fhs.get("overlap", 0.25)),
        )

    hpr = config.get("head_person_hard_filter", {}) or {}
    if isinstance(hpr, dict):
        cfg.head_person_filter = HeadPersonFilterCfg(
            min_x_overlap=float(hpr.get("min_x_overlap", 0.15)),
            max_head_y_rel_in_person=float(
                hpr.get("max_head_y_rel_in_person", 0.60)
            ),
            max_head_person_area_ratio=float(
                hpr.get("max_head_person_area_ratio", 0.40)
            ),
            person_expand_ratio=float(hpr.get("person_expand_ratio", 0.20)),
        )

    hps = config.get("head_person_score_weights", {}) or {}
    if isinstance(hps, dict):
        cfg.head_person_score = HeadPersonScoreCfg(
            upper_body_position=float(hps.get("upper_body_position", 0.30)),
            x_overlap=float(hps.get("x_overlap", 0.25)),
            area_ratio=float(hps.get("area_ratio", 0.20)),
            center_distance=float(hps.get("center_distance", 0.15)),
            keypoint_support=float(hps.get("keypoint_support", 0.10)),
        )

    return cfg


# ---------------------------------------------------------------------------
# face → head
# ---------------------------------------------------------------------------


def match_face_to_heads(
    face: QcShape,
    heads: List[QcShape],
    cfg: MatchingCfg,
) -> FaceHeadMatch:
    """Rank candidate heads for one face.

    Args:
        face: the face shape.
        heads: all head shapes *in the same file*.
        cfg: matching config.

    Returns:
        a ``FaceHeadMatch`` with ranked candidates.
    """
    result = FaceHeadMatch(face=face)
    face_bbox = G.shape_bbox(face.shape_type, face.points)
    result.face_bbox = face_bbox
    if face_bbox is None or not G.is_valid_bbox(face_bbox):
        return result

    fc = cfg.face_head_filter
    sc = cfg.face_head_score

    scored: List[Tuple[float, MatchCandidate, QcShape, G.BBox]] = []
    for head in heads:
        head_bbox = G.shape_bbox(head.shape_type, head.points)
        if head_bbox is None or not G.is_valid_bbox(head_bbox):
            continue

        # ---- hard filter ----
        x_ov = G.x_overlap_ratio(face_bbox, head_bbox)
        y_ov = G.y_overlap_ratio(face_bbox, head_bbox)
        ar = G.area_ratio(face_bbox, head_bbox)
        overflow = G.overflow_ratio(face_bbox, head_bbox)
        expanded_head = G.expand_bbox(head_bbox, fc.head_expand_ratio)
        fcenter = G.bbox_center(face_bbox)
        center_in_expanded = G.point_in_bbox(fcenter, expanded_head)

        if x_ov < fc.min_x_overlap:
            continue
        if y_ov < fc.min_y_overlap:
            continue
        if ar > fc.max_face_head_area_ratio:
            continue
        if overflow > fc.max_overflow_ratio:
            continue
        if not center_in_expanded:
            continue

        # ---- score ----
        containment = G.containment_ratio(face_bbox, head_bbox)
        center_align = 1.0 - min(
            1.0, G.center_distance_norm(face_bbox, head_bbox)
        )
        # area ratio score: ideal around 0.3, falls off toward 0 and 0.85
        area_score = _area_ratio_score(ar, ideal=0.30, hi=0.85)
        overlap = G.iou(face_bbox, head_bbox)

        score = (
            sc.containment * containment
            + sc.center_alignment * center_align
            + sc.area_ratio * area_score
            + sc.overlap * overlap
        )
        cand = MatchCandidate(
            shape_index=head.shape_index,
            label=head.label,
            score=score,
            metrics={
                "containment_score": containment,
                "center_alignment_score": center_align,
                "area_ratio_score": area_score,
                "overlap_score": overlap,
                "x_overlap_ratio": x_ov,
                "y_overlap_ratio": y_ov,
                "face_head_area_ratio": ar,
                "face_head_overflow_ratio": overflow,
            },
        )
        scored.append((score, cand, head, head_bbox))

    if not scored:
        return result

    scored.sort(key=lambda t: t[0], reverse=True)
    result.candidates = [t[1] for t in scored[: max(1, cfg.top_n_candidates)]]
    best_score, best_cand, best_head, best_head_bbox = scored[0]
    result.best = best_cand
    result.matched_head = best_head
    result.matched_head_bbox = best_head_bbox
    result.match_gap = max(0.0, 1.0 - best_score)
    if len(scored) >= 2:
        top2_gap = scored[0][0] - scored[1][0]
        result.ambiguous = top2_gap < cfg.ambiguous_top_gap
    return result


# ---------------------------------------------------------------------------
# head → person
# ---------------------------------------------------------------------------


def match_head_to_persons(
    head: QcShape,
    persons: List[QcShape],
    cfg: MatchingCfg,
) -> HeadPersonMatch:
    """Rank candidate persons for one head (loose protocol)."""
    result = HeadPersonMatch(head=head, file_has_person=len(persons) > 0)
    head_bbox = G.shape_bbox(head.shape_type, head.points)
    result.head_bbox = head_bbox
    if head_bbox is None or not G.is_valid_bbox(head_bbox):
        return result

    fc = cfg.head_person_filter
    sc = cfg.head_person_score

    head_center = G.bbox_center(head_bbox)

    scored: List[Tuple[float, MatchCandidate, QcShape, G.BBox]] = []
    for person in persons:
        person_bbox = G.shape_bbox(person.shape_type, person.points)
        if person_bbox is None or not G.is_valid_bbox(person_bbox):
            continue

        ph = G.bbox_height(person_bbox)
        if ph <= G._EPS:
            continue

        # ---- hard filter ----
        x_ov = G.x_overlap_ratio(head_bbox, person_bbox)
        head_y_rel = (head_center[1] - person_bbox[1]) / ph
        ar = G.area_ratio(head_bbox, person_bbox)
        expanded_person = G.expand_bbox(person_bbox, fc.person_expand_ratio)
        center_in_expanded = G.point_in_bbox(head_center, expanded_person)

        if x_ov < fc.min_x_overlap:
            continue
        if head_y_rel > fc.max_head_y_rel_in_person:
            continue
        if ar > fc.max_head_person_area_ratio:
            continue
        if not center_in_expanded:
            continue

        # ---- score ----
        # upper-body position: ideal head_y_rel around 0.10–0.30
        upper = _upper_body_position_score(head_y_rel)
        x_score = min(1.0, x_ov)
        # area ratio score: ideal around 0.08, falls off toward 0 and 0.40
        area_score = _area_ratio_score(ar, ideal=0.08, hi=0.40)
        center_dist = 1.0 - min(
            1.0, G.center_distance_norm(head_bbox, person_bbox)
        )
        kp_support = _keypoint_support_score(person)

        score = (
            sc.upper_body_position * upper
            + sc.x_overlap * x_score
            + sc.area_ratio * area_score
            + sc.center_distance * center_dist
            + sc.keypoint_support * kp_support
        )
        cand = MatchCandidate(
            shape_index=person.shape_index,
            label=person.label,
            score=score,
            metrics={
                "upper_body_position_score": upper,
                "x_overlap_score": x_score,
                "area_ratio_score": area_score,
                "center_distance_score": center_dist,
                "keypoint_support_score": kp_support,
                "x_overlap_ratio": x_ov,
                "head_center_y_rel": head_y_rel,
                "head_person_area_ratio": ar,
            },
        )
        scored.append((score, cand, person, person_bbox))

    if not scored:
        return result

    scored.sort(key=lambda t: t[0], reverse=True)
    result.candidates = [t[1] for t in scored[: max(1, cfg.top_n_candidates)]]
    best_score, best_cand, best_person, best_person_bbox = scored[0]
    result.best = best_cand
    result.matched_person = best_person
    result.matched_person_bbox = best_person_bbox
    result.match_gap = max(0.0, 1.0 - best_score)
    if len(scored) >= 2:
        top2_gap = scored[0][0] - scored[1][0]
        result.ambiguous = top2_gap < cfg.ambiguous_top_gap
    return result


# ---------------------------------------------------------------------------
# File-level helpers
# ---------------------------------------------------------------------------


def match_all_faces(qc_file: QcFile, cfg: MatchingCfg) -> List[FaceHeadMatch]:
    """Match every face shape in a file to its heads."""
    heads = qc_file.shapes_with_label("head")
    out: List[FaceHeadMatch] = []
    for shape in qc_file.shapes:
        if shape.label == "face":
            out.append(match_face_to_heads(shape, heads, cfg))
    return out


def match_all_heads(
    qc_file: QcFile, cfg: MatchingCfg
) -> List[HeadPersonMatch]:
    """Match every head shape in a file to its persons."""
    persons = qc_file.shapes_with_label("person")
    out: List[HeadPersonMatch] = []
    for shape in qc_file.shapes:
        if shape.label == "head":
            out.append(match_head_to_persons(shape, persons, cfg))
    return out


# ---------------------------------------------------------------------------
# internal scoring helpers
# ---------------------------------------------------------------------------


def _area_ratio_score(ratio: float, ideal: float, hi: float) -> float:
    """Triangle score peaking at ``ideal`` and falling to 0 at 0 and ``hi``.

    Ratios above ``hi`` (already filtered) clip to ~0.
    """
    if ratio <= 0:
        return 0.0
    if ratio >= hi:
        return 0.0
    if ratio <= ideal:
        return ratio / ideal if ideal > 0 else 1.0
    return max(0.0, (hi - ratio) / (hi - ideal)) if hi > ideal else 1.0


def _upper_body_position_score(head_y_rel: float) -> float:
    """Score peaking around head_y_rel in [0.10, 0.30], falling off."""
    if head_y_rel < 0:
        return 0.0
    if 0.10 <= head_y_rel <= 0.30:
        return 1.0
    if head_y_rel < 0.10:
        return max(0.0, head_y_rel / 0.10)
    # above 0.30 → linear decay to 0 at 0.60
    return max(0.0, (0.60 - head_y_rel) / 0.30)


def _keypoint_support_score(person: QcShape) -> float:
    """Stub: a person whose group carries keypoints is a stronger target.

    We cannot see siblings here, so we return a neutral 0.5.  Real support
    is computed by the rule that has the full file context.
    """
    return 0.5
