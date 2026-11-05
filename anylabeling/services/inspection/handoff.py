"""Inspection-to-canvas handoff and explicit completion dimensions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from .models import (
    Decision,
    InspectionIssue,
    InspectionStatus,
    RunReport,
    RunState,
    VerificationState,
    normalize_path,
    output_identity,
    utc_now_iso,
)


def dense_review_available(host: Optional[Any] = None) -> bool:
    """Whether a dense-review workspace can actually take a handoff.

    The workspace exists in this repository, but a handoff also needs a
    loaded image and an importable module.  Without a host the protocol is
    still available for planning; callers that will really open it must
    pass the host so an unavailable environment is reported honestly.
    """
    if host is None:
        return True
    try:
        from PyQt6 import QtWidgets  # noqa: F401
        from anylabeling.views.labeling.dense_review import (
            DenseReviewWorkspace,  # noqa: F401
        )
    except (ImportError, RuntimeError):
        return False
    filename = getattr(host, "filename", None)
    image = getattr(host, "image", None)
    if filename is None or image is None:
        return False
    try:
        return not image.isNull()
    except (AttributeError, RuntimeError):
        return False


@dataclass(frozen=True)
class HandoffRequest:
    """Everything the dense-review side needs to prove it got the same input."""

    issue_id: str
    family_key: str
    dataset_root: str
    output_root: str
    relative_path: str
    image_path: str = ""
    object_ids: tuple[str, ...] = ()
    region: Optional[tuple[float, float, float, float]] = None
    snapshot_digest: str = ""
    sent_at: str = field(default_factory=utc_now_iso)
    protocol: str = "dense-review.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "issue_id": self.issue_id,
            "family_key": self.family_key,
            "dataset_root": self.dataset_root,
            "output_root": self.output_root,
            "relative_path": self.relative_path,
            "image_path": self.image_path,
            "object_ids": list(self.object_ids),
            "region": list(self.region) if self.region else None,
            "snapshot_digest": self.snapshot_digest,
            "sent_at": self.sent_at,
        }


def build_handoff_request(
    issue: InspectionIssue,
    *,
    dataset_root: str,
    output_root: str = "",
) -> HandoffRequest:
    return HandoffRequest(
        issue_id=issue.issue_id,
        family_key=issue.family_key,
        dataset_root=dataset_root,
        output_root=output_root,
        relative_path=issue.location.relative_path,
        image_path=issue.location.image_path,
        object_ids=tuple(issue.location.object_ids),
        region=issue.location.region,
        snapshot_digest=issue.location.snapshot_digest,
    )


def validate_handoff(
    request: HandoffRequest,
    *,
    dataset_root: str,
    output_root: str = "",
    current_relative_path: str = "",
) -> str:
    """Return the reason a handoff must be refused, or "" when it may run."""
    if not request.relative_path:
        return "交接缺少文件身份"
    if normalize_path(request.dataset_root) != normalize_path(dataset_root):
        return "交接数据集与当前数据集不一致"
    if output_identity(request.output_root) != output_identity(output_root):
        return "交接输出目录与当前输出目录不一致"
    if not current_relative_path:
        return "当前没有已加载图片"
    if request.relative_path != current_relative_path:
        return "请先定位到问题所在文件再交接"
    if not request.snapshot_digest:
        return "问题缺少输入快照，无法核验交接上下文"
    return ""


def handoff_unavailable_status(reason: str = "") -> Mapping[str, Any]:
    return {
        "available": False,
        "reason": reason or "当前版本没有可用的密集复核工作区",
        "fallback": "ordinary_canvas",
        "message": "独立空间查漏尚未开展；请在普通画布处理该问题。",
    }


def spatial_omission_status(available: Optional[bool] = None) -> Mapping[str, Any]:
    if available is False:
        return {
            "state": "unavailable",
            "label": "独立空间查漏未开展",
            "reason": "密集复核工作区不可用；普通画布仍可处理问题",
        }
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
    dense_review: Optional[bool] = None,
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
    available = dense_review_available() if dense_review is None else dense_review
    if not available:
        notes.append("密集复核工作区不可用，普通画布仍可处理问题。")
    return InspectionStatus(
        execution=execution,
        issue_handling=issue_handling,
        object_review={
            "state": "available" if available else "unavailable",
            "label": (
                "对象级复核（密集复核）工作区可用"
                if available
                else "对象级复核工作区不可用，请使用普通画布"
            ),
        },
        spatial_omission=spatial_omission_status(available),
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


def handoff_payload(
    issue: InspectionIssue, *, available: Optional[bool] = None
) -> Mapping[str, Any]:
    """Describe what would be sent to a dense-review workspace if present."""
    usable = dense_review_available() if available is None else available
    if usable:
        return {
            "available": True,
            "protocol": "dense-review.v1",
            "context": issue_context(issue),
        }
    return {
        **dict(handoff_unavailable_status()),
        "context": issue_context(issue),
    }
