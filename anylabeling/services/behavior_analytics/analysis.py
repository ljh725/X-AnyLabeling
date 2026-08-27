"""Deterministic event reading and first-pass behavior statistics."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator

from .schema import EventEnvelope
from .pipeline import UtcRange, iter_event_stream
from .replay import replay_events
from .metrics import (
    action_metrics,
    episode_metrics,
    episode_cycle_metrics,
    feature_comparisons,
    image_metrics,
    measurement_quality,
    object_metrics,
    rework_metrics,
    semantic_actions,
    sequence_metrics,
    repetition_diagnostics,
)
from .statistics_v3 import (
    episode_time_decomposition,
    time_contribution_metrics,
    workflow_stage_metrics,
)


@dataclass(frozen=True)
class AnalysisFilter:
    """Inclusive filters for natural days, project sessions and UTC bounds."""

    local_dates: frozenset[str] = frozenset()
    project_session_ids: frozenset[str] = frozenset()
    start_utc: str | None = None
    end_utc: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return the requested range in manifest-friendly form."""
        return {
            "local_dates": sorted(self.local_dates),
            "project_session_ids": sorted(self.project_session_ids),
            "start_utc": self.start_utc,
            "end_utc": self.end_utc,
        }

    def matches(self, event: EventEnvelope) -> bool:
        """Return whether an event belongs to this filter."""
        if self.local_dates and event.local_date not in self.local_dates:
            return False
        if (
            self.project_session_ids
            and event.project_session_id not in self.project_session_ids
        ):
            return False
        if self.start_utc and event.occurred_at_utc < self.start_utc:
            return False
        if self.end_utc and event.occurred_at_utc > self.end_utc:
            return False
        return True


