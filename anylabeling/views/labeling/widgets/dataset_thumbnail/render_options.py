"""Immutable display policy shared by thumbnails and large previews."""

from dataclasses import dataclass
import math

from .cache import THUMBNAIL_CROP_POLICY_VERSION


@dataclass(frozen=True)
class RenderOptions:
    """Describe visual context without changing stored annotation geometry."""

    padding: float = 0.15
    show_box: bool = False
    mode: str = "crop"

    def __post_init__(self) -> None:
        """Keep display requests finite and bounded."""
        if not math.isfinite(self.padding) or not 0 <= self.padding <= 1:
            raise ValueError("Context must be between 0 and 100 percent")
        if self.mode not in ("crop", "full"):
            raise ValueError("Unknown preview mode")

    @property
    def cache_policy(self) -> str:
        """Preserve default cache reuse and isolate all other policies."""
        if self == RenderOptions():
            return THUMBNAIL_CROP_POLICY_VERSION
        return f"review-v1:{self.padding:.6f}:{int(self.show_box)}:{self.mode}"
