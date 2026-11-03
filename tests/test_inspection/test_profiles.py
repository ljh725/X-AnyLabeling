from anylabeling.services.inspection.models import RuleConfig
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
