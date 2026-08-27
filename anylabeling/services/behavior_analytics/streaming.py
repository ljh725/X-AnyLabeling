"""Incremental replay and aggregation state for large local exports."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .intervals import (
    MonoInterval,
    intersect_intervals,
    subtract_intervals,
    union_duration_ms,
)
from .metrics import action_name, duration_summary
from .schema import EventEnvelope
from .statistics_v3 import workflow_stage_for_action


def _is_semantic_action(event: EventEnvelope) -> bool:
    """Return whether an event is an exact, countable semantic action."""
    if event.event_type in {
        "shape_created",
        "shape_deleted",
        "shape_saved",
    }:
        return True
    if event.event_type != "action_span":
        return False
    return not (
        event.schema_version < 3
        and event.action_type in {None, "shape_edited"}
    )


@dataclass
class _ActionBucket:
    """Bounded aggregate state for one action/context/result key."""

    count: int = 0
    success_count: int = 0
    durations: list[int] = field(default_factory=list)
    duration_count: int = 0
    duration_total_ms: int = 0
    objects: set[str] = field(default_factory=set)


@dataclass
class _EpisodeBucket:
    """Compact episode state retaining intervals, not raw event objects."""

    episode_id: str
    project_session_id: str
    start_ms: int | None = None
    end_ms: int | None = None
    action_intervals: list[MonoInterval] = field(default_factory=list)
    system_wait_intervals: list[MonoInterval] = field(default_factory=list)
    event_count: int = 0
    changed: bool = False
    saved_after_change: bool = False
    closed: bool = False

    def consume(self, event: EventEnvelope) -> None:
        """Fold one event into the compact episode state."""
        current = event.monotonic_ms
        end = event.ended_monotonic_ms or current
        self.start_ms = (
            current if self.start_ms is None else min(self.start_ms, current)
        )
        self.end_ms = end if self.end_ms is None else max(self.end_ms, end)
        self.event_count += 1
        if event.event_type == "action_span" and end > current:
            self.action_intervals.append(MonoInterval(current, end))
        if event.event_type == "action_span" and event.result == "success":
            self.changed = True
        if event.event_type == "shape_saved" or bool(
            (event.payload or {}).get("saved_after_change")
        ):
            self.saved_after_change = True
        if event.event_type in {
            "shape_deleted",
            "image_visit_ended",
            "project_session_ended",
        }:
            self.closed = True
        if event.event_type == "idle_changed" and (event.payload or {}).get(
            "idle"
        ):
            self.system_wait_intervals.append(MonoInterval(current, end))
        if event.event_type == "focus_changed" and not (
            event.payload or {}
        ).get("focused", True):
            self.system_wait_intervals.append(MonoInterval(current, end))


class StreamingAnalytics:
    """Incremental finite-state aggregator for semantic event streams."""

    def __init__(self) -> None:
        """Initialize bounded entity and low-cardinality state."""
        self.event_count = 0
        self._action_buckets: defaultdict[
            tuple[str, str, str, str, str], _ActionBucket
        ] = defaultdict(_ActionBucket)
        self._stage_buckets: defaultdict[str, _ActionBucket] = defaultdict(
            _ActionBucket
        )
        self._episodes: dict[str, _EpisodeBucket] = {}
        self._rework: Counter[str] = Counter()
        self._sequence_last: dict[str, int] = {}
        self.sequence_gap_count = 0
        self.legacy_ordering_count = 0
        self._timed_actions = 0
        self._actions = 0

    def consume(self, event: EventEnvelope) -> None:
        """Consume one event without retaining the raw envelope."""
        self.event_count += 1
        if event.schema_version < 3:
            self.legacy_ordering_count += 1
        if event.schema_version == 3:
            previous = self._sequence_last.get(event.app_session_id)
            if previous is not None and event.sequence_no != previous + 1:
                self.sequence_gap_count += 1
            self._sequence_last[event.app_session_id] = (
                event.sequence_no or previous or 0
            )
        if event.object_episode_id:
            episode = self._episodes.setdefault(
                event.object_episode_id,
                _EpisodeBucket(
                    event.object_episode_id, event.project_session_id
                ),
            )
            episode.consume(event)
        if not _is_semantic_action(event):
            return
        name = action_name(event)
        target = (
            event.edit_target
            or (event.payload or {}).get("edit_target")
            or "unknown"
        )
        context = event.context or (event.payload or {}).get("context") or {}
        context_key = str(context.get("shape_type", "unknown"))
        key = (
            name,
            str(target),
            event.input_source,
            event.result,
            context_key,
        )
        bucket = self._action_buckets[key]
        bucket.count += 1
        bucket.success_count += event.result == "success"
        if event.shape_id or event.object_episode_id:
            bucket.objects.add(event.shape_id or event.object_episode_id or "")
        if event.effective_duration_ms is not None:
            self._record_duration(bucket, event.effective_duration_ms)
            self._timed_actions += 1
        self._actions += 1
        stage_bucket = self._stage_buckets[workflow_stage_for_action(name)]
        stage_bucket.count += 1
        stage_bucket.success_count += event.result == "success"
        stage_bucket.objects.update(bucket.objects)
        if event.effective_duration_ms is not None:
            self._record_duration(stage_bucket, event.effective_duration_ms)
        if name in {"undo", "redo"}:
            self._rework[name] += 1
        if event.result == "no_change":
            self._rework["no_change"] += 1

    def consume_iter(
        self,
        events: Iterable[EventEnvelope],
        *,
        batch_size: int = 256,
        on_batch: Callable[[int], None] | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> None:
        """Consume an iterable with bounded progress and cancellation checks."""
        batch_count = 0
        for event in events:
            if cancel and cancel():
                return
            self.consume(event)
            batch_count += 1
            if batch_count >= max(1, batch_size):
                if on_batch:
                    on_batch(batch_count)
                batch_count = 0
        if batch_count and on_batch:
            on_batch(batch_count)

    def finish(self) -> dict[str, object]:
        """Materialize deterministic metrics from compact state."""
        action_rows = []
        for (name, target, source, result, context), bucket in sorted(
            self._action_buckets.items()
        ):
            action_rows.append(
                {
                    "action": name,
                    "edit_target": target,
                    "input_source": source,
                    "result": result,
                    "shape_context": context,
                    "count": bucket.count,
                    "result_rate": bucket.success_count / bucket.count,
                    "duration_coverage": bucket.duration_count / bucket.count,
                    **self._duration_summary(bucket),
                }
            )
        stage_rows = []
        for stage, bucket in sorted(self._stage_buckets.items()):
            stage_rows.append(
                {
                    "workflow_stage": stage,
                    "count": bucket.count,
                    "object_coverage": len(bucket.objects),
                    "success_count": bucket.success_count,
                    "result_rate": bucket.success_count / bucket.count,
                    "duration_coverage": bucket.duration_count / bucket.count,
                    **self._duration_summary(bucket),
                }
            )
        episode_rows = [
            self._episode_row(row) for row in self._episodes.values()
        ]
        episode_rows.sort(key=lambda row: row["object_episode_id"])
        totals: Counter[str] = Counter()
        counts: Counter[str] = Counter()
        for (name, *_), bucket in self._action_buckets.items():
            counts[name] += bucket.count
            totals[name] += bucket.duration_total_ms
        for row in episode_rows:
            totals["system_wait"] += row["system_wait_ms"]
            totals["transition_gap"] += row["transition_gap_ms"]
            totals["unattributed"] += row["unattributed_active_ms"]
        total_ms = sum(totals.values())
        cumulative = 0
        time_rows = []
        for name, total in sorted(
            totals.items(), key=lambda item: (-item[1], item[0])
        ):
            cumulative += total
            time_rows.append(
                {
                    "action": name,
                    "workflow_stage": workflow_stage_for_action(name),
                    "count": counts.get(name, 0),
                    "total_ms": total,
                    "time_share": total / total_ms if total_ms else None,
                    "cumulative_time_share": (
                        cumulative / total_ms if total_ms else None
                    ),
                }
            )
        duration_rate = (
            self._timed_actions / self._actions if self._actions else 0.0
        )
        closure_rate = (
            sum(
                row["terminal_integrity"] == "complete" for row in episode_rows
            )
            / len(episode_rows)
            if episode_rows
            else 1.0
        )
        return {
            "streaming": True,
            "event_count": self.event_count,
            "action_metrics": action_rows,
            "workflow_stage_metrics": stage_rows,
            "episode_time_decomposition": episode_rows,
            "time_contribution": time_rows,
            "rework_metrics": [
                {"metric": name, "numerator": count}
                for name, count in sorted(self._rework.items())
            ],
            "measurement_quality": {
                "metrics": {
                    "action_duration_coverage": {
                        "numerator": self._timed_actions,
                        "denominator": self._actions,
                        "value": duration_rate,
                    },
                    "episode_closure_rate": {
                        "numerator": sum(
                            row["terminal_integrity"] == "complete"
                            for row in episode_rows
                        ),
                        "denominator": len(episode_rows),
                        "value": closure_rate,
                    },
                    "sequence_gap_count": {
                        "numerator": self.sequence_gap_count,
                        "denominator": self.event_count,
                        "value": self.sequence_gap_count,
                    },
                },
                "legacy_ordering_count": self.legacy_ordering_count,
            },
        }

    @staticmethod
    def _record_duration(bucket: _ActionBucket, value: int) -> None:
        """Keep exact totals and a fixed deterministic percentile sample."""
        bucket.duration_count += 1
        bucket.duration_total_ms += value
        sample_limit = 1024
        if len(bucket.durations) < sample_limit:
            bucket.durations.append(value)
            return
        replace_at = (bucket.duration_count - 1) % sample_limit
        bucket.durations[replace_at] = value

    @staticmethod
    def _duration_summary(bucket: _ActionBucket) -> dict[str, object]:
        """Return bounded percentile facts with exact count and total."""
        summary = duration_summary(bucket.durations)
        summary["sample_count"] = bucket.duration_count
        summary["total_ms"] = bucket.duration_total_ms
        summary["sample_method"] = "deterministic_bounded_1024"
        return summary

    @staticmethod
    def _episode_row(row: _EpisodeBucket) -> dict[str, object]:
        """Materialize one episode's interval facts."""
        start = row.start_ms or 0
        end = max(start, row.end_ms or start)
        active = [MonoInterval(start, end)] if end > start else []
        actions = intersect_intervals(active, row.action_intervals)
        waits = subtract_intervals(
            intersect_intervals(active, row.system_wait_intervals), actions
        )
        transition = []
        for previous, current in zip(sorted(actions), sorted(actions)[1:]):
            if 0 < current.start_ms - previous.end_ms <= 2000:
                transition.append(
                    MonoInterval(previous.end_ms, current.start_ms)
                )
        transition = subtract_intervals(
            intersect_intervals(active, transition), actions + waits
        )
        remainder = subtract_intervals(active, actions + waits + transition)
        action_ms = union_duration_ms(actions)
        wait_ms = union_duration_ms(waits)
        transition_ms = union_duration_ms(transition)
        unattributed = union_duration_ms(remainder)
        return {
            "object_episode_id": row.episode_id,
            "project_session_id": row.project_session_id,
            "wall_ms": end - start,
            "attributed_action_ms": action_ms,
            "system_wait_ms": wait_ms,
            "transition_gap_ms": transition_ms,
            "unattributed_active_ms": unattributed,
            "attribution_total_ms": action_ms
            + wait_ms
            + transition_ms
            + unattributed,
            "conservation_ok": action_ms
            + wait_ms
            + transition_ms
            + unattributed
            == end - start,
            "event_count": row.event_count,
            "changed": row.changed,
            "saved_after_change": row.saved_after_change,
            "terminal_integrity": "complete" if row.closed else "unknown",
        }


def stream_calculate_statistics(
    events: Iterable[EventEnvelope],
    *,
    batch_size: int = 256,
    on_batch: Callable[[int], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> dict[str, object]:
    """Calculate streaming metrics without retaining raw event envelopes."""
    state = StreamingAnalytics()
    state.consume_iter(
        events,
        batch_size=batch_size,
        on_batch=on_batch,
        cancel=cancel,
    )
    return state.finish()
