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
from typing import Iterable

from .analysis import AnalysisFilter, ReadQuality, calculate_statistics
from .catalog import sanitize_payload, validate_payload
from .schema import EventEnvelope

ANALYSIS_BUNDLE_VERSION = "1.0"
_CSV_FIELDS = {
    "action_counts.csv": ["action", "result", "count"],
    "action_durations.csv": [
        "action",
        "sample_count",
        "total_ms",
        "mean_ms",
        "median_ms",
        "p75_ms",
        "p95_ms",
    ],
    "transitions.csv": ["from_action", "to_action", "count"],
    "common_sequences.csv": ["sequence", "length", "count"],
    "object_episodes.csv": [
        "project_id",
        "image_id",
        "shape_id",
        "object_episode_id",
        "event_count",
        "duration",
        "actions",
    ],
    "feature_comparisons.csv": [
        "feature_key",
        "state_dimension",
        "group",
        "sample_count",
        "difference",
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
            writer.writerow(normalized)


def _representative_traces(
    events: Iterable[EventEnvelope], limit: int, max_bytes: int
) -> list[dict[str, object]]:
    """Select categorized, bounded and deterministic object traces."""
    grouped: dict[str, list[EventEnvelope]] = {}
    for event in events:
        if event.object_episode_id:
            grouped.setdefault(event.object_episode_id, []).append(event)
    candidates = []
    for episode_id, episode_events in grouped.items():
        ordered = sorted(
            episode_events,
            key=lambda event: (
                event.occurred_at_utc,
                event.monotonic_ms,
                event.event_id,
            ),
        )
        duration = sum(event.duration_ms or 0 for event in ordered)
        actions = tuple(_action_name(event) for event in ordered)
        candidates.append(
            {
                "duration": duration,
                "count": len(ordered),
                "episode_id": episode_id,
                "events": ordered,
                "actions": actions,
                "failed": any(
                    event.result in {"failed", "cancelled", "incomplete"}
                    for event in ordered
                ),
                "loop": any(
                    index >= 2 and actions[index] == actions[index - 2]
                    for index in range(len(actions))
                ),
            }
        )
    if not candidates or limit <= 0 or max_bytes <= 0:
        return []
    durations = sorted(item["duration"] for item in candidates)
    median = durations[(len(durations) - 1) // 2]
    p75 = durations[min(len(durations) - 1, int(len(durations) * 0.75))]
    signature_counts = {}
    for item in candidates:
        signature_counts[item["actions"]] = (
            signature_counts.get(item["actions"], 0) + 1
        )
    common_signature = sorted(
        signature_counts.items(), key=lambda item: (-item[1], item[0])
    )[0][0]
    selectors = [
        (
            "common",
            lambda item: item["actions"] == common_signature,
            lambda item: (-item["count"], item["episode_id"]),
        ),
        (
            "median",
            lambda item: True,
            lambda item: (abs(item["duration"] - median), item["episode_id"]),
        ),
        (
            "p75",
            lambda item: True,
            lambda item: (abs(item["duration"] - p75), item["episode_id"]),
        ),
        (
            "longest",
            lambda item: True,
            lambda item: (
                -item["duration"],
                -item["count"],
                item["episode_id"],
            ),
        ),
        (
            "failure_or_loop",
            lambda item: item["failed"] or item["loop"],
            lambda item: (-item["duration"], item["episode_id"]),
        ),
    ]
    selected = []
    used = set()
    per_category = max(1, limit // len(selectors))
    for reason, predicate, sort_key in selectors:
        options = sorted(
            [item for item in candidates if predicate(item)], key=sort_key
        )
        for item in options[:per_category]:
            if item["episode_id"] in used:
                continue
            trace = {
                "selection_reason": reason,
                "episode_id": item["episode_id"],
                "event_count": item["count"],
                "duration_ms": item["duration"],
                "events": [event.to_dict() for event in item["events"]],
            }
            encoded = json.dumps(trace, ensure_ascii=False, sort_keys=True)
            current_bytes = sum(
                len(json.dumps(row, ensure_ascii=False, sort_keys=True)) + 1
                for row in selected
            )
            if current_bytes + len(encoded) + 1 > max_bytes:
                return selected
            selected.append(trace)
            used.add(item["episode_id"])
            if len(selected) >= limit:
                return selected
    return selected


def _action_name(event: EventEnvelope) -> str:
    """Return the action name used for trace signatures."""
    if event.payload and event.payload.get("action"):
        return str(event.payload["action"])
    return event.event_type


def export_analysis_bundle(
    output_dir: str | Path,
    events: Iterable[EventEnvelope],
    *,
    quality: ReadQuality | None = None,
    event_filter: AnalysisFilter | None = None,
    representative_trace_limit: int = 24,
    max_bundle_bytes: int = 5_242_880,
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
    for event in events:
        payload, removed = sanitize_payload(event.event_type, event.payload)
        validate_payload(event.event_type, payload)
        selected_events.append(replace(event, payload=payload or None))
        privacy_fields_removed += removed
    statistics = calculate_statistics(selected_events)
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
        _write_json(
            temporary / "summary.json",
            {
                "analysis_bundle_version": ANALYSIS_BUNDLE_VERSION,
                "event_count": len(selected_events),
                "statistics": statistics,
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
        for filename, rows in rows_by_file.items():
            _write_csv(temporary / filename, _CSV_FIELDS[filename], rows)
        traces = _representative_traces(
            selected_events, representative_trace_limit, max_bundle_bytes
        )
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
            "analysis_bundle_version": ANALYSIS_BUNDLE_VERSION,
            "generated_at_utc": datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "requested_filter": event_filter.to_dict(),
            "input_event_schema_versions": quality.metadata.get(
                "input_schema_versions", [1]
            ),
            "quality": quality.to_dict(),
            "privacy_fields_removed": privacy_fields_removed,
            "representative_trace_limit": representative_trace_limit,
            "representative_trace_count": len(traces),
            "max_bundle_bytes": max_bundle_bytes,
            "files": file_hashes,
        }
        _write_json(temporary / "manifest.json", manifest)
        os.replace(temporary, target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return target
