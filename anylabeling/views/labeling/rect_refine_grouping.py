# PyQt-free module — MUST NOT import PyQt6 or any UI widget.
"""Asymmetric three-box grouping: scoring, GID merge, conflict detection.

Pure-function module.  Inputs are :class:`ShapeRefineView` records (already
deep-copied at capture); outputs are :class:`GroupingResult` discriminated
unions.  No real :class:`Shape` is ever touched here.

Geometry primitives are reused from
:mod:`anylabeling.views.labeling.widgets.inspector.quality.geometry` (§29.8).
The QA ``matching.py`` is *not* imported: its ``QcShape`` is a disk/report
model and its ``top_n_candidates=3`` would truncate legitimate multi-candidate
results (audit risk #10, AC-048).

Determinism contract (§29.3, AC-047): identical inputs must produce identical
member ordering.  Sort keys are total orders ending in ``shape_index`` so
there are never ties.

References:
    §29.1 pre-filter          §29.4 person downward path
    §29.2 scoring formulas    §29.5 head upward path
    §29.3 stable sort         §29.6 face upward path
    §29.7 conflict codes      §21   default parameters
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .rect_refine_types import (
    BBox,
    CandidateSource,
    ConflictCode,
    GroupingCandidate,
    Point,
    RelationGraph,
    RelationKind,
    ShapeId,
    ShapeRefineView,
    is_valid_gid,
)
from .widgets.inspector.quality import geometry as geom

# ---------------------------------------------------------------------------
# §21 default parameters — hardcoded for stage 1+2.
#
# Stage 5 will inject these from the ``rect_refine`` yaml block.  Hardcoding
# now keeps the pure-logic layer free of config plumbing and lets the tests
# assert exact numeric outcomes (AC-045/046/047).
# ---------------------------------------------------------------------------

_FACE_TO_HEAD_DEFAULTS: Dict[str, float] = {
    "min_x_overlap": 0.25,
    "min_y_overlap": 0.15,
    "max_area_ratio": 0.85,
    "search_expand": 0.15,
    "max_overflow": 0.30,
    # §29.2 face→head weights.
    "w_containment": 0.35,
    "w_center": 0.20,
    "w_area": 0.20,
    "w_iou": 0.25,
    # §29.2 face→head triangle area-ratio score parameters.
    "area_ideal": 0.30,
    "area_high": 0.85,
}

_HEAD_TO_PERSON_DEFAULTS: Dict[str, float] = {
    "min_x_overlap": 0.15,
    "max_head_y_rel": 0.60,
    "max_area_ratio": 0.40,
    "search_expand": 0.20,
    # §29.2 head→person weights.
    "w_containment": 0.30,
    "w_upper": 0.25,
    "w_x_overlap": 0.20,
    "w_area": 0.15,
    "w_center": 0.10,
    # §29.2 head→person triangle area-ratio score parameters.
    "area_ideal": 0.08,
    "area_high": 0.40,
    # §29.2 head_y_rel upper-score band edges.
    "upper_low": 0.10,
    "upper_ideal_lo": 0.10,
    "upper_ideal_hi": 0.30,
    "upper_high": 0.60,
}

_GENERAL_DEFAULTS: Dict[str, float] = {
    # §21.3
    "min_accept_score": 0.55,
    "ambiguous_top_gap": 0.12,
    "alignment_hint_px": 3.0,
}

DEFAULTS: Dict[str, Any] = {
    "face_to_head": dict(_FACE_TO_HEAD_DEFAULTS),
    "head_to_person": dict(_HEAD_TO_PERSON_DEFAULTS),
    "general": dict(_GENERAL_DEFAULTS),
}

#: Recognised anchor labels (§29.1 pre-filter set).
ANCHOR_LABELS = ("person", "head", "face")

_EPS = 1e-9


# ---------------------------------------------------------------------------
# §29.2 sub-scores
# ---------------------------------------------------------------------------


def triangle_area_score(ratio: float, ideal: float, high: float) -> float:
    """Triangle area-ratio score (§29.2).

    ::
        ratio <= 0 or ratio >= high  -> 0
        0 < ratio <= ideal           -> ratio / ideal
        ideal < ratio < high         -> (high - ratio) / (high - ideal)
    """
    if ratio <= 0.0 or ratio >= high:
        return 0.0
    if ratio <= ideal:
        return ratio / ideal if ideal > 0 else 0.0
    denom = high - ideal
    return (high - ratio) / denom if denom > 0 else 0.0


def upper_body_score(
    head_y_rel: float,
    ideal_lo: float = 0.10,
    ideal_hi: float = 0.30,
    high: float = 0.60,
) -> float:
    """``head→person`` upper-position score (§29.2).

    ::
        ideal_lo <= head_y_rel <= ideal_hi  -> 1.0
        0 <= head_y_rel < ideal_lo          -> head_y_rel / ideal_lo
        ideal_hi < head_y_rel < high        -> (high - head_y_rel) / (high - ideal_hi)
        otherwise                           -> 0.0
    """
    if ideal_lo <= head_y_rel <= ideal_hi:
        return 1.0
    if 0.0 <= head_y_rel < ideal_lo:
        return head_y_rel / ideal_lo if ideal_lo > 0 else 0.0
    if ideal_hi < head_y_rel < high:
        denom = high - ideal_hi
        return (high - head_y_rel) / denom if denom > 0 else 0.0
    return 0.0


def _head_y_rel(head: ShapeRefineView, person_bbox: BBox) -> float:
    """``(head_center_y - person.y_min) / person.height`` (§29.2)."""
    h_center_y = (head.bbox[1] + head.bbox[3]) / 2.0
    p_height = person_bbox[3] - person_bbox[1]
    if p_height <= _EPS:
        return 1.0  # degenerate person → falls outside any ideal band
    return (h_center_y - person_bbox[1]) / p_height


# ---------------------------------------------------------------------------
# Hard filters (§21.1 / §21.2)
# ---------------------------------------------------------------------------


def _hard_filter_face_to_head(
    face: ShapeRefineView, head: ShapeRefineView, cfg: Dict[str, float]
) -> bool:
    """§21.1 face→head hard filter.

    Uses minimum x/y overlap, maximum face/head area ratio and maximum face
    overflow.  A candidate failing this filter never enters the scored set,
    even if its weighted score would otherwise clear ``min_accept_score``.
    """
    fb = face.bbox
    hb = head.bbox
    if fb is None or hb is None:
        return False
    if geom.x_overlap_ratio(fb, hb) < cfg["min_x_overlap"]:
        return False
    if geom.y_overlap_ratio(fb, hb) < cfg["min_y_overlap"]:
        return False
    # area_ratio guards against zero denominators internally.
    if geom.area_ratio(fb, hb) > cfg["max_area_ratio"]:
        return False
    if geom.overflow_ratio(fb, hb) > cfg["max_overflow"]:
        return False
    return True


def _hard_filter_head_to_person(
    head: ShapeRefineView, person: ShapeRefineView, cfg: Dict[str, float]
) -> bool:
    """§21.2 head→person hard filter.

    Uses minimum x overlap, ``head_y_rel`` upper bound and maximum head/person
    area ratio.
    """
    hb = head.bbox
    pb = person.bbox
    if hb is None or pb is None:
        return False
    if geom.x_overlap_ratio(hb, pb) < cfg["min_x_overlap"]:
        return False
    if _head_y_rel(head, pb) > cfg["max_head_y_rel"]:
        return False
    if geom.area_ratio(hb, pb) > cfg["max_area_ratio"]:
        return False
    return True


# ---------------------------------------------------------------------------
# §29.2 scoring
# ---------------------------------------------------------------------------


def _score_face_to_head(
    face: ShapeRefineView, head: ShapeRefineView, cfg: Dict[str, float]
) -> Tuple[float, Dict[str, float]]:
    """Aggregate face→head score + per-metric breakdown."""
    fb = face.bbox
    hb = head.bbox
    containment = geom.containment_ratio(fb, hb)
    center_align = 1.0 - min(1.0, geom.center_distance_norm(fb, hb))
    area_score = triangle_area_score(
        geom.area_ratio(fb, hb), cfg["area_ideal"], cfg["area_high"]
    )
    iou_val = geom.iou(fb, hb)
    score = (
        cfg["w_containment"] * containment
        + cfg["w_center"] * center_align
        + cfg["w_area"] * area_score
        + cfg["w_iou"] * iou_val
    )
    metrics = {
        "containment": containment,
        "center_alignment": center_align,
        "area_score": area_score,
        "iou": iou_val,
        "area_ratio": geom.area_ratio(fb, hb),
        "overflow": geom.overflow_ratio(fb, hb),
    }
    return score, metrics


def _score_head_to_person(
    head: ShapeRefineView, person: ShapeRefineView, cfg: Dict[str, float]
) -> Tuple[float, Dict[str, float]]:
    """Aggregate head→person score + per-metric breakdown."""
    hb = head.bbox
    pb = person.bbox
    containment = geom.containment_ratio(hb, pb)
    y_rel = _head_y_rel(head, pb)
    upper = upper_body_score(
        y_rel,
        ideal_lo=cfg["upper_ideal_lo"],
        ideal_hi=cfg["upper_ideal_hi"],
        high=cfg["upper_high"],
    )
    x_overlap = geom.x_overlap_ratio(hb, pb)
    area_score = triangle_area_score(
        geom.area_ratio(hb, pb), cfg["area_ideal"], cfg["area_high"]
    )
    center_align = 1.0 - min(1.0, geom.center_distance_norm(hb, pb))
    score = (
        cfg["w_containment"] * containment
        + cfg["w_upper"] * upper
        + cfg["w_x_overlap"] * x_overlap
        + cfg["w_area"] * area_score
        + cfg["w_center"] * center_align
    )
    metrics = {
        "containment": containment,
        "upper_score": upper,
        "x_overlap": x_overlap,
        "area_score": area_score,
        "center_alignment": center_align,
        "head_y_rel": y_rel,
        "area_ratio": geom.area_ratio(hb, pb),
    }
    return score, metrics


# ---------------------------------------------------------------------------
# Candidate enumeration + stable sort (§29.3)
# ---------------------------------------------------------------------------


def _bbox_area(b: Optional[BBox]) -> float:
    if b is None:
        return 0.0
    return geom.bbox_area(b)


def _center_distance(a: Optional[BBox], b: Optional[BBox]) -> float:
    """Raw (un-normalised) center distance for tie-break sorting."""
    if a is None or b is None:
        return float("inf")
    ca = geom.bbox_center(a)
    cb = geom.bbox_center(b)
    return math.hypot(ca[0] - cb[0], ca[1] - cb[1])


def _sort_key_for(
    candidate_view: ShapeRefineView,
    anchor_bbox: Optional[BBox],
    score: float,
    containment: float,
    relation: RelationKind,
    cfg: Dict[str, float],
) -> Tuple[float, ...]:
    """Build the §29.3 total-order ascending sort key.

    §29.3 specifies descending score, descending containment, ascending center
    distance, ascending area, ascending shape_index.  We negate the
    descending fields so a single ``sorted(key=...)`` call yields the spec
    order; the trailing ``shape_index`` is unique, guaranteeing no ties
    (AC-047).
    """
    return (
        -score,
        -containment,
        _center_distance(candidate_view.bbox, anchor_bbox),
        _bbox_area(candidate_view.bbox),
        float(candidate_view.shape_index),
    )


def _enumerate_scored(
    anchor: ShapeRefineView,
    pool: Sequence[ShapeRefineView],
    relation: RelationKind,
    hard_filter: Callable,
    scorer: Callable,
    cfg: Dict[str, float],
    general: Dict[str, float],
) -> List[GroupingCandidate]:
    """Run hard-filter + score over ``pool`` and return *all* survivors.

    No ``top_n`` truncation (AC-048): every candidate that passes the hard
    filter is scored and kept; ``min_accept_score`` is recorded on each
    candidate but the caller decides whether to admit.
    """
    scored: List[Tuple[float, GroupingCandidate]] = []
    for view in pool:
        if view.shape_id == anchor.shape_id:
            continue
        passed = hard_filter(view, anchor, cfg)
        if not passed:
            continue
        score, metrics = scorer(view, anchor, cfg)
        containment = metrics.get("containment", 0.0)
        sort_key = _sort_key_for(
            view, anchor.bbox, score, containment, relation, cfg
        )
        scored.append(
            (
                score,
                GroupingCandidate(
                    target_id=view.shape_id,
                    relation=relation,
                    source=CandidateSource.GEOMETRY,
                    score=score,
                    passed_hard_filter=True,
                    meets_accept_score=score >= general["min_accept_score"],
                    top_gap=0.0,  # filled in after sorting
                    sort_key=sort_key,
                    metrics=metrics,
                ),
            )
        )
    # Stable sort by the total-order key (score desc → … → shape_index asc).
    scored.sort(key=lambda pair: pair[1].sort_key)
    # Fill top_gap relative to the top-1 (which is index 0 after sort).
    result: List[GroupingCandidate] = []
    top_score = scored[0][0] if scored else 0.0
    for _score, cand in scored:
        gap = top_score - cand.score
        result.append(
            GroupingCandidate(
                target_id=cand.target_id,
                relation=cand.relation,
                source=cand.source,
                score=cand.score,
                passed_hard_filter=cand.passed_hard_filter,
                meets_accept_score=cand.meets_accept_score,
                top_gap=gap,
                sort_key=cand.sort_key,
                metrics=cand.metrics,
            )
        )
    return result


def _accepted(candidates: List[GroupingCandidate]) -> List[GroupingCandidate]:
    """Keep only candidates whose score ≥ ``min_accept_score``."""
    return [c for c in candidates if c.meets_accept_score]


# ---------------------------------------------------------------------------
# §29.1 pre-filter
# ---------------------------------------------------------------------------


def _is_refinable(view: ShapeRefineView) -> bool:
    """Eligible for the inference pool (§29.1)."""
    return (
        view.label in ANCHOR_LABELS
        and view.shape_type == "rectangle"
        and view.bbox is not None
        and _bbox_area(view.bbox) > _EPS
    )


def _degenerate_bbox(view: ShapeRefineView) -> bool:
    """Anchor bbox is invalid (zero area or missing) but anchor is retained."""
    return view.bbox is None or _bbox_area(view.bbox) <= _EPS


# ---------------------------------------------------------------------------
# GID collection helpers (§29.4 step 2)
# ---------------------------------------------------------------------------


def _collect_same_gid(
    anchor: ShapeRefineView,
    pool: Sequence[ShapeRefineView],
    label: str,
) -> List[ShapeRefineView]:
    """All pool entries sharing the anchor's *valid* GID with the given label."""
    gid = anchor.group_id
    if not is_valid_gid(gid):
        return []
    return [
        v
        for v in pool
        if v.label == label
        and v.shape_id != anchor.shape_id
        and is_valid_gid(v.group_id)
        and v.group_id == gid
    ]


