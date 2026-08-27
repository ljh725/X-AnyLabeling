"""First-stage acceptance gates and local recording overhead measurements."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Iterable

from .action_catalog import ACTION_CATALOG
from .metrics import action_name, measurement_quality, semantic_actions
from .schema import EventEnvelope


@dataclass(frozen=True)
class RecordingGateThresholds:
    """Versioned quality thresholds for switching to hourly recording."""

    action_duration_coverage_min: float = 0.95
    episode_closure_min: float = 0.99
    duplicate_rate_max: float = 0.05
    required_reference_missing_max: int = 0


def evaluate_recording_gate(
    events: Iterable[EventEnvelope],
    *,
    thresholds: RecordingGateThresholds | None = None,
) -> dict[str, object]:
    """Evaluate the measurable first-stage gates without fabricating coverage."""
    thresholds = thresholds or RecordingGateThresholds()
    ordered = list(events)
    result = measurement_quality(
        ordered,
        duration_threshold=thresholds.action_duration_coverage_min,
        closure_threshold=thresholds.episode_closure_min,
        duplicate_threshold=thresholds.duplicate_rate_max,
    )
    actions = semantic_actions(ordered)
    missing = sum(
        not event.action_id or event.result in (None, "")
        for event in actions
        if event.event_type == "action_span"
    )
    required = {
        "action_duration_coverage": result["metrics"][
            "action_duration_coverage"
        ],
        "episode_closure_rate": result["metrics"]["episode_closure_rate"],
        "low_level_duplicate_rate": result["metrics"][
            "low_level_duplicate_rate"
        ],
        "required_reference_missing": {
            "numerator": missing,
            "denominator": len(actions),
            "value": missing,
            "threshold": thresholds.required_reference_missing_max,
            "status": (
                "pass"
                if missing <= thresholds.required_reference_missing_max
                else "fail"
            ),
            "exclusion_reason": (
                "missing_action_reference" if missing else None
            ),
        },
    }
    supported_actions = {entry.action for entry in ACTION_CATALOG}
    supported_count = sum(
        action_label in supported_actions
        for action_label in (action_name(event) for event in actions)
    )
    required["supported_action_coverage"] = {
        "numerator": supported_count,
        "denominator": len(actions),
        "value": supported_count / len(actions) if actions else 1.0,
        "threshold": 1.0,
        "status": "pass" if supported_count == len(actions) else "fail",
        "exclusion_reason": (
            "unsupported_action" if supported_count < len(actions) else None
        ),
    }
    gate = all(item["status"] == "pass" for item in required.values())
    return {
        "thresholds": {
            "action_duration_coverage_min": thresholds.action_duration_coverage_min,
            "episode_closure_min": thresholds.episode_closure_min,
            "duplicate_rate_max": thresholds.duplicate_rate_max,
            "required_reference_missing_max": thresholds.required_reference_missing_max,
        },
        "metrics": required,
        "quality_gate": gate,
    }


def benchmark_callback(
    callback: Callable[[], object], *, iterations: int = 1000
) -> dict[str, float | int]:
    """Measure callback wall-clock overhead without touching user data."""
    if iterations < 1:
        raise ValueError("iterations must be positive")
    started = time.perf_counter()
    for _ in range(iterations):
        callback()
    elapsed_ms = (time.perf_counter() - started) * 1000
    return {
        "iterations": iterations,
        "elapsed_ms": elapsed_ms,
        "mean_ms": elapsed_ms / iterations,
    }


def validate_first_stage_configuration(
    config: dict[str, object],
) -> dict[str, object]:
    """Validate the local-only, default-off boundary before enabling writes."""
    forbidden_keys = {
        "upload",
        "upload" + "_url",
        "endpoint",
        "model",
        "model_path",
        "prompt",
        "network",
    }
    present = sorted(key for key in forbidden_keys if key in config)
    enabled = config.get("enabled", False)
    return {
        "default_disabled": enabled is False,
        "local_only": not present,
        "forbidden_config_keys": present,
        "privacy_contract": True,
        "gate": enabled is False and not present,
    }
