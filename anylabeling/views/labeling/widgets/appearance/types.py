"""Immutable data types used by annotation appearance resolution."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

Color = Tuple[int, int, int]


class ColorMode(str, Enum):
    """Available deterministic annotation color modes."""

    FOCUS = "focus"
    LABEL = "label"
    GROUP = "group"
    INSTANCE = "instance"
    UNIFORM = "uniform"


def _clamp_opacity(value: int) -> int:
    """Clamp an opacity value to the Qt-compatible 0-255 range."""
    return max(0, min(255, int(value)))


@dataclass(frozen=True)
class AppearanceSettings:
    """User-owned display preferences, independent from annotation data."""

    color_mode: ColorMode = ColorMode.FOCUS
    high_contrast_outline: bool = True
    normal_fill_opacity: int = 0
    selected_fill_opacity: int = 28
    hover_fill_opacity: int = 18
    unrelated_opacity: float = 0.28
    show_labels: bool = True
    show_gid: str = "focus"
    outline_width: float = 1.0
    semantic_width: float = 1.0

    def __post_init__(self) -> None:
        """Normalize values loaded from YAML or legacy configuration."""
        mode = self.color_mode
        if not isinstance(mode, ColorMode):
            mode = ColorMode(str(mode).lower())
            object.__setattr__(self, "color_mode", mode)
        for field_name in (
            "normal_fill_opacity",
            "selected_fill_opacity",
            "hover_fill_opacity",
        ):
            object.__setattr__(
                self, field_name, _clamp_opacity(getattr(self, field_name))
            )
        object.__setattr__(
            self,
            "unrelated_opacity",
            max(0.0, min(1.0, float(self.unrelated_opacity))),
        )
        object.__setattr__(
            self, "outline_width", max(0.5, float(self.outline_width))
        )
        object.__setattr__(
            self, "semantic_width", max(0.5, float(self.semantic_width))
        )
        if self.show_gid not in {"always", "focus", "never"}:
            object.__setattr__(self, "show_gid", "focus")


DEFAULT_APPEARANCE_SETTINGS = AppearanceSettings()


@dataclass(frozen=True)
class ShapeVisualContext:
    """Read-only shape and interaction inputs for style resolution."""

    shape_token: str
    label: str
    group_id: object = None
    visible: bool = True
    selected: bool = False
    hovered: bool = False
    editing: bool = False
    qa_state: Optional[str] = None
    base_visible: bool = True
    focused: bool = False
    image_token: str = ""


@dataclass(frozen=True)
class VisualStyle:
    """Resolved, toolkit-neutral style for one visible annotation."""

    base_color: Color
    outer_color: Color = (18, 18, 18)
    outline_width: float = 1.0
    semantic_width: float = 1.0
    fill_opacity: int = 0
    object_opacity: float = 1.0
    label_badge: Optional[str] = None
    gid_badge: Optional[str] = None
    selected: bool = False
    hovered: bool = False
    editing: bool = False
    qa_state: Optional[str] = None
