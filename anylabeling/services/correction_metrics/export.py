"""Write one CSV from an immutable report snapshot, preserving any old file."""

from __future__ import annotations

import csv
import json
import os
import tempfile
import unicodedata
from pathlib import Path

from .reporting import CLASS_COLUMNS, IMAGE_COLUMNS, class_details, work_seconds


class ExportCancelled(Exception):
    pass


EXTRA_TIME_FIELDS = (
    "working_seconds", "raw_working_seconds", "paused_seconds", "inactive_seconds",
    "blocking_wait_seconds", "not_ready_seconds", "idle_pending_seconds",
    "idle_excluded_seconds",
)
CSV_COLUMNS = {
    "images": IMAGE_COLUMNS + EXTRA_TIME_FIELDS,
    "classes": CLASS_COLUMNS,
    "dictionary": ("field", "meaning"),
}
DEFINITIONS = {
    "schema_version": "Report schema version.",
    "dataset_id": "Dataset identity including image and annotation roots.",
    "image_path": "Image within the dataset.",
    "label_path": "Annotation output for this round.",
    "image_digest": "Fingerprint of the version of image content.",
    "round_id": "One immutable baseline and the work performed against it.",
    "session_ids": "Anonymous sessions contributing to this single round row.",
    "phase": "Correction or separately started review.",
    "origin": "unknown-existing, replacement or additive baseline.",
    "run_id": "Prediction run that supplied this baseline, when known.",
    "model": "Recorded model name; unknown sources stay unknown.",
    "model_version": "Recorded weights version; a display name is insufficient.",
    "config_digest": "Fingerprint of the relevant prediction configuration.",
    "prompt": "Recorded grounding prompt, when available.",
    "thresholds": "Recorded prediction thresholds.",
    "category_version": "Version of the class vocabulary used for comparison.",
    "revision": "Last confirmed saved annotation revision; draft excluded.",
    "current": "Whether the round represents the current result.",
    "completed": "Explicit processing completion for the saved revision.",
    "quality": "Quality assessment status, independent of processing completion.",
    "comparable": "Whether complete comparison is supported for this round.",
    "issues": "Scope, provenance, timing or recording limitations.",
    "baseline_count": "Number of ordinary rectangles in the starting set B.",
    "ai_count": "Known members of B supplied by this prediction run.",
    "final_count": "Number of ordinary rectangles in the saved set F.",
    "unsupported_count": "Shapes outside the ordinary rectangle scope.",
    "added": "Identities in F but absent from B.",
    "deleted": "Identities in B but absent from F.",
    "geometry_changed": "Identities present in B and F with changed bounds.",
    "class_changed": "Comparable identities present in B and F with changed class.",
    "modified_original": "Unique union of deleted, geometry_changed and class_changed.",
    "unchanged": "Original surviving rectangles with unchanged geometry and class.",
    "modified_rate": "modified_original / baseline_count (fraction).",
    "unchanged_rate": "unchanged / baseline_count (fraction); retention is not accuracy.",
    "transactions": "Number of completed content-edit transactions.",
    "touches": "Sum of affected object counts across transactions.",
    "unique_objects": "Distinct object identities touched across transactions.",
    "undo_count": "Number of observed undo actions.",
    "redo_count": "Number of observed redo actions.",
    "operation_counts": "Counts by recorded operation type.",
    "time": "Recorded timing counters in seconds, including all contributing sessions.",
    "inference_seconds": "Elapsed model runtime; may overlap foreground work.",
    "working_seconds": "Foreground processing seconds after explicitly confirmed exclusions.",
    "raw_working_seconds": "Raw application foreground processing seconds.",
    "paused_seconds": "Explicitly paused seconds.",
    "inactive_seconds": "Application inactive or system suspended seconds, when known.",
    "blocking_wait_seconds": "Seconds waiting while the image could not be edited.",
    "not_ready_seconds": "Seconds before an image became interactive.",
    "idle_pending_seconds": "Time awaiting an idle decision; still included in working time.",
    "idle_excluded_seconds": "Foreground seconds explicitly excluded by the operator.",
    "kind": "Class detail type: initial, final, added, deleted, geometry or class_changed.",
    "initial_class": "Original class name; used for deletions and geometry changes.",
    "final_class": "Final class name; used for additions and change direction.",
    "count": "Object count for this class detail in this round.",
    "denominator": "Applicable denominator for the specified class and scope.",
}


def safe_cell(value):
    if value is None:
        return "N/A"
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (dict, tuple, list)):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    value = str(value)
    candidate = unicodedata.normalize("NFKC", value.lstrip())
    if candidate.startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def _image_record(row):
    times = row.get("time") or {}
    return {
        **row,
        "working_seconds": work_seconds(row),
        "raw_working_seconds": times.get("working"),
        **{key + "_seconds": times.get(key) for key in (
            "paused", "inactive", "blocking_wait", "not_ready",
            "idle_pending", "idle_excluded",
        )},
    }


def export_csv(path, rows, kind="images", *, cancelled=None, progress=None):
    """Publish only after a full write. The caller owns the frozen rows."""
    columns = CSV_COLUMNS[kind]
    destination = Path(path)
    records = tuple(DEFINITIONS.items()) if kind == "dictionary" else rows
    total = len(records)
    temporary = None

    def check():
        if cancelled is not None and cancelled():
            raise ExportCancelled()

    try:
        check()
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8-sig", newline="", delete=False,
            dir=destination.parent, prefix=".correction-export-", suffix=".tmp",
        ) as stream:
            temporary = Path(stream.name)
            writer = csv.writer(stream)
            writer.writerow(columns)
            for index, item in enumerate(records, 1):
                check()
                if kind == "dictionary":
                    writer.writerow([safe_cell(v) for v in item])
                else:
                    details = class_details(item) if kind == "classes" else (_image_record(item),)
                    for detail in details:
                        check()
                        writer.writerow([safe_cell(detail.get(key)) for key in columns])
                if progress and (index % 128 == 0 or index == total):
                    progress(index, total)
            if kind == "dictionary":
                writer.writerows((
                    ("N/A", "Unknown, inapplicable or zero-denominator value; never substitute zero."),
                    ("CSV text", "A leading apostrophe escapes untrusted formula-like text for spreadsheet software."),
                    ("Cost", "Session totals belong to one round. Sequential runs on the same image are not an independent comparison."),
                ))
            stream.flush()
            os.fsync(stream.fileno())
        check()
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
