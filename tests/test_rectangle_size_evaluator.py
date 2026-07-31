"""Tests for the pure configurable rectangle-size evaluator."""

import math

import pytest

from anylabeling.views.labeling.rectangle_size import (
    RectangleCandidate,
    RectangleSizeEvaluator,
    RectangleSizeRule,
)


def _candidate(
    label: str,
    width: float,
    height: float,
    index: int = 0,
    *,
    shape_type: str = "rectangle",
    interactive: bool = True,
) -> RectangleCandidate:
    """Build a deterministic candidate with origin-based geometry."""
    return RectangleCandidate(
        candidate_id=("image-1", index),
        shape_index=index,
        label=label,
        shape_type=shape_type,
        bbox=(0.0, 0.0, width, height),
        interactive=interactive,
    )


def test_actual_value_below_or_equal_to_threshold_is_abnormal() -> None:
    """Both lower and equal values must fail the configured minimum."""
    evaluator = RectangleSizeEvaluator(
        [RectangleSizeRule(label="face", min_width_px=10.0)]
    )

    below = evaluator.evaluate_candidate(_candidate("face", 9.9, 20.0))
    equal = evaluator.evaluate_candidate(_candidate("face", 10.0, 20.0))
    greater = evaluator.evaluate_candidate(_candidate("face", 10.1, 20.0))

    assert below is not None
    assert equal is not None
    assert greater is None


def test_empty_dimension_does_not_participate() -> None:
    """An unset height threshold cannot make a width-only rule fail."""
    evaluator = RectangleSizeEvaluator(
        [RectangleSizeRule(label="face", min_width_px=10.0)]
    )

    issue = evaluator.evaluate_candidate(_candidate("face", 8.0, 1.0))

    assert issue is not None
    assert tuple(item.dimension for item in issue.violations) == ("width",)


def test_any_mode_triggers_when_one_dimension_fails() -> None:
    """Any mode reports the candidate when either configured dimension fails."""
    evaluator = RectangleSizeEvaluator(
        [
            RectangleSizeRule(
                label="person",
                min_width_px=24.0,
                min_height_px=48.0,
                trigger_mode="any",
            )
        ]
    )

    issue = evaluator.evaluate_candidate(_candidate("person", 20.0, 60.0))

    assert issue is not None
    assert tuple(item.dimension for item in issue.violations) == ("width",)


def test_all_mode_requires_every_configured_dimension_to_fail() -> None:
    """All mode preserves the legacy both-dimensions-small behavior."""
    evaluator = RectangleSizeEvaluator(
        [
            RectangleSizeRule(
                label="person",
                min_width_px=36.0,
                min_height_px=36.0,
                trigger_mode="all",
            )
        ]
    )

    assert (
        evaluator.evaluate_candidate(_candidate("person", 20.0, 60.0)) is None
    )
    issue = evaluator.evaluate_candidate(_candidate("person", 20.0, 30.0))

    assert issue is not None
    assert tuple(item.dimension for item in issue.violations) == (
        "width",
        "height",
    )


def test_single_configured_dimension_works_in_all_mode() -> None:
    """All mode with one configured dimension behaves like that dimension."""
    evaluator = RectangleSizeEvaluator(
        [
            RectangleSizeRule(
                label="head",
                min_height_px=12.0,
                trigger_mode="all",
            )
        ]
    )

    assert evaluator.evaluate_candidate(_candidate("head", 50.0, 12.0))
    assert evaluator.evaluate_candidate(_candidate("head", 50.0, 12.1)) is None


def test_issue_contains_raw_float_metrics_and_thresholds() -> None:
    """Evaluation preserves raw float measurements in deterministic order."""
    evaluator = RectangleSizeEvaluator(
        [
            RectangleSizeRule(
                label="head",
                min_width_px=12.5,
                min_height_px=14.5,
            )
        ]
    )

    issue = evaluator.evaluate_candidate(_candidate("head", 12.25, 14.5))

    assert issue is not None
    assert issue.width == 12.25
    assert issue.height == 14.5
    assert tuple(
        (item.dimension, item.actual_px, item.threshold_px)
        for item in issue.violations
    ) == (
        ("width", 12.25, 12.5),
        ("height", 14.5, 14.5),
    )


def test_evaluate_reports_multiple_labels_in_candidate_order() -> None:
    """One indexed rule set can report several categories simultaneously."""
    evaluator = RectangleSizeEvaluator(
        [
            RectangleSizeRule(label="person", min_width_px=24.0),
            RectangleSizeRule(label="head", min_height_px=12.0),
            RectangleSizeRule(label="face", min_width_px=10.0),
        ]
    )
    candidates = [
        _candidate("head", 20.0, 8.0, 2),
        _candidate("unconfigured", 1.0, 1.0, 3),
        _candidate("person", 20.0, 100.0, 4),
        _candidate("face", 10.0, 20.0, 5),
    ]

    issues = evaluator.evaluate(candidates)

    assert tuple(issue.label for issue in issues) == (
        "head",
        "person",
        "face",
    )
    assert tuple(issue.shape_index for issue in issues) == (2, 4, 5)