# ---------------------------------------------------------------------------
# Result type (discriminated union, §27.2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupingResult:
    """Discriminated union returned by :func:`infer` (§27.2).

    ``kind`` is ``"READY"`` or ``"CONFLICT"``.  Missing members, upward
    ambiguity and pure-geometry multi-candidates are ``READY`` with optional
    ``nonblocking_message``; only the five §29.7 codes produce ``CONFLICT``.
    """

    kind: str
    # READY payload.
    members: Tuple[ShapeRefineView, ...] = ()
    relation_graph: RelationGraph = field(default_factory=RelationGraph)
    provenance: Dict[ShapeId, CandidateSource] = field(default_factory=dict)
    nonblocking_message: Optional[str] = None
    # CONFLICT payload.
    conflict_code: Optional[ConflictCode] = None
    conflict_args: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_ready(self) -> bool:
        return self.kind == "READY"

    @property
    def is_conflict(self) -> bool:
        return self.kind == "CONFLICT"

    @classmethod
    def ready(
        cls,
        members: Sequence[ShapeRefineView],
        relation_graph: RelationGraph,
        provenance: Dict[ShapeId, CandidateSource],
        nonblocking_message: Optional[str] = None,
    ) -> "GroupingResult":
        return cls(
            kind="READY",
            members=tuple(members),
            relation_graph=relation_graph,
            provenance=dict(provenance),
            nonblocking_message=nonblocking_message,
        )

    @classmethod
    def conflict(cls, code: ConflictCode, **args: Any) -> "GroupingResult":
        return cls(
            kind="CONFLICT", conflict_code=code, conflict_args=dict(args)
        )


