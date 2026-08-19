"""Persistent task locators and conservative reconciliation.

A :term:`locator` is a JSON snapshot of the intended source content of
one atomic task: kind, normalized group id, member ordinals, labels,
shape types, quantized geometry fingerprints, and image dimensions.
Locators are deliberately separate from runtime shape ids, which are
reassigned after every image load.

Rehydration climbs a conservative ladder and never transfers progress to
an ambiguous target.  All geometry quantization goes through
:mod:`virtual_review.serialization` so build-time and runtime
signatures agree exactly.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

from .models import (
    VirtualShapeView,
    VirtualTask,
    VirtualTaskCriteria,
)
from .task_builder import build_virtual_tasks
from .queue_models import AtomicTaskRecord, BindingState, TaskFreshness
from .queue_models import SourceFileRecord, TaskOutcome
from .serialization import (
    geometry_fingerprint,
    locator_signature,
    member_snapshot_dict,
    points_to_bbox,
    quantize_bbox,
    quantize_points,
    resolve_relative_path,
)

# Shared reconciliation constants: the confidence threshold and winner
# margin are hard policy, not user-tunable values.
MATCH_CONFIDENCE_THRESHOLD = 0.65
MATCH_WINNER_MARGIN = 0.15


@dataclass(frozen=True)
class AnnotationScan:
    """Tolerant result of reading one annotation JSON file."""

    path: str
    shapes: tuple[dict, ...] = ()
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    source_signature: Optional[str] = None
    error: Optional[str] = None  # None | "missing" | "parse"

    @property
    def ok(self) -> bool:
        """Return whether the file was read and parsed successfully."""

        return self.error is None


def source_signature_of(data: bytes) -> str:
    """Return the fast content signature of annotation bytes."""

    return hashlib.sha256(data).hexdigest()


def scan_annotation_file(path: str) -> AnnotationScan:
    """Read one annotation file, failing closed on missing/invalid data.

    A missing or unparseable file returns an ``AnnotationScan`` with an
    ``error`` instead of raising; callers decide whether to exclude the
    file from a draft or mark it missing during reconcile.
    """

    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return AnnotationScan(path=str(path), error="missing")
    signature = source_signature_of(data)
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return AnnotationScan(
            path=str(path), source_signature=signature, error="parse"
        )
    if not isinstance(payload, dict):
        return AnnotationScan(
            path=str(path), source_signature=signature, error="parse"
        )
    raw_shapes = payload.get("shapes")
    if not isinstance(raw_shapes, list):
        raw_shapes = []
    shapes = tuple(shape for shape in raw_shapes if isinstance(shape, dict))
    return AnnotationScan(
        path=str(path),
        shapes=shapes,
        image_width=_positive_int(payload.get("imageWidth")),
        image_height=_positive_int(payload.get("imageHeight")),
        source_signature=signature,
    )


def _positive_int(value: Any) -> Optional[int]:
    """Return a positive integer image dimension, or ``None``."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)) or value <= 0:
        return None
    return int(value)


def shape_entry(
    shape: dict, ordinal: int
) -> tuple[VirtualShapeView, tuple[tuple[float, float], ...]]:
    """Adapt one raw annotation shape into a view plus points.

    ``shape_id`` is the scan-local ordinal so that build-time and
    disk-reconcile views are reproducible; runtime callers pass their
    own ids through :func:`views_from_shape_data`.
    """

    return views_entry(
        shape_id=str(ordinal),
        label=shape.get("label"),
        shape_type=shape.get("shape_type"),
        group_id=shape.get("group_id"),
        points=shape.get("points"),
        visible=shape.get("visible", True),
    )


def views_entry(
    shape_id: str,
    label: Any,
    shape_type: Any,
    group_id: Any,
    points: Any,
    visible: Any = True,
) -> tuple[VirtualShapeView, tuple[tuple[float, float], ...]]:
    """Build one shape view plus its quantized points."""

    quantized = quantize_points(points)
    bbox = points_to_bbox(quantized)
    width = height = None
    if bbox is not None:
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
    view = VirtualShapeView(
        shape_id=shape_id,
        label="" if label is None else str(label),
        shape_type="" if shape_type is None else str(shape_type),
        group_id=group_id,
        width=width,
        height=height,
        bbox=bbox,
        base_visible=bool(visible),
    )
    return view, quantized


