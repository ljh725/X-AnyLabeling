"""Tests for immutable rectangle-size validation contracts."""

from dataclasses import FrozenInstanceError

import pytest

from anylabeling.views.labeling.rectangle_size import (
    DimensionViolation,
    RectangleCandidate,
    RectangleSizeIssue,
    RectangleSizeRule,
)


def test_rule_supports_independent_optional_dimensions() -> None:
    """A rule may configure only one dimension without sentinel values."""
    rule = RectangleSizeRule(label="face", min_width_px=10.0)

    assert rule.min_width_px == 10.0
    assert rule.min_height_px is None
    assert rule.trigger_mode == "any"
    assert rule.enabled is True


def test_candidate_uses_plain_python_geometry() -> None:
    """A candidate stores a tuple bbox without Qt geometry objects."""
    candidate = RectangleCandidate(
        candidate_id=("image-1", 3),
        shape_index=3,
        label="person",
        shape_type="rectangle",
        bbox=(10.5, 20.25, 40.75, 90.0),
    )

    assert candidate.bbox == (10.5, 20.25, 40.75, 90.0)
    assert candidate.interactive is True


def test_issue_aggregates_width_and_height_violations() -> None:
    """One issue can carry both failed dimensions for one rectangle."""
    violations = (
        DimensionViolation(
            dimension="width",
            actual_px=20.0,
            threshold_px=24.0,
        ),
        DimensionViolation(
            dimension="height",
            actual_px=35.0,
            threshold_px=48.0,
        ),
    )
    issue = RectangleSizeIssue(
        candidate_id=("image-1", 2),
        shape_index=2,
        label="person",
        bbox=(0.0, 0.0, 20.0, 35.0),
        width=20.0,
        height=35.0,
        violations=violations,
    )

    assert issue.violations == violations
    assert tuple(item.dimension for item in issue.violations) == (
        "width",
        "height",
    )


def test_models_are_immutable_snapshots() -> None:
    """Frozen contracts reject accidental runtime mutation."""
    rule = RectangleSizeRule(label="head", min_height_px=12.0)

    with pytest.raises(FrozenInstanceError):
        rule.min_height_px = 20.0
