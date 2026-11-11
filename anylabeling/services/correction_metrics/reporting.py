"""Read-only projections shared by the report dialog and CSV exporter."""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median

from .core import DISCLOSURE_ISSUES


IMAGE_COLUMNS = (
    "schema_version", "dataset_id", "image_path", "label_path", "image_digest",
    "round_id", "session_ids", "phase", "origin", "run_id", "model",
    "model_version", "config_digest", "prompt", "thresholds", "category_version",
    "revision", "current", "completed", "quality", "comparable", "issues",
    "baseline_count", "ai_count", "final_count", "unsupported_count",
    "added", "deleted", "geometry_changed", "class_changed", "modified_original",
    "unchanged", "modified_rate", "unchanged_rate", "transactions", "touches",
    "unique_objects", "undo_count", "redo_count", "completion", "operation_counts",
    "time", "inference_seconds",
)
CLASS_COLUMNS = (
    "dataset_id", "image_path", "round_id", "run_id", "revision", "model",
    "model_version", "category_version", "phase", "origin", "current", "completed",
    "comparable", "issues", "kind", "initial_class", "final_class",
    "count", "denominator",
)
NET_COLUMNS = (
    "final_count", "added", "deleted", "geometry_changed", "class_changed",
    "modified_original", "unchanged", "modified_rate", "unchanged_rate",
)
IMAGE_VIEW = (
    "image_path", "phase", "model", "model_version", "completed", "current",
    "baseline_count", "final_count", "added", "deleted", "geometry_changed",
    "class_changed", "transactions", "working_seconds", "quality", "issues",
)
CLASS_VIEW = (
    "category_version", "kind", "initial_class", "final_class", "count",
    "denominator", "rounds", "model", "model_version", "phase", "origin",
)
GROUP_VIEW = (
    "model", "model_version", "category_version", "density", "phase", "origin",
    "rounds", "images", "final_count", "working_seconds", "median_seconds",
    "seconds_per_100", "modified_original", "baseline_count", "modified_rate",
)
GROUP_KEYS = (
    "dataset_id", "phase", "origin", "model", "model_version", "config_digest",
    "category_version", "current",
)


def work_seconds(row):
    times = row.get("time") or {}
    adjusted = times.get("adjusted_working")
    return times.get("working") if adjusted is None else adjusted


def saved_row(raw):
    """Whitelist exportable fields. An unsaved draft has no final quantities."""
    row = {key: raw.get(key) for key in IMAGE_COLUMNS}
    row["quality"] = raw.get("quality") or "not-assessed"
    row["classes"] = raw.get("classes") or ()
    if not row["revision"]:
        row.update(dict.fromkeys(NET_COLUMNS))
        row.update(completed=False, comparable=False, classes=())
    row["working_seconds"] = work_seconds(row)
    return row


def class_details(row):
    for change in row.get("classes") or ():
        yield {
            key: change.get(key) if key in (
                "kind", "initial_class", "final_class", "count", "denominator"
            ) else row.get(key)
            for key in CLASS_COLUMNS
        }


def exclusion_reasons(row):
    reasons = set()
    if not row.get("revision"):
        reasons.add("unsaved")
    if not row.get("completed"):
        reasons.add("unfinished")
    if not row.get("comparable"):
        blocking = [issue for issue in (row.get("issues") or ())
                    if issue not in DISCLOSURE_ISSUES]
        reasons.update(blocking or ["incomplete"])
    return sorted(reasons)


def filter_rounds(rows, phase="", version="", *, current_only=False):
    return tuple(
        row for row in rows
        if (not phase or row.get("phase") == phase)
        and (not version or row.get("model_version") == version)
        and (not current_only or row.get("current"))
    )


def outcome(rows):
    completed = set()
    excluded = Counter()
    comparable = 0
    for row in rows:
        if row.get("completed") and row.get("revision") and row.get("current"):
            completed.add((row["dataset_id"], row["image_path"], row["label_path"]))
        reasons = exclusion_reasons(row)
        if reasons:
            excluded.update(reasons)
        else:
            comparable += 1
    return len(completed), comparable, excluded


def _density(count):
    if count is None:
        return "N/A"
    if count == 0:
        return "0"
    if count <= 10:
        return "1–10"
    if count <= 30:
        return "11–30"
    return "31+"


def density_groups(rows):
    groups = defaultdict(list)
    for row in rows:
        if not exclusion_reasons(row):
            key = tuple(row.get(k) for k in GROUP_KEYS)
            groups[key + (_density(row.get("final_count")),)].append(row)
    result = []
    for key, group in groups.items():
        record = dict(zip(GROUP_KEYS + ("density",), key))
        record["rounds"] = len(group)
        record["images"] = len({(r["image_path"], r["label_path"]) for r in group})
        seconds = [work_seconds(r) for r in group]
        known_time = all(s is not None for s in seconds)
        record["working_seconds"] = sum(seconds) if known_time else None
        record["median_seconds"] = median(seconds) if known_time else None
        for field in ("baseline_count", "final_count", "modified_original"):
            values = [r.get(field) for r in group]
            record[field] = sum(values) if None not in values else None
        record["seconds_per_100"] = (
            100 * record["working_seconds"] / record["final_count"]
            if known_time and record["final_count"] else None
        )
        record["modified_rate"] = (
            record["modified_original"] / record["baseline_count"]
            if record["modified_original"] is not None and record["baseline_count"]
            else None
        )
        result.append(record)
    return result


def class_groups(rows):
    values = {}
    for row in rows:
        if exclusion_reasons(row):
            continue
        for item in class_details(row):
            fields = GROUP_KEYS + ("kind", "initial_class", "final_class")
            key = tuple(row.get(k) if k in GROUP_KEYS else item.get(k) for k in fields)
            record = values.setdefault(key, {**dict(zip(fields, key)),
                                             "count": 0, "denominator": 0,
                                             "rounds": 0})
            record["rounds"] += 1
            for field in ("count", "denominator"):
                value = item.get(field)
                if value is None or record[field] is None:
                    record[field] = None
                else:
                    record[field] += value
    return list(values.values())


def view_records(rows, mode, search="", sort_key=None, descending=False):
    if mode == "class":
        records, columns = class_groups(rows), CLASS_VIEW
    elif mode == "group":
        records, columns = density_groups(rows), GROUP_VIEW
    else:
        records, columns = rows, IMAGE_VIEW
    needle = search.strip().casefold()
    if needle:
        records = [
            r for r in records if any(
                needle in str(r.get(k) or "").casefold()
                for k in ("image_path", "initial_class", "final_class", "model",
                          "model_version", "round_id", "density")
            )
        ]
    if sort_key in columns:
        def sort_value(row):
            value = row.get(sort_key)
            if isinstance(value, (int, float)):
                return (0, value)
            return (1, str(value).casefold())
        known = [r for r in records if r.get(sort_key) is not None]
        unknown = [r for r in records if r.get(sort_key) is None]
        records = sorted(known, key=sort_value, reverse=descending) + unknown
    return columns, records
