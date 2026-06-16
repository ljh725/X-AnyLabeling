"""Pose keypoint label rendering package.

Provides COCO keypoint constants, display configuration, layout
algorithms, and a QPainter-based renderer that integrates with the
existing Canvas paint pipeline.
"""

from .pose_color_panel import PoseColorPanel
from .pose_config import PoseDisplayConfig
from .pose_constants import (
    BODY_PART_ORDER,
    BODY_PARTS,
    COCO_KEYPOINT_INDEX,
    COCO_KEYPOINT_ORDER,
    COCO_KEYPOINT_SET,
    COLOR_PRESETS,
    DEFAULT_BODY_COLORS,
    DEFAULT_PERSON_COLORS,
    DIRECTION_ARROWS,
    DIRECTION_VECTORS,
    LABEL_TO_BODY_PART,
    LAYOUT_PRIORITY,
    SKELETON_EDGES,
)
from .pose_layout import (
    PoseLabelItem,
    apply_layout,
    compute_direction,
    compute_midline,
)
from .pose_settings_panel import PoseSettingsPanel
from .pose_view_panel import PoseViewPanel
from .pose_renderer import PoseRenderer

__all__ = [
    "PoseColorPanel",
    "PoseDisplayConfig",
    "PoseLabelItem",
    "PoseRenderer",
    "PoseSettingsPanel",
    "PoseViewPanel",
    "apply_layout",
    "compute_direction",
    "compute_midline",
    "BODY_PART_ORDER",
    "BODY_PARTS",
    "COCO_KEYPOINT_INDEX",
    "COCO_KEYPOINT_ORDER",
    "COCO_KEYPOINT_SET",
    "COLOR_PRESETS",
    "DEFAULT_BODY_COLORS",
    "DEFAULT_PERSON_COLORS",
    "DIRECTION_ARROWS",
    "DIRECTION_VECTORS",
    "LABEL_TO_BODY_PART",
    "LAYOUT_PRIORITY",
    "SKELETON_EDGES",
]
