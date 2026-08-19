"""Tests for local rectangle review refinement metrics."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from anylabeling.views.labeling.review_refinement.metrics import (
    EpisodeEndReason,
    FeatureStage,
    JsonlMetricsWriter,
    ReviewEpisodeCollector,
    aggregate_records,
    read_records,
)


class FakeClock:
    """Small deterministic clock for episode tests."""

    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        """Return the current fake monotonic time."""
        return self.value

    def utc_now(self) -> datetime:
        """Return a deterministic UTC wall time."""
        return datetime.fromtimestamp(self.value, tz=timezone.utc)

    def advance(self, seconds: float) -> None:
        """Advance fake time."""
        self.value += seconds


def _collector(clock: FakeClock, writer=None) -> ReviewEpisodeCollector:
    """Create an enabled collector with deterministic thresholds."""
    return ReviewEpisodeCollector(
        writer=writer,
        app_version="test",
        enabled=True,
        monotonic=clock.monotonic,
        utc_now=clock.utc_now,
        idle_timeout_seconds=30.0,
        session_id="session",
    )


def test_episode_records_time_zoom_reversal_and_undo(tmp_path) -> None:
    """One episode exposes all four requested review metrics."""
    clock = FakeClock()
    path = tmp_path / "metrics.jsonl"
    collector = _collector(clock, JsonlMetricsWriter(path))
    collector.target_selected("target-1", FeatureStage.BASELINE)

    clock.advance(2.0)
    collector.review_input()
    collector.zoom_applied(3)
    clock.advance(0.1)
    collector.zoom_applied(2)
    collector.edge_drag_started("left")
    collector.edge_drag_sample(1.0)
    collector.edge_drag_sample(-0.5)
    collector.edge_drag_sample(-0.5)
    collector.edge_drag_finished(True)
    collector.undo_applied("target-1", True)
    clock.advance(1.0)

    record = collector.finish(EpisodeEndReason.TARGET_CHANGED)

    assert record is not None
    assert record.end_reason == "target_changed"
    assert record.feature_stage == "baseline"
    assert record.wall_elapsed_ms == 3100
    assert record.zoom_action_count == 1
    assert record.zoom_step_count == 5
    assert record.drag_reversal_count == 1
    assert record.undo_count == 1
    assert record.edited is True

    lines = path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[0])
    assert payload["schema_version"] == 1
    assert "target-1" in payload["target_token"]
    assert "label" not in payload
    assert "points" not in payload


def test_focus_time_is_excluded_and_idle_time_is_capped() -> None:
    """Focused and active durations exclude focus loss and long idle gaps."""
    clock = FakeClock()
    collector = _collector(clock)
    collector.target_selected("target")
    clock.advance(2.0)
    collector.review_input()
    collector.focus_changed(False)
    clock.advance(10.0)
    collector.focus_changed(True)
    clock.advance(40.0)
    collector.review_input()

    record = collector.finish(EpisodeEndReason.SESSION_ENDED)

    assert record is not None
    assert record.wall_elapsed_ms == 52000
    assert record.focused_elapsed_ms == 42000
    assert record.active_elapsed_ms == 32000


def test_reversal_detector_ignores_subpixel_jitter() -> None:
    """Tiny direction changes must not inflate correction counts."""
    clock = FakeClock()
    collector = _collector(clock)
    collector.target_selected("target")
    collector.edge_drag_started("left")
    collector.edge_drag_sample(0.4)
    collector.edge_drag_sample(-0.4)
    collector.edge_drag_sample(1.0)
    collector.edge_drag_sample(-0.4)
    collector.edge_drag_sample(-0.4)
    record = collector.finish(EpisodeEndReason.TARGET_CLEARED)

    assert record is not None
    assert record.drag_reversal_count == 0


def test_reader_skips_corrupt_lines_and_aggregates_stage(tmp_path) -> None:
    """A bad JSONL line does not prevent valid stage aggregation."""
    path = tmp_path / "metrics.jsonl"
    writer = JsonlMetricsWriter(path)
    clock = FakeClock()
    collector = _collector(clock, writer)
    collector.target_selected("target", FeatureStage.P0_GAIN)
    clock.advance(1.0)
    collector.review_input()
    collector.finish(EpisodeEndReason.APPLICATION_CLOSED)
    with path.open("a", encoding="utf-8") as stream:
        stream.write("not-json\n")

    records, skipped = read_records(path)
    summary = aggregate_records(records)

    assert len(records) == 1
    assert skipped == 1
    assert summary[0]["feature_stage"] == "p0_gain"
    assert summary[0]["episode_count"] == 1
    assert summary[0]["wall_elapsed_ms_count"] == 1
    assert summary[0]["drag_reversals_p75"] == 0.0


def test_disabled_collector_does_not_write(tmp_path) -> None:
    """Metrics are opt-in and create no file while disabled."""
    path = tmp_path / "disabled.jsonl"
    collector = ReviewEpisodeCollector(
        writer=JsonlMetricsWriter(path), enabled=False
    )
    collector.target_selected("target")
    assert collector.finish(EpisodeEndReason.TARGET_CLEARED) is None
    assert not path.exists()
