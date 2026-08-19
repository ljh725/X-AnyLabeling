"""Local, fail-open metrics for rectangle review refinement."""

from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from statistics import mean, median
from typing import Any, Callable, Iterable

DEFAULT_IDLE_TIMEOUT_SECONDS = 30.0
DEFAULT_ZOOM_BURST_SECONDS = 0.3
DEFAULT_REVERSAL_DEADBAND_PX = 0.5
DEFAULT_REVERSAL_CONFIRM_PX = 1.0
SCHEMA_VERSION = 1


class FeatureStage(str, Enum):
    """Feature rollout labels attached to each completed episode."""

    BASELINE = "baseline"
    P0_GAIN = "p0_gain"
    P0_NUDGE = "p0_nudge"
    P1_FEEDBACK = "p1_feedback"
    P1_CONTINUITY = "p1_continuity"
    P2_ASSISTANCE = "p2_assistance"


class EpisodeEndReason(str, Enum):
    """Reasons why the current single-rectangle episode ended."""

    TARGET_CHANGED = "target_changed"
    IMAGE_CHANGED = "image_changed"
    SESSION_ENDED = "session_ended"
    APPLICATION_CLOSED = "application_closed"
    TARGET_CLEARED = "target_cleared"


@dataclass(frozen=True)
class ReviewEpisodeRecord:
    """Serializable, privacy-minimized metrics for one review episode."""

    schema_version: int
    app_version: str
    session_id: str
    episode_id: str
    target_token: str
    feature_stage: str
    feature_flags: dict[str, bool]
    started_at_utc: str
    ended_at_utc: str
    end_reason: str
    wall_elapsed_ms: int
    focused_elapsed_ms: int
    active_elapsed_ms: int
    edited: bool
    zoom_action_count: int
    zoom_step_count: int
    drag_reversal_count: int
    undo_count: int

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible dictionary without private fields."""
        return asdict(self)


@dataclass
class _ZoomCounter:
    """Count zoom action bursts and normalized steps."""

    burst_seconds: float = DEFAULT_ZOOM_BURST_SECONDS
    last_timestamp: float | None = None
    action_count: int = 0
    step_count: int = 0

    def record(self, timestamp: float, steps: int) -> None:
        """Record actual zoom steps at ``timestamp``."""
        count = abs(int(steps))
        if count == 0:
            return
        if (
            self.last_timestamp is None
            or timestamp - self.last_timestamp > self.burst_seconds
        ):
            self.action_count += 1
        self.step_count += count
        self.last_timestamp = timestamp


@dataclass
class _ReversalDetector:
    """Count deliberate sign changes while ignoring pointer jitter."""

    deadband_px: float = DEFAULT_REVERSAL_DEADBAND_PX
    confirm_px: float = DEFAULT_REVERSAL_CONFIRM_PX
    confirmed_sign: int | None = None
    pending_sign: int | None = None
    pending_magnitude: float = 0.0
    reversal_count: int = 0

    def reset(self) -> None:
        """Reset state at the beginning of every edge drag."""
        self.confirmed_sign = None
        self.pending_sign = None
        self.pending_magnitude = 0.0

    def record(self, axis_delta: float) -> None:
        """Record an accepted axis delta and update reversal count."""
        magnitude = abs(float(axis_delta))
        if not math.isfinite(magnitude) or magnitude < self.deadband_px:
            return
        sign = 1 if axis_delta > 0 else -1
        if self.confirmed_sign is None:
            self._accumulate_pending(sign, magnitude)
            if self.pending_magnitude >= self.confirm_px:
                self.confirmed_sign = sign
                self.pending_sign = None
                self.pending_magnitude = 0.0
            return
        if sign == self.confirmed_sign:
            self.pending_sign = None
            self.pending_magnitude = 0.0
            return
        self._accumulate_pending(sign, magnitude)
        if self.pending_magnitude >= self.confirm_px:
            self.reversal_count += 1
            self.confirmed_sign = sign
            self.pending_sign = None
            self.pending_magnitude = 0.0

    def _accumulate_pending(self, sign: int, magnitude: float) -> None:
        """Accumulate a candidate direction until it is confirmed."""
        if self.pending_sign != sign:
            self.pending_sign = sign
            self.pending_magnitude = 0.0
        self.pending_magnitude += magnitude


class JsonlMetricsWriter:
    """Append episode records to a local JSONL file without blocking UI."""

    def __init__(
        self,
        path: str | Path,
        warning_callback: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize a fail-open writer for ``path``."""
        self.path = Path(path)
        self.warning_callback = warning_callback
        self.failed = False
        self._warned = False

    def append(self, record: ReviewEpisodeRecord) -> bool:
        """Append one record and return whether it was persisted."""
        if self.failed:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                record.to_dict(), ensure_ascii=False, separators=(",", ":")
            )
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(payload + "\n")
                stream.flush()
            return True
        except (OSError, TypeError, ValueError) as exc:
            self.failed = True
            self._warn_once(f"Rectangle review metrics disabled: {exc}")
            return False

    def _warn_once(self, message: str) -> None:
        """Send at most one non-blocking warning to the host UI."""
        if self._warned:
            return
        self._warned = True
        if self.warning_callback is not None:
            self.warning_callback(message)


