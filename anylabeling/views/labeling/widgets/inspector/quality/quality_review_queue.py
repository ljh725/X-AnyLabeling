"""
Pure-Python quality review queue model.

Maintains the in-memory list of L1/L2 quality issues loaded from a
``report.json`` (or lightweight ``review.tsv``), merges human review
decisions from ``review_feedback.tsv``, and supports:

- filtering (status / severity / rule / current file)
- sorting (severity > unreviewed > metric risk > file path)
- per-issue review updates (decision / final_action / note)
- writing back ``review_feedback.tsv`` while preserving existing reviews
- merging a re-scan of one file without losing prior feedback
  (disappeared issues are tagged ``resolved_after_rescan``)

This module has NO PyQt dependency so it stays unit-testable in a plain
Python environment (per the quality-acceptance hard constraint).
"""

from __future__ import annotations

import datetime
import json
import logging
import os.path as osp
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .feedback import (
    FEEDBACK_TEMPLATE_COLUMNS,
    VALID_DECISIONS,
    VALID_FINAL_ACTIONS,
    _load_existing_feedback,
    read_review_feedback,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# UI queue statuses (section 8.2).  The first set are the "actionable"
# review outcomes; ``resolved_after_rescan`` is a derived state set when a
# previously-seen issue is no longer produced by a re-scan.
VALID_STATUSES = {
    "pending",
    "viewed",
    "fixed",
    "confirmed_error",
    "false_positive",
    "acceptable",
    "needs_discussion",
    "resolved_after_rescan",
}

# Statuses that count as "reviewed" (have a human decision behind them).
REVIEWED_STATUSES = {
    "fixed",
    "confirmed_error",
    "false_positive",
    "acceptable",
    "needs_discussion",
}

# Severity sort rank (higher = surfaced first).
_SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}

# Conservative default; the UI exposes a selector for more specific fixes.
DEFAULT_FIXED_ACTION = "fixed_box"


# ---------------------------------------------------------------------------
# Status <-> feedback decision mapping (section 8.2)
# ---------------------------------------------------------------------------

# status -> (decision, final_action)
STATUS_TO_FEEDBACK: Dict[str, tuple] = {
    "pending": ("", ""),
    "viewed": ("", ""),
    "fixed": ("fixed", DEFAULT_FIXED_ACTION),
    "confirmed_error": ("confirmed_error", "none"),
    "false_positive": ("false_positive", "ignored"),
    "acceptable": ("acceptable", "ignored"),
    "needs_discussion": ("needs_discussion", "escalated"),
    "resolved_after_rescan": ("", ""),
}

# decision -> status  (reverse mapping used when loading feedback)
DECISION_TO_STATUS: Dict[str, str] = {
    "": "pending",
    "fixed": "fixed",
    "confirmed_error": "confirmed_error",
    "false_positive": "false_positive",
    "acceptable": "acceptable",
    "needs_discussion": "needs_discussion",
}


def status_from_decision(decision: str) -> str:
    """Map a feedback ``decision`` to a UI queue ``status``."""
    return DECISION_TO_STATUS.get(decision, "pending")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class QualityReviewItem:
    """One issue in the review queue."""

    issue_id: str
    run_id: str
    file_path: str
    shape_index: int  # -1 for file-level issues
    rule_id: str
    rule_name: str
    severity: str
    message: str
    shape_id: str = ""
    label: str = ""
    group_id: Optional[int] = None
    primary_metric_name: str = ""
    primary_metric_value: float = 0.0
    primary_metric_direction: str = "higher_is_worse"
    # review state
    status: str = "pending"
    decision: str = ""
    final_action: str = ""
    reviewer: str = ""
    reviewed_at: str = ""
    note: str = ""
    # misc preserved evidence
    original_severity: str = ""

    @property
    def is_reviewed(self) -> bool:
        return self.status in REVIEWED_STATUSES

    def to_feedback_row(self) -> Dict[str, Any]:
        """Render as a review_feedback.tsv row (template columns)."""
        return {
            "issue_id": self.issue_id,
            "run_id": self.run_id,
            "file_path": self.file_path,
            "shape_index": self.shape_index,
            "shape_id": self.shape_id,
            "rule_name": self.rule_name,
            "original_severity": self.original_severity or self.severity,
            "decision": self.decision,
            "final_action": self.final_action or "none",
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at,
            "note": self.note,
            "message": self.message,
            "label": self.label,
            "group_id": "" if self.group_id is None else str(self.group_id),
            "primary_metric_name": self.primary_metric_name,
            "primary_metric_value": (
                ""
                if self.primary_metric_value == 0.0
                and not self.primary_metric_name
                else f"{self.primary_metric_value:.4f}"
            ),
        }


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


