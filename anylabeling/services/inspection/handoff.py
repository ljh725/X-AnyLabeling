"""Inspection-to-canvas handoff and explicit completion dimensions."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from .models import (
    Decision,
    InspectionIssue,
    InspectionStatus,
    RunReport,
    RunState,
    VerificationState,
)


def dense_review_available() -> bool:
    """The dense-review workspace is available in this repository."""
    return True


def spatial_omission_status() -> Mapping[str, Any]:
    return {
        "state": "available",
        "label": "独立空间查漏工作区可用",
        "reason": "具体完成状态以当前标注对象的密集复核进度为准",
    }


def formal_acceptance_status(
    checked: Optional[object] = None,
) -> Mapping[str, Any]:
    if checked is True:
        return {"state": "passed", "label": "既有审核已通过"}
    if checked == "failed":
        return {"state": "failed", "label": "既有审核未通过"}
    return {"state": "unchanged", "label": "既有审核状态未改变"}


def build_status(
    report: RunReport,
    feedback: Mapping[str, Any],
    *,
    checked: Optional[object] = None,
) -> InspectionStatus:
    """Show execution, issue handling and other reviews as separate axes."""
    decisions = {
        key: str(value.get("decision", "pending"))
        for key, value in feedback.items()
        if isinstance(value, Mapping)
    }
    open_issues = [
        issue
        for issue in report.issues
        if issue.verification
        in (
            VerificationState.CURRENT,
            VerificationState.PENDING_RECHECK,
        )
    ]
    pending = sum(
        1
        for issue in open_issues
        if decisions.get(issue.family_key, "pending") == "pending"
    )
    handled = len(open_issues) - pending
    execution = {
        "state": report.state.value,
        "run_id": report.run_id,
        "completed": report.completed_files,
        "failed": report.failed_files,
        "not_run": report.not_run_files,
        "requested": report.requested_files,
        "truncated": report.truncated,
        "completed_scope": report.state is RunState.COMPLETED,
    }
    issue_handling = {
        "total": len(report.issues),
        "open": len(open_issues),
        "pending": pending,
        "handled": handled,
        "stale": sum(
            1
            for issue in report.issues
            if issue.verification is VerificationState.STALE
        ),
        "confirmed_error": sum(
            1
            for value in decisions.values()
            if value == Decision.CONFIRMED_ERROR.value
        ),
        "false_positive": sum(
            1
            for value in decisions.values()
            if value == Decision.FALSE_POSITIVE.value
        ),
        "acceptable": sum(
            1
            for value in decisions.values()
            if value == Decision.ACCEPTABLE.value
        ),
    }
    notes = [
        "检查、问题处理、对象复核、空间查漏与正式验收是独立状态。",
        "问题队列清空或规则未报警不能证明整图没有漏标。",
    ]
    if not dense_review_available():
        notes.append("密集复核工作区不可用，普通画布仍可处理问题。")
    return InspectionStatus(
        execution=execution,
        issue_handling=issue_handling,
        object_review={
            "state": "available",
            "label": "对象级复核（密集复核）工作区可用",
        },
        spatial_omission=spatial_omission_status(),
        formal_acceptance=formal_acceptance_status(checked),
        notes=tuple(notes),
    )


def issue_context(issue: InspectionIssue) -> Mapping[str, Any]:
    """Return the portable context shown before handing an issue to canvas."""
    return {
        "issue_id": issue.issue_id,
        "family_key": issue.family_key,
        "title": issue.title,
        "message": issue.message,
        "severity": issue.severity.value,
        "relative_path": issue.location.relative_path,
        "image_path": issue.location.image_path,
        "object_ids": list(issue.location.object_ids),
        "shape_indices": list(issue.location.shape_indices),
        "group_id": issue.location.group_id,
        "region": (
            list(issue.location.region) if issue.location.region else None
        ),
        "rules": [
            {
                "rule_id": evidence.rule_id,
                "rule_name": evidence.rule_name,
                "implementation_version": evidence.implementation_version,
                "message": evidence.message,
                "relation": evidence.relation,
                "filtered_reason": evidence.filtered_reason,
            }
            for evidence in issue.evidence
        ],
        "suggested_action": issue.suggested_action,
        "dense_review_available": dense_review_available(),
        "spatial_omission": dict(spatial_omission_status()),
    }


def handoff_payload(issue: InspectionIssue) -> Mapping[str, Any]:
    """Describe what would be sent to a dense-review workspace if present."""
    if dense_review_available():
        return {
            "available": True,
            "protocol": "dense-review.v1",
            "context": issue_context(issue),
        }
    return {
        "available": False,
        "reason": "当前版本没有密集复核工作区",
        "fallback": "ordinary_canvas",
        "context": issue_context(issue),
    }