# ---------------------------------------------------------------------------
# Person → downward inference (§29.4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FaceBundle:
    """Internal aggregation of §29.4 steps 5–7 face-collection results."""

    accepted_face_ids: List[ShapeId]
    accepted_face_views: Dict[ShapeId, ShapeRefineView]
    face_to_head: Dict[ShapeId, Optional[ShapeId]]
    head_to_face_candidates: Dict[ShapeId, List[GroupingCandidate]]
    conflict: Optional[GroupingResult] = None


def _collect_faces_for_heads(
    accepted_head_views: Dict[ShapeId, ShapeRefineView],
    face_pool: Sequence[ShapeRefineView],
    gid_faces: List[ShapeRefineView],
    f2h_cfg: Dict[str, float],
    general: Dict[str, float],
) -> _FaceBundle:
    """Run §29.4 steps 5–7: enumerate faces per head, merge GID face, resolve
    face_to_head ownership.  Returns a :class:`_FaceBundle`; ``conflict`` is
    set when §29.4 step 6 finds a GID face geometry failure.
    """
    head_to_face_candidates: Dict[ShapeId, List[GroupingCandidate]] = {}
    accepted_face_ids: List[ShapeId] = []
    accepted_face_views: Dict[ShapeId, ShapeRefineView] = {}

    # Step 5 — enumerate + dedupe.
    for head_id, head_view in accepted_head_views.items():
        cands = _enumerate_scored(
            head_view,
            face_pool,
            RelationKind.FACE_OF_HEAD,
            _hard_filter_face_to_head,
            _score_face_to_head,
            f2h_cfg,
            general,
        )
        accepted = _accepted(cands)
        head_to_face_candidates[head_id] = accepted
        for c in accepted:
            if c.target_id not in accepted_face_views:
                fv = next(
                    (v for v in face_pool if v.shape_id == c.target_id),
                    None,
                )
                if fv is not None:
                    accepted_face_views[c.target_id] = fv
                    accepted_face_ids.append(c.target_id)

    # Step 6 — merge the (single) GID face.
    gid_face_conflict = _merge_gid_face(
        gid_faces,
        accepted_head_views,
        head_to_face_candidates,
        f2h_cfg,
        general,
        face_pool,
    )
    if gid_face_conflict is not None:
        return _FaceBundle(
            accepted_face_ids=accepted_face_ids,
            accepted_face_views=accepted_face_views,
            face_to_head={},
            head_to_face_candidates=head_to_face_candidates,
            conflict=gid_face_conflict,
        )

    # A geometry-verified GID face must be included.
    for gf in gid_faces:
        if gf.shape_id not in accepted_face_views:
            accepted_face_views[gf.shape_id] = gf
            accepted_face_ids.append(gf.shape_id)

    # Step 7 — face_to_head ownership; ambiguous → None.
    face_to_head: Dict[ShapeId, Optional[ShapeId]] = _resolve_face_owners(
        accepted_face_ids, head_to_face_candidates, general
    )
    return _FaceBundle(
        accepted_face_ids=accepted_face_ids,
        accepted_face_views=accepted_face_views,
        face_to_head=face_to_head,
        head_to_face_candidates=head_to_face_candidates,
    )