@pytest.mark.parametrize(
    ("shape_type", "interactive", "label"),
    [
        ("polygon", True, "person"),
        ("rectangle", False, "person"),
        ("rectangle", True, "Person"),
    ],
)
def test_non_target_candidates_are_skipped(
    shape_type: str,
    interactive: bool,
    label: str,
) -> None:
    """Type, visibility, and exact-case label gates are all enforced."""
    evaluator = RectangleSizeEvaluator(
        [RectangleSizeRule(label="person", min_width_px=24.0)]
    )

    issue = evaluator.evaluate_candidate(
        _candidate(
            label,
            1.0,
            1.0,
            shape_type=shape_type,
            interactive=interactive,
        )
    )

    assert issue is None


def test_disabled_rule_does_not_participate() -> None:
    """A disabled rule is omitted from the exact-label lookup."""
    evaluator = RectangleSizeEvaluator(
        [
            RectangleSizeRule(
                label="person",
                min_width_px=24.0,
                enabled=False,
            )
        ]
    )

    assert evaluator.evaluate_candidate(_candidate("person", 1.0, 1.0)) is None


def test_reversed_bbox_still_produces_positive_dimensions() -> None:
    """Defensive absolute differences handle reversed snapshot coordinates."""
    evaluator = RectangleSizeEvaluator(
        [RectangleSizeRule(label="person", min_width_px=25.0)]
    )
    candidate = RectangleCandidate(
        candidate_id=("image-1", 0),
        shape_index=0,
        label="person",
        shape_type="rectangle",
        bbox=(30.0, 40.0, 10.0, 20.0),
    )

    issue = evaluator.evaluate_candidate(candidate)

    assert issue is not None
    assert issue.width == 20.0
    assert issue.height == 20.0


def test_non_finite_candidate_geometry_is_skipped() -> None:
    """NaN or infinite geometry cannot create a drawable issue."""
    evaluator = RectangleSizeEvaluator(
        [RectangleSizeRule(label="person", min_width_px=25.0)]
    )
    candidates = [
        RectangleCandidate(
            candidate_id=("image-1", 0),
            shape_index=0,
            label="person",
            shape_type="rectangle",
            bbox=(0.0, 0.0, math.nan, 20.0),
        ),
        RectangleCandidate(
            candidate_id=("image-1", 1),
            shape_index=1,
            label="person",
            shape_type="rectangle",
            bbox=(0.0, 0.0, math.inf, 20.0),
        ),
    ]

    assert evaluator.evaluate(candidates) == ()


def test_duplicate_enabled_label_is_rejected() -> None:
    """Duplicate enabled labels fail fast instead of choosing silently."""
    rules = [
        RectangleSizeRule(label="person", min_width_px=24.0),
        RectangleSizeRule(label="person", min_height_px=48.0),
    ]

    with pytest.raises(ValueError, match="Duplicate enabled"):
        RectangleSizeEvaluator(rules)


@pytest.mark.parametrize(
    "rule",
    [
        RectangleSizeRule(label="", min_width_px=10.0),
        RectangleSizeRule(label=" face ", min_width_px=10.0),
        RectangleSizeRule(label="face"),
        RectangleSizeRule(label="face", min_width_px=0.0),
        RectangleSizeRule(label="face", min_width_px=-1.0),
        RectangleSizeRule(label="face", min_width_px=math.nan),
        RectangleSizeRule(label="face", min_width_px=math.inf),
        RectangleSizeRule(label="face", min_width_px=True),
        RectangleSizeRule(
            label="face",
            min_width_px=10.0,
            trigger_mode="invalid",
        ),
    ],
)
def test_invalid_enabled_rule_is_rejected(rule: RectangleSizeRule) -> None:
    """Domain-invalid enabled rules cannot enter the compiled lookup."""
    with pytest.raises(ValueError):
        RectangleSizeEvaluator([rule])


def test_invalid_disabled_rule_is_ignored() -> None:
    """Disabled draft rows do not block evaluation of valid active rules."""
    evaluator = RectangleSizeEvaluator(
        [
            RectangleSizeRule(label="", enabled=False),
            RectangleSizeRule(label="person", min_width_px=24.0),
        ]
    )

    assert evaluator.evaluate_candidate(_candidate("person", 20.0, 50.0))