def views_from_annotation(
    scan: AnnotationScan,
) -> tuple[tuple[VirtualShapeView, ...], dict[str, tuple]]:
    """Return ordinal views and points for one annotation scan."""

    views: list[VirtualShapeView] = []
    points_by_id: dict[str, tuple] = {}
    for ordinal, shape in enumerate(scan.shapes):
        view, quantized = shape_entry(shape, ordinal)
        views.append(view)
        points_by_id[view.shape_id] = quantized
    return tuple(views), points_by_id


@dataclass(frozen=True)
class LiveTaskCandidate:
    """One live task candidate rebuilt from current content."""

    task: VirtualTask
    signature: Optional[str]
    member_snapshots: tuple[dict, ...]
    anchor_label: str


def _member_snapshot(
    view: VirtualShapeView,
    ordinal: int,
    points: Sequence[tuple[float, float]],
) -> dict:
    """Return the canonical member snapshot for one live member."""

    return member_snapshot_dict(
        ordinal=ordinal,
        label=view.label,
        shape_type=view.shape_type,
        normalized_group_id=view.normalized_group_id,
        bbox=view.bbox,
        point_count=len(points),
        fingerprint=geometry_fingerprint(points, view.bbox),
    )


def build_live_candidates(
    views: Sequence[VirtualShapeView],
    points_by_id: dict,
    criteria: VirtualTaskCriteria,
    ordinal_of: Optional[dict[str, int]] = None,
) -> tuple[LiveTaskCandidate, ...]:
    """Rebuild live task candidates from current shape views.

    ``ordinal_of`` maps shape ids to file ordinals; when omitted the
    position inside ``views`` is used, which matches the build-time
    ordinal assignment.
    """

    views_tuple = tuple(views)
    tasks = build_virtual_tasks(views_tuple, criteria)
    view_by_id = {view.shape_id: view for view in views_tuple}
    if ordinal_of is None:
        ordinal_of = {
            view.shape_id: index for index, view in enumerate(views_tuple)
        }
    candidates = []
    for task in tasks:
        snapshots = tuple(
            _member_snapshot(
                view_by_id[member_id],
                ordinal_of.get(member_id, 0),
                points_by_id.get(member_id, ()),
            )
            for member_id in task.member_ids
        )
        candidates.append(
            LiveTaskCandidate(
                task=task,
                signature=locator_signature({"members": snapshots}),
                member_snapshots=snapshots,
                anchor_label=(
                    view_by_id[task.anchor_id].label
                    if task.anchor_id in view_by_id
                    else ""
                ),
            )
        )
    return tuple(candidates)


def build_task_locator(
    task: VirtualTask,
    views: Sequence[VirtualShapeView],
    points_by_id: dict,
    image_width: Optional[int],
    image_height: Optional[int],
) -> dict:
    """Return the persistent locator payload for one atomic task."""

    view_by_id = {view.shape_id: view for view in views}
    ordinal_of = {view.shape_id: index for index, view in enumerate(views)}
    snapshots = tuple(
        _member_snapshot(
            view_by_id[member_id],
            ordinal_of.get(member_id, 0),
            points_by_id.get(member_id, ()),
        )
        for member_id in task.member_ids
        if member_id in view_by_id
    )
    return {
        "kind": "group" if task.group_id is not None else "single",
        "gid": task.group_id,
        "anchor_ordinal": ordinal_of.get(task.anchor_id, 0),
        "members": [dict(snapshot) for snapshot in snapshots],
        "bbox": (
            list(quantize_bbox(task.bbox)) if task.bbox is not None else None
        ),
        "image_size": [image_width, image_height],
    }


@dataclass(frozen=True)
class TaskBinding:
    """Outcome of reconciling one stored locator against live content."""

    state: BindingState
    member_ids: tuple[str, ...] = ()
    current_signature: Optional[str] = None
    confidence: float = 0.0
    runner_up: float = 0.0
    reason: str = ""
    anchor_id: Optional[str] = None


def _ordinal_id_map(live_ids_by_ordinal: Optional[dict]) -> dict:
    """Normalize an ordinal-to-id mapping to integer keys.

    Callers may pass integer or string keys; locator ordinals are
    integers after JSON round trips, so both spellings must resolve.
    """

    normalized: dict = {}
    for key, value in (live_ids_by_ordinal or {}).items():
        try:
            normalized[int(key)] = value
        except (TypeError, ValueError):
            continue
    return normalized


