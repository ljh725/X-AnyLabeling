"""
Reader for ``review_feedback.tsv`` (human review conclusions).

Validates ``decision`` / ``final_action`` enum values per spec section 8.1
and re-links each row back to its ``report.json`` issue via ``issue_id``.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import os.path as osp
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


VALID_DECISIONS = {
    "confirmed_error",
    "fixed",
    "false_positive",
    "acceptable",
    "needs_discussion",
}

VALID_FINAL_ACTIONS = {
    "none",
    "fixed_box",
    "fixed_label",
    "fixed_group_id",
    "fixed_points",
    "ignored",
    "escalated",
}

TRUE_ERROR_DECISIONS = {"confirmed_error", "fixed"}

FEEDBACK_COLUMNS = [
    "issue_id",
    "run_id",
    "file_path",
    "shape_index",
    "rule_name",
    "original_severity",
    "decision",
    "final_action",
    "reviewer",
    "reviewed_at",
    "note",
]

FEEDBACK_CONTEXT_COLUMNS = [
    "message",
    "label",
    "group_id",
    "primary_metric_name",
    "primary_metric_value",
]

FEEDBACK_TEMPLATE_COLUMNS = FEEDBACK_COLUMNS + FEEDBACK_CONTEXT_COLUMNS


@dataclass
class FeedbackRow:
    """One review conclusion row."""

    issue_id: str
    run_id: str
    file_path: str
    shape_index: int
    rule_name: str
    original_severity: str
    decision: str
    final_action: str
    reviewer: str = ""
    reviewed_at: str = ""
    note: str = ""

    @property
    def is_true_error(self) -> bool:
        return self.decision in TRUE_ERROR_DECISIONS

    @property
    def is_false_positive(self) -> bool:
        return self.decision == "false_positive"

    @property
    def is_acceptable(self) -> bool:
        return self.decision == "acceptable"

    @property
    def needs_discussion(self) -> bool:
        return self.decision == "needs_discussion"


@dataclass
class FeedbackParseResult:
    """Outcome of reading a feedback file."""

    rows: List[FeedbackRow] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class FeedbackTemplateResult:
    """Outcome of writing a review feedback template."""

    output_path: str
    total_rows: int
    preserved_rows: int = 0
    blank_rows: int = 0


def read_review_feedback(
    path: str,
    strict: bool = True,
) -> FeedbackParseResult:
    """Read ``review_feedback.tsv``.

    Args:
        path: path to the TSV.
        strict: when True, invalid enum values raise errors into the
            result; when False they are logged and the row is dropped.

    Returns:
        a ``FeedbackParseResult``.
    """
    result = FeedbackParseResult()
    if not osp.isfile(path):
        result.errors.append(f"Feedback file not found: {path}")
        return result

    with open(path, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        if reader.fieldnames is None:
            result.errors.append("Feedback file is empty or headerless")
            return result
        missing = [c for c in FEEDBACK_COLUMNS if c not in reader.fieldnames]
        if missing:
            result.errors.append(
                f"Feedback missing required columns: {missing}"
            )
            return result

        for lineno, raw in enumerate(reader, start=2):
            row = _parse_row(raw, lineno, result, strict)
            if row is not None:
                result.rows.append(row)

    logger.info(
        f"Read feedback: {len(result.rows)} rows, "
        f"{len(result.errors)} errors"
    )
    return result


def _parse_row(
    raw: Dict[str, str],
    lineno: int,
    result: FeedbackParseResult,
    strict: bool,
) -> Optional[FeedbackRow]:
    issue_id = (raw.get("issue_id") or "").strip()
    rule_name = (raw.get("rule_name") or "").strip()
    decision = (raw.get("decision") or "").strip()
    final_action = (raw.get("final_action") or "").strip()

    if not issue_id:
        result.errors.append(f"line {lineno}: empty issue_id")
        return None
    if not decision and not strict:
        return None
    if decision not in VALID_DECISIONS:
        msg = (
            f"line {lineno}: invalid decision {decision!r} "
            f"(issue_id={issue_id})"
        )
        if strict:
            result.errors.append(msg)
            return None
        logger.warning(msg)
        return None
    if final_action and final_action not in VALID_FINAL_ACTIONS:
        msg = (
            f"line {lineno}: invalid final_action {final_action!r} "
            f"(issue_id={issue_id})"
        )
        if strict:
            result.errors.append(msg)
            return None
        logger.warning(msg)
        final_action = "none"

    shape_index_raw = (raw.get("shape_index") or "").strip()
    try:
        shape_index = int(shape_index_raw)
    except ValueError:
        shape_index = -1

    return FeedbackRow(
        issue_id=issue_id,
        run_id=(raw.get("run_id") or "").strip(),
        file_path=(raw.get("file_path") or "").strip(),
        shape_index=shape_index,
        rule_name=rule_name,
        original_severity=(raw.get("original_severity") or "").strip(),
        decision=decision,
        final_action=final_action or "none",
        reviewer=(raw.get("reviewer") or "").strip(),
        reviewed_at=(raw.get("reviewed_at") or "").strip(),
        note=(raw.get("note") or "").strip(),
    )


def write_review_feedback_template(
    report_path: str,
    output_path: str,
    existing_feedback_path: Optional[str] = None,
    reviewer: str = "",
    reviewed_at: str = "",
) -> FeedbackTemplateResult:
    """Create or refresh a semi-automatic ``review_feedback.tsv``.

    The generated table pre-fills all stable issue metadata from
    ``report.json``. Reviewers only need to fill ``decision``,
    ``final_action`` and optional ``note``. If an existing feedback file is
    supplied, reviewed cells are preserved by ``issue_id``.
    """
    report = _load_report(report_path)
    preserved = _load_existing_feedback(existing_feedback_path)
    run_id = str(report.get("run_id", "") or "")
    issues = report.get("issues", []) or []

    rows: List[Dict[str, Any]] = []
    preserved_count = 0
    blank_count = 0
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        issue_id = str(issue.get("issue_id", "") or "")
        old = preserved.get(issue_id, {})
        if old:
            preserved_count += 1
        decision = str(old.get("decision", "") or "")
        if not decision:
            blank_count += 1
        row = {
            "issue_id": issue_id,
            "run_id": run_id,
            "file_path": str(issue.get("file_path", "") or ""),
            "shape_index": issue.get("shape_index", -1),
            "rule_name": str(issue.get("rule_name", "") or ""),
            "original_severity": str(issue.get("severity", "") or ""),
            "decision": decision,
            "final_action": str(old.get("final_action", "") or "none"),
            "reviewer": str(old.get("reviewer", "") or reviewer),
            "reviewed_at": str(old.get("reviewed_at", "") or reviewed_at),
            "note": str(old.get("note", "") or ""),
        }
        row.update(_issue_context(issue))
        rows.append(row)

    _ensure_parent(output_path)
    with open(output_path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=FEEDBACK_TEMPLATE_COLUMNS,
            delimiter="\t",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)

    logger.info(
        "Wrote review_feedback.tsv template -> %s "
        "(%s rows, %s preserved, %s blank)",
        output_path,
        len(rows),
        preserved_count,
        blank_count,
    )
    return FeedbackTemplateResult(
        output_path=output_path,
        total_rows=len(rows),
        preserved_rows=preserved_count,
        blank_rows=blank_count,
    )


def aggregate_by_rule(
    rows: List[FeedbackRow],
) -> Dict[str, Dict[str, Any]]:
    """Aggregate feedback rows by ``rule_name``.

    Returns a dict keyed by rule_name, each value containing counts and
    the four review rates.  ``needs_discussion`` is excluded from the
    denominators of the first three rates (per spec section 9).
    """
    by_rule: Dict[str, List[FeedbackRow]] = {}
    for row in rows:
        by_rule.setdefault(row.rule_name, []).append(row)

    out: Dict[str, Dict[str, Any]] = {}
    for rule_name, group in by_rule.items():
        all_rows = len(group)
        needs_discussion = sum(1 for r in group if r.needs_discussion)
        denom = all_rows - needs_discussion
        true_error = sum(1 for r in group if r.is_true_error)
        false_positive = sum(1 for r in group if r.is_false_positive)
        acceptable = sum(1 for r in group if r.is_acceptable)
        out[rule_name] = {
            "all_review_rows": all_rows,
            "reviewed_count": denom,  # denominator excludes discussion
            "true_error_count": true_error,
            "false_positive_count": false_positive,
            "acceptable_count": acceptable,
            "needs_discussion_count": needs_discussion,
            "true_error_rate": _safe_rate(true_error, denom),
            "false_positive_rate": _safe_rate(false_positive, denom),
            "acceptable_rate": _safe_rate(acceptable, denom),
            "discussion_rate": _safe_rate(needs_discussion, all_rows),
        }
    return out


def _safe_rate(num: int, denom: int) -> float:
    if denom <= 0:
        return 0.0
    return round(num / denom, 3)


def _load_report(path: str) -> Dict[str, Any]:
    if not osp.isfile(path):
        raise FileNotFoundError(f"report.json not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        report = json.load(fh)
    if not isinstance(report, dict):
        raise ValueError("report.json root must be an object")
    return report


def _load_existing_feedback(
    path: Optional[str],
) -> Dict[str, Dict[str, str]]:
    if not path or not osp.isfile(path):
        return {}
    out: Dict[str, Dict[str, str]] = {}
    with open(path, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        if reader.fieldnames is None:
            return out
        for raw in reader:
            issue_id = (raw.get("issue_id") or "").strip()
            if issue_id:
                out[issue_id] = {k: v for k, v in raw.items() if k}
    return out


def _issue_context(issue: Dict[str, Any]) -> Dict[str, str]:
    primary = issue.get("primary_metric") or {}
    if not isinstance(primary, dict):
        primary = {}
    metric_value = primary.get("value", "")
    if metric_value is None:
        metric_value = ""
    return {
        "message": str(issue.get("message", "") or ""),
        "label": str(issue.get("label", "") or ""),
        "group_id": (
            "" if issue.get("group_id") is None else str(issue.get("group_id"))
        ),
        "primary_metric_name": str(primary.get("name", "") or ""),
        "primary_metric_value": str(metric_value),
    }


def _ensure_parent(path: str) -> None:
    parent = osp.dirname(osp.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
