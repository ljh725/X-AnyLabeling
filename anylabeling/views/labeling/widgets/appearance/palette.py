"""Deterministic accessible palette and color-mode resolution."""

import hashlib
from typing import Mapping, Optional, Tuple

from .types import Color, ColorMode

# Paul Tol / Okabe-Ito inspired colors.  The reserved black background entry
# used by the legacy palette is intentionally absent.
ACCESSIBLE_PALETTE: Tuple[Color, ...] = (
    (0, 114, 178),
    (230, 159, 0),
    (0, 158, 115),
    (213, 94, 0),
    (204, 121, 167),
    (86, 180, 233),
    (240, 228, 66),
    (117, 112, 179),
    (166, 54, 66),
    (46, 125, 50),
    (123, 31, 162),
    (0, 121, 107),
)


def is_valid_group_id(value: object) -> bool:
    """Return whether ``value`` is a non-negative integer group id."""
    return (
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
    )


def color_for_key(
    key: object, palette: Tuple[Color, ...] = ACCESSIBLE_PALETTE
) -> Color:
    """Return a stable palette color without ever selecting a background slot."""
    if not palette:
        raise ValueError("palette must contain at least one color")
    if isinstance(key, int) and not isinstance(key, bool):
        index = key % len(palette)
    else:
        digest = hashlib.sha256(str(key).encode("utf-8")).digest()
        index = int.from_bytes(digest[:8], "big") % len(palette)
    return tuple(int(channel) for channel in palette[index])


def resolve_base_color(
    mode: ColorMode | str,
    label: str,
    group_id: object = None,
    shape_token: Optional[str] = None,
    label_colors: Optional[Mapping[str, Color]] = None,
) -> Color:
    """Resolve a shape's semantic base color for one display mode."""
    if not isinstance(mode, ColorMode):
        mode = ColorMode(str(mode).lower())
    if mode is ColorMode.UNIFORM:
        return ACCESSIBLE_PALETTE[0]
    if mode is ColorMode.LABEL:
        if label_colors and label in label_colors:
            return tuple(int(channel) for channel in label_colors[label])
        return color_for_key(label)
    if mode is ColorMode.GROUP:
        return color_for_key(
            group_id if is_valid_group_id(group_id) else "ungrouped"
        )
    if mode is ColorMode.INSTANCE:
        return color_for_key(shape_token or label)
    # Focus mode uses label semantics when there is no active group.  The
    # focused-group dimming is applied by the focus/style policy layer.
    if is_valid_group_id(group_id):
        return color_for_key(label, ACCESSIBLE_PALETTE)
    return (
        tuple(int(channel) for channel in label_colors[label])
        if label_colors and label in label_colors
        else color_for_key(label)
    )
