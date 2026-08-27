"""Reproducible event fixtures and bounded performance measurements."""

from __future__ import annotations

import json
import time
import tracemalloc
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Iterator

from .schema import EventEnvelope
from .streaming import stream_calculate_statistics


@dataclass(frozen=True)
class BenchmarkThresholds:
    """Default local acceptance thresholds for the recording/export path."""

    max_mean_enqueue_ms: float = 1.0
    max_peak_memory_bytes: int = 256 * 1024 * 1024
    max_open_sources: int = 64
    max_cancel_batch: int = 256

    def to_dict(self) -> dict[str, int | float]:
        """Return the recorded local acceptance thresholds."""
        return {
            "max_mean_enqueue_ms": self.max_mean_enqueue_ms,
            "max_peak_memory_bytes": self.max_peak_memory_bytes,
            "max_open_sources": self.max_open_sources,
            "max_cancel_batch": self.max_cancel_batch,
        }


def generate_events(
    count: int, *, sessions: int = 2, start_sequence: int = 1
) -> Iterator[EventEnvelope]:
    """Yield deterministic v3 events for 1k/100k/1M scale fixtures."""
    if count < 0 or sessions < 1:
        raise ValueError("count must be non-negative and sessions positive")
    for index in range(count):
        session_index = index % sessions
        sequence = start_sequence + index // sessions
        session_id = f"benchmark-app-{session_index}"
        project_id = f"benchmark-project-{session_index}"
        event_time = datetime(2026, 8, 21, tzinfo=timezone.utc) + timedelta(
            minutes=index // 1000
        )
        event_type = (
            "project_session_started",
            "image_visit_started",
            "shape_created",
            "action_span",
            "action_span",
            "shape_saved",
            "shape_deleted",
            "image_visit_ended",
        )[index % 8]
        action = "geometry_adjust" if index % 8 == 3 else "undo"
        episode_id = f"benchmark-episode-{index // 8:09d}"
        payload = {"action": action} if event_type == "action_span" else {}
        fields = {
            "image_id": f"benchmark-image-{index // 8:09d}",
            "shape_id": f"benchmark-shape-{index // 8:09d}",
            "object_episode_id": episode_id,
        }
        if event_type == "action_span":
            fields.update(
                {
                    "action_id": f"benchmark-action-{index:09d}",
                    "action_phase": "committed",
                    "action_type": action,
                    "started_monotonic_ms": index,
                    "ended_monotonic_ms": index + 1,
                }
            )
        yield EventEnvelope.from_mapping(
            {
                "schema_version": 3,
                "event_id": f"benchmark-{index:09d}",
                "event_type": event_type,
                "occurred_at_utc": event_time.isoformat(
                    timespec="milliseconds"
                ).replace("+00:00", "Z"),
                "local_date": event_time.date().isoformat(),
                "timezone_offset": "+00:00",
                "monotonic_ms": index,
                "app_session_id": session_id,
                "project_session_id": project_id,
                "project_id": project_id,
                "feature_state_version": 1,
                "input_source": "system",
                "result": "success",
                "sequence_no": sequence,
                "payload": payload,
                **fields,
            }
        )


def write_fixture(path: str | Path, count: int, *, sessions: int = 2) -> Path:
    """Write one deterministic JSONL fixture without changing source logs."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as stream:
        for event in generate_events(count, sessions=sessions):
            stream.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
    return target


def benchmark_stream(
    events: Iterable[EventEnvelope],
    *,
    batch_size: int = 256,
    cancellation_after: int | None = None,
) -> dict[str, object]:
    """Measure streaming time, peak traced memory and cancellation boundary."""
    processed = 0
    thresholds = BenchmarkThresholds()
    cancel_requested = False
    tracemalloc.start()
    started = time.perf_counter()

    def on_batch(batch_count: int) -> None:
        """Track bounded batch progress."""
        nonlocal processed
        processed += batch_count

    def cancel() -> bool:
        """Stop only at a configured batch boundary."""
        nonlocal cancel_requested
        if cancellation_after is not None and processed >= cancellation_after:
            cancel_requested = True
            return True
        return False

    result = stream_calculate_statistics(
        events,
        batch_size=batch_size,
        on_batch=on_batch,
        cancel=cancel if cancellation_after is not None else None,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    _, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "processed_events": processed,
        "reported_event_count": result["event_count"],
        "elapsed_ms": elapsed_ms,
        "mean_event_ms": elapsed_ms / processed if processed else 0.0,
        "peak_memory_bytes": peak_memory,
        "cancelled": cancel_requested,
        "batch_size": batch_size,
        "thresholds": thresholds.to_dict(),
    }


def benchmark_recording_callback(
    callback: Callable[[], object], *, iterations: int = 1000
) -> dict[str, float | int]:
    """Measure enabled/disabled recorder callback overhead."""
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
