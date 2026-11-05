"""Recheck queue merge, per-source verification and feedback binding."""

from dataclasses import replace

from anylabeling.services.inspection.models import (
    ActionState,
    CoverageEntry,
    CoverageState,
    Decision,
    FeedbackRecord,
    InspectionIssue,
    IssueEvidence,
    IssueLocation,
    IssueSeverity,
    RunReport,
    RunScope,
    RunState,
    VerificationState,
)
from anylabeling.services.inspection.review_queue import (
    action_target_problem,
    apply_feedback,
    invalidate_file_edits,
    merge_recheck_report,
    source_checks,
)


def _evidence(rule_id, version="1.0.0", source="local"):
    return IssueEvidence(
        rule_id=rule_id,
        implementation_version=version,
        rule_name=rule_id,
        message=f"{rule_id} hit",
        severity=IssueSeverity.WARNING,
        source=source,
    )


def _issue(family, path="a.jpg", evidence=None, verification=VerificationState.CURRENT):
    return InspectionIssue(
        issue_id=f"issue-{family}",
        family_key=family,
        title="疑似重复矩形框",
        message="m",
        severity=IssueSeverity.WARNING,
        location=IssueLocation(
            relative_path=path,
            object_ids=("id1", "id2"),
            snapshot_digest="digest-1",
        ),
        evidence=tuple(evidence or (_evidence("duplicate_boxes"),)),
        verification=verification,
    )


def _coverage(path, rule_id, state=CoverageState.COMPLETED, truncated=False, reason=""):
    return CoverageEntry(
        relative_path=path,
        rule_id=rule_id,
        state=state,
        reason=reason,
        truncated=truncated,
    )


def _report(issues, coverage, *, state=RunState.COMPLETED, rules=None, run_id="run-1"):
    return RunReport(
        run_id=run_id,
        state=state,
        scope=RunScope.CURRENT_IMAGE,
        dataset_root="D:/data",
        output_root="",
        manifest_fingerprint="fp",
        profile_snapshot={
            "profile": {"profile_id": "generic", "profile_version": 1},
            "profile_fingerprint": "profile-fp",
            "snapshot_digest": "config-digest",
            "rules": list(
                rules
                or [
                    {
                        "rule_id": "duplicate_boxes",
                        "enabled": True,
                        "implementation_version": "1.0.0",
                    },
                    {
                        "rule_id": "legacy_same_group_duplicate",
                        "enabled": True,
                        "implementation_version": "l2-13.v1",
                    },
                ]
            ),
        },
        coverage=tuple(coverage),
        issues=tuple(issues),
        requested_files=1,
        completed_files=1,
    )


def test_successful_recheck_marks_not_detected_and_keeps_other_files():
    prior = _report(
        [
            _issue("dup|a", path="a.jpg"),
            _issue("dup|b", path="b.jpg"),
        ],
        [_coverage("a.jpg", "duplicate_boxes")],
    )
    recheck = _report(
        [],
        [_coverage("a.jpg", "duplicate_boxes")],
        run_id="run-2",
    )
    result = merge_recheck_report(
        prior,
        recheck,
        "a.jpg",
        selected_family_key="dup|a",
    )
    assert result.outcome == "not_detected"
    assert result.preserved_other_files == 1
    by_key = {issue.family_key: issue for issue in result.report.issues}
    assert by_key["dup|a"].verification is VerificationState.NOT_DETECTED
    assert by_key["dup|a"].evidence[0].verification is (
        VerificationState.NOT_DETECTED
    )
    assert by_key["dup|b"].verification is VerificationState.CURRENT
    assert result.report.run_id != prior.run_id
    assert any("保留其他图片问题" in note for note in result.report.scope_notes)


def test_cancelled_recheck_is_unverifiable_and_never_clears_queue():
    prior = _report(
        [_issue("dup|a")], [_coverage("a.jpg", "duplicate_boxes")]
    )
    recheck = _report(
        [],
        [_coverage("a.jpg", "duplicate_boxes", CoverageState.CANCELLED)],
        state=RunState.CANCELLED,
        run_id="run-2",
    )
    result = merge_recheck_report(
        prior, recheck, "a.jpg", selected_family_key="dup|a"
    )
    assert result.outcome == "unverifiable"
    assert result.report.state is RunState.PARTIAL
    issue = result.selected_issue
    assert issue is not None
    assert issue.verification is VerificationState.UNVERIFIABLE
    assert issue.evidence[0].verification is VerificationState.UNVERIFIABLE
    assert len(result.report.issues) == 1


