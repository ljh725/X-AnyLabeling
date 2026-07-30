"""Lightweight focus controller for three-box rectangle filtering.

The controller owns only two pieces of runtime state: whether the mode is
enabled and which Shape ids are currently focused.  It deliberately does not
know about Canvas, Qt, dirty state, undo, saving, or Shape mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Optional, Sequence

from .rect_refine_grouping import infer
from .rect_refine_types import ShapeId, ShapeRefineView


@dataclass(frozen=True)
class FocusResult:
    """Result of one valid anchor-selection attempt."""

    member_ids: FrozenSet[ShapeId] = frozenset()
    message: Optional[str] = None


class RectRefineFocusController:
    """Track mode/focus state and delegate geometric association to infer()."""

    def __init__(self) -> None:
        """Initialize an inactive controller."""
        self._enabled = False
        self._image_token = ""
        self._focused_ids: Optional[FrozenSet[ShapeId]] = None

    @property
    def enabled(self) -> bool:
        """Return whether the focus mode is enabled."""
        return self._enabled

    @property
    def image_token(self) -> str:
        """Return the current image-load token."""
        return self._image_token

    @property
    def focused_ids(self) -> Optional[FrozenSet[ShapeId]]:
        """Return focused member ids, or None while waiting for an anchor."""
        return self._focused_ids

    @property
    def has_focus(self) -> bool:
        """Return whether a non-empty focus result is installed."""
        return bool(self._focused_ids)

    def enable(self, image_token: str) -> None:
        """Enable the mode and wait for an anchor on the current image."""
        self._enabled = True
        self._image_token = image_token
        self._focused_ids = None

    def disable(self) -> None:
        """Disable the mode and forget the current focus."""
        self._enabled = False
        self._focused_ids = None

    def clear_focus(self) -> bool:
        """Clear the current focus and report whether one existed."""
        had_focus = self.has_focus
        self._focused_ids = None
        return had_focus

    def on_image_loaded(self, image_token: str) -> None:
        """Bind to a newly loaded image and discard stale focused ids."""
        self._image_token = image_token
        self._focused_ids = None

    def focus_from_selection(
        self,
        selected_views: Sequence[ShapeRefineView],
        all_views: Sequence[ShapeRefineView],
    ) -> Optional[FocusResult]:
        """Build focus members from one valid formal selection.

        Invalid, empty, multi-select, hidden, or stale selections are ignored
        and leave the current focus unchanged.

        Args:
            selected_views: Immutable views of formally selected Shapes.
            all_views: Immutable views of every Shape on the current image.

        Returns:
            A new focus result for a valid anchor, otherwise None.
        """
        if not self._enabled or len(selected_views) != 1:
            return None
        anchor = selected_views[0]
        if not self._is_valid_anchor(anchor):
            return None
        if anchor.shape_id[0] != self._image_token:
            return None

        grouping = infer(anchor, all_views)
        member_ids = frozenset(member.shape_id for member in grouping.members)
        self._focused_ids = member_ids or frozenset((anchor.shape_id,))
        return FocusResult(
            member_ids=self._focused_ids,
            message=grouping.nonblocking_message,
        )

    @staticmethod
    def _is_valid_anchor(view: ShapeRefineView) -> bool:
        """Return whether a Shape view may trigger geometric focus."""
        return (
            view.label in ("person", "head", "face")
            and view.shape_type == "rectangle"
            and view.base_visible
        )


__all__ = ["FocusResult", "RectRefineFocusController"]