def _resolve_face_owners(
    accepted_face_ids: List[ShapeId],
    head_to_face_candidates: Dict[ShapeId, List[GroupingCandidate]],
    general: Dict[str, float],
) -> Dict[ShapeId, Optional[ShapeId]]:
    """§29.4 step 7: map each face to its owning head, or ``None`` if the
    top-1/top-2 gap is below ``ambiguous_top_gap``."""
    face_to_head: Dict[ShapeId, Optional[ShapeId]] = {}
    for face_id in accepted_face_ids:
        owners = [
            hid
            for hid, cands in head_to_face_candidates.items()
            if any(c.target_id == face_id for c in cands)
        ]
        if len(owners) == 1:
            face_to_head[face_id] = owners[0]
            continue
        # Multiple heads own this face → check top1/top2 gap per head.
        scored_pairs: List[Tuple[float, ShapeId]] = []
        for hid in owners:
            cands = head_to_face_candidates[hid]
            top = next((c for c in cands if c.target_id == face_id), None)
            if top is not None:
                scored_pairs.append((top.score, hid))
        scored_pairs.sort(key=lambda p: -p[0])
        if len(scored_pairs) >= 2:
            gap = scored_pairs[0][0] - scored_pairs[1][0]
            if gap >= general["ambiguous_top_gap"]:
                face_to_head[face_id] = scored_pairs[0][1]
            else:
                face_to_head[face_id] = None  # ambiguous
        else:
            face_to_head[face_id] = scored_pairs[0][1]
    return face_to_head


