"""Pure appearance and group-focus behavior tests."""

import logging
from unittest.mock import patch

from anylabeling.views.labeling.widgets.appearance import (
    ACCESSIBLE_PALETTE,
    AppearanceSettings,
    ColorMode,
    GroupFocusController,
    ShapeVisualContext,
    resolve_render_decision,
    color_for_key,
    is_valid_group_id,
    resolve_base_color,
)
from anylabeling.views.labeling.widgets.appearance.config import (
    clear_project_palette_cache,
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


def test_focus_controller_uses_configured_unrelated_opacity_boundaries():
    """Focus dimming follows the configured value, including its bounds."""
    controller = GroupFocusController()
    controller.update("image-a", [{"id": "a", "group_id": 3}])
    unrelated = {"group_id": 4}

    assert controller.emphasis(unrelated, 0.08) == 0.08
    assert controller.emphasis(unrelated, -1) == 0.0
    assert controller.emphasis(unrelated, 2) == 1.0
    assert controller.emphasis({"group_id": 3}, 0.08) == 1.0


def test_render_policy_applies_focus_zero_opacity_and_label_gates():
    """Final render decisions hide all ordinary channels at zero opacity."""
    context = ShapeVisualContext(
        shape_token="other",
        label="person",
        group_id=4,
        selected=False,
        hovered=False,
        focused=False,
    )
    decision = resolve_render_decision(
        context,
        focus_active=True,
        unrelated_opacity=0.0,
        show_labels=True,
        show_gid="always",
    )
    assert not decision.draw_geometry
    assert not decision.draw_text
    assert not decision.draw_gid
    assert not decision.draw_size_overlay
    assert decision.canvas_interactive


def test_render_policy_isolation_excludes_hidden_shapes_from_hit_testing():
    """Isolation hides excluded shapes and removes them from Canvas hits."""
    context = ShapeVisualContext(
        shape_token="other",
        label="person",
        group_id=4,
    )
    decision = resolve_render_decision(
        context,
        isolation_enabled=True,
        isolation_group_id=8,
    )
    assert not decision.draw_geometry
    assert not decision.draw_text
    assert not decision.canvas_interactive


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
    clear_project_palette_cache()
    assert load_project_palette(str(tmp_path))["person"] == (1, 2, 3)


def test_missing_project_sidecar_is_silent_and_cached(tmp_path, caplog):
    """An optional sidecar may be absent without warning or repeated I/O."""
    clear_project_palette_cache()
    path = str(tmp_path)
    with patch(
        "builtins.open",
        side_effect=FileNotFoundError(2, "No such file or directory"),
    ) as mocked_open:
        with caplog.at_level(
            logging.WARNING,
            logger="anylabeling.views.labeling.widgets.appearance.config",
        ):
            assert load_project_palette(path) == {}
            assert load_project_palette(path) == {}
    assert mocked_open.call_count == 1
    assert not caplog.records


def test_unc_missing_project_sidecar_is_non_blocking(caplog):
    """A missing UNC sidecar follows the same optional-file fallback."""
    clear_project_palette_cache()
    root = r"\\server\share\dataset\images"
    with patch(
        "builtins.open",
        side_effect=FileNotFoundError(2, "No such file or directory"),
    ):
        with caplog.at_level(
            logging.WARNING,
            logger="anylabeling.views.labeling.widgets.appearance.config",
        ):
            assert load_project_palette(root) == {}
    assert not caplog.records


def test_invalid_project_sidecar_payload_warns_and_falls_back(
    tmp_path, caplog
):
    """Malformed versions and channels never escape the loader."""
    sidecar = tmp_path / ".xanylabeling" / "appearance.yaml"
    sidecar.parent.mkdir()
    sidecar.write_text(
        "schema_version: 99\nlabel_colors:\n  person: [1, 2, 3]\n",
        encoding="utf-8",
    )
    clear_project_palette_cache()
    with caplog.at_level(
        logging.WARNING,
        logger="anylabeling.views.labeling.widgets.appearance.config",
    ):
        assert load_project_palette(str(tmp_path)) == {}
    assert "unsupported schema_version" in caplog.text

    sidecar.write_text(
        "schema_version: 1\nlabel_colors: [bad]\n",
        encoding="utf-8",
    )
    clear_project_palette_cache()
    with caplog.at_level(
        logging.WARNING,
        logger="anylabeling.views.labeling.widgets.appearance.config",
    ):
        assert load_project_palette(str(tmp_path)) == {}
    assert "label_colors must be a mapping" in caplog.text

    sidecar.write_text(
        "schema_version: 1\n"
        "label_colors:\n"
        "  person: [1, 2, 3]\n"
        "  invalid: [true, 2, 3]\n",
        encoding="utf-8",
    )
    clear_project_palette_cache()
    assert load_project_palette(str(tmp_path)) == {"person": (1, 2, 3)}


def test_saving_project_palette_refreshes_cached_values(tmp_path):
    """A successful save makes the new palette visible immediately."""
    clear_project_palette_cache()
    sidecar = tmp_path / ".xanylabeling" / "appearance.yaml"
    sidecar.parent.mkdir()
    sidecar.write_text(
        "schema_version: 1\nlabel_colors:\n  old: [1, 2, 3]\n",
        encoding="utf-8",
    )
    assert load_project_palette(str(tmp_path)) == {"old": (1, 2, 3)}
    save_project_palette(str(tmp_path), {"new": (4, 5, 6)})
    assert load_project_palette(str(tmp_path)) == {"new": (4, 5, 6)}


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
