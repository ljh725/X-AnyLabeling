"""Legacy issue import and loss-aware report export."""

from __future__ import annotations

import csv
import json
import os
import os.path as osp
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from .models import (
    ActionState,
    Decision,
    IssueEvidence,
    IssueLocation,
    IssueSeverity,
    InspectionIssue,
    Manifest,
    RunReport,
    VerificationState,
    stable_issue_id,
    utc_now_iso,
)
from .storage import atomic_write_json, read_json

LEGACY_COLUMNS = (
    "issue_id",
    "file_path",
    "shape_index",
    "shape_id",
    "rule_name",
    "severity",
    "message",
    "label",
    "group_id",
)

EXPORT_COLUMNS = LEGACY_COLUMNS + (
    "rule_id",
    "decision",
    "verification",
    "object_ids",
    "region",
)


@dataclass(frozen=True)
class ImportResult:
    """Imported issues plus explicit errors and ambiguous path records."""

    issues: tuple[InspectionIssue, ...]
    errors: tuple[Mapping[str, Any], ...] = ()
    ambiguous: tuple[Mapping[str, Any], ...] = ()
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "imported": len(self.issues),
            "errors": [dict(item) for item in self.errors],
            "ambiguous": [dict(item) for item in self.ambiguous],
        }


def _resolve_relative(
    raw_path: str,
    manifest: Optional[Manifest],
) -> tuple[str, bool, str]:
    if manifest is None:
        return raw_path.replace("\\", "/"), True, "无文件清单，无法核验路径"
    normalized = raw_path.replace("\\", "/")
    candidates = []
    for file in manifest.files:
        if normalized in (
            file.relative_path,
            file.image_path.replace("\\", "/"),
            file.annotation_path.replace("\\", "/"),
        ):
            candidates.append(file)
            continue
        if osp.basename(normalized) in (
            osp.basename(file.relative_path),
            osp.basename(file.image_path),
        ):
            candidates.append(file)
    unique = {file.relative_path: file for file in candidates}
    if len(unique) == 1:
        file = next(iter(unique.values()))
        return file.relative_path, False, ""
    if not unique:
        return raw_path.replace("\\", "/"), True, "清单中找不到该文件"
    return raw_path.replace("\\", "/"), True, "多个同名文件，无法唯一映射"


def _severity(value: str) -> IssueSeverity:
    try:
        return IssueSeverity(str(value))
    except ValueError:
        return IssueSeverity.WARNING


def _flatten_issue_row(row: Mapping[str, Any]) -> Mapping[str, Any]:
    """Flatten one native report issue without losing its location/evidence."""
    flattened = dict(row)
    location = row.get("location")
    if isinstance(location, Mapping):
        for key in (
            "relative_path",
            "image_path",
            "object_ids",
            "shape_indices",
            "group_id",
            "region",
            "snapshot_digest",
            "ambiguous",
        ):
            if key in location and key not in flattened:
                flattened[key] = location[key]
    evidence = row.get("evidence")
    if isinstance(evidence, (list, tuple)) and evidence:
        first = evidence[0]
        if isinstance(first, Mapping):
            for key in (
                "rule_id",
                "rule_name",
                "message",
                "severity",
                "metrics",
                "thresholds",
                "snapshot_digest",
                "relation",
                "filtered_reason",
            ):
                if key in first and key not in flattened:
                    flattened[key] = first[key]
            if "source" in first and "source" not in flattened:
                flattened["source"] = first["source"]
    return flattened


