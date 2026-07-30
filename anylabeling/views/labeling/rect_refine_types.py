"""Pure-Python data types for three-box geometric grouping."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

BBox = Tuple[float, float, float, float]
ShapeId = Tuple[str, int]
Point = Tuple[float, float]


class RelationKind(Enum):
    """Directed geometric relation between two rectangles."""

    HEAD_OF_PERSON = "head_of_person"
    FACE_OF_HEAD = "face_of_head"
    PERSON_OF_HEAD = "person_of_head"


class CandidateSource(Enum):
    """Evidence used to associate a grouping candidate."""

    GEOMETRY = "geometry"
    GID = "gid"
    BOTH = "both"


class ConflictCode(Enum):
    """Stable codes for GID and geometry disagreement."""

    DUPLICATE_GID_HEAD = "DUPLICATE_GID_HEAD"
    DUPLICATE_GID_FACE = "DUPLICATE_GID_FACE"
    GID_HEAD_GEOMETRY_INVALID = "GID_HEAD_GEOMETRY_INVALID"
    GID_HEAD_DISAGREES_WITH_GEOMETRY = "GID_HEAD_DISAGREES_WITH_GEOMETRY"
    GID_FACE_GEOMETRY_INVALID = "GID_FACE_GEOMETRY_INVALID"


@dataclass(frozen=True)
class ShapeRefineView:
    """Immutable grouping input copied from one live Shape."""

    shape_id: ShapeId
    shape_index: int = 0
    label: str = ""
    shape_type: str = "rectangle"
    group_id: Any = None
    points: Tuple[Point, ...] = ()
    bbox: Optional[BBox] = None
    base_visible: bool = True


@dataclass(frozen=True)
class GroupingCandidate:
    """One scored rectangle association candidate."""

    target_id: ShapeId
    relation: RelationKind
    source: CandidateSource
    score: float
    passed_hard_filter: bool
    meets_accept_score: bool
    top_gap: float
    sort_key: Tuple[float, ...]
    metrics: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class RelationGraph:
    """Directed relations retained by one grouping result."""

    person_to_heads: Dict[ShapeId, List[ShapeId]] = field(default_factory=dict)
    head_to_faces: Dict[ShapeId, List[ShapeId]] = field(default_factory=dict)
    head_to_person: Dict[ShapeId, Optional[ShapeId]] = field(
        default_factory=dict
    )
    face_to_head: Dict[ShapeId, Optional[ShapeId]] = field(
        default_factory=dict
    )


def is_valid_gid(gid: Any) -> bool:
    """Return whether a value is a usable non-bool integer group id."""
    return isinstance(gid, int) and not isinstance(gid, bool)


__all__ = [
    "BBox",
    "CandidateSource",
    "ConflictCode",
    "GroupingCandidate",
    "Point",
    "RelationGraph",
    "RelationKind",
    "ShapeId",
    "ShapeRefineView",
    "is_valid_gid",
]
