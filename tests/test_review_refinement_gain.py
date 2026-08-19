"""Tests for the pure-Python rectangle refinement gain helper."""

from __future__ import annotations

import math

from anylabeling.views.labeling.review_refinement.gain import (
    effective_gain,
    effective_image_delta,
    image_delta_multiplier,
    resolve_target_gain,
    target_gain_from_legacy_config,
)


def test_effective_gain_caps_low_zoom_to_target_gain() -> None:
    """Low zoom must not turn a comfortable drag into a large jump."""
    assert effective_gain(0.5, 0.5) == 0.5
    assert effective_image_delta((8.0, 0.0), 0.5, 0.5) == (4.0, 0.0)


def test_effective_gain_preserves_natural_high_zoom_precision() -> None:
    """High zoom keeps its naturally smaller image-space movement."""
    assert effective_gain(4.0, 0.5) == 0.25
    assert effective_image_delta((8.0, 0.0), 4.0, 0.5) == (2.0, 0.0)


def test_image_delta_multiplier_matches_screen_gain_after_transform() -> None:
    """Image-space deltas receive the equivalent post-transform multiplier."""
    assert image_delta_multiplier(0.5, 0.5) == 0.25
    assert image_delta_multiplier(4.0, 0.5) == 1.0


def test_effective_gain_handles_invalid_inputs() -> None:
    """Invalid scale and target values fall back to safe defaults."""
    assert math.isclose(effective_gain(0.0, 0.0), 0.5)
    assert math.isclose(effective_gain(float("nan"), -1), 0.5)


def test_legacy_zoom_config_maps_to_inverse_max_factor() -> None:
    """The shipped legacy zoom default maps to a 0.5 target gain."""
    assert (
        target_gain_from_legacy_config(
            {
                "canvas_precision_mode": "zoom",
                "canvas_precision_max_factor": 2.0,
            }
        )
        == 0.5
    )


def test_new_target_gain_wins_over_legacy_config() -> None:
    """Explicit new configuration has migration precedence."""
    assert (
        target_gain_from_legacy_config(
            {
                "target_gain": 0.4,
                "canvas_precision_mode": "zoom",
                "canvas_precision_max_factor": 2.0,
            }
        )
        == 0.4
    )


def test_resolve_target_gain_reports_legacy_migration() -> None:
    """Runtime resolution exposes whether a migration hint is needed."""
    value, migrated = resolve_target_gain(
        {},
        {
            "canvas_precision_mode": "fixed",
            "canvas_precision_factor": 4,
        },
    )
    assert value == 0.25
    assert migrated is True


def test_resolve_target_gain_prefers_nested_value() -> None:
    """A valid nested value suppresses legacy migration."""
    value, migrated = resolve_target_gain(
        {"target_gain": 0.6},
        {"canvas_precision_mode": "zoom", "canvas_precision_max_factor": 2},
    )
    assert value == 0.6
    assert migrated is False