def test_truncated_or_unrun_rule_cannot_prove_disappearance():
    prior = _report(
        [_issue("dup|a")], [_coverage("a.jpg", "duplicate_boxes")]
    )
    truncated = _report(
        [],
        [_coverage("a.jpg", "duplicate_boxes", truncated=True)],
        state=RunState.PARTIAL,
        run_id="run-2",
    )
    result = merge_recheck_report(
        prior, truncated, "a.jpg", selected_family_key="dup|a"
    )
    assert result.outcome == "unverifiable"

    not_run = _report(
        [],
        [_coverage("a.jpg", "duplicate_boxes", CoverageState.NOT_RUN)],
        state=RunState.PARTIAL,
        run_id="run-3",
    )
    result = merge_recheck_report(
        prior, not_run, "a.jpg", selected_family_key="dup|a"
    )
    assert result.outcome == "unverifiable"


def test_multi_source_keeps_unresolved_source_active():
    prior = _report(
        [
            _issue(
                "dup|a",
                evidence=(
                    _evidence("duplicate_boxes"),
                    _evidence("legacy_same_group_duplicate", "l2-13.v1"),
                ),
            )
        ],
        [
            _coverage("a.jpg", "duplicate_boxes"),
            _coverage("a.jpg", "legacy_same_group_duplicate"),
        ],
    )
    recheck = _report(
        [],
        [
            _coverage("a.jpg", "duplicate_boxes"),
            _coverage(
                "a.jpg",
                "legacy_same_group_duplicate",
                CoverageState.FAILED,
                reason="规则执行失败",
            ),
        ],
        state=RunState.PARTIAL,
        run_id="run-2",
    )
    checks = source_checks(recheck, prior.issues[0])
    assert [check.state for check in checks] == [
        VerificationState.NOT_DETECTED,
        VerificationState.UNVERIFIABLE,
    ]
    result = merge_recheck_report(
        prior, recheck, "a.jpg", selected_family_key="dup|a"
    )
    assert result.outcome == "unverifiable"
    issue = result.selected_issue
    assert issue.verification is VerificationState.UNVERIFIABLE
    states = {item.rule_id: item.verification for item in issue.evidence}
    assert states["duplicate_boxes"] is VerificationState.NOT_DETECTED
    assert states["legacy_same_group_duplicate"] is (
        VerificationState.UNVERIFIABLE
    )


def test_disabled_rule_or_changed_version_is_unverifiable():
    prior = _report(
        [_issue("dup|a")], [_coverage("a.jpg", "duplicate_boxes")]
    )
    disabled = _report(
        [],
        [_coverage("a.jpg", "duplicate_boxes")],
        rules=[
            {
                "rule_id": "duplicate_boxes",
                "enabled": False,
                "implementation_version": "1.0.0",
            }
        ],
        run_id="run-2",
    )
    checks = source_checks(disabled, prior.issues[0])
    assert checks[0].state is VerificationState.UNVERIFIABLE
    assert "停用" in checks[0].reason

    changed = _report(
        [],
        [_coverage("a.jpg", "duplicate_boxes")],
        rules=[
            {
                "rule_id": "duplicate_boxes",
                "enabled": True,
                "implementation_version": "2.0.0",
            }
        ],
        run_id="run-3",
    )
    assert source_checks(changed, prior.issues[0])[0].state is (
        VerificationState.UNVERIFIABLE
    )


def test_redetected_after_not_detected_returns_to_pending():
    prior = _report(
        [
            _issue(
                "dup|a",
                verification=VerificationState.NOT_DETECTED,
            )
        ],
        [_coverage("a.jpg", "duplicate_boxes")],
    )
    current = _issue("dup|a")
    recheck = _report(
        [current],
        [_coverage("a.jpg", "duplicate_boxes")],
        run_id="run-2",
    )
    result = merge_recheck_report(
        prior, recheck, "a.jpg", selected_family_key="dup|a"
    )
    assert result.outcome == "re_detected"
    issue = result.selected_issue
    assert issue.decision is Decision.PENDING
    assert issue.verification is VerificationState.CURRENT
    assert any(
        entry.get("event") == "re_detected_after_not_detected"
        for entry in issue.history
    )


def test_recheck_of_still_present_issue_keeps_human_decision():
    prior_issue = replace(
        _issue("dup|a"),
        decision=Decision.FALSE_POSITIVE,
        action=ActionState.UNCHANGED,
    )
    prior = _report(
        [prior_issue], [_coverage("a.jpg", "duplicate_boxes")]
    )
    current = replace(_issue("dup|a"), decision=Decision.PENDING)
    recheck = _report(
        [current],
        [_coverage("a.jpg", "duplicate_boxes")],
        run_id="run-2",
    )
    result = merge_recheck_report(
        prior, recheck, "a.jpg", selected_family_key="dup|a"
    )
    assert result.outcome == "re_detected"
    assert result.selected_issue.decision is Decision.FALSE_POSITIVE
    assert result.selected_issue.verification is VerificationState.CURRENT
    assert result.selected_issue.history == ()


