"""Two-pass, bounded representative trace selection."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable

from .metrics import action_name
from .schema import EventEnvelope


@dataclass(frozen=True)
class TraceCandidate:
    """First-pass trace ranking facts without raw event retention."""

    episode_id: str
    event_count: int
    duration_ms: int
    actions: tuple[str, ...]
    failed: bool
    rework: bool
    unattributed_anomaly: bool
    measurement_anomaly: bool
    loop: bool

    def to_dict(self) -> dict[str, object]:
        """Return the serializable first-pass ranking summary."""
        return {
            "episode_id": self.episode_id,
            "event_count": self.event_count,
            "duration_ms": self.duration_ms,
            "actions": list(self.actions),
            "failed": self.failed,
            "rework": self.rework,
            "unattributed_anomaly": self.unattributed_anomaly,
            "measurement_anomaly": self.measurement_anomaly,
            "loop": self.loop,
        }


def collect_trace_candidates(
    events: Iterable[EventEnvelope],
) -> list[TraceCandidate]:
    """Collect deterministic candidate summaries in one streaming pass."""
    grouped: dict[str, dict[str, object]] = {}
    for event in events:
        episode_id = event.object_episode_id
        if not episode_id:
            continue
        row = grouped.setdefault(
            episode_id,
            {
                "count": 0,
                "duration": 0,
                "actions": [],
                "failed": False,
                "rework": False,
                "unattributed": True,
                "measurement": False,
            },
        )
        row["count"] += 1
        row["duration"] += event.duration_ms or 0
        name = action_name(event)
        row["actions"].append(name)
        row["failed"] |= event.result in {
            "failed",
            "cancelled",
            "incomplete",
        }
        row["rework"] |= name in {"undo", "redo"} or event.event_type in {
            "shape_restored",
            "shape_deleted",
        }
        row["unattributed"] &= event.event_type != "action_span"
        row["measurement"] |= (
            event.event_type == "action_span"
            and event.effective_duration_ms is None
        )
    candidates = []
    for episode_id, row in sorted(grouped.items()):
        actions = tuple(row["actions"])
        candidates.append(
            TraceCandidate(
                episode_id=episode_id,
                event_count=int(row["count"]),
                duration_ms=int(row["duration"]),
                actions=actions,
                failed=bool(row["failed"]),
                rework=bool(row["rework"]),
                unattributed_anomaly=bool(row["unattributed"]),
                measurement_anomaly=bool(row["measurement"]),
                loop=any(
                    index >= 2 and actions[index] == actions[index - 2]
                    for index in range(len(actions))
                ),
            )
        )
    return candidates


def select_trace_candidates(
    candidates: Iterable[TraceCandidate],
    *,
    limit: int,
) -> list[tuple[str, str]]:
    """Select candidate IDs and reasons with stable category tie-breakers."""
    candidates = list(candidates)
    if limit <= 0 or not candidates:
        return []
    durations = sorted(item.duration_ms for item in candidates)
    median = durations[(len(durations) - 1) // 2]
    p75 = durations[min(len(durations) - 1, int(len(durations) * 0.75))]
    signatures = Counter(item.actions for item in candidates)
    common = sorted(signatures.items(), key=lambda item: (-item[1], item[0]))[
        0
    ][0]
    selectors = (
        (
            "common",
            lambda item: item.actions == common,
            lambda item: (-item.event_count, item.episode_id),
        ),
        (
            "median",
            lambda item: True,
            lambda item: (abs(item.duration_ms - median), item.episode_id),
        ),
        (
            "p75",
            lambda item: True,
            lambda item: (abs(item.duration_ms - p75), item.episode_id),
        ),
        (
            "longest",
            lambda item: True,
            lambda item: (
                -item.duration_ms,
                -item.event_count,
                item.episode_id,
            ),
        ),
        (
            "rework",
            lambda item: item.rework,
            lambda item: (-item.duration_ms, item.episode_id),
        ),
        (
            "failure",
            lambda item: item.failed,
            lambda item: (-item.duration_ms, item.episode_id),
        ),
        (
            "unattributed_anomaly",
            lambda item: item.unattributed_anomaly,
            lambda item: (-item.event_count, item.episode_id),
        ),
        (
            "measurement_anomaly",
            lambda item: item.measurement_anomaly,
            lambda item: (-item.event_count, item.episode_id),
        ),
        (
            "loop",
            lambda item: item.loop or item.failed,
            lambda item: (-item.duration_ms, item.episode_id),
        ),
    )
    selected: list[tuple[str, str]] = []
    used: set[str] = set()
    per_category = max(1, limit // len(selectors))
    for reason, predicate, sort_key in selectors:
        options = sorted(
            (item for item in candidates if predicate(item)), key=sort_key
        )
        for item in options:
            if item.episode_id in used:
                continue
            selected.append((reason, item.episode_id))
            used.add(item.episode_id)
            if len(selected) >= limit:
                return selected
            if (
                sum(reason == current for current, _ in selected)
                >= per_category
            ):
                break
    return selected


def extract_trace_events(
    events: Iterable[EventEnvelope],
    selected: Iterable[tuple[str, str]],
    *,
    max_events: int = 256,
    max_bytes: int = 64 * 1024,
) -> list[dict[str, object]]:
    """Re-scan events and materialize only selected bounded traces."""
    reasons = {episode_id: reason for reason, episode_id in selected}
    if not reasons:
        return []
    grouped: defaultdict[str, list[EventEnvelope]] = defaultdict(list)
    for event in events:
        if event.object_episode_id in reasons:
            current = grouped[event.object_episode_id]
            if len(current) < max_events:
                current.append(event)
    output = []
    used_bytes = 0
    for episode_id in sorted(grouped):
        row = {
            "selection_reason": reasons[episode_id],
            "episode_id": episode_id,
            "event_count": len(grouped[episode_id]),
            "events": [event.to_dict() for event in grouped[episode_id]],
        }
        import json

        encoded = json.dumps(row, ensure_ascii=False, sort_keys=True)
        size = len(encoded.encode("utf-8")) + 1
        if used_bytes + size > max_bytes:
            break
        output.append(row)
        used_bytes += size
    return output
