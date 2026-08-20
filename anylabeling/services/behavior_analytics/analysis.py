"""Deterministic event reading and first-pass behavior statistics."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

from .catalog import validate_payload
from .schema import (
    EVENT_SCHEMA_VERSION,
    EventEnvelope,
    EventValidationError,
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
    invalid_count: int = 0
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
            "invalid_count": self.invalid_count,
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


def read_events(
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
    events: list[EventEnvelope] = []
    for source in sources:
        for path in iter_event_files(source):
            try:
                stream = path.open("r", encoding="utf-8")
            except OSError as exc:
                quality.invalid_count += 1
                quality.reason_counts["file_error"] += 1
                quality.reason_counts[str(exc)] += 1
                continue
            with stream:
                for line in stream:
                    if not line.strip():
                        continue
                    quality.read_count += 1
                    try:
                        data = json.loads(line)
                        if (
                            isinstance(data, dict)
                            and data.get("schema_version")
                            != EVENT_SCHEMA_VERSION
                        ):
                            quality.unknown_schema_count += 1
                            quality.reason_counts["schema_version"] += 1
                            continue
                        event = EventEnvelope.from_mapping(data)
                        validate_payload(event.event_type, event.payload)
                    except json.JSONDecodeError:
                        quality.corrupt_count += 1
                        quality.reason_counts["json_parse"] += 1
                        continue
                    except EventValidationError as exc:
                        text = str(exc)
                        if "schema_version" in text:
                            quality.unknown_schema_count += 1
                            quality.reason_counts["schema_version"] += 1
                        else:
                            quality.invalid_count += 1
                            quality.reason_counts["event_contract"] += 1
                        continue
                    except (TypeError, ValueError):
                        quality.invalid_count += 1
                        quality.reason_counts["payload_contract"] += 1
                        continue
                    if not event_filter.matches(event):
                        quality.filtered_count += 1
                        continue
                    quality.accepted_count += 1
                    events.append(event)
    events.sort(
        key=lambda event: (
            event.occurred_at_utc,
            event.monotonic_ms,
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
    }
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
            "p95_ms": None,
        }
    return {
        "sample_count": len(values),
        "total_ms": sum(values),
        "mean_ms": sum(values) / len(values),
        "median_ms": _percentile(values, 50),
        "p75_ms": _percentile(values, 75),
        "p95_ms": _percentile(values, 95),
    }


def _context_key(event: EventEnvelope) -> tuple[str, str, str]:
    """Return a sequence boundary key."""
    return (
        event.project_session_id,
        event.image_id or "",
        event.object_episode_id or "",
    )


def calculate_statistics(events: Iterable[EventEnvelope]) -> dict[str, object]:
    """Calculate deterministic counts, durations, transitions and episodes."""
    ordered = sorted(
        events,
        key=lambda event: (
            event.occurred_at_utc,
            event.monotonic_ms,
            event.event_id,
        ),
    )
    action_counts: Counter[tuple[str, str]] = Counter()
    durations: defaultdict[str, list[int]] = defaultdict(list)
    contexts: defaultdict[tuple[str, str, str], list[str]] = defaultdict(list)
    transitions: Counter[tuple[str, str]] = Counter()
    episode_rows: defaultdict[tuple[str, str, str], dict[str, object]] = (
        defaultdict(dict)
    )
    for event in ordered:
        action = _action_name(event)
        action_counts[(action, event.result)] += 1
        if event.duration_ms is not None:
            durations[action].append(event.duration_ms)
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
        context = _context_key(event)
        previous = contexts[context][-1] if contexts[context] else None
        if event.image_id and previous:
            transitions[(previous, action)] += 1
        if event.image_id:
            contexts[context].append(action)

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
    return {
        "event_count": len(ordered),
        "action_counts": action_count_rows,
        "action_durations": duration_rows,
        "transitions": transition_rows,
        "common_sequences": sequence_rows,
        "object_episodes": object_rows,
    }
