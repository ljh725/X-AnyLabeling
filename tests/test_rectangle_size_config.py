"""Tests for rectangle-size rule configuration and legacy migration."""

import math
from pathlib import Path

import pytest
import yaml

from anylabeling.views.labeling.rectangle_size import (
    RectangleSizeConfigError,
    RectangleSizeRule,
    load_rectangle_size_rules,
    migrate_legacy_person_rule,
    parse_rectangle_size_rules,
    serialize_rectangle_size_rules,
)


def test_default_config_contains_migrated_person_combination_rule() -> None:
    """Bundled defaults preserve the old both-dimensions trigger structure."""
    path = Path("anylabeling/configs/xanylabeling_config.yaml")
    config = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert config["show_rectangle_size_violations"] is False
    rules = load_rectangle_size_rules(config)
    assert rules == (
        RectangleSizeRule(
            label="person",
            min_width_px=36.0,
            min_height_px=36.0,
            trigger_mode="all",
            enabled=True,
        ),
    )


def test_missing_rule_key_migrates_custom_legacy_threshold() -> None:
    """An old config receives a both-dimensions person rule."""
    rules = load_rectangle_size_rules(
        {"show_rectangle_pixels": True},
        legacy_person_threshold_px=42,
    )

    assert rules == (
        RectangleSizeRule(
            label="person",
            min_width_px=42.0,
            min_height_px=42.0,
            trigger_mode="all",
            enabled=True,
        ),
    )


def test_explicit_empty_rule_list_remains_empty() -> None:
    """An explicit empty list disables every category without migration."""
    assert load_rectangle_size_rules({"rectangle_size_rules": []}) == ()


def test_parse_normalizes_labels_numbers_and_empty_dimensions() -> None:
    """Persisted strings become trimmed labels, floats, and optional None."""
    rules = parse_rectangle_size_rules(
        [
            {
                "label": " face ",
                "min_width_px": "10.5",
                "min_height_px": " ",
            }
        ]
    )

    assert rules == (
        RectangleSizeRule(
            label="face",
            min_width_px=10.5,
            min_height_px=None,
            trigger_mode="any",
            enabled=True,
        ),
    )


def test_disabled_rule_may_keep_both_dimensions_empty() -> None:
    """A disabled editable row may persist without active thresholds."""
    rules = parse_rectangle_size_rules([{"label": "face", "enabled": False}])

    assert rules == (RectangleSizeRule(label="face", enabled=False),)


def test_serialization_is_deterministic_and_round_trips() -> None:
    """Serialization emits stable keys and preserves normalized rule values."""
    rules = (
        RectangleSizeRule(
            label="person",
            min_width_px=24.0,
            min_height_px=48.0,
            trigger_mode="any",
        ),
        RectangleSizeRule(
            label="head",
            min_width_px=None,
            min_height_px=12.0,
            trigger_mode="all",
            enabled=False,
        ),
    )

    serialized = serialize_rectangle_size_rules(rules)

    assert list(serialized[0]) == [
        "label",
        "min_width_px",
        "min_height_px",
        "trigger_mode",
        "enabled",
    ]
    assert parse_rectangle_size_rules(serialized) == rules


@pytest.mark.parametrize(
    "raw_rules",
    [
        None,
        {},
        "person",
        [None],
        [{"label": "person", "unknown": 1, "min_width_px": 10}],
        [{"label": "", "min_width_px": 10}],
        [{"label": 123, "min_width_px": 10}],
        [{"label": "person", "enabled": "yes", "min_width_px": 10}],
        [{"label": "person", "trigger_mode": "either", "min_width_px": 10}],
        [{"label": "person"}],
        [
            {"label": "person", "min_width_px": 10},
            {"label": " person ", "min_height_px": 20},
        ],
    ],
)
def test_invalid_rule_structure_is_rejected(raw_rules: object) -> None:
    """Malformed persisted rows fail before replacing active runtime rules."""
    with pytest.raises(RectangleSizeConfigError):
        parse_rectangle_size_rules(raw_rules)


@pytest.mark.parametrize(
    ("raw_rules", "code", "row_index", "field_name"),
    [
        (
            [{"label": "", "min_width_px": 10}],
            "empty_label",
            0,
            "label",
        ),
        (
            [
                {"label": "person", "min_width_px": 10},
                {"label": "person", "min_height_px": 20},
            ],
            "duplicate_label",
            1,
            "label",
        ),
        (
            [{"label": "person", "min_width_px": 0}],
            "invalid_threshold",
            0,
            "min_width_px",
        ),
        (
            [{"label": "person"}],
            "missing_threshold",
            0,
            None,
        ),
    ],
)
def test_config_errors_expose_stable_localization_metadata(
    raw_rules: object,
    code: str,
    row_index: int,
    field_name: str | None,
) -> None:
    """The pure codec should expose metadata without owning UI language."""
    with pytest.raises(RectangleSizeConfigError) as caught:
        parse_rectangle_size_rules(raw_rules)

    assert caught.value.code == code
    assert caught.value.row_index == row_index
    assert caught.value.field_name == field_name


@pytest.mark.parametrize(
    "threshold",
    [
        True,
        "not-a-number",
        0,
        -1,
        math.nan,
        math.inf,
        -math.inf,
    ],
)
def test_invalid_threshold_is_rejected(threshold: object) -> None:
    """Non-positive or non-finite configured pixel boundaries are invalid."""
    with pytest.raises(RectangleSizeConfigError):
        parse_rectangle_size_rules(
            [{"label": "face", "min_width_px": threshold}]
        )


def test_invalid_legacy_threshold_is_rejected() -> None:
    """Legacy migration cannot introduce an unusable threshold."""
    with pytest.raises(RectangleSizeConfigError):
        migrate_legacy_person_rule(0)


def test_serialization_rejects_invalid_models() -> None:
    """Programmatically constructed invalid models cannot be persisted."""
    with pytest.raises(RectangleSizeConfigError):
        serialize_rectangle_size_rules(
            [RectangleSizeRule(label="face", min_width_px=0)]
        )
