"""Pure-Python tests for the lightweight three-box focus controller."""

from __future__ import annotations

from anylabeling.views.labeling.rect_refine_focus import (
    RectRefineFocusController,
)
from anylabeling.views.labeling.rect_refine_types import (
    RectRefineLabelRoles,
    ShapeRefineView,
)

TOKEN = "image-1"


def _view(
    label: str,
    bbox: tuple[float, float, float, float],
    index: int,
    *,
    token: str = TOKEN,
    visible: bool = True,
    shape_type: str = "rectangle",
) -> ShapeRefineView:
    """Build one deterministic immutable Shape view."""
    return ShapeRefineView(
        shape_id=(token, index),
        shape_index=index,
        label=label,
        shape_type=shape_type,
        bbox=bbox,
        base_visible=visible,
    )


def _related_views() -> tuple[ShapeRefineView, ShapeRefineView]:
    """Return a person and a geometrically related head."""
    return (
        _view("person", (0, 0, 100, 200), 1),
        _view("head", (30, 10, 70, 50), 2),
    )


def test_disabled_controller_ignores_selection() -> None:
    """Selection is inert until the mode is enabled."""
    person, head = _related_views()
    controller = RectRefineFocusController()

    result = controller.focus_from_selection([person], [person, head])

    assert result is None
    assert controller.has_focus is False


def test_valid_selection_focuses_related_rectangles() -> None:
    """A visible three-box rectangle anchors geometric focus."""
    person, head = _related_views()
    controller = RectRefineFocusController()
    controller.enable(TOKEN)

    result = controller.focus_from_selection([person], [person, head])

    assert result is not None
    assert result.member_ids == frozenset((person.shape_id, head.shape_id))
    assert controller.focused_ids == result.member_ids


def test_default_controller_accepts_halfperson_anchor() -> None:
    """The shipped roles treat halfperson as a body rectangle."""
    halfperson = _view("halfperson", (0, 0, 100, 150), 1)
    head = _view("head", (30, 5, 70, 45), 2)
    controller = RectRefineFocusController()
    controller.enable(TOKEN)

    result = controller.focus_from_selection(
        [halfperson],
        [halfperson, head],
    )

    assert result is not None
    assert result.member_ids == frozenset((halfperson.shape_id, head.shape_id))


def test_controller_uses_injected_custom_roles() -> None:
    """User-configured body labels replace shipped body labels."""
    roles = RectRefineLabelRoles(
        body=frozenset(("upper_body",)),
        head=frozenset(("head",)),
        face=frozenset(("face",)),
    )
    upper_body = _view("upper_body", (0, 0, 100, 150), 1)
    person = _view("person", (0, 0, 100, 200), 2)
    head = _view("head", (30, 5, 70, 45), 3)
    controller = RectRefineFocusController(label_roles=roles)
    controller.enable(TOKEN)

    assert (
        controller.focus_from_selection(
            [upper_body],
            [upper_body, person, head],
        )
        is not None
    )
    controller.clear_focus()
    assert (
        controller.focus_from_selection(
            [person],
            [upper_body, person, head],
        )
        is None
    )


def test_invalid_selection_leaves_existing_focus_unchanged() -> None:
    """Non-target and multi-selection events do not disturb current focus."""
    person, head = _related_views()
    polygon = _view(
        "halfperson",
        (0, 0, 10, 10),
        3,
        shape_type="polygon",
    )
    controller = RectRefineFocusController()
    controller.enable(TOKEN)
    first = controller.focus_from_selection([person], [person, head])
    assert first is not None

    assert controller.focus_from_selection([polygon], [polygon]) is None
    assert (
        controller.focus_from_selection([person, head], [person, head]) is None
    )
    assert controller.focused_ids == first.member_ids


def test_hidden_or_stale_anchor_is_ignored() -> None:
    """Base-hidden and previous-image Shapes cannot create a focus."""
    hidden = _view("person", (0, 0, 100, 200), 1, visible=False)
    stale = _view("person", (0, 0, 100, 200), 2, token="image-old")
    controller = RectRefineFocusController()
    controller.enable(TOKEN)

    assert controller.focus_from_selection([hidden], [hidden]) is None
    assert controller.focus_from_selection([stale], [stale]) is None
    assert controller.has_focus is False


def test_clear_focus_does_not_disable_mode() -> None:
    """Esc-style clearing forgets members while leaving the mode enabled."""
    person, head = _related_views()
    controller = RectRefineFocusController()
    controller.enable(TOKEN)
    controller.focus_from_selection([person], [person, head])

    assert controller.clear_focus() is True
    assert controller.enabled is True
    assert controller.has_focus is False


def test_successful_image_load_clears_focus_and_updates_token() -> None:
    """A new image invalidates old Shape ids without closing the mode."""
    person, head = _related_views()
    controller = RectRefineFocusController()
    controller.enable(TOKEN)
    controller.focus_from_selection([person], [person, head])

    controller.on_image_loaded("image-2")

    assert controller.enabled is True
    assert controller.image_token == "image-2"
    assert controller.focused_ids is None


def test_disable_clears_focus() -> None:
    """Turning the mode off discards its only transient state."""
    person, head = _related_views()
    controller = RectRefineFocusController()
    controller.enable(TOKEN)
    controller.focus_from_selection([person], [person, head])

    controller.disable()

    assert controller.enabled is False
    assert controller.focused_ids is None
