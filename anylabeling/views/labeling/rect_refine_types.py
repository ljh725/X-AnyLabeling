"""Pure-Python input types for three-box geometric filtering."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, FrozenSet, Mapping, Optional, Tuple

BBox = Tuple[float, float, float, float]
ShapeId = Tuple[str, int]
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RectRefineLabelRoles:
    """Labels assigned to each geometric role in rectangle focus."""

    body: FrozenSet[str]
    head: FrozenSet[str]
    face: FrozenSet[str]

    def contains(self, label: str) -> bool:
        """Return whether a label belongs to any configured role."""
        return label in self.body or label in self.head or label in self.face


DEFAULT_RECT_REFINE_LABEL_ROLES = RectRefineLabelRoles(
    body=frozenset(("person", "halfperson")),
    head=frozenset(("head",)),
    face=frozenset(("face",)),
)


def _parse_role_labels(
    raw_roles: Mapping[str, Any],
    role_name: str,
    default_labels: FrozenSet[str],
) -> FrozenSet[str]:
    """Parse one configured role or return its default labels."""
    if role_name not in raw_roles:
        return default_labels
    raw_labels = raw_roles[role_name]
    if not isinstance(raw_labels, list):
        logger.warning(
            "Invalid rect_refine.label_roles.%s; using defaults",
            role_name,
        )
        return default_labels
    labels = [
        label.strip()
        for label in raw_labels
        if isinstance(label, str) and label.strip()
    ]
    if len(labels) != len(raw_labels) or not labels:
        logger.warning(
            "Invalid rect_refine.label_roles.%s; using defaults",
            role_name,
        )
        return default_labels
    return frozenset(labels)


def parse_rect_refine_label_roles(
    config: object,
) -> RectRefineLabelRoles:
    """Build safe label roles from a merged ``rect_refine`` config block."""
    if not isinstance(config, Mapping):
        return DEFAULT_RECT_REFINE_LABEL_ROLES
    raw_roles = config.get("label_roles")
    if raw_roles is None:
        return DEFAULT_RECT_REFINE_LABEL_ROLES
    if not isinstance(raw_roles, Mapping):
        logger.warning("Invalid rect_refine.label_roles; using defaults")
        return DEFAULT_RECT_REFINE_LABEL_ROLES

    defaults = DEFAULT_RECT_REFINE_LABEL_ROLES
    roles = RectRefineLabelRoles(
        body=_parse_role_labels(raw_roles, "body", defaults.body),
        head=_parse_role_labels(raw_roles, "head", defaults.head),
        face=_parse_role_labels(raw_roles, "face", defaults.face),
    )
    if (
        roles.body & roles.head
        or roles.body & roles.face
        or roles.head & roles.face
    ):
        logger.warning("Overlapping rect_refine label roles; using defaults")
        return defaults
    return roles


@dataclass(frozen=True)
class ShapeRefineView:
    """Immutable geometry copied from one live Shape."""

    shape_id: ShapeId
    shape_index: int = 0
    label: str = ""
    shape_type: str = "rectangle"
    bbox: Optional[BBox] = None
    base_visible: bool = True


__all__ = [
    "BBox",
    "DEFAULT_RECT_REFINE_LABEL_ROLES",
    "RectRefineLabelRoles",
    "ShapeId",
    "ShapeRefineView",
    "parse_rect_refine_label_roles",
]
