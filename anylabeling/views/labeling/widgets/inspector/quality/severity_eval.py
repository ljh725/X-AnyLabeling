"""
Shared threshold evaluation helpers for L2 rules.

Given a ``RuleThreshold`` (direction + warning/error thresholds +
error_requires) and a primary metric value, decide the resulting
severity.  All cross-rule threshold logic lives here so the 12 L2 rule
classes stay small and focused on metric computation.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from .threshold_profile import RuleThreshold


def evaluate_severity(
    rule: RuleThreshold,
    value: float,
    error_requires_satisfied: bool = False,
    extra_metrics: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Evaluate a primary metric value against a rule's thresholds.

    Returns:
        ``(severity, thresholds_hit)`` where ``severity`` is one of
        ``error`` / ``warning`` / ``info`` / None (no hit), and
        ``thresholds_hit`` is the dict stored on the issue.

    Semantics (per spec section 3):

    - ``higher_is_worse`` / ``lower_is_worse`` / ``higher_abs_is_worse``:
      scalar thresholds. ``error`` only fires when
      ``error_requires`` is empty OR ``error_requires_satisfied`` is True.
    - ``two_sided``: ``warning`` fires outside [min, max]; ``error`` fires
      above ``max`` (upper bound only — the spec says the lower side
      stays at warning).
    """
    direction = rule.direction
    w = rule.warning_threshold
    e = rule.error_threshold

    hit: Dict[str, Any] = {}
    level: Optional[str] = None

    if direction == "two_sided":
        level = _eval_two_sided(value, w, e, rule, error_requires_satisfied)
    else:
        abs_value = abs(value) if direction == "higher_abs_is_worse" else value
        level = _eval_directional(
            abs_value,
            w,
            e,
            direction,
            rule,
            error_requires_satisfied,
        )

    if level is None:
        return None, {}

    hit = {
        "level": level,
        "direction": direction,
        "value": round(float(value), 4),
    }
    if w is not None:
        hit["warning_threshold"] = w
    if e is not None:
        hit["error_threshold"] = e
    if rule.error_requires:
        hit["error_requires"] = list(rule.error_requires)
        hit["error_requires_satisfied"] = bool(error_requires_satisfied)
    return level, hit


def _eval_directional(
    value: float,
    w: Any,
    e: Any,
    direction: str,
    rule: RuleThreshold,
    error_requires_satisfied: bool,
) -> Optional[str]:
    """Eval for higher_is_worse / lower_is_worse / higher_abs_is_worse."""
    higher = direction in ("higher_is_worse", "higher_abs_is_worse")
    sign = 1.0 if higher else -1.0

    # error first (higher priority)
    err_level = _scalar_threshold_value(e)
    if err_level is not None and (sign * value) > (sign * err_level):
        # require second confirmation when configured
        if not rule.error_requires or error_requires_satisfied:
            return "error"
        # error_requires present but not satisfied → fall through to warning

    warn_level = _scalar_threshold_value(w)
    if warn_level is not None and (sign * value) > (sign * warn_level):
        return "warning"
    return None


def _eval_two_sided(
    value: float,
    w: Any,
    e: Any,
    rule: RuleThreshold,
    error_requires_satisfied: bool,
) -> Optional[str]:
    """Eval for two_sided: warning outside [min,max]; error above max."""
    w_min, w_max = _two_sided_bounds(w)
    e_max = _two_sided_max(e)

    # error on the upper bound only (per spec: 过小默认 warning)
    if e_max is not None and value >= e_max:
        if not rule.error_requires or error_requires_satisfied:
            return "error"

    if w_min is not None and value < w_min:
        return "warning"
    if w_max is not None and value > w_max:
        return "warning"
    return None


def _scalar_threshold_value(t: Any) -> Optional[float]:
    """Extract a scalar threshold from a scalar or {key: value} dict."""
    if t is None:
        return None
    if isinstance(t, (int, float)):
        return float(t)
    if isinstance(t, dict):
        for v in t.values():
            if isinstance(v, (int, float)):
                return float(v)
    return None


def _two_sided_bounds(t: Any) -> Tuple[Optional[float], Optional[float]]:
    if t is None:
        return None, None
    if isinstance(t, (int, float)):
        # symmetric scalar: treat as ±t around 0 (rarely used)
        return -float(t), float(t)
    if isinstance(t, dict):
        mn = t.get("min")
        mx = t.get("max")
        return (
            float(mn) if isinstance(mn, (int, float)) else None,
            float(mx) if isinstance(mx, (int, float)) else None,
        )
    return None, None


def _two_sided_max(t: Any) -> Optional[float]:
    if t is None:
        return None
    if isinstance(t, (int, float)):
        return float(t)
    if isinstance(t, dict):
        mx = t.get("max")
        return float(mx) if isinstance(mx, (int, float)) else None
    return None
