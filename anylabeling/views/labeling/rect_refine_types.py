"""Pure-Python input types for three-box geometric filtering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

BBox = Tuple[float, float, float, float]
ShapeId = Tuple[str, int]


@dataclass(frozen=True)
class ShapeRefineView:
    """Immutable geometry copied from one live Shape."""

    shape_id: ShapeId
    shape_index: int = 0
    label: str = ""
    shape_type: str = "rectangle"
    bbox: Optional[BBox] = None
    base_visible: bool = True


__all__ = ["BBox", "ShapeId", "ShapeRefineView"]
