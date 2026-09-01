"""Pure transient isolation state for dense annotation review."""

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence

from .palette import is_valid_group_id


def _value(shape: object, name: str, default: object = None) -> object:
    """Read a shape field from either a mapping or an object."""
    if isinstance(shape, Mapping):
        return shape.get(name, default)
    return getattr(shape, name, default)


def _token(shape: object) -> str:
    """Return a stable per-object token when serialized identity is absent."""
    value = _value(shape, "shape_token", None)
    if value in (None, ""):
        value = _value(shape, "id", None)
    return str(value if value not in (None, "") else id(shape))


@dataclass(frozen=True)
class IsolationState:
    """Immutable, image-scoped target for transient canvas isolation."""

    image_token: str = ""
    enabled: bool = False
    focused_group_id: Optional[int] = None
    selected_shape_tokens: tuple[str, ...] = ()

    def allows(self, shape: object) -> bool:
        """Return whether a shape belongs to this isolation target."""
        if not self.enabled:
            return True
        if self.focused_group_id is not None:
            return _value(shape, "group_id") == self.focused_group_id
        return _token(shape) in self.selected_shape_tokens


def derive_isolation_state(
    image_token: str,
    selected_shapes: Sequence[object] | Iterable[object],
    enabled: bool = True,
) -> IsolationState:
    """Derive a target for single-group, mixed-group, and ungrouped selection.

    A selection containing only one valid group isolates the complete group.
    Mixed, ungrouped, or otherwise heterogeneous selections isolate exact
    shape tokens so that unrelated objects remain hidden without mutating them.
    """
    selected = tuple(selected_shapes)
    if not enabled or not selected:
        return IsolationState(image_token=str(image_token))
    groups = {
        _value(shape, "group_id")
        for shape in selected
        if is_valid_group_id(_value(shape, "group_id"))
    }
    has_ungrouped = any(
        not is_valid_group_id(_value(shape, "group_id")) for shape in selected
    )
    focused_group_id = (
        next(iter(groups)) if len(groups) == 1 and not has_ungrouped else None
    )
    tokens = (
        ()
        if focused_group_id is not None
        else tuple(_token(shape) for shape in selected)
    )
    return IsolationState(
        image_token=str(image_token),
        enabled=True,
        focused_group_id=focused_group_id,
        selected_shape_tokens=tokens,
    )