def _infer_from_person(
    anchor: ShapeRefineView,
    pool: Sequence[ShapeRefineView],
    config: Dict[str, Any],
) -> GroupingResult:
    """§29.4 full downward inference.

    Steps mirror the spec exactly; GID conflicts short-circuit to
    ``CONFLICT`` and prevent workgroup construction.
    """
    f2h_cfg = config["face_to_head"]
    h2p_cfg = config["head_to_person"]
    general = config["general"]

    # Degenerate anchor: keep anchor only, no inference (§29.1 last paragraph).
    if _degenerate_bbox(anchor):
        return _build_ready_anchor_only(anchor, "anchor_degenerate_geometry")

    # §29.4 step 2 — GID path.
    gid_heads = _collect_same_gid(anchor, pool, "head")
    gid_faces = _collect_same_gid(anchor, pool, "face")
    if len(gid_heads) > 1:
        return GroupingResult.conflict(
            ConflictCode.DUPLICATE_GID_HEAD,
            gid=anchor.group_id,
            count=len(gid_heads),
        )
    if len(gid_faces) > 1:
        return GroupingResult.conflict(
            ConflictCode.DUPLICATE_GID_FACE,
            gid=anchor.group_id,
            count=len(gid_faces),
        )

    # §29.4 step 3 — score every head against the anchor person.
    head_pool = [v for v in pool if v.label == "head"]
    head_candidates = _enumerate_scored(
        anchor,
        head_pool,
        RelationKind.HEAD_OF_PERSON,
        _hard_filter_head_to_person,
        _score_head_to_person,
        h2p_cfg,
        general,
    )
    accepted_heads = _accepted(head_candidates)

    # §29.4 step 4 — merge the (single) GID head.
    gid_head_conflict = _merge_gid_head(
        gid_heads, head_candidates, accepted_heads, h2p_cfg, general
    )
    if gid_head_conflict is not None:
        return gid_head_conflict

    # Build per-head index for face search.
    accepted_head_views: Dict[ShapeId, ShapeRefineView] = {
        h.shape_id: h
        for h in head_pool
        if any(c.target_id == h.shape_id for c in accepted_heads)
    }
    # Include a GID head that passed merge even if not in head_pool enumeration
    # (it always is, because the pool is the same set; kept defensive).
    for gh in gid_heads:
        accepted_head_views.setdefault(gh.shape_id, gh)

    # §29.4 steps 5–7 — collect faces per head, merge GID face, resolve
    # face_to_head ownership.  Extracted to keep this function's complexity
    # within the flake8 limit.
    face_pool = [v for v in pool if v.label == "face"]
    face_bundle = _collect_faces_for_heads(
        accepted_head_views,
        face_pool,
        gid_faces,
        f2h_cfg,
        general,
    )
    if face_bundle.conflict is not None:
        return face_bundle.conflict
    accepted_face_ids = face_bundle.accepted_face_ids
    accepted_face_views = face_bundle.accepted_face_views
    face_to_head = face_bundle.face_to_head
    head_to_face_candidates = face_bundle.head_to_face_candidates

    # Build relation graph + provenance.
    person_id = anchor.shape_id
    head_ids = list(accepted_head_views.keys())
    head_to_faces: Dict[ShapeId, List[ShapeId]] = {}
    for head_id in head_ids:
        owned = [
            fid
            for fid, owner in face_to_head.items()
            # A face belongs to a head if the head owns it (unique) OR the head
            # accepted it as a candidate even if ownership is ambiguous.
            if owner == head_id
            or any(
                c.target_id == fid
                for c in head_to_face_candidates.get(head_id, [])
            )
        ]
        # Dedupe preserving deterministic order (by face shape_index).
        owned = sorted(
            set(owned),
            key=lambda fid: accepted_face_views[fid].shape_index,
        )
        head_to_faces[head_id] = owned

    graph = RelationGraph(
        person_to_heads={person_id: list(head_ids)},
        head_to_faces=head_to_faces,
        head_to_person={hid: person_id for hid in head_ids},
        face_to_head=face_to_head,
    )

    # Provenance: anchor is geometry-only by convention; GID-tagged members
    # are BOTH when they also passed geometry; pure-geometry members are
    # GEOMETRY.
    provenance: Dict[ShapeId, CandidateSource] = {
        person_id: CandidateSource.GEOMETRY
    }
    gid_head_ids = {h.shape_id for h in gid_heads}
    gid_face_ids = {f.shape_id for f in gid_faces}
    for hid in head_ids:
        provenance[hid] = (
            CandidateSource.BOTH
            if hid in gid_head_ids
            else CandidateSource.GEOMETRY
        )
    for fid in accepted_face_ids:
        provenance[fid] = (
            CandidateSource.BOTH
            if fid in gid_face_ids
            else CandidateSource.GEOMETRY
        )

    members = (
        [anchor]
        + [accepted_head_views[hid] for hid in head_ids]
        + [accepted_face_views[fid] for fid in accepted_face_ids]
    )

    return GroupingResult.ready(members, graph, provenance)