def _fast_path_binding(
    locator: dict,
    candidates: Sequence[LiveTaskCandidate],
    live_ids_by_ordinal: dict,
) -> Optional[TaskBinding]:
    """Verify stored ordinals and exact fingerprints for an unchanged file."""

    members = locator.get("members")
    if not isinstance(members, list):
        return None
    ordinal_map = _ordinal_id_map(live_ids_by_ordinal)
    runtime_members: list[str] = []
    for member in members:
        ordinal = member.get("ordinal")
        if not isinstance(ordinal, int):
            return None
        runtime_id = ordinal_map.get(ordinal)
        if runtime_id is None:
            return None
        runtime_members.append(runtime_id)
    wanted = frozenset(runtime_members)
    for candidate in candidates:
        if frozenset(candidate.task.member_ids) == wanted:
            return TaskBinding(
                state=BindingState.READY,
                member_ids=tuple(candidate.task.member_ids),
                current_signature=locator_signature(locator),
                confidence=1.0,
                reason="file_unchanged",
                anchor_id=candidate.task.anchor_id,
            )
    return None


def _score_candidate(locator: dict, candidate: LiveTaskCandidate) -> float:
    """Score one candidate with hard gates and soft evidence.

    Hard gates (member count and shape-type multiset equality) reject
    incompatible candidates before any soft evidence is considered, so
    no amount of geometric similarity can bind across shape types.
    """

    members = locator.get("members") or []
    snapshots = candidate.member_snapshots
    if len(members) != len(snapshots):
        return -1.0
    stored_types = sorted(str(m.get("shape_type")) for m in members)
    live_types = sorted(str(s.get("shape_type")) for s in snapshots)
    if stored_types != live_types:
        return -1.0

    stored_box = quantize_bbox(locator.get("bbox"))
    live_box = quantize_bbox(_candidate_bbox(snapshots))
    iou = 0.0
    center = 0.0
    if stored_box is not None and live_box is not None:
        iou = _bbox_iou(stored_box, live_box)
        center = _center_closeness(stored_box, live_box)
    stored_gid = locator.get("gid")
    group_evidence = 1.0 if stored_gid == snapshots[0].get("gid") else 0.0
    stored_labels = sorted(str(m.get("label")) for m in members)
    live_labels = sorted(str(s.get("label")) for s in snapshots)
    label_evidence = 1.0 if stored_labels == live_labels else 0.0
    return (
        0.55 * iou
        + 0.20 * center
        + 0.15 * group_evidence
        + 0.10 * label_evidence
    )