class QualityReviewQueue:
    """In-memory review queue over a set of quality issues.

    Usage::

        q = QualityReviewQueue()
        q.load_report("report.json")          # primary evidence source
        q.merge_feedback("review_feedback.tsv")  # overlay human reviews
        for item in q.sorted_items():
            ...
        q.update_review(item.issue_id, status="false_positive")
        q.write_feedback("review_feedback.tsv")
    """

    def __init__(self) -> None:
        self._items: Dict[str, QualityReviewItem] = {}
        self._report_path: Optional[str] = None
        self._review_tsv_path: Optional[str] = None
        self._feedback_path: Optional[str] = None
        self._run_id: str = ""

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def report_path(self) -> Optional[str]:
        return self._report_path

    @property
    def review_tsv_path(self) -> Optional[str]:
        return self._review_tsv_path

    @property
    def has_report(self) -> bool:
        return self._report_path is not None

    @property
    def feedback_path(self) -> Optional[str]:
        return self._feedback_path

    @property
    def total(self) -> int:
        return len(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self):
        return iter(self._items.values())

    def get(self, issue_id: str) -> Optional[QualityReviewItem]:
        return self._items.get(issue_id)

    def items(self) -> List[QualityReviewItem]:
        return list(self._items.values())

    def clear(self) -> None:
        self._items.clear()
        self._report_path = None
        self._review_tsv_path = None
        self._feedback_path = None
        self._run_id = ""

    # ------------------------------------------------------------------
    # Loaders (A2, A3, A4)
    # ------------------------------------------------------------------

    def load_report(self, report_path: str) -> int:
        """Load issues from a ``report.json`` (primary evidence source).

        Returns the number of issues loaded.  Replaces any existing items.
        """
        report = _load_json(report_path)
        self._report_path = report_path
        self._review_tsv_path = None
        self._run_id = str(report.get("run_id", "") or "")
        self._items.clear()
        count = 0
        for raw in report.get("issues", []) or []:
            item = _item_from_report_issue(raw, self._run_id)
            if item is not None:
                self._items[item.issue_id] = item
                count += 1
        logger.info(
            f"QualityReviewQueue.load_report: {count} issues from "
            f"{report_path}"
        )
        return count

    def load_review_tsv(self, tsv_path: str) -> int:
        """Load lightweight issues from a ``review.tsv``.

        review.tsv has fewer fields than report.json (no metrics); the
        items are created with empty primary metric.  Replaces existing.
        """
        self._report_path = None
        self._review_tsv_path = tsv_path
        self._items.clear()
        count = 0
        for row in _iter_tsv(tsv_path):
            item = _item_from_review_row(row)
            if item is not None:
                self._items[item.issue_id] = item
                count += 1
        logger.info(
            f"QualityReviewQueue.load_review_tsv: {count} issues from "
            f"{tsv_path}"
        )
        return count

    def merge_feedback(self, feedback_path: str) -> int:
        """Overlay human review decisions onto existing items by issue_id.

        Returns the number of items updated.  Items present in the
        feedback file but not in the queue are ignored (they belong to a
        different run).  Sets ``self._feedback_path``.
        """
        self._feedback_path = feedback_path
        result = read_review_feedback(feedback_path, strict=False)
        updated = 0
        for fb in result.rows:
            item = self._items.get(fb.issue_id)
            if item is None:
                continue
            item.decision = fb.decision
            item.final_action = fb.final_action
            item.note = fb.note
            item.reviewer = fb.reviewer
            item.reviewed_at = fb.reviewed_at
            # derive status from decision (unless this is a stale review
            # for an issue that was already resolved by a rescan)
            if item.status != "resolved_after_rescan":
                item.status = status_from_decision(fb.decision)
            updated += 1
        if result.errors:
            logger.warning(
                f"merge_feedback errors in {feedback_path}: "
                f"{len(result.errors)}"
            )
        logger.info(
            f"QualityReviewQueue.merge_feedback: {updated} items updated "
            f"from {feedback_path}"
        )
        return updated

    # ------------------------------------------------------------------
    # Filter / sort (A5)
    # ------------------------------------------------------------------

    def filter(
        self,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        rule_id: Optional[str] = None,
        rule_name: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> List[QualityReviewItem]:
        """Return items matching ALL of the provided filters."""
        out: List[QualityReviewItem] = []
        for item in self._items.values():
            if status is not None and item.status != status:
                continue
            if severity is not None and item.severity != severity:
                continue
            if rule_id is not None and item.rule_id != rule_id:
                continue
            if rule_name is not None and item.rule_name != rule_name:
                continue
            if file_path is not None and not _same_file_path(
                item.file_path, file_path
            ):
                continue
            out.append(item)
        return out

    def find_matching_file(self, file_path: Optional[str]) -> Optional[str]:
        """Return a queue JSON path matching ``file_path``.

        The active canvas path may be an image path while queue entries are
        JSON paths, so this falls back to basename stem matching after exact
        normalized path matching.
        """
        if not file_path:
            return None
        for item in self._items.values():
            if _same_file_path(item.file_path, file_path):
                return item.file_path
        return None

    def sorted_items(
        self,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        rule_id: Optional[str] = None,
        rule_name: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> List[QualityReviewItem]:
        """Filtered + sorted view (severity > unreviewed > metric > path)."""
        items = self.filter(
            status=status,
            severity=severity,
            rule_id=rule_id,
            rule_name=rule_name,
            file_path=file_path,
        )
        items.sort(key=_sort_key)
        return items

    def unique_rule_ids(self) -> List[str]:
        return sorted({i.rule_id for i in self._items.values() if i.rule_id})

    def unique_rule_names(self) -> List[str]:
        return sorted(
            {i.rule_name for i in self._items.values() if i.rule_name}
        )

    def unique_severities(self) -> List[str]:
        return sorted(
            {i.severity for i in self._items.values()},
            key=lambda s: _SEVERITY_RANK.get(s, 99),
        )

    # ------------------------------------------------------------------
    # Review update (A6)
    # ------------------------------------------------------------------

    def update_review(
        self,
        issue_id: str,
        status: Optional[str] = None,
        decision: Optional[str] = None,
        final_action: Optional[str] = None,
        note: Optional[str] = None,
        reviewer: str = "",
    ) -> Optional[QualityReviewItem]:
        """Update one issue's review state.

        Either ``status`` or ``decision`` may be supplied; if both are
        given they must be consistent.  When ``status`` is provided the
        decision/final_action are derived from the section-8.2 mapping
        (unless explicitly overridden).

        Returns the updated item, or None if the issue_id is unknown.
        """
        item = self._items.get(issue_id)
        if item is None:
            return None

        if decision is not None:
            if decision and decision not in VALID_DECISIONS:
                raise ValueError(f"invalid decision: {decision!r}")
            if final_action and final_action not in VALID_FINAL_ACTIONS:
                raise ValueError(f"invalid final_action: {final_action!r}")
            item.decision = decision
            item.final_action = final_action or ("none" if decision else "")
            if status is None:
                item.status = status_from_decision(decision)
        elif status is not None:
            if status not in VALID_STATUSES:
                raise ValueError(f"invalid status: {status!r}")
            dec, act = STATUS_TO_FEEDBACK.get(status, ("", ""))
            item.status = status
            item.decision = dec
            item.final_action = final_action or act
            if (
                item.final_action
                and item.final_action not in VALID_FINAL_ACTIONS
            ):
                raise ValueError(
                    f"invalid final_action: {item.final_action!r}"
                )
        else:
            # nothing to update status-wise
            pass

        if note is not None:
            item.note = note
        if reviewer:
            item.reviewer = reviewer
        # stamp reviewed_at whenever a real decision is recorded
        if item.decision:
            item.reviewed_at = _now_iso()
        elif item.status == "viewed":
            item.reviewed_at = ""
        return item

    def mark_viewed(self, issue_id: str) -> None:
        """Mark an issue as viewed without recording a decision."""
        item = self._items.get(issue_id)
        if item is None:
            return
        if item.status == "pending":
            item.status = "viewed"

    # ------------------------------------------------------------------
    # Write feedback (A7, E1, E2)
    # ------------------------------------------------------------------

    def write_feedback(self, output_path: str) -> int:
        """Write the current review state to ``review_feedback.tsv``.

        Preserves any existing rows for issue_ids that are no longer in
        the queue (e.g. from a different run) by merging them in.  The
        on-disk file is rewritten atomically.
        """
        existing = _load_existing_feedback(output_path)

        rows: List[Dict[str, Any]] = []
        for item in self._items.values():
            row = item.to_feedback_row()
            rows.append(row)
            # mark this issue_id as seen so we don't duplicate it below
            existing.pop(item.issue_id, None)

        # carry over rows from the previous feedback file that are not in
        # the current queue (preserves cross-run history)
        for issue_id, old in existing.items():
            old_norm = {k: v for k, v in old.items()}
            # ensure all template columns present
            full = _empty_feedback_row()
            full.update(old_norm)
            rows.append(full)

        _write_tsv(output_path, _FEEDBACK_TEMPLATE_COLUMNS, rows)
        logger.info(
            f"QualityReviewQueue.write_feedback: {len(rows)} rows -> "
            f"{output_path}"
        )
        return len(rows)

    # ------------------------------------------------------------------
    # Rescan merge (G7, 9.4)
    # ------------------------------------------------------------------

    def rescan_file(
        self,
        file_path: str,
        new_items: List[QualityReviewItem],
    ) -> Dict[str, int]:
        """Merge a re-scan of one file into the queue.

        - New issues (issue_id not previously known) are added as pending.
        - Re-appearing issues keep their existing review state.
        - Issues that belonged to ``file_path`` but no longer appear are
          tagged ``resolved_after_rescan`` (their feedback is preserved).

        Returns a small summary dict.
        """
        target = file_path
        new_ids = set()
        added = 0
        for item in new_items:
            # only items belonging to this file are relevant
            if not _same_file_path(item.file_path, target):
                continue
            new_ids.add(item.issue_id)
            if item.issue_id not in self._items:
                self._items[item.issue_id] = item
                added += 1
            else:
                # update evidence fields but keep review state
                existing = self._items[item.issue_id]
                _merge_evidence(existing, item)

        resolved = 0
        for item in self._items.values():
            if not _same_file_path(item.file_path, target):
                continue
            if item.issue_id in new_ids:
                continue
            if item.status != "resolved_after_rescan":
                item.status = "resolved_after_rescan"
                resolved += 1
        logger.info(
            f"rescan_file({file_path}): added={added}, resolved="
            f"{resolved}, new_total={len(self._items)}"
        )
        return {
            "added": added,
            "resolved": resolved,
            "total": len(self._items),
        }

    # ------------------------------------------------------------------
    # Stats (F1-F5)
    # ------------------------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        """Aggregate review stats over the whole queue.

        Counts exclude ``resolved_after_rescan`` from the "active" totals
        and exclude ``needs_discussion`` from the rate denominators
        (consistent with feedback aggregation, section 9).
        """
        total = len(self._items)
        by_status: Dict[str, int] = {}
        by_severity: Dict[str, int] = {}
        by_rule: Dict[str, Dict[str, int]] = {}
        reviewed = 0
        for item in self._items.values():
            by_status[item.status] = by_status.get(item.status, 0) + 1
            by_severity[item.severity] = by_severity.get(item.severity, 0) + 1
            rstats = by_rule.setdefault(
                item.rule_name,
                {
                    "total": 0,
                    "reviewed": 0,
                    "true_error": 0,
                    "false_positive": 0,
                    "acceptable": 0,
                    "needs_discussion": 0,
                },
            )
            rstats["total"] += 1
            if item.status in REVIEWED_STATUSES:
                reviewed += 1
                rstats["reviewed"] += 1
                if item.decision in ("confirmed_error", "fixed"):
                    rstats["true_error"] += 1
                elif item.decision == "false_positive":
                    rstats["false_positive"] += 1
                elif item.decision == "acceptable":
                    rstats["acceptable"] += 1
                elif item.decision == "needs_discussion":
                    rstats["needs_discussion"] += 1
        return {
            "total": total,
            "reviewed": reviewed,
            "unreviewed": total - reviewed,
            "by_status": by_status,
            "by_severity": by_severity,
            "by_rule": by_rule,
            "false_positive": by_status.get("false_positive", 0),
            "fixed": by_status.get("fixed", 0),
        }


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------


def _sort_key(item: QualityReviewItem) -> tuple:
    """severity asc(error first) > unreviewed first > metric risk > path."""
    sev = _SEVERITY_RANK.get(item.severity, 99)
    # unreviewed (pending/viewed) sorts before reviewed
    unreviewed_first = 0 if item.status in ("pending", "viewed") else 1
    metric_risk = -_metric_risk_score(item)
    return (
        sev,
        unreviewed_first,
        metric_risk,
        item.file_path,
        item.shape_index,
    )


# ---------------------------------------------------------------------------
# JSON / TSV parsing helpers
# ---------------------------------------------------------------------------


def _item_from_report_issue(
    raw: Any, run_id: str
) -> Optional[QualityReviewItem]:
    if not isinstance(raw, dict):
        return None
    issue_id = str(raw.get("issue_id", "") or "")
    if not issue_id:
        return None
    primary = raw.get("primary_metric") or {}
    if not isinstance(primary, dict):
        primary = {}
    pm_value = primary.get("value", 0.0)
    try:
        pm_value = float(pm_value)
    except (TypeError, ValueError):
        pm_value = 0.0
    gid = raw.get("group_id")
    if gid is None or (isinstance(gid, bool)):
        gid = None
    try:
        shape_index = int(raw.get("shape_index", -1))
    except (TypeError, ValueError):
        shape_index = -1
    return QualityReviewItem(
        issue_id=issue_id,
        run_id=str(raw.get("run_id", run_id) or run_id),
        file_path=str(raw.get("file_path", "") or ""),
        shape_index=shape_index,
        shape_id=str(raw.get("shape_id", "") or ""),
        rule_id=str(raw.get("rule_id", "") or ""),
        rule_name=str(raw.get("rule_name", "") or ""),
        severity=str(raw.get("severity", "warning") or "warning"),
        message=str(raw.get("message", "") or ""),
        label=str(raw.get("label", "") or ""),
        group_id=gid,
        primary_metric_name=str(primary.get("name", "") or ""),
        primary_metric_value=pm_value,
        primary_metric_direction=str(
            primary.get("direction", "") or "higher_is_worse"
        ),
        original_severity=str(raw.get("severity", "") or ""),
    )


def _item_from_review_row(row: Dict[str, str]) -> Optional[QualityReviewItem]:
    issue_id = (row.get("issue_id") or "").strip()
    if not issue_id:
        return None
    try:
        shape_index = int((row.get("shape_index") or "-1").strip())
    except ValueError:
        shape_index = -1
    gid_raw = (row.get("group_id") or "").strip()
    gid: Optional[int]
    if gid_raw == "":
        gid = None
    else:
        try:
            gid = int(gid_raw)
        except ValueError:
            gid = None
    return QualityReviewItem(
        issue_id=issue_id,
        run_id=(row.get("run_id") or "").strip(),
        file_path=(row.get("file_path") or "").strip(),
        shape_index=shape_index,
        shape_id=(row.get("shape_id") or "").strip(),
        rule_id="",
        rule_name=(row.get("rule_name") or "").strip(),
        severity=(row.get("severity") or "warning").strip() or "warning",
        message=(row.get("message") or "").strip(),
        label=(row.get("label") or "").strip(),
        group_id=gid,
        primary_metric_name="",
        primary_metric_value=0.0,
        original_severity=(row.get("severity") or "").strip(),
    )


def _iter_tsv(path: str):
    import csv as _csv

    with open(path, "r", encoding="utf-8") as fh:
        reader = _csv.DictReader(fh, delimiter="\t")
        if reader.fieldnames is None:
            return
        for row in reader:
            yield row


def _load_json(path: str) -> Dict[str, Any]:
    if not osp.isfile(path):
        raise FileNotFoundError(f"report file not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("report.json root must be an object")
    return data


def _write_tsv(
    path: str, fieldnames: List[str], rows: List[Dict[str, Any]]
) -> None:
    import csv as _csv

    parent = osp.dirname(osp.abspath(path))
    if parent:
        import os

        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = _csv.DictWriter(
            fh,
            fieldnames=fieldnames,
            delimiter="\t",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def _empty_feedback_row() -> Dict[str, Any]:
    return {col: "" for col in _FEEDBACK_TEMPLATE_COLUMNS}


def _merge_evidence(
    existing: QualityReviewItem, new: QualityReviewItem
) -> None:
    """Update mutable evidence fields on ``existing`` from a re-scan,
    leaving review state (decision/status/note/...) untouched."""
    existing.message = new.message
    existing.severity = new.severity
    existing.shape_id = new.shape_id or existing.shape_id
    existing.label = new.label
    existing.group_id = new.group_id
    existing.primary_metric_name = new.primary_metric_name
    existing.primary_metric_value = new.primary_metric_value
    existing.primary_metric_direction = new.primary_metric_direction
    existing.run_id = new.run_id or existing.run_id


def _same_file_path(left: str, right: str) -> bool:
    """Return True when two paths refer to the same annotation target."""
    left_norm = osp.normcase(osp.normpath(left or ""))
    right_norm = osp.normcase(osp.normpath(right or ""))
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    left_stem = osp.splitext(osp.basename(left_norm))[0]
    right_stem = osp.splitext(osp.basename(right_norm))[0]
    return bool(left_stem and left_stem == right_stem)


def _metric_risk_score(item: QualityReviewItem) -> float:
    """Normalize primary metric values so larger scores are riskier."""
    value = float(item.primary_metric_value or 0.0)
    direction = item.primary_metric_direction or "higher_is_worse"
    if direction == "lower_is_worse":
        return -value
    if direction in ("higher_abs_is_worse", "two_sided"):
        return abs(value)
    return value


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


# Keep queue output byte-compatible with the shared feedback template.
_FEEDBACK_TEMPLATE_COLUMNS = list(FEEDBACK_TEMPLATE_COLUMNS)
