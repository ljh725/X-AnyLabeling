"""Tests for high-frequency aggregation and local log cleanup."""

import json

from anylabeling.services.behavior_analytics import (
    BurstAggregator,
    LocalEventRecorder,
    cleanup_event_logs,
)


def test_burst_aggregator_groups_adjacent_inputs_and_flushes_boundaries():
    """Different actions and silence windows close exactly one burst."""
    aggregator = BurstAggregator(silence_ms=300)
    assert aggregator.add("zoom", "wheel", 100) == []
    assert aggregator.add("zoom", "wheel", 200) == []
    completed = aggregator.add("zoom", "wheel", 500)
    assert completed == []
    completed = aggregator.add("pan", "wheel", 800)
    assert completed[0].input_count == 3
    assert completed[0].duration_ms == 400
    final = aggregator.flush()
    assert [(item.action, item.input_count) for item in final] == [("pan", 1)]


def test_cleanup_supports_project_scope_without_touching_other_files(tmp_path):
    """Explicit cleanup removes matching events and leaves annotation files."""
    event_dir = tmp_path / "events"
    event_dir.mkdir()
    event_path = event_dir / "events-2026-08.jsonl"
    rows = [
        {
            "project_id": "project-a",
            "occurred_at_utc": "2026-08-01T00:00:00.000Z",
            "event_type": "action_span",
        },
        {
            "project_id": "project-b",
            "occurred_at_utc": "2026-08-01T00:00:00.000Z",
            "event_type": "action_span",
        },
    ]
    event_path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    annotation_path = tmp_path / "annotation.json"
    annotation_path.write_text("keep", encoding="utf-8")

    summary = cleanup_event_logs(
        tmp_path, project_ids={"project-a"}, start_utc="2026-01-01"
    )
    assert summary.events_removed == 1
    remaining = event_path.read_text(encoding="utf-8")
    assert "project-a" not in remaining
    assert "project-b" in remaining
    assert annotation_path.read_text(encoding="utf-8") == "keep"


def test_recorder_exposes_explicit_cleanup_api(tmp_path):
    """The recorder forwards cleanup without requiring an active worker."""
    assert isinstance(
        LocalEventRecorder.cleanup(
            tmp_path, project_ids={"missing"}
        ).files_scanned,
        int,
    )
