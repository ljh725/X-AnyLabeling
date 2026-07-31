"""Pure evaluator for configurable rectangle-size rules."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

from .models import (
    DimensionName,
    DimensionViolation,
    RectangleCandidate,
    RectangleSizeIssue,
    RectangleSizeRule,
)


@dataclass(frozen=True)
class _CompiledRule:
    """Validated rule with deterministic configured-dimension ordering."""

    source: RectangleSizeRule
    thresholds: Tuple[Tuple[DimensionName, float], ...]


class RectangleSizeEvaluator:
    """Evaluate immutable rectangle snapshots against label-specific rules."""

    def __init__(self, rules: Iterable[RectangleSizeRule]) -> None:
        """Compile enabled rules into an exact-label lookup.

        Args:
            rules: Rectangle-size rules to validate and compile.

        Raises:
            ValueError: If an enabled rule is invalid or duplicates a label.
        """
        self.rules = tuple(rules)
        self._rules_by_label = self._compile_rules(self.rules)

    def evaluate(
        self,
        candidates: Iterable[RectangleCandidate],
    ) -> Tuple[RectangleSizeIssue, ...]:
        """Return issues for all matching candidates in input order.

        Args:
            candidates: Current-image rectangle snapshots to evaluate.

        Returns:
            Immutable tuple containing one issue per failed candidate.
        """
        issues = []
        for candidate in candidates:
            issue = self.evaluate_candidate(candidate)
            if issue is not None:
                issues.append(issue)
        return tuple(issues)

    def evaluate_candidate(
        self,
        candidate: RectangleCandidate,
    ) -> Optional[RectangleSizeIssue]:
        """Evaluate one candidate for incremental runtime refresh.

        A configured dimension fails when its actual image-pixel value is
        less than or equal to the configured threshold. Equality is therefore
        abnormal; only a strictly greater value passes.

        Args:
            candidate: Rectangle snapshot to evaluate.

        Returns:
            An aggregated issue, or ``None`` when the candidate is skipped or
            passes its matching rule.
        """
        if candidate.shape_type != "rectangle" or not candidate.interactive:
            return None
        compiled = self._rules_by_label.get(candidate.label)
        if compiled is None:
            return None

        width, height = self._candidate_size(candidate)
        if width is None or height is None:
            return None
        actual_by_dimension = {
            "width": width,
            "height": height,
        }
        violations = tuple(
            DimensionViolation(
                dimension=dimension,
                actual_px=actual_by_dimension[dimension],
                threshold_px=threshold,
            )
            for dimension, threshold in compiled.thresholds
            if actual_by_dimension[dimension] <= threshold
        )

        if compiled.source.trigger_mode == "any":
            triggered = bool(violations)
        else:
            triggered = len(violations) == len(compiled.thresholds)
        if not triggered:
            return None

        return RectangleSizeIssue(
            candidate_id=candidate.candidate_id,
            shape_index=candidate.shape_index,
            label=candidate.label,
            bbox=candidate.bbox,
            width=width,
            height=height,
            violations=violations,
        )

    @classmethod
    def _compile_rules(
        cls,
        rules: Tuple[RectangleSizeRule, ...],
    ) -> Dict[str, _CompiledRule]:
        """Validate and index enabled rules by exact label."""
        compiled = {}
        for rule in rules:
            if not rule.enabled:
                continue
            if not isinstance(rule.label, str) or not rule.label.strip():
                raise ValueError("Enabled rectangle-size rule needs a label")
            if rule.label != rule.label.strip():
                raise ValueError(
                    "Rectangle-size rule labels cannot have surrounding "
                    f"whitespace: {rule.label!r}"
                )
            if rule.trigger_mode not in ("any", "all"):
                raise ValueError(
                    f"Invalid trigger_mode for label {rule.label!r}: "
                    f"{rule.trigger_mode!r}"
                )
            if rule.label in compiled:
                raise ValueError(
                    "Duplicate enabled rectangle-size rule for label "
                    f"{rule.label!r}"
                )

            thresholds = cls._compile_thresholds(rule)
            if not thresholds:
                raise ValueError(
                    "Enabled rectangle-size rule needs at least one threshold: "
                    f"{rule.label!r}"
                )
            compiled[rule.label] = _CompiledRule(
                source=rule,
                thresholds=thresholds,
            )
        return compiled

    @classmethod
    def _compile_thresholds(
        cls,
        rule: RectangleSizeRule,
    ) -> Tuple[Tuple[DimensionName, float], ...]:
        """Return validated thresholds in width-then-height order."""
        thresholds = []
        for dimension, raw_value in (
            ("width", rule.min_width_px),
            ("height", rule.min_height_px),
        ):
            if raw_value is None:
                continue
            threshold = cls._positive_finite_threshold(
                raw_value,
                label=rule.label,
                dimension=dimension,
            )
            thresholds.append((dimension, threshold))
        return tuple(thresholds)

    @staticmethod
    def _positive_finite_threshold(
        value: object,
        *,
        label: str,
        dimension: DimensionName,
    ) -> float:
        """Coerce one threshold or raise a domain-level configuration error."""
        if isinstance(value, bool):
            raise ValueError(
                f"{label!r} {dimension} threshold must be a positive number"
            )
        try:
            threshold = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{label!r} {dimension} threshold must be a positive number"
            ) from exc
        if not math.isfinite(threshold) or threshold <= 0:
            raise ValueError(
                f"{label!r} {dimension} threshold must be a positive number"
            )
        return threshold

    @staticmethod
    def _candidate_size(
        candidate: RectangleCandidate,
    ) -> Tuple[Optional[float], Optional[float]]:
        """Return finite raw width/height or ``(None, None)`` on bad geometry."""
        try:
            x_min, y_min, x_max, y_max = candidate.bbox
            coords = tuple(float(value) for value in candidate.bbox)
        except (TypeError, ValueError):
            return (None, None)
        if len(coords) != 4 or not all(
            math.isfinite(value) for value in coords
        ):
            return (None, None)
        width = abs(float(x_max) - float(x_min))
        height = abs(float(y_max) - float(y_min))
        return (width, height)


__all__ = ["RectangleSizeEvaluator"]
