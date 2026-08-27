"""
Report writer + quality-run orchestrator.

Drives the full pipeline:

    annotation JSON
        ↓ QcShapeLoader
    L1 + L2 rules
        ↓
    review.tsv + report.json

Run is read-only: no JSON is written back.  ``run_id`` is generated
deterministically from the inputs (input root + profile id + file paths)
so re-runs on the same batch produce stable ``issue_id`` values.
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import json
import logging
import os
import os.path as osp
from typing import Any, Callable, Dict, List, Optional

from .l1_rules import run_l1
from .l2_rules import run_l2
from .matching import MatchingCfg, matching_cfg_from_profile
from .quality_issue import QcFile, QualityIssue, QualityReport, QcShapeLoader
from .threshold_profile import (
    ThresholdProfile,
    load_threshold_profile,
    threshold_to_snapshot,
)

logger = logging.getLogger(__name__)

REVIEW_TSV_COLUMNS = [
    "issue_id",
    "file_path",
    "shape_index",
    "shape_id",
    "rule_name",
    "severity",
    "message",
    "label",
    "group_id",
]

CHECKER_VERSION = "stage1_l1_l2_v0"


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


def run_quality_check(
    json_paths: List[str],
    profile: Optional[ThresholdProfile] = None,
    profile_path: Optional[str] = None,
    input_root: str = "",
    image_dir: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> QualityReport:
    """Run L1 + L2 over a batch and return a ``QualityReport``.

    Args:
        json_paths: annotation JSON files to check.
        profile: pre-loaded threshold profile. If None, ``profile_path``
            (or the bundled v0 profile) is loaded.
        profile_path: path to a threshold YAML (used when profile None).
        input_root: descriptive root for the source block.
        image_dir: optional image directory (recorded in source only).
        progress_callback: optional (current, total, filename).

    Returns:
        a populated ``QualityReport``.
    """
    if profile is None:
        profile = load_threshold_profile(profile_path)

    cfg = matching_cfg_from_profile(profile.config)

    loader = QcShapeLoader()
    loader.load(json_paths, progress_callback=progress_callback)

    run_id = _make_run_id(input_root or "", profile.profile_id, json_paths)
    created_at = _now_iso()

    all_issues: List[QualityIssue] = []
    for qc_file in loader.files:
        for issue in run_l1(qc_file, profile):
            _attach_shape_identity(issue, qc_file)
            issue.run_id = run_id
            all_issues.append(issue)
        for issue in run_l2(qc_file, profile, cfg):
            _attach_shape_identity(issue, qc_file)
            issue.run_id = run_id
            all_issues.append(issue)

    thresholds_snapshot = {
        rt.rule_id: threshold_to_snapshot(rt) for rt in profile.rules
    }

    report = QualityReport(
        run_id=run_id,
        created_at=created_at,
        threshold_profile=profile.profile_id,
        thresholds=thresholds_snapshot,
        source={
            "input_root": input_root,
            "image_dir": image_dir or "",
            "checker_version": CHECKER_VERSION,
            "file_count": len(json_paths),
            "files_loaded": loader.file_count,
            "files_failed": [
                {"path": p, "error": e} for p, e in loader.files_failed
            ],
        },
        issues=all_issues,
        total_files=loader.file_count,
        total_shapes=loader.total_shapes,
    )
    return report


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def write_review_tsv(report: QualityReport, path: str) -> str:
    """Write the Inspector-importable ``review.tsv``."""
    os.makedirs(osp.dirname(osp.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(REVIEW_TSV_COLUMNS)
        for issue in report.issues:
            writer.writerow(
                [
                    issue.issue_id(),
                    issue.file_path,
                    issue.shape_index,
                    issue.shape_id,
                    issue.rule_name,
                    issue.severity,
                    issue.message,
                    issue.label,
                    "" if issue.group_id is None else str(issue.group_id),
                ]
            )
    logger.info(f"Wrote review.tsv → {path} ({report.total_issues} rows)")
    return path


def write_report_json(report: QualityReport, path: str) -> str:
    """Write the full evidence ``report.json``."""
    os.makedirs(osp.dirname(osp.abspath(path)), exist_ok=True)

    by_rule = {
        name: len(issues) for name, issues in report.issues_by_rule().items()
    }
    by_severity = report.issues_by_severity()

    payload: Dict[str, Any] = {
        "schema_version": "l1_l2_qc.v1",
        "run_id": report.run_id,
        "created_at": report.created_at,
        "source": report.source,
        "threshold_profile": report.threshold_profile,
        "thresholds": report.thresholds,
        "summary": {
            "total_files": report.total_files,
            "total_shapes": report.total_shapes,
            "total_issues": report.total_issues,
            "issues_by_rule": by_rule,
            "issues_by_severity": by_severity,
        },
        "issues": [issue.to_dict() for issue in report.issues],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    logger.info(
        f"Wrote report.json → {path} "
        f"({report.total_issues} issues, {report.total_files} files)"
    )
    return path


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _attach_shape_identity(issue: QualityIssue, qc_file: QcFile) -> None:
    """Attach the persistent Shape identity matching an issue's index."""
    if 0 <= issue.shape_index < len(qc_file.shapes):
        issue.shape_id = qc_file.shapes[issue.shape_index].shape_id


def _make_run_id(
    input_root: str, profile_id: str, json_paths: List[str]
) -> str:
    normalized_paths = [osp.abspath(p) for p in sorted(json_paths)]
    raw = json.dumps(
        {
            "checker_version": CHECKER_VERSION,
            "input_root": osp.abspath(input_root) if input_root else "",
            "profile_id": profile_id,
            "json_paths": normalized_paths,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    h = hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]
    return f"{CHECKER_VERSION}-{h}"


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")
