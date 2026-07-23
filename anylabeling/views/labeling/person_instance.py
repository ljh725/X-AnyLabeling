"""Shared rules for person-instance annotation data."""

from typing import Any, FrozenSet

INSTANCE_MEMBER_LABELS: FrozenSet[str] = frozenset({"person", "head", "face"})
INSTANCE_SHAPE_TYPE = "rectangle"
POSE_SUBJECT_LABEL = "person"


def is_valid_group_id(value: Any) -> bool:
    """Return whether a group ID is a non-negative integer.

    Args:
        value: Candidate group ID value.

    Returns:
        True when ``value`` is an integer greater than or equal to zero.
    """
    return (
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
    )
