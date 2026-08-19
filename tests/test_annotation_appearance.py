"""Pure appearance and group-focus behavior tests."""

from anylabeling.views.labeling.widgets.appearance import (
    ACCESSIBLE_PALETTE,
    AppearanceSettings,
    ColorMode,
    GroupFocusController,
    color_for_key,
    is_valid_group_id,
    resolve_base_color,
)
from anylabeling.views.labeling.widgets.appearance.config import (
    load_project_palette,
    load_user_appearance,
    save_project_palette,
)


def test_group_id_validation_excludes_bool_negative_and_none():
    """Only non-negative integer ids are group identities."""
    assert is_valid_group_id(0)
    assert is_valid_group_id(12)
    assert not is_valid_group_id(False)
    assert not is_valid_group_id(-1)
    assert not is_valid_group_id(None)


def test_palette_never_returns_reserved_black_entry_for_group_zero():
    """Group zero gets a visible deterministic color."""
    assert color_for_key(0) != (0, 0, 0)
    assert resolve_base_color(ColorMode.GROUP, "person", 0) != (0, 0, 0)


def test_modes_are_stable_and_label_palette_wins_in_label_mode():
    """Label mode uses the project palette while other modes stay deterministic."""
    colors = {"person": (1, 2, 3)}
    assert resolve_base_color("label", "person", 1, label_colors=colors) == (
        1,
        2,
        3,
    )
    assert resolve_base_color("uniform", "person", 1) == resolve_base_color(
        "uniform", "head", 99
    )
    assert resolve_base_color(
        "instance", "person", 1, "shape-a"
    ) == resolve_base_color("instance", "person", 1, "shape-a")
    assert resolve_base_color("group", "person", 7) == color_for_key(7)
    assert resolve_base_color("instance", "person", 7, "shape-a") == (
        color_for_key("shape-a")
    )


def test_appearance_settings_clamp_loaded_values():
    """Malformed persisted opacity values are bounded at the model boundary."""
    settings = AppearanceSettings(
        color_mode="group",
        normal_fill_opacity=999,
        selected_fill_opacity=-4,
        unrelated_opacity=2,
        show_gid="invalid",
    )
    assert settings.color_mode is ColorMode.GROUP
    assert settings.normal_fill_opacity == 255
    assert settings.selected_fill_opacity == 0
    assert settings.unrelated_opacity == 1.0
    assert settings.show_gid == "focus"


def test_focus_controller_supports_same_group_multi_select_and_clears_mixed():
    """Focus is retained for one group and exits for mixed semantics."""
    controller = GroupFocusController()
    same_group = [
        {"id": "person", "group_id": 3},
        {"id": "head", "group_id": 3},
    ]
    assert controller.update("image-a", same_group).focused_group_id == 3
    assert controller.emphasis({"group_id": 3}) == 1.0
    assert controller.emphasis({"group_id": 4}) < 1.0
    mixed = [{"id": "a", "group_id": 3}, {"id": "b", "group_id": 4}]
    assert controller.update("image-a", mixed).focused_group_id is None


def test_focus_controller_resets_when_image_changes():
    """Repeated group ids on another image do not inherit stale focus."""
    controller = GroupFocusController()
    controller.update("image-a", [{"id": "a", "group_id": 1}])
    state = controller.reset_image("image-b")
    assert state.focused_group_id is None
    assert state.image_token == "image-b"


def test_legacy_config_and_project_sidecar_round_trip(tmp_path):
    """Legacy keys migrate in memory and project colors stay outside JSON."""
    settings = load_user_appearance(
        {"shape_color": "manual", "label_colors": {"person": [1, 2, 3]}}
    )
    assert settings.color_mode is ColorMode.LABEL
    path = save_project_palette(str(tmp_path), {"person": (1, 2, 3)})
    assert path.endswith("appearance.yaml")
    assert load_project_palette(str(tmp_path))["person"] == (1, 2, 3)


def test_ten_group_review_has_one_focus_and_neutral_unrelated_emphasis():
    """Ten visible groups do not require ten simultaneous attention colors."""
    controller = GroupFocusController()
    shapes = [{"id": str(index), "group_id": index} for index in range(10)]
    state = controller.update("image", [shapes[4]])
    assert state.focused_group_id == 4
    assert controller.emphasis(shapes[4]) == 1.0
    assert sum(controller.emphasis(shape) < 1.0 for shape in shapes) == 9


def test_invalid_group_boundaries_and_palette_cycles_are_deterministic():
    """Invalid ids use safe fallback colors and large sets remain bounded."""
    for group_id in (None, -1, False):
        assert resolve_base_color(ColorMode.GROUP, "person", group_id) != (
            0,
            0,
            0,
        )
    colors = {color_for_key(index) for index in range(100)}
    assert len(colors) <= len(ACCESSIBLE_PALETTE)


def test_focus_keeps_person_head_face_group_together_and_cleans_cross_image():
    """Related object classes share emphasis while image switches clear it."""
    controller = GroupFocusController()
    related = [
        {"id": "person", "label": "person", "group_id": 8},
        {"id": "head", "label": "head", "group_id": 8},
        {"id": "face", "label": "face", "group_id": 8},
    ]
    controller.update("image-a", [related[0]])
    assert all(controller.emphasis(shape) == 1.0 for shape in related)
    assert controller.emphasis({"group_id": 9, "hidden": True}) < 1.0
    controller.reset_image("image-b")
    assert not controller.state.active
    assert controller.emphasis(related[0]) == 1.0
