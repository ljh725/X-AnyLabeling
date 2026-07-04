"""
Generate ``threshold_suggestion.json`` — a NON-binding suggestion file.

It never modifies the threshold YAML.  ``approval.status`` is always
``pending`` and requires human sign-off before a new profile is cut.

Implements the 9-level priority trigger table from spec section 9.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import os.path as osp
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .feedback import (
    FeedbackParseResult,
    aggregate_by_rule,
    read_review_feedback,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "threshold_suggestion.v1"

# suggested_action enum (spec section 9)
VALID_ACTIONS = {
    "keep_threshold",
    "relax_threshold",
    "tighten_threshold",
    "downgrade_severity",
    "upgrade_severity",
    "rewrite_message",
    "split_rule",
    "disable_as_strong_rule",
    "require_more_review",
    "definition_review",
}


@dataclass
class SuggestionContext:
    """Inputs needed to build suggestions."""

    report_path: str
    feedback_path: str
    base_threshold_profile: str
    target_threshold_profile: str = "v1_after_review"


def generate_threshold_suggestion(
    ctx: SuggestionContext,
    output_path: str,
) -> str:
    """Build and write ``threshold_suggestion.json``.

    Args:
        ctx: paths + profile names.
        output_path: where to write the suggestion JSON.

    Returns:
        the output path.
    """
    report = _load_report(ctx.report_path)
    feedback = read_review_feedback(ctx.feedback_path, strict=False)
    rule_stats = aggregate_by_rule(feedback.rows)

    # join: for each rule that appears in the report's thresholds, build
    # a suggestion using its feedback stats (empty if unreviewed).
    thresholds = report.get("thresholds", {}) or {}
    rule_suggestions: List[Dict[str, Any]] = []
    for rule_id, rule_thresholds in thresholds.items():
        rule_name = _rule_name_from_report(report, rule_id) or rule_id
        stats = rule_stats.get(rule_name, _empty_stats())
        primary_metric = (rule_thresholds or {}).get("primary_metric")
        suggestion = _build_suggestion(
            rule_id=rule_id,
            rule_name=rule_name,
            rule_thresholds=rule_thresholds or {},
            stats=stats,
            issues=_issues_for_rule(report, rule_name),
            primary_metric=primary_metric,
        )
        rule_suggestions.append(suggestion)

    total_reviewed = sum(
        s["review_stats"]["reviewed_count"] for s in rule_suggestions
    )
    ready = sum(
        1
        for s in rule_suggestions
        if s["suggested_action"]
        not in ("require_more_review", "keep_threshold")
    )
    need_more = sum(
        1
        for s in rule_suggestions
        if s["suggested_action"] == "require_more_review"
    )

    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "source": {
            "report_files": [ctx.report_path],
            "feedback_files": [ctx.feedback_path],
            "base_threshold_profile": ctx.base_threshold_profile,
        },
        "target_threshold_profile": ctx.target_threshold_profile,
        "global_summary": {
            "total_rules": len(rule_suggestions),
            "total_issues": report.get("summary", {}).get("total_issues", 0),
            "total_reviewed": total_reviewed,
            "rules_ready_for_adjustment": ready,
            "rules_need_more_review": need_more,
        },
        "rule_suggestions": rule_suggestions,
    }

    _ensure_parent(output_path)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    logger.info(
        f"Wrote threshold_suggestion.json → {output_path} "
        f"({len(rule_suggestions)} rules)"
    )
    return output_path


# ---------------------------------------------------------------------------
# Suggestion builder + 9-level priority trigger
# ---------------------------------------------------------------------------


def _build_suggestion(
    rule_id: str,
    rule_name: str,
    rule_thresholds: Dict[str, Any],
    stats: Dict[str, Any],
    issues: List[Dict[str, Any]],
    primary_metric: Optional[str],
) -> Dict[str, Any]:
    reviewed = stats["reviewed_count"]
    true_err_rate = stats["true_error_rate"]
    fp_rate = stats["false_positive_rate"]
    acc_rate = stats["acceptable_rate"]
    disc_rate = stats["discussion_rate"]

    action = _pick_action(
        reviewed, true_err_rate, fp_rate, acc_rate, disc_rate
    )
    secondary = _secondary_actions(action, acc_rate, fp_rate)

    return {
        "rule_id": rule_id,
        "rule_name": rule_name,
        "current": {
            "thresholds": rule_thresholds,
        },
        "review_stats": stats,
        "metric_analysis": _metric_analysis(issues, primary_metric),
        "suggested_action": action,
        "secondary_actions": secondary,
        "proposed": _proposed(action, rule_thresholds),
        "confidence": _confidence(action, reviewed),
        "reason": _reason(
            action, reviewed, true_err_rate, fp_rate, acc_rate, disc_rate
        ),
        "requires_human_approval": True,
        "approval": {
            "status": "pending",  # ALWAYS pending — never auto-applied
            "approved_by": None,
            "approved_at": None,
            "note": "",
        },
    }


def _pick_action(
    reviewed: int,
    true_err_rate: float,
    fp_rate: float,
    acc_rate: float,
    disc_rate: float,
) -> str:
    """Apply the 9-level priority trigger table (spec section 9)."""
    # P1
    if reviewed < 30:
        return "require_more_review"
    # P2
    if disc_rate >= 0.25:
        return "definition_review"
    # P3
    if fp_rate >= 0.60 and true_err_rate < 0.30:
        return "disable_as_strong_rule"
    # P4
    if fp_rate >= 0.50:
        return "relax_threshold"
    # P5
    if acc_rate >= 0.40 and fp_rate < 0.30:
        return "downgrade_severity"
    # P7
    if true_err_rate >= 0.85 and fp_rate <= 0.10 and reviewed >= 100:
        return "tighten_threshold"
    # P6
    if true_err_rate >= 0.75 and fp_rate <= 0.15:
        return "keep_threshold"
    # P8
    if true_err_rate < 0.40 and acc_rate >= 0.35:
        return "downgrade_severity"
    # default: keep
    return "keep_threshold"


def _secondary_actions(
    action: str, acc_rate: float, fp_rate: float
) -> List[str]:
    secondary: List[str] = []
    if acc_rate >= 0.40 and "downgrade_severity" not in (action, *secondary):
        secondary.append("rewrite_message")
    if fp_rate >= 0.30 and "relax_threshold" not in (action, *secondary):
        secondary.append("relax_threshold")
    return secondary


def _proposed(action: str, current: Dict[str, Any]) -> Dict[str, Any]:
    """A placeholder proposal.  We deliberately do NOT compute new numbers
    automatically — that is a human decision.  We carry the current
    thresholds forward and tag the intent."""
    return {
        "thresholds": dict(current),
        "intent": action,
    }


def _confidence(action: str, reviewed: int) -> str:
    if reviewed < 30:
        return "low"
    if action in ("keep_threshold", "tighten_threshold"):
        return "high"
    if action in ("definition_review", "require_more_review"):
        return "low"
    return "medium"


def _reason(
    action: str,
    reviewed: int,
    true_err_rate: float,
    fp_rate: float,
    acc_rate: float,
    disc_rate: float,
) -> str:
    base = (
        f"reviewed={reviewed}, true_error_rate={true_err_rate:.3f}, "
        f"false_positive_rate={fp_rate:.3f}, "
        f"acceptable_rate={acc_rate:.3f}, "
        f"discussion_rate={disc_rate:.3f}. "
    )
    reasons = {
        "require_more_review": "复核样本不足 30，需更多反馈才能判断。",
        "definition_review": "discussion_rate >= 0.25，规则定义本身存疑，需先回到规则定义。",
        "disable_as_strong_rule": "误报率高且真错率低，建议先降级或停用。",
        "relax_threshold": "误报率 >= 0.50，建议放宽阈值。",
        "downgrade_severity": "acceptable_rate 高，建议降级或改文案。",
        "keep_threshold": "真错率高、误报率低，保持阈值。",
        "tighten_threshold": "真错率高、误报率低且样本充足，可考虑收紧。",
        "rewrite_message": "真错率偏低且 acceptable 集中，建议改文案。",
        "split_rule": "误报集中在子场景，建议拆分规则。",
    }
    return base + reasons.get(action, "保持现状。")


def _metric_analysis(
    issues: List[Dict[str, Any]], primary_metric: Optional[str]
) -> Dict[str, Any]:
    """Best-effort distribution of the primary metric across the rule's
    issues.  Only used when the issue carries a numeric primary_metric."""
    values: List[float] = []
    for issue in issues:
        pm = issue.get("primary_metric") or {}
        v = pm.get("value") if isinstance(pm, dict) else None
        if isinstance(v, (int, float)):
            values.append(float(v))
    if not values:
        return {"primary_metric": primary_metric}
    values.sort()
    n = len(values)
    return {
        "primary_metric": primary_metric,
        "count": n,
        "min": round(values[0], 4),
        "p10": round(values[int(n * 0.10)], 4) if n >= 10 else None,
        "median": round(values[n // 2], 4),
        "p90": (
            round(values[min(n - 1, int(n * 0.90))], 4) if n >= 10 else None
        ),
        "max": round(values[-1], 4),
    }


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------


def _load_report(path: str) -> Dict[str, Any]:
    if not osp.isfile(path):
        raise FileNotFoundError(f"report.json not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _rule_name_from_report(
    report: Dict[str, Any], rule_id: str
) -> Optional[str]:
    for issue in report.get("issues", []) or []:
        if issue.get("rule_id") == rule_id:
            return issue.get("rule_name")
    return None


def _issues_for_rule(
    report: Dict[str, Any], rule_name: str
) -> List[Dict[str, Any]]:
    return [
        i
        for i in (report.get("issues", []) or [])
        if i.get("rule_name") == rule_name
    ]


def _empty_stats() -> Dict[str, Any]:
    return {
        "all_review_rows": 0,
        "reviewed_count": 0,
        "true_error_count": 0,
        "false_positive_count": 0,
        "acceptable_count": 0,
        "needs_discussion_count": 0,
        "true_error_rate": 0.0,
        "false_positive_rate": 0.0,
        "acceptable_rate": 0.0,
        "discussion_rate": 0.0,
    }


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _ensure_parent(path: str) -> None:
    parent = osp.dirname(osp.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


# re-export for tests / CLI
__all__ = [
    "SCHEMA_VERSION",
    "VALID_ACTIONS",
    "SuggestionContext",
    "generate_threshold_suggestion",
    "FeedbackParseResult",
]
