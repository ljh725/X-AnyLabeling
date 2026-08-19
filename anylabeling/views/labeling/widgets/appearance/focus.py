"""Pure group-focus state machine for annotation review."""

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence

from .palette import is_valid_group_id


@dataclass(frozen=True)
class GroupFocusState:
    """Transient focus state scoped to one image token."""

    image_token: str = ""
    focused_group_id: Optional[int] = None
    selected_shape_tokens: tuple[str, ...] = ()

    @property
    def active(self) -> bool:
        """Return whether a valid group is currently focused."""
        return self.focused_group_id is not None


def _value(shape: object, name: str, default: object = None) -> object:
    """Read a shape field from either a mapping or an object."""
    if isinstance(shape, Mapping):
        return shape.get(name, default)
    return getattr(shape, name, default)


class GroupFocusController:
    """Manage focus transitions without mutating shapes or persistence state."""

    def __init__(self) -> None:
        """Initialize an empty focus state."""
        self._state = GroupFocusState()

    @property
    def state(self) -> GroupFocusState:
        """Return the current immutable state."""
        return self._state

    def clear(self) -> GroupFocusState:
        """Clear transient focus and selected token state."""
        self._state = GroupFocusState(image_token=self._state.image_token)
        return self._state

    def reset_image(self, image_token: str) -> GroupFocusState:
        """Switch images and clear focus even when group ids repeat."""
        self._state = GroupFocusState(image_token=str(image_token))
        return self._state

    def update(
        self,
        image_token: str,
        selected_shapes: Sequence[object] | Iterable[object],
        mode: str = "focus",
    ) -> GroupFocusState:
        """Apply a normalized selection snapshot to the state machine."""
        selected = tuple(selected_shapes)
        tokens = tuple(
            str(_value(shape, "shape_token", _value(shape, "id", "")))
            for shape in selected
        )
        if str(mode).lower() != "focus":
            self._state = GroupFocusState(
                image_token=str(image_token), selected_shape_tokens=tokens
            )
            return self._state
        groups = {
            _value(shape, "group_id")
            for shape in selected
            if is_valid_group_id(_value(shape, "group_id"))
        }
        has_ungrouped = any(
            not is_valid_group_id(_value(shape, "group_id"))
            for shape in selected
        )
        focused = (
            next(iter(groups))
            if len(groups) == 1 and not has_ungrouped
            else None
        )
        self._state = GroupFocusState(
            image_token=str(image_token),
            focused_group_id=focused,
            selected_shape_tokens=tokens,
        )
        return self._state

    def emphasis(self, shape: object) -> float:
        """Return opacity multiplier for a shape after visibility gates pass."""
        if not self._state.active:
            return 1.0
        return (
            1.0
            if _value(shape, "group_id") == self._state.focused_group_id
            else 0.28
        )
