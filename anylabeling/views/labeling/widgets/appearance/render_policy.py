"""Pure rendering visibility decisions for dense annotation scenes."""

from dataclasses import dataclass
from typing import Optional, Sequence

from .types import ShapeVisualContext


@dataclass(frozen=True)
class RenderDecision:
    """Final display and interaction gates for one annotation shape."""

    draw_geometry: bool
    draw_text: bool
    draw_gid: bool
    draw_size_overlay: bool
    canvas_interactive: bool
    object_opacity: float


def resolve_render_decision(
    context: ShapeVisualContext,
    *,
    focus_active: bool = False,
    unrelated_opacity: float = 0.28,
    isolation_enabled: bool = False,
    isolation_group_id: Optional[int] = None,
    isolation_shape_tokens: Sequence[str] = (),
    show_labels: bool = True,
    label_on_selection: bool = False,
    show_gid: str = "focus",
) -> RenderDecision:
    """Resolve final output gates after base visibility has been evaluated.

    Args:
        context: Immutable shape and interaction inputs.
        focus_active: Whether a valid single-group Focus is active.
        unrelated_opacity: Opacity for objects outside the focused group.
        isolation_enabled: Whether transient selection isolation is active.
        isolation_group_id: Group retained by isolation, if any.
        isolation_shape_tokens: Explicit shape tokens retained by isolation.
        show_labels: Global appearance label preference.
        label_on_selection: Restrict text to selected/hovered shapes.
        show_gid: ``always``, ``focus`` or ``never``.

    Returns:
        A deterministic, toolkit-neutral rendering decision.
    """
    opacity = max(0.0, min(1.0, float(unrelated_opacity)))
    base_allowed = bool(context.visible and context.base_visible)
    isolation_allowed = True
    if isolation_enabled:
        token_allowed = context.shape_token in {
            str(token) for token in isolation_shape_tokens
        }
        group_allowed = (
            isolation_group_id is not None
            and context.group_id == isolation_group_id
        )
        isolation_allowed = token_allowed or group_allowed

    allowed = base_allowed and isolation_allowed
    focused = not focus_active or context.focused
    object_opacity = 1.0 if focused else opacity
    draw_geometry = allowed and object_opacity > 0.0
    draw_text = (
        draw_geometry
        and bool(show_labels)
        and (not label_on_selection or context.selected or context.hovered)
    )
    draw_gid = (
        draw_text
        and show_gid in {"always", "focus"}
        and (show_gid == "always" or focus_active)
    )
    return RenderDecision(
        draw_geometry=draw_geometry,
        draw_text=draw_text,
        draw_gid=draw_gid,
        draw_size_overlay=draw_geometry
        and (context.selected or context.hovered),
        canvas_interactive=allowed
        and not (isolation_enabled and not isolation_allowed),
        object_opacity=object_opacity,
    )
