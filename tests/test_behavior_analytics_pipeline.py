"""Tests for the two-stage range, streaming and quality contracts."""

import json
from pathlib import Path

from anylabeling.services.behavior_analytics import (
    DualRangeSelection,
    EventEnvelope,
    MonoInterval,
    UtcRange,
    build_range_selection,
    benchmark_stream,
    benchmark_recording_callback,
    BenchmarkThresholds,
    candidate_event_files,
    ComparisonConfig,
    compare_ranges,
    evaluate_recording_gate,
    episode_time_decomposition,
    intersect_intervals,
    normalize_intervals,
    read_events,
    subtract_intervals,
    stream_calculate_statistics,
    time_contribution_metrics,
    collect_trace_candidates,
    extract_trace_events,
    select_trace_candidates,
    validate_first_stage_configuration,
    workflow_stage_metrics,
)

FIXTURES = Path("tests/fixtures/behavior_analytics/two_stage")


def _event(event_id: str, sequence_no: int, when: str) -> EventEnvelope:
    """Build a minimal v3 event for stream contract tests."""
    return EventEnvelope.from_mapping(
        {
            "schema_version": 3,
            "event_id": event_id,
            "event_type": "project_session_started",
            "occurred_at_utc": when,
            "local_date": when[:10],
            "timezone_offset": "+00:00",
            "monotonic_ms": sequence_no * 100,
            "app_session_id": "app-test",
            "project_session_id": "project-test",
            "project_id": "project-anon",
            "feature_state_version": 1,
            "input_source": "system",
            "result": "success",
            "sequence_no": sequence_no,
            "payload": {},
        }
    )


def _action_event(event_id: str, sequence_no: int, when: str) -> EventEnvelope:
    """Build a timed semantic action for metric tests."""
    data = _event(event_id, sequence_no, when).to_dict()
    data.update(
        {
            "event_type": "action_span",
            "action_id": f"action-{event_id}",
            "action_phase": "committed",
            "action_type": "geometry_adjust",
            "started_monotonic_ms": sequence_no * 100,
            "ended_monotonic_ms": sequence_no * 100 + 50,
            "payload": {"action": "geometry_adjust"},
        }
    )
    return EventEnvelope.from_mapping(data)


def test_range_selection_converts_local_dst_and_rejects_missing_project():
    """Range requests preserve local input and resolve deterministic UTC."""
    selection = build_range_selection(
        "custom",
        timezone_name="Asia/Shanghai",
        local_start="2026-08-21T10:15:00",
        local_end="2026-08-21T12:30:00",
    )
    assert selection.utc.start_utc == "2026-08-21T02:15:00.000Z"
    assert selection.utc.end_utc == "2026-08-21T04:30:00.000Z"
    try:
        build_range_selection("current_project")
    except ValueError as exc:
        assert "active project" in str(exc)
    else:
        raise AssertionError("missing current project must reject export")


def test_shard_candidates_are_pruned_by_inclusive_range():
    """Only intersecting hourly and monthly sources are candidates."""
    paths = [
        FIXTURES / "hourly/events-2026-08-21-01.jsonl",
        FIXTURES / "dual_range/events-2026-08-21-05.jsonl",
        FIXTURES / "monthly/events-2026-08.jsonl",
    ]
    candidates = candidate_event_files(
        paths,
        UtcRange("2026-08-21T01:30:00Z", "2026-08-21T02:00:00Z"),
    )
    assert candidates == [paths[0], paths[2]]
    selected = UtcRange("2026-08-21T01:30:00Z", "2026-08-21T02:00:00Z")
    assert selected.contains("2026-08-21T01:30:00Z")
    assert selected.contains("2026-08-21T02:00:00Z")
    assert not selected.contains("2026-08-21T02:00:00.001Z")


def test_stream_deduplicates_sources_and_reports_sequence_gap(tmp_path):
    """Duplicate IDs are removed and v3 sequence gaps remain observable."""
    source = tmp_path / "events-2026-08-21-01.jsonl"
    rows = [
        _event("one", 1, "2026-08-21T01:00:00Z").to_dict(),
        _event("three", 3, "2026-08-21T01:00:02Z").to_dict(),
    ]
    source.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )
    duplicate = tmp_path / "events-2026-08-21-02.jsonl"
    duplicate.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
    events, quality = read_events([source, duplicate])
    assert [event.event_id for event in events] == ["one", "three"]
    assert quality.duplicate_source_count == 1
    assert quality.sequence_gap_count == 1


