"""Versioned, deterministic second-stage metrics for bounded exports."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Iterable

from .intervals import (
    MonoInterval,
    intersect_intervals,
    subtract_intervals,
    union_duration_ms,
)
from .versions import ANALYTICS_ALGORITHM_VERSION
from .metrics import (
    action_name,
    duration_summary,
    episode_metrics,
    object_metrics,
    rework_metrics,
    semantic_actions,
)
from .schema import EventEnvelope
from .versions import PERCENTILE_RULE_VERSION, WORKFLOW_STAGE_VERSION


@dataclass(frozen=True)
class ComparisonConfig:
    """Shared algorithm contract for both sides of a range comparison."""

    schema_adoption_version: str = "v3-preferred-v2-readable"
    algorithm_version: str = "2.0"
    workflow_stage_version: str = WORKFLOW_STAGE_VERSION
    rework_rule_version: str = "1.0"
    percentile_rule_version: str = PERCENTILE_RULE_VERSION
    min_samples: int = 30
    min_duration_coverage: float = 0.95

    def to_dict(self) -> dict[str, object]:
        """Return the exact contract used by both groups."""
        return {
            "schema_adoption_version": self.schema_adoption_version,
            "algorithm_version": self.algorithm_version,
            "workflow_stage_version": self.workflow_stage_version,
            "rework_rule_version": self.rework_rule_version,
            "percentile_rule_version": self.percentile_rule_version,
            "min_samples": self.min_samples,
            "min_duration_coverage": self.min_duration_coverage,
        }


WORKFLOW_STAGE_MAP: dict[str, str] = {
    "image_navigate": "navigation",
    "image_visit_started": "navigation",
    "shape_created": "object_creation",
    "shape_deleted": "object_creation",
    "shape_restored": "rework_recovery",
    "geometry_adjust": "geometry_edit",
    "rectangle_adjust": "geometry_edit",
    "keypoint_adjust": "geometry_edit",
    "keyboard_nudge": "geometry_edit",
    "zoom": "navigation",
    "pan": "navigation",
    "label_edit": "label_attribute",
    "attribute_edit": "label_attribute",
    "ai_correct": "ai_generation_correction",
    "inspector_review": "inspection_quality",
    "quality_review": "inspection_quality",
    "undo": "rework_recovery",
    "redo": "rework_recovery",
    "labels_saved": "save_commit",
    "shape_saved": "save_commit",
    "action_span": "unattributed",
}


def workflow_stage_for_action(action: str) -> str:
    """Map an action to a stable workflow stage without guessing intent."""
    return WORKFLOW_STAGE_MAP.get(action, "unattributed")


def workflow_stage_metrics(
    events: Iterable[EventEnvelope],
) -> list[dict[str, object]]:
    """Aggregate semantic actions by versioned workflow stage."""
    groups: defaultdict[str, list[EventEnvelope]] = defaultdict(list)
    for event in semantic_actions(events):
        groups[workflow_stage_for_action(action_name(event))].append(event)
    rows = []
    for stage, group in sorted(groups.items()):
        durations = [
            event.effective_duration_ms
            for event in group
            if event.effective_duration_ms is not None
        ]
        objects = {
            event.shape_id or event.object_episode_id
            for event in group
            if event.shape_id or event.object_episode_id
        }
        successes = sum(event.result == "success" for event in group)
        rows.append(
            {
                "workflow_stage": stage,
                "workflow_stage_version": WORKFLOW_STAGE_VERSION,
                "count": len(group),
                "object_coverage": len(objects),
                "success_count": successes,
                "result_rate": successes / len(group) if group else None,
                "duration_coverage": (
                    len(durations) / len(group) if group else 0.0
                ),
                "percentile_rule_version": PERCENTILE_RULE_VERSION,
                **duration_summary(durations),
            }
        )
    return rows


def episode_time_decomposition(
    events: Iterable[EventEnvelope], *, transition_gap_threshold_ms: int = 2000
) -> list[dict[str, object]]:
    """Decompose active episode time into action, wait, gap and unattributed.

    The implementation uses half-open intervals.  It intentionally reports
    ``unattributed`` as a neutral remainder and never labels it as a loss.
    """
    grouped: defaultdict[str, list[EventEnvelope]] = defaultdict(list)
    for event in events:
        if event.object_episode_id:
            grouped[event.object_episode_id].append(event)
    rows = []
    for episode_id, group in sorted(grouped.items()):
        ordered = sorted(
            group,
            key=lambda item: (
                item.monotonic_ms,
                (
                    item.sequence_no
                    if item.sequence_no is not None
                    else 2**63 - 1
                ),
                item.event_id,
            ),
        )
        starts = [
            event.monotonic_ms
            for event in ordered
            if event.event_type == "shape_selected"
        ]
        start = min(starts or [event.monotonic_ms for event in ordered])
        explicit_ends = [
            event.monotonic_ms
            for event in ordered
            if event.event_type == "object_episode_ended"
        ]
        is_v4 = any(event.schema_version >= 4 for event in ordered)
        if is_v4 and not explicit_ends:
            continue
        end = (
            min(explicit_ends)
            if explicit_ends
            else max(
                event.ended_monotonic_ms or event.monotonic_ms
                for event in ordered
            )
        )
        if end <= start:
            continue
        active = [MonoInterval(start, end)]
        action_intervals = []
        system_wait = []
        for event in ordered:
            event_start = event.started_monotonic_ms
            if event.event_type == "action_span" and event_start is None:
                event_start = event.monotonic_ms
            event_end = event.ended_monotonic_ms or event.monotonic_ms
            if (
                event.event_type == "action_span"
                and event_start is not None
                and event_end >= event_start
            ):
                action_intervals.append(MonoInterval(event_start, event_end))
            if event.event_type in {"idle_changed", "focus_changed"}:
                payload = event.payload or {}
                if event.event_type == "idle_changed" and payload.get("idle"):
                    system_wait.append(MonoInterval(event.monotonic_ms, end))
                if event.event_type == "focus_changed" and not payload.get(
                    "focused", True
                ):
                    system_wait.append(MonoInterval(event.monotonic_ms, end))
        action = intersect_intervals(active, action_intervals)
        wait = subtract_intervals(
            intersect_intervals(active, system_wait), action
        )
        transition = []
        action_sorted = sorted(action)
        for previous, current in zip(action_sorted, action_sorted[1:]):
            if (
                0
                < current.start_ms - previous.end_ms
                <= transition_gap_threshold_ms
            ):
                transition.append(
                    MonoInterval(previous.end_ms, current.start_ms)
                )
        transition = subtract_intervals(
            intersect_intervals(active, transition), action + wait
        )
        attributed = action + wait + transition
        remainder = subtract_intervals(active, attributed)
        wall_ms = end - start
        action_ms = union_duration_ms(action)
        wait_ms = union_duration_ms(wait)
        transition_ms = union_duration_ms(transition)
        unattributed_ms = union_duration_ms(remainder)
        total = action_ms + wait_ms + transition_ms + unattributed_ms
        rows.append(
            {
                "object_episode_id": episode_id,
                "project_session_id": ordered[0].project_session_id,
                "wall_ms": wall_ms,
                "attributed_action_ms": action_ms,
                "system_wait_ms": wait_ms,
                "transition_gap_ms": transition_ms,
                "unattributed_active_ms": unattributed_ms,
                "attribution_total_ms": total,
                "conservation_ok": total == wall_ms,
                "unattributed_active_ratio": unattributed_ms / wall_ms,
            }
        )
    return rows


def time_contribution_metrics(
    events: Iterable[EventEnvelope], *, transition_gap_threshold_ms: int = 2000
) -> list[dict[str, object]]:
    """Create objectively ranked action/stage time contribution rows."""
    action_totals: defaultdict[str, int] = defaultdict(int)
    action_counts: defaultdict[str, int] = defaultdict(int)
    for event in semantic_actions(events):
        duration = event.effective_duration_ms
        if duration is not None:
            action_totals[action_name(event)] += duration
        action_counts[action_name(event)] += 1
    for row in episode_time_decomposition(
        events, transition_gap_threshold_ms=transition_gap_threshold_ms
    ):
        action_totals["system_wait"] += int(row["system_wait_ms"])
        action_totals["transition_gap"] += int(row["transition_gap_ms"])
        action_totals["unattributed"] += int(row["unattributed_active_ms"])
    total_ms = sum(action_totals.values())
    rows = []
    cumulative = 0
    for action, total in sorted(
        action_totals.items(), key=lambda item: (-item[1], item[0])
    ):
        cumulative += total
        rows.append(
            {
                "action": action,
                "workflow_stage": workflow_stage_for_action(action),
                "count": action_counts.get(action, 0),
                "total_ms": total,
                "time_share": total / total_ms if total_ms else None,
                "cumulative_time_share": (
                    cumulative / total_ms if total_ms else None
                ),
                "percentile_rule_version": PERCENTILE_RULE_VERSION,
            }
        )
    return rows


def compare_ranges(
    baseline: Iterable[EventEnvelope],
    comparison: Iterable[EventEnvelope],
    *,
    min_samples: int = 30,
    config: ComparisonConfig | None = None,
    stratify: bool = True,
) -> list[dict[str, object]]:
    """Compare two ranges with shared metrics and observational semantics."""
    config_was_none = config is None
    config = config or ComparisonConfig(min_samples=min_samples)
    min_samples = config.min_samples
    baseline_events = list(baseline)
    comparison_events = list(comparison)
    if config_was_none and any(
        event.schema_version >= 4
        for event in baseline_events + comparison_events
    ):
        config = replace(config, algorithm_version=ANALYTICS_ALGORITHM_VERSION)
    baseline_rows = _comparison_rows(baseline_events, stratify=stratify)
    comparison_rows = _comparison_rows(comparison_events, stratify=stratify)
    keys = sorted(set(baseline_rows) | set(comparison_rows))
    output = [
        _overall_comparison_row(
            baseline_events,
            comparison_events,
            min_samples=min_samples,
            config=config,
        )
    ]
    for key in keys:
        left = baseline_rows.get(key, {"sample_count": 0, "mean_ms": None})
        right = comparison_rows.get(key, {"sample_count": 0, "mean_ms": None})
        reason = None
        if not left["sample_count"] or not right["sample_count"]:
            reason = "missing_group"
        elif min(left["sample_count"], right["sample_count"]) < min_samples:
            reason = "insufficient_samples"
        elif (
            min(
                left.get("duration_coverage", 0.0),
                right.get("duration_coverage", 0.0),
            )
            < config.min_duration_coverage
        ):
            reason = "insufficient_coverage"
        left_mean = left["mean_ms"]
        right_mean = right["mean_ms"]
        difference = (
            None
            if reason or left_mean is None or right_mean is None
            else right_mean - left_mean
        )
        relative = None
        if difference is not None and left_mean:
            relative = difference / left_mean
        output.append(
            {
                "dimension": key,
                "baseline": left,
                "comparison": right,
                "comparison_unavailable": reason,
                "absolute_difference_ms": difference,
                "relative_change": relative,
                "observational": True,
                "algorithm_version": ANALYTICS_ALGORITHM_VERSION,
                "workflow_stage_version": WORKFLOW_STAGE_VERSION,
                "percentile_rule_version": PERCENTILE_RULE_VERSION,
                "comparison_config": config.to_dict(),
            }
        )
    return output


def _overall_comparison_row(
    baseline: list[EventEnvelope],
    comparison: list[EventEnvelope],
    *,
    min_samples: int,
    config: ComparisonConfig,
) -> dict[str, object]:
    """Return whole-range sample, coverage and rework facts."""
    left = _comparison_summary(baseline)
    right = _comparison_summary(comparison)
    reason = (
        "missing_group"
        if not left["sample_count"] or not right["sample_count"]
        else (
            "insufficient_samples"
            if min(left["sample_count"], right["sample_count"]) < min_samples
            else (
                "insufficient_coverage"
                if min(
                    left["duration_coverage"],
                    right["duration_coverage"],
                )
                < config.min_duration_coverage
                else None
            )
        )
    )
    difference = (
        None
        if reason
        else (
            right["mean_ms"] - left["mean_ms"]
            if left["mean_ms"] is not None and right["mean_ms"] is not None
            else None
        )
    )
    relative = (
        difference / left["mean_ms"]
        if difference and left["mean_ms"]
        else None
    )
    return {
        "dimension": "__overall__",
        "baseline": left,
        "comparison": right,
        "comparison_unavailable": reason,
        "absolute_difference_ms": difference,
        "relative_change": relative,
        "observational": True,
        "algorithm_version": config.algorithm_version,
        "workflow_stage_version": config.workflow_stage_version,
        "percentile_rule_version": config.percentile_rule_version,
        "comparison_config": config.to_dict(),
    }


def _comparison_summary(events: list[EventEnvelope]) -> dict[str, object]:
    """Summarize comparison facts without a causal interpretation."""
    actions = semantic_actions(events)
    durations = [
        event.effective_duration_ms
        for event in actions
        if event.effective_duration_ms is not None
    ]
    episodes = episode_metrics(events)
    objects = object_metrics(events)
    rework = rework_metrics(events)
    rework_by_name = {row["metric"]: row["numerator"] for row in rework}
    decomposition = episode_time_decomposition(events)
    active_ms = sum(int(row["wall_ms"]) for row in decomposition)
    unattributed_ms = sum(
        int(row["unattributed_active_ms"]) for row in decomposition
    )
    summary = duration_summary(durations)
    return {
        "event_count": len(events),
        "episode_count": len(episodes),
        "object_count": len(objects),
        "sample_count": len(actions),
        "mean_ms": summary["mean_ms"],
        "duration_coverage": len(durations) / len(actions) if actions else 0.0,
        "active_ms": active_ms,
        "throughput_objects_per_hour": (
            len(objects) / (active_ms / 3_600_000) if active_ms else None
        ),
        "return_count": rework_by_name.get("returned_for_edit", 0),
        "undo_count": rework_by_name.get("undo", 0),
        "rework_count": sum(
            int(value or 0)
            for key, value in rework_by_name.items()
            if key not in {"returned_for_edit"}
        ),
        "unattributed_active_ms": unattributed_ms,
    }


def _comparison_rows(
    events: list[EventEnvelope], *, stratify: bool = True
) -> dict[str, dict[str, object]]:
    """Aggregate low-cardinality action rows for range comparison."""
    grouped: defaultdict[str, list[int]] = defaultdict(list)
    actions = semantic_actions(events)
    for event in actions:
        value = event.effective_duration_ms
        key = _comparison_key(event, stratify=stratify)
        if value is not None:
            grouped[key].append(value)
        else:
            grouped.setdefault(key, [])
    rows = {}
    for key, values in grouped.items():
        summary = duration_summary(values)
        rows[key] = {
            "sample_count": len(values),
            "mean_ms": summary["mean_ms"],
            "duration_coverage": len(values)
            / len(
                [
                    event
                    for event in actions
                    if _comparison_key(event, stratify=stratify) == key
                ]
            ),
        }
    return rows


def _comparison_key(event: EventEnvelope, *, stratify: bool) -> str:
    """Build the low-cardinality comparison key for one action."""
    key = action_name(event)
    if not stratify:
        return key
    context = event.context or (event.payload or {}).get("context") or {}
    return (
        key
        + "|"
        + "|".join(
            f"{dimension}={context.get(dimension, 'unknown')}"
            for dimension in (
                "shape_type",
                "size_bucket",
                "complexity_bucket",
                "initial_source",
                "functional_state",
            )
        )
    )
