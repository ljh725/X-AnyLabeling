"""End-to-end pure-Python flow for local recording and analysis export."""

import time

from anylabeling.services.behavior_analytics import (
    AnalysisFilter,
    BehaviorTelemetry,
    FeatureState,
    LocalEventRecorder,
    export_analysis_bundle,
    read_events,
)


def test_record_two_objects_and_export_by_project_session(tmp_path):
    """A/B/A recording produces a bounded analysis bundle for one project."""
    recorder = LocalEventRecorder(tmp_path / "logs", enabled=True)
    telemetry = BehaviorTelemetry(str(tmp_path / "project"), recorder)
    telemetry.start_project(
        {"rectangle_refinement": FeatureState(True, True, False)}
    )
    telemetry.enter_image(str(tmp_path / "image.jpg"))
    telemetry.select_shape("shape-a")
    telemetry.action(
        "action_span",
        input_source="mouse",
        result="success",
        payload={"action": "adjust"},
        duration_ms=120,
    )
    telemetry.apply_feature_state(
        {"rectangle_refinement": FeatureState(True, True, True)}
    )
    telemetry.select_shape("shape-b")
    telemetry.select_shape("shape-a")
    telemetry.close_project()
    assert recorder.close(timeout=1.0) is True

    events, quality = read_events([tmp_path / "logs" / "events"])
    project_session_id = next(
        event.project_session_id
        for event in events
        if event.event_type == "project_session_started"
    )
    target = tmp_path / "bundle"
    export_analysis_bundle(
        target,
        events,
        quality=quality,
        event_filter=AnalysisFilter(
            project_session_ids=frozenset({project_session_id})
        ),
    )
    assert (target / "summary.json").exists()
    assert (target / "representative_traces.jsonl").exists()
    export_analysis_bundle(
        tmp_path / "natural-day-bundle",
        events,
        quality=quality,
        event_filter=AnalysisFilter(
            local_dates=frozenset({events[0].local_date})
        ),
    )
    assert (tmp_path / "natural-day-bundle" / "summary.json").exists()


def test_large_statistics_run_stays_within_local_baseline(tmp_path):
    """A thousand in-memory events are analyzed without unbounded work."""
    recorder = LocalEventRecorder(tmp_path / "logs", enabled=True)
    telemetry = BehaviorTelemetry(str(tmp_path / "project"), recorder)
    telemetry.start_project()
    telemetry.enter_image(str(tmp_path / "image.jpg"))
    telemetry.select_shape("shape-a")
    for _ in range(1000):
        telemetry.action(
            "action_span",
            input_source="keyboard",
            result="success",
            payload={"action": "micro_adjust"},
            duration_ms=1,
        )
    telemetry.close_project()
    assert recorder.close(timeout=2.0) is True
    started = time.perf_counter()
    events, quality = read_events([tmp_path / "logs" / "events"])
    export_analysis_bundle(tmp_path / "bundle", events, quality=quality)
    assert time.perf_counter() - started < 2.0


def test_disabled_recorder_does_not_touch_storage(tmp_path):
    """The off mode keeps the UI path free of log directories and I/O."""
    root = tmp_path / "disabled-logs"
    recorder = LocalEventRecorder(root, enabled=False)
    telemetry = BehaviorTelemetry(str(tmp_path / "project"), recorder)
    telemetry.start_project()
    telemetry.shutdown()
    assert not root.exists()