@dataclass
class ReadQuality:
    """Counts and reason buckets produced while reading source events."""

    read_count: int = 0
    accepted_count: int = 0
    filtered_count: int = 0
    corrupt_count: int = 0
    unknown_schema_count: int = 0
    incomplete_count: int = 0
    incomplete_span_count: int = 0
    missing_reference_count: int = 0
    unknown_field_count: int = 0
    invalid_count: int = 0
    parse_error_count: int = 0
    schema_error_count: int = 0
    required_field_error_count: int = 0
    reference_error_count: int = 0
    time_error_count: int = 0
    terminal_error_count: int = 0
    state_version_error_count: int = 0
    sequence_gap_count: int = 0
    manifest_error_count: int = 0
    duplicate_source_count: int = 0
    legacy_ordering_count: int = 0
    reason_counts: Counter[str] = field(default_factory=Counter)
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible quality summary."""
        return {
            "read_count": self.read_count,
            "accepted_count": self.accepted_count,
            "filtered_count": self.filtered_count,
            "corrupt_count": self.corrupt_count,
            "unknown_schema_count": self.unknown_schema_count,
            "incomplete_count": self.incomplete_count,
            "incomplete_span_count": self.incomplete_span_count,
            "missing_reference_count": self.missing_reference_count,
            "unknown_field_count": self.unknown_field_count,
            "invalid_count": self.invalid_count,
            "parse_error_count": self.parse_error_count,
            "schema_error_count": self.schema_error_count,
            "required_field_error_count": self.required_field_error_count,
            "reference_error_count": self.reference_error_count,
            "time_error_count": self.time_error_count,
            "terminal_error_count": self.terminal_error_count,
            "state_version_error_count": self.state_version_error_count,
            "sequence_gap_count": self.sequence_gap_count,
            "manifest_error_count": self.manifest_error_count,
            "duplicate_source_count": self.duplicate_source_count,
            "legacy_ordering_count": self.legacy_ordering_count,
            "reason_counts": dict(sorted(self.reason_counts.items())),
            "metadata": self.metadata,
        }


def iter_event_files(source: str | Path) -> Iterator[Path]:
    """Yield JSONL event files in deterministic path order."""
    path = Path(source)
    if path.is_file():
        yield path
        return
    if path.is_dir():
        yield from sorted(path.rglob("*.jsonl"))


def read_events(  # noqa: C901
    sources: Iterable[str | Path],
    *,
    event_filter: AnalysisFilter | None = None,
) -> tuple[list[EventEnvelope], ReadQuality]:
    """Read complete events while isolating invalid lines.

    The source files are never modified. Valid events are sorted by UTC time,
    monotonic time and event ID so repeated analysis has stable ordering.
    """
    event_filter = event_filter or AnalysisFilter()
    quality = ReadQuality()
    event_range = None
    if event_filter.start_utc or event_filter.end_utc:
        event_range = UtcRange(event_filter.start_utc, event_filter.end_utc)
    streamed_events = list(
        iter_event_stream(
            sources,
            event_range=event_range,
            project_session_ids=event_filter.project_session_ids,
            quality=quality,
        )
    )
    events = [
        event for event in streamed_events if event_filter.matches(event)
    ]
    local_filtered = len(streamed_events) - len(events)
    quality.filtered_count += local_filtered
    quality.accepted_count -= local_filtered
    events.sort(
        key=lambda event: (
            event.occurred_at_utc,
            event.monotonic_ms,
            event.sequence_no if event.sequence_no is not None else 2**63 - 1,
            event.event_id,
        )
    )
    quality.metadata = {
        "requested_filter": event_filter.to_dict(),
        "actual_start_utc": events[0].occurred_at_utc if events else None,
        "actual_end_utc": events[-1].occurred_at_utc if events else None,
        "actual_local_dates": sorted({event.local_date for event in events}),
        "timezone_offsets": sorted(
            {event.timezone_offset for event in events}
        ),
        "input_schema_versions": sorted(
            {event.schema_version for event in events}
        ),
        "legacy_low_granularity_count": sum(
            1
            for event in events
            if event.schema_version == 1 and event.event_type == "shape_edited"
        ),
    }
    project_sessions = {
        event.project_session_id
        for event in events
        if event.event_type == "project_session_started"
    }
    image_ids = {
        event.image_id
        for event in events
        if event.event_type == "image_visit_started" and event.image_id
    }
    episode_ids = {
        event.object_episode_id
        for event in events
        if event.event_type == "shape_selected" and event.object_episode_id
    }
    missing_references = 0
    for event in events:
        if event.project_session_id not in project_sessions:
            missing_references += 1
        if event.image_id and event.image_id not in image_ids:
            missing_references += 1
        if (
            event.object_episode_id
            and event.object_episode_id not in episode_ids
        ):
            missing_references += 1
    quality.missing_reference_count = missing_references
    quality.reference_error_count = missing_references
    quality.metadata["missing_reference_count"] = missing_references
    quality.incomplete_span_count = sum(
        1
        for event in events
        if event.event_type == "action_span" and event.result == "incomplete"
    )
    quality.metadata["incomplete_span_count"] = quality.incomplete_span_count
    quality.metadata["legacy_ordering_count"] = quality.legacy_ordering_count
    quality.metadata["sequence_gap_count"] = quality.sequence_gap_count
    quality.metadata["manifest_error_count"] = quality.manifest_error_count
    quality.metadata["duplicate_source_count"] = quality.duplicate_source_count
    return events, quality


def _action_name(event: EventEnvelope) -> str:
    """Return the stable action name used by aggregate tables."""
    if event.payload and event.payload.get("action"):
        return str(event.payload["action"])
    return event.event_type


def _percentile(values: list[int], percentile: float) -> float | None:
    """Return an interpolated deterministic percentile."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _duration_summary(values: list[int]) -> dict[str, float | int | None]:
    """Summarize durations without inventing values for empty samples."""
    if not values:
        return {
            "sample_count": 0,
            "total_ms": 0,
            "mean_ms": None,
            "median_ms": None,
            "p75_ms": None,
            "p90_ms": None,
            "p95_ms": None,
        }
    return {
        "sample_count": len(values),
        "total_ms": sum(values),
        "mean_ms": sum(values) / len(values),
        "median_ms": _percentile(values, 50),
        "p75_ms": _percentile(values, 75),
        "p90_ms": _percentile(values, 90),
        "p95_ms": _percentile(values, 95),
    }


def _context_key(event: EventEnvelope) -> tuple[str, str, str]:
    """Return a sequence boundary key."""
    return (
        event.project_session_id,
        event.image_id or "",
        event.object_episode_id or "",
    )


