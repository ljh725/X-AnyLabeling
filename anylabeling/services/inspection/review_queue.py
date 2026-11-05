"""Pure review-queue logic: recheck merging, feedback and action guards.

Everything here is deliberately free of Qt so the state machine can be
tested without a window: the Inspector dialog only renders the results.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional, Sequence

from .models import (
    CoverageEntry,
    CoverageState,
    Decision,
    InspectionIssue,
    IssueEvidence,
    RunReport,
    RunState,
    VerificationState,
    dataset_identity,
    new_run_id,
    output_identity,
    utc_now_iso,
)

PROOF_STATES = (CoverageState.COMPLETED,)
BLOCKING_STATES = (
    CoverageState.FAILED,
    CoverageState.CANCELLED,
    CoverageState.NOT_RUN,
    CoverageState.SKIPPED,
)


@dataclass(frozen=True)
class SourceCheck:
    """Verification result for one evidence source of an issue."""

    rule_id: str
    implementation_version: str
    state: VerificationState
    reason: str
    coverage_state: str = ""

    @property
    def successful(self) -> bool:
        return self.state is VerificationState.NOT_DETECTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "implementation_version": self.implementation_version,
            "state": self.state.value,
            "reason": self.reason,
            "coverage_state": self.coverage_state,
        }


@dataclass(frozen=True)
class RecheckResult:
    """Merged queue after rechecking one file."""

    report: RunReport
    selected_issue: Optional[InspectionIssue] = None
    sources: tuple[SourceCheck, ...] = ()
    outcome: str = "unverifiable"
    preserved_other_files: int = 0
    notes: tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.outcome == "not_detected"

    @property
    def re_detected(self) -> bool:
        return self.outcome == "re_detected"


def _rule_snapshots(report: RunReport) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for rule in report.profile_snapshot.get("rules", []) or []:
        if isinstance(rule, Mapping):
            result[str(rule.get("rule_id", ""))] = rule
    return result


def _history_entry(
    previous: InspectionIssue,
    event: str,
    **extra: Any,
) -> Mapping[str, Any]:
    payload = {
        "at": utc_now_iso(),
        "event": event,
        "previous_decision": previous.decision.value,
        "previous_action": previous.action.value,
        "previous_verification": previous.verification.value,
        "previous_evidence_digest": previous.location.snapshot_digest,
    }
    payload.update(extra)
    return payload


def source_checks(
    report: RunReport, issue: InspectionIssue
) -> tuple[SourceCheck, ...]:
    """Verify every evidence source of one issue against a run report."""
    rules = _rule_snapshots(report)
    results: list[SourceCheck] = []
    for evidence in issue.evidence:
        results.append(
            _check_source(
                report, issue.location.relative_path, evidence, rules
            )
        )
    if not results:
        # A manifest/import issue without rule evidence can only be checked
        # through the file-level coverage.
        entries = _coverage_for(report, issue.location.relative_path, "")
        if (
            entries
            and report.state in (RunState.COMPLETED, RunState.PARTIAL)
            and all(entry.state in PROOF_STATES for entry in entries)
            and not any(entry.truncated for entry in entries)
        ):
            return (
                SourceCheck(
                    rule_id="",
                    implementation_version="",
                    state=VerificationState.NOT_DETECTED,
                    reason="文件级覆盖完成且未再命中",
                    coverage_state=CoverageState.COMPLETED.value,
                ),
            )
        return (
            SourceCheck(
                rule_id="",
                implementation_version="",
                state=VerificationState.UNVERIFIABLE,
                reason="问题没有规则来源，且文件级覆盖不足以证明未再命中",
            ),
        )
    return tuple(results)


def _coverage_for(
    report: RunReport, relative_path: str, rule_id: str
) -> list[CoverageEntry]:
    return [
        entry
        for entry in report.coverage
        if entry.relative_path == relative_path
        and (not rule_id or entry.rule_id == rule_id)
    ]


def _check_source(
    report: RunReport,
    relative_path: str,
    evidence: IssueEvidence,
    rules: Mapping[str, Mapping[str, Any]],
) -> SourceCheck:
    rule_id = evidence.rule_id
    version = evidence.implementation_version
    snapshot = rules.get(rule_id) if rule_id else None
    if rule_id and snapshot is None:
        return SourceCheck(
            rule_id,
            version,
            VerificationState.UNVERIFIABLE,
            "当前方案未包含该规则来源",
        )
    if snapshot is not None and not bool(snapshot.get("enabled", True)):
        return SourceCheck(
            rule_id,
            version,
            VerificationState.UNVERIFIABLE,
            "规则已停用，不能证明问题已消失",
        )
    snapshot_version = (
        str(snapshot.get("implementation_version", "")) if snapshot else ""
    )
    if (
        rule_id
        and version
        and snapshot_version
        and snapshot_version != version
    ):
        return SourceCheck(
            rule_id,
            version,
            VerificationState.UNVERIFIABLE,
            "规则实现版本已变化（{} -> {}）".format(version, snapshot_version),
        )
    entries = _coverage_for(report, relative_path, rule_id)
    if not entries:
        return SourceCheck(
            rule_id,
            version,
            VerificationState.UNVERIFIABLE,
            "本次运行未执行该规则",
        )
    blocking = [entry for entry in entries if entry.state in BLOCKING_STATES]
    if blocking:
        entry = blocking[0]
        return SourceCheck(
            rule_id,
            version,
            VerificationState.UNVERIFIABLE,
            "规则未成功完成: {}".format(entry.reason or entry.state.value),
            entry.state.value,
        )
    if any(entry.truncated for entry in entries):
        return SourceCheck(
            rule_id,
            version,
            VerificationState.UNVERIFIABLE,
            "规则结果发生截断，无法证明未再命中",
            CoverageState.COMPLETED.value,
        )
    if any(entry.state not in PROOF_STATES for entry in entries):
        return SourceCheck(
            rule_id,
            version,
            VerificationState.UNVERIFIABLE,
            "规则在当前输入上不适用，无法证明未再命中",
            CoverageState.NOT_APPLICABLE.value,
        )
    return SourceCheck(
        rule_id,
        version,
        VerificationState.NOT_DETECTED,
        "规则成功完成且未再命中",
        CoverageState.COMPLETED.value,
    )


def _with_evidence_states(
    issue: InspectionIssue, checks: Sequence[SourceCheck]
) -> InspectionIssue:
    by_key = {
        (check.rule_id, check.implementation_version): check
        for check in checks
    }
    evidence: list[IssueEvidence] = []
    for item in issue.evidence:
        check = by_key.get(
            (item.rule_id, item.implementation_version)
        ) or next(
            (
                candidate
                for candidate in checks
                if candidate.rule_id == item.rule_id
            ),
            None,
        )
        if check is None:
            evidence.append(item)
        else:
            evidence.append(
                replace(
                    item,
                    verification=check.state,
                    verification_reason=check.reason,
                )
            )
    return replace(issue, evidence=tuple(evidence))


def _reactivate(
    current: InspectionIssue, previous: InspectionIssue
) -> InspectionIssue:
    evidence = tuple(
        replace(
            item,
            verification=VerificationState.CURRENT,
            verification_reason="",
        )
        for item in current.evidence
    )
    decision = previous.decision
    action = previous.action
    history = tuple(current.history)
    if previous.verification is VerificationState.NOT_DETECTED:
        decision = Decision.PENDING
        action = previous.action
        history = history + (
            _history_entry(previous, "re_detected_after_not_detected"),
        )
    return replace(
        current,
        evidence=evidence,
        decision=decision,
        action=action,
        verification=VerificationState.CURRENT,
        history=history,
        updated_at=utc_now_iso(),
    )


def _not_detected(
    previous: InspectionIssue, checks: Sequence[SourceCheck]
) -> InspectionIssue:
    issue = _with_evidence_states(previous, checks)
    return replace(
        issue,
        verification=VerificationState.NOT_DETECTED,
        history=tuple(issue.history)
        + (
            _history_entry(
                previous,
                "not_detected_on_successful_recheck",
                sources=[check.to_dict() for check in checks],
            ),
        ),
        updated_at=utc_now_iso(),
    )


def _unverifiable(
    previous: InspectionIssue, checks: Sequence[SourceCheck]
) -> InspectionIssue:
    issue = _with_evidence_states(previous, checks)
    return replace(
        issue,
        verification=VerificationState.UNVERIFIABLE,
        history=tuple(issue.history)
        + (
            _history_entry(
                previous,
                "recheck_unverifiable",
                sources=[check.to_dict() for check in checks],
            ),
        ),
        updated_at=utc_now_iso(),
    )


def merge_recheck_report(
    prior_report: RunReport,
    recheck_report: RunReport,
    relative_path: str,
    *,
    selected_family_key: str = "",
) -> RecheckResult:
    """Merge a one-file recheck into the existing queue without losing it."""
    recheck_by_family: dict[str, InspectionIssue] = {}
    for issue in recheck_report.issues:
        recheck_by_family[issue.family_key] = issue
    merged: list[InspectionIssue] = []
    selected: Optional[InspectionIssue] = None
    selected_checks: tuple[SourceCheck, ...] = ()
    selected_outcome = "not_selected"
    preserved_other_files = 0
    config_changed = bool(
        prior_report.config_digest
        and recheck_report.config_digest
        and prior_report.config_digest != recheck_report.config_digest
    )
    for prior in prior_report.issues:
        if prior.location.relative_path != relative_path:
            merged.append(
                replace(prior, verification=VerificationState.STALE)
                if config_changed
                else prior
            )
            preserved_other_files += 1
            continue
        current = recheck_by_family.pop(prior.family_key, None)
        checks = source_checks(recheck_report, prior)
        if current is not None:
            updated = _reactivate(current, prior)
            outcome = "re_detected"
        elif checks and all(check.successful for check in checks):
            updated = _not_detected(prior, checks)
            outcome = "not_detected"
        else:
            updated = _unverifiable(prior, checks)
            outcome = "unverifiable"
        if prior.family_key == selected_family_key:
            selected = updated
            selected_checks = checks
            selected_outcome = outcome
        merged.append(updated)
    for issue in recheck_by_family.values():
        merged.append(issue)
        if issue.family_key == selected_family_key:
            selected = issue
            selected_checks = source_checks(recheck_report, issue)
            selected_outcome = "re_detected"
    merged.sort(
        key=lambda item: (
            item.location.relative_path,
            item.location.object_ids,
            item.title,
        )
    )
    profile_id = str(
        (recheck_report.profile_snapshot.get("profile", {}) or {}).get(
            "profile_id", ""
        )
    )
    coverage = _merge_coverage(prior_report.coverage, recheck_report.coverage)
    state = _merged_state(recheck_report, merged)
    notes = list(prior_report.scope_notes) + list(recheck_report.scope_notes)
    notes.append(
        "复查 {}：保留其他图片问题 {} 项；本次队列为合并结果".format(
            relative_path, preserved_other_files
        )
    )
    merged_report = replace(
        prior_report,
        run_id=new_run_id(profile_id or "recheck"),
        state=state,
        manifest_fingerprint=prior_report.manifest_fingerprint
        or recheck_report.manifest_fingerprint,
        profile_snapshot=dict(recheck_report.profile_snapshot),
        coverage=coverage,
        issues=tuple(merged),
        finished_at=recheck_report.finished_at or utc_now_iso(),
        truncated=bool(prior_report.truncated or recheck_report.truncated),
        error=recheck_report.error,
        generation=recheck_report.generation,
        source_kind=recheck_report.source_kind,
        scope_notes=tuple(dict.fromkeys(notes)),
    )
    return RecheckResult(
        report=merged_report,
        selected_issue=selected,
        sources=selected_checks,
        outcome=selected_outcome,
        preserved_other_files=preserved_other_files,
        notes=tuple(note for note in notes if note),
    )


def _merge_coverage(
    prior: Sequence[CoverageEntry], recheck: Sequence[CoverageEntry]
) -> tuple[CoverageEntry, ...]:
    merged: dict[tuple[str, str], CoverageEntry] = {}
    for entry in prior:
        merged[(entry.relative_path, entry.rule_id)] = entry
    for entry in recheck:
        merged[(entry.relative_path, entry.rule_id)] = entry
    return tuple(merged[key] for key in sorted(merged))


def _merged_state(
    recheck_report: RunReport, merged: Sequence[InspectionIssue]
) -> RunState:
    if recheck_report.state is RunState.CANCELLED:
        return RunState.PARTIAL
    if recheck_report.state is RunState.FAILED:
        return RunState.PARTIAL
    if any(
        issue.verification is VerificationState.UNVERIFIABLE
        for issue in merged
    ):
        return RunState.PARTIAL
    return recheck_report.state


def apply_feedback(
    report: RunReport,
    records: Mapping[str, Any],
    *,
    dataset_key: str = "",
) -> RunReport:
    """Apply human decisions without resurrecting a resolved conclusion."""
    issues: list[InspectionIssue] = []
    for issue in report.issues:
        record = records.get(issue.family_key)
        if record is None:
            issues.append(issue)
            continue
        record_key = str(getattr(record, "dataset_key", "") or "")
        if record_key and dataset_key and record_key != dataset_key:
            issues.append(issue)
            continue
        record_profile = str(getattr(record, "profile_fingerprint", "") or "")
        if (
            record_profile
            and report.config_digest
            and record_profile != report.config_digest
        ):
            issues.append(
                replace(
                    issue,
                    decision=record.decision,
                    action=record.action,
                    verification=VerificationState.STALE,
                )
            )
            continue
        record_digest = str(getattr(record, "evidence_digest", "") or "")
        if (
            record_digest
            and issue.location.snapshot_digest
            and record_digest != issue.location.snapshot_digest
        ):
            issues.append(
                replace(
                    issue,
                    decision=record.decision,
                    action=record.action,
                    verification=VerificationState.STALE,
                )
            )
            continue
        if record.verification is VerificationState.NOT_DETECTED:
            if issue.verification is VerificationState.NOT_DETECTED:
                # The issue is a retained history entry of the current queue,
                # not a fresh re-detection: keep the recorded conclusion.
                issues.append(
                    replace(
                        issue,
                        decision=record.decision,
                        action=record.action,
                    )
                )
                continue
            # The rule re-detected this family: a previous "not detected"
            # conclusion must not survive into the current queue.
            issues.append(
                replace(
                    issue,
                    decision=Decision.PENDING,
                    action=record.action,
                    verification=VerificationState.PENDING_RECHECK,
                    history=tuple(issue.history)
                    + (
                        {
                            "at": utc_now_iso(),
                            "event": "re_detected_after_not_detected",
                            "previous_decision": record.decision.value,
                            "previous_verification": record.verification.value,
                        },
                    ),
                )
            )
            continue
        verification = (
            VerificationState.PENDING_RECHECK
            if record.verification is VerificationState.PENDING_RECHECK
            else VerificationState.CURRENT
        )
        issues.append(
            replace(
                issue,
                decision=record.decision,
                action=record.action,
                verification=verification,
            )
        )
    return replace(report, issues=tuple(issues))


def invalidate_file_edits(
    report: RunReport, relative_path: str
) -> tuple[RunReport, int]:
    """Mark current and not-detected issues stale after a canvas edit."""
    changed = 0
    issues: list[InspectionIssue] = []
    for issue in report.issues:
        if (
            issue.location.relative_path == relative_path
            and issue.verification
            in (
                VerificationState.CURRENT,
                VerificationState.NOT_DETECTED,
                VerificationState.PENDING_RECHECK,
            )
        ):
            changed += 1
            issues.append(
                replace(
                    issue,
                    verification=VerificationState.PENDING_RECHECK,
                    evidence=tuple(
                        replace(
                            item,
                            verification=VerificationState.PENDING_RECHECK,
                            verification_reason="画布修改后待复查",
                        )
                        for item in issue.evidence
                    ),
                    history=tuple(issue.history)
                    + (
                        {
                            "at": utc_now_iso(),
                            "event": "canvas_edit_invalidated",
                            "previous_verification": issue.verification.value,
                        },
                    ),
                )
            )
        else:
            issues.append(issue)
    return replace(report, issues=tuple(issues)), changed


def action_target_problem(
    report: Optional[RunReport],
    issue: Optional[InspectionIssue],
    *,
    dataset_root: str,
    output_dir: str,
    current_relative_path: str,
) -> str:
    """Return why an issue may not authorize a canvas edit, or ""."""
    if report is None:
        return "当前没有可核验的检查报告"
    if issue is None:
        return "请选择问题"
    if not current_relative_path:
        return "当前没有已加载图片"
    if issue.location.relative_path != current_relative_path:
        return "问题属于 {}，当前画布是 {}；禁止跨文件操作".format(
            issue.location.relative_path, current_relative_path
        )
    if issue.location.ambiguous:
        return "问题文件定位存在歧义，需重新检查后再操作"
    report_dataset = dataset_identity(report.dataset_root)
    current_dataset = dataset_identity(dataset_root)
    if report.dataset_root and report_dataset != current_dataset:
        return "报告数据集与当前数据集不一致"
    if output_identity(report.output_root) != output_identity(output_dir):
        return "报告输出目录与当前输出目录不一致"
    if issue.verification in (
        VerificationState.STALE,
        VerificationState.NOT_DETECTED,
        VerificationState.UNVERIFIABLE,
    ):
        return "问题当前状态为 {}，需先复查".format(issue.verification.value)
    return ""