def test_apply_feedback_binds_config_and_input_digest():
    report = _report([_issue("dup|a")], [_coverage("a.jpg", "duplicate_boxes")])
    same_input = FeedbackRecord(
        family_key="dup|a",
        issue_id="issue-dup|a",
        decision=Decision.FALSE_POSITIVE,
        verification=VerificationState.CURRENT,
        evidence_digest="digest-1",
        profile_fingerprint="config-digest",
    )
    applied = apply_feedback(
        report, {"dup|a": same_input}, dataset_key=""
    )
    assert applied.issues[0].decision is Decision.FALSE_POSITIVE
    assert applied.issues[0].verification is VerificationState.CURRENT

    changed_config = replace(same_input, profile_fingerprint="other-config")
    applied = apply_feedback(
        report, {"dup|a": changed_config}, dataset_key=""
    )
    assert applied.issues[0].verification is VerificationState.STALE

    changed_input = replace(same_input, evidence_digest="digest-2")
    applied = apply_feedback(
        report, {"dup|a": changed_input}, dataset_key=""
    )
    assert applied.issues[0].verification is VerificationState.STALE


def test_apply_feedback_does_not_resurrect_not_detected_for_current_issue():
    report = _report([_issue("dup|a")], [_coverage("a.jpg", "duplicate_boxes")])
    record = FeedbackRecord(
        family_key="dup|a",
        issue_id="issue-dup|a",
        decision=Decision.FALSE_POSITIVE,
        verification=VerificationState.NOT_DETECTED,
        evidence_digest="digest-1",
        profile_fingerprint="config-digest",
    )
    applied = apply_feedback(report, {"dup|a": record})
    assert applied.issues[0].decision is Decision.PENDING
    assert applied.issues[0].verification is (
        VerificationState.PENDING_RECHECK
    )

    history_report = _report(
        [_issue("dup|a", verification=VerificationState.NOT_DETECTED)],
        [_coverage("a.jpg", "duplicate_boxes")],
    )
    kept = apply_feedback(history_report, {"dup|a": record})
    assert kept.issues[0].verification is VerificationState.NOT_DETECTED
    assert kept.issues[0].decision is Decision.FALSE_POSITIVE


def test_apply_feedback_ignores_foreign_dataset_record():
    report = _report([_issue("dup|a")], [_coverage("a.jpg", "duplicate_boxes")])
    record = FeedbackRecord(
        family_key="dup|a",
        issue_id="issue-dup|a",
        decision=Decision.FALSE_POSITIVE,
        dataset_key="dataset-b",
    )
    applied = apply_feedback(report, {"dup|a": record}, dataset_key="dataset-a")
    assert applied.issues[0].decision is Decision.PENDING


def test_canvas_edit_invalidates_not_detected_history():
    report = _report(
        [
            _issue("dup|a", verification=VerificationState.NOT_DETECTED),
            _issue("dup|b", path="b.jpg"),
        ],
        [_coverage("a.jpg", "duplicate_boxes")],
    )
    updated, changed = invalidate_file_edits(report, "a.jpg")
    assert changed == 1
    by_key = {issue.family_key: issue for issue in updated.issues}
    assert by_key["dup|a"].verification is VerificationState.PENDING_RECHECK
    assert by_key["dup|a"].evidence[0].verification is (
        VerificationState.PENDING_RECHECK
    )
    assert by_key["dup|b"].verification is VerificationState.CURRENT


def test_action_guard_blocks_cross_file_same_id_and_root_mismatch():
    report = _report(
        [_issue("dup|b", path="b.jpg")],
        [_coverage("b.jpg", "duplicate_boxes")],
    )
    issue = report.issues[0]
    reason = action_target_problem(
        report,
        issue,
        dataset_root="D:/data",
        output_dir="",
        current_relative_path="a.jpg",
    )
    assert "禁止跨文件" in reason

    ok = action_target_problem(
        report,
        issue,
        dataset_root="D:/data",
        output_dir="",
        current_relative_path="b.jpg",
    )
    assert ok == ""

    other_output = action_target_problem(
        report,
        issue,
        dataset_root="D:/data",
        output_dir="D:/labels",
        current_relative_path="b.jpg",
    )
    assert "输出目录" in other_output

    stale = action_target_problem(
        report,
        replace(issue, verification=VerificationState.STALE),
        dataset_root="D:/data",
        output_dir="",
        current_relative_path="b.jpg",
    )
    assert "需先复查" in stale
