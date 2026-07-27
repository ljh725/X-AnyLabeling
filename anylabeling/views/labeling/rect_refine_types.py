# PyQt-free module — MUST NOT import PyQt6 or any UI widget.
"""Type definitions for the three-box rectangle refine mode.

This module is pure Python data layer (``Enum`` + ``dataclass``).  It holds
*zero* business logic and never touches a real :class:`Shape` instance.

The architecture rule from ``docs/三框精修模式交互与状态机设计.md`` §23.3:
grouping/types must be importable in a process without PyQt6 installed.
The concrete :class:`~anylabeling.views.labeling.shape.Shape` reference is
carried as an opaque ``shape_ref`` field (typed ``Any``); pure-logic code
must never read it.

References:
    §24 core data model
    §22.3 invariants
    §29.7 conflict codes
    §24.7 save result
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Primitive aliases — kept tuple-based so the data is hashable & immutable.
# ---------------------------------------------------------------------------

#: Axis-aligned bounding box ``(x1, y1, x2, y2)`` in original-image floats.
BBox = Tuple[float, float, float, float]

#: First-version runtime identity: ``(image_token, id(shape))``.
#:
#: The image token scopes identity to one image-load lifetime; reloading the
#: same file produces a fresh token.  ``id(shape)`` is the Python object
#: identity.  This pair is stable within a single image session and is *never*
#: persisted to JSON, ``other_data`` or ``Shape`` attributes.
ShapeId = Tuple[str, int]

#: A single point in original-image floats.
Point = Tuple[float, float]


# ---------------------------------------------------------------------------
# §24.1 RectRefineState
# ---------------------------------------------------------------------------


class RectRefineState(Enum):
    """Workflow state machine states (§24.1, §25.1).

    ``SAVING`` is a transient state even for the current synchronous save
    implementation; it makes reentrancy and exception-recovery semantics
    explicit.
    """

    OFF = "OFF"
    SELECTING = "SELECTING"
    INFERRING = "INFERRING"
    ACTIVE = "ACTIVE"
    SAVING = "SAVING"


# ---------------------------------------------------------------------------
# §24.3 / §29 relation / source enums
# ---------------------------------------------------------------------------


class RelationKind(Enum):
    """Directed relation between two workgroup members."""

    #: head is the upper box of a person (downward inference).
    HEAD_OF_PERSON = "head_of_person"
    #: face is the inner box of a head (downward inference).
    FACE_OF_HEAD = "face_of_head"
    #: person is the outer box of a head (upward inference, §29.5).
    PERSON_OF_HEAD = "person_of_head"


class CandidateSource(Enum):
    """Why a candidate was admitted into the workgroup."""

    GEOMETRY = "geometry"
    GID = "gid"
    BOTH = "both"


class ConflictCode(Enum):
    """Stable conflict codes for GID/geometry disagreement (§29.7).

    Pure-geometry multi-candidates, missing members, no reliable candidate
    and upward ambiguity are *not* GID conflicts and must not use these codes.
    """

    #: §29.4 step 2 / AC-025: person GID path contains >1 head.
    DUPLICATE_GID_HEAD = "DUPLICATE_GID_HEAD"
    #: §29.4 step 2 / AC-026: person GID path contains >1 face.
    DUPLICATE_GID_FACE = "DUPLICATE_GID_FACE"
    #: §29.4 step 4 / AC-027: same-GID head fails person hard filter.
    GID_HEAD_GEOMETRY_INVALID = "GID_HEAD_GEOMETRY_INVALID"
    #: §29.4 step 4 / AC-028: another head beats the same-GID head by ≥0.12.
    GID_HEAD_DISAGREES_WITH_GEOMETRY = "GID_HEAD_DISAGREES_WITH_GEOMETRY"
    #: §29.4 step 6 / AC-030: same-GID face unverifiable by any accepted head.
    GID_FACE_GEOMETRY_INVALID = "GID_FACE_GEOMETRY_INVALID"


class SaveResult(Enum):
    """Outcome of the accept-current-workgroup save adapter (§24.7).

    The save adapter wraps ``save_labels()``; workflow branches on this enum
    rather than inferring state from window dirty flags.
    """

    #: Preserve geometry, release workgroup, transition to ``SELECTING``.
    SUCCESS = "SUCCESS"
    #: Keep workgroup and geometry, transition back to ``ACTIVE``.
    CANCELLED = "CANCELLED"
    #: Keep workgroup and geometry, transition back to ``ACTIVE``.
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# §24.2 ShapeRefineView — pure-logic input view
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShapeRefineView:
    """Immutable pure-logic view of a candidate Shape (§24.2).

    ``shape_ref`` is opaque to all pure-logic modules; only the workflow/UI
    layer reads it to reach the live :class:`Shape`.  All geometry-bearing
    fields (``points``, ``bbox``) are deep-copied at construction so later
    in-place edits to the real Shape cannot corrupt grouping results.
    """

    #: ``(image_token, id(shape))`` runtime identity.
    shape_id: ShapeId
    #: Opaque live Shape reference; pure logic never reads this.
    shape_ref: Any = None
    #: Index within ``canvas.shapes`` at capture time — sort/diagnostic only.
    shape_index: int = 0
    #: ``person`` / ``head`` / ``face``.
    label: str = ""
    #: First version only accepts ``rectangle``.
    shape_type: str = "rectangle"
    #: Original group_id, kept read-only as-is (may be bool/str/None).
    group_id: Any = None
    #: Immutable copy of original-image points ``((x, y), ...)``.
    points: Tuple[Point, ...] = ()
    #: ``(x1, y1, x2, y2)`` computed from ``points``; ``None`` if degenerate.
    bbox: Optional[BBox] = None
    #: User base-layer visibility captured at mode entry (§6.1, §28.2).
    #: Default ``True``; the workflow supplies the real snapshot.
    base_visible: bool = True


# ---------------------------------------------------------------------------
# §24.3 GroupingCandidate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupingCandidate:
    """One scored candidate produced by grouping (§24.3).

    Scores are for internal judgement and tests only; they are never shown
    in the UI (§29.2 last paragraph).
    """

    #: Identity of the candidate Shape.
    target_id: ShapeId
    #: Directed relation to the anchor.
    relation: RelationKind
    #: Why admitted (geometry / gid / both).
    source: CandidateSource
    #: Aggregate score in ``[0.0, 1.0]``.
    score: float
    #: Passed the §21 hard filter.
    passed_hard_filter: bool
    #: ``score >= min_accept_score`` (default ``0.55``).
    meets_accept_score: bool
    #: Score gap vs the top-1 candidate (top-1 itself is ``0.0``).
    top_gap: float
    #: Deterministic total-order sort key (§29.3).
    sort_key: Tuple[float, ...]
    #: Per-metric breakdown for conflict diagnostics / tests.
    metrics: Dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# §24.4 RelationGraph
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RelationGraph:
    """Explicit directed relations retained by the workgroup (§24.4).

    The Overlay reads *only* this graph and must never re-run full-image
    matching during paint (§24.4 last paragraph).
    """

    #: person shape_id -> list of head shape_ids (downward).
    person_to_heads: Dict[ShapeId, List[ShapeId]] = field(default_factory=dict)
    #: head shape_id -> list of face shape_ids (downward).
    head_to_faces: Dict[ShapeId, List[ShapeId]] = field(default_factory=dict)
    #: head shape_id -> optional person shape_id (upward; ``None`` = ambiguous).
    head_to_person: Dict[ShapeId, Optional[ShapeId]] = field(
        default_factory=dict
    )
    #: face shape_id -> optional head shape_id (upward; ``None`` = ambiguous).
    face_to_head: Dict[ShapeId, Optional[ShapeId]] = field(
        default_factory=dict
    )


# ---------------------------------------------------------------------------
# §24.5 WorkgroupSnapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkgroupSnapshot:
    """One-shot capture taken at workgroup construction (§24.5).

    Frozen so rollback cannot be corrupted by later in-place edits.
    """

    #: Scopes the workgroup to one image-load (invariant §22.3 #3).
    image_token: str
    #: Identity of the non-replaceable anchor.
    anchor_shape_id: ShapeId
    #: All member identities (anchor is always included).
    member_shape_ids: Tuple[ShapeId, ...]
    #: Deep copy of each member's original points, keyed by shape_id.
    original_points: Dict[ShapeId, Tuple[Point, ...]]
    #: Document dirty flag captured *before* workgroup edits (§32.3).
    dirty_before: bool
    #: ``len(canvas.shapes_backups)`` captured before workgroup edits (§32.4).
    #: Workflow uses this as the Ctrl+Z floor; the value is informational here
    #: because the Canvas adapter owns the real backup stack.
    undo_floor: int
    #: Frozen relation graph for Overlay and internal walks.
    relation_graph: RelationGraph
    #: Per-member provenance (geometry / gid / both).
    provenance: Dict[ShapeId, CandidateSource]


# ---------------------------------------------------------------------------
# §24.6 RectRefineWorkgroup (mutable runtime state)
# ---------------------------------------------------------------------------


@dataclass
class RectRefineWorkgroup:
    """Live workgroup state held by the workflow (§24.6).

    ``snapshot`` is the immutable construction record; the mutable fields
    below track runtime evolution without rewriting history.
    """

    #: Immutable construction record.
    snapshot: WorkgroupSnapshot
    #: Current workflow state of this workgroup.
    state: RectRefineState
    #: shape_id -> opaque live Shape reference.
    current_members: Dict[ShapeId, Any] = field(default_factory=dict)
    #: Currently formally-selected member, if any.
    current_selected_id: Optional[ShapeId] = None
    #: Whether any geometry change has been committed to memory.
    has_committed_geometry: bool = False
    #: Last non-blocking conflict / hint message key, if any.
    last_message: Optional[str] = None


# ---------------------------------------------------------------------------
# §24.7 SaveResult already defined above.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# §30 Overlay model (pure data; Canvas paints in stage 3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OverlayRelation:
    """One comparable edge pair for the live alignment hint (§30.1)."""

    #: Opaque reference to the outer (parent) Shape; Canvas reads live points.
    outer_ref: Any
    #: Opaque reference to the inner (child) Shape.
    inner_ref: Any
    #: ``"top"`` (head.y_min vs person.y_min) or ``"bottom"`` (face.y_max vs
    #: head.y_max).
    edge_kind: str
    #: Strict less-than threshold in original-image px (default ``3.0``).
    alignment_hint_px: float = 3.0


@dataclass(frozen=True)
class OverlayModel:
    """Read-only Overlay payload produced by the workflow (§30.1).

    The Canvas computes the actual px delta at paint time from the live Shape
    references; the workflow never re-runs full-image matching here.
    """

    #: Whether the workflow is in ``ACTIVE``.
    is_active: bool
    #: Currently selected member identity, if any.
    selected_id: Optional[ShapeId]
    #: Comparable relations derived from the workgroup's relation graph.
    relations: Tuple[OverlayRelation, ...] = ()


# ---------------------------------------------------------------------------
# GID validation — §24.2 last paragraph
# ---------------------------------------------------------------------------


def is_valid_gid(gid: Any) -> bool:
    """Return ``True`` only for a non-bool integer GID (§24.2).

    Missing, wrong-typed or illegal values are *not* errors — they simply mean
    "no usable GID evidence".  The refine mode never auto-repairs GIDs
    (invariant §22.3 #5, §29.4 step 2).
    """
    return isinstance(gid, int) and not isinstance(gid, bool)


# ---------------------------------------------------------------------------
# Invariant self-checks — used by workflow + tests (§24.4, §22.3 #5)
# ---------------------------------------------------------------------------


def collect_member_ids(graph: RelationGraph) -> List[ShapeId]:
    """Return every shape_id that appears in any relation slot."""
    seen: List[ShapeId] = []
    seen_set: set = set()

    def _add(sid: Optional[ShapeId]) -> None:
        if sid is None or sid in seen_set:
            return
        seen_set.add(sid)
        seen.append(sid)

    for person, heads in graph.person_to_heads.items():
        _add(person)
        for h in heads:
            _add(h)
    for head, faces in graph.head_to_faces.items():
        _add(head)
        for f in faces:
            _add(f)
    for head, person in graph.head_to_person.items():
        _add(head)
        _add(person)
    for face, head in graph.face_to_head.items():
        _add(face)
        _add(head)
    return seen


def assert_member_unique_in_graph(graph: RelationGraph) -> None:
    """Invariant §24.4 last row: each Shape appears at most once as a *member*.

    A shape may legitimately appear in multiple relation *slots* (e.g. a head
    is in ``person_to_heads`` and ``head_to_faces``), but the deduplicated
    member set must be consistent — i.e. no two different relation entries
    disagree about the same member's identity.  This check is a sanity guard
    against accidental duplication in grouping output; it does not forbid
    cross-slot co-occurrence.
    """
    # Verify relation value lists have no internal duplicates.
    for heads in graph.person_to_heads.values():
        if len(set(heads)) != len(heads):  # pragma: no cover - defensive
            raise AssertionError("duplicate head in person_to_heads")
    for faces in graph.head_to_faces.values():
        if len(set(faces)) != len(faces):  # pragma: no cover - defensive
            raise AssertionError("duplicate face in head_to_faces")


def assert_anchor_in_members(snapshot: WorkgroupSnapshot) -> None:
    """Invariant §22.3 #4: the anchor is always a member."""
    if snapshot.anchor_shape_id not in snapshot.member_shape_ids:
        raise AssertionError("anchor shape_id missing from member_shape_ids")


def validate_snapshot(snapshot: WorkgroupSnapshot) -> None:
    """Run all snapshot-level invariant checks."""
    assert_anchor_in_members(snapshot)
    assert_member_unique_in_graph(snapshot.relation_graph)
    # original_points must cover every member.
    missing = [
        sid
        for sid in snapshot.member_shape_ids
        if sid not in snapshot.original_points
    ]
    if missing:  # pragma: no cover - defensive
        raise AssertionError(f"snapshot.original_points missing for {missing}")


__all__ = [
    "BBox",
    "ShapeId",
    "Point",
    "RectRefineState",
    "RelationKind",
    "CandidateSource",
    "ConflictCode",
    "SaveResult",
    "ShapeRefineView",
    "GroupingCandidate",
    "RelationGraph",
    "WorkgroupSnapshot",
    "RectRefineWorkgroup",
    "OverlayRelation",
    "OverlayModel",
    "is_valid_gid",
    "collect_member_ids",
    "assert_member_unique_in_graph",
    "assert_anchor_in_members",
    "validate_snapshot",
]
