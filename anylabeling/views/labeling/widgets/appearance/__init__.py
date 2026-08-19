"""Pure-Python annotation appearance and group-focus primitives."""

from .config import (
    DEFAULT_APPEARANCE_SETTINGS,
    load_project_palette,
    load_user_appearance,
    migrate_legacy_appearance,
    save_project_palette,
)
from .focus import GroupFocusController, GroupFocusState
from .palette import (
    ACCESSIBLE_PALETTE,
    color_for_key,
    is_valid_group_id,
    resolve_base_color,
)
from .types import (
    AppearanceSettings,
    ColorMode,
    ShapeVisualContext,
    VisualStyle,
)

__all__ = [
    "ACCESSIBLE_PALETTE",
    "AppearanceSettings",
    "ColorMode",
    "DEFAULT_APPEARANCE_SETTINGS",
    "GroupFocusController",
    "GroupFocusState",
    "ShapeVisualContext",
    "VisualStyle",
    "color_for_key",
    "is_valid_group_id",
    "load_project_palette",
    "load_user_appearance",
    "migrate_legacy_appearance",
    "resolve_base_color",
    "save_project_palette",
]
