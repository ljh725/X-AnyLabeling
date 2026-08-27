"""Fixed-format, privacy-filtered analysis bundle export."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping

from .analysis import AnalysisFilter, ReadQuality, calculate_statistics
from .catalog import sanitize_event, validate_payload
from .schema import EventEnvelope
from .statistics_v3 import compare_ranges
from .traces import (
    collect_trace_candidates,
    extract_trace_events,
    select_trace_candidates,
)
from .versions import (
    ANALYTICS_ALGORITHM_VERSION,
    BUNDLE_SCHEMA_VERSION,
    STATISTICAL_EXPORT_VERSION,
    OBJECT_WORKFLOW_EXPORT_VERSION,
    TIME_DECOMPOSITION_VERSION,
    SEQUENCE_RULE_VERSION,
    WORKFLOW_TIMELINE_VERSION,
)
from .workflow import (
    build_workflow_timeline,
    object_workflow_summary,
    project_bottlenecks,
    sequence_metrics as workflow_sequence_metrics,
)

ANALYSIS_BUNDLE_VERSION = BUNDLE_SCHEMA_VERSION
_CSV_FIELDS = {
    "action_counts.csv": [
        "action",
        "result",
        "count",
        "edit_target",
        "input_source",
        "shape_context",
        "result_rate",
        "duration_coverage",
    ],
    "action_durations.csv": [
        "action",
        "sample_count",
        "total_ms",
        "mean_ms",
        "median_ms",
        "p75_ms",
        "p90_ms",
        "p95_ms",
        "edit_target",
        "input_source",
        "shape_context",
        "result",
        "duration_coverage",
    ],
    "transitions.csv": ["from_action", "to_action", "count"],
    "common_sequences.csv": [
        "sequence",
        "length",
        "count",
        "object_count",
        "episode_count",
        "active_ms",
    ],
    "object_episodes.csv": [
        "project_id",
        "image_id",
        "shape_id",
        "object_episode_id",
        "event_count",
        "duration",
        "actions",
        "started_monotonic_ms",
        "ended_monotonic_ms",
        "wall_ms",
        "focused_ms",
        "active_ms",
        "action_duration_ms",
        "action_count",
        "changed",
        "saved_after_change",
        "completion",
        "end_reason",
        "terminal_integrity",
    ],
    "feature_comparisons.csv": [
        "feature_key",
        "state_dimension",
        "group",
        "sample_count",
        "difference",
        "comparison_unavailable",
        "minimum_samples",
        "observational",
        "groups",
    ],
    "image_metrics.csv": [
        "row_type",
        "image_id",
        "image_visit_count",
        "object_count",
        "created_count",
        "edited_count",
        "deleted_count",
        "rework_object_count",
        "active_ms",
        "objects_per_active_hour",
    ],
    "rework_metrics.csv": [
        "metric",
        "rule_version",
        "time_window",
        "numerator",
        "denominator",
        "rate",
        "not_applicable",
        "rework_active_ms",
    ],
    "action_metrics.csv": [
        "action",
        "edit_target",
        "input_source",
        "result",
        "shape_context",
        "count",
        "result_rate",
        "duration_coverage",
        "sample_count",
        "total_ms",
        "mean_ms",
        "median_ms",
        "p75_ms",
        "p90_ms",
        "p95_ms",
    ],
    "workflow_stage_metrics.csv": [
        "workflow_stage",
        "workflow_stage_version",
        "count",
        "object_coverage",
        "success_count",
        "result_rate",
        "duration_coverage",
        "sample_count",
        "total_ms",
        "mean_ms",
        "median_ms",
        "p75_ms",
        "p95_ms",
        "percentile_rule_version",
    ],
    "time_contribution.csv": [
        "action",
        "workflow_stage",
        "count",
        "total_ms",
        "time_share",
        "cumulative_time_share",
        "percentile_rule_version",
    ],
    "episode_metrics.csv": [
        "row_type",
        "object_episode_id",
        "project_session_id",
        "image_id",
        "shape_id",
        "event_count",
        "active_ms",
        "action_duration_ms",
        "changed",
        "saved_after_change",
        "end_reason",
        "terminal_integrity",
    ],
    "object_metrics.csv": [
        "row_type",
        "project_id",
        "image_id",
        "shape_id",
        "episode_count",
        "edit_count",
        "return_count",
        "active_ms",
        "rework_count",
    ],
    "range_comparison.csv": [
        "dimension",
        "baseline",
        "comparison",
        "comparison_unavailable",
        "absolute_difference_ms",
        "relative_change",
        "observational",
        "algorithm_version",
        "workflow_stage_version",
        "percentile_rule_version",
    ],
    "object_workflow_summary.csv": [
        "project_id",
        "image_id",
        "shape_id",
        "object_episode_id",
        "workflow_type",
        "creation_mode",
        "shape_type",
        "size_bucket",
        "started_ms",
        "ended_ms",
        "wall_ms",
        "focused_ms",
        "active_ms",
        "action_union_ms",
        "action_count",
        "action_duration_ms",
        "zoom_count",
        "zoom_start",
        "zoom_end",
        "stage_times_ms",
        "rework_ms",
        "save_count",
        "integrity",
        "exclusion_reason",
        "conservation_ok",
    ],
    "project_bottlenecks.csv": [
        "ranking",
        "stage",
        "action",
        "total_ms",
        "share",
        "cumulative_share",
        "count",
        "object_coverage",
        "median_ms",
        "p75_ms",
        "p90_ms",
        "p95_ms",
        "rework_ms",
        "duration_coverage",
        "project_active_ms",
        "algorithm_version",
    ],
}


def _json_default(value):
    """Serialize values not directly supported by JSON."""
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"unsupported JSON value {type(value).__name__}")


def _write_json(path: Path, payload: object) -> None:
    """Write deterministic UTF-8 JSON."""
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=_json_default,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, object]]) -> int:
    """Write deterministic one-record-per-line JSON and return row count."""
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            count += 1
    return count


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    """Write a deterministic UTF-8 CSV table."""
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=fieldnames, extrasaction="ignore"
        )
        writer.writeheader()
        for row in rows:
            normalized = dict(row)
            if isinstance(normalized.get("sequence"), list):
                normalized["sequence"] = " -> ".join(
                    str(item) for item in normalized["sequence"]
                )
            if isinstance(normalized.get("duration"), dict):
                normalized["duration"] = json.dumps(
                    normalized["duration"], sort_keys=True
                )
            if isinstance(normalized.get("actions"), dict):
                normalized["actions"] = json.dumps(
                    normalized["actions"], sort_keys=True
                )
            for key, value in list(normalized.items()):
                if isinstance(value, (dict, list)):
                    normalized[key] = json.dumps(value, sort_keys=True)
            writer.writerow(normalized)


def _representative_traces(
    events: Iterable[EventEnvelope], limit: int, max_bytes: int
) -> list[dict[str, object]]:
    """Select traces in a summary pass and extract them in a second pass."""
    if limit <= 0 or max_bytes <= 0:
        return []
    events = list(events)
    candidates = collect_trace_candidates(events)
    selected = select_trace_candidates(candidates, limit=limit)
    return extract_trace_events(
        events,
        selected,
        max_events=256,
        max_bytes=max_bytes,
    )


def _action_name(event: EventEnvelope) -> str:
    """Return the action name used for trace signatures."""
    if event.payload and event.payload.get("action"):
        return str(event.payload["action"])
    return event.event_type


def _bound_rows(
    rows: Iterable[dict], *, row_limit: int, byte_limit: int
) -> tuple[list[dict], int]:
    """Select deterministic compact rows under count and byte limits."""
    ordered = sorted(
        (dict(row) for row in rows),
        key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True),
    )
    selected: list[dict] = []
    used = 0
    for row in ordered:
        if len(selected) >= max(0, row_limit):
            break
        encoded = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if used + len(encoded.encode("utf-8")) + 1 > max(0, byte_limit):
            break
        selected.append(row)
        used += len(encoded.encode("utf-8")) + 1
    return selected, max(0, len(ordered) - len(selected))


def _other_row(
    fieldnames: list[str], *, omitted: int, total: int
) -> dict[str, object]:
    """Return an explicit, schema-safe aggregate for omitted entities."""
    row = {field: None for field in fieldnames}
    row["row_type"] = "other"
    if "image_id" in row:
        row["image_id"] = "other"
    if "object_episode_id" in row:
        row["object_episode_id"] = "other"
    if "shape_id" in row:
        row["shape_id"] = "other"
    if "count" in row:
        row["count"] = omitted
    if "event_count" in row:
        row["event_count"] = omitted
    if "episode_count" in row:
        row["episode_count"] = omitted
    row["omitted_rows"] = omitted
    row["total_rows"] = total
    return row


def export_analysis_bundle(
    output_dir: str | Path,
    events: Iterable[EventEnvelope],
    *,
    quality: ReadQuality | None = None,
    event_filter: AnalysisFilter | None = None,
    representative_trace_limit: int = 24,
    max_bundle_bytes: int = 5_242_880,
    comparison_events: Iterable[EventEnvelope] | None = None,
    range_selection: object | None = None,
    compact_table_row_limit: int = 5000,
    compact_table_bytes_limit: int = 1_048_576,
    cancel_check: Callable[[], bool] | None = None,
) -> Path:
    """Export a fixed analysis bundle using an atomic directory publish.

    Existing output directories are never overwritten. A failed write removes
    only its private temporary directory and leaves source events untouched.
    """
    target = Path(output_dir)
    if target.exists():
        raise FileExistsError(f"analysis bundle already exists: {target}")
    selected_events = []
    privacy_fields_removed = 0
    has_v2 = False
    has_v4 = False
    for event in events:
        if cancel_check and cancel_check():
            raise RuntimeError("behavior analytics export cancelled")
        sanitized, removed = sanitize_event(event)
        validate_payload(event.event_type, sanitized.payload)
        has_v2 = has_v2 or event.schema_version >= 2
        has_v4 = has_v4 or event.schema_version >= 4
        selected_events.append(sanitized)
        privacy_fields_removed += removed
    statistics = calculate_statistics(
        selected_events,
        cancel_check=cancel_check,
    )
    workflow_timeline = (
        build_workflow_timeline(selected_events) if has_v4 else None
    )
    quality = quality or ReadQuality(
        read_count=len(selected_events), accepted_count=len(selected_events)
    )
    event_filter = event_filter or AnalysisFilter()
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=".behavior-bundle-", dir=str(parent))
    )
    try:
        summary_statistics = {
            key: value
            for key, value in statistics.items()
            if key
            not in {
                "action_spans",
                "semantic_actions",
                "dimension_counts",
            }
        }
        _write_json(
            temporary / "summary.json",
            {
                "analysis_bundle_version": (
                    ANALYSIS_BUNDLE_VERSION if has_v2 else "1.0"
                ),
                "event_count": len(selected_events),
                "statistics": summary_statistics,
                "quality": quality.to_dict(),
                "privacy_fields_removed": privacy_fields_removed,
            },
        )
        rows_by_file = {
            "action_counts.csv": statistics["action_counts"],
            "action_durations.csv": statistics["action_durations"],
            "transitions.csv": statistics["transitions"],
            "common_sequences.csv": statistics["common_sequences"],
            "object_episodes.csv": statistics["object_episodes"],
            "feature_comparisons.csv": statistics["feature_comparisons"],
        }
        if has_v2:
            rows_by_file["action_counts.csv"] = statistics["action_metrics"]
            rows_by_file["action_durations.csv"] = statistics["action_metrics"]
            rows_by_file["common_sequences.csv"] = statistics[
                "sequence_metrics"
            ]
            rows_by_file["object_episodes.csv"] = statistics["episode_metrics"]
            rows_by_file["feature_comparisons.csv"] = statistics[
                "feature_comparisons_v2"
            ]
            rows_by_file["image_metrics.csv"] = statistics["image_metrics"]
            rows_by_file["rework_metrics.csv"] = statistics["rework_metrics"]
            rows_by_file["action_metrics.csv"] = statistics["action_metrics"]
            rows_by_file["workflow_stage_metrics.csv"] = statistics[
                "workflow_stage_metrics"
            ]
            rows_by_file["time_contribution.csv"] = statistics[
                "time_contribution"
            ]
            rows_by_file["episode_metrics.csv"] = statistics["episode_metrics"]
            rows_by_file["object_metrics.csv"] = statistics["object_metrics"]
            rows_by_file["range_comparison.csv"] = (
                compare_ranges(
                    selected_events,
                    list(comparison_events or []),
                )
                if comparison_events is not None
                else []
            )
            _write_json(
                temporary / "measurement_quality.json",
                statistics["measurement_quality"],
            )
            _write_json(
                temporary / "episode_cycle_metrics.json",
                statistics["episode_cycle_metrics"],
            )
        workflow_summary_rows = []
        workflow_bottleneck_rows = []
        workflow_sequence_rows = []
        if workflow_timeline is not None:
            workflow_summary_rows = object_workflow_summary(workflow_timeline)
            workflow_bottleneck_rows = project_bottlenecks(workflow_timeline)
            workflow_sequence_rows = workflow_sequence_metrics(
                workflow_timeline
            )
            _write_jsonl(
                temporary / "object_workflow_timeline.jsonl",
                (record.to_dict() for record in workflow_timeline.records),
            )
            _write_csv(
                temporary / "object_workflow_summary.csv",
                _CSV_FIELDS["object_workflow_summary.csv"],
                workflow_summary_rows,
            )
            _write_csv(
                temporary / "project_bottlenecks.csv",
                _CSV_FIELDS["project_bottlenecks.csv"],
                workflow_bottleneck_rows,
            )
            _write_json(
                temporary / "object_workflow_sequences.json",
                {
                    "sequence_rule_version": SEQUENCE_RULE_VERSION,
                    "rows": workflow_sequence_rows,
                },
            )
            _write_json(
                temporary / "object_workflow_quality.json",
                {
                    "timeline_schema_version": WORKFLOW_TIMELINE_VERSION,
                    "time_decomposition_version": TIME_DECOMPOSITION_VERSION,
                    "record_count": len(workflow_timeline.records),
                    "excluded_count": len(workflow_timeline.excluded),
                    "sequence_gap_count": workflow_timeline.sequence_gap_count,
                    "excluded": list(workflow_timeline.excluded),
                },
            )
        row_limits = {}
        for filename, rows in rows_by_file.items():
            if filename in {
                "object_episodes.csv",
                "episode_metrics.csv",
                "object_metrics.csv",
                "image_metrics.csv",
            }:
                rows = [{"row_type": "entity", **dict(row)} for row in rows]
            bounded, omitted = _bound_rows(
                rows,
                row_limit=compact_table_row_limit,
                byte_limit=compact_table_bytes_limit,
            )
            row_limits[filename] = {
                "total_rows": len(rows),
                "exported_rows": len(bounded)
                + int(
                    bool(
                        omitted
                        and filename
                        in {
                            "object_episodes.csv",
                            "episode_metrics.csv",
                            "object_metrics.csv",
                            "image_metrics.csv",
                        }
                    )
                ),
                "omitted_rows": omitted,
                "other_summary": {
                    "row_bucket": "other",
                    "omitted_rows": omitted,
                },
            }
            if omitted and filename in {
                "object_episodes.csv",
                "episode_metrics.csv",
                "object_metrics.csv",
                "image_metrics.csv",
            }:
                bounded.append(
                    _other_row(
                        _CSV_FIELDS[filename],
                        omitted=omitted,
                        total=len(rows),
                    )
                )
            _write_csv(temporary / filename, _CSV_FIELDS[filename], bounded)
        statistics["measurement_quality"]["metrics"][
            "manifest_completeness"
        ] = {
            "numerator": max(
                0,
                len(selected_events) - quality.manifest_error_count,
            ),
            "denominator": len(selected_events),
            "value": (
                1.0
                if not selected_events
                else max(
                    0,
                    len(selected_events) - quality.manifest_error_count,
                )
                / len(selected_events)
            ),
            "threshold": 1.0,
            "status": (
                "pass" if quality.manifest_error_count == 0 else "fail"
            ),
            "affected_event_types": ["manifest"],
            "exclusion_reason": (
                "manifest_error" if quality.manifest_error_count else None
            ),
        }
        statistics["measurement_quality"]["metrics"]["export_completeness"] = (
            dict(
                statistics["measurement_quality"]["metrics"][
                    "manifest_completeness"
                ]
            )
        )
        statistics["measurement_quality"]["metrics"]["export_completeness"][
            "affected_event_types"
        ] = ["manifest", "export_tables"]
        if has_v2:
            _write_json(
                temporary / "measurement_quality.json",
                statistics["measurement_quality"],
            )
            _write_json(
                temporary / "episode_cycle_metrics.json",
                statistics["episode_cycle_metrics"],
            )
        traces = _representative_traces(
            selected_events, representative_trace_limit, max_bundle_bytes
        )
        if cancel_check and cancel_check():
            raise RuntimeError("behavior analytics export cancelled")
        trace_path = temporary / "representative_traces.jsonl"
        with trace_path.open("w", encoding="utf-8") as stream:
            for trace in traces:
                stream.write(
                    json.dumps(trace, ensure_ascii=False, sort_keys=True)
                    + "\n"
                )
        file_hashes = {}
        for path in sorted(temporary.iterdir()):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            file_hashes[path.name] = {
                "bytes": path.stat().st_size,
                "sha256": digest,
            }
        manifest = {
            "analysis_bundle_version": (
                ANALYSIS_BUNDLE_VERSION if has_v2 else "1.0"
            ),
            "bundle_schema_version": (
                BUNDLE_SCHEMA_VERSION
                if has_v4
                else ("2.0" if has_v2 else "1.0")
            ),
            "statistical_export_version": (
                STATISTICAL_EXPORT_VERSION if has_v2 else None
            ),
            "generated_at_utc": datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "requested_filter": event_filter.to_dict(),
            "input_event_schema_versions": quality.metadata.get(
                "input_schema_versions", [1]
            ),
            "event_version_distribution": {
                str(version): sum(
                    event.schema_version == version
                    for event in selected_events
                )
                for version in sorted(
                    {event.schema_version for event in selected_events}
                )
            },
            "analytics_algorithm_version": (
                ANALYTICS_ALGORITHM_VERSION if has_v2 else "1.0"
            ),
            "context_schema_version": "1.0" if has_v2 else None,
            "rework_rule_version": "1.0" if has_v2 else None,
            "measurement_quality": statistics.get("measurement_quality"),
            "thresholds": {
                "duration_coverage_min": 0.95,
                "episode_closure_min": 0.99,
                "duplicate_rate_max": 0.05,
                "anomaly_episode_event_count": 100,
                "anomaly_episode_active_ms": 600000,
            },
            "quality": quality.to_dict(),
            "privacy_fields_removed": privacy_fields_removed,
            "representative_trace_limit": representative_trace_limit,
            "representative_trace_count": len(traces),
            "max_bundle_bytes": max_bundle_bytes,
            "range_selection": (
                range_selection.to_dict()
                if hasattr(range_selection, "to_dict")
                else range_selection
            ),
            "table_limits": {
                "row_limit": compact_table_row_limit,
                "bytes_limit": compact_table_bytes_limit,
                "tables": row_limits,
            },
            "files": file_hashes,
        }
        if workflow_timeline is not None:
            manifest["object_workflow"] = {
                "export_version": OBJECT_WORKFLOW_EXPORT_VERSION,
                "timeline_schema_version": WORKFLOW_TIMELINE_VERSION,
                "time_decomposition_version": TIME_DECOMPOSITION_VERSION,
                "sequence_rule_version": SEQUENCE_RULE_VERSION,
                "record_count": len(workflow_timeline.records),
                "excluded_count": len(workflow_timeline.excluded),
                "timeline_rows": len(workflow_timeline.records),
                "timeline_truncated": False,
                "timeline_shard_count": 1,
                "representative_traces_are_supplemental": True,
                "local_deterministic": True,
                "external_model_required": False,
                "files": {
                    name: file_hashes[name]
                    for name in (
                        "object_workflow_timeline.jsonl",
                        "object_workflow_summary.csv",
                        "project_bottlenecks.csv",
                        "object_workflow_sequences.json",
                        "object_workflow_quality.json",
                    )
                    if name in file_hashes
                },
            }
        _write_json(temporary / "manifest.json", manifest)
        os.replace(temporary, target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return target
