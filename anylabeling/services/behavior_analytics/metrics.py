"""Deterministic second-phase behavior analytics metrics."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable

from .replay import replay_events
from .schema import EventEnvelope
from .versions import PAUSE_RULE_VERSION, REWORK_RULE_VERSION

_LIFECYCLE_EVENTS = {
    "app_session_started",
    "app_session_ended",
    "project_session_started",
    "project_session_ended",
    "feature_state_snapshot",
    "feature_state_changed",
    "image_visit_started",
    "image_visit_ended",
    "shape_selected",
    "object_episode_ended",
    "focus_changed",
    "idle_changed",
}


def _ordered(events: Iterable[EventEnvelope]) -> list[EventEnvelope]:
    """Return events in their deterministic temporal order."""
    return sorted(
        events,
        key=lambda event: (
            event.occurred_at_utc,
            event.monotonic_ms,
            event.sequence_no if event.sequence_no is not None else 2**63 - 1,
            event.event_id,
        ),
    )


def action_name(event: EventEnvelope) -> str:
    """Return the stable semantic action name for an event."""
    if event.action_type:
        return event.action_type
    if event.payload and event.payload.get("action"):
        return str(event.payload["action"])
    return event.event_type


def semantic_actions(events: Iterable[EventEnvelope]) -> list[EventEnvelope]:
    """Filter lifecycle and legacy duplicate callbacks from action streams."""
    result = []
    for event in _ordered(events):
        if event.event_type in _LIFECYCLE_EVENTS:
            continue
        if event.schema_version == 1 and event.event_type == "shape_edited":
            continue
        if event.event_type == "action_span" or event.event_type in {
            "shape_created",
            "shape_deleted",
            "shape_saved",
        }:
            result.append(event)
    return result


def sequence_metrics(
    events: Iterable[EventEnvelope], *, idle_boundary_ms: int = 600_000
) -> list[dict[str, object]]:
    """Count deterministic 3-6 action sequences after semantic normalization."""
    grouped: defaultdict[tuple[str, str, str], list[EventEnvelope]] = (
        defaultdict(list)
    )
    for event in semantic_actions(events):
        if event.image_id:
            grouped[
                (
                    event.project_session_id,
                    event.image_id,
                    event.object_episode_id or "",
                )
            ].append(event)
    counts: Counter[tuple[tuple[str, ...], int]] = Counter()
    coverage: defaultdict[
        tuple[tuple[str, ...], int], set[tuple[str, str, str]]
    ] = defaultdict(set)
    active_by_sequence: Counter[tuple[tuple[str, ...], int]] = Counter()
    for group_key, group in grouped.items():
        group = _ordered(group)
        actions: list[str] = []
        last_ms: int | None = None
        for event in group:
            if (
                last_ms is not None
                and event.monotonic_ms - last_ms > idle_boundary_ms
            ):
                actions = []
            actions.append(action_name(event))
            last_ms = event.monotonic_ms
        for size in range(3, 7):
            for index in range(len(actions) - size + 1):
                counts[(tuple(actions[index : index + size]), size)] += 1
                sequence_key = (tuple(actions[index : index + size]), size)
                coverage[sequence_key].add(group_key)
                active_by_sequence[sequence_key] += sum(
                    event.effective_duration_ms or 0 for event in group
                )
    return [
        {
            "sequence": list(sequence),
            "length": size,
            "count": count,
            "object_count": len(coverage[(sequence, size)]),
            "episode_count": len(coverage[(sequence, size)]),
            "active_ms": active_by_sequence[(sequence, size)] or None,
        }
        for (sequence, size), count in sorted(
            counts.items(), key=lambda item: (-item[1], item[0][0])
        )
    ]


def repetition_diagnostics(
    events: Iterable[EventEnvelope],
) -> list[dict[str, object]]:
    """Report same-action loops separately from primary workflow sequences."""
    actions = semantic_actions(events)
    repeats = sum(
        action_name(before) == action_name(after)
        for before, after in zip(actions, actions[1:])
    )
    return [
        {
            "diagnostic": "same_action_loop",
            "count": repeats,
            "event_count": len(actions),
            "rate": repeats / len(actions) if actions else 0.0,
        }
    ]


def duration_summary(values: Iterable[int]) -> dict[str, int | float | None]:
    """Summarize valid durations without replacing missing values with zero."""
    ordered = sorted(value for value in values if value >= 0)
    if not ordered:
        return {
            "sample_count": 0,
            "total_ms": None,
            "mean_ms": None,
            "median_ms": None,
            "p75_ms": None,
            "p90_ms": None,
            "p95_ms": None,
        }

    def percentile(percent: float) -> float:
        """Compute one interpolated percentile."""
        position = (len(ordered) - 1) * percent
        lower = int(position)
        upper = min(len(ordered) - 1, lower + 1)
        weight = position - lower
        return ordered[lower] + (ordered[upper] - ordered[lower]) * weight

    return {
        "sample_count": len(ordered),
        "total_ms": sum(ordered),
        "mean_ms": sum(ordered) / len(ordered),
        "median_ms": percentile(0.5),
        "p75_ms": percentile(0.75),
        "p90_ms": percentile(0.90),
        "p95_ms": percentile(0.95),
    }


def action_metrics(events: Iterable[EventEnvelope]) -> list[dict[str, object]]:
    """Aggregate semantic actions by action, target, source, result and context."""
    groups: defaultdict[
        tuple[str, str, str, str, str], list[EventEnvelope]
    ] = defaultdict(list)
    for event in semantic_actions(events):
        context = event.context or (event.payload or {}).get("context") or {}
        context_key = str(context.get("shape_type", "unknown"))
        target = event.edit_target or (event.payload or {}).get("edit_target")
        groups[
            (
                action_name(event),
                str(target or "unknown"),
                event.input_source,
                event.result,
                context_key,
            )
        ].append(event)
    rows = []
    for (action, target, source, result, context), group in sorted(
        groups.items()
    ):
        durations = [
            duration
            for event in group
            if (duration := event.effective_duration_ms) is not None
        ]
        summary = duration_summary(durations)
        rows.append(
            {
                "action": action,
                "edit_target": target,
                "input_source": source,
                "result": result,
                "shape_context": context,
                "count": len(group),
                "result_rate": len(group) / len(group),
                "duration_coverage": len(durations) / len(group),
                **summary,
            }
        )
    return rows


def _episode_end_reason(events: list[EventEnvelope]) -> str | None:
    """Infer an auditable episode ending reason from boundary events."""
    for event in reversed(events):
        if event.event_type == "object_episode_ended":
            return event.episode_end_reason or "unknown"
        if event.event_type == "shape_deleted":
            return "shape_deleted"
        if event.event_type == "image_visit_ended":
            return "image_changed"
        if event.event_type == "project_session_ended":
            return "project_closed"
    return None


def _time_layers(
    all_events: list[EventEnvelope],
    group: list[EventEnvelope],
) -> tuple[int, int, int, str | None]:
    """Integrate wall/focused/active layers and locate the next boundary."""
    session_id = group[0].project_session_id
    starts = [
        event.monotonic_ms
        for event in group
        if event.event_type == "shape_selected"
    ]
    start = min(starts or [event.monotonic_ms for event in group])
    explicit_end = [
        event.monotonic_ms
        for event in group
        if event.event_type == "object_episode_ended"
    ]
    end = (
        min(explicit_end)
        if explicit_end
        else max(event.monotonic_ms for event in group)
    )
    surrounding = [
        event
        for event in all_events
        if event.project_session_id == session_id
        and event.monotonic_ms >= start
    ]
    focused = True
    idle = False
    focused_ms = 0
    active_ms = 0
    previous = start
    reason = _episode_end_reason(group)
    for event in surrounding:
        if event.monotonic_ms > end and event.event_type in {
            "shape_selected",
            "image_visit_ended",
            "project_session_ended",
        }:
            if event.event_type == "shape_selected":
                reason = "selection_changed"
            elif event.event_type == "image_visit_ended":
                reason = "image_changed"
            else:
                reason = "project_closed"
            break
        if event.monotonic_ms > end:
            continue
        elapsed = max(0, event.monotonic_ms - previous)
        if focused:
            focused_ms += elapsed
            if not idle:
                active_ms += elapsed
        if event.event_type == "focus_changed" and event.payload:
            focused = bool(event.payload.get("focused", focused))
        elif event.event_type == "idle_changed" and event.payload:
            idle = bool(event.payload.get("idle", idle))
        previous = event.monotonic_ms
    elapsed = max(0, end - previous)
    if focused:
        focused_ms += elapsed
        if not idle:
            active_ms += elapsed
    return end - start, focused_ms, active_ms, reason


def episode_metrics(
    events: Iterable[EventEnvelope],
) -> list[dict[str, object]]:
    """Build per-episode wall, focused, active and completion fact rows."""
    grouped: defaultdict[str, list[EventEnvelope]] = defaultdict(list)
    ordered = _ordered(events)
    for event in ordered:
        if event.object_episode_id:
            grouped[event.object_episode_id].append(event)
    rows = []
    ordered = _ordered(events)
    for episode_id, group in sorted(grouped.items()):
        is_v4 = any(event.schema_version >= 4 for event in group)
        has_explicit_end = any(
            event.event_type == "object_episode_ended" for event in group
        )
        start = min(
            (
                event.monotonic_ms
                for event in group
                if event.event_type == "shape_selected"
            ),
            default=min(event.monotonic_ms for event in group),
        )
        if is_v4 and not has_explicit_end:
            wall_ms = focused_ms = active_ms = None
            end_reason = None
            end = None
        else:
            wall_ms, focused_ms, active_ms, end_reason = _time_layers(
                ordered, group
            )
            end = start + wall_ms
            if not any(
                event.event_type in {"focus_changed", "idle_changed"}
                for event in group
            ):
                focused_ms = None
                active_ms = None
        durations = [
            value
            for event in group
            if (value := event.effective_duration_ms) is not None
        ]
        changed = any(
            event.event_type == "action_span" and event.result == "success"
            for event in group
        )
        saved = any(
            event.event_type == "shape_saved"
            or bool((event.payload or {}).get("saved_after_change"))
            for event in group
        )
        rows.append(
            {
                "object_episode_id": episode_id,
                "project_id": group[0].project_id,
                "image_id": group[0].image_id,
                "shape_id": group[0].shape_id,
                "started_monotonic_ms": start,
                "ended_monotonic_ms": end,
                "wall_ms": wall_ms,
                "focused_ms": focused_ms,
                "active_ms": active_ms,
                "action_duration_ms": duration_summary(durations),
                "event_count": len(group),
                "action_count": sum(
                    event.event_type == "action_span" for event in group
                ),
                "changed": changed,
                "saved_after_change": saved if changed else False,
                "completion": "unknown",
                "end_reason": end_reason,
                "terminal_integrity": (
                    "complete"
                    if end_reason and (has_explicit_end or not is_v4)
                    else ("unclosed" if is_v4 else "legacy_low_confidence")
                ),
            }
        )
    return rows


def episode_cycle_metrics(
    events: Iterable[EventEnvelope], *, pause_threshold_ms: int = 600_000
) -> dict[str, object]:
    """Summarize object-cycle durations with explicit missingness categories.

    Only positively measured, closed v4 cycles are included in the primary
    duration distribution.  Zero-duration, unclosed, and over-pause cycles
    remain visible as counts instead of being silently coerced into samples.
    """
    rows = episode_metrics(events)
    positive: list[int] = []
    pause_adjusted: list[int] = []
    zero_duration = 0
    unclosed = 0
    over_pause = 0
    for row in rows:
        wall = row.get("wall_ms")
        if row.get("terminal_integrity") == "unclosed" or wall is None:
            unclosed += 1
            continue
        wall = int(wall)
        if wall == 0:
            zero_duration += 1
            continue
        if wall < 0:
            unclosed += 1
            continue
        if wall > pause_threshold_ms:
            over_pause += 1
            pause_adjusted.append(max(0, wall - pause_threshold_ms))
            continue
        positive.append(wall)
    return {
        "rule_version": PAUSE_RULE_VERSION,
        "pause_threshold_ms": pause_threshold_ms,
        "cycle_count": len(rows),
        "positive_count": len(positive),
        "zero_duration_count": zero_duration,
        "unclosed_count": unclosed,
        "over_pause_count": over_pause,
        "duration_summary": duration_summary(positive),
        "pause_adjusted_summary": duration_summary(pause_adjusted),
    }


def object_metrics(events: Iterable[EventEnvelope]) -> list[dict[str, object]]:
    """Aggregate episode counts and return/rework facts by object identity."""
    episodes = episode_metrics(events)
    grouped: defaultdict[tuple[str, str, str], list[dict[str, object]]] = (
        defaultdict(list)
    )
    for row in episodes:
        grouped[(row["project_id"], row["image_id"], row["shape_id"])].append(
            row
        )
    rows = []
    for key, group in sorted(grouped.items()):
        active = [
            row["active_ms"] for row in group if row["active_ms"] is not None
        ]
        rows.append(
            {
                "project_id": key[0],
                "image_id": key[1],
                "shape_id": key[2],
                "episode_count": len(group),
                "return_count": max(0, len(group) - 1),
                "effective_edit_count": sum(row["changed"] for row in group),
                "active_ms": sum(active) if active else None,
                "completion": (
                    "unknown"
                    if any(row["completion"] == "unknown" for row in group)
                    else "complete"
                ),
                "saved": any(row["saved_after_change"] for row in group),
                "rework_count": max(0, len(group) - 1),
            }
        )
    return rows


def image_metrics(events: Iterable[EventEnvelope]) -> list[dict[str, object]]:
    """Aggregate image visits, object work and active-time throughput."""
    ordered = _ordered(events)
    grouped: defaultdict[str, list[EventEnvelope]] = defaultdict(list)
    for event in ordered:
        if event.image_id:
            grouped[event.image_id].append(event)
    objects = object_metrics(ordered)
    object_by_image: defaultdict[str, list[dict[str, object]]] = defaultdict(
        list
    )
    for row in objects:
        object_by_image[str(row["image_id"])].append(row)
    rows = []
    for image_id, group in sorted(grouped.items()):
        visits = sum(
            event.event_type == "image_visit_started" for event in group
        )
        active = [
            row["active_ms"]
            for row in object_by_image[image_id]
            if row["active_ms"] is not None
        ]
        active_ms = sum(active) if active else None
        object_count = len(object_by_image[image_id])
        rows.append(
            {
                "image_id": image_id,
                "image_visit_count": visits,
                "object_count": object_count,
                "created_count": sum(
                    event.event_type == "shape_created" for event in group
                ),
                "edited_count": sum(
                    event.event_type == "action_span"
                    and event.result == "success"
                    for event in group
                ),
                "deleted_count": sum(
                    event.event_type == "shape_deleted" for event in group
                ),
                "rework_object_count": sum(
                    row["rework_count"] > 0
                    for row in object_by_image[image_id]
                ),
                "active_ms": active_ms,
                "objects_per_active_hour": (
                    object_count / (active_ms / 3_600_000)
                    if active_ms
                    else None
                ),
            }
        )
    return rows


def rework_metrics(events: Iterable[EventEnvelope]) -> list[dict[str, object]]:
    """Compute versioned, auditable rework numerator/denominator rows."""
    ordered = _ordered(events)
    episodes = episode_metrics(ordered)
    by_object: defaultdict[
        tuple[object, object, object], list[dict[str, object]]
    ] = defaultdict(list)
    for row in episodes:
        by_object[
            (row["project_id"], row["image_id"], row["shape_id"])
        ].append(row)
    facts = Counter()
    denominators = Counter()
    active_by_rule: Counter[str] = Counter()
    for key, group in by_object.items():
        del key
        denominators["returned_for_edit"] += max(0, len(group) - 1)
        facts["returned_for_edit"] += max(0, len(group) - 1)
        denominators["repeated_return"] += max(0, len(group) - 2)
        facts["repeated_return"] += max(0, len(group) - 2)
        if any(row["saved_after_change"] for row in group[:-1]) and any(
            row["changed"] for row in group[1:]
        ):
            facts["saved_then_reedited"] += 1
        denominators["saved_then_reedited"] += bool(
            any(row["saved_after_change"] for row in group[:-1])
        )
        active_by_rule["returned_for_edit"] += sum(
            row["active_ms"] or 0 for row in group[1:]
        )
    action_events = semantic_actions(ordered)
    for event in action_events:
        name = action_name(event)
        if event.result == "no_change":
            facts["no_change"] += 1
        denominators["no_change"] += 1
        if name in {"undo", "redo"} or event.event_type == "shape_deleted":
            denominators[name] += 1
            if name in {"undo", "redo"}:
                relation = (event.payload or {}).get(
                    "undo_of_action_id"
                    if name == "undo"
                    else "redo_of_action_id"
                )
                if relation:
                    facts[name] += 1
        if name in {"adjust", "rectangle_adjust", "shape_adjust"}:
            denominators["reverse_adjustment"] += 1
        if name in {"undo", "redo"}:
            relation = (event.payload or {}).get(
                "undo_of_action_id" if name == "undo" else "redo_of_action_id"
            )
            if relation:
                facts[f"{name}_associated"] += 1
        if name in {"adjust", "rectangle_adjust", "shape_adjust"}:
            if (event.payload or {}).get("reverse_of_action_id"):
                facts["reverse_adjustment"] += 1
    created = {
        (event.project_id, event.image_id, event.shape_id)
        for event in ordered
        if event.event_type == "shape_created" and event.shape_id
    }
    deleted = {
        (event.project_id, event.image_id, event.shape_id)
        for event in ordered
        if event.event_type == "shape_deleted" and event.shape_id
    }
    denominators["created_then_deleted"] += len(created)
    facts["created_then_deleted"] += len(created & deleted)
    modified = {
        (event.project_id, event.image_id, event.shape_id)
        for event in ordered
        if event.event_type == "action_span" and event.result == "success"
    }
    denominators["modified_then_deleted"] += len(modified)
    facts["modified_then_deleted"] += len(modified & deleted)
    rows = []
    for rule in sorted(set(denominators) | set(facts)):
        denominator = denominators[rule]
        numerator = facts[rule]
        rows.append(
            {
                "metric": rule,
                "rule_version": REWORK_RULE_VERSION,
                "time_window": "project_session",
                "numerator": numerator,
                "denominator": denominator,
                "rate": numerator / denominator if denominator else None,
                "not_applicable": 1 if denominator == 0 else 0,
                "rework_active_ms": active_by_rule.get(rule, 0) or None,
            }
        )
    return rows


def measurement_quality(
    events: Iterable[EventEnvelope],
    *,
    duration_threshold: float = 0.95,
    closure_threshold: float = 0.99,
    duplicate_threshold: float = 0.05,
    anomaly_event_count: int = 100,
    anomaly_active_ms: int = 600_000,
) -> dict[str, object]:
    """Return quality gates with numerator, denominator and exclusion reasons."""
    ordered = _ordered(events)
    actions = [event for event in ordered if event.event_type == "action_span"]
    timed = [
        event for event in actions if event.effective_duration_ms is not None
    ]
    episodes = episode_metrics(ordered)
    closed = [
        row for row in episodes if row["terminal_integrity"] == "complete"
    ]
    context_count = sum(
        bool(event.context or (event.payload or {}).get("context"))
        for event in actions
    )
    duplicates = sum(
        event.schema_version == 1 and event.event_type == "shape_edited"
        for event in ordered
    )
    denominator = len(actions)
    duration_rate = len(timed) / denominator if denominator else 0.0
    closure_rate = len(closed) / len(episodes) if episodes else 1.0
    duplicate_rate = duplicates / len(ordered) if ordered else 0.0
    feature_versions = {
        event.feature_state_version
        for event in ordered
        if event.event_type
        in {"feature_state_snapshot", "feature_state_changed"}
    }
    feature_covered = sum(
        event.feature_state_version in feature_versions for event in actions
    )
    legacy_count = sum(event.schema_version == 1 for event in ordered)
    sequence_events = [event for event in ordered if event.schema_version >= 3]
    sequence_events.sort(
        key=lambda event: (event.app_session_id, event.sequence_no or 0)
    )
    sequence_gaps = 0
    previous_by_session: dict[str, int] = {}
    for event in sequence_events:
        previous = previous_by_session.get(event.app_session_id)
        if previous is not None and event.sequence_no != previous + 1:
            sequence_gaps += 1
        previous_by_session[event.app_session_id] = (
            event.sequence_no or previous or 0
        )
    try:
        from .statistics_v3 import episode_time_decomposition

        decomposition = episode_time_decomposition(ordered)
    except (ImportError, ValueError):
        decomposition = []
    wall_ms = sum(int(row["wall_ms"]) for row in decomposition)
    unattributed_ms = sum(
        int(row["unattributed_active_ms"]) for row in decomposition
    )
    episode_samples = len(episodes)
    object_samples = len(object_metrics(ordered))
    image_samples = len(image_metrics(ordered))
    metrics = {
        "action_duration_coverage": {
            "numerator": len(timed),
            "denominator": denominator,
            "value": duration_rate,
            "threshold": duration_threshold,
            "status": (
                "pass" if duration_rate >= duration_threshold else "fail"
            ),
            "affected_event_types": ["action_span"],
            "exclusion_reason": (
                "missing_monotonic_boundaries"
                if denominator > len(timed)
                else None
            ),
        },
        "episode_closure_rate": {
            "numerator": len(closed),
            "denominator": len(episodes),
            "value": closure_rate,
            "threshold": closure_threshold,
            "status": "pass" if closure_rate >= closure_threshold else "fail",
            "affected_event_types": ["shape_selected", "image_visit_ended"],
            "exclusion_reason": (
                "missing_boundary" if len(closed) < len(episodes) else None
            ),
        },
        "context_coverage": {
            "numerator": context_count,
            "denominator": denominator,
            "value": context_count / denominator if denominator else 0.0,
            "threshold": 1.0,
            "status": "pass" if context_count == denominator else "fail",
            "affected_event_types": ["action_span"],
            "exclusion_reason": (
                "missing_context" if context_count < denominator else None
            ),
        },
        "comparison_context": {
            "numerator": context_count,
            "denominator": denominator,
            "value": context_count / denominator if denominator else 0.0,
            "threshold": 1.0,
            "status": (
                "pass"
                if context_count == denominator
                else ("unavailable" if context_count == 0 else "degraded")
            ),
            "affected_event_types": ["action_span"],
            "exclusion_reason": (
                "missing_context" if context_count < denominator else None
            ),
        },
        "action_duration": {
            "numerator": len(timed),
            "denominator": denominator,
            "value": duration_rate,
            "threshold": duration_threshold,
            "status": (
                "pass" if duration_rate >= duration_threshold else "fail"
            ),
            "affected_event_types": ["action_span"],
            "exclusion_reason": (
                "missing_monotonic_boundaries"
                if denominator > len(timed)
                else None
            ),
        },
        "object_cycle": {
            "numerator": len(closed),
            "denominator": len(episodes),
            "value": closure_rate,
            "threshold": closure_threshold,
            "status": "pass" if closure_rate >= closure_threshold else "fail",
            "affected_event_types": ["shape_selected", "object_episode_ended"],
            "exclusion_reason": (
                "missing_boundary" if len(closed) < len(episodes) else None
            ),
        },
        "focused_active": {
            "numerator": sum(
                event.event_type in {"focus_changed", "idle_changed"}
                for event in ordered
            ),
            "denominator": len(episodes),
            "value": (
                None
                if not episodes
                else (
                    sum(
                        event.event_type in {"focus_changed", "idle_changed"}
                        for event in ordered
                    )
                    / len(episodes)
                )
            ),
            "threshold": 1.0,
            "status": (
                "pass"
                if episodes
                and any(
                    event.event_type in {"focus_changed", "idle_changed"}
                    for event in ordered
                )
                and all(
                    row["focused_ms"] is not None
                    and row["active_ms"] is not None
                    for row in episodes
                    if row["terminal_integrity"] == "complete"
                )
                else ("unavailable" if not episodes else "degraded")
            ),
            "affected_event_types": ["focus_changed", "idle_changed"],
            "exclusion_reason": (
                "missing_focus_idle_boundaries"
                if episodes
                and not any(
                    event.event_type in {"focus_changed", "idle_changed"}
                    for event in ordered
                )
                else None
            ),
        },
        "low_level_duplicate_rate": {
            "numerator": duplicates,
            "denominator": len(ordered),
            "value": duplicate_rate,
            "threshold": duplicate_threshold,
            "status": (
                "pass" if duplicate_rate < duplicate_threshold else "fail"
            ),
            "affected_event_types": ["shape_edited"],
            "exclusion_reason": (
                "legacy_low_granularity" if duplicates else None
            ),
        },
        "long_episode_count": {
            "numerator": sum(
                row["event_count"] > anomaly_event_count
                or (row["active_ms"] or 0) > anomaly_active_ms
                for row in episodes
            ),
            "denominator": len(episodes),
            "value": None,
            "threshold": {
                "event_count": anomaly_event_count,
                "active_ms": anomaly_active_ms,
            },
            "status": "diagnostic",
            "affected_event_types": ["action_span"],
            "exclusion_reason": None,
        },
        "feature_state_coverage": {
            "numerator": feature_covered,
            "denominator": denominator,
            "value": feature_covered / denominator if denominator else 0.0,
            "threshold": 1.0,
            "status": "pass" if feature_covered == denominator else "fail",
            "affected_event_types": ["action_span", "feature_state_snapshot"],
            "exclusion_reason": (
                "missing_state_reference"
                if feature_covered < denominator
                else None
            ),
        },
        "legacy_version_share": {
            "numerator": legacy_count,
            "denominator": len(ordered),
            "value": legacy_count / len(ordered) if ordered else 0.0,
            "threshold": None,
            "status": "diagnostic",
            "affected_event_types": ["schema_v1"],
            "exclusion_reason": (
                "legacy_low_granularity" if legacy_count else None
            ),
        },
        "terminal_integrity": {
            "numerator": sum(
                event.event_type == "action_span"
                and event.action_phase
                in {
                    "committed",
                    "cancelled",
                    "no_change",
                    "interrupted",
                }
                for event in ordered
            ),
            "denominator": denominator,
            "value": (
                sum(
                    event.event_type == "action_span"
                    and event.action_phase
                    in {
                        "committed",
                        "cancelled",
                        "no_change",
                        "interrupted",
                    }
                    for event in ordered
                )
                / denominator
                if denominator
                else 0.0
            ),
            "threshold": 1.0,
            "status": (
                "pass"
                if all(
                    event.action_phase
                    in {"committed", "cancelled", "no_change", "interrupted"}
                    for event in actions
                )
                else "fail"
            ),
            "affected_event_types": ["action_span"],
            "exclusion_reason": (
                "missing_terminal_phase"
                if any(event.action_phase == "started" for event in actions)
                else None
            ),
        },
        "sequence_continuity": {
            "numerator": max(0, len(sequence_events) - sequence_gaps),
            "denominator": len(sequence_events),
            "value": (
                max(0, len(sequence_events) - sequence_gaps)
                / len(sequence_events)
                if sequence_events
                else 1.0
            ),
            "threshold": 1.0,
            "status": "pass" if sequence_gaps == 0 else "fail",
            "affected_event_types": ["all_v3"],
            "exclusion_reason": "sequence_gap" if sequence_gaps else None,
        },
        "legacy_ordering_share": {
            "numerator": legacy_count,
            "denominator": len(ordered),
            "value": legacy_count / len(ordered) if ordered else 0.0,
            "threshold": None,
            "status": "diagnostic",
            "affected_event_types": ["schema_v1", "schema_v2"],
            "exclusion_reason": "legacy_ordering" if legacy_count else None,
        },
        "manifest_completeness": {
            "numerator": 0,
            "denominator": 0,
            "value": None,
            "threshold": 1.0,
            "status": "diagnostic",
            "affected_event_types": ["manifest"],
            "exclusion_reason": "manifest_quality_supplied_by_reader",
        },
        "export_completeness": {
            "numerator": 0,
            "denominator": 0,
            "value": None,
            "threshold": 1.0,
            "status": "unavailable",
            "affected_event_types": ["manifest", "export_tables"],
            "exclusion_reason": "manifest_quality_supplied_by_reader",
        },
        "unattributed_active_time": {
            "numerator": unattributed_ms,
            "denominator": wall_ms,
            "value": unattributed_ms / wall_ms if wall_ms else 0.0,
            "threshold": None,
            "status": "diagnostic",
            "affected_event_types": ["object_episode"],
            "exclusion_reason": None,
        },
        "truncation": {
            "numerator": 0,
            "denominator": len(ordered),
            "value": 0.0,
            "threshold": 0.0,
            "status": "diagnostic",
            "affected_event_types": ["export_tables"],
            "exclusion_reason": "applied_during_bundle_export",
        },
        "table_effective_samples": {
            "numerator": {
                "action": len(actions),
                "episode": episode_samples,
                "object": object_samples,
                "image": image_samples,
            },
            "denominator": len(ordered),
            "value": None,
            "threshold": None,
            "status": "diagnostic",
            "affected_event_types": ["all"],
            "exclusion_reason": "table_specific_denominators",
        },
    }
    for name, item in metrics.items():
        if name in {"action_duration", "action_duration_coverage"}:
            item["available"] = denominator > 0
        elif name in {
            "object_cycle",
            "episode_closure_rate",
            "focused_active",
        }:
            item["available"] = episode_samples > 0
        elif name in {"comparison_context", "context_coverage"}:
            item["available"] = context_count > 0
        elif name == "sequence_continuity":
            item["available"] = bool(sequence_events)
        else:
            item.setdefault("available", item["status"] != "unavailable")
    return {
        "metrics": metrics,
        "quality_gate": all(
            metrics[name]["status"] == "pass"
            for name in (
                "action_duration_coverage",
                "episode_closure_rate",
                "terminal_integrity",
                "sequence_continuity",
            )
        ),
    }


def feature_comparisons(
    events: Iterable[EventEnvelope],
    *,
    min_samples: int = 30,
) -> list[dict[str, object]]:
    """Compare feature state groups only when a complete control exists."""
    replay = replay_events(events)
    states = {
        int(version): state
        for version, state in replay["feature_states"].items()
    }
    samples: defaultdict[tuple[str, str, str], list[EventEnvelope]] = (
        defaultdict(list)
    )
    for event in semantic_actions(events):
        state = states.get(event.feature_state_version)
        if not isinstance(state, dict):
            continue
        for key, value in state.items():
            if not isinstance(value, dict):
                continue
            for dimension in ("configured", "active", "used"):
                if dimension in value:
                    group = str(bool(value[dimension])).lower()
                    samples[(key, dimension, group)].append(event)
    features = sorted({key for key, _, _ in samples})
    rows = []
    for feature in features:
        for dimension in ("configured", "active", "used"):
            groups = {
                group: samples[(feature, dimension, group)]
                for group in ("false", "true")
            }
            if not groups["false"] or not groups["true"]:
                reason = "missing_control_group"
            elif (
                len(groups["false"]) < min_samples
                or len(groups["true"]) < min_samples
            ):
                reason = "insufficient_samples"
            else:
                reason = None
            row: dict[str, object] = {
                "feature_key": feature,
                "state_dimension": dimension,
                "comparison_unavailable": reason,
                "minimum_samples": min_samples,
                "observational": True,
                "groups": {},
            }
            for group, group_events in groups.items():
                values = [
                    value
                    for event in group_events
                    if (value := event.effective_duration_ms) is not None
                ]
                row["groups"][group] = {
                    "sample_count": len(group_events),
                    "duration_coverage": (
                        len(values) / len(group_events)
                        if group_events
                        else 0.0
                    ),
                    "duration": duration_summary(values),
                }
            if reason is None:
                means = [
                    row["groups"][group]["duration"]["mean_ms"]
                    for group in ("false", "true")
                ]
                row["difference"] = means[1] - means[0]
            else:
                row["difference"] = None
            rows.append(row)
    return rows
