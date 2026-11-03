"""Cancellable inspection runner with explicit coverage and terminal states."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from .models import (
    CoverageEntry,
    CoverageState,
    FileSnapshot,
    InspectionIssue,
    InspectionProfile,
    IssueLocation,
    IssueSeverity,
    Manifest,
    RunReport,
    RunScope,
    RunState,
    new_run_id,
    utc_now_iso,
)
from .profiles import (
    RuleCatalog,
    build_default_catalog,
    effective_profile_snapshot,
    prepare_profile,
)
from .rules import RuleContext, RuleOutcome


def _cancel_checker(
    cancel_event: Optional[threading.Event],
    should_cancel: Optional[Callable[[], bool]],
) -> Callable[[], bool]:
    def check() -> bool:
        if cancel_event is not None and cancel_event.is_set():
            return True
        if should_cancel is not None and should_cancel():
            return True
        return False

    return check


def _stage_applies(profile_stage: str, rule_stage: str) -> bool:
    if rule_stage == "pre_label":
        return profile_stage == "pre_label"
    if rule_stage == "in_progress":
        return profile_stage in ("in_progress", "post_label")
    return True


def _merge_issues(
    issues: Iterable[InspectionIssue],
) -> tuple[InspectionIssue, ...]:
    grouped: dict[str, list[InspectionIssue]] = {}
    for issue in issues:
        grouped.setdefault(issue.family_key, []).append(issue)
    merged: list[InspectionIssue] = []
    for family_key, members in grouped.items():
        ordered = sorted(
            members,
            key=lambda item: (
                -int(item.severity == IssueSeverity.ERROR),
                item.issue_id,
            ),
        )
        primary = ordered[0]
        evidence = []
        seen = set()
        for member in ordered:
            for item in member.evidence:
                key = (
                    item.rule_id,
                    item.implementation_version,
                    item.message,
                    item.snapshot_digest,
                )
                if key in seen:
                    continue
                seen.add(key)
                evidence.append(item)
        object_ids = sorted(
            {
                object_id
                for member in ordered
                for object_id in member.location.object_ids
            }
        )
        shape_indices = sorted(
            {
                index
                for member in ordered
                for index in member.location.shape_indices
            }
        )
        location = IssueLocation(
            relative_path=primary.location.relative_path,
            image_path=primary.location.image_path,
            object_ids=tuple(object_ids),
            shape_indices=tuple(shape_indices),
            group_id=primary.location.group_id,
            region=primary.location.region,
            snapshot_digest=primary.location.snapshot_digest,
            ambiguous=any(member.location.ambiguous for member in ordered),
        )
        merged.append(
            replace(
                primary,
                family_key=family_key,
                evidence=tuple(evidence),
                location=location,
                severity=max(
                    (member.severity for member in ordered),
                    key=lambda value: (
                        value == IssueSeverity.ERROR,
                        value == IssueSeverity.WARNING,
                    ),
                ),
                updated_at=utc_now_iso(),
            )
        )
    merged.sort(
        key=lambda item: (
            item.location.relative_path,
            item.location.object_ids,
            item.title,
        )
    )
    return tuple(merged)


@dataclass(frozen=True)
class _RuleExecution:
    entry: CoverageEntry
    issues: tuple[InspectionIssue, ...] = ()
    truncated: bool = False
    cancelled: bool = False


class InspectionRunner:
    """Run a validated profile over an immutable manifest on any thread."""

    def __init__(
        self,
        catalog: Optional[RuleCatalog] = None,
        *,
        max_issues: int = 20000,
        allow_partial_profile: bool = False,
    ) -> None:
        self.catalog = catalog or build_default_catalog()
        self.max_issues = int(max_issues)
        self.allow_partial_profile = bool(allow_partial_profile)

    def run(
        self,
        manifest: Manifest,
        profile: InspectionProfile,
        scope: RunScope = RunScope.DATASET,
        *,
        cancel_event: Optional[threading.Event] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
        progress: Optional[Callable[[int, int, str], None]] = None,
        generation: int = 0,
    ) -> RunReport:
        started = utc_now_iso()
        run_id = new_run_id(profile.profile_id)
        check_cancel = _cancel_checker(cancel_event, should_cancel)
        prepared, validation = prepare_profile(profile, self.catalog)
        if not validation.valid:
            return RunReport(
                run_id=run_id,
                state=RunState.FAILED,
                scope=scope,
                dataset_root=manifest.dataset_root,
                output_root=manifest.output_root,
                manifest_fingerprint=manifest.fingerprint(),
                profile_snapshot=effective_profile_snapshot(
                    prepared, self.catalog
                ),
                coverage=(),
                issues=(),
                started_at=started,
                finished_at=utc_now_iso(),
                error="; ".join(validation.errors),
                requested_files=len(manifest.files) + len(manifest.errors),
                generation=generation,
                source_kind=_source_kind(manifest),
            )
        if validation.missing_rule_ids and not self.allow_partial_profile:
            return RunReport(
                run_id=run_id,
                state=RunState.FAILED,
                scope=scope,
                dataset_root=manifest.dataset_root,
                output_root=manifest.output_root,
                manifest_fingerprint=manifest.fingerprint(),
                profile_snapshot=effective_profile_snapshot(
                    prepared, self.catalog
                ),
                coverage=(),
                issues=(),
                started_at=started,
                finished_at=utc_now_iso(),
                error=(
                    "方案引用本机未登记规则: "
                    + ", ".join(validation.missing_rule_ids)
                ),
                requested_files=len(manifest.files) + len(manifest.errors),
                generation=generation,
                source_kind=_source_kind(manifest),
            )
        if not manifest.files:
            return RunReport(
                run_id=run_id,
                state=RunState.FAILED,
                scope=scope,
                dataset_root=manifest.dataset_root,
                output_root=manifest.output_root,
                manifest_fingerprint=manifest.fingerprint(),
                profile_snapshot=effective_profile_snapshot(
                    prepared, self.catalog
                ),
                coverage=(),
                issues=(),
                started_at=started,
                finished_at=utc_now_iso(),
                error="所选范围没有可检查的图片文件",
                requested_files=0,
                generation=generation,
                source_kind=_source_kind(manifest),
            )
        coverage: list[CoverageEntry] = []
        raw_issues: list[InspectionIssue] = []
        covered: set[tuple[str, str]] = set()
        truncated = False
        cancelled = False
        total = len(manifest.files)
        enabled_rules = prepared.enabled_rules
        for file_index, file in enumerate(manifest.files, 1):
            if check_cancel():
                cancelled = True
                break
            executions, file_cancelled = self._run_file(
                file, enabled_rules, prepared, check_cancel
            )
            for execution in executions:
                coverage.append(execution.entry)
                covered.add(
                    (execution.entry.relative_path, execution.entry.rule_id)
                )
                raw_issues.extend(execution.issues)
                if execution.truncated:
                    truncated = True
            if progress is not None:
                progress(file_index, total, file.relative_path)
            if file_cancelled:
                cancelled = True
                break
        for file in manifest.files:
            for rule in enabled_rules:
                if (file.relative_path, rule.rule_id) in covered:
                    continue
                coverage.append(
                    CoverageEntry(
                        file.relative_path,
                        rule.rule_id,
                        (
                            CoverageState.CANCELLED
                            if cancelled
                            else CoverageState.NOT_RUN
                        ),
                        "运行已取消" if cancelled else "未执行",
                    )
                )
        manifest_error_paths = set()
        for error in manifest.errors:
            relative = str(error.get("relative_path", ""))
            manifest_error_paths.add(relative)
            coverage.append(
                CoverageEntry(
                    relative,
                    "__manifest__",
                    CoverageState.FAILED,
                    str(error.get("error", "文件读取失败")),
                )
            )
            raw_issues.append(
                InspectionIssue(
                    issue_id=f"manifest-{relative}",
                    family_key=f"manifest|{relative}",
                    title="文件读取失败",
                    message=str(error.get("error", "")),
                    severity=IssueSeverity.ERROR,
                    location=IssueLocation(
                        relative_path=relative,
                        image_path=str(error.get("image_path", "")),
                    ),
                    evidence=(),
                    suggested_action="检查文件权限或内容后重试该文件。",
                )
            )
        merged_issues = _merge_issues(raw_issues)
        if len(merged_issues) > self.max_issues:
            merged_issues = merged_issues[: self.max_issues]
            truncated = True
        completed_files = _count_completed_files(manifest, coverage)
        requested_paths = {
            file.relative_path for file in manifest.files
        } | manifest_error_paths
        failed_paths = {
            entry.relative_path
            for entry in coverage
            if entry.state is CoverageState.FAILED
        } | manifest_error_paths
        failed_files = len(failed_paths)
        not_run_files = _count_state_files(
            manifest,
            coverage,
            CoverageState.NOT_RUN,
            CoverageState.CANCELLED,
            CoverageState.SKIPPED,
        )
        state = _terminal_state(
            cancelled=cancelled,
            failed_files=failed_files,
            not_run_files=not_run_files,
            truncated=truncated,
            missing_rules=bool(validation.missing_rule_ids),
        )
        return RunReport(
            run_id=run_id,
            state=state,
            scope=scope,
            dataset_root=manifest.dataset_root,
            output_root=manifest.output_root,
            manifest_fingerprint=manifest.fingerprint(),
            profile_snapshot=effective_profile_snapshot(
                prepared, self.catalog
            ),
            coverage=tuple(coverage),
            issues=merged_issues,
            started_at=started,
            finished_at=utc_now_iso(),
            requested_files=len(requested_paths),
            completed_files=completed_files,
            failed_files=failed_files,
            not_run_files=not_run_files,
            truncated=truncated,
            error=(
                "方案包含未登记规则，仅执行可用子集"
                if validation.missing_rule_ids
                else ""
            ),
            generation=generation,
            source_kind=_source_kind(manifest),
        )

    def _run_file(
        self,
        file: FileSnapshot,
        rules: Sequence[Any],
        prepared: InspectionProfile,
        check_cancel: Callable[[], bool],
    ) -> tuple[list[_RuleExecution], bool]:
        executions: list[_RuleExecution] = []
        for rule in rules:
            if check_cancel():
                return executions, True
            execution = self._run_rule(file, rule, prepared, check_cancel)
            executions.append(execution)
            if execution.cancelled:
                return executions, True
        return executions, False

    def _run_rule(
        self,
        file: FileSnapshot,
        rule: Any,
        prepared: InspectionProfile,
        check_cancel: Callable[[], bool],
    ) -> _RuleExecution:
        meta = self.catalog.meta(rule.rule_id)
        if meta is None:
            return _RuleExecution(
                CoverageEntry(
                    file.relative_path,
                    rule.rule_id,
                    CoverageState.FAILED,
                    "规则未登记",
                )
            )
        if not _stage_applies(prepared.stage, meta.stage):
            return _RuleExecution(
                CoverageEntry(
                    file.relative_path,
                    rule.rule_id,
                    CoverageState.SKIPPED,
                    f"当前阶段 {prepared.stage} 不适用",
                )
            )
        if file.annotation_state == "error":
            return _RuleExecution(
                CoverageEntry(
                    file.relative_path,
                    rule.rule_id,
                    CoverageState.FAILED,
                    file.error or "标注文件读取失败",
                )
            )
        if file.annotation_state == "missing":
            return _RuleExecution(
                CoverageEntry(
                    file.relative_path,
                    rule.rule_id,
                    CoverageState.SKIPPED,
                    "缺少标注文件；仍需图像查漏",
                )
            )
        started_rule = time.perf_counter()
        try:
            executor = self.catalog.executor(rule.rule_id)
            if executor is None:
                raise RuntimeError("规则执行器缺失")
            outcome = executor(
                RuleContext(
                    profile=prepared,
                    file=file,
                    should_cancel=check_cancel,
                ),
                dict(rule.parameters),
            )
            if not isinstance(outcome, RuleOutcome):
                raise TypeError("规则返回值不是 RuleOutcome")
        except Exception as error:  # noqa: BLE001
            return _RuleExecution(
                CoverageEntry(
                    file.relative_path,
                    rule.rule_id,
                    CoverageState.FAILED,
                    f"{type(error).__name__}: {error}",
                )
            )
        elapsed = (time.perf_counter() - started_rule) * 1000.0
        entry = CoverageEntry(
            file.relative_path,
            rule.rule_id,
            outcome.state,
            outcome.reason,
            issue_count=len(outcome.issues),
            duration_ms=elapsed,
        )
        return _RuleExecution(
            entry=entry,
            issues=outcome.issues,
            truncated=outcome.truncated,
            cancelled=outcome.state == CoverageState.CANCELLED,
        )


def _source_kind(manifest: Manifest) -> str:
    if any(file.unsaved for file in manifest.files):
        return "memory"
    return "disk"


def _terminal_state(
    *,
    cancelled: bool,
    failed_files: int,
    not_run_files: int,
    truncated: bool,
    missing_rules: bool,
) -> RunState:
    if cancelled:
        return RunState.CANCELLED
    if failed_files or not_run_files or truncated or missing_rules:
        return RunState.PARTIAL
    return RunState.COMPLETED


def _count_state_files(
    manifest: Manifest,
    coverage: Sequence[CoverageEntry],
    *states: CoverageState,
) -> int:
    if not states:
        return 0
    selected = set(states)
    files = {
        entry.relative_path for entry in coverage if entry.state in selected
    }
    return len(
        files.intersection({file.relative_path for file in manifest.files})
    )


def _count_completed_files(
    manifest: Manifest, coverage: Sequence[CoverageEntry]
) -> int:
    by_file: dict[str, set[CoverageState]] = {}
    for entry in coverage:
        by_file.setdefault(entry.relative_path, set()).add(entry.state)
    completed = 0
    for file in manifest.files:
        states = by_file.get(file.relative_path, set())
        if states and states.issubset(
            {CoverageState.COMPLETED, CoverageState.NOT_APPLICABLE}
        ):
            completed += 1
    return completed
