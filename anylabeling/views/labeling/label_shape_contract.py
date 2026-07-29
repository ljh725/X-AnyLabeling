"""Shared label-to-shape-type contract for annotation validators."""

from typing import FrozenSet, Optional, Sequence, Tuple

RECTANGLE_SHAPE_TYPE = "rectangle"
POINT_SHAPE_TYPE = "point"

DEFAULT_RECTANGLE_LABELS: Tuple[str, ...] = ("person", "head", "face")
DEFAULT_POINT_LABELS: Tuple[str, ...] = (
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
)
DEFAULT_SHARED_LABELS: Tuple[str, ...] = (
    DEFAULT_RECTANGLE_LABELS + DEFAULT_POINT_LABELS
)

DEFAULT_RECTANGLE_LABEL_SET: FrozenSet[str] = frozenset(
    DEFAULT_RECTANGLE_LABELS
)
DEFAULT_POINT_LABEL_SET: FrozenSet[str] = frozenset(DEFAULT_POINT_LABELS)
DEFAULT_BOUND_LABEL_SET: FrozenSet[str] = frozenset(DEFAULT_SHARED_LABELS)


def expected_shape_type_for_label(label: str) -> Optional[str]:
    """Return the default shape type bound to a label, if any."""
    if label in DEFAULT_RECTANGLE_LABEL_SET:
        return RECTANGLE_SHAPE_TYPE
    if label in DEFAULT_POINT_LABEL_SET:
        return POINT_SHAPE_TYPE
    return None


def labels_to_csv(labels: Sequence[str]) -> str:
    """Render labels in contract order for UI configuration defaults."""
    return ",".join(labels)