@dataclass
class _EpisodeState:
    """Mutable internal state for one active episode."""

    target_token: str
    feature_stage: str
    feature_flags: dict[str, bool]
    started_mono: float
    started_focused_total: float
    started_at_utc: str
    episode_id: str
    edited: bool = False
    focused: bool = True
    focus_started_mono: float | None = None
    focused_accumulated: float = 0.0
    last_activity_focused_total: float = 0.0
    active_elapsed: float = 0.0
    zoom: _ZoomCounter = field(default_factory=_ZoomCounter)
    reversal: _ReversalDetector = field(default_factory=_ReversalDetector)
    undo_count: int = 0


class ReviewEpisodeCollector:
    """Collect one selected-rectangle episode with an injectable clock."""

    def __init__(
        self,
        writer: JsonlMetricsWriter | None = None,
        *,
        app_version: str = "unknown",
        enabled: bool = False,
        idle_timeout_seconds: float = DEFAULT_IDLE_TIMEOUT_SECONDS,
        zoom_burst_seconds: float = DEFAULT_ZOOM_BURST_SECONDS,
        reversal_deadband_px: float = DEFAULT_REVERSAL_DEADBAND_PX,
        reversal_confirm_px: float = DEFAULT_REVERSAL_CONFIRM_PX,
        monotonic: Callable[[], float] | None = None,
        utc_now: Callable[[], datetime] | None = None,
        session_id: str | None = None,
    ) -> None:
        """Initialize a collector that is safe to use from UI callbacks."""
        self.writer = writer
        self.app_version = app_version
        self.enabled = bool(enabled)
        self.idle_timeout_seconds = max(float(idle_timeout_seconds), 0.0)
        self.zoom_burst_seconds = max(float(zoom_burst_seconds), 0.0)
        self.reversal_deadband_px = max(float(reversal_deadband_px), 0.0)
        self.reversal_confirm_px = max(float(reversal_confirm_px), 0.0)
        self._monotonic = monotonic or time.monotonic
        self._utc_now = utc_now or (lambda: datetime.now(timezone.utc))
        self.session_id = session_id or uuid.uuid4().hex
        self._state: _EpisodeState | None = None
        self.last_record: ReviewEpisodeRecord | None = None

    def target_selected(
        self,
        target_token: str,
        feature_stage: str | FeatureStage = FeatureStage.BASELINE,
        feature_flags: dict[str, bool] | None = None,
    ) -> None:
        """Start an episode for a sole selected rectangle."""
        if not self.enabled:
            return
        if self._state is not None:
            self.finish(EpisodeEndReason.TARGET_CHANGED)
        now = self._monotonic()
        focused_total = 0.0
        self._state = _EpisodeState(
            target_token=str(target_token),
            feature_stage=_enum_value(feature_stage),
            feature_flags=dict(feature_flags or {}),
            started_mono=now,
            started_focused_total=focused_total,
            started_at_utc=self._utc_now().isoformat(),
            episode_id=uuid.uuid4().hex,
            focus_started_mono=now,
            last_activity_focused_total=focused_total,
            zoom=_ZoomCounter(self.zoom_burst_seconds),
            reversal=_ReversalDetector(
                self.reversal_deadband_px, self.reversal_confirm_px
            ),
        )

    def target_cleared(self, reason: str | EpisodeEndReason) -> None:
        """Finish the active episode for a target or image lifecycle change."""
        if self._state is not None:
            self.finish(reason)

    def focus_changed(self, is_active: bool) -> None:
        """Pause focused-time accounting when the host window loses focus."""
        state = self._state
        if state is None or state.focused == bool(is_active):
            return
        now = self._monotonic()
        if state.focused:
            if state.focus_started_mono is not None:
                state.focused_accumulated += max(
                    now - state.focus_started_mono, 0.0
                )
            state.focus_started_mono = None
        else:
            state.focus_started_mono = now
        state.focused = bool(is_active)

    def review_input(self, timestamp: float | None = None) -> None:
        """Record a meaningful focused input for active-time accounting."""
        state = self._state
        if state is None or not state.focused:
            return
        now = self._monotonic() if timestamp is None else float(timestamp)
        focused_total = self._focused_total(now)
        delta = max(focused_total - state.last_activity_focused_total, 0.0)
        state.active_elapsed += min(delta, self.idle_timeout_seconds)
        state.last_activity_focused_total = focused_total

    def zoom_applied(self, normalized_steps: int) -> None:
        """Record actual main-canvas zoom changes only."""
        state = self._state
        if state is None:
            return
        now = self._monotonic()
        state.zoom.record(now, normalized_steps)
        self.review_input(now)

    def edge_drag_started(self, edge_token: str) -> None:
        """Reset direction tracking for a new edge drag."""
        del edge_token
        state = self._state
        if state is None:
            return
        state.reversal.reset()
        self.review_input()

    def edge_drag_sample(self, accepted_axis_delta: float) -> None:
        """Record an accepted axis delta from the geometry layer."""
        state = self._state
        if state is None:
            return
        state.reversal.record(accepted_axis_delta)
        self.review_input()

    def edge_drag_finished(self, committed: bool) -> None:
        """Finish an edge drag and mark the episode edited when committed."""
        state = self._state
        if state is None:
            return
        if committed:
            state.edited = True
        self.review_input()

    def undo_applied(
        self,
        target_token: str,
        geometry_changed: bool,
    ) -> None:
        """Count an undo only when it changed the current target geometry."""
        state = self._state
        if state is None:
            return
        if geometry_changed and str(target_token) == state.target_token:
            state.undo_count += 1
        self.review_input()

    def finish(
        self, reason: str | EpisodeEndReason
    ) -> ReviewEpisodeRecord | None:
        """Finalize, optionally persist, and return the active episode record."""
        state = self._state
        if state is None:
            return None
        now = self._monotonic()
        focused_elapsed = self._focused_total(now)
        wall_elapsed = max(now - state.started_mono, 0.0)
        record = ReviewEpisodeRecord(
            schema_version=SCHEMA_VERSION,
            app_version=self.app_version,
            session_id=self.session_id,
            episode_id=state.episode_id,
            target_token=state.target_token,
            feature_stage=state.feature_stage,
            feature_flags=dict(state.feature_flags),
            started_at_utc=state.started_at_utc,
            ended_at_utc=self._utc_now().isoformat(),
            end_reason=_enum_value(reason),
            wall_elapsed_ms=int(round(wall_elapsed * 1000)),
            focused_elapsed_ms=int(round(focused_elapsed * 1000)),
            active_elapsed_ms=int(round(state.active_elapsed * 1000)),
            edited=state.edited,
            zoom_action_count=state.zoom.action_count,
            zoom_step_count=state.zoom.step_count,
            drag_reversal_count=state.reversal.reversal_count,
            undo_count=state.undo_count,
        )
        self.last_record = record
        self._state = None
        if self.writer is not None:
            self.writer.append(record)
        return record

    def _focused_total(self, now: float) -> float:
        """Return focused seconds accumulated by the active episode."""
        state = self._state
        if state is None:
            return 0.0
        total = state.focused_accumulated
        if state.focused and state.focus_started_mono is not None:
            total += max(now - state.focus_started_mono, 0.0)
        return total