def test_interval_algebra_is_half_open_and_conserves_difference():
    """Overlapping intervals merge, while adjacency remains representable."""
    merged = normalize_intervals(
        [MonoInterval(0, 10), MonoInterval(5, 20), MonoInterval(20, 30)]
    )
    assert merged == [MonoInterval(0, 20), MonoInterval(20, 30)]
    assert intersect_intervals(merged, [MonoInterval(8, 22)]) == [
        MonoInterval(8, 20),
        MonoInterval(20, 22),
    ]


def test_episode_time_decomposition_conserves_wall_time():
    """Action, transition and unattributed intervals sum to wall time."""
    first = _action_event("one", 1, "2026-08-21T01:00:00Z").to_dict()
    first["object_episode_id"] = "episode-1"
    first["ended_monotonic_ms"] = 150
    second = _action_event("two", 2, "2026-08-21T01:00:01Z").to_dict()
    second["object_episode_id"] = "episode-1"
    second["started_monotonic_ms"] = 300
    second["ended_monotonic_ms"] = 350
    rows = episode_time_decomposition(
        [EventEnvelope.from_mapping(first), EventEnvelope.from_mapping(second)]
    )
    assert rows[0]["conservation_ok"] is True
    assert rows[0]["attribution_total_ms"] == rows[0]["wall_ms"]
    assert subtract_intervals(
        [MonoInterval(0, 30)], [MonoInterval(10, 20)]
    ) == [
        MonoInterval(0, 10),
        MonoInterval(20, 30),
    ]


def test_time_decomposition_handles_overlap_wait_transition_and_unclosed():
    """Overlapping classifications remain disjoint and unclosed is explicit."""
    first = _action_event("one", 1, "2026-08-21T01:00:00Z").to_dict()
    first.update(
        {
            "object_episode_id": "episode-overlap",
            "ended_monotonic_ms": 500,
            "payload": {"action": "geometry_adjust"},
        }
    )
    wait = _event("wait", 2, "2026-08-21T01:00:01Z").to_dict()
    wait.update(
        {
            "object_episode_id": "episode-overlap",
            "event_type": "idle_changed",
            "monotonic_ms": 400,
            "payload": {"idle": True},
        }
    )
    second = _action_event("two", 3, "2026-08-21T01:00:02Z").to_dict()
    second.update(
        {
            "object_episode_id": "episode-overlap",
            "monotonic_ms": 700,
            "started_monotonic_ms": 700,
            "ended_monotonic_ms": 750,
        }
    )
    rows = episode_time_decomposition(
        [EventEnvelope.from_mapping(row) for row in (first, wait, second)]
    )
    assert rows[0]["conservation_ok"] is True
    assert rows[0]["transition_gap_ms"] == 0
    assert rows[0]["unattributed_active_ms"] >= 0
    third = _action_event("three", 4, "2026-08-21T01:00:03Z").to_dict()
    third.update(
        {
            "object_episode_id": "episode-transition",
            "monotonic_ms": 100,
            "started_monotonic_ms": 100,
            "ended_monotonic_ms": 150,
        }
    )
    fourth = _action_event("four", 5, "2026-08-21T01:00:04Z").to_dict()
    fourth.update(
        {
            "object_episode_id": "episode-transition",
            "monotonic_ms": 300,
            "started_monotonic_ms": 300,
            "ended_monotonic_ms": 350,
        }
    )
    transition_row = episode_time_decomposition(
        [EventEnvelope.from_mapping(row) for row in (third, fourth)]
    )[0]
    assert transition_row["transition_gap_ms"] == 150


def test_two_pass_trace_selection_keeps_only_ids_in_first_pass():
    """Candidate ranking is separate from bounded second-pass extraction."""
    first = _action_event("one", 1, "2026-08-21T01:00:00Z").to_dict()
    first["object_episode_id"] = "episode-1"
    candidates = collect_trace_candidates([EventEnvelope.from_mapping(first)])
    selected = select_trace_candidates(candidates, limit=1)
    assert selected and selected[0][1] == "episode-1"
    traces = extract_trace_events(
        [EventEnvelope.from_mapping(first)], selected, max_events=1
    )
    assert traces[0]["event_count"] == 1


