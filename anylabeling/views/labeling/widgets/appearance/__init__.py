"""Pure-Python annotation appearance and group-focus primitives."""

from .config import (
    DEFAULT_APPEARANCE_SETTINGS,
    clear_project_palette_cache,
    load_project_palette,
    load_user_appearance,
    migrate_legacy_appearance,
    save_project_palette,
)
from .focus import GroupFocusController, GroupFocusState
from .isolation import IsolationState, derive_isolation_state
from .render_policy import RenderDecision, resolve_render_decision
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
    "IsolationState",
    "RenderDecision",
    "ShapeVisualContext",
    "VisualStyle",
    "color_for_key",
    "clear_project_palette_cache",
    "is_valid_group_id",
    "load_project_palette",
    "load_user_appearance",
    "migrate_legacy_appearance",
    "resolve_base_color",
    "resolve_render_decision",
    "derive_isolation_state",
    "save_project_palette",
]