def calculate_statistics(
    events: Iterable[EventEnvelope],
    *,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, object]:
    """Calculate deterministic counts, durations, transitions and episodes."""
    materialized = []
    for event in events:
        if cancel_check and cancel_check():
            raise RuntimeError("behavior analytics export cancelled")
        materialized.append(event)
    ordered = sorted(
        materialized,
        key=lambda event: (
            event.occurred_at_utc,
            event.monotonic_ms,
            event.sequence_no if event.sequence_no is not None else 2**63 - 1,
            event.event_id,
        ),
    )
    action_counts: Counter[tuple[str, str]] = Counter()
    durations: defaultdict[str, list[int]] = defaultdict(list)
    contexts: defaultdict[tuple[str, str, str], list[str]] = defaultdict(list)
    transitions: Counter[tuple[str, str]] = Counter()
    dimension_rows: Counter[tuple[str, str, str, str, str, str]] = Counter()
    context_last_ms: dict[tuple[str, str, str], int] = {}
    composite_objects: defaultdict[tuple[str, str, str], dict[str, object]] = (
        defaultdict(dict)
    )
    episode_rows: defaultdict[tuple[str, str, str], dict[str, object]] = (
        defaultdict(dict)
    )
    for event in ordered:
        action = _action_name(event)
        action_counts[(action, event.result)] += 1
        dimension_rows[
            (
                action,
                event.input_source,
                event.result,
                event.project_id,
                event.local_date,
                event.image_id or "",
            )
        ] += 1
        if event.effective_duration_ms is not None:
            durations[action].append(event.effective_duration_ms)
        if event.image_id and event.object_episode_id:
            key = (event.project_id, event.image_id, event.shape_id or "")
            row = episode_rows.setdefault(
                (key[0], key[1], event.object_episode_id),
                {
                    "project_id": key[0],
                    "image_id": key[1],
                    "shape_id": key[2],
                    "object_episode_id": event.object_episode_id,
                    "event_count": 0,
                    "duration_ms": [],
                    "actions": Counter(),
                },
            )
            row["event_count"] += 1
            if event.duration_ms is not None:
                row["duration_ms"].append(event.duration_ms)
            row["actions"][action] += 1
            object_key = (key[0], key[1], key[2])
            object_row = composite_objects.setdefault(
                object_key,
                {
                    "project_id": key[0],
                    "image_id": key[1],
                    "shape_id": key[2],
                    "edit_count": 0,
                    "return_count": 0,
                    "duration_ms": [],
                    "actions": Counter(),
                    "episodes": set(),
                },
            )
            object_row["edit_count"] += 1
            object_row["episodes"].add(event.object_episode_id)
            object_row["actions"][action] += 1
            if event.duration_ms is not None:
                object_row["duration_ms"].append(event.duration_ms)
        context = _context_key(event)
        previous_ms = context_last_ms.get(context)
        if (
            previous_ms is not None
            and event.monotonic_ms - previous_ms > 120_000
        ):
            contexts[context].clear()
        previous = contexts[context][-1] if contexts[context] else None
        if event.image_id and previous:
            transitions[(previous, action)] += 1
        if event.image_id:
            contexts[context].append(action)
            context_last_ms[context] = event.monotonic_ms

    sequence_counts: Counter[tuple[str, ...]] = Counter()
    for actions in contexts.values():
        for size in range(3, 7):
            sequence_counts.update(
                tuple(actions[index : index + size])
                for index in range(len(actions) - size + 1)
            )
    action_count_rows = [
        {"action": action, "result": result, "count": count}
        for (action, result), count in sorted(action_counts.items())
    ]
    duration_rows = [
        {"action": action, **_duration_summary(values)}
        for action, values in sorted(durations.items())
    ]
    transition_rows = [
        {"from_action": before, "to_action": after, "count": count}
        for (before, after), count in sorted(transitions.items())
    ]
    sequence_rows = [
        {"sequence": list(sequence), "length": len(sequence), "count": count}
        for sequence, count in sorted(
            sequence_counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    object_rows = []
    for row in sorted(
        episode_rows.values(),
        key=lambda item: (
            item["project_id"],
            item["image_id"],
            item["shape_id"],
            item["object_episode_id"],
        ),
    ):
        durations_for_episode = row.pop("duration_ms")
        actions_for_episode = row.pop("actions")
        object_rows.append(
            {
                **row,
                "duration": _duration_summary(durations_for_episode),
                "actions": dict(sorted(actions_for_episode.items())),
            }
        )
    object_summary_rows = []
    for row in sorted(
        composite_objects.values(),
        key=lambda item: (
            item["project_id"],
            item["image_id"],
            item["shape_id"],
        ),
    ):
        durations_for_object = row.pop("duration_ms")
        actions_for_object = row.pop("actions")
        episodes_for_object = row.pop("episodes")
        object_summary_rows.append(
            {
                **row,
                "episode_count": len(episodes_for_object),
                "return_count": max(0, len(episodes_for_object) - 1),
                "duration": _duration_summary(durations_for_object),
                "actions": dict(sorted(actions_for_object.items())),
            }
        )
    replay = replay_events(ordered)
    legacy_feature_comparisons = _feature_comparisons(ordered, replay)
    dimension_count_rows = [
        {
            "action": action,
            "input_source": source,
            "result": result,
            "project_id": project_id,
            "local_date": local_date,
            "image_id": image_id,
            "count": count,
        }
        for (
            action,
            source,
            result,
            project_id,
            local_date,
            image_id,
        ), count in sorted(dimension_rows.items())
    ]
    loop_counts = _loop_counts(contexts)
    quality_metrics = measurement_quality(ordered)
    return {
        "event_count": len(ordered),
        "action_counts": action_count_rows,
        "action_durations": duration_rows,
        "transitions": transition_rows,
        "common_sequences": sequence_rows,
        "object_episodes": object_rows,
        "object_summaries": object_summary_rows,
        "dimension_counts": dimension_count_rows,
        "loop_counts": loop_counts,
        "time_metrics": replay["sessions"],
        "action_spans": replay["action_spans"],
        "feature_comparisons": legacy_feature_comparisons,
        "semantic_actions": [
            event.to_dict() for event in semantic_actions(ordered)
        ],
        "action_metrics": action_metrics(ordered),
        "episode_metrics": episode_metrics(ordered),
        "episode_cycle_metrics": episode_cycle_metrics(ordered),
        "object_metrics": object_metrics(ordered),
        "image_metrics": image_metrics(ordered),
        "rework_metrics": rework_metrics(ordered),
        "measurement_quality": quality_metrics,
        "feature_comparisons_v2": feature_comparisons(ordered),
        "sequence_metrics": sequence_metrics(ordered),
        "repetition_diagnostics": repetition_diagnostics(ordered),
        "workflow_stage_metrics": workflow_stage_metrics(ordered),
        "episode_time_decomposition": episode_time_decomposition(ordered),
        "time_contribution": time_contribution_metrics(ordered),
    }


def _loop_counts(
    contexts: defaultdict[tuple[str, str, str], list[str]],
) -> list[dict[str, object]]:
    """Count explicit repeats, reversals and cancellation outcomes."""
    counts: Counter[tuple[str, str]] = Counter()
    for actions in contexts.values():
        for index, action in enumerate(actions):
            if index and action == actions[index - 1]:
                counts[("repeat", action)] += 1
            if index >= 2 and action == actions[index - 2]:
                counts[("reversal", action)] += 1
            if action in {"undo", "cancel", "cancelled", "failed"}:
                counts[("outcome", action)] += 1
    return [
        {"loop_type": kind, "action": action, "count": count}
        for (kind, action), count in sorted(counts.items())
    ]


def _feature_comparisons(
    events: list[EventEnvelope], replay: dict[str, object]
) -> list[dict[str, object]]:
    """Compare action duration samples by observed feature state values."""
    state_map = {
        int(version): state
        for version, state in replay["feature_states"].items()
    }
    samples: defaultdict[tuple[str, str, str], list[int]] = defaultdict(list)
    for event in events:
        if event.duration_ms is None:
            continue
        state = state_map.get(event.feature_state_version)
        if not isinstance(state, dict):
            continue
        for key, value in state.items():
            if not isinstance(value, dict):
                continue
            for dimension in ("configured", "active", "used"):
                if dimension in value:
                    group = str(bool(value[dimension])).lower()
                    samples[(key, dimension, group)].append(event.duration_ms)
    rows = []
    for (key, dimension, group), values in sorted(samples.items()):
        opposite = samples.get(
            (key, dimension, "false" if group == "true" else "true"), []
        )
        current_mean = sum(values) / len(values)
        opposite_mean = sum(opposite) / len(opposite) if opposite else None
        rows.append(
            {
                "feature_key": key,
                "state_dimension": dimension,
                "group": group,
                "sample_count": len(values),
                "difference": (
                    current_mean - opposite_mean
                    if opposite_mean is not None
                    else None
                ),
            }
        )
    return rows