def test_stage_time_and_comparison_outputs_are_objective():
    """Stage and comparison rows expose facts and observational boundaries."""
    events = [
        _action_event("one", 1, "2026-08-21T01:00:00Z"),
        _action_event("two", 2, "2026-08-21T01:00:01Z"),
    ]
    assert isinstance(workflow_stage_metrics(events), list)
    assert isinstance(time_contribution_metrics(events), list)
    assert (
        compare_ranges(events, events, min_samples=30)[0]["observational"]
        is True
    )
    comparison = compare_ranges(
        events,
        events,
        config=ComparisonConfig(min_samples=30),
    )
    assert comparison[0]["comparison_config"]["algorithm_version"] == "2.0"
    assert comparison[0]["comparison"]["duration_coverage"] == 1.0
    assert (
        "bottleneck" not in json.dumps(compare_ranges(events, events)).lower()
    )
    assert (
        DualRangeSelection(
            build_range_selection(
                "custom",
                local_start="2026-08-21T01:00:00+00:00",
                local_end="2026-08-21T02:00:00+00:00",
            ),
            build_range_selection(
                "custom",
                local_start="2026-08-21T03:00:00+00:00",
                local_end="2026-08-21T04:00:00+00:00",
            ),
        ).to_dict()["baseline"]["kind"]
        == "custom"
    )


def test_comparison_reports_missing_groups_samples_and_zero_baseline():
    """Comparison preserves structural facts instead of inventing deltas."""
    baseline = [_action_event("one", 1, "2026-08-21T01:00:00Z")]
    comparison = [_action_event("two", 2, "2026-08-21T01:00:01Z")]
    rows = compare_ranges(baseline, comparison, min_samples=2)
    assert rows[0]["comparison_unavailable"] == "insufficient_samples"
    assert rows[0]["absolute_difference_ms"] is None
    missing = compare_ranges(
        baseline,
        [_event("system", 2, "2026-08-21T01:00:01Z")],
        min_samples=1,
    )
    assert any(
        row["comparison_unavailable"] == "missing_group" for row in missing
    )


def test_quality_gate_reports_required_thresholds():
    """Quality gates carry thresholds and never silently pass missing actions."""
    result = evaluate_recording_gate([])
    assert result["quality_gate"] is False
    assert result["metrics"]["required_reference_missing"]["status"] == "pass"
    assert (
        validate_first_stage_configuration({"enabled": False})["gate"] is True
    )
    assert (
        validate_first_stage_configuration({"enabled": False, "upload": True})[
            "gate"
        ]
        is False
    )


def test_streaming_statistics_matches_batch_action_facts():
    """Incremental action rows agree with batch metrics on the fixture."""
    events, _ = read_events(
        [Path("tests/fixtures/behavior_analytics/behavior_analytics_v2.jsonl")]
    )
    streamed = stream_calculate_statistics(events, batch_size=2)
    from anylabeling.services.behavior_analytics import action_metrics

    batch_actions = {
        (row["action"], row["result"], row["count"])
        for row in action_metrics(events)
    }
    stream_actions = {
        (row["action"], row["result"], row["count"])
        for row in streamed["action_metrics"]
    }
    assert stream_actions == batch_actions


def test_stream_benchmark_checks_batch_and_cancel_boundaries():
    """The benchmark reports bounded progress and stops at a batch boundary."""
    result = benchmark_stream(
        generate_events_for_test(100), batch_size=16, cancellation_after=32
    )
    assert result["processed_events"] >= 32
    assert result["processed_events"] <= 48
    assert result["cancelled"] is True


def test_recording_benchmark_and_fixture_contract_are_bounded():
    """First-stage callback and scale fixture APIs expose acceptance facts."""
    result = benchmark_recording_callback(lambda: None, iterations=10)
    assert result["iterations"] == 10
    thresholds = BenchmarkThresholds()
    assert thresholds.max_cancel_batch <= 256
    generated = list(generate_events_for_test(16))
    assert {event.event_type for event in generated} >= {
        "action_span",
        "shape_created",
        "shape_deleted",
    }


def generate_events_for_test(count: int):
    """Keep the benchmark test independent from fixture files."""
    from anylabeling.services.behavior_analytics import generate_events

    return generate_events(count, sessions=2)
