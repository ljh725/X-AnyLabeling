"""Tests for focus/idle and feature-state version contracts."""

from dataclasses import dataclass

import pytest

from anylabeling.services.behavior_analytics import (
    ActivityTracker,
    DEFAULT_FEATURE_KEYS,
    FeatureRegistry,
    FeatureState,
    FeatureStateTracker,
)


@dataclass
class Reading:
    """Minimal clock reading for state-machine tests."""

    occurred_at_utc: str = "2026-08-20T00:00:00Z"
    local_date: str = "2026-08-20"
    timezone_offset: str = "+08:00"
    monotonic_ms: int = 0


def test_activity_tracker_excludes_focus_and_idle_intervals():
    """Focus loss and inactivity produce explicit state transitions."""
    tracker = ActivityTracker(idle_threshold_ms=100)
    assert tracker.input_received(Reading(monotonic_ms=10)) == []
    idle = tracker.observe(Reading(monotonic_ms=110))
    assert [(item.kind, item.value) for item in idle] == [("idle", True)]
    resumed = tracker.input_received(Reading(monotonic_ms=120))
    assert [(item.kind, item.value) for item in resumed] == [("idle", False)]
    focus = tracker.focus_changed(False, Reading(monotonic_ms=130))
    assert [(item.kind, item.value) for item in focus] == [("focused", False)]


def test_activity_tracker_requires_positive_threshold():
    """An invalid threshold cannot silently produce active-time errors."""
    with pytest.raises(ValueError, match="positive"):
        ActivityTracker(idle_threshold_ms=0)


def test_feature_snapshot_starts_at_version_one():
    """Known startup state is recorded at version one."""
    tracker = FeatureStateTracker()
    snapshot = tracker.start_snapshot(
        {"rectangle_refinement": FeatureState(True, True)}
    )
    assert snapshot["version"] == 1
    assert snapshot["state_unknown"] is False
    assert snapshot["features"]["rectangle_refinement"]["active"] is True


def test_feature_registry_has_stable_behavior_allow_list():
    """The registry excludes unregistered appearance-only settings."""
    registry = FeatureRegistry()
    assert registry.keys == DEFAULT_FEATURE_KEYS
    filtered = registry.filter(
        {
            "rectangle_refinement": FeatureState(True, True),
            "theme_color": FeatureState(True, True),
        }
    )
    assert set(filtered) == {"rectangle_refinement"}


def test_feature_change_is_one_version_for_one_transaction():
    """Multiple effective changes share one increment and no-op is stable."""
    tracker = FeatureStateTracker()
    tracker.start_snapshot(
        {
            "edit_mode": FeatureState(True, True),
            "rectangle_refinement": FeatureState(False, False),
        }
    )
    change = tracker.apply_changes(
        {
            "edit_mode": FeatureState(True, False),
            "rectangle_refinement": FeatureState(True, True),
        }
    )
    assert change["version"] == 2
    assert set(change["changes"]) == {
        "edit_mode",
        "rectangle_refinement",
    }
    assert tracker.apply_changes(tracker.features) is None


def test_unknown_snapshot_uses_version_zero():
    """Missing startup state is explicit and cannot enter feature comparisons."""
    tracker = FeatureStateTracker()
    assert tracker.start_snapshot(None) == {
        "version": 0,
        "state_unknown": True,
        "features": {},
    }
    assert tracker.reference() == {
        "feature_state_version": 0,
        "state_unknown": True,
    }


def test_mark_used_does_not_change_effective_state_version():
    """Usage evidence is tracked separately from configured/active changes."""
    tracker = FeatureStateTracker()
    tracker.start_snapshot({"ai_active": FeatureState(True, True)})
    assert tracker.mark_used("ai_active") is True
    assert tracker.version == 1
    assert tracker.features["ai_active"].used is True