def _candidate_bbox(snapshots: Sequence[dict]) -> Any:
    """Return the union bbox of candidate member snapshots."""

    boxes = [
        quantize_bbox(snapshot.get("bbox"))
        for snapshot in snapshots
        if quantize_bbox(snapshot.get("bbox")) is not None
    ]
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _bbox_iou(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    """Return intersection-over-union of two axis-aligned boxes."""

    intersection_width = min(first[2], second[2]) - max(first[0], second[0])
    intersection_height = min(first[3], second[3]) - max(first[1], second[1])
    if intersection_width <= 0 or intersection_height <= 0:
        return 0.0
    intersection = intersection_width * intersection_height
    area_first = (first[2] - first[0]) * (first[3] - first[1])
    area_second = (second[2] - second[0]) * (second[3] - second[1])
    union = area_first + area_second - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def _center_closeness(
    stored: tuple[float, float, float, float],
    live: tuple[float, float, float, float],
) -> float:
    """Return normalized center closeness in ``[0, 1]``."""

    diagonal = math.hypot(stored[2] - stored[0], stored[3] - stored[1])
    if diagonal <= 0:
        return 0.0
    distance = math.hypot(
        (stored[0] + stored[2]) / 2.0 - (live[0] + live[2]) / 2.0,
        (stored[1] + stored[3]) / 2.0 - (live[1] + live[3]) / 2.0,
    )
    return 1.0 - min(1.0, distance / diagonal)


def reconcile_task_locator(
    locator: Any,
    candidates: Sequence[LiveTaskCandidate],
    file_unchanged: bool,
    live_ids_by_ordinal: Optional[dict] = None,
) -> TaskBinding:
    """Bind one stored locator to live candidates, failing closed."""

    if not isinstance(locator, dict) or not locator.get("members"):
        return TaskBinding(BindingState.ORPHANED, reason="invalid_locator")
    stored_signature = locator_signature(locator)

    if file_unchanged:
        fast = _fast_path_binding(
            locator, candidates, live_ids_by_ordinal or {}
        )
        if fast is not None:
            return fast

    # Exact normalized-group match: same group id and identical content.
    stored_gid = locator.get("gid")
    if stored_gid is not None:
        exact_group = [
            candidate
            for candidate in candidates
            if candidate.task.group_id == stored_gid
            and candidate.signature == stored_signature
        ]
        if len(exact_group) == 1:
            return TaskBinding(
                state=BindingState.CHANGED_RESOLVED,
                member_ids=tuple(exact_group[0].task.member_ids),
                current_signature=stored_signature,
                confidence=1.0,
                reason="exact_group",
                anchor_id=exact_group[0].task.anchor_id,
            )

    # Exact member-content fingerprint match.
    exact_content = [
        candidate
        for candidate in candidates
        if candidate.signature == stored_signature
    ]
    if len(exact_content) == 1:
        return TaskBinding(
            state=BindingState.CHANGED_RESOLVED,
            member_ids=tuple(exact_content[0].task.member_ids),
            current_signature=stored_signature,
            confidence=1.0,
            reason="exact_fingerprint",
            anchor_id=exact_content[0].task.anchor_id,
        )

    # Conservative scoring ladder with hard compatibility gates.
    scored = sorted(
        (
            (score, candidate)
            for candidate in candidates
            if (score := _score_candidate(locator, candidate)) >= 0
        ),
        key=lambda item: (-item[0], item[1].task.task_id),
    )
    if not scored:
        return TaskBinding(
            BindingState.ORPHANED, reason="no_compatible_candidate"
        )
    best_score, best = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if (
        best_score >= MATCH_CONFIDENCE_THRESHOLD
        and best_score - runner_up >= MATCH_WINNER_MARGIN
    ):
        return TaskBinding(
            state=BindingState.CHANGED_RESOLVED,
            member_ids=tuple(best.task.member_ids),
            current_signature=best.signature,
            confidence=best_score,
            runner_up=runner_up,
            reason="scored_match",
            anchor_id=best.task.anchor_id,
        )
    if best_score >= MATCH_CONFIDENCE_THRESHOLD:
        return TaskBinding(
            BindingState.AMBIGUOUS,
            confidence=best_score,
            runner_up=runner_up,
            reason="winner_margin_too_small",
        )
    return TaskBinding(
        BindingState.ORPHANED,
        confidence=best_score,
        reason="below_confidence_threshold",
    )


@dataclass
class FileReconcileReport:
    """Reconcile input for one source file, consumed by the store."""

    file_id: str
    availability: str = "available"
    source_signature: Optional[str] = None
    image_rel_path: Optional[str] = None
    label_rel_path: Optional[str] = None
    task_bindings: dict[str, TaskBinding] = field(default_factory=dict)
    new_candidate_count: int = 0


def reconcile_file_tasks(
    locators_by_task: dict[str, dict],
    candidates: Iterable[LiveTaskCandidate],
    file_unchanged: bool,
    live_ids_by_ordinal: Optional[dict] = None,
    manual_choices: Optional[dict[str, str]] = None,
) -> dict[str, TaskBinding]:
    """Reconcile every stored task of one file with collision downgrade.

    When several stored tasks claim the same live candidate, every
    claimant is downgraded to ambiguous: ambiguous candidates never
    receive automatic progress transfer.  Manually confirmed choices are
    protected while their chosen signature still exists.
    """

    candidate_tuple = tuple(candidates)
    manual_choices = manual_choices or {}
    bindings: dict[str, TaskBinding] = {}
    for task_id, locator in locators_by_task.items():
        chosen_signature = manual_choices.get(task_id)
        if chosen_signature is not None:
            match = next(
                (
                    candidate
                    for candidate in candidate_tuple
                    if candidate.signature == chosen_signature
                ),
                None,
            )
            if match is not None:
                bindings[task_id] = TaskBinding(
                    state=BindingState.MANUALLY_BOUND,
                    member_ids=tuple(match.task.member_ids),
                    current_signature=match.signature,
                    confidence=1.0,
                    reason="manual",
                    anchor_id=match.task.anchor_id,
                )
                continue
        bindings[task_id] = reconcile_task_locator(
            locator, candidate_tuple, file_unchanged, live_ids_by_ordinal
        )
    claimed: dict[str, list[str]] = {}
    for task_id, binding in bindings.items():
        if binding.state in (
            BindingState.READY,
            BindingState.CHANGED_RESOLVED,
        ):
            key = "|".join(binding.member_ids)
            claimed.setdefault(key, []).append(task_id)
    for claimers in claimed.values():
        if len(claimers) > 1:
            for task_id in claimers:
                bindings[task_id] = TaskBinding(
                    BindingState.AMBIGUOUS,
                    reason="conflicting_claim",
                )
    return bindings


def reconcile_source_file(
    file_record: SourceFileRecord,
    dataset_root: str,
    locators_by_task: dict,
    manual_choices: Optional[dict] = None,
) -> FileReconcileReport:
    """Reconcile one stored source file against current disk state.

    This is the single driver used by both store-level reconcile and
    controller rehydration: it resolves the stored relative path under
    ``dataset_root``, rescans the annotation, compares source
    signatures, and runs the binding ladder for every stored task of
    the file.  Live candidates are rebuilt with permissive criteria so
    a renamed label never erases its own reconciliation target.  New
    candidate counts report live tasks no stored task claimed, without
    mutating queue membership.
    """

    label_path = resolve_relative_path(
        dataset_root, file_record.label_rel_path
    )
    scan = scan_annotation_file(label_path)
    if not scan.ok:
        bindings = {
            task_id: TaskBinding(
                BindingState.MISSING, reason=scan.error or "missing"
            )
            for task_id in locators_by_task
        }
        return FileReconcileReport(
            file_id=file_record.file_id,
            availability="missing",
            source_signature=scan.source_signature,
            task_bindings=bindings,
        )
    views, points_by_id = views_from_annotation(scan)
    candidates = build_live_candidates(
        views, points_by_id, VirtualTaskCriteria()
    )
    file_unchanged = (
        file_record.source_signature is not None
        and file_record.source_signature == scan.source_signature
    )
    ordinal_ids = {index: view.shape_id for index, view in enumerate(views)}
    bindings = reconcile_file_tasks(
        locators_by_task,
        candidates,
        file_unchanged,
        live_ids_by_ordinal=ordinal_ids,
        manual_choices=manual_choices,
    )
    claimed = {
        "|".join(binding.member_ids)
        for binding in bindings.values()
        if binding.member_ids
    }
    new_candidates = sum(
        1
        for candidate in candidates
        if "|".join(candidate.task.member_ids) not in claimed
    )
    return FileReconcileReport(
        file_id=file_record.file_id,
        availability="available",
        source_signature=scan.source_signature,
        task_bindings=bindings,
        new_candidate_count=new_candidates,
    )


def evaluate_task_freshness(
    outcome: Any,
    reviewed_signature: Optional[str],
    current_signature: Optional[str],
    trusted_binding: bool,
) -> TaskFreshness:
    """Evaluate per-task freshness after rebinding.

    Only completions can become stale; pending or rework outcomes are
    fresh by definition unless the binding itself is untrustworthy,
    in which case freshness is unresolved but the outcome is retained.
    """

    if not trusted_binding:
        return TaskFreshness.UNRESOLVED
    if TaskOutcome(outcome) is not TaskOutcome.COMPLETED:
        return TaskFreshness.FRESH
    if reviewed_signature is None:
        return TaskFreshness.FRESH
    if current_signature is None:
        return TaskFreshness.UNRESOLVED
    if reviewed_signature == current_signature:
        return TaskFreshness.FRESH
    return TaskFreshness.STALE


def freshness_for_record(
    record: AtomicTaskRecord,
    current_signature: Optional[str],
    trusted_binding: bool,
) -> TaskFreshness:
    """Evaluate freshness for one stored task record."""

    return evaluate_task_freshness(
        record.outcome,
        record.reviewed_signature,
        current_signature,
        trusted_binding,
    )


__all__ = [
    "AnnotationScan",
    "FileReconcileReport",
    "LiveTaskCandidate",
    "MATCH_CONFIDENCE_THRESHOLD",
    "MATCH_WINNER_MARGIN",
    "TaskBinding",
    "build_live_candidates",
    "build_task_locator",
    "evaluate_task_freshness",
    "freshness_for_record",
    "reconcile_file_tasks",
    "reconcile_source_file",
    "reconcile_task_locator",
    "scan_annotation_file",
    "shape_entry",
    "source_signature_of",
    "views_entry",
    "views_from_annotation",
]