def _merge_gid_head(
    gid_heads: List[ShapeRefineView],
    head_candidates: List[GroupingCandidate],
    accepted_heads: List[GroupingCandidate],
    h2p_cfg: Dict[str, float],
    general: Dict[str, float],
) -> Optional[GroupingResult]:
    """§29.4 step 4 — GID head merge + conflict detection.

    Returns a ``CONFLICT`` result if a GID conflict is found, else ``None``
    (the GID head is implicitly accepted via ``accepted_heads``).
    """
    if not gid_heads:
        return None
    gid_head = gid_heads[0]

    # GID head must pass the person hard filter.
    passes_hard = any(
        c.target_id == gid_head.shape_id for c in head_candidates
    )
    if not passes_hard:
        return GroupingResult.conflict(
            ConflictCode.GID_HEAD_GEOMETRY_INVALID,
            head_id=gid_head.shape_id,
        )

    # If GID head is already accepted (score ≥ min_accept_score), nothing more
    # to do — it stays in accepted_heads.
    gid_accepted = any(
        c.target_id == gid_head.shape_id for c in accepted_heads
    )
    if gid_accepted:
        return None

    # GID head passed hard filter but score < min_accept_score.  Check whether
    # another head is clearly better (gap ≥ ambiguous_top_gap) → conflict.
    # If no other accepted head exists OR gap < threshold → treat as ambiguity,
    # keep nothing extra, no conflict (§29.4 step 4 last bullet).
    if accepted_heads:
        top = accepted_heads[0]
        gid_cand = next(
            (c for c in head_candidates if c.target_id == gid_head.shape_id),
            None,
        )
        gid_score = gid_cand.score if gid_cand is not None else 0.0
        gap = top.score - gid_score
        if gap >= general["ambiguous_top_gap"]:
            return GroupingResult.conflict(
                ConflictCode.GID_HEAD_DISAGREES_WITH_GEOMETRY,
                gid_head_score=gid_score,
                top_score=top.score,
                gap=gap,
            )
    # Gap < threshold or no other accepted head → ambiguity, no conflict.
    return None


