from anylabeling.services.inspection.models import RuleConfig
from anylabeling.services.inspection.parameters import (
    describe_rule_parameters,
    validate_rule_parameters,
)
from anylabeling.services.inspection.profiles import (
    build_default_catalog,
    copy_builtin,
    default_profiles,
    effective_profile_snapshot,
    load_profile,
    prepare_profile,
    save_profile,
    validate_profile,
)


def test_builtin_profiles_cover_three_scenarios():
    profiles = {profile.profile_id: profile for profile in default_profiles()}
    assert set(profiles) == {"generic", "screen_corners", "classroom_actions"}
    assert profiles["generic"].stage == "post_label"
    assert profiles["screen_corners"].stage == "in_progress"
    assert any(
        rule.rule_id == "duplicate_boxes"
        for rule in profiles["generic"].enabled_rules
    )


def test_copy_builtin_is_independent_and_round_trips(tmp_path):
    catalog = build_default_catalog()
    source = default_profiles()[0]
    copied = copy_builtin(source, "custom-1", "项目方案")
    assert copied.builtin is False
    assert copied.profile_id == "custom-1"
    assert copied.rules == source.rules
    path = tmp_path / "profile.json"
    save_profile(str(path), copied)
    loaded = load_profile(str(path))
    assert loaded == copied
    assert validate_profile(loaded, catalog).valid is True


def test_effective_snapshot_freezes_rule_versions():
    catalog = build_default_catalog()
    snapshot = effective_profile_snapshot(default_profiles()[0], catalog)
    assert snapshot["snapshot_digest"]
    duplicate = next(
        rule
        for rule in snapshot["rules"]
        if rule["rule_id"] == "duplicate_boxes"
    )
    assert duplicate["implementation_version"] == "1.0.0"
    assert duplicate["registered"] is True


def test_prepare_profile_disables_only_missing_rules():
    catalog = build_default_catalog()
    source = default_profiles()[0]
    profile = type(source).from_dict(
        {
            **source.to_dict(),
            "rules": [
                {"rule_id": "label_required"},
                {"rule_id": "future_rule"},
            ],
        }
    )
    prepared, validation = prepare_profile(profile, catalog)
    assert validation.missing_rule_ids == ("future_rule",)
    assert [rule.rule_id for rule in prepared.enabled_rules] == [
        "label_required"
    ]


def test_rule_config_rejects_malformed_payload():
    try:
        RuleConfig.from_dict({"parameters": {}})
    except ValueError:
        pass
    else:
        raise AssertionError("missing rule_id must be rejected")


def test_parameter_ranges_and_unknown_fields_are_rejected():
    assert validate_rule_parameters("duplicate_boxes", {"max_pairs": -1})
    assert any(
        "不能小于" in error
        for error in validate_rule_parameters(
            "duplicate_boxes", {"max_pairs": -1}
        )
    )
    assert any(
        "必须是整数" in error
        for error in validate_rule_parameters(
            "duplicate_boxes", {"max_pairs": "5000"}
        )
    )
    assert any(
        "有限" in error
        for error in validate_rule_parameters(
            "legacy_same_group_duplicate",
            {"edge_tolerance_px": float("inf")},
        )
    )
    assert any(
        "未知参数" in error
        for error in validate_rule_parameters(
            "label_required", {"unexpected": 1}
        )
    )
    assert validate_rule_parameters("duplicate_boxes", {"max_pairs": 5000}) == ()
    assert validate_rule_parameters(
        "legacy_same_group_duplicate", {"edge_tolerance_px": 2.0}
    ) == ()
    assert any(
        "取值必须是" in error
        for error in validate_rule_parameters(
            "duplicate_boxes", {"preset": "extreme"}
        )
    )


def test_cross_field_and_threshold_parameters_are_validated():
    errors = validate_rule_parameters(
        "count_constraint",
        {"counts": {"person": {"min": 5, "max": 2, "scope": "image"}}},
    )
    assert any("min 不能大于 max" in error for error in errors)

    errors = validate_rule_parameters(
        "classroom_relation", {"min_overlap": 1.5}
    )
    assert errors

    errors = validate_rule_parameters("duplicate_boxes", {"thresholds": {"iou": 1}})
    assert any("无效" in error for error in errors)

    errors = validate_rule_parameters(
        "corner_completeness", {"corner_labels": {"unknown_corner": "x"}}
    )
    assert any("未知键" in error for error in errors)


def test_profile_with_invalid_parameter_cannot_run():
    catalog = build_default_catalog()
    source = default_profiles()[0]
    payload = source.to_dict()
    payload["rules"] = [
        {"rule_id": "duplicate_boxes", "parameters": {"max_pairs": -1}}
    ]
    profile = type(source).from_dict(payload)
    validation = validate_profile(profile, catalog)
    assert validation.valid is False
    assert any("max_pairs" in error for error in validation.errors)
    prepared, validation = prepare_profile(profile, catalog)
    assert validation.valid is False
    assert prepared is profile


def test_rule_metadata_exposes_dependencies_and_parameter_docs():
    catalog = build_default_catalog()
    duplicate = catalog.meta("duplicate_boxes")
    assert duplicate is not None
    assert "shapes.points" in duplicate.depends_on
    described = describe_rule_parameters("duplicate_boxes")
    names = {item["name"] for item in described}
    assert {"preset", "thresholds", "relations", "max_pairs"} == names


def test_effective_snapshot_digest_is_stable_across_runs():
    catalog = build_default_catalog()
    profile = default_profiles()[0]
    first = effective_profile_snapshot(profile, catalog)["snapshot_digest"]
    second = effective_profile_snapshot(profile, catalog)["snapshot_digest"]
    assert first == second
    # A fresh process rebuilds the built-in profile with new timestamps; that
    # must not invalidate the frozen configuration identity.
    from dataclasses import replace as dataclass_replace

    restarted = dataclass_replace(
        default_profiles()[0],
        created_at="2030-01-01T00:00:00+00:00",
        updated_at="2030-01-01T00:00:00+00:00",
    )
    third = effective_profile_snapshot(restarted, build_default_catalog())[
        "snapshot_digest"
    ]
    assert third == first
