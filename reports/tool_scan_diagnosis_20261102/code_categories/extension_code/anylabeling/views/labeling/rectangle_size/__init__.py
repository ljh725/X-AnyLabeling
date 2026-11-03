"""Pure data contracts for configurable rectangle-size validation."""

from .config_codec import (
    RULES_CONFIG_KEY,
    RectangleSizeConfigError,
    load_rectangle_size_rules,
    parse_rectangle_size_rules,
    serialize_rectangle_size_rules,
)
from .evaluator import RectangleSizeEvaluator
from .layout import (
    OverlayLayoutItem,
    OverlayLayoutPlacement,
    RectXYWH,
    layout_overlay_items,
    pick_overlay_anchor,
)
from .models import (
    BBox,
    CandidateId,
    DimensionName,
    DimensionViolation,
    RectangleCandidate,
    RectangleSizeIssue,
    RectangleSizeRule,
    TriggerMode,
)

__all__ = [
    "BBox",
    "CandidateId",
    "DimensionName",
    "DimensionViolation",
    "OverlayLayoutItem",
    "OverlayLayoutPlacement",
    "RULES_CONFIG_KEY",
    "RectXYWH",
    "RectangleCandidate",
    "RectangleSizeConfigError",
    "RectangleSizeEvaluator",
    "RectangleSizeIssue",
    "RectangleSizeRule",
    "TriggerMode",
    "load_rectangle_size_rules",
    "layout_overlay_items",
    "parse_rectangle_size_rules",
    "pick_overlay_anchor",
    "serialize_rectangle_size_rules",
]