def _merge_gid_face(
    gid_faces: List[ShapeRefineView],
    accepted_head_views: Dict[ShapeId, ShapeRefineView],
    head_to_face_candidates: Dict[ShapeId, List[GroupingCandidate]],
    f2h_cfg: Dict[str, float],
    general: Dict[str, float],
    face_pool: Sequence[ShapeRefineView],
) -> Optional[GroupingResult]:
    """§29.4 step 6 — GID face merge + conflict detection."""
    if not gid_faces:
        return None
    gid_face = gid_faces[0]

    if not accepted_head_views:
        # §29.4 step 6 last bullet: no accepted head → GID face must NOT bypass
        # geometry; return non-blocking (no conflict) by leaving face out.
        return None

    # The GID face must pass hard filter against at least one accepted head.
    verified = False
    for head_view in accepted_head_views.values():
        if _hard_filter_face_to_head(gid_face, head_view, f2h_cfg):
            verified = True
            break
    if not verified:
        return GroupingResult.conflict(
            ConflictCode.GID_FACE_GEOMETRY_INVALID,
            face_id=gid_face.shape_id,
        )
    return None


def _build_ready_anchor_only(
    anchor: ShapeRefineView, message_key: Optional[str]
) -> GroupingResult:
    """Return a READY result containing only the anchor (§29.4 step 8)."""
    graph = RelationGraph()
    return GroupingResult.ready(
        members=[anchor],
        relation_graph=graph,
        provenance={anchor.shape_id: CandidateSource.GEOMETRY},
        nonblocking_message=message_key,
    )


# ---------------------------------------------------------------------------
# Head → upward inference (§29.5)
# ---------------------------------------------------------------------------


def _infer_from_head(
    anchor: ShapeRefineView,
    pool: Sequence[ShapeRefineView],
    config: Dict[str, Any],
) -> GroupingResult:
    """§29.5 head→person upward-only inference."""
    h2p_cfg = config["head_to_person"]
    general = config["general"]

    if _degenerate_bbox(anchor):
        return _build_ready_anchor_only(anchor, "anchor_degenerate_geometry")

    person_pool = [v for v in pool if v.label == "person"]
    person_candidates = _enumerate_scored(
        anchor,
        person_pool,
        RelationKind.PERSON_OF_HEAD,
        # Hard filter is symmetric in args: (candidate=person, outer=anchor)
        # but _hard_filter_head_to_person expects (head, person).  We adapt:
        _hard_filter_head_to_person_swapped,
        _score_head_to_person_swapped,
        h2p_cfg,
        general,
    )
    accepted = _accepted(person_candidates)

    if not accepted:
        return _build_ready_anchor_only(anchor, "head_no_reliable_person")

    top = accepted[0]
    if len(accepted) >= 2:
        gap = top.score - accepted[1].score
        if gap < general["ambiguous_top_gap"]:
            # §29.5 step 4: upward ambiguity → do not auto-join any person.
            return _build_ready_anchor_only(
                anchor, "head_upward_ambiguous_person"
            )

    # Unique reliable top-1 → join this person.
    person_view = next(v for v in person_pool if v.shape_id == top.target_id)
    graph = RelationGraph(
        head_to_person={anchor.shape_id: person_view.shape_id},
        person_to_heads={person_view.shape_id: [anchor.shape_id]},
    )
    provenance = {
        anchor.shape_id: CandidateSource.GEOMETRY,
        person_view.shape_id: CandidateSource.GEOMETRY,
    }
    return GroupingResult.ready(
        members=[anchor, person_view],
        relation_graph=graph,
        provenance=provenance,
    )


def _hard_filter_head_to_person_swapped(
    person: ShapeRefineView, head: ShapeRefineView, cfg: Dict[str, float]
) -> bool:
    """Adapter so _enumerate_scored can score persons *for* a head anchor.

    ``_enumerate_scored`` calls ``hard_filter(candidate, anchor, cfg)``.  When
    the anchor is a head and candidates are persons, we swap arguments back to
    the canonical ``(head, person)`` signature.
    """
    return _hard_filter_head_to_person(head, person, cfg)


def _score_head_to_person_swapped(
    person: ShapeRefineView, head: ShapeRefineView, cfg: Dict[str, float]
) -> Tuple[float, Dict[str, float]]:
    """Score adapter mirroring the hard-filter swap above."""
    return _score_head_to_person(head, person, cfg)


# ---------------------------------------------------------------------------
# Face → upward chain inference (§29.6)
# ---------------------------------------------------------------------------