def read_records(path: str | Path) -> tuple[list[dict[str, Any]], int]:
    """Read valid JSONL records and return ``(records, skipped_count)``."""
    records: list[dict[str, Any]] = []
    skipped = 0
    try:
        stream = Path(path).open("r", encoding="utf-8")
    except OSError:
        return records, 0
    with stream:
        for line in stream:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                skipped += 1
                continue
            if not isinstance(value, dict) or value.get("schema_version") != 1:
                skipped += 1
                continue
            records.append(value)
    return records, skipped


def _enum_value(value: str | Enum) -> str:
    """Return the wire value for a string-like enum or plain string."""
    return str(getattr(value, "value", value))


def aggregate_records(
    records: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate valid episode records by feature stage."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        stage = str(record.get("feature_stage", "unknown"))
        grouped.setdefault(stage, []).append(record)
    result: list[dict[str, Any]] = []
    for stage in sorted(grouped):
        items = grouped[stage]
        result.append(
            {
                "feature_stage": stage,
                "episode_count": len(items),
                **_summary_stats(items, "wall_elapsed_ms", "wall_elapsed_ms"),
                **_summary_stats(
                    items, "active_elapsed_ms", "active_elapsed_ms"
                ),
                **_summary_stats(items, "zoom_action_count", "zoom_actions"),
                **_summary_stats(items, "zoom_step_count", "zoom_steps"),
                **_summary_stats(
                    items, "drag_reversal_count", "drag_reversals"
                ),
                **_summary_stats(items, "undo_count", "undos"),
            }
        )
    return result


def _numeric_values(
    records: Iterable[dict[str, Any]], key: str
) -> list[float]:
    """Extract finite numeric values for aggregation."""
    values: list[float] = []
    for record in records:
        try:
            value = float(record[key])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(value):
            values.append(value)
    return values


def _mean(records: Iterable[dict[str, Any]], key: str) -> float:
    """Return a rounded mean or zero for an empty sample."""
    values = _numeric_values(records, key)
    return round(mean(values), 3) if values else 0.0


def _summary_stats(
    records: Iterable[dict[str, Any]], key: str, prefix: str
) -> dict[str, float]:
    """Return count, mean, median and p75 for one numeric metric."""
    values = sorted(_numeric_values(records, key))
    if not values:
        return {
            f"{prefix}_count": 0,
            f"{prefix}_mean": 0.0,
            f"{prefix}_median": 0.0,
            f"{prefix}_p75": 0.0,
        }
    return {
        f"{prefix}_count": len(values),
        f"{prefix}_mean": round(mean(values), 3),
        f"{prefix}_median": round(median(values), 3),
        f"{prefix}_p75": _percentile(records, key, 0.75),
    }


def _percentile(
    records: Iterable[dict[str, Any]], key: str, quantile: float
) -> float:
    """Return a nearest-rank percentile or zero for an empty sample."""
    values = sorted(_numeric_values(records, key))
    if not values:
        return 0.0
    index = min(max(math.ceil(quantile * len(values)) - 1, 0), len(values) - 1)
    return round(median([values[index]]), 3)
