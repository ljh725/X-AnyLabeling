"""PoseDisplayConfig – all tunable parameters for the pose label renderer.

The config is a plain dataclass that can be (de)serialised to/from the
project YAML config.  It is shared between the Canvas, the renderer, and
the sidebar panels so that a single mutation triggers a repaint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .pose_constants import (
    COLOR_PRESETS,
    DEFAULT_BODY_COLORS,
    DEFAULT_PERSON_COLORS,
)


@dataclass
class PoseDisplayConfig:
    """All parameters controlling pose keypoint label rendering.

    Attributes:
        enabled: Master switch.  When ``True`` the Canvas delegates
            COCO keypoint rendering to :class:`PoseRenderer`.
        layout_mode: ``"direct"`` | ``"anti"`` | ``"column"``.
        color_mode: ``"bodypart"`` | ``"person"``.
        font_size: Label font size in "CSS px" (divided by scale at
            render time so the screen size stays constant).
        opacity: Label background opacity (0.0 – 1.0).
        leader_length: Base leader-line length in screen px.
        border_width: Label border width in screen px (0 = none).
        column_gap: Vertical gap between labels in column layout.
        show_skeleton: Draw skeleton edges between keypoints.
        show_midline: Draw a dashed vertical body midline.
        show_bbox: Draw the person bounding-box rectangle.
        occlusion_highlight: Highlight overlapping labels in red.
        show_leader: Draw leader lines from labels to keypoints.
        font_shadow: Draw a dark text shadow for readability.
        font_color_mode: ``"white"`` | ``"black"`` | ``"auto"`` |
            ``"yellow"`` | ``"custom"``.
        custom_font_color: Hex colour used when *font_color_mode* is
            ``"custom"``.
        body_colors: Mapping body-part -> hex colour.
        person_colors: List of per-person hex colours (cycled).
        color_preset: Name of the currently-applied preset.
        occlusion_count: Last computed overlap count (read-only).
    """

    # Master switch
    enabled: bool = False

    # Layout & colouring
    layout_mode: str = "anti"
    color_mode: str = "bodypart"

    # Display parameters (screen-px semantics)
    font_size: int = 11
    opacity: float = 0.85
    leader_length: int = 40
    border_width: float = 0.0
    column_gap: int = 8
    # When True, clicking a person in Pose View focuses its group via
    # the gid filter (single-select; no whole-group selection).
    pose_click_to_focus: bool = True

    # Display toggles
    show_skeleton: bool = True
    show_midline: bool = False
    show_bbox: bool = True
    occlusion_highlight: bool = True
    show_leader: bool = True
    font_shadow: bool = True

    # Font colour
    font_color_mode: str = "white"
    custom_font_color: str = "#00ff88"

    # Colours
    body_colors: Dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_BODY_COLORS)
    )
    person_colors: List[str] = field(
        default_factory=lambda: list(DEFAULT_PERSON_COLORS)
    )
    color_preset: str = "default"

    # Runtime-only (not persisted)
    occlusion_count: int = 0

    # -- Serialisation helpers ------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a YAML-serialisable dict (excludes runtime fields)."""
        return {
            "enabled": self.enabled,
            "layout_mode": self.layout_mode,
            "color_mode": self.color_mode,
            "font_size": self.font_size,
            "opacity": self.opacity,
            "leader_length": self.leader_length,
            "border_width": self.border_width,
            "column_gap": self.column_gap,
            "pose_click_to_focus": self.pose_click_to_focus,
            "show_skeleton": self.show_skeleton,
            "show_midline": self.show_midline,
            "show_bbox": self.show_bbox,
            "occlusion_highlight": self.occlusion_highlight,
            "show_leader": self.show_leader,
            "font_shadow": self.font_shadow,
            "font_color_mode": self.font_color_mode,
            "custom_font_color": self.custom_font_color,
            "body_colors": dict(self.body_colors),
            "person_colors": list(self.person_colors),
            "color_preset": self.color_preset,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PoseDisplayConfig":
        """Build a config from a (possibly partial) dict.

        Missing keys fall back to dataclass defaults.
        """
        known = {
            k: v
            for k, v in data.items()
            if k in cls.__dataclass_fields__ and k != "occlusion_count"
        }
        return cls(**known)

    # -- Convenience ----------------------------------------------------

    def apply_preset(self, name: str) -> bool:
        """Apply a named colour preset.

        Args:
            name: One of the keys in
                :data:`pose_constants.COLOR_PRESETS`.

        Returns:
            ``True`` if the preset was found and applied.
        """
        preset = COLOR_PRESETS.get(name)
        if preset is None:
            return False
        self.body_colors = dict(preset)
        self.color_preset = name
        return True

    def get_person_color(self, person_index: int) -> str:
        """Return the colour for the *person_index*-th person."""
        if not self.person_colors:
            return DEFAULT_PERSON_COLORS[0]
        return self.person_colors[person_index % len(self.person_colors)]