def _infer_from_face(
    anchor: ShapeRefineView,
    pool: Sequence[ShapeRefineView],
    config: Dict[str, Any],
) -> GroupingResult:
    """§29.6 face→head→person upward chain inference."""
    f2h_cfg = config["face_to_head"]
    general = config["general"]

    if _degenerate_bbox(anchor):
        return _build_ready_anchor_only(anchor, "anchor_degenerate_geometry")

    # Step 2 — face→head.
    head_pool = [v for v in pool if v.label == "head"]
    head_candidates = _enumerate_scored(
        anchor,
        head_pool,
        # Relation from the head's perspective once we ascend.
        RelationKind.FACE_OF_HEAD,
        _hard_filter_face_to_head_swapped,
        _score_face_to_head_swapped,
        f2h_cfg,
        general,
    )
    accepted_heads = _accepted(head_candidates)

    if not accepted_heads:
        return _build_ready_anchor_only(anchor, "face_no_reliable_head")

    top_head = accepted_heads[0]
    if len(accepted_heads) >= 2:
        gap = top_head.score - accepted_heads[1].score
        if gap < general["ambiguous_top_gap"]:
            return _build_ready_anchor_only(
                anchor, "face_upward_ambiguous_head"
            )

    head_view = next(v for v in head_pool if v.shape_id == top_head.target_id)

    # Step 3 — head→person (reuse §29.5 logic on the joined head).
    person_result = _infer_from_head(head_view, pool, config)
    if not person_result.is_ready:
        # Should not happen (head inference never returns CONFLICT), but guard.
        return _build_ready_anchor_only(anchor, "face_upward_person_failed")

    # If the head could not reliably join a person, return face+head only.
    member_ids = {m.shape_id for m in person_result.members}
    if head_view.shape_id not in member_ids or len(person_result.members) == 1:
        graph = RelationGraph(
            face_to_head={anchor.shape_id: head_view.shape_id},
            head_to_faces={head_view.shape_id: [anchor.shape_id]},
        )
        provenance = {
            anchor.shape_id: CandidateSource.GEOMETRY,
            head_view.shape_id: CandidateSource.GEOMETRY,
        }
        return GroupingResult.ready(
            members=[anchor, head_view],
            relation_graph=graph,
            provenance=provenance,
            nonblocking_message=person_result.nonblocking_message,
        )

    # Full chain: face → head → person.  Merge graphs.
    person_view = person_result.members[0]
    if person_view.shape_id == head_view.shape_id:
        person_view = person_result.members[1]
    graph = RelationGraph(
        person_to_heads={person_view.shape_id: [head_view.shape_id]},
        head_to_faces={head_view.shape_id: [anchor.shape_id]},
        head_to_person={head_view.shape_id: person_view.shape_id},
        face_to_head={anchor.shape_id: head_view.shape_id},
    )
    provenance = {
        anchor.shape_id: CandidateSource.GEOMETRY,
        head_view.shape_id: CandidateSource.GEOMETRY,
        person_view.shape_id: CandidateSource.GEOMETRY,
    }
    return GroupingResult.ready(
        members=[anchor, head_view, person_view],
        relation_graph=graph,
        provenance=provenance,
    )


def _hard_filter_face_to_head_swapped(
    head: ShapeRefineView, face: ShapeRefineView, cfg: Dict[str, float]
) -> bool:
    """Adapter: anchor=face, candidate=head → canonical (face, head)."""
    return _hard_filter_face_to_head(face, head, cfg)


def _score_face_to_head_swapped(
    head: ShapeRefineView, face: ShapeRefineView, cfg: Dict[str, float]
) -> Tuple[float, Dict[str, float]]:
    return _score_face_to_head(face, head, cfg)


# ---------------------------------------------------------------------------
# Public entry point (§27.2)
# ---------------------------------------------------------------------------


def infer(
    anchor: ShapeRefineView,
    all_shapes: Sequence[ShapeRefineView],
    config: Dict[str, Any] = DEFAULTS,
) -> GroupingResult:
    """Run asymmetric three-box inference for one anchor (§27.2).

    Args:
        anchor: The user's formally-selected Shape view.  Its label drives
            the inference direction; its identity is never replaced
            (invariant §22.3 #4).
        all_shapes: Read-only views of every ``person/head/face rectangle``
            on the current image.  The pre-filter (§29.1) is applied here so
            callers may pass the full canvas shape list.
        config: Threshold/weight configuration.  Defaults to :data:`DEFAULTS`
            (§21 values).

    Returns:
        A :class:`GroupingResult` discriminated union.  ``READY`` always
        contains at least the anchor (§29.4 step 8).
    """
    pool = [v for v in all_shapes if _is_refinable(v)]
    # Anchor must be retained even if degenerate; ensure it is in the pool
    # for self-exclusion checks.  We do NOT require the anchor to pass the
    # refinable filter — degenerate anchor is handled inside each branch.
    if anchor.label == "person":
        return _infer_from_person(anchor, pool, config)
    if anchor.label == "head":
        return _infer_from_head(anchor, pool, config)
    if anchor.label == "face":
        return _infer_from_face(anchor, pool, config)
    # Non-anchor label: return anchor-only READY (caller should pre-filter).
    return _build_ready_anchor_only(anchor, "anchor_not_three_box_label")


__all__ = [
    "DEFAULTS",
    "ANCHOR_LABELS",
    "GroupingResult",
    "infer",
    "triangle_area_score",
    "upper_body_score",
]