def _issue_from_mapping(
    row: Mapping[str, Any],
    *,
    source: str,
    manifest: Optional[Manifest],
) -> tuple[Optional[InspectionIssue], Optional[Mapping[str, Any]], bool]:
    row = _flatten_issue_row(row)
    raw_path = str(
        row.get("file_path")
        or row.get("relative_path")
        or row.get("image_path")
        or ""
    ).strip()
    if not raw_path:
        return None, {"row": dict(row), "error": "缺少文件路径"}, False
    relative, ambiguous, ambiguity_reason = _resolve_relative(
        raw_path, manifest
    )
    object_ids = []
    raw_ids = row.get("object_ids")
    if isinstance(raw_ids, (list, tuple)):
        object_ids = [str(item) for item in raw_ids if str(item)]
    shape_id = str(row.get("shape_id", "") or "")
    if shape_id:
        object_ids.append(shape_id)
    shape_indices = []
    raw_index = row.get("shape_index")
    if raw_index not in (None, "", -1, "-1"):
        try:
            shape_indices.append(int(raw_index))
        except (TypeError, ValueError):
            pass
    region_raw = row.get("region")
    region = None
    if isinstance(region_raw, (list, tuple)) and len(region_raw) >= 4:
        try:
            region = tuple(float(item) for item in region_raw[:4])
        except (TypeError, ValueError):
            region = None
    rule_id = str(row.get("rule_id") or row.get("rule_name") or "imported")
    rule_name = str(row.get("rule_name") or rule_id)
    message = str(row.get("message") or row.get("reason") or "")
    family = str(row.get("family_key") or "") or (
        f"import|{source}|{relative}|{rule_id}|"
        + ",".join(sorted(object_ids))
        + f"|{shape_indices}"
    )
    issue_id = str(row.get("issue_id") or "") or stable_issue_id(
        family, "import", relative, object_ids, region
    )
    location = IssueLocation(
        relative_path=relative,
        object_ids=tuple(object_ids),
        shape_indices=tuple(shape_indices),
        region=region,
        snapshot_digest=str(row.get("snapshot_digest", "")),
        ambiguous=ambiguous,
    )
    metrics_payload = row.get("metrics")
    metrics = (
        {
            str(key): float(value)
            for key, value in metrics_payload.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        if isinstance(metrics_payload, Mapping)
        else {
            key: float(value)
            for key, value in row.items()
            if key not in EXPORT_COLUMNS
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        }
    )
    decision_raw = str(row.get("decision", "pending"))
    decision = (
        Decision(decision_raw)
        if decision_raw in {item.value for item in Decision}
        else Decision.PENDING
    )
    action_raw = str(row.get("action", "unchanged"))
    action = (
        ActionState(action_raw)
        if action_raw in {item.value for item in ActionState}
        else ActionState.UNCHANGED
    )
    verification_raw = str(row.get("verification", "unverifiable"))
    verification = (
        VerificationState(verification_raw)
        if verification_raw in {item.value for item in VerificationState}
        else VerificationState.UNVERIFIABLE
    )
    evidence = IssueEvidence(
        rule_id=rule_id,
        implementation_version=str(
            row.get("implementation_version", "legacy-import")
        ),
        rule_name=rule_name,
        message=message,
        severity=_severity(str(row.get("severity", "warning"))),
        metrics=metrics,
        thresholds=(
            dict(row.get("thresholds", {}))
            if isinstance(row.get("thresholds"), Mapping)
            else {}
        ),
        snapshot_digest=str(row.get("snapshot_digest", "")),
        relation=str(row.get("relation", "")),
        filtered_reason=str(row.get("filtered_reason", "")),
        source=str(row.get("source", source)),
    )
    issue = InspectionIssue(
        issue_id=issue_id,
        family_key=family,
        title=str(row.get("title") or rule_name),
        message=message,
        severity=_severity(str(row.get("severity", "warning"))),
        location=location,
        evidence=(evidence,),
        suggested_action=str(row.get("suggested_action", "")),
        decision=decision,
        action=action,
        verification=verification,
        created_at=str(row.get("created_at", utc_now_iso())),
        updated_at=str(row.get("updated_at", utc_now_iso())),
    )
    ambiguous_record = (
        {
            "raw_path": raw_path,
            "relative_path": relative,
            "reason": ambiguity_reason,
            "issue_id": issue_id,
        }
        if ambiguous
        else None
    )
    return issue, ambiguous_record, ambiguous


def _rows_from_tsv(
    path: str,
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    rows: list[Mapping[str, Any]] = []
    errors: list[Mapping[str, Any]] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        delimiter = "\t" if sample.count("\t") >= sample.count(",") else ","
        reader = csv.DictReader(handle, delimiter=delimiter)
        if not reader.fieldnames:
            return [], [{"error": "TSV/CSV 没有表头"}]
        for line_number, row in enumerate(reader, 2):
            if not any(str(value or "").strip() for value in row.values()):
                continue
            if not any(row.get(column) for column in LEGACY_COLUMNS):
                errors.append(
                    {"line": line_number, "error": "无法识别的问题行"}
                )
                continue
            rows.append(row)
    return rows, errors


def import_legacy_report(
    path: str,
    *,
    manifest: Optional[Manifest] = None,
    source: str = "",
) -> ImportResult:
    """Import beta4-style TSV/CSV or JSON reports without replacing a queue."""
    source = source or osp.splitext(osp.basename(path))[0]
    extension = osp.splitext(path)[1].lower()
    errors: list[Mapping[str, Any]] = []
    ambiguous: list[Mapping[str, Any]] = []
    if extension == ".json":
        payload = read_json(path)
        if isinstance(payload, Mapping):
            raw_rows = payload.get("issues", [])
        elif isinstance(payload, list):
            raw_rows = payload
        else:
            return ImportResult(
                (),
                ({"error": "JSON 报告必须是对象或数组"},),
                source=source,
            )
    else:
        raw_rows, parse_errors = _rows_from_tsv(path)
        errors.extend(parse_errors)
    issues: list[InspectionIssue] = []
    for index, row in enumerate(raw_rows or []):
        if not isinstance(row, Mapping):
            errors.append({"index": index, "error": "问题记录不是对象"})
            continue
        issue, ambiguity, is_ambiguous = _issue_from_mapping(
            row, source=source, manifest=manifest
        )
        if issue is None:
            if ambiguity:
                errors.append(ambiguity)
            continue
        issues.append(issue)
        if is_ambiguous and ambiguity:
            ambiguous.append(ambiguity)
    return ImportResult(
        issues=tuple(issues),
        errors=tuple(errors),
        ambiguous=tuple(ambiguous),
        source=source,
    )


def export_report(
    report: RunReport,
    json_path: str,
    tsv_path: str = "",
) -> tuple[str, str]:
    """Export the complete report; optional TSV is explicitly lossy."""
    payload = report.to_dict()
    payload["exported_at"] = utc_now_iso()
    atomic_write_json(json_path, payload)
    if not tsv_path:
        return json_path, ""
    directory = os.path.dirname(os.path.abspath(tsv_path))
    os.makedirs(directory, exist_ok=True)
    with open(tsv_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(EXPORT_COLUMNS)
        for issue in report.issues:
            writer.writerow(
                [
                    issue.issue_id,
                    issue.location.relative_path,
                    (
                        issue.location.shape_indices[0]
                        if issue.location.shape_indices
                        else -1
                    ),
                    (
                        issue.location.object_ids[0]
                        if issue.location.object_ids
                        else ""
                    ),
                    issue.evidence[0].rule_name if issue.evidence else "",
                    issue.severity.value,
                    issue.message,
                    "",
                    (
                        ""
                        if issue.location.group_id is None
                        else issue.location.group_id
                    ),
                    ",".join(
                        sorted({item.rule_id for item in issue.evidence})
                    ),
                    issue.decision.value,
                    issue.verification.value,
                    ",".join(issue.location.object_ids),
                    (
                        ",".join(str(value) for value in issue.location.region)
                        if issue.location.region
                        else ""
                    ),
                ]
            )
    return json_path, tsv_path
